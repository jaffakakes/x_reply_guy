"""Bounded, public-only source reading for drafting. No browser cookies or API keys."""
import base64
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from html.parser import HTMLParser
from html import unescape
from urllib.parse import urlparse, urljoin

MAX_VISUAL_CHARS = 32_000_000

POST_PARAMS = {"post.fields": "created_at,entities,attachments,note_post", "expansions": "attachments.media_keys,referenced_posts", "media.fields": "url,preview_image_url,type,alt_text,variants,duration_ms"}


def image_url(value):
    try:
        p = urlparse(value or "")
        return value if p.scheme == "https" and p.hostname == "pbs.twimg.com" and p.port in (None,443) and not p.username else ""
    except ValueError:
        return ""


def public_address(url):
    p = urlparse(url)
    if p.scheme not in ("https", "http") or not p.hostname or p.username or p.password or p.port not in (None, 80 if p.scheme == "http" else 443):
        raise ValueError("Only public web pages can be read.")
    addresses = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Private network links cannot be read.")
    return p, addresses[0]


def fetch_public(url, limit=1_000_000, timeout=20, allowed_hosts=None):
    # Pin the validated address for this connection; revalidate every redirect.
    deadline = time.monotonic() + timeout
    for _ in range(5):
        if allowed_hosts and urlparse(url).hostname not in allowed_hosts:
            raise ValueError("Media redirected away from its trusted host.")
        p, address = public_address(url)
        connection = http.client.HTTPConnection(p.hostname, timeout=8)
        sock = socket.socket(address[0], address[1], address[2])
        sock.settimeout(8)
        try:
            sock.connect(address[4])
            if p.scheme == "https":
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=p.hostname)
            connection.sock = sock
            connection.request("GET", (p.path or "/") + (("?" + p.query) if p.query else ""), headers={"User-Agent":"DraftDesk/1.0", "Accept-Encoding":"identity", "Accept":"text/html,text/plain,image/jpeg,image/png,image/webp"})
            response = connection.getresponse()
            if response.status in (301,302,303,307,308):
                destination = response.getheader("Location")
                if not destination:
                    raise ValueError("Link redirect had no destination.")
                url = urljoin(url, destination)
                continue
            if response.status != 200:
                raise ValueError("Page unavailable or requires access.")
            chunks, size = [], 0
            while size <= limit:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError("Source reading timed out.")
                sock.settimeout(min(8, remaining))
                chunk = response.read1(min(65536, limit + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            data = b"".join(chunks)
            if len(data) > limit:
                raise ValueError("Source exceeds the reading limit.")
            return url, response.getheader("Content-Type", "").split(";")[0].lower(), data
        finally:
            connection.close()
            sock.close()
    raise ValueError("Too many link redirects.")


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored = []
        self.text = []
        self.article = []
        self.article_depth = 0
        self.title = []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg", "nav", "footer", "header", "form"):
            self.ignored.append(tag)
        if tag in ("article", "main"):
            self.article_depth += 1
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag in self.ignored:
            self.ignored.remove(tag)
        if tag in ("article", "main"):
            self.article_depth = max(0, self.article_depth - 1)
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.ignored:
            return
        value = " ".join(data.split())
        if value:
            self.text.append(value)
            if self.article_depth:
                self.article.append(value)
            if self.in_title:
                self.title.append(value)


def read_page(url):
    final, kind, data = fetch_public(url)
    if kind not in ("text/html", "application/xhtml+xml", "text/plain"):
        raise ValueError("This link is not a readable web page.")
    text = data.decode("utf-8", errors="replace")
    parser = PageText()
    if kind != "text/plain":
        parser.feed(text)
        text = " ".join(parser.article or parser.text)
    if len(text.strip()) < 100:
        raise ValueError("Page has too little readable text; it may need login or JavaScript.")
    # shortcut: HTML excerpts only; add a document reader if PDF or JS-only pages become necessary.
    return {"url": final, "title": " ".join(parser.title)[:300], "excerpt": text[:12000], "truncated": len(text) > 12000}


def read_image(url):
    if not image_url(url):
        raise ValueError("Image is not available from X's image host.")
    final, kind, data = fetch_public(url, 8_000_000)
    if not image_url(final) or kind not in ("image/jpeg", "image/png", "image/webp"):
        raise ValueError("Image format or location is unsupported.")
    return "data:" + kind + ";base64," + base64.b64encode(data).decode()


def post_text(post):
    return unescape((post.get("note_post") or post.get("note_tweet") or {}).get("text") or post.get("text", ""))


def x_post_id(url):
    p = urlparse(url)
    if p.hostname in ("x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"):
        match = re.search(r"/(?:status|statuses)/(\d+)", p.path)
        return match[1] if match else None
    return None


def build_context(root, lookup, page_reader=read_page, image_reader=read_image, video_reader=None):
    """Prioritize the source and direct references; bound older background context."""
    sources, pages, images, missing, warnings = [], [], [], [], []
    packets = {str(root["data"]["id"]): root}
    queue = [(root["data"], root.get("includes", {}), "source", 0)]
    visited, links_seen, images_seen = set(), set(), set()
    videos_seen = set()
    photo_count = 0

    def enqueue(pid, relation, includes, depth):
        issues = missing if depth <= 1 else warnings
        if pid in visited or any(str(p[0]["id"]) == pid for p in queue):
            return
        if len(visited) + len(queue) >= 4:
            issues.append("Additional referenced posts exceed the context limit.")
            return
        included = next((p for p in includes.get("posts", includes.get("tweets", [])) if str(p.get("id")) == pid), None)
        try:
            # Included text often lacks its media expansion. Hydrate attachments when needed.
            media_keys = {m.get("media_key") for m in includes.get("media", [])}
            needed = set((included or {}).get("attachments", {}).get("media_keys", []))
            stale_video = any(m.get("media_key") in needed and m.get("type") in ("video", "animated_gif") and not m.get("variants") for m in includes.get("media", []))
            if included and needed.issubset(media_keys) and not stale_video:
                queue.append((included, includes, relation, depth))
            else:
                if pid not in packets:
                    packets[pid] = lookup(pid)
                packet = packets[pid]
                queue.append((packet["data"], packet.get("includes", {}), relation, depth))
        except (ValueError, OSError, RuntimeError):
            issues.append(f"Referenced post {pid} could not be read.")

    while queue:
        post, includes, relation, depth = queue.pop(0)
        issues = missing if depth <= 1 else warnings
        pid = str(post["id"])
        if pid in visited:
            continue
        visited.add(pid)
        source = {"id": pid, "relation": relation, "reference_depth": depth, "text": post_text(post), "images": [], "videos": []}
        sources.append(source)
        for ref in post.get("referenced_posts", post.get("referenced_tweets", [])):
            enqueue(str(ref["id"]), ref.get("type", "referenced"), includes, depth + 1)
        for key in post.get("attachments", {}).get("media_keys", []):
            media = next((m for m in includes.get("media", []) if m.get("media_key") == key), None)
            if not media:
                issues.append(f"An image or attachment on post {pid} is unavailable.")
                continue
            if media.get("type") in ("video", "animated_gif"):
                if key in videos_seen:
                    continue
                if len(videos_seen) >= 2 or video_reader is None:
                    issues.append(f"Video on post {pid} was not read: video reader unavailable or two-video limit reached.")
                    continue
                videos_seen.add(key)
                try:
                    video, frames = video_reader(media)
                    if sum(len(i["image_url"]) for i in images) + sum(len(f["image_url"]) for f in frames) > MAX_VISUAL_CHARS:
                        raise ValueError("Video frames exceed the context size limit.")
                    for frame in frames:
                        images.append({"type":"input_image", "image_url":frame["image_url"], "detail":"high"})
                        frame["image_number"] = len(images)
                    source["videos"].append({**video, "frames":[{"image_number":f["image_number"], "seconds":f["seconds"]} for f in frames]})
                except (ValueError, OSError, RuntimeError, http.client.HTTPException) as exc:
                    issues.append(f"Video on post {pid} could not be read: {exc}")
                continue
            if media.get("type") != "photo":
                issues.append(f"Unsupported attachment on post {pid}.")
                continue
            url = media.get("url", "")
            if url in images_seen:
                continue
            if photo_count >= 8:
                issues.append("Additional images exceed the context limit.")
                continue
            images_seen.add(url)
            try:
                data = image_reader(url)
                if sum(len(i["image_url"]) for i in images) + len(data) > MAX_VISUAL_CHARS:
                    issues.append(f"Image on post {pid} exceeds the context size limit.")
                    continue
                images.append({"type": "input_image", "image_url": data, "detail": "high"})
                photo_count += 1
                source["images"].append({"image_number": len(images), "alt_text": media.get("alt_text", ""), "url": url})
            except (ValueError, OSError, http.client.HTTPException):
                issues.append(f"An image on post {pid} could not be read.")
        note = post.get("note_post") or post.get("note_tweet") or {}
        urls = post.get("entities", {}).get("urls", []) + note.get("entities", {}).get("urls", [])
        if not urls:
            urls = [{"url": u} for u in re.findall(r"https?://[^\s<>]+", source["text"])]
        for entity in urls:
            url = entity.get("unwound_url") or entity.get("expanded_url") or entity.get("url", "")
            if not url or url in links_seen:
                continue
            links_seen.add(url)
            linked_id = x_post_id(url)
            if linked_id:
                # Media permalinks point back to the source, not to a web article.
                if linked_id != pid:
                    enqueue(linked_id, "linked_post", includes, depth + 1)
                continue
            if entity.get("media_key"):
                continue
            if len(pages) >= 3:
                issues.append("Additional links exceed the context limit.")
                continue
            try:
                page = page_reader(url)
                pages.append({"source_post": pid, **page})
            except (ValueError, OSError, http.client.HTTPException):
                pages.append({"source_post": pid, "url": url, "unavailable": True})
                issues.append(f"Linked page could not be read: {url}")
    return {"posts": sources, "linked_pages": pages, "missing_context": list(dict.fromkeys(missing)), "background_warnings": list(dict.fromkeys(warnings))}, images
