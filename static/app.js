"use strict";
let state,
  selectedId = null,
  draftKind = "reply",
  filter = "active";
let dirty = false,
  preferencesDirty = false,
  keysDirty = false,
  busy = false;
let editorSignature = "",
  postSignature = "",
  watchSignature = "",
  toastTimer;
let searchResult = null,
  searchRevision = 0,
  notifying = false,
  lastInAppReminder = "";
let serviceWorker = null;
const $ = (id) => document.getElementById(id);
const escape = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const closeIcon =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6"/></svg>';
function profileAvatar(account) {
  const label = account.handle || "";
  const url = account.profile_image_url || "";
  const photo = /^https:\/\/pbs\.twimg\.com\//.test(url)
    ? `<img src="${escape(url)}" alt="${escape(account.name || label)} profile photo" referrerpolicy="no-referrer">`
    : "";
  return `<span class="avatar"><span aria-hidden="true">${escape(label.slice(0, 2))}</span>${photo}</span>`;
}
document.addEventListener("error", (event) => {
  if (event.target?.matches?.(".avatar img")) event.target.remove();
}, true);
function toast(message, error = false) {
  $("toast").textContent = message;
  $("toast").className = "toast" + (error ? " error" : "");
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(
    () => ($("toast").hidden = true),
    error ? 9000 : 4500,
  );
}
async function api(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Desk-Token": state.csrf },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(data.error || "The action could not finish.");
  return data;
}
async function action(fn, button) {
  if (busy) return;
  busy = true;
  document.body.setAttribute("aria-busy", "true");
  if (button) button.disabled = true;
  try {
    await fn();
    await refresh();
  } catch (error) {
    toast(error.message, true);
  } finally {
    busy = false;
    if (button) button.disabled = false;
    document.body.removeAttribute("aria-busy");
  }
}
function currentPost() {
  return state.posts.find((p) => p.id === selectedId);
}
function visiblePosts() {
  return state.posts.filter(
    (p) =>
      !p.demo &&
      (filter === "archived"
        ? p.status === "archived" || !!p.replied_at
        : p.status !== "archived" && !p.replied_at),
  );
}
function sourceUrl(post) {
  return `https://x.com/${post.handle}/status/${post.id}`;
}
function completeDraft(post) {
  const draft = post[draftKind].trim();
  return draftKind === "repurpose"
    ? `${draft}\n\nSource: ${sourceUrl(post)}`
    : draft;
}
function dateLabel(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}
async function saveDraft() {
  const p = currentPost();
  if (!p || !dirty) return;
  const submitted = { id: p.id, reply: p.reply, repurpose: p.repurpose };
  await api("/api/posts", submitted);
  if (p.reply !== submitted.reply || p.repurpose !== submitted.repurpose) {
    throw new Error(
      "You added changes while saving. Save again to keep the latest version before switching.",
    );
  }
  dirty = false;
}
async function refresh() {
  const response = await fetch("/api/state");
  if (!response.ok)
    throw new Error(
      "Your desk is offline. Keep the server and ngrok running on your Mac.",
    );
  const fresh = await response.json();
  if (dirty && state) {
    const local = currentPost(),
      remote = fresh.posts.find((p) => p.id === selectedId);
    if (local && remote) {
      remote.reply = local.reply;
      remote.repurpose = local.repurpose;
    }
  }
  state = fresh;
  render();
  maybeNotify();
}
function render() {
  const s = state.settings,
    c = state.connections,
    accounts = state.accounts;
  const signature = JSON.stringify(accounts.map((a) => [a.handle, a.error]));
  if (watchSignature !== signature) {
    watchSignature = signature;
    $("watchlist").innerHTML = accounts.length
      ? accounts
          .map(
            (a) =>
              `<div class="watch-chip ${a.error ? "has-error" : ""}" title="${escape(a.error || "Watching new posts")}"><a href="https://x.com/${escape(a.handle)}" target="_blank" rel="noopener noreferrer">${profileAvatar(a)}<span>@${escape(a.handle)}</span></a><button class="icon-button remove" data-remove="${escape(a.handle)}" aria-label="Stop watching @${escape(a.handle)}">${closeIcon}</button></div>`,
          )
          .join("")
      : '<span class="watch-empty">People you watch will appear here</span>';
  }
  const errors = accounts.filter((a) => a.error);
  $("monitor-label").textContent = !s.enabled
    ? "Paused"
    : errors.length
      ? "Needs attention"
      : "Monitoring";
  $("toggle-monitor").setAttribute(
    "aria-label",
    s.enabled ? "Pause monitoring" : "Start monitoring",
  );
  $("monitor-dot").className =
    "status-dot" + (s.enabled ? (errors.length ? " error" : " on") : "");
  const posts = visiblePosts(),
    settingsOpen = !$("settings-panel").hidden;
  $("empty-state").hidden = !!posts.length || settingsOpen;
  $("inbox").hidden = !posts.length || settingsOpen;
  $("empty-state").classList.toggle(
    "paused",
    !s.enabled || !accounts.length || !!errors.length,
  );
  let title = "Monitoring posts…",
    hint = "";
  if (filter === "archived") {
    title = "No archived posts.";
  } else if (!c.x) {
    title = "Connect X to start.";
    hint = "Choose API keys below to add your X token.";
  } else if (!accounts.length) {
    title = "Who are you watching?";
    hint = "Use the + above to find an account.";
  } else if (!s.enabled) {
    title = "Monitoring paused.";
    hint = "Press Paused below to start again.";
  } else if (errors.length) {
    title =
      errors.length === accounts.length
        ? "Monitoring needs attention."
        : "Monitoring available accounts…";
    hint = "Open Settings to see the account errors.";
  }
  $("empty-title").textContent = title;
  $("empty-hint").textContent = hint;
  $("empty-hint").hidden = !hint;
  $("return-inbox").hidden = filter !== "archived";
  if (!posts.some((p) => p.id === selectedId)) {
    selectedId = posts[0]?.id ?? null;
    dirty = false;
  }
  const postMarkup = posts
    .map(
      (p) =>
        `<button class="post-option ${p.id === selectedId ? "active" : ""}" data-post="${escape(p.id)}" aria-pressed="${p.id === selectedId}"><strong>@${escape(p.handle)}</strong><span>${escape(p.text)}</span></button>`,
    )
    .join("");
  if (postMarkup !== postSignature) {
    postSignature = postMarkup;
    $("post-list").innerHTML = postMarkup;
  }
  if (!dirty && document.activeElement?.id !== "draft-text") renderEditor();
  $("archive-filter").textContent =
    filter === "archived" ? "Back to inbox" : "Replied & archived";
  $("archive-filter").setAttribute(
    "aria-pressed",
    String(filter === "archived"),
  );
  $("connection-status").textContent =
    `${c.x ? "X token saved" : "X not connected"} · ${c.ai ? "AI key saved" : "AI not connected"}`;
  $("x-key").placeholder = c.x ? "Leave blank to keep saved token" : "Paste your X bearer token";
  $("ai-key").placeholder = c.ai ? "Leave blank to keep saved key" : "Paste your OpenAI API key";
  $("usage-summary").textContent =
    `${state.usage.posts_read} post reads · ${state.usage.draft_attempts}/${s.daily_drafts} draft attempts · ${state.usage.transcription_attempts || 0}/${s.daily_drafts} audio transcriptions today (UTC)`;
  $("check-now").disabled = state.busy || !accounts.length || !c.x;
  $("account-errors").innerHTML = errors
    .map(
      (a) =>
        `<p><strong>@${escape(a.handle)}</strong> — ${escape(a.error)}</p>`,
    )
    .join("");
  if (
    !preferencesDirty &&
    !$("settings-form").contains(document.activeElement)
  ) {
    $("topic").value = s.topic;
    $("voice").value = s.voice;
    $("interval").value = s.interval;
    $("reads").value = s.daily_reads;
    $("drafts").value = s.daily_drafts;
    $("auto-draft").checked = s.auto_draft;
  }
  if (!keysDirty) $("model").value = c.model;
  renderSchedule();
}
function draftMessage(post) {
  if (post.status === "needs_context") return post.error || "Draft paused: source context is missing. Check the source and retry.";
  if (post.status === "skipped") return `No draft suggested: ${post.error || "There wasn't enough context for a useful reply."}`;
  if (post.status === "error") return `Draft failed: ${post.error || "Try Generate drafts again."}`;
  if (post.status !== "new") return "";
  if (!state.settings.auto_draft) return "Automatic drafting is off. Choose Generate drafts to create a reply.";
  if (state.usage.draft_attempts >= state.settings.daily_drafts) return "Daily draft allowance reached. Resets at midnight UTC; you can still write your own reply.";
  if (!state.connections.ai) return "Connect your AI key in Settings to generate a reply.";
  if (!state.settings.enabled) return "Monitoring is paused. Choose Generate drafts or resume monitoring.";
  return "Draft queued. The app will read the context and write a reply.";
}
function renderEditor() {
  const p = currentPost();
  if (!p) {
    $("editor").innerHTML = "";
    editorSignature = "";
    return;
  }
  const signature = JSON.stringify([
    p,
    draftKind,
    state.connections.ai,
    state.busy,
    draftMessage(p),
  ]);
  if (signature === editorSignature) {
    updateCount();
    return;
  }
  editorSignature = signature;
  $("editor").innerHTML =
    `<div class="source-meta"><strong>@${escape(p.handle)}</strong><a href="${sourceUrl(p)}" target="_blank" rel="noopener noreferrer">${escape(dateLabel(p.created_at))} · View post</a></div><p class="source-text">${escape(p.text)}</p>${draftMessage(p) ? `<p class="editor-note" role="status">${escape(draftMessage(p))}</p>` : ""}${p.context_summary ? `<p class="editor-note">${escape(p.context_summary)}</p>` : ""}<div class="draft-tabs" role="group" aria-label="Draft type"><button class="draft-tab ${draftKind === "reply" ? "active" : ""}" data-kind="reply" aria-pressed="${draftKind === "reply"}">Reply</button><button class="draft-tab ${draftKind === "repurpose" ? "active" : ""}" data-kind="repurpose" aria-pressed="${draftKind === "repurpose"}">Your take</button></div><label for="draft-text" class="sr-only">Edit your draft</label><textarea id="draft-text" maxlength="2000" placeholder="Add something worth saying…">${escape(p[draftKind])}</textarea><div class="draft-details"><span>${draftKind === "repurpose" ? "Source link included when you open X." : "Review the wording. You publish in X."}</span><span id="character-count"></span></div><div class="editor-actions"><button id="open-composer" class="button">Open in X</button><button id="save-draft" class="button secondary">Save</button><button id="copy-draft" class="text-button">Copy</button><button id="generate-draft" class="text-button" ${!state.connections.ai || state.busy ? "disabled" : ""}>${p.reply || p.repurpose ? "Regenerate both" : "Generate drafts"}</button><button id="mark-replied" class="text-button">${p.replied_at ? "Undo replied" : "Mark replied"}</button><button id="archive-draft" class="text-button">${p.status === "archived" ? "Restore" : "Archive"}</button></div>${p.error && p.status === "ready" ? `<p class="editor-note">${escape(p.error)}</p>` : ""}`;
  updateCount();
}
function updateCount() {
  const p = currentPost();
  if (!p || !$("character-count")) return;
  $("character-count").textContent =
    `${[...completeDraft(p)].length} characters`;
  $("character-count").title =
    "Approximate. X applies its own rules for links and emoji.";
  $("open-composer").disabled = !p[draftKind].trim() || p.status === "needs_context";
  $("copy-draft").disabled = !p[draftKind].trim();
  $("save-draft").textContent = dirty ? "Save changes" : "Save";
}
function renderSchedule() {
  const schedule = state.schedule;
  if (!schedule) return;
  const due = schedule.current,
    age = due ? Date.now() - Date.parse(due.due_at) : Infinity;
  const needsPost =
    schedule.enabled && due && !due.completed && age >= 0 && age < 30 * 60000;
  $("mark-posted").hidden = !needsPost;
  $("next-reminder").textContent = !schedule.enabled
    ? "Reminders paused"
    : needsPost
      ? `Time to post · ${due.number}/33`
      : `Next ${schedule.next?.time || "10:00"} · 33/day · London`;
  $("mark-posted")
    .closest(".reminder-summary")
    .classList.toggle("due", needsPost);
  $("toggle-reminders").textContent = schedule.enabled
    ? "Pause reminders"
    : "Resume reminders";
  const permission =
    "Notification" in window ? Notification.permission : "unsupported";
  $("enable-notifications").textContent =
    permission === "granted"
      ? "Notifications enabled"
      : permission === "denied"
        ? "Notifications blocked"
        : "Enable browser notifications";
  $("enable-notifications").disabled =
    permission === "granted" || permission === "unsupported";
  $("notification-toggle").setAttribute(
    "aria-label",
    permission === "granted"
      ? "Notification settings"
      : "Enable browser notifications",
  );
  $("notification-status").textContent =
    permission === "granted"
      ? "Browser permission granted. Reminders appear while this app is open."
      : permission === "denied"
        ? "Allow notifications for this address in your browser settings, then reload."
        : permission === "unsupported"
          ? "This browser cannot show notifications. Open this address in a supported browser such as Safari or Chrome."
          : "Enable notifications once in this browser. You can also use the reminder displayed at the bottom.";
  const times = schedule.slots
    .map(
      (slot) =>
        `<li class="${slot.completed ? "completed" : ""}" title="Post ${slot.number} of 33${slot.completed ? " · marked posted" : ""}">${escape(slot.time)}${slot.completed ? " · done" : ""}</li>`,
    )
    .join("");
  if ($("schedule-times").innerHTML !== times)
    $("schedule-times").innerHTML = times;
}
async function enableNotifications() {
  if ("Notification" in window && Notification.permission === "granted") {
    setSettings(true);
    $("toggle-reminders").scrollIntoView({ block: "center" });
    $("toggle-reminders").focus();
    return;
  }
  if (!("Notification" in window)) {
    setSettings(true);
    toast("Open this app in Safari or Chrome to enable notifications.", true);
    return;
  }
  if (Notification.permission === "denied") {
    setSettings(true);
    toast(
      "Notifications are blocked. Allow them in your browser's site settings.",
      true,
    );
    return;
  }
  if (Notification.permission !== "granted")
    await Notification.requestPermission();
  renderSchedule();
  if (Notification.permission === "granted")
    toast(
      "Notifications enabled. Keep this app open for your 33 daily reminders.",
    );
}
async function maybeNotify() {
  const schedule = state?.schedule,
    slot = schedule?.current;
  if (!schedule?.enabled || !slot || slot.completed) return;
  const age = Date.now() - Date.parse(slot.due_at);
  if (age < 0 || age >= 300000) return;
  if (lastInAppReminder !== slot.id) {
    lastInAppReminder = slot.id;
    toast(`Time to post · reminder ${slot.number} of 33`);
  }
  if (
    notifying ||
    !("Notification" in window) ||
    Notification.permission !== "granted"
  )
    return;
  notifying = true;
  try {
    const result = await api("/api/reminders/claim", { id: slot.id });
    if (!result.claimed) return;
    const options = {
      body: `Posting reminder ${slot.number} of 33. Open Draft Desk to find your next post.`,
      tag: `desk-${slot.id}`,
      icon: "/icon.svg",
      data: { url: "/" },
    };
    const registration = await serviceWorker;
    if (registration)
      await registration.showNotification("Time to post", options);
    else {
      const notification = new Notification("Time to post", options);
      notification.onclick = () => {
        window.focus();
        notification.close();
      };
    }
  } catch (error) {
    toast(
      "Could not display a browser notification. Your reminder is shown below.",
      true,
    );
  } finally {
    notifying = false;
  }
}
function setSettings(open) {
  $("settings-panel").hidden = !open;
  $("settings-toggle").setAttribute("aria-expanded", String(open));
  render();
  if (open) $("settings-title").scrollIntoView({ block: "start" });
}
function setSearch(open) {
  $("search-form").hidden = !open;
  $("add-account").classList.toggle("expanded", open);
  $("add-toggle").setAttribute("aria-expanded", String(open));
  $("add-toggle").setAttribute(
    "aria-label",
    open ? "Close account search" : "Add someone to watch",
  );
  if (open) $("account-search").focus();
  else {
    searchRevision++;
    $("search-result").hidden = true;
    $("account-search").value = "";
    searchResult = null;
    $("add-toggle").focus();
  }
}
document.addEventListener("input", (event) => {
  if (event.target.id === "draft-text") {
    currentPost()[draftKind] = event.target.value;
    dirty = true;
    updateCount();
  }
  if (event.target.closest("#settings-form")) preferencesDirty = true;
  if (event.target.closest("#keys-form")) keysDirty = true;
  if (event.target.id === "account-search") {
    searchRevision++;
    searchResult = null;
    $("search-result").hidden = true;
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("search-form").hidden) setSearch(false);
});
document.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button || button.disabled) return;
  if (button.dataset.post || button.dataset.kind)
    return action(async () => {
      await saveDraft();
      if (button.dataset.post) selectedId = button.dataset.post;
      if (button.dataset.kind) draftKind = button.dataset.kind;
      renderEditor();
    }, button);
  if (button.dataset.remove)
    return action(async () => {
      await saveDraft();
      await api("/api/accounts/remove", { handle: button.dataset.remove });
      toast("Stopped watching this account. Existing drafts are kept.");
    }, button);
  const id = button.id;
  if (id === "add-toggle") return setSearch($("search-form").hidden);
  if (id === "settings-toggle") return setSettings($("settings-panel").hidden);
  if (id === "close-settings") return setSettings(false);
  if (id === "schedule-toggle") return setSettings(true);
  if (id === "enable-notifications" || id === "notification-toggle")
    return enableNotifications().catch((error) => toast(error.message, true));
  if (id === "watch-result")
    return action(async () => {
      if (!searchResult) return;
      await api("/api/accounts", { handle: searchResult.handle });
      setSearch(false);
      toast("Account added. Fetching their latest post, then watching for new ones.");
    }, button);
  if (id === "toggle-monitor")
    return action(async () => {
      if (!state.accounts.length) {
        setSearch(true);
        toast("Add an account to start monitoring.");
        return;
      }
      await api("/api/settings", { enabled: !state.settings.enabled });
    }, button);
  if (id === "toggle-reminders")
    return action(
      () =>
        api("/api/settings", {
          reminders_enabled: !state.settings.reminders_enabled,
        }),
      button,
    );
  if (id === "mark-posted")
    return action(async () => {
      await api("/api/reminders/complete", { id: state.schedule.current.id });
      toast("Marked posted. Your next reminder is on the way.");
    }, button);
  if (id === "check-now")
    return action(async () => {
      await api("/api/check", {});
      toast("Checking for new posts…");
    }, button);
  if (id === "save-draft")
    return action(async () => {
      await saveDraft();
      toast("Draft saved.");
    }, button);
  if (id === "copy-draft")
    return action(async () => {
      await navigator.clipboard.writeText(completeDraft(currentPost()));
      toast("Draft copied.");
    }, button);
  if (id === "generate-draft")
    return action(async () => {
      await saveDraft();
      button.textContent = "Reading context…";
      try {
        await api("/api/draft", { id: selectedId });
      } finally {
        editorSignature = "";
      }
    }, button);
  if (id === "mark-replied")
    return action(async () => {
      await saveDraft();
      const post = currentPost();
      await api("/api/posts", { id: post.id, replied: !post.replied_at });
      toast(post.replied_at ? "Reply mark undone." : "Marked replied. This post is out of your reply queue.");
    }, button);
  if (id === "archive-draft")
    return action(async () => {
      await saveDraft();
      await api("/api/posts", {
        id: selectedId,
        status: currentPost().status === "archived" ? "ready" : "archived",
      });
    }, button);
  if (id === "archive-filter" || id === "return-inbox" || id === "view-archive")
    return action(async () => {
      await saveDraft();
      filter =
        id === "view-archive"
          ? "archived"
          : id === "return-inbox"
            ? "active"
            : filter === "archived"
              ? "active"
              : "archived";
      $("settings-panel").hidden = true;
      $("settings-toggle").setAttribute("aria-expanded", "false");
    }, button);
  if (id === "open-composer") {
    const post = currentPost();
    if (!post || post.demo || post.status === "needs_context" || !post[draftKind].trim()) return;
    const params = new URLSearchParams({ text: completeDraft(post) });
    if (draftKind === "reply") params.set("in_reply_to", post.id);
    window.open(
      `https://x.com/intent/tweet?${params}`,
      "_blank",
      "noopener,noreferrer",
    );
    action(async () => {
      await saveDraft();
      toast(draftKind === "reply" ? "Finish in X, then use “Mark replied” on this post." : "Finish in X, then use “I’ve posted” when you’re done.");
    });
  }
});
$("search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const handle = $("account-search")
    .value.trim()
    .replace(/^@/, "")
    .toLowerCase();
  if (!/^[a-z0-9_]{1,15}$/.test(handle)) {
    toast("Enter an exact X @username, up to 15 characters.", true);
    return;
  }
  const revision = ++searchRevision;
  $("search-result").hidden = false;
  $("search-result").textContent = "Searching X…";
  action(async () => {
    try {
      const result = await api("/api/accounts/search", { handle });
      if (revision !== searchRevision) return;
      searchResult = result.account;
      $("search-result").innerHTML =
        `<div class="search-person">${profileAvatar(searchResult)}<span class="person"><strong>${escape(searchResult.name)}</strong><small>@${escape(handle)}</small></span><button id="watch-result" class="button small" ${state.accounts.some(a => a.handle === handle) ? "disabled" : ""}>${state.accounts.some(a => a.handle === handle) ? "Watching" : "Watch"}</button></div>${searchResult.description ? `<p class="profile-bio">${escape(searchResult.description)}</p>` : ""}<a class="profile-link" href="https://x.com/${escape(handle)}" target="_blank" rel="noopener noreferrer">View profile on X</a>`;
    } catch (error) {
      if (revision === searchRevision)
        $("search-result").textContent = error.message;
    }
  });
});
$("keys-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    await api("/api/keys", Object.fromEntries(new FormData(event.target)));
    $("x-key").value = "";
    $("ai-key").value = "";
    keysDirty = false;
    toast("API keys saved. They'll be checked when first used.");
  });
});
$("settings-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const values = {
      topic: $("topic").value,
      voice: $("voice").value,
      interval: Number($("interval").value),
      daily_reads: Number($("reads").value),
      daily_drafts: Number($("drafts").value),
      auto_draft: $("auto-draft").checked,
    };
    const submitted = JSON.stringify(values);
    await api("/api/settings", values);
    const latest = {
      topic: $("topic").value,
      voice: $("voice").value,
      interval: Number($("interval").value),
      daily_reads: Number($("reads").value),
      daily_drafts: Number($("drafts").value),
      auto_draft: $("auto-draft").checked,
    };
    preferencesDirty = JSON.stringify(latest) !== submitted;
    toast(
      preferencesDirty
        ? "Saved. You have additional unsaved changes."
        : "Preferences saved.",
    );
  });
});
window.addEventListener("beforeunload", (event) => {
  if (dirty || preferencesDirty || keysDirty) {
    event.preventDefault();
    event.returnValue = "";
  }
});
if ("serviceWorker" in navigator)
  serviceWorker = navigator.serviceWorker.register("/sw.js").catch(() => null);
refresh().catch((error) => {
  toast(error.message, true);
  $("empty-title").textContent = "Your desk is offline.";
});
setInterval(() => {
  if (!busy)
    refresh().catch(() => {
      $("monitor-label").textContent = "Offline";
      $("monitor-dot").className = "status-dot error";
      $("empty-title").textContent = "Your desk is offline.";
    });
}, 10000);
