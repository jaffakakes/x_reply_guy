"""Run a password-protected ngrok tunnel for the local Draft Desk."""
import json
import base64
import fcntl
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def private_write(path, text):
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(text)
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def main():
    DATA.mkdir(exist_ok=True, mode=0o700)
    lock = (DATA / "ngrok.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("The Draft Desk tunnel is already running.", flush=True)
        return 1
    try:
        headers = {}
        active = DATA / "tunnel.json"
        if active.exists():
            old = json.loads(active.read_text())
            headers["Authorization"] = "Basic " + base64.b64encode((old["username"] + ":" + old["password"]).encode()).decode()
        with urlopen(Request("http://127.0.0.1:8765/api/state", headers=headers), timeout=3) as response:
            json.load(response)
    except Exception:
        print("Start Draft Desk first: python3 app.py", flush=True)
        return 1
    access_path = DATA / "ngrok-access.json"
    if access_path.exists():
        access = json.loads(access_path.read_text())
    else:
        access = {"username": "desk", "password": secrets.token_urlsafe(24)}
        private_write(access_path, json.dumps(access))
    # Draft Desk enforces Basic Auth itself, so no paid ngrok traffic policy is needed.
    private_write(DATA / "ngrok-login.txt", f"Draft Desk ngrok login\n\nUsername: {access['username']}\nPassword: {access['password']}\n\nKeep this file private. Only use this login on your Draft Desk ngrok URL.\n")
    private_write(active, json.dumps({"origin": "", "username": access["username"], "password": access["password"]}))
    try:
        process = subprocess.Popen(["ngrok", "http", "http://127.0.0.1:8765",
                                    "--inspect=false", "--log", "stdout", "--log-format", "json"],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except FileNotFoundError:
        active.unlink(missing_ok=True)
        print("ngrok is not installed. Install it from ngrok.com first.", flush=True)
        return 1
    print("Starting password-protected ngrok tunnel…", flush=True)
    try:
        for line in process.stdout:
            try:
                record = json.loads(line)
            except ValueError:
                # Only surface error codes, never raw logs which may contain secrets.
                codes = re.findall(r"ERR_NGROK_\d+", line)
                if codes:
                    print("ngrok could not start: " + ", ".join(codes), flush=True)
                continue
            url = record.get("url", "")
            parsed = urlparse(url)
            if record.get("msg") == "started tunnel" and parsed.scheme == "https" and parsed.netloc:
                private_write(DATA / "tunnel.json", json.dumps({"origin": url.rstrip("/"), "username": access["username"], "password": access["password"]}))
                print("Draft Desk: " + url, flush=True)
                print("Login details: " + str(DATA / "ngrok-login.txt"), flush=True)
                print("Keep this process and Draft Desk running. Ctrl+C stops the tunnel.", flush=True)
            elif record.get("lvl") in ("eror", "error", "crit"):
                codes = re.findall(r"ERR_NGROK_\d+", str(record.get("err", "")))
                print("ngrok could not connect" + (": " + ", ".join(codes) if codes else ". Check your ngrok account and configuration."), flush=True)
        return process.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        (DATA / "tunnel.json").unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
