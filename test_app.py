import json
import base64
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from app import Desk, ServiceError, make_handler, request_json


class DeskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.responses = []
        self.requests = []
        self.desk = Desk(Path(self.temp.name) / "data", Path(self.temp.name) / ".env", self.transport)
        self.addCleanup(self.desk.db.close)
        self.desk.keys = {"X_BEARER_TOKEN": "test-x", "OPENAI_API_KEY": "test-ai"}

    def transport(self, url, token, body=None):
        self.requests.append((url, token, body))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def account(self):
        return self.desk.rows("SELECT * FROM accounts")[0]

    def add_account(self):
        self.desk.add_account("@test_account")
        self.desk.execute("UPDATE accounts SET user_id='123',latest_seeded=1")

    def add_post(self):
        self.desk.execute("INSERT INTO posts(id,handle,text,created_at) VALUES ('101','test_account','A useful observation.','2026-11-19T12:00:00Z')")

        self.desk.execute("UPDATE posts SET source_json=? WHERE id='101'", (json.dumps({"data":{"id":"101","text":"A useful observation."}}),))

    def test_pagination_keeps_cursor_until_all_pages_and_deduplicates(self):
        self.add_account()
        self.responses = [
            {"data": [{"id": "105", "text": "Newest"}], "meta": {"next_token": "page2"}},
            {"data": [{"id": "104", "text": "Older"}, {"id": "105", "text": "Newest"}], "meta": {}},
            {"data": [{"id": "106", "text": "Next poll"}], "meta": {}}]
        self.desk.poll_account(self.account())
        self.assertIsNone(self.account()["since_id"])
        self.assertEqual(self.account()["newest_id"], "105")
        self.desk.poll_account(self.account())
        self.assertEqual(self.account()["since_id"], "105")
        self.assertEqual(len(self.desk.rows("SELECT * FROM posts")), 2)
        self.desk.poll_account(self.account())
        self.assertEqual(self.account()["since_id"], "106")
        second = parse_qs(urlparse(self.requests[1][0]).query)
        third = parse_qs(urlparse(self.requests[2][0]).query)
        self.assertEqual(second["pagination_token"], ["page2"])
        self.assertEqual(third["since_id"], ["105"])
        self.assertEqual(third["post.fields"], ["created_at"])
        self.assertNotIn("start_time", third)

    def test_first_poll_starts_when_account_added_and_empty_results_are_valid(self):
        self.add_account()
        self.responses = [{"meta": {"result_count": 0}}]
        self.desk.poll_account(self.account())
        params = parse_qs(urlparse(self.requests[0][0]).query)
        self.assertEqual(params["start_time"], [self.account()["start_time"]])
        self.assertEqual(self.desk.usage()["read_slots"], 0)

    def test_latest_post_backfill_ignores_watch_date_and_keeps_only_newest(self):
        self.add_account()
        self.desk.execute("UPDATE accounts SET latest_seeded=0")
        self.responses = [{"data":[{"id":"104","text":"Older"},{"id":"105","text":"Latest"}],"meta":{"next_token":"older-page"}}]
        self.desk.poll_account(self.account())
        params = parse_qs(urlparse(self.requests[0][0]).query)
        self.assertNotIn("start_time", params)
        self.assertNotIn("since_id", params)
        self.assertEqual(params["max_results"], ["5"])
        self.assertEqual([p["id"] for p in self.desk.snapshot()["posts"]], ["105"])
        self.assertEqual(self.account()["since_id"], "105")
        self.assertIsNone(self.account()["next_token"])
        self.assertEqual(self.desk.usage()["posts_read"], 2)
        self.responses = [{"meta":{}}]
        self.desk.poll_account(self.account())
        self.assertEqual(parse_qs(urlparse(self.requests[-1][0]).query)["since_id"], ["105"])

    def test_latest_backfill_preserves_existing_reply_and_pagination(self):
        self.add_account()
        self.add_post()
        self.desk.execute("UPDATE posts SET reply='My saved reply',replied_at='2026-11-20T10:00:00Z'")
        self.desk.execute("UPDATE accounts SET latest_seeded=0,since_id='90',next_token='pending',newest_id='100'")
        self.responses = [{"data":[{"id":"101","text":"A useful observation."}]}]
        self.desk.poll_account(self.account())
        account = self.account()
        self.assertEqual((account["since_id"],account["next_token"],account["newest_id"]), ("90","pending","100"))
        post = self.desk.snapshot()["posts"][0]
        self.assertEqual(post["reply"], "My saved reply")
        self.assertTrue(post["replied_at"])

    def test_failed_latest_lookup_remains_retryable(self):
        self.add_account()
        self.desk.execute("UPDATE accounts SET latest_seeded=0")
        self.responses = [ServiceError("Unavailable")]
        self.desk.poll_account(self.account())
        self.assertEqual(self.account()["latest_seeded"], 0)
        self.assertEqual(self.desk.usage()["read_slots"], 5)

    def test_failure_does_not_advance_cursor_and_reserves_uncertain_cost(self):
        self.add_account()
        self.desk.execute("UPDATE accounts SET since_id='100',next_token='next',newest_id='105'")
        self.responses = [ServiceError("rate limited", 9999999999)]
        self.desk.poll_account(self.account())
        self.assertEqual(self.account()["since_id"], "100")
        self.assertEqual(self.account()["next_token"], "next")
        self.assertEqual(self.account()["retry_at"], 9999999999)
        self.assertEqual(self.desk.usage()["read_slots"], 100)
        self.assertEqual(self.desk.usage()["posts_read"], 0)

    def test_read_allowance_limits_request_size_and_stops_at_limit(self):
        self.add_account()
        self.desk.save_settings({"daily_reads": 5})
        self.responses = [{"data": [{"id": str(n), "text": "Post"} for n in range(100,105)]}]
        self.desk.poll_account(self.account())
        self.desk.poll_account(self.account())
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(parse_qs(urlparse(self.requests[0][0]).query)["max_results"], ["5"])

    def test_partial_api_error_is_rejected(self):
        from io import BytesIO
        with patch("app.urlopen", return_value=BytesIO(json.dumps({"data":[{"id":"1"}],"errors":[{"detail":"private"}]}).encode())):
            with self.assertRaises(ServiceError):
                request_json("https://api.x.com/2/test", "key")

    def test_draft_generation_and_attempt_cap(self):
        self.add_post()
        self.desk.save_settings({"daily_drafts": 1})
        draft = {"reply":"A specific question?", "repurpose":"An original observation.", "skip":False, "reason":"Review before publishing."}
        self.responses = [{"status":"completed", "output":[{"type":"message", "content":[{"type":"output_text", "text":json.dumps(draft)}]}]}]
        self.desk.generate("101")
        post = self.desk.rows("SELECT * FROM posts")[0]
        self.assertEqual(post["reply"], draft["reply"])
        self.assertEqual(post["status"], "ready")
        self.assertFalse(self.requests[0][2]["store"])
        with self.assertRaisesRegex(ValueError, "allowance"):
            self.desk.generate("101")

    def test_incomplete_draft_keeps_previous_work_and_counts_attempt(self):
        self.add_post()
        self.desk.execute("UPDATE posts SET reply='Keep my work'")
        self.responses = [{"status":"incomplete", "output":[]}]
        with self.assertRaises(ServiceError):
            self.desk.generate("101")
        self.assertEqual(self.desk.rows("SELECT * FROM posts")[0]["reply"], "Keep my work")
        self.assertEqual(self.desk.usage()["draft_attempts"], 1)

    def test_demo_is_idempotent_and_never_uses_ai(self):
        self.desk.demo(); self.desk.demo()
        self.assertEqual(len(self.desk.snapshot()["posts"]), 2)
        with self.assertRaisesRegex(ValueError, "Demo"):
            self.desk.generate("demo-1")
        self.assertEqual(self.requests, [])

    def test_settings_and_handles_validate_before_writing(self):
        with self.assertRaises(ValueError):
            self.desk.save_settings({"interval": 1})
        with self.assertRaises(ValueError):
            self.desk.add_account("../bad")
        self.desk.keys = {}
        with self.assertRaises(ValueError):
            self.desk.save_settings({"enabled": True})
        self.assertFalse(self.desk.settings()["enabled"])

    def test_credentials_are_private_and_not_returned(self):
        self.desk.save_keys({"X_BEARER_TOKEN": "private-token"})
        self.assertEqual(self.desk.env_path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("private-token", json.dumps(self.desk.snapshot()))
        with self.assertRaises(ValueError):
            self.desk.save_keys({"X_BEARER_TOKEN": "token\nINJECT=value"})

    def test_http_blocks_cross_origin_writes_and_secret_paths(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.desk))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with urlopen(base + "/api/state") as response:
            state = json.load(response)
        for headers in ({}, {"X-Desk-Token":state["csrf"],"Origin":"https://other.example"}):
            with self.assertRaises(HTTPError) as caught:
                urlopen(Request(base + "/api/demo", data=b"{}", headers={"Content-Type":"application/json", **headers}))
            self.assertEqual(caught.exception.code, 403)
            caught.exception.close()
        with urlopen(Request(base + "/api/demo", data=b"{}", headers={"Content-Type":"application/json", "X-Desk-Token":state["csrf"]})) as response:
            self.assertEqual(response.status, 200)
        self.add_post()
        headers = {"Content-Type":"application/json", "X-Desk-Token":state["csrf"]}
        for body in ({"id":"101","replied":True}, {"id":"101","reply":"Edited after sending","repurpose":"A take"}):
            with urlopen(Request(base + "/api/posts", data=json.dumps(body).encode(), headers=headers)) as response:
                self.assertEqual(response.status, 200)
        self.assertTrue(self.desk.rows("SELECT replied_at FROM posts WHERE id='101'")[0]["replied_at"])
        with urlopen(Request(base + "/api/posts", data=b'{"id":"101","replied":false}', headers=headers)) as response:
            self.assertEqual(response.status, 200)
        self.assertIsNone(self.desk.rows("SELECT replied_at FROM posts WHERE id='101'")[0]["replied_at"])
        for path in ("/.env", "/../app.py", "/data/desk.sqlite3"):
            with self.assertRaises(HTTPError) as caught:
                urlopen(base + path)
            self.assertEqual(caught.exception.code, 404)
            caught.exception.close()

    def test_tunnel_requires_login_even_with_spoofed_localhost(self):
        config = self.desk.directory / "tunnel.json"
        config.write_text(json.dumps({"origin":"https://desk.example", "username":"desk", "password":"test-secret"}))
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.desk))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_address[1]}"
        for path in ("/", "/api/state", "/sw.js"):
            with self.assertRaises(HTTPError) as caught:
                urlopen(base + path)
            self.assertEqual(caught.exception.code, 401)
            caught.exception.close()
        auth = "Basic " + base64.b64encode(b"desk:test-secret").decode()
        with urlopen(Request(base + "/api/state", headers={"Authorization":auth,"Host":"desk.example"})) as response:
            state = json.load(response)
        self.assertNotIn("test-secret", json.dumps(state))
        headers = {"Authorization":auth,"Host":"desk.example","Origin":"https://evil.example", "X-Desk-Token":state["csrf"],"Content-Type":"application/json"}
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(base + "/api/settings", data=b"{}", headers=headers))
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()
        headers["Origin"] = "https://desk.example"
        with urlopen(Request(base + "/api/settings", data=b"{}", headers=headers)) as response:
            self.assertEqual(response.status, 200)


if __name__ == "__main__":
    unittest.main()
