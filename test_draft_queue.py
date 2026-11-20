import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from unittest.mock import patch

import test_app
from app import Desk, ServiceError, make_handler
from test_tones import response


class DraftQueueTests(unittest.TestCase):
    setUp = test_app.DeskTests.setUp
    transport = test_app.DeskTests.transport
    add_post = test_app.DeskTests.add_post

    def other_post(self):
        self.desk.execute("INSERT INTO posts(id,handle,text,created_at,source_json) VALUES ('102','person','Another post','2026-11-20T12:01:00Z',?)", (json.dumps({'data':{'id':'102','text':'Another post'}}),))

    def test_monitor_lock_does_not_block_http_queue_or_generation(self):
        self.add_post()
        server = ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.desk))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.responses = [response()]
        with self.desk.work_lock:
            req = Request(f'http://127.0.0.1:{server.server_port}/api/draft',data=json.dumps({'id':'101','tone':'disagree'}).encode(),headers={'Content-Type':'application/json','X-Desk-Token':self.desk.csrf})
            with urlopen(req,timeout=2) as result:
                self.assertEqual(result.status,202)
                self.assertTrue(json.load(result)['queued'])
            self.assertTrue(self.desk.snapshot()['busy'])
            self.assertEqual(self.desk.snapshot()['posts'][0]['draft_job'],'queued')
            self.assertTrue(self.desk.draft_once())
        self.assertEqual(self.desk.snapshot()['posts'][0]['draft_tone'],'disagree')
        self.assertIsNone(self.desk.snapshot()['posts'][0]['draft_job'])

    def test_slow_draft_does_not_stop_monitor_and_other_posts_can_queue(self):
        self.add_post()
        self.other_post()
        started, release = threading.Event(), threading.Event()
        def slow(url,token,body=None):
            started.set()
            if not release.wait(3):
                raise RuntimeError('Test did not release draft')
            return response()
        self.desk.transport=slow
        self.desk.queue_draft('101','provocative')
        worker=threading.Thread(target=self.desk.draft_once)
        worker.start()
        self.addCleanup(lambda: (release.set(),worker.join(3)))
        self.assertTrue(started.wait(2))
        self.assertFalse(self.desk.work_lock.locked())
        self.assertEqual(self.desk.queue_draft('102','agreeable')['state'],'queued')
        self.assertFalse(self.desk.draft_once())
        with patch.object(self.desk,'poll_activity') as polling:
            self.desk.check_once()
            polling.assert_called_once()
        states={p['id']:p['draft_job'] for p in self.desk.snapshot()['posts']}
        self.assertEqual(states,{'101':'writing','102':'queued'})
        release.set(); worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertTrue(self.desk.draft_once())
        self.assertEqual(self.desk.rows('SELECT * FROM draft_jobs'),[])

    def test_duplicate_clicks_do_not_create_duplicate_ai_attempts(self):
        self.add_post()
        self.desk.queue_draft('101','disagree')
        self.desk.queue_draft('101','disagree')
        self.assertEqual(len(self.desk.rows('SELECT * FROM draft_jobs')),1)
        self.responses=[response()]
        self.desk.draft_once()
        self.assertFalse(self.desk.draft_once())
        self.assertEqual(self.desk.usage()['draft_attempts'],1)

    def test_manual_rewrite_takes_priority_over_waiting_automatic_draft(self):
        self.add_post(); self.other_post()
        self.desk.save_settings({'enabled':True})
        self.desk.queue_draft('101',manual=False)
        self.desk.queue_draft('102','provocative')
        self.responses=[response()]
        self.desk.draft_once()
        self.assertEqual(self.desk.rows("SELECT draft_tone FROM posts WHERE id='102'")[0]['draft_tone'],'provocative')
        self.assertEqual(self.desk.rows('SELECT post_id FROM draft_jobs')[0]['post_id'],'101')

    def test_manual_angle_replaces_a_not_yet_started_automatic_request(self):
        self.add_post()
        self.desk.queue_draft('101',manual=False)
        result=self.desk.queue_draft('101','controversial')
        self.assertEqual(result['tone'],'controversial')
        job=self.desk.rows('SELECT * FROM draft_jobs')[0]
        self.assertTrue(job['manual'])
        self.assertEqual(job['tone'],'controversial')

    def test_edit_while_queued_is_kept_without_spending_ai(self):
        self.add_post()
        self.desk.queue_draft('101','disagree')
        self.desk.execute("UPDATE posts SET reply='A newer edit'")
        self.desk.draft_once()
        post=self.desk.snapshot()['posts'][0]
        self.assertEqual(post['reply'],'A newer edit')
        self.assertIn('while it was queued',post['error'])
        self.assertEqual(self.requests,[])
        self.assertIsNone(post['draft_job'])

    def test_worker_releases_failed_job_and_continues(self):
        self.add_post(); self.other_post()
        self.desk.queue_draft('101'); self.desk.queue_draft('102')
        self.responses=[ServiceError('AI unavailable'),response()]
        self.desk.draft_once(); self.desk.draft_once()
        posts={p['id']:p for p in self.desk.snapshot()['posts']}
        self.assertEqual(posts['101']['error'],'AI unavailable')
        self.assertEqual(posts['102']['status'],'ready')
        self.assertEqual(self.desk.rows('SELECT * FROM draft_jobs'),[])

    def test_restart_keeps_waiting_jobs_but_does_not_repeat_interrupted_ai(self):
        self.add_post(); self.other_post()
        self.desk.queue_draft('101'); self.desk.queue_draft('102')
        self.desk.execute("UPDATE draft_jobs SET state='writing' WHERE post_id='101'")
        reopened=Desk(self.desk.directory,self.desk.env_path,self.transport)
        self.addCleanup(reopened.db.close)
        posts={p['id']:p for p in reopened.snapshot()['posts']}
        self.assertIsNone(posts['101']['draft_job'])
        self.assertIn('interrupted',posts['101']['error'])
        self.assertEqual(posts['102']['draft_job'],'queued')

    def test_automatic_draft_is_skipped_if_replied_before_it_starts(self):
        self.add_post()
        self.desk.save_settings({'enabled':True})
        self.desk.queue_draft('101',manual=False)
        self.desk.execute("UPDATE posts SET replied_at='2026-11-20T12:00:00Z'")
        self.desk.draft_once()
        self.assertEqual(self.requests,[])
        self.assertIsNone(self.desk.snapshot()['posts'][0]['draft_job'])

    def test_background_worker_processes_queued_job_and_stops_cleanly(self):
        self.add_post()
        finished=threading.Event()
        original=self.desk.draft_once
        def observe():
            result=original()
            if result:
                finished.set()
            return result
        self.desk.draft_once=observe
        self.responses=[response()]
        self.desk.queue_draft('101','disagree')
        worker=threading.Thread(target=self.desk.run_drafts)
        worker.start()
        def stop():
            self.desk.stop.set()
            self.desk.draft_wake.set()
            worker.join(3)
        self.addCleanup(stop)
        self.assertTrue(finished.wait(2))
        self.assertEqual(self.desk.snapshot()['posts'][0]['draft_tone'],'disagree')
        stop()
        self.assertFalse(worker.is_alive())


if __name__ == '__main__':
    unittest.main()
