/* AllProPhoto Studio: the page. Plain JavaScript, no build step.
   The server (studio/server.py) keeps the session; this page shows it and sends what you do. */
"use strict";

// Icons ----------------------------------------------------------------------------------
const ICONS = {
  chev: '<path d="m6 9 6 6 6-6"/>',
  export: '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  single: '<rect x="3" y="4" width="18" height="16" rx="2"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  star: '<path fill="currentColor" stroke="none" d="m12 2.6 2.9 5.9 6.5.9-4.7 4.6 1.1 6.5L12 17.4l-5.8 3.1 1.1-6.5L2.6 9.4l6.5-.9z"/>',
  starO: '<path d="m12 2.6 2.9 5.9 6.5.9-4.7 4.6 1.1 6.5L12 17.4l-5.8 3.1 1.1-6.5L2.6 9.4l6.5-.9z"/>',
  left: '<path d="m15 18-6-6 6-6"/>',
  right: '<path d="m9 18 6-6-6-6"/>',
  compare: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
  dice: '<path d="M2 18h1.4c1.3 0 2.5-.6 3.3-1.7l6.1-8.6c.7-1.1 2-1.7 3.3-1.7H22"/><path d="m18 2 4 4-4 4"/><path d="M2 6h1.9c1.5 0 2.9.9 3.6 2.2"/><path d="M22 18h-5.9c-1.3 0-2.6-.7-3.3-1.8l-.5-.8"/><path d="m18 14 4 4-4 4"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  wand: '<path d="m3 21 12-12"/><path d="m14 4 1-2 1 2 2 1-2 1-1 2-1-2-2-1z"/><path d="m19 11 .5-1 .5 1 1 .5-1 .5-.5 1-.5-1-1-.5z"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  save: '<path d="M5 3h11l3 3v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M7 3v6h8V3M7 21v-7h10v7"/>',
  film: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 3v18M17 3v18M3 8h4M3 16h4M17 8h4M17 16h4"/>',
  zoom: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5M8 11h6M11 8v6"/>',
  clip: '<rect x="8" y="3" width="8" height="4" rx="1"/><path d="M16 5h2a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2"/>',
  redo: '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
  crop: '<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/>',
  eraser: '<path d="m7 21-4.3-4.3a1 1 0 0 1 0-1.4l10-10a1 1 0 0 1 1.4 0l5.6 5.6a1 1 0 0 1 0 1.4L11 21z"/><path d="M22 21H7M5 11l9 9"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1" fill="currentColor"/>',
  pipette: '<path d="m2 22 1-1h3l9-9"/><path d="M3 21v-3l9-9"/><path d="m15 6 3.4-3.4a2.1 2.1 0 1 1 3 3L18 9l.4.4a2.1 2.1 0 1 1-3 3l-3.8-3.8a2.1 2.1 0 1 1 3-3z"/>',
  type: '<path d="M4 7V4h16v3M9 20h6M12 4v16"/>',
  level: '<path d="M2 12h20"/><path d="M5 8l14 8" opacity=".5"/>',
  share: '<path d="M12 3v13"/><path d="m7 8 5-5 5 5"/><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/>',
  pick: '<circle cx="12" cy="12" r="9.5" fill="currentColor" stroke="none"/><path d="m7.5 12.2 3 3 6-6.2" stroke="#111" stroke-width="2.4"/>',
  pickO: '<circle cx="12" cy="12" r="9"/><path d="m7.5 12.2 3 3 6-6.2"/>',
  airdrop: '<path d="M8.5 15.5a5 5 0 1 1 7 0"/><path d="M5.6 18.4a9 9 0 1 1 12.8 0"/><path d="m12 13-3 9h6z"/>',
  message: '<path d="M21 12a8 8 0 0 1-11.6 7.1L3 21l1.9-6.4A8 8 0 1 1 21 12z"/>',
  mail: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/>',
  photos: '<circle cx="12" cy="7" r="3.2"/><circle cx="12" cy="17" r="3.2"/><circle cx="7" cy="12" r="3.2"/><circle cx="17" cy="12" r="3.2"/>',
  layout: '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M4 9h16M9 21V9"/>',
  person: '<circle cx="10" cy="8" r="4"/><path d="M3 21v-1a7 7 0 0 1 11-5.7"/><circle cx="17.5" cy="17.5" r="3"/><path d="m21 21-1.4-1.4"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  badge: '<path d="M12 2 4 5v6c0 5 3.4 9.3 8 11 4.6-1.7 8-6 8-11V5z"/><path d="m9 12 2 2 4-4"/>',
  music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
};
const icon = (name) => `<i data-i="${name}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ""}</svg></i>`;
function paintIcons(root = document) {
  root.querySelectorAll("i[data-i]:empty").forEach((el) => { el.outerHTML = icon(el.dataset.i); });
}

// Helpers --------------------------------------------------------------------------------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const enc = encodeURIComponent;
const plural = (n, word, many = word + "s") => `${n} ${n === 1 ? word : many}`;
/* A countdown that reads like a clock: 2:35, 0:42, 8 s. */
function clock(sec) {
  sec = Math.round(sec);
  if (sec < 60) return `${sec} s`;
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}
function say(sec) {
  if (sec < 10) return `about ${Math.max(1, Math.round(sec))} s`;
  if (sec < 90) return `about ${Math.round(sec / 5) * 5} s`;
  return `about ${Math.round(sec / 60)} min`;
}
function short(sec) {
  if (sec < 2) return "instant";
  if (sec < 90) return `${Math.round(sec)} s`;
  return `${Math.round(sec / 60)} min`;
}
async function api(path, body, opts = {}) {
  const init = { method: body === undefined && !opts.method ? "GET" : (opts.method || "POST") };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) { init.body = JSON.stringify(body); init.headers = { "Content-Type": "application/json" }; }
  const res = await fetch(path, init);
  let data = {};
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) {
    const msg = data.error || data.detail || `Something went wrong (${res.status})`;
    toast(typeof msg === "string" ? msg : "Something went wrong", { bad: true });
    throw Object.assign(new Error(msg), { shown: true });
  }
  return data;
}
// a problem the app already explained in a note needs nothing more
window.addEventListener("unhandledrejection", (e) => { if (e.reason?.shown) e.preventDefault(); });
const store = {
  get(k, d) { try { const v = localStorage.getItem("app." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("app." + k, JSON.stringify(v)); } catch { /* private mode */ } },
};

// Help: a tip on hover for anything with a title, and the reason for anything not usable yet ---
/* A control that cannot be used yet stays clickable: clicking (or hovering) it says why. */
const off = (cond, why) => cond ? `aria-disabled="true" data-why="${esc(why)}"` : "";
function setOff(el, cond, why) {
  if (!el) return;
  el.disabled = false;
  if (cond) { el.setAttribute("aria-disabled", "true"); el.dataset.why = why; }
  else { el.removeAttribute("aria-disabled"); delete el.dataset.why; }
}
let tipEl = null, tipTimer = null, tipFor = null;
function hideTip() {
  clearTimeout(tipTimer); tipFor = null;
  if (tipEl) tipEl.hidden = true;
}
function showTip(el, { why = false } = {}) {
  if (!el.isConnected) return;
  tipEl ||= Object.assign(document.body.appendChild(document.createElement("div")), { className: "tip", role: "tooltip" });
  const look = el.dataset.tipLook && lookByName(el.dataset.tipLook);
  if (el.dataset.why && (why || !el.dataset.tip)) {
    tipEl.innerHTML = `<span class="why-head">${icon("info")} Not yet</span>${esc(el.dataset.why)}`;
  } else if (look) {
    tipEl.innerHTML = `<b>${esc(look.name)}</b><p>${esc(look.about)}</p><small>${look.ai ? "Drawn by AI on this Mac" : look.cutout ? "Separates the player from the background" : "A color and light look"} · ${short(look.secs) === "instant" ? "instant" : "about " + short(look.secs) + " a photo"}</small>
      <small class="dim">${look.ai ? "Its picture is an example" : "Point at its picture to try it on your photo"} · click to pick it</small>`;
  } else tipEl.textContent = el.dataset.tip || "";
  tipEl.className = "tip" + (el.dataset.why && (why || !el.dataset.tip) ? " why" : "") + (look ? " rich" : "");
  tipEl.hidden = false;
  paintIcons(tipEl);
  const r = (look ? el.closest(".look") || el : el).getBoundingClientRect(), t = tipEl.getBoundingClientRect(), pad = 8;
  let x, y;
  if (look) { x = r.left - t.width - 10; y = r.top + r.height / 2 - t.height / 2; }
  else {
    x = r.left + r.width / 2 - t.width / 2;
    y = r.top - t.height - 8;
    if (y < pad) y = r.bottom + 8;
  }
  tipEl.style.left = `${Math.max(pad, Math.min(innerWidth - t.width - pad, x))}px`;
  tipEl.style.top = `${Math.max(pad, Math.min(innerHeight - t.height - pad, y))}px`;
}
document.addEventListener("pointerover", (e) => {
  const el = e.target.closest?.("[title], [data-tip], [data-why], [data-tip-look]");
  if (el?.hasAttribute("title")) { if (el.title) el.dataset.tip = el.title; el.removeAttribute("title"); }
  if (el === tipFor) return;
  hideTip();
  if (!el || !(el.dataset.tip || el.dataset.why || el.dataset.tipLook)) return;
  tipFor = el;
  tipTimer = setTimeout(() => showTip(el), el.dataset.tipLook ? 550 : 320);
});
document.addEventListener("pointerout", (e) => { if (tipFor && !tipFor.contains(e.relatedTarget)) hideTip(); });
document.addEventListener("keydown", hideTip, true);
document.addEventListener("click", (e) => {
  const el = e.target.closest?.('[aria-disabled="true"]');
  if (!el) return;
  e.preventDefault(); e.stopPropagation();
  explain(el);
}, true);
/* Says why a control cannot be used yet, next to it. */
function explain(el) {
  hideTip(); tipFor = el;
  showTip(el, { why: true });
  el.classList.remove("nudge"); void el.offsetWidth; el.classList.add("nudge");
  tipTimer = setTimeout(hideTip, 4000);
}

// State ----------------------------------------------------------------------------------
const CROPS = [["none", "Whole", "The photo as shot, nothing cut"],
  ["wide", "Pro", "Its own shape, trimmed a little (at most 10%) so the players sit on a thirds line; keeps the scene"],
  ["crop", "Tight", "Zoomed in on the action: the players in the play fill the picture"],
  ["face", "Face", "A head-and-shoulders portrait of the main player"]];
const MEASURE = { PHOTO_READY: 4, CUT_OUT: 28, MODEL_LOAD: 60 };

const st = {
  photos: [], slots: [], tasks: [], looks: [], groups: [], sizes: [], prefs: {}, credit: {}, busy: false, left: 0,
  modelsLoaded: false,
  activePhoto: null, current: null, mode: "edit", view: "single", tab: "looks",
  picked: new Set(), filter: store.get("filter", "All"), query: "", fromEdits: store.get("fromEdits", true),
  scope: "one", crop: "none", compare: false, split: 50, fixing: false, fixAdd: true, fixVer: 0,
  reelSource: "kept", reelTask: null, reelOrder: [], reelOut: new Set(),
  zoom: { on: false, x: 50, y: 50, k: 2.5 }, survey: [],
  tool: null, cropDraft: null, brush: { r: store.get("brush", 0.025), strokes: [], points: [], order: [] }, areaSel: null, textSel: null,
  show: "all", kit: [], logoSel: null, openGroups: {},
  player: null, finding: false, railShow: "all", chosen: new Set(),
};
const slotById = (id) => st.slots.find((s) => s.id === id);
const doneSlots = () => st.slots.filter((s) => s.state === "done");
const keptSlots = () => st.slots.filter((s) => s.state === "done" && s.kept);
/* The looks shown in the strip and the contact sheet: all, the picks, or those rated at least N stars. */
const visibleSlots = () => st.show === "all" ? st.slots
  : st.show === "picks" ? st.slots.filter((s) => s.kept) : st.slots.filter((s) => (s.rating || 0) >= +st.show);
const lookByName = (n) => st.looks.find((l) => l.name === n);
const slotImg = (s, kind = "after") => `/img/slot/${s.id}/${s.ver}/${kind}.jpg`;

// Loading --------------------------------------------------------------------------------
let pollTimer = null;
async function refresh() {
  const data = await fetch("/api/state").then((r) => r.json()).catch(() => null);
  if (!data) return;
  const before = new Set(st.photos.map((p) => p.id));
  const wasActive = st.activePhoto;
  st.photos = data.photos; st.slots = data.slots; st.tasks = data.tasks; st.busy = data.busy; st.left = data.left;
  st.phase = data.phase;
  // the look previews start from your edit: when it changes, they are made again
  stalePreviews();
  // time left, smoothed: the finish time moves gently toward each new estimate, and counts down by itself
  if (st.busy && data.left > 0) {
    const target = Date.now() + data.left * 1000;
    st.eta = st.eta ? st.eta + (target - st.eta) * 0.35 : target;
    st.runStart ||= Date.now();
  } else { st.eta = null; st.runStart = null; }
  st.modelsLoaded = data.models_loaded; st.credit = data.credit; st.prefs = data.prefs; st.update = data.update;
  st.player = data.player;
  if (!st.player) st.railShow = "all";
  for (const id of [...st.chosen]) if (!data.photos.some((p) => p.id === id)) st.chosen.delete(id);
  if (st.scope === "chosen" && !st.chosen.size) st.scope = "one";
  if (st.activePhoto && !st.photos.some((p) => p.id === st.activePhoto)) st.activePhoto = null;
  if (!st.activePhoto && st.photos.length) st.activePhoto = st.photos.find((p) => !before.has(p.id))?.id ?? st.photos[0].id;
  if (st.current && !slotById(st.current)) st.current = null;
  if (st.scope === "all" && st.photos.length < 2) st.scope = "one";
  render();
  if (st.activePhoto !== wasActive) renderLooks(true);  // the looks previewed on this photo
  schedule();
}
setInterval(() => { if (st.busy && st.eta) renderTop(); }, 1000);  // the countdown ticks between updates
function schedule() {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(refresh, st.busy ? 700 : 30000);  // when idle, now and then: a newer version, say
}
async function loadLooks() {
  const data = await api("/api/looks");
  st.looks = data.looks; st.groups = ["All", ...data.groups.filter((g) => data.looks.some((l) => l.group === g))];
  st.sizes = data.sizes;
  if (!st.groups.includes(st.filter)) st.filter = "All";
  renderLooks(true);
}

// Rendering --------------------------------------------------------------------------------
function render() {
  $("#app").classList.toggle("reel-mode", st.mode === "reel");
  $$(".modes button").forEach((b) => b.classList.toggle("on", b.dataset.mode === st.mode));
  renderTop(); renderRail(); renderStrip(); renderViewer(); renderMake(); renderTabs(); renderTasks();
  if (st.mode === "reel") renderReel();
}

let wasMaking = 0;
function renderTop() {
  const pill = $("#run-pill");
  const making = st.slots.filter((s) => s.state === "wait" || s.state === "now");
  if (wasMaking && !making.length) {
    const n = doneSlots().length;
    notify("Your looks are ready", `${plural(n, "look")} to look through`);
  }
  wasMaking = making.length;
  document.title = "AllProPhoto";
  if (making.length) {
    const runIds = new Set(making.map((s) => s.run));
    const inRuns = st.slots.filter((s) => runIds.has(s.run));
    const done = inRuns.filter((s) => s.state === "done" || s.state === "failed").length;
    const now = making.find((s) => s.state === "now");
    const frac = (done + (now ? now.pct / 100 : 0)) / inRuns.length;
    pill.hidden = false;
    const left = st.eta ? Math.max(1, (st.eta - Date.now()) / 1000) : 0;
    const spent = st.runStart ? (Date.now() - st.runStart) / 1000 : 0;
    const pct = left ? Math.min(99, Math.round(100 * spent / (spent + left))) : Math.round(frac * 100);
    document.title = `(${pct}%) Making looks · AllProPhoto`;
    pill.innerHTML = `<span class="spin"></span><span><b>${pct}%</b> · ${done} of ${plural(inRuns.length, "look")}${left ? " · " + clock(left) + " left" : ""}
      <small class="phase">${esc(st.phase || "")}</small></span>
      <button class="btn ghost" id="stop-run">Stop</button><span class="bar" style="width:${pct}%"></span>`;
    $("#stop-run").onclick = async () => { await api("/api/run/stop", {}); toast("Stopped. The looks already made are kept."); refresh(); };
  } else pill.hidden = true;
  const up = $("#update-btn");
  up.hidden = !st.update;
  up.onclick = restartApp;
  const kept = keptSlots().length;
  const btn = $("#export-btn");
  const cur = slotById(st.current);
  setOff(btn, !(kept || (cur && cur.state === "done")),
    !doneSlots().length ? "Make a look first (pick looks on the right, then Make), then export it here."
      : cur && cur.state !== "done" ? "This look is still being made. Export it when it's done, or open a finished one."
        : "Open a look (click it in the strip below), or pick some with Space, to export them.");
  btn.querySelector("span").textContent = kept ? `Export ${plural(kept, "pick")}` : "Export";
  btn.title = kept ? "Export the pictures you picked (E)" : "Export this picture (E)";
}

function renderRail() {
  $("#photo-count").textContent = st.photos.length || "";
  $("#rail-empty").hidden = st.photos.length > 0;
  const counts = {};
  for (const s of st.slots) if (s.state === "done") counts[s.photo] = (counts[s.photo] || 0) + 1;
  renderPlayerPanel();
  const hits = new Map((st.player?.results || []).map((h) => [h.photo, h]));
  const shown = st.railShow === "with" ? st.photos.filter((p) => hits.get(p.id)?.status === "sure")
    .sort((a, b) => st.player.results.findIndex((h) => h.photo === a.id) - st.player.results.findIndex((h) => h.photo === b.id))
    : st.railShow === "best" ? st.photos.filter((p) => st.player?.best.includes(p.id))
      .sort((a, b) => st.player.best.indexOf(a.id) - st.player.best.indexOf(b.id)) : st.photos;
  $("#chosen-bar").hidden = !st.chosen.size;
  $("#chosen-bar").innerHTML = `<span><b>${st.chosen.size}</b> chosen</span><button class="chip-btn" id="chosen-clear" title="Un-choose them">Clear</button>`;
  $("#chosen-clear").onclick = () => { st.chosen.clear(); if (st.scope === "chosen") st.scope = "one"; render(); };
  reconcile($("#photo-list"), shown, (p) => p.id, (p) => {
    const b = document.createElement("button");
    b.className = "ph"; b.title = p.name;
    b.innerHTML = `<img src="/img/photo/${p.id}/thumb.jpg" alt="${esc(p.name)}" loading="lazy" draggable="false"><span class="n" hidden></span><span class="badge-best" hidden>★ Best</span><span class="ck" role="checkbox" title="Choose this photo (to make looks on the chosen ones)">${icon("check")}</span><span class="x" role="button" aria-label="Remove ${esc(p.name)}" title="Take this photo out of the app (the file stays where it is)">${icon("x")}</span>`;
    b.onclick = (e) => {
      if (e.target.closest(".x")) { removePhoto(p.id); return; }
      if (e.target.closest(".ck") || e.metaKey || e.shiftKey) {
        st.chosen.has(p.id) ? st.chosen.delete(p.id) : st.chosen.add(p.id);
        if (st.chosen.size && st.scope !== "all") st.scope = "chosen";
        render(); return;
      }
      st.activePhoto = p.id; st.current = null; st.fixing = false; st.view = "single"; render(); renderLooks(true);
    };
    return b;
  }, (b, p) => {
    b.classList.toggle("on", p.id === st.activePhoto);
    b.classList.toggle("chosen", st.chosen.has(p.id));
    const n = b.querySelector(".n");
    n.hidden = !counts[p.id]; n.textContent = counts[p.id] ? plural(counts[p.id], "look") : "";
    const h = hits.get(p.id);
    b.querySelector(".badge-best").hidden = !(h && h.best && h.status === "sure");
  });
}

async function removePhoto(id) {
  await api(`/api/photos/${id}`, undefined, { method: "DELETE" });
  if (st.activePhoto === id) st.activePhoto = null;
  refresh();
}

/* Keeps a container's children in step with a list, by key, without rebuilding the
   ones that stay (so their pictures do not flash). */
function reconcile(container, items, key, create, update) {
  const old = new Map([...container.children].filter((c) => c.dataset.key).map((c) => [c.dataset.key, c]));
  let prev = null;
  for (const item of items) {
    const k = String(key(item));
    let node = old.get(k);
    if (!node) { node = create(item); node.dataset.key = k; } else old.delete(k);
    update(node, item);
    const want = prev ? prev.nextSibling : container.firstChild;
    if (node !== want) container.insertBefore(node, want);
    prev = node;
  }
  old.forEach((n) => n.remove());
  [...container.children].filter((c) => !c.dataset.key).forEach((c) => c.remove());
}

function tileCreate(sheet) {
  return (s) => {
    const b = document.createElement("button");
    b.className = "tile"; b.setAttribute("role", "option");
    b.innerHTML = `<img alt="" draggable="false" hidden><div class="ring" hidden><span></span></div><span class="name"></span><span class="star">${icon("pick")}</span><span class="stars"></span>`
      + (sheet ? `<span class="acts"><span class="k" data-act="keep" title="Pick (Space)">${icon("pickO")}</span><span data-act="export" title="Export this one">${icon("export")}</span><span data-act="delete" title="Remove this look">${icon("trash")}</span></span>` : "");
    b.onclick = (e) => {
      const act = e.target.closest("[data-act]")?.dataset.act;
      if (act === "keep") { toggleKeep([s.id]); return; }
      if (act === "export") { openExport([s.id]); return; }
      if (act === "delete") { deleteLooks([s.id]); return; }
      if ((e.metaKey || e.shiftKey || e.ctrlKey) && slotById(s.id)?.state === "done") { toggleSurvey(s.id); return; }
      st.survey = [];
      select(s.id, sheet);
    };
    b.ondblclick = () => { if (sheet) { st.view = "single"; select(s.id); } };
    return b;
  };
}
function tileUpdate(node, s0) {
  const s = slotById(s0.id) || s0;
  const done = s.state === "done";
  node.classList.toggle("on", s.id === st.current && st.survey.length < 2);
  node.classList.toggle("in-survey", st.survey.includes(s.id));
  node.classList.toggle("kept", !!s.kept);
  node.classList.toggle("pending", !done);
  node.classList.toggle("failed", s.state === "failed");
  node.title = `${s.title}${s.state === "failed" ? " — failed: " + s.error : ""}`;
  const img = node.querySelector("img");
  const ring = node.querySelector(".ring");
  node.querySelector(".name").textContent = s.look;
  node.querySelector(".stars").textContent = s.rating ? "★".repeat(s.rating) : "";
  if (done) {
    const src = slotImg(s, "thumb");
    if (img.getAttribute("src") !== src) img.src = src;
    img.hidden = false; ring.hidden = true;
  } else {
    img.hidden = true; ring.hidden = s.state === "failed";
    ring.classList.toggle("wait", s.state === "wait");
    ring.style.setProperty("--p", s.pct);
    ring.querySelector("span").textContent = s.state === "now" ? `${s.pct}%` : "";
  }
}

function renderStrip() {
  const wrap = $("#strip-wrap");
  wrap.hidden = !st.slots.length || st.mode !== "edit";
  if (wrap.hidden) return;
  const done = doneSlots().length, kept = keptSlots().length, waiting = st.slots.length - done;
  $("#strip-count").innerHTML = `<b>${plural(done, "look")}</b>${waiting ? ` · ${waiting} on the way` : ""}${kept ? ` · <span style="color:var(--gold)">${plural(kept, "pick")}</span>` : ""}`;
  const show = $("#show");
  show.innerHTML = [["all", "All"], ["picks", `Picks (${kept})`], ...[1, 2, 3, 4, 5].map((n) => [String(n), "★".repeat(n) + (n < 5 ? " and up" : "")])]
    .map(([v, l]) => `<option value="${v}" ${st.show === v ? "selected" : ""}>${l}</option>`).join("");
  $("#keep-none").hidden = !kept;
  $("#drop-unpicked").hidden = !kept || kept === done;
  $("#keep-all").hidden = !done || kept === done;
  wrap.classList.toggle("grid", st.view === "grid");
  $("#view-single").classList.toggle("on", st.view === "single");
  $("#view-grid").classList.toggle("on", st.view === "grid");
  reconcile($("#strip"), visibleSlots(), (s) => s.id, tileCreate(false), tileUpdate);
}

function select(id, keepGrid) {
  st.current = id; st.fixing = false; st.zoom.on = false; st.tool = null; st.cropDraft = null; st.areaSel = null; st.textSel = null;
  const s = slotById(id);
  if (s) st.activePhoto = s.photo;
  if (!keepGrid) st.view = "single";
  if (s && s.state === "done" && st.tab === "looks" && !keepGrid) { /* stay on looks: adjusting is one click away */ }
  render();
  $(`#strip [data-key="${id}"]`)?.scrollIntoView({ block: "nearest", inline: "nearest" });
}

// The viewer -----------------------------------------------------------------------------
let viewerSig = "";
function renderViewer() {
  const v = $("#viewer");
  $("#reel").hidden = st.mode !== "reel";
  v.hidden = st.mode === "reel";
  if (st.mode === "reel") { viewerSig = ""; return; }
  const cur = slotById(st.current);
  if (st.view === "grid" && st.slots.length) return renderSheet(v);
  st.survey = st.survey.filter((id) => slotById(id)?.state === "done");
  if (st.survey.length >= 2) return renderSurvey(v);
  v.classList.remove("grid-mode");
  if (!st.photos.length) {
    if (viewerSig === "hero") return;
    viewerSig = "hero";
    v.innerHTML = `<div class="hero"><div class="glyph">${icon("image")}</div>
      <h1>Start with your game photos</h1>
      <p>Drop them anywhere on this window, paste with <kbd>⌘V</kbd>, or choose them. JPG, HEIC and RAW all work, and your originals are never changed.</p>
      <div class="row"><button class="btn primary big" data-add="files">${icon("plus")} Add photos…</button><button class="btn big" data-add="folder">${icon("folder")} Add a folder…</button></div>
      <div class="steps"><span><b>1</b>Add photos</span><span><b>2</b>Pick looks</span><span><b>3</b>Edit the best</span><span><b>4</b>Share</span></div></div>`;
    bindAdd(v);
    return;
  }
  const sig = viewerSignature(cur);
  v.classList.remove("survey-mode");
  if (sig === viewerSig) return updateViewerLive(cur);
  viewerSig = sig;
  if (st.finding) { renderFindPick(v); return; }
  if (cur && cur.state === "done" && st.tool) { renderTool(v, cur); return; }
  if (cur && cur.state === "done") {
    const src = st.fixing ? `/img/slot/${cur.id}/0/fix.jpg?v=${st.fixVer}` : slotImg(cur);
    v.innerHTML = `<div class="frame${st.fixing ? " fixing" : ""}${st.zoom.on ? " zoomed" : ""}" id="frame" style="--split:${st.split}%;${zoomVars()}">
        <div class="layer"><img class="after" src="${src}" alt="${esc(cur.title)}" draggable="false" data-base="${st.fixing ? "" : `${cur.width}x${cur.height}`}"></div>
        ${st.fixing || st.zoom.on || st.compare ? "" : `<div class="texts" id="texts"></div>`}
        ${st.compare && !st.fixing ? `<div class="layer before-layer"><img class="before" src="${slotImg(cur, "before")}" alt="Original" draggable="false"></div>
        <div class="handle"><span>${icon("compare")}</span></div><span class="tag l">Before</span><span class="tag r">After</span>` : ""}
        ${st.zoom.on ? `<span class="tag zoom-tag">${icon("zoom")}<span> Zoomed · double-click or Z to fit</span></span>` : ""}
      </div>
      ${st.fixing ? fixBar() : ""}
      <div class="caption">${toolbar(cur)}</div>`;
    if (st.fixing) fitFrame(cur.base_width, cur.base_height); else fitFrame(cur.width, cur.height);
    paintTexts(cur);
    bindViewer(cur);
    bindPicks(cur);
    watchPicture(cur);
  } else if (cur) {
    v.innerHTML = `<div class="frame" id="frame"><div class="layer"><img class="after" src="/img/photo/${cur.photo}/view.jpg" alt="" draggable="false"></div>
        <div class="wait">${cur.state === "failed" ? `<b>${icon("x")}</b><span>This look could not be made</span><small>${esc(cur.error)}</small>`
        : `<div class="ring${cur.state === "wait" ? " wait" : ""}" style="--p:${cur.pct};width:64px;height:64px;font-size:14px"><span>${cur.state === "now" ? cur.pct + "%" : ""}</span></div>
           <span>${cur.state === "now" ? "Making" : "Waiting to make"} <b style="font-size:inherit">${esc(cur.look)}</b></span><small class="note">${esc(cur.note || "")}</small>`}</div>
      </div><div class="caption">${toolbar(cur)}</div>`;
    fitPhotoFrame();
    bindViewer(cur);
  } else {
    const p = st.photos.find((x) => x.id === st.activePhoto);
    const any = st.looks.length && pickedLooks().length;
    v.innerHTML = `<div class="frame" id="frame"><div class="layer"><img class="after" src="/img/photo/${p.id}/view.jpg" alt="${esc(p.name)}" draggable="false"></div></div>
      <div class="caption"><div class="toolbar"><span class="title"><b>${esc(p.name)}</b><span>original</span></span>
      <span class="sep"></span><button id="edit-photo" title="Edit the photo itself: light, color, crop, remove distractions, text (A)">${icon("sun")} Edit</button>
      ${doneSlots().length ? `<button id="back-to-looks" title="All the looks made so far (G)">${icon("grid")} Looks made</button>` : ""}</div></div>
      ${any ? "" : `<div class="hint-line">Pick looks on the right and press <b>Make</b>, or <b>Edit</b> the photo as it is</div>`}`;
    fitPhotoFrame();
    $("#back-to-looks")?.addEventListener("click", () => { st.view = "grid"; render(); });
    $("#edit-photo").onclick = () => editPhoto(p.id);
  }
  paintIcons(v);
}

const viewerSignature = (cur) => JSON.stringify([cur?.id, cur?.ver, cur?.state, st.compare, st.fixing, st.fixVer,
  st.activePhoto, st.tool, st.areaSel, st.finding]);

function toolbar(cur) {
  const list = visibleSlots();
  const i = list.findIndex((s) => s.id === cur.id);
  const done = cur.state === "done";
  const photo = st.photos.find((p) => p.id === cur.photo);
  return `<div class="toolbar">
    <button data-nav="-1" title="Previous (←)" ${off(i <= 0, "This is the first look.")}>${icon("left")}</button>
    <span class="of">${i < 0 ? "–" : i + 1} / ${list.length}</span>
    <button data-nav="1" title="Next (→)" ${off(i >= list.length - 1, "This is the last look.")}>${icon("right")}</button>
    <span class="sep"></span>
    <span class="title"><b>${esc(cur.look)}</b><span>${esc(photo?.name || "")}</span></span>
    <span class="sep"></span>
    ${done ? `<button data-act="compare" class="${st.compare ? "on" : ""}" title="Compare with the original (C, or hold B)">${icon("compare")}</button>
    <button data-act="edit" title="Edit: light, crop, remove, text (A)">${icon("sun")}<span class="lbl"> Edit</span></button>
    <span class="sep"></span>
    <span class="rating" title="Rate it (1 to 5)">${[1, 2, 3, 4, 5].map((n) => `<button data-rate="${n}" class="${(cur.rating || 0) >= n ? "on" : ""}">${icon("star")}</button>`).join("")}</span>
    <button data-act="keep" class="${cur.kept ? "kept" : ""}" title="Pick it (Space)">${icon(cur.kept ? "pick" : "pickO")}<span class="lbl"> ${cur.kept ? "Picked" : "Pick"}</span></button>
    <span class="sep"></span>
    <button data-act="share" title="AirDrop, Messages, Mail, Photos, Copy">${icon("share")}</button>
    <button data-act="export" title="Export this picture">${icon("export")}</button>
    <button data-act="delete" title="Remove this look (Delete): undo is one click">${icon("trash")}</button>`
    : `<button data-act="remove" title="Remove">${icon("trash")} Remove</button>`}
  </div>`;
}

function fixBar() {
  return `<div class="fixbar toolbar">
    <div class="seg small"><button data-fix="add" class="${st.fixAdd ? "on" : ""}">${icon("plus")} Add</button><button data-fix="remove" class="${st.fixAdd ? "" : "on"}">${icon("x")} Take out</button></div>
    <span class="sep"></span>
    <button data-fix="undo" title="Undo the last click">${icon("undo")}</button>
    <button data-fix="reset">Automatic</button>
    <span class="sep"></span>
    <button data-fix="remake" class="on">Remake this photo's looks</button>
    <button data-fix="done">Done</button></div>`;
}

function updateViewerLive(cur) {
  if (!cur || cur.state === "done") return;
  const ring = $("#viewer .wait .ring");
  if (ring) {
    ring.style.setProperty("--p", cur.pct);
    ring.querySelector("span").textContent = cur.state === "now" ? cur.pct + "%" : "";
  }
  const note = $("#viewer .wait .note");
  if (note) note.textContent = cur.note || "";
}

function fitFrame(w, h) {
  const v = $("#viewer"), f = $("#frame");
  if (!f || !w || !h) return;
  const cs = getComputedStyle(v);
  const aw = v.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  const ah = v.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
  const k = Math.min(aw / w, ah / h);
  f.style.width = `${Math.floor(w * k)}px`; f.style.height = `${Math.floor(h * k)}px`;
  f.style.setProperty("--fw", `${Math.floor(w * k)}px`);
  f.dataset.w = w; f.dataset.h = h;
}
function fitPhotoFrame() {
  const img = $("#frame img.after");
  const go = () => fitFrame(img.naturalWidth, img.naturalHeight);
  if (img.complete && img.naturalWidth) go(); else { img.onload = go; fitFrame(4, 3); }
}
window.addEventListener("resize", () => { const f = $("#frame"); if (f?.dataset.w) fitFrame(+f.dataset.w, +f.dataset.h); });

function bindViewer(cur) {
  const v = $("#viewer");
  v.querySelectorAll("[data-nav]").forEach((b) => b.onclick = () => step(+b.dataset.nav));
  v.querySelectorAll("[data-rate]").forEach((b) => b.onclick = () => rate([cur.id], +b.dataset.rate === cur.rating ? 0 : +b.dataset.rate));
  v.querySelectorAll("[data-act]").forEach((b) => b.onclick = () => {
    const a = b.dataset.act;
    if (a === "compare") { st.compare = !st.compare; renderViewer(); if (st.zoom.on) sharpen(cur); }
    if (a === "keep") toggleKeep([cur.id]);
    if (a === "export") openExport([cur.id]);
    if (a === "edit") { st.tab = "edit"; renderTabs(); }
    if (a === "share") shareMenu(cur, b);
    if (a === "remove" || a === "delete") deleteLooks([cur.id]);
    if (a === "copy") copyPicture(cur);
  });
  const f = $("#frame");
  if (f && !st.fixing && cur.state === "done") {
    const split = (e) => {
      const r = f.getBoundingClientRect();
      st.split = Math.max(0, Math.min(100, ((e.clientX - r.left) / r.width) * 100));
      f.style.setProperty("--split", st.split + "%");
    };
    let last = null;
    const pan = (e) => {
      const r = f.getBoundingClientRect(), k = st.zoom.k - 1;
      st.zoom.x = Math.max(0, Math.min(100, st.zoom.x - ((e.clientX - last.x) / r.width) * 100 / k));
      st.zoom.y = Math.max(0, Math.min(100, st.zoom.y - ((e.clientY - last.y) / r.height) * 100 / k));
      last = { x: e.clientX, y: e.clientY };
      f.style.cssText += zoomVars();
    };
    f.onpointerdown = (e) => {
      if (e.button !== 0) return;
      f.setPointerCapture(e.pointerId);
      if (st.compare && (e.target.closest(".handle") || !st.zoom.on)) { split(e); f.onpointermove = split; }
      else if (st.zoom.on) { last = { x: e.clientX, y: e.clientY }; f.classList.add("panning"); f.onpointermove = pan; }
    };
    f.onpointerup = () => { f.onpointermove = null; f.classList.remove("panning"); };
    f.ondblclick = (e) => {
      const r = f.getBoundingClientRect();
      toggleZoom(((e.clientX - r.left) / r.width) * 100, ((e.clientY - r.top) / r.height) * 100);
    };
  }
  if (st.fixing && f) {
    f.onclick = async (e) => {
      const r = f.getBoundingClientRect();
      await api(`/api/slots/${cur.id}/fix`, { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height, add: st.fixAdd });
      st.fixVer++; renderViewer();
    };
    v.querySelectorAll("[data-fix]").forEach((b) => b.onclick = async (e) => {
      e.stopPropagation();
      const a = b.dataset.fix;
      if (a === "add" || a === "remove") { st.fixAdd = a === "add"; viewerSig = ""; renderViewer(); return; }
      if (a === "done") { st.fixing = false; renderViewer(); return; }
      if (a === "undo" || a === "reset") {
        await api(`/api/slots/${cur.id}/fix`, { [a]: true }); st.fixVer++; renderViewer(); return;
      }
      if (a === "remake") {
        st.fixing = false; renderViewer();
        const t = toast("Remaking this photo's looks with the fixed cut-out…", { sticky: true, spin: true });
        try { const r = await api(`/api/slots/${cur.id}/remake`, {}); t.done(`Remade ${plural(r.count, "look")}`); }
        catch { t.close(); }
        refresh();
      }
    });
  }
}

function zoomVars() {
  return `--zk:${st.zoom.on ? st.zoom.k : 1};--zx:${st.zoom.x}%;--zy:${st.zoom.y}%;`;
}
function toggleZoom(x = 50, y = 50) {
  const cur = slotById(st.current);
  if (!cur || cur.state !== "done" || st.fixing) return;
  st.zoom.on = !st.zoom.on;
  if (st.zoom.on) { st.zoom.x = x; st.zoom.y = y; }
  viewerSig = ""; renderViewer();
  if (st.zoom.on) sharpen(cur);
}
/* Zoomed in, the look is made again at a bigger size, so faces and focus can be judged. */
function sharpen(cur) {
  const f = $("#frame"), tag = $("#frame .zoom-tag");
  if (tag) tag.lastChild.textContent = " Sharpening…";
  const load = (sel, kind) => new Promise((res) => {
    const img = $(sel); if (!img) return res();
    const big = new Image();
    big.onload = () => { if (st.zoom.on && st.current === cur.id && img.isConnected) img.src = big.src; res(); };
    big.onerror = res;
    big.src = `/img/zoom/${cur.id}/${cur.ver}/${kind}.jpg`;
  });
  Promise.all([load("#frame img.after", "after"), st.compare ? load("#frame img.before", "before") : null]).then(() => {
    const t = $("#frame .zoom-tag");
    if (t && f?.isConnected) t.lastChild.textContent = " Zoomed · double-click or Z to fit";
  });
}

function shareMenu(cur, anchor) {
  closeMenus();
  $("#share-menu")?.remove();
  const m = document.createElement("div");
  m.className = "share-menu menu-like"; m.id = "share-menu";
  m.innerHTML = [["airdrop", "airdrop", "AirDrop", "To your iPhone, full size"], ["messages", "message", "Messages", ""],
    ["mail", "mail", "Mail", ""], ["photos", "photos", "Add to Photos", "Reaches your iPhone through iCloud"], ["copy", "clip", "Copy", "⌘C"]]
    .map(([k, ic, l, sub]) => `<button data-share="${k}">${icon(ic)}<span>${l}${sub ? `<small>${sub}</small>` : ""}</span></button>`).join("");
  document.body.appendChild(m);
  const r = anchor.getBoundingClientRect();
  Object.assign(m.style, { position: "fixed", left: `${Math.min(r.left, innerWidth - 260)}px`, right: "auto", width: "250px", top: "auto", bottom: `${innerHeight - r.top + 8}px` });
  m.querySelectorAll("[data-share]").forEach((b) => b.onclick = async (e) => {
    e.stopPropagation(); m.remove();
    if (b.dataset.share === "copy") return copyPicture(cur);
    await api(`/api/slots/${cur.id}/share`, { service: b.dataset.share });
    refresh();
  });
  setTimeout(() => document.addEventListener("click", () => m.remove(), { once: true }), 0);
}

/* Takes looks out, with an Undo right there (and the next look opens). */
async function deleteLooks(ids) {
  if (!ids.length) return;
  const list = visibleSlots(), at = list.findIndex((s) => s.id === st.current);
  const r = await api("/api/slots/remove", { ids });
  if (ids.includes(st.current)) {
    const rest = list.filter((s) => !ids.includes(s.id));
    st.current = rest.length ? rest[Math.min(Math.max(at, 0), rest.length - 1)].id : null;
    st.tool = null; st.fixing = false;
  }
  viewerSig = ""; await refresh();
  const gone = r.removed || [];
  if (gone.length) toast(gone.length === 1 ? "Look removed" : `${plural(gone.length, "look")} removed`, {
    action: { label: "Undo", run: async () => { await api("/api/slots/restore", { ids: gone }); viewerSig = ""; refresh(); } } });
}

async function rate(ids, rating) {
  ids.forEach((id) => { const s = slotById(id); if (s) s.rating = rating; });
  viewerSig = ""; render();
  await api("/api/slots/rate", { ids, rating });
}

async function copyPicture(s) {
  try {
    const blob = await fetch(slotImg(s, "full")).then((r) => r.blob());
    const bmp = await createImageBitmap(blob);
    const c = document.createElement("canvas");
    c.width = bmp.width; c.height = bmp.height;
    c.getContext("2d").drawImage(bmp, 0, 0);
    const png = await new Promise((res) => c.toBlob(res, "image/png"));
    await navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
    toast("Copied", { small: "Paste into Messages, Mail or a post. Export saves it full size." });
  } catch {
    toast("Could not copy here; use Export instead", { bad: true });
  }
}

function toggleSurvey(id) {
  if (!st.survey.length && st.current && st.current !== id && slotById(st.current)?.state === "done") st.survey = [st.current];
  st.survey = st.survey.includes(id) ? st.survey.filter((x) => x !== id) : [...st.survey, id].slice(-6);
  if (st.survey.length >= 2 && st.view === "grid") { /* the sheet's head offers to open them */ }
  viewerSig = ""; render();
}

function renderSurvey(v) {
  const ids = st.survey;
  const sig = "survey:" + ids.map((id) => id + ":" + slotById(id).ver + ":" + slotById(id).kept).join(",");
  if (sig === viewerSig) return;
  viewerSig = sig;
  v.classList.remove("grid-mode"); v.classList.add("survey-mode");
  const cols = ids.length <= 3 ? ids.length : ids.length === 4 ? 2 : 3;
  v.innerHTML = `<div class="survey" style="--cols:${cols}">${ids.map((id) => {
    const s = slotById(id), photo = st.photos.find((p) => p.id === s.photo);
    return `<div class="cell${s.kept ? " kept" : ""}" data-id="${id}"><img src="${slotImg(s, "full")}" alt="${esc(s.title)}" draggable="false">
      <div class="cell-bar"><span><b>${esc(s.look)}</b> ${esc(photo?.name || "")}</span>
        <button data-k="${id}" class="${s.kept ? "kept" : ""}" title="Pick">${icon(s.kept ? "pick" : "pickO")}</button>
        <button data-x="${id}" title="Take out of the comparison">${icon("x")}</button></div></div>`;
  }).join("")}</div>
  <div class="caption"><div class="toolbar"><span class="title"><b>Comparing ${ids.length}</b><span>⌘-click pictures to add or take out · click one to open it</span></span>
    <span class="sep"></span><button id="sv-keep">${icon("pick")} Pick all ${ids.length}</button><button id="sv-done">Done</button></div></div>`;
  paintIcons(v);
  v.querySelectorAll(".cell").forEach((c) => c.onclick = (e) => {
    const id = +c.dataset.id;
    if (e.target.closest("[data-k]")) { toggleKeep([id]); return; }
    if (e.target.closest("[data-x]")) { toggleSurvey(id); return; }
    if (e.metaKey || e.shiftKey) { toggleSurvey(id); return; }
    st.survey = []; select(id);
  });
  $("#sv-keep").onclick = () => { const off = ids.filter((id) => !slotById(id).kept); toggleKeep(off.length ? off : ids); };
  $("#sv-done").onclick = () => { st.survey = []; viewerSig = ""; render(); };
}

function notify(title, body) {
  if (document.hasFocus() && !document.hidden) return;
  api("/api/notify", { title, body }).catch(() => {});
}

function step(d) {
  const list = visibleSlots();
  const i = list.findIndex((s) => s.id === st.current);
  const next = list[Math.max(0, Math.min(list.length - 1, (i < 0 ? 0 : i + d)))];
  if (next) select(next.id, st.view === "grid");
}

function renderSheet(v) {
  if (!v.classList.contains("grid-mode")) {
    v.classList.add("grid-mode");
    v.innerHTML = `<div class="sheet-head"><h3>All looks</h3><span>Click to star the keepers, double-click to open one</span></div><div class="sheet" id="sheet"></div>`;
    viewerSig = "grid";
  }
  const done = doneSlots().length;
  v.querySelector(".sheet-head span").textContent = done
    ? `${plural(done, "look")} · pick the keepers · ⌘-click to compare side by side · double-click to open` : "Your looks appear here as they are made";
  let cmp = v.querySelector("#sheet-compare");
  if (!cmp) {
    cmp = document.createElement("button"); cmp.id = "sheet-compare"; cmp.className = "btn primary";
    cmp.onclick = () => { st.view = "single"; viewerSig = ""; render(); };
    v.querySelector(".sheet-head").appendChild(cmp);
  }
  cmp.hidden = st.survey.length < 2;
  cmp.textContent = `Compare ${st.survey.length} side by side`;
  reconcile($("#sheet"), visibleSlots(), (s) => s.id, tileCreate(true), tileUpdate);
  paintIcons(v);
}

// Keeping and exporting ---------------------------------------------------------------------
async function toggleKeep(ids) {
  const on = !ids.every((id) => slotById(id)?.kept);
  ids.forEach((id) => { const s = slotById(id); if (s) s.kept = on; });
  viewerSig = ""; render();
  await api("/api/slots/keep", { ids, on });
}

function openExport(ids) {
  ids = ids.filter((id) => slotById(id)?.state === "done");
  if (!ids.length) return;
  const p = st.prefs;
  const sel = { how: p.how || "files", kind: p.kind || "jpeg", sizes: new Set(p.sizes || ["full"]), folder: p.folder,
    mark: Object.assign({ on: false, text: "", style: "corner", opacity: 0.5 }, p.watermark || {}),
    logo: Object.assign({ on: false, id: st.kit?.[0]?.id, corner: "br", size: 0.16, color: "auto" }, p.logo || {}) };
  if (!st.kit?.some((k) => k.id === sel.logo.id)) sel.logo.id = st.kit?.[0]?.id;
  const c = st.credit || {};
  const n = ids.length;
  const thumbs = ids.slice(0, 5).map((id) => `<img src="${slotImg(slotById(id), "thumb")}" alt="">`).join("");
  const m = modal(`<header><h2>Export ${plural(n, "picture")}</h2><div class="thumbs">${thumbs}</div></header>
    <div class="body">
      <div class="fld"><label>Save to</label><div class="path"><code id="x-folder"></code><button class="btn" id="x-change">Change…</button></div></div>
      <div class="fld"><label>As</label><div class="seg full" id="x-how"><button data-v="files" title="In a new folder of their own">${icon("image")} Separate files</button><button data-v="zip">${icon("layers")} One zip file</button></div></div>
      <div class="fld"><label>Sizes <span style="color:var(--faint);font-weight:400">· each cropped around the players</span></label><div class="chips" id="x-sizes">
        ${st.sizes.map((s) => `<button data-v="${s.key}" title="${esc(s.label)}">${esc(s.short)}</button>`).join("")}</div></div>
      <div class="fld"><label>File type</label><div class="seg full" id="x-kind"><button data-v="jpeg">JPEG</button><button data-v="tiff">16-bit TIFF</button><button data-v="both">Both</button></div>
        <small class="notes" id="x-kind-note"></small></div>
      ${(st.kit || []).length ? `<div class="fld"><label class="toggle"><input type="checkbox" id="x-logo" ${sel.logo.on ? "checked" : ""}><span><b>Add my logo</b><small>On every picture that has none placed</small></span></label>
        <div id="x-logo-box" class="fld" ${sel.logo.on ? "" : "hidden"}>
          <div class="kit-grid small" id="x-logo-pick">${st.kit.map((k) => `<button class="kit-logo" data-v="${k.id}" title="${esc(k.name)}"><img src="/img/logo/${enc(k.id)}/original.png" alt=""></button>`).join("")}</div>
          <div class="seg full small" id="x-logo-corner">${[["tl", "Top left"], ["tr", "Top right"], ["bl", "Bottom left"], ["br", "Bottom right"]].map(([v, t]) => `<button data-v="${v}">${t}</button>`).join("")}</div>
          <div class="seg full small" id="x-logo-color">${[["auto", "Auto"], ["original", "As it is"], ["white", "White"], ["black", "Black"]].map(([v, t]) => `<button data-v="${v}">${t}</button>`).join("")}</div>
          <div class="slider"><label>Size</label><output id="x-logo-size-v"></output><input type="range" id="x-logo-size" min="0.06" max="0.4" step="0.01" value="${sel.logo.size}"></div>
        </div></div>` : ""}
      <details class="more"><summary>${icon("chev")} Your name, copyright, watermark and more</summary><div class="inner">
        <div class="fld"><div class="two"><input class="field" id="x-creator" placeholder="Photographer" value="${esc(c.creator || "")}"><input class="field" id="x-contact" placeholder="Email, website or @handle" value="${esc(c.contact || "")}"></div></div>
        <input class="field" id="x-copy" placeholder="Copyright (empty: © year taken, your name)" value="${esc(c.copyright || "")}">
        <label class="toggle"><input type="checkbox" id="x-recipes" ${p.recipes ? "checked" : ""}><span><b>Also save how each was made</b><small>A small .json file beside each picture (its look, edits and settings)</small></span></label>
        <label class="toggle"><input type="checkbox" id="x-mark" ${sel.mark.on ? "checked" : ""}><span><b>Add a watermark</b><small>For client proofs and posts</small></span></label>
        <div id="x-mark-box" class="fld" ${sel.mark.on ? "" : "hidden"}>
          <div class="seg full" id="x-style"><button data-v="corner">Corner</button><button data-v="across">Across (proofs)</button></div>
          <input class="field" id="x-mtext" placeholder="Text (empty: your copyright)" value="${esc(sel.mark.text || "")}">
          <div class="slider"><label>Strength</label><output id="x-op-v"></output><input type="range" id="x-op" min="0.1" max="1" step="0.05" value="${sel.mark.opacity}"></div>
        </div></div></details>
    </div>
    <footer><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="x-go">${icon("export")} Export ${plural(n, "picture")}</button></footer>`);
  const KIND_NOTE = { jpeg: "Full size, sRGB. For the web, Instagram and clients.", tiff: "16 bits from RAW photos, for big prints and editing. About 6 times bigger.", both: "A JPEG and a 16-bit TIFF of each." };
  const paint = () => {
    $("#x-folder", m).textContent = (sel.folder || "").replace(/^\/Users\/[^/]+/, "~");
    $$("#x-how button", m).forEach((b) => b.classList.toggle("on", b.dataset.v === sel.how));
    $$("#x-kind button", m).forEach((b) => b.classList.toggle("on", b.dataset.v === sel.kind));
    $$("#x-style button", m).forEach((b) => b.classList.toggle("on", b.dataset.v === sel.mark.style));
    $$("#x-sizes button", m).forEach((b) => b.classList.toggle("on", sel.sizes.has(b.dataset.v)));
    $("#x-kind-note", m).textContent = KIND_NOTE[sel.kind];
    $("#x-op-v", m).textContent = Math.round(sel.mark.opacity * 100) + "%";
    $$("#x-logo-pick button", m).forEach((b) => b.classList.toggle("on", b.dataset.v === sel.logo.id));
    $$("#x-logo-corner button", m).forEach((b) => b.classList.toggle("on", b.dataset.v === sel.logo.corner));
    $$("#x-logo-color button", m).forEach((b) => b.classList.toggle("on", b.dataset.v === sel.logo.color));
    if ($("#x-logo-size-v", m)) $("#x-logo-size-v", m).textContent = Math.round(sel.logo.size * 100) + "%";
    setOff($("#x-go", m), !sel.sizes.size, "Choose at least one size above.");
  };
  $$("#x-how button", m).forEach((b) => b.onclick = () => { sel.how = b.dataset.v; paint(); });
  $$("#x-kind button", m).forEach((b) => b.onclick = () => { sel.kind = b.dataset.v; paint(); });
  $$("#x-style button", m).forEach((b) => b.onclick = () => { sel.mark.style = b.dataset.v; paint(); });
  $$("#x-sizes button", m).forEach((b) => b.onclick = () => {
    sel.sizes.has(b.dataset.v) ? sel.sizes.delete(b.dataset.v) : sel.sizes.add(b.dataset.v); paint();
  });
  $("#x-mark", m).onchange = (e) => { sel.mark.on = e.target.checked; $("#x-mark-box", m).hidden = !sel.mark.on; };
  $("#x-op", m).oninput = (e) => { sel.mark.opacity = +e.target.value; paint(); };
  $("#x-logo", m)?.addEventListener("change", (e) => { sel.logo.on = e.target.checked; $("#x-logo-box", m).hidden = !sel.logo.on; });
  $$("#x-logo-pick button", m).forEach((b) => b.onclick = () => { sel.logo.id = b.dataset.v; paint(); });
  $$("#x-logo-corner button", m).forEach((b) => b.onclick = () => { sel.logo.corner = b.dataset.v; paint(); });
  $$("#x-logo-color button", m).forEach((b) => b.onclick = () => { sel.logo.color = b.dataset.v; paint(); });
  $("#x-logo-size", m)?.addEventListener("input", (e) => { sel.logo.size = +e.target.value; paint(); });
  $("#x-change", m).onclick = async () => {
    const r = await api("/api/folder/choose", { folder: sel.folder });
    if (r.folder) { sel.folder = r.folder; paint(); }
  };
  $("#x-go", m).onclick = async () => {
    const body = { ids, how: sel.how, kind: sel.kind, sizes: [...sel.sizes], folder: sel.folder,
      credit: { creator: $("#x-creator", m).value, contact: $("#x-contact", m).value, copyright: $("#x-copy", m).value },
      watermark: { on: sel.mark.on, text: $("#x-mtext", m).value, style: sel.mark.style, opacity: sel.mark.opacity },
      logo: { ...sel.logo, on: sel.logo.on && !!sel.logo.id }, recipes: $("#x-recipes", m).checked };
    st.prefs.recipes = body.recipes;
    closeModal();
    await api("/api/export", body);
    refresh();
  };
  paint();
}

// Modal and toasts ------------------------------------------------------------------------
function modal(html) {
  const root = $("#modal-root");
  root.innerHTML = `<div class="scrim"><div class="modal" role="dialog" aria-modal="true">${html}</div></div>`;
  paintIcons(root);
  const scrim = $(".scrim", root);
  scrim.onclick = (e) => { if (e.target === scrim || e.target.closest("[data-close]")) closeModal(); };
  setTimeout(() => $(".modal button.primary, .modal input", root)?.focus(), 30);
  return $(".modal", root);
}
const closeModal = () => { $("#modal-root").innerHTML = ""; };
const modalOpen = () => !!$("#modal-root").firstChild;

function toast(text, { bad = false, sticky = false, spin = false, action = null, small = "" } = {}) {
  const t = document.createElement("div");
  t.className = "toast" + (bad ? " bad" : "");
  const paint = (msg, sub, withSpin, act) => {
    t.innerHTML = `${withSpin ? '<span class="spin"></span>' : ""}<div class="msg">${esc(msg)}${sub ? `<small>${esc(sub)}</small>` : ""}</div>`
      + (act ? `<button class="btn">${esc(act.label)}</button>` : "") + `<button class="icon-btn" aria-label="Close">${icon("x")}</button><span class="bar"></span>`;
    if (act) t.querySelector(".btn").onclick = act.run;
    t.querySelector(".icon-btn").onclick = () => t.remove();
  };
  paint(text, small, spin, action);
  $("#toasts").appendChild(t);
  if (!sticky) setTimeout(() => t.remove(), bad ? 7000 : 4500);
  return {
    el: t,
    update(msg, sub, frac) { paint(msg, sub, true, null); t.querySelector(".bar").style.width = `${(frac * 100).toFixed(0)}%`; },
    done(msg, sub = "", act = null) { paint(msg, sub, false, act); setTimeout(() => t.remove(), 9000); },
    fail(msg) { t.classList.add("bad"); paint(msg, "", false, null); setTimeout(() => t.remove(), 9000); },
    close() { t.remove(); },
  };
}

const taskToasts = new Map();
function renderTasks() {
  for (const task of st.tasks) {
    let t = taskToasts.get(task.id);
    if (t === "finished") continue;
    const what = { reel: "Making the reel", share: "Getting it ready to share", find: "Looking for your player" }[task.kind] || "Exporting full size";
    if (task.state === "running") {
      if (!t) { t = toast(what, { sticky: true, spin: true }); taskToasts.set(task.id, t); }
      t.update(`${what} · ${task.done} of ${task.total}`, task.now, task.total ? task.done / task.total : 0);
    } else {
      if (!t) { taskToasts.set(task.id, "finished"); continue; }  // finished before this page saw it
      if (task.state === "done" && task.kind === "share") t.done(task.message);
      else if (task.state === "done" && task.kind === "find") { t.done(task.message); st.railShow = "with"; refresh(); }
      else if (task.state === "done") {
        t.done(task.message, "", { label: "Show in Finder", run: () => api("/api/reveal", { path: task.path }) });
        notify(task.kind === "reel" ? "Your reel is ready" : "Export finished", task.message);
      }
      else t.fail(task.message);
      taskToasts.set(task.id, "finished");
      if (task.kind === "reel" && st.reelTask === task.id) renderReel(true);
    }
  }
}

// Looks ---------------------------------------------------------------------------------------
const pickedLooks = () => st.looks.filter((l) => st.picked.has(l.name));
st.picked = new Set(store.get("looks", []));

function renderLooks(full = false) {
  const f = $("#look-filters");
  f.innerHTML = st.groups.map((g) => `<button class="${g === st.filter ? "on" : ""}" data-g="${esc(g)}">${esc(g)}</button>`).join("");
  f.querySelectorAll("button").forEach((b) => b.onclick = () => { st.filter = b.dataset.g; store.set("filter", st.filter); renderLooks(true); });
  const q = st.query.trim().toLowerCase();
  const shown = st.looks.filter((l) => (st.filter === "All" || l.group === st.filter)
    && (!q || (l.name + " " + l.about + " " + l.group).toLowerCase().includes(q)));
  const grid = $("#look-grid");
  if (full) {
    let html = "", group = null;
    for (const l of shown) {
      if (st.filter === "All" && l.group !== group) { group = l.group; html += `<h4 class="group-title">${esc(group)}</h4>`; }
      html += lookCard(l);
    }
    grid.innerHTML = html || `<div class="no-looks">No looks match “${esc(st.query)}”.</div>`;
    paintIcons(grid);
    grid.querySelectorAll(".look").forEach((b) => {
      b.onmouseenter = () => tryOn(b.dataset.name);
      b.onmouseleave = tryOff;
    });
    grid.querySelectorAll(".look").forEach((b) => b.onclick = () => {
      const n = b.dataset.name;
      st.picked.has(n) ? st.picked.delete(n) : st.picked.add(n);
      store.set("looks", [...st.picked]);
      renderLooks(); renderMake();
      if (!st.current) { viewerSig = ""; renderViewer(); }
    });
    watchSwatches();
  }
  const order = pickedLooks().map((l) => l.name);
  grid.querySelectorAll(".look").forEach((b) => {
    const on = st.picked.has(b.dataset.name);
    b.classList.toggle("on", on);
    b.querySelector(".check").innerHTML = on ? String(order.indexOf(b.dataset.name) + 1) : "";
  });
}

/* Resting the pointer on a look's card shows it on the big photo, full size, at once. */
let tryTimer = null, tryName = null;
function tryOn(name) {
  clearTimeout(tryTimer);
  const l = lookByName(name), cur = slotById(st.current);
  if (!l || !st.activePhoto || st.mode !== "edit" || st.view === "grid" || st.fixing || st.survey.length >= 2) return;
  if (cur && cur.photo !== st.activePhoto) return;
  tryName = name;
  tryTimer = setTimeout(() => {
    const f = $("#frame");
    if (!f || tryName !== name) return;
    let ov = f.querySelector(".tryon");
    if (!ov) { ov = document.createElement("div"); ov.className = "tryon"; f.appendChild(ov); }
    if (l.ai || l.design) {
      ov.classList.toggle("ready", !!l.example);
      ov.innerHTML = `${l.example ? `<img src="/img/example/${enc(name)}.jpg" alt="">` : ""}<span class="tag l">${esc(name)} · ${l.design ? "your design as saved: press Make to put this photo in it" : "an AI look: an example, press Make to see it on this photo"}</span>`;
      return;
    }
    ov.innerHTML = `<span class="tag l"><span class="spin"></span> ${esc(name)}</span>`;
    const img = new Image();
    img.onload = () => {
      if (tryName !== name || !ov.isConnected) return;
      ov.innerHTML = `<span class="tag l">Trying on · <b>${esc(name)}</b></span>`;
      ov.classList.add("ready");
      ov.prepend(img);
    };
    img.src = `/img/try/${st.activePhoto}/${enc(name)}.jpg?edits=${editKey() ? 1 : 0}&v=${enc(editKey())}`;
  }, 140);
}
function tryOff() {
  clearTimeout(tryTimer); tryName = null;
  $("#frame .tryon")?.remove();
}

function lookCard(l) {
  // its latest picture (made whenever the look is used), until your photo's own is ready
  const art = `<span class="ph-art" style="background:${gradientFor(l.name)}">${esc(initials(l.name))}</span>
    <img src="/img/example/${enc(l.name)}.jpg?v=${pageStamp}" alt="" loading="lazy" draggable="false" onerror="this.hidden=true"
      onload="this.previousElementSibling?.remove()"><span class="coming" hidden></span>`;
  return `<button class="look" data-name="${esc(l.name)}">
    <div class="pic">${art}<span class="check"></span>
      <span class="badge">${l.ai ? '<span class="ai">AI</span>' : ""}<span>${short(l.secs)}</span></span></div>
    <div class="label" data-tip-look="${esc(l.name)}"><b>${esc(l.name)}</b><small>${esc(l.about)}</small></div></button>`;
}
const pageStamp = Date.now();
const initials = (n) => n.split(/\s+/).filter((w) => /^[A-Za-z]/.test(w)).slice(0, 2).map((w) => w[0]).join("");
function gradientFor(name) {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `linear-gradient(135deg, hsl(${h} 45% 22%), hsl(${(h + 50) % 360} 55% 14%))`;
}

/* Each quick look is shown on the photo you are working on, as its card scrolls into view
   (the AI looks show their latest picture instead: they take 20 s each). The page asks the
   app every second which are ready, then shows them; "preview coming" until then. */
/* The edit the look previews start from ("" = the photo as shot): with "From: My edit" on and the photo edited. */
function stalePreviews() {
  if (st.tab === "looks" && st.gridEdit !== undefined && st.gridEdit !== editKey()) renderLooks(true);
}
function editKey(pid = st.activePhoto) {
  const p = st.photos.find((x) => x.id === pid);
  return st.fromEdits && p?.edit ? p.edit : "";
}
let swatchObserver = null, swatchWanted = new Map(), swatchTimer = null, swatchSince = 0;
function watchSwatches() {
  swatchObserver?.disconnect();
  swatchWanted = new Map(); clearTimeout(swatchTimer);
  const pid = st.activePhoto;
  st.gridEdit = editKey();
  if (!pid) return;
  swatchSince = Date.now();
  swatchObserver = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      swatchObserver.unobserve(e.target);
      const card = e.target, l = lookByName(card.dataset.name);
      if (!l || l.ai || l.design) continue;
      swatchWanted.set(l.name, card);
      const coming = card.querySelector(".coming");
      coming.hidden = false; coming.textContent = "Preview coming…";
      card.querySelector("img").classList.add("loading");
    }
    pollSwatches(pid);
  }, { root: $("#look-grid"), rootMargin: "200px" });
  $$("#look-grid .look").forEach((c) => swatchObserver.observe(c));
}
async function pollSwatches(pid) {
  clearTimeout(swatchTimer);
  if (!swatchWanted.size || st.activePhoto !== pid) return;
  let r;
  try {  // quietly: a hiccup here just means asking again
    r = await fetch(`/api/swatches/${pid}`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ names: [...swatchWanted.keys()], edits: !!editKey(pid) }) }).then((x) => x.json());
  } catch { r = {}; }
  r.ready ||= []; r.failed ||= [];
  if (st.activePhoto !== pid) return;
  for (const name of [...r.ready, ...r.failed]) {
    const card = swatchWanted.get(name);
    swatchWanted.delete(name);
    if (!card?.isConnected) continue;
    const img = card.querySelector("img"), coming = card.querySelector(".coming");
    if (r.failed.includes(name)) { img.classList.remove("loading"); coming.hidden = true; continue; }
    const live = new Image();
    live.onload = () => {
      if (st.activePhoto !== pid || !card.isConnected) return;
      img.src = live.src; img.hidden = false; img.classList.remove("loading"); coming.hidden = true;
      card.querySelector(".ph-art")?.remove();
    };
    live.src = `/img/swatch/${pid}/${enc(name)}.jpg?e=${enc(r.token || "")}&t=${Date.now()}`;
  }
  if (swatchWanted.size) swatchTimer = setTimeout(() => pollSwatches(pid), 1000);
}

function estimate(looks, photos) {
  let total = looks.reduce((a, l) => a + l.secs, 0) * photos;
  if (looks.some((l) => l.cutout)) total += MEASURE.CUT_OUT * photos;
  if (looks.some((l) => l.ai) && !st.modelsLoaded) total += MEASURE.MODEL_LOAD;
  return total;
}

function renderMake() {
  const box = $("#make");
  const looks = pickedLooks();
  const many = st.photos.length > 1;
  const photos = st.scope === "all" ? st.photos.length : st.scope === "chosen" ? st.chosen.size : 1;
  const n = looks.length * photos;
  const can = st.photos.length && n;
  const targets = st.scope === "all" ? st.photos : st.scope === "chosen" ? st.photos.filter((p) => st.chosen.has(p.id)) : st.photos.filter((p) => p.id === st.activePhoto);
  const edited = targets.some((p) => p.edited);
  box.innerHTML = `
    ${many ? `<div class="row"><span>Photos</span><div class="seg full" id="m-scope">
      <button data-v="one" class="${st.scope === "one" ? "on" : ""}" title="Try looks on one photo first">This photo</button>
      ${st.chosen.size ? `<button data-v="chosen" class="${st.scope === "chosen" ? "on" : ""}" title="The photos you chose (✓ on them)">Chosen ${st.chosen.size}</button>` : ""}
      <button data-v="all" class="${st.scope === "all" ? "on" : ""}" title="Make the looks on every photo">All ${st.photos.length}</button></div></div>` : ""}
    <div class="row"><span>Framing</span><div class="seg full" id="m-crop">${CROPS.map(([v, label]) => `<button data-v="${v}" class="${st.crop === v ? "on" : ""}">${label}</button>`).join("")}</div></div>
    <p class="crop-hint" id="m-crop-hint">${esc(cropHint(st.crop))}</p>
    ${edited ? `<div class="row"><span>From</span><div class="seg full" id="m-from">
      <button data-v="1" class="${st.fromEdits ? "on" : ""}" title="The looks go on top of your edits (light, color, crop, removals): darken the player, then add Stadium Lights for a night shot">My edit</button>
      <button data-v="0" class="${st.fromEdits ? "" : "on"}" title="The looks start from the photo as shot, your edits left out">Original photo</button></div></div>
      <p class="crop-hint">${st.fromEdits ? (photos > 1 ? "Photos you edited keep your edits under the look." : "The look goes on top of your edits.") : "Your edits are left out of these looks."}</p>` : ""}
    <div class="summary">${looks.length ? `<span><b>${plural(looks.length, "look")}</b> picked · <button id="m-clear">Clear</button></span><span>${n > 0 ? say(estimate(looks, photos)) : ""}</span>`
      : `<span>Tap looks to pick them</span>`}</div>
    <div class="inline"><button class="btn primary big wide" id="m-go" ${off(!can, !st.photos.length ? "Add a photo first: drop one on the window, paste it, or press + at the top left." : "Tap one or more looks above to pick them, then Make.")}>${n ? `Make ${plural(n, "look")}` : "Make looks"}</button>
      <button class="btn big" id="m-random" title="Surprise me: six random looks, to discover new styles" ${off(!st.photos.length, "Add a photo first: drop one on the window, paste it, or press + at the top left.")}>${icon("dice")}</button></div>`;
  paintIcons(box);
  box.querySelectorAll("#m-scope button").forEach((b) => b.onclick = () => { st.scope = b.dataset.v; renderMake(); });
  box.querySelectorAll("#m-crop button").forEach((b) => {
    b.onclick = () => { st.crop = b.dataset.v; store.set("crop", st.crop); renderMake(); };
    b.onmouseenter = () => { $("#m-crop-hint").textContent = cropHint(b.dataset.v); previewFrame(b.dataset.v); };
    b.onmouseleave = () => { $("#m-crop-hint").textContent = cropHint(st.crop); previewFrame(null); };
  });
  box.querySelectorAll("#m-from button").forEach((b) => b.onclick = () => {
    st.fromEdits = b.dataset.v === "1"; store.set("fromEdits", st.fromEdits); renderMake(); renderLooks(true);
  });
  $("#m-clear", box)?.addEventListener("click", () => { st.picked.clear(); store.set("looks", []); renderLooks(); renderMake(); });
  $("#m-go", box).onclick = () => make({ looks: looks.map((l) => l.name) });
  $("#m-random", box).onclick = () => make({ random: 6 });
}

function cropHint(v) {
  const [, label, tip] = CROPS.find((c) => c[0] === v) || CROPS[0];
  return `${label}: ${tip}.`;
}

/* Hovering a framing choice draws where it would cut the photo, on the big picture. */
const frameBoxes = {};
async function previewFrame(kind) {
  $("#frame .frame-preview")?.remove();
  const f = $("#frame"), cur = slotById(st.current), pid = st.activePhoto;
  if (!kind || !f || !pid || st.tool || st.fixing || st.view === "grid" || st.survey.length >= 2) return;
  const plain = !cur || (cur.photo === pid && cur.state === "done" && cur.crop === "none" && !cur.edits?.crop && !cur.edits?.angle);
  if (!plain) return;
  const ov = document.createElement("div");
  ov.className = "frame-preview"; ov.dataset.kind = kind;
  f.appendChild(ov);
  const label = (text) => `<span class="tag l">${text}</span>`;
  if (kind === "none") { ov.innerHTML = label("<b>Whole</b> · the photo as shot"); return; }
  if (!frameBoxes[pid]) {
    ov.innerHTML = label('<span class="spin"></span> Finding the players…');
    frameBoxes[pid] = api(`/api/photos/${pid}/frames`).catch(() => ({}));
  }
  const boxes = await frameBoxes[pid];
  if (!ov.isConnected || ov.dataset.kind !== kind) return;
  const box = boxes[kind], name = CROPS.find((c) => c[0] === kind)[1];
  if (!box) {
    ov.innerHTML = label(kind === "face" ? `<b>${name}</b> · no clear face found here: it keeps the whole photo` : `<b>${name}</b> · this photo is already well framed: it stays whole`);
    return;
  }
  const [x0, y0, x1, y1] = box;
  ov.innerHTML = `<div class="fp-box" style="left:${x0 * 100}%;top:${y0 * 100}%;width:${(x1 - x0) * 100}%;height:${(y1 - y0) * 100}%">
    <i class="g1"></i><i class="g2"></i><i class="g3"></i><i class="g4"></i></div>${label(`<b>${name}</b> · what this framing keeps`)}`;
}

/* Edit works on any photo: with no look made, the photo itself opens for editing. */
async function editPhoto(pid = st.activePhoto) {
  if (!pid) return;
  const r = await api(`/api/photos/${pid}/original`, {});
  st.current = r.slot; st.tab = "edit"; st.view = "single"; st.survey = [];
  st.editWhenReady = r.slot;  // (still being prepared: the editor opens by itself when it's ready)
  await refresh();
  if (slotById(r.slot)?.state !== "done") toast("Opening the photo for editing…", { small: "A moment while it's prepared" });
}

async function make(what) {
  const photos = st.scope === "all" ? st.photos.map((p) => p.id) : st.scope === "chosen" ? [...st.chosen] : [st.activePhoto];
  const fromEdits = st.fromEdits && st.photos.some((p) => photos.includes(p.id) && p.edited);
  if (fromEdits) toast("Putting the looks on top of your edits…", { small: "Your edited photo is saved at full size first" });
  const r = await api("/api/run", { photos, crop: st.crop, from_edits: fromEdits, ...what });
  if (r.slots?.length) { st.current = r.slots[0]; st.view = "single"; st.compare = false; }
  await refresh();
  $(`#strip [data-key="${r.slots?.[0]}"]`)?.scrollIntoView({ block: "nearest", inline: "start" });
}

// The right panel's tabs -------------------------------------------------------------------------
function renderTabs() {
  const cur = slotById(st.current);
  const can = cur && cur.state === "done";
  if (can && st.editWhenReady === cur.id) { st.tab = "edit"; st.editWhenReady = null; }
  if (cur && st.editWhenReady && st.editWhenReady !== cur.id) st.editWhenReady = null;  // (you moved on)
  if (!can && st.tab === "edit") st.tab = "looks";
  $$(".tabs button").forEach((b) => {
    b.classList.toggle("on", b.dataset.tab === st.tab);
    if (b.dataset.tab === "edit") {
      setOff(b, !st.photos.length || (cur && !can),
        !st.photos.length ? "Add a photo first, then edit it here."
          : cur?.state === "failed" ? "This look could not be made, so there is nothing to edit. Open another one."
            : "This look is still being made. It can be edited as soon as it's done.");
      b.title = can ? "Edit this look: light, color, crop, remove, text (A)" : "Edit this photo: light, color, crop, remove, text (A)";
    }
  });
  $("#pane-looks").hidden = st.tab !== "looks";
  stalePreviews();
  $("#pane-edit").hidden = st.tab !== "edit";
  if (st.tab === "edit") renderEdit(cur);
}

// Reel ---------------------------------------------------------------------------------------
const reelForm = store.get("reel", { title: "", closing: "", sec: 2, max: 59, start: 0 });
let reelSong = null;
function renderReel(force = false) {
  const box = $("#reel");
  const kept = keptSlots(), all = doneSlots();
  if (!kept.length && st.reelSource === "kept") st.reelSource = "all";
  const pool = st.reelSource === "kept" ? kept : all;
  const ids = new Set(pool.map((s) => s.id));
  st.reelOrder = st.reelOrder.filter((id) => ids.has(id));
  for (const s of pool) if (!st.reelOrder.includes(s.id)) st.reelOrder.push(s.id);
  const use = st.reelOrder.filter((id) => !st.reelOut.has(id)).map(slotById);
  const sig = `${st.reelOrder.join(",")}|${[...st.reelOut].join(",")}|${use.map((s) => s.ver).join(",")}|${st.reelSource}|${st.reelTask}|${force}`;
  if (box.dataset.sig === sig && !force) return;
  box.dataset.sig = sig;
  const task = st.tasks.find((t) => t.id === st.reelTask);
  const n = use.length;
  const fit = reelFit(n, reelForm.sec, reelForm.max);
  box.innerHTML = `<div class="card">
      <div><h1>Make an Instagram reel</h1></div>
      <p class="lead">A vertical video under a minute: each picture slowly pushes in, dissolves into the next, and cuts on the beat of your song.</p>
      <div class="fld"><label>Pictures</label>
        <div class="seg full" id="r-src"><button data-v="kept" ${off(!kept.length, "Pick some looks first: open one and press Space (or the ✓ in the contact sheet).")}>Picks (${kept.length})</button><button data-v="all">All looks (${all.length})</button></div>
        <div class="reel-photos" id="r-order">${st.reelOrder.map((id, i) => { const s = slotById(id); const out = st.reelOut.has(id);
          return `<div class="rp${out ? " out" : ""}" draggable="true" data-id="${id}" title="${esc(s.title)}"><img src="${slotImg(s, "thumb")}" alt="" draggable="false"><span class="num">${out ? "" : use.indexOf(s) + 1}</span><button data-out="${id}" title="${out ? "Put back in the reel" : "Leave out of the reel"}">${icon(out ? "plus" : "x")}</button></div>`; }).join("") || `<span class="notes">Make some looks first.</span>`}</div>
        ${st.reelOrder.length > 1 ? `<small class="notes">Drag to change the order · × leaves one out</small>` : ""}</div>
      <div class="fld"><label>Song (optional)</label><label class="file-pick">${icon("music")}<span id="r-song-name">${reelSong ? esc(reelSong.name) : "Choose a song…"}</span><input type="file" id="r-song" accept="audio/*"></label>
        <div class="two"><div class="slider"><label>Start the song at</label><output id="r-start-v">${reelForm.start}s</output><input type="range" id="r-start" min="0" max="120" step="1" value="${reelForm.start}"></div><span></span></div></div>
      <div class="fld two"><div class="fld"><label>Opening title</label><input class="field" id="r-title" placeholder="PSG 11U vs West Park" value="${esc(reelForm.title)}"></div>
        <div class="fld"><label>Closing text</label><input class="field" id="r-closing" placeholder="@yourhandle" value="${esc(reelForm.closing)}"></div></div>
      <div class="fld"><div class="two">
        <div class="slider"><label>Seconds a picture</label><output id="r-sec-v">${(+reelForm.sec).toFixed(1)} s</output><input type="range" id="r-sec" min="1.5" max="4" step="0.1" value="${reelForm.sec}"></div>
        <div class="slider"><label>Longest reel</label><output id="r-max-v">${reelForm.max} s</output><input type="range" id="r-max" min="15" max="59" step="1" value="${reelForm.max}"></div></div></div>
      <p class="notes" id="r-est">${n ? `${fit.keep} pictures × ${fit.sec.toFixed(1)} s = ${Math.round(fit.keep * fit.sec)} s reel${fit.keep < n ? ` · the last ${n - fit.keep} do not fit` : ""} · takes ${say(fit.keep * 1.5 + fit.keep * fit.sec * 0.4 + 15)}` : ""}</p>
      <button class="btn primary big" id="r-go" ${off(!n || (task && task.state === "running"), !n ? "Make some looks first, on the Looks tab: the reel is made from them." : "A reel is being made. This button comes back when it's done.")}>${icon("film")} ${task && task.state === "running" ? "Making the reel…" : "Make reel"}</button>
    </div>
    <div class="phone"><div class="screen">${task && task.state === "done" && task.video ? `<video src="${task.video}?t=${task.id}" controls autoplay playsinline loop></video>`
      : task && task.state === "running" ? `<div><div class="spin" style="width:28px;height:28px;margin:0 auto 12px"></div>${esc(task.now)}<br>${task.done} of ${task.total}</div>`
      : `<div>${icon("film")}<p>Your reel plays here</p></div>`}</div></div>`;
  paintIcons(box);
  $$("#r-src button", box).forEach((b) => { b.classList.toggle("on", b.dataset.v === st.reelSource); b.onclick = () => { st.reelSource = b.dataset.v; renderReel(true); }; });
  const save = () => store.set("reel", reelForm);
  let dragId = null;
  $$("#r-order .rp", box).forEach((el) => {
    el.ondragstart = (e) => { dragId = +el.dataset.id; e.dataTransfer.effectAllowed = "move"; el.classList.add("dragging"); };
    el.ondragend = () => el.classList.remove("dragging");
    el.ondragover = (e) => { e.preventDefault(); el.classList.add("over"); };
    el.ondragleave = () => el.classList.remove("over");
    el.ondrop = (e) => {
      e.preventDefault(); e.stopPropagation();
      const to = +el.dataset.id;
      if (dragId == null || dragId === to) return;
      const order = st.reelOrder.filter((id) => id !== dragId);
      order.splice(order.indexOf(to) + (st.reelOrder.indexOf(dragId) < st.reelOrder.indexOf(to) ? 1 : 0), 0, dragId);
      st.reelOrder = order; renderReel(true);
    };
  });
  $$("#r-order [data-out]", box).forEach((b) => b.onclick = () => {
    const id = +b.dataset.out;
    st.reelOut.has(id) ? st.reelOut.delete(id) : st.reelOut.add(id); renderReel(true);
  });
  const est = () => {
    const f = reelFit(n, reelForm.sec, reelForm.max);
    $("#r-est", box).textContent = n ? `${f.keep} pictures × ${f.sec.toFixed(1)} s = ${Math.round(f.keep * f.sec)} s reel${f.keep < n ? ` · the last ${n - f.keep} do not fit` : ""} · takes ${say(f.keep * 1.5 + f.keep * f.sec * 0.4 + 15)}` : "";
  };
  $("#r-sec", box).oninput = (e) => { reelForm.sec = +e.target.value; $("#r-sec-v", box).textContent = reelForm.sec.toFixed(1) + " s"; est(); save(); };
  $("#r-max", box).oninput = (e) => { reelForm.max = +e.target.value; $("#r-max-v", box).textContent = reelForm.max + " s"; est(); save(); };
  $("#r-start", box).oninput = (e) => { reelForm.start = +e.target.value; $("#r-start-v", box).textContent = reelForm.start + "s"; save(); };
  $("#r-title", box).oninput = (e) => { reelForm.title = e.target.value; save(); };
  $("#r-closing", box).oninput = (e) => { reelForm.closing = e.target.value; save(); };
  $("#r-song", box).onchange = (e) => { reelSong = e.target.files[0] || null; $("#r-song-name", box).textContent = reelSong ? reelSong.name : "Choose a song…"; };
  $("#r-go", box).onclick = async () => {
    const fd = new FormData();
    fd.append("ids", JSON.stringify(use.map((s) => s.id)));
    fd.append("title", reelForm.title); fd.append("closing", reelForm.closing);
    fd.append("photo_sec", reelForm.sec); fd.append("max_sec", reelForm.max); fd.append("start", reelForm.start);
    if (reelSong) fd.append("song", reelSong);
    const t = await api("/api/reel", fd);
    st.reelTask = t.id; await refresh(); renderReel(true);
  };
}
function reelFit(n, sec, max) {
  if (!n) return { keep: 0, sec };
  let s = sec;
  if (n * s > max) s = Math.max(1.5, max / n);
  return { keep: Math.min(n, Math.floor(max / s + 1e-6)), sec: s };
}

// Adding photos --------------------------------------------------------------------------------
async function addPhotos(kind) {
  const r = await api(kind === "folder" ? "/api/photos/folder" : "/api/photos/choose", {});
  afterAdd(r.added);
}
async function upload(files) {
  const PHOTO = /\.(jpe?g|png|heic|heif|webp|tiff?|arw|dng|cr2|cr3|nef|raf|orf|rw2)$/i;
  files = files.filter((f) => f.type.startsWith("image/") || PHOTO.test(f.name));
  if (!files.length) return;
  const fd = new FormData();
  const now = new Date(), two = (n) => String(n).padStart(2, "0");
  const stamp = `${now.getFullYear()}-${two(now.getMonth() + 1)}-${two(now.getDate())} ${two(now.getHours())}.${two(now.getMinutes())}.${two(now.getSeconds())}`;
  files.forEach((f, i) => {
    const generic = !f.name || /^image\.\w+$/i.test(f.name);
    const ext = (f.type.split("/")[1] || "png").replace("jpeg", "jpg");
    fd.append("files", f, generic ? `Pasted ${stamp}${files.length > 1 ? "-" + (i + 1) : ""}.${ext}` : f.name);
  });
  const t = toast(`Adding ${plural(files.length, "photo")}…`, { sticky: true, spin: true });
  const added = [];
  try {
    const names = fd.getAll("files");
    for (let i = 0; i < names.length; i += 6) {
      const part = new FormData();
      names.slice(i, i + 6).forEach((f) => part.append("files", f, f.name));
      const r = await api("/api/photos/upload", part);
      added.push(...r.added);
      t.update(`Adding photos · ${Math.min(i + 6, names.length)} of ${names.length}`, "", Math.min(i + 6, names.length) / names.length);
    }
    t.close(); afterAdd(added);
  } catch { t.close(); if (added.length) afterAdd(added); }
}
async function afterAdd(added) {
  if (!added?.length) return;
  st.activePhoto = added[0]; st.current = null; st.view = "single";
  await refresh();
  renderLooks(true);
  toast(`Added ${plural(added.length, "photo")}`);
}
function bindAdd(root) {
  root.querySelectorAll("[data-add]").forEach((b) => b.onclick = () => { closeMenus(); addPhotos(b.dataset.add); });
}

let dragDepth = 0;
window.addEventListener("dragenter", (e) => { if ([...e.dataTransfer.types].includes("Files")) { dragDepth++; $("#drop").hidden = false; } });
window.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; $("#drop").hidden = true; } });
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", async (e) => {
  e.preventDefault(); dragDepth = 0; $("#drop").hidden = true;
  if (e.target.closest?.("#r-order")) return;
  if (e.target.closest?.(".kit-drop")) { for (const f of e.dataTransfer?.files || []) await addLogo(f); return; }
  const files = await droppedFiles(e.dataTransfer);
  const drawn = files.filter((f) => DRAWN.test(f.name));  // an SVG, PDF or Illustrator file is a logo, never a photo
  for (const f of drawn) await addLogo(f);
  const photos = files.filter((f) => !DRAWN.test(f.name));
  if (photos.length || !drawn.length) upload(photos);
});
const DRAWN = /\.(svgz?|pdf|ai)$/i;
/* Files dropped on the page, the photos inside dropped folders included. */
async function droppedFiles(dt) {
  const entries = [...(dt?.items || [])].map((i) => i.webkitGetAsEntry?.()).filter(Boolean);
  if (!entries.length || entries.every((en) => en.isFile)) return [...(dt?.files || [])];
  const out = [];
  const walk = async (en) => {
    if (en.isFile) out.push(await new Promise((res, rej) => en.file(res, rej)));
    else if (en.isDirectory) {
      const reader = en.createReader();
      let batch;
      do {
        batch = await new Promise((res, rej) => reader.readEntries(res, rej));
        for (const c of batch) await walk(c);
      } while (batch.length);
    }
  };
  for (const en of entries) await walk(en);
  // a shot saved as both JPEG and RAW: the camera's JPEG (as for a chosen folder)
  const RAW = /\.(arw|dng|cr2|cr3|nef|raf|orf|rw2)$/i;
  const stems = new Set(out.filter((f) => !RAW.test(f.name)).map((f) => f.name.replace(/\.[^.]+$/, "")));
  return out.filter((f) => !RAW.test(f.name) || !stems.has(f.name.replace(/\.[^.]+$/, "")));
}
document.addEventListener("paste", (e) => {
  if (e.target.closest?.("input, textarea")) return;
  const files = [...(e.clipboardData?.files || [])];
  if (files.length) { e.preventDefault(); upload(files); }
});

// Menus, tabs, keys ------------------------------------------------------------------------------
function closeMenus() { $$(".menu").forEach((m) => m.hidden = true); }
function menu(btn, m) {
  btn.onclick = (e) => { e.stopPropagation(); const open = m.hidden; closeMenus(); m.hidden = !open; };
}
document.addEventListener("click", (e) => { if (!e.target.closest(".menu")) closeMenus(); });

function showHelp() {
  closeMenus();
  const keys = [["← →", "Previous / next look"], ["Space or P", "Pick this look"], ["C", "Compare with the original"],
    ["B (hold)", "Show the original"], ["G", "Contact sheet / one at a time"], ["E", "Export the picks (or this one)"],
    ["A", "Edit this look"], ["R", "Crop and straighten"], ["T", "Add text"], ["1 – 5, 0", "Rate it, or clear the rating"],
    ["⌘Z, ⇧⌘Z", "Undo, redo"], ["Delete", "Remove this look (with Undo)"], ["Z or double-click", "Zoom in to check faces and focus (drag to move)"],
    ["⌘-click", "Compare pictures side by side"], ["⌘C", "Copy the picture (paste into Messages or Mail)"],
    ["⌘V", "Paste a photo"], ["Esc", "Close, or go back"]];
  modal(`<header><h2>Keyboard shortcuts</h2></header><div class="body"><div class="help-list">${keys.map(([k, t]) => `<kbd>${k}</kbd><span>${t}</span>`).join("")}</div></div>
    <footer><button class="btn primary" data-close>Done</button></footer>`);
}

document.addEventListener("keydown", (e) => {
  if (e.target.closest?.("input, textarea, select")) return;
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") { e.preventDefault(); (e.shiftKey ? redo : undo)(); return; }
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "c" && !String(window.getSelection())) {
    const cur = slotById(st.current);
    if (cur?.state === "done" && st.mode === "edit") { e.preventDefault(); copyPicture(cur); }
    return;
  }
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === "Escape") {
    if (modalOpen()) closeModal();
    else if (st.tool) setTool(st.tool);
    else if (st.survey.length) { st.survey = []; viewerSig = ""; render(); }
    else if (st.zoom.on) toggleZoom();
    else if (st.fixing) { st.fixing = false; renderViewer(); }
    else if (st.view === "grid") { st.view = "single"; render(); }
    return;
  }
  if (modalOpen() || st.mode !== "edit") return;
  const cur = slotById(st.current);
  const k = e.key.toLowerCase();
  if (k === "arrowright" || k === "arrowleft") { e.preventDefault(); step(k === "arrowright" ? 1 : -1); }
  else if ((k === " " || k === "p") && cur?.state === "done") { e.preventDefault(); toggleKeep([cur.id]); }
  else if ((k === " " || k === "p") && cur) { e.preventDefault(); toast("This look is still being made; pick it when it's done"); }
  else if (k === " " || k === "p") { e.preventDefault(); toast("Nothing to pick yet", { small: "Make some looks, then press Space on the ones you like" }); }
  else if (k === "c" && cur?.state === "done") { st.compare = !st.compare; st.view = "single"; viewerSig = ""; render(); if (st.zoom.on) sharpen(cur); }
  else if (k === "b" && cur?.state === "done" && !e.repeat) {
    st.compare = true; st.split = 100; viewerSig = ""; renderViewer();
    const up = (u) => { if (u.key.toLowerCase() === "b") { st.compare = false; st.split = 50; renderViewer(); document.removeEventListener("keyup", up); } };
    document.addEventListener("keyup", up);
  }
  else if ((k === "delete" || k === "backspace") && cur?.state === "done" && !st.tool) { e.preventDefault(); deleteLooks([cur.id]); }
  else if (k === "g" && st.slots.length) { st.view = st.view === "grid" ? "single" : "grid"; render(); }
  else if (k === "e") exportDefault();
  else if (k === "a" && cur?.state === "done") { st.tab = "edit"; renderTabs(); }
  else if (k === "a" && !cur && st.activePhoto) editPhoto();
  else if (k === "r" && cur?.state === "done") setTool("crop");
  else if (k === "t" && cur?.state === "done") setTool("text");
  else if (/^[0-5]$/.test(k) && cur?.state === "done") rate([cur.id], +k);
  else if (k === "z" && cur?.state === "done") toggleZoom(st.zoom.x, st.zoom.y);
  else if (k === "enter" && st.view === "grid" && cur) { st.view = "single"; render(); }
  else if (e.key === "?") showHelp();
  else if (k === "escape" && st.finding) { st.finding = false; render(); }
});

/* A newer version is on this Mac: restart into it. The looks, edits, picks and stars are saved
   and come back; only looks still being made would stop. */
function restartApp() {
  const making = st.slots.filter((s) => s.state === "wait" || s.state === "now").length;
  const m = modal(`<header><h2>Restart with the new version?</h2></header><div class="body"><p style="margin:0;color:var(--muted)">
    AllProPhoto closes and opens again in a few seconds. Your photos, looks, edits, picks and stars come back as they are.
    ${making ? `<br><br><b style="color:var(--gold)">${plural(making, "look")} still being made will stop</b>: make them again after.` : ""}</p></div>
    <footer><button class="btn ghost" data-close>Later</button><button class="btn primary" id="rs-go">Restart now</button></footer>`);
  $("#rs-go", m).onclick = async () => {
    closeModal();
    $("#modal-root").innerHTML = `<div class="scrim"><div class="modal" style="width:auto;padding:26px 30px;display:flex;gap:14px;align-items:center"><span class="spin"></span><b>Restarting AllProPhoto…</b></div></div>`;
    try { await fetch("/api/restart", { method: "POST" }); } catch { /* it is going down */ }
    const back = async () => {
      try { const r = await fetch("/api/looks", { cache: "no-store" }); if (r.ok) { location.reload(); return; } } catch { /* not yet */ }
      setTimeout(back, 1000);
    };
    setTimeout(back, 2500);
  };
}

function exportDefault() {
  const kept = keptSlots();
  if (kept.length) openExport(kept.map((s) => s.id));
  else if (slotById(st.current)?.state === "done") openExport([st.current]);
  else explain($("#export-btn"));
}

function init() {
  paintIcons();
  menu($("#add-btn"), $("#add-menu"));
  menu($("#tools-btn"), $("#tools-menu"));
  bindAdd(document);
  $("#help-btn").onclick = showHelp;
  $$("#tools-menu a").forEach((a) => a.onclick = (e) => {  // in your browser (the app's own window has no tabs)
    e.preventDefault(); closeMenus(); api("/api/open", { path: a.getAttribute("href") });
  });
  $("#export-btn").onclick = exportDefault;
  $$(".modes button").forEach((b) => b.onclick = () => { st.mode = b.dataset.mode; viewerSig = ""; render(); });
  $$(".tabs button").forEach((b) => b.onclick = () => {
    const cur = slotById(st.current);
    if (b.dataset.tab === "edit" && !(cur && cur.state === "done")) { editPhoto(); return; }
    st.tab = b.dataset.tab; editSig = ""; renderTabs();
  });
  $("#look-search").oninput = (e) => { st.query = e.target.value; renderLooks(true); };
  $("#show").onchange = (e) => { st.show = e.target.value; render(); };
  $("#view-single").onclick = () => { st.view = "single"; render(); };
  $("#view-grid").onclick = () => { st.view = "grid"; render(); };
  $("#keep-all").onclick = () => { const ids = doneSlots().filter((s) => !s.kept).map((s) => s.id); toggleKeep(ids); };
  $("#keep-none").onclick = () => toggleKeep(keptSlots().map((s) => s.id));
  $("#drop-unpicked").onclick = () => deleteLooks(doneSlots().filter((s) => !s.kept).map((s) => s.id));
  $("#clear-looks").onclick = () => {
    const m = modal(`<header><h2>Remove all looks?</h2></header><div class="body"><p style="margin:0;color:var(--muted)">The ${plural(doneSlots().length, "look")} made so far leave this session. Your photos stay, and anything you exported is kept.</p></div>
      <footer><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="rm-go">Remove all</button></footer>`);
    $("#rm-go", m).onclick = async () => {
      closeModal();
      await api("/api/run/stop", {});
      await api("/api/slots/remove", { ids: st.slots.map((s) => s.id) });
      st.current = null; st.view = "single"; refresh();
    };
  };
  st.crop = store.get("crop", "none");
  loadLooks().then(refresh);
  document.addEventListener("DOMContentLoaded", () => loadKit());
}
init();

/* Elastic side panels: drag the edge between a panel and the photo to widen or narrow it (the photo
   fits itself to the space left); the widths are remembered. Double-click an edge: back to normal. */
const PANELS = { rail: { min: 140, max: 0.42, sel: ".rail" }, inspector: { min: 280, max: 0.62, sel: ".inspector" } };
const STAGE_MIN = 360;
function setPanelWidth(name, px) {
  const app = $("#app"), p = PANELS[name];
  const other = name === "rail" ? $(".inspector")?.offsetWidth || 0 : $(".rail")?.offsetWidth || 0;
  const most = Math.min(window.innerWidth * p.max, window.innerWidth - other - STAGE_MIN);
  const w = Math.round(Math.max(p.min, Math.min(px, most)));
  app.style.setProperty(`--${name}`, `${w}px`);
  return w;
}
function refit() { const f = $("#frame"); if (f?.dataset.w) fitFrame(+f.dataset.w, +f.dataset.h); }
function bindGrips() {
  const saved = store.get("panels", {});
  for (const [name, w] of Object.entries(saved)) if (PANELS[name] && w) setPanelWidth(name, w);
  for (const name of Object.keys(PANELS)) {
    const panel = $(PANELS[name].sel);
    if (!panel || panel.querySelector(":scope > .grip")) continue;
    const grip = document.createElement("div");
    grip.className = "grip"; grip.setAttribute("role", "separator"); grip.setAttribute("aria-orientation", "vertical");
    grip.setAttribute("aria-label", name === "rail" ? "Resize the photos panel" : "Resize the side panel");
    panel.appendChild(grip);
    let frame = 0;
    grip.onpointerdown = (e) => {
      e.preventDefault();
      grip.setPointerCapture(e.pointerId); grip.classList.add("dragging"); document.body.classList.add("resizing");
      grip.onpointermove = (m) => {
        const px = name === "rail" ? m.clientX : window.innerWidth - m.clientX;
        setPanelWidth(name, px);
        cancelAnimationFrame(frame); frame = requestAnimationFrame(refit);
      };
      grip.onpointerup = () => {
        grip.onpointermove = grip.onpointerup = null;
        grip.classList.remove("dragging"); document.body.classList.remove("resizing");
        store.set("panels", { ...store.get("panels", {}), [name]: panel.offsetWidth });
        refit();
      };
    };
    grip.ondblclick = () => {
      $("#app").style.removeProperty(`--${name}`);
      const keep = store.get("panels", {}); delete keep[name]; store.set("panels", keep);
      requestAnimationFrame(refit);
    };
  }
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bindGrips); else bindGrips();
window.addEventListener("resize", () => {  // a smaller window: the panels give way, the photo keeps room
  const saved = store.get("panels", {});
  for (const [name, w] of Object.entries(saved)) if (PANELS[name] && w) setPanelWidth(name, w);
});

/* While a picture is still being made (the first time after a restart, a poster's players are found
   again), the photo shows at once, softly, with a note; the picture takes its place when ready. */
function watchPicture(cur) {
  const f = $("#frame"), img = f?.querySelector("img.after");
  if (!img || (img.complete && img.naturalWidth)) return;
  f.classList.add("waiting");
  f.style.setProperty("--placeholder", `url("/img/photo/${cur.photo}/view.jpg")`);
  if (!f.querySelector(".ready-note")) f.insertAdjacentHTML("beforeend", `<span class="tag ready-note"><span class="spin"></span> Getting the picture ready…</span>`);
  const done = () => { f.classList.remove("waiting"); f.querySelector(".ready-note")?.remove(); };
  img.addEventListener("load", done, { once: true });
  img.addEventListener("error", () => {
    const note = f.querySelector(".ready-note");
    if (note) note.innerHTML = `This picture could not be shown · <button class="link" id="ready-retry">Try again</button>`;
    $("#ready-retry")?.addEventListener("click", () => { img.src = img.src.split("?")[0] + "?r=" + Date.now(); watchPicture(cur); });
  }, { once: true });
}
