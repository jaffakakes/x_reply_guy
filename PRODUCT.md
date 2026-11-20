# X Draft Desk

<!-- impeccable:product-schema 1 -->

## Platform
web

## Stack
Python standard-library server, SQLite, plain HTML/CSS/JavaScript. Single-user app on the owner's Mac, optionally reached through an authenticated ngrok HTTPS tunnel.

## Users
The owner monitors selected X accounts, writes replies and credited commentary, and wants 33 daily reminders to post.

## Product Purpose
Turn new posts into editable drafts and support a regular posting schedule. Final publication happens in X's composer; opening it does not establish publication.

## Capabilities and Constraints
Official X API polling with a one-time latest-existing-post lookup per account, persistent watchlist and inbox, OpenAI drafts grounded in quoted posts, actual photo inputs, sampled native X video frames with speech transcripts, and public linked-page excerpts, photo/name/bio account search, editable text, manual reply-completion tracking and archive, and 33 browser posting reminders between 10:00 and 00:00 Europe/London. Browser notifications require permission and an open page; the Mac and server must remain awake/running. No cloud hosting or closed-page push. Ngrok runs only while the Mac is running and requires a private login. Following means a local watchlist, not automatically following on X. User credentials are configured privately, never included in public app state. Samples have been removed from the working inbox and UI.

## Confirmed Interface Direction
A simple black single page. Watched accounts occupy the top strip; the plus on the right expands into exact-username search. When no posts are available, center “Monitoring posts…”. Settings remain on the same page and are hidden until needed. A quiet footer exposes monitoring, reminders, notifications and settings. Preserve truthful paused, disconnected and error states.

## Evidence on Hand
Existing working app, configured integrations, two watched accounts, user-approved local/ngrok hosting and browser notification preferences. Desktop 1440×900 and mobile 390×844 captures verify the requested empty-state composition. Final publication and operating-system notification delivery require user/browser interaction.

## Context Reading Limits
Draft context is bounded to four posts, eight photos, two native X videos/GIFs, and three linked pages. Each video is at most five minutes/80 MB; up to 24 frames spanning the full clip and the audio transcript are supplied together with the author’s reaction. Inaccessible source or direct-reference context is flagged and automatic drafting stops with a visible reason. Incomplete older quoted background is a warning; a grounded draft can use the context actually read. Combined visual inputs are limited to 32 million encoded characters. Video frame sampling may miss rapid actions; transcripts may miss tone, sounds or unclear speech. Over-limit clips, external video sites, PDFs and login-required or JavaScript-only content need manual review. Profile images use X’s image host with initials as fallback.
