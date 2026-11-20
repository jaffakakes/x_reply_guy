const { test } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");

function harness() {
  const listeners = {};
  const element = { addEventListener() {} };
  const context = vm.createContext({
    document: {
      getElementById: () => element,
      addEventListener: (name, callback) => (listeners[name] = callback),
      body: { setAttribute() {}, removeAttribute() {} },
    },
    window: { addEventListener() {} },
    navigator: {},
    fetch: () => new Promise(() => {}),
    setInterval() {},
    setTimeout() {},
    clearTimeout() {},
    URLSearchParams,
  });
  vm.runInContext(fs.readFileSync("static/app.js", "utf8"), context);
  vm.runInContext(
    `
    state = {posts:[{id:'live-1',reply:'Original edit',repurpose:'My perspective',demo:0}]};
    selectedId='live-1'; dirty=true;
    refresh=async () => {}; toast=() => {};
  `,
    context,
  );
  return { context, listeners, run: (code) => vm.runInContext(code, context) };
}

test("typing during a pending save preserves dirty state and prevents navigation", async () => {
  const h = harness();
  let release;
  h.context.saveRequest = () => new Promise((resolve) => (release = resolve));
  h.run("api=saveRequest");
  const saving = h.run("saveDraft()");
  h.run("currentPost().reply='A later edit'");
  release({ ok: true });
  await assert.rejects(saving, /added changes while saving/);
  assert.equal(h.run("dirty"), true);
  assert.equal(h.run("currentPost().reply"), "A later edit");
});

test("successful unchanged save marks the draft clean", async () => {
  const h = harness();
  h.run("api=async () => ({ok:true})");
  await h.run("saveDraft()");
  assert.equal(h.run("dirty"), false);
});

test("removing an account saves the edited live post first", async () => {
  const h = harness();
  const calls = [];
  h.context.saveRequest = async (path, body) => calls.push({ path, body });
  h.run("api=saveRequest");
  const button = { dataset: { remove: "watched_account" }, disabled: false };
  await h.listeners.click({ target: { closest: () => button } });
  assert.deepEqual(
    calls.map((c) => c.path),
    ["/api/posts", "/api/accounts/remove"],
  );
  assert.equal(calls[0].body.reply, "Original edit");
  assert.equal(h.run("dirty"), false);
});

test("a failed save prevents account removal and keeps the live draft dirty", async () => {
  const h = harness();
  const calls = [];
  h.context.saveRequest = async (path) => {
    calls.push(path);
    throw new Error("Offline");
  };
  h.run("api=saveRequest");
  const button = { dataset: { remove: "watched_account" }, disabled: false };
  await h.listeners.click({ target: { closest: () => button } });
  assert.deepEqual(calls, ["/api/posts"]);
  assert.equal(h.run("dirty"), true);
});

test("replied posts leave the queue even if a saved draft is ready", () => {
  const h = harness();
  h.run(`state.posts=[
    {id:'1',status:'ready',replied_at:'2026-11-20T10:00:00Z'},
    {id:'2',status:'ready',replied_at:null},
    {id:'3',status:'archived',replied_at:null}
  ]`);
  assert.equal(h.run("visiblePosts().map(p=>p.id).join(',')"), "2");
  h.run("filter='archived'");
  assert.equal(h.run("visiblePosts().map(p=>p.id).join(',')"), "1,3");
});

test("mark replied preserves edits before recording completion", async () => {
  const h = harness();
  const calls=[];
  h.context.saveRequest=async (path,body)=>calls.push({path,body});
  h.run("api=saveRequest");
  const button={id:'mark-replied',dataset:{},disabled:false};
  await h.listeners.click({target:{closest:()=>button}});
  assert.equal(calls.length,2);
  assert.equal(calls[0].body.reply,'Original edit');
  assert.equal(calls[1].body.id,'live-1');
  assert.equal(calls[1].body.replied,true);
});

test("profile photos use X's host and escape account labels", () => {
  const h = harness();
  const html = h.run(`profileAvatar({handle:'person',name:'<Person>',profile_image_url:'https://pbs.twimg.com/profile_images/photo.jpg'})`);
  assert.match(html, /<img/);
  assert.match(html, /&lt;Person&gt;/);
  assert.match(html, /referrerpolicy="no-referrer"/);
  assert.doesNotMatch(h.run(`profileAvatar({handle:'person',profile_image_url:'https://pbs.twimg.com.evil.test/photo'})`), /<img/);
});

test("empty drafts show the specific blocking reason", () => {
  const h = harness();
  assert.match(h.run(`draftMessage({status:'needs_context',error:'Draft paused: image unavailable. Check the source.'})`), /image unavailable/);
  assert.match(h.run(`draftMessage({status:'skipped',error:'The clip needs missing audio.'})`), /No draft suggested: The clip needs missing audio/);
});

test("queued drafts explain disabled generation and exhausted allowance", () => {
  const h = harness();
  h.run("state.settings={auto_draft:false,daily_drafts:30,enabled:true}; state.usage={draft_attempts:0}; state.connections={ai:true}");
  assert.match(h.run("draftMessage({status:'new'})"), /Automatic drafting is off/);
  h.run("state.settings.auto_draft=true;state.usage.draft_attempts=30");
  assert.match(h.run("draftMessage({status:'new'})"), /Daily draft allowance reached/);
});

test("an automatically detected reply keeps unsaved edits visible until saved", () => {
  const h = harness();
  h.run("state.posts[0].replied_at='2026-11-20T12:00:00Z'; state.posts[0].detected_reply_id='202'");
  assert.equal(h.run("visiblePosts().length"), 1);
  h.run("dirty=false");
  assert.equal(h.run("visiblePosts().length"), 0);
});

test("reply progress distinguishes goal reached, behind pace and tracking failures", () => {
  const h=harness();
  h.run("p={handle:'person',replies:30,goal:23,goal_met:true,error:'',monitoring:true,syncing:false,fresh:true,active_window:true,behind:false,remaining:0}");
  assert.match(h.run("progressLabel(p)"), /30\/23 replies.*Goal reached/);
  h.run("p.replies=5;p.goal_met=false;p.behind=true;p.remaining=18");
  assert.match(h.run("progressLabel(p)"), /18 to go/);
  h.run("p.error='Rate limited'");
  assert.match(h.run("progressLabel(p)"), /Tracking issue/);
  h.run("p.error='';p.fresh=false");
  assert.match(h.run("progressLabel(p)"), /Waiting for X/);
});

test("notification checks stop when the daily goal is met", async () => {
  const h=harness();
  h.run("state.schedule={enabled:true,needs_reply:false,current:{id:'today:6',due_at:new Date().toISOString()},progress:{goal_met:true,replies:30,goal:23}}; api=()=>{throw Error('Should not claim a reminder')}");
  await h.run("maybeNotify()");
  assert.equal(h.run("lastInAppReminder"), "");
});

test("angle selection saves edits then sends the chosen tone for the same post", async () => {
  const h=harness();
  const calls=[];
  h.context.send=async (path,body)=>calls.push({path,body});
  h.run("api=send");
  const button={dataset:{tone:'disagree'},disabled:false,textContent:'Disagree'};
  await h.listeners.click({target:{closest:()=>button}});
  assert.deepEqual(calls.map(c=>c.path),['/api/posts','/api/draft']);
  assert.equal(calls[0].body.reply,'Original edit');
  assert.equal(calls[1].body.id,'live-1');
  assert.equal(calls[1].body.tone,'disagree');
  assert.equal(button.textContent,'Disagree');
  assert.equal(button.disabled,false);
});

test("angle controls remain available during monitoring and disable only their own queued draft", () => {
  const h=harness();
  h.run("state.connections={ai:true};state.busy=false");
  const html=h.run("toneControls({draft_tone:'controversial'})");
  assert.match(html,/data-tone="controversial" aria-pressed="true"/);
  assert.match(html,/data-tone="agreeable" aria-pressed="false"/);
  assert.match(html,/rewrite Reply and Your take/);
  h.run("state.busy=true");
  assert.equal((h.run("toneControls({})").match(/ disabled/g)||[]).length,0);
  assert.equal((h.run("toneControls({draft_job:'queued'})").match(/ disabled/g)||[]).length,5);
});

test("failed rewrite restores the angle button and preserves the current text", async () => {
  const h=harness();
  h.run("dirty=false;api=async()=>{throw Error('Unavailable')}");
  const button={dataset:{tone:'provocative'},disabled:false,textContent:'Provocative'};
  await h.listeners.click({target:{closest:()=>button}});
  assert.equal(button.textContent,'Provocative');
  assert.equal(h.run("currentPost().reply"),'Original edit');
});

test("draft queue messages replace stale failure messages while a retry runs", () => {
  const h=harness();
  assert.match(h.run("draftMessage({draft_job:'queued',status:'error',error:'Old error'})"), /queued.*automatically/);
  assert.match(h.run("draftMessage({draft_job:'writing',status:'needs_context',error:'Old error'})"), /writing your drafts/);
});
