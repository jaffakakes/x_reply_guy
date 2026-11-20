# x_reply_guy

X Draft Desk is a single-page black web app for watching X accounts, writing reply/commentary drafts, and getting 33 daily posting reminders.

## Run on your Mac

Requires Python 3.11+. No Python packages to install. Video context also requires FFmpeg/ffprobe (on macOS, use `brew install ffmpeg`).

1. Double-click `Start Draft Desk.command` (or run `python3 app.py`).
2. Open http://127.0.0.1:8765.
3. For remote access, double-click `Start Ngrok.command` (or run `python3 tunnel.py`). Ngrok must be installed and configured with your account.
4. Open the HTTPS URL printed by the tunnel. Sign in with the credentials in `data/ngrok-login.txt`. The same login protects localhost while the tunnel is active. Keep this file private.

Keep both processes running and your Mac awake. Ctrl+C stops each process. Monitoring preferences survive restarts. Restarting the tunnel can change its URL; its login stays the same. The tunnel uses app-level Basic authentication over HTTPS, exact Host/Origin checks and CSRF protection. API keys and drafts are never served as files. Ngrok request inspection is disabled. Do not expose the server through another tunnel or port-forwarding configuration.

## Use

- The top bar holds your watchlist. Click **+**, search an exact **@username**, confirm the profile photo/name/bio, then **Watch**. Search also offers a link to the full X profile. Photos fall back to initials if unavailable. Up to 20 accounts are supported. This does not follow them on X.
- When you add an account, monitoring first fetches its latest existing original post, then checks new posts. Existing watched accounts receive the same one-time latest-post lookup on upgrade. Replies/reposts are excluded. The empty inbox says **Monitoring posts…** while monitoring is healthy.
- Review and edit **Reply** or **Your take**, then open the X composer to publish yourself. Replies aim for one short, conversational reaction (usually 5–18 words), with an actual opinion or angle rather than a summary of the source. Context analysis stays behind the scenes. Your custom writing voice still applies. Commentary includes the source URL. After publishing a reply, click **Mark replied** to remove its source post from the reply queue. This is a local acknowledgement; the app cannot detect replies sent directly on X. **Replied & archived** in settings lets you view completed posts and undo the reply mark. Saving or regenerating a draft does not undo that mark. Archive other finished drafts. No sample posts appear in the interface.
- Open settings with the sliders icon. Save X/OpenAI credentials there, never in chat. Keys live in an owner-readable `.env`; environment variables override it at startup. Saved credentials are verified when their provider is first used.

## Browser reminders

Click the bell and **Allow** browser notifications. Permission is specific to each browser and URL. The app schedules **33 reminders from 10:00 through 00:00, Europe/London**, 26 or 27 minutes apart; daylight-saving changes are handled automatically. Midnight is reminder 33 of the preceding posting day. The complete schedule is in settings.

Keep the page open and the Mac awake. Background tabs may be throttled and browser/OS Focus settings can suppress notifications; timing is best-effort. There is no push service for a closed page. Monitoring continues with the server even if the page is closed, but browser reminders do not. Only the latest reminder within five minutes is eligible after reconnecting; missed reminders are not replayed. A database claim prevents duplicate notifications across tabs/devices. “I've posted” records your acknowledgement, not confirmation from X. You can pause reminders separately from monitoring.

## Costs and limits

Polling defaults to 60 seconds per account; rate limits, pagination and AI generation can add delay. API access/billing are separate. New installations default to 500 possible post reads and 40 AI draft attempts per UTC day; existing settings are preserved. Each AI attempt generates both drafts. Failed/uncertain reads retain reserved slots conservatively. Account lookups are separate X charges. These safeguards are not dollar spending caps; use provider billing limits.

Draft generation sends source text, quoted/referenced posts, downloaded X images, timestamped video frames, audio transcripts, and readable linked-page excerpts to OpenAI with response storage disabled. Photos and video frames are passed as actual vision inputs. Spoken audio is sent separately to OpenAI’s `gpt-transcribe` transcription API; successful transcripts are cached locally by audio content so regeneration avoids another transcription charge. Additional post lookups count toward the read allowance; image/frame inputs, audio transcription and longer context can increase AI charges. Audio attempts have a separate daily limit equal to the configured daily draft allowance, displayed in settings; failed attempts still count. Failed drafts await manual retry. The inbox shows the newest 300 posts; older records remain in SQLite. Timeline cursors and duplicate prevention persist. Long offline gaps are subject to X retention/access limits. Review facts and attribution before publishing. Each draft reads up to four source/referenced posts, eight photos, two native X videos/GIFs and three public HTML/text pages (12,000 characters per page). Long-post text is included when X supplies it. For each native X video/GIF, it downloads an MP4 of at most 80 MB and five minutes, samples up to 24 timestamped frames across the full clip, and transcribes its full audio track when present. Clips exceeding these limits are flagged, not silently truncated. Sampling can miss rapid action; transcripts can mishear speech and do not capture tone or non-speech sounds reliably. The model is instructed to skip if those missing details are essential. Temporary media files are deleted after analysis. External video sites, live streams and unavailable MP4 variants need manual review. It does not read PDFs, log into websites, or bypass paywalls; it does not promise the whole thread. Missing source or direct-reference context stops new AI drafting and retains any existing draft for manual editing. Limits or failures on older quoted background are shown as warnings; drafting can proceed from the context actually read unless the missing detail is essential. Combined image and video-frame inputs are limited to 32 million encoded characters. Empty drafts show the specific pause, failure, skip or queue reason. Unreadable images or page challenges should be skipped by the model. The context note shows what was supplied and what is missing. Edit/save manually after checking the source, or retry generation. Media decoding disables network access and external track references. Public-page fetching blocks private network addresses, pins validated DNS addresses, validates redirects, and sends no app credentials or browser cookies. Publication and following remain manual.

## Verification

```sh
python3 -m unittest -v
node --test test_frontend.cjs
node --check static/app.js
```

Tests cover timeline recovery, usage allowances, draft failures, secret handling, authenticated tunnel access, CSRF/Origin checks, reminder spacing/midnight/DST, duplicate claims, account lookup caching and edit preservation. Tests use temporary databases and mocked provider calls. Desktop/mobile empty layouts, account-search interaction and schedule display were checked. Public tunnel access was checked for unauthenticated rejection and authenticated success. Actual OS notification delivery and publishing in X have not been verified.

Implementation references: [X post lookup](https://docs.x.com/x-api/posts/get-post-by-id), [OpenAI image inputs](https://developers.openai.com/api/docs/guides/images-vision).

Video implementation reference: [OpenAI file transcription](https://developers.openai.com/api/docs/guides/speech-to-text).
