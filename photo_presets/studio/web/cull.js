/* AllProPhoto Studio: the Culling tab.
   Pass 1: the app looks at every photo of a shoot and marks it keep or reject (with why, how sure
   it is and a crop on the action). Pass 2: you go through it, keep and reject (your marks always win
   and teach it your taste), then delete the rejects (to the Trash, undoable), copy or crop-and-edit
   the keepers, or send them to Looks / Reel. Loaded after app.js, whose helpers it uses. */
"use strict";

Object.assign(ICONS, {
  card: '<rect x="5" y="2.5" width="14" height="19" rx="2"/><path d="M9 2.5v4M12 2.5v4M15 2.5v4"/>',
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  keep: '<path d="M5 12.5l4.2 4.2L19 7"/>',
  reject: '<path d="M6 6l12 12M18 6 6 18"/>',
  stack: '<rect x="7" y="7" width="13" height="13" rx="2"/><path d="M4 16V6a2 2 0 0 1 2-2h10"/>',
  timeline: '<path d="M3 20h18M6 16v-4M10 16V8M14 16v-6M18 16V5"/>',
  user: '<circle cx="12" cy="7.5" r="3.5"/><path d="M5 20.5c.8-3.8 3.6-6 7-6s6.2 2.2 7 6"/>',
  spray: '<rect x="7" y="9" width="8" height="12" rx="2"/><path d="M9 9V6h4v3M13 4h2M17 5l2-1M17 8h3M17 11l2 1"/>',
});

const cu = {
  shoots: [], cards: [], taste: null, ai: false, sizes: {}, versions: {},
  sel: store.get("cull.sel", null), photos: new Map(), rev: 0, order: [],
  view: "grid", cur: null, picked: new Set(), anchor: null,
  tile: store.get("cull.tile", 210), group: store.get("cull.group", true), open: new Set(),
  show: "all", issues: new Set(), stars: 0, sort: store.get("cull.sort", "time"),
  advance: store.get("cull.advance", true), cropShow: store.get("cull.crop", false), marks: store.get("cull.marks", true),
  zoom: null, hist: [], future: [], timer: null, built: false, shootSig: "", gridSig: "",
  survey: null, spray: null, labelF: new Set(), labels: [],
  people: [], person: null, personHits: null, personJob: null, picking: false,
};
const CU_ISSUE = { blur: ["Soft", "The main player is soft"], eyes: ["Eyes closed", "Eyes look closed"],
  focus: ["Missed focus", "Focused on the background"], empty: ["No players", "No players in it"],
  small: ["Small", "Players small in the frame"], dark: ["Too dark", "Too dark on the players"],
  bright: ["Too bright", "Blown out"], back: ["No face", "The main player's face can't be seen"],
  dupe: ["Near copy", "A near copy of a better frame"] };
const UNSURE = 0.65;

const cuShoot = () => cu.shoots.find((s) => s.id === cu.sel);
const cuP = (id) => cu.photos.get(id);
const flagOf = (p) => p.flag || p.auto?.[0] || null;
const yours = (p) => !!p.flag;
const unsure = (p) => !p.flag && p.auto && p.auto[1] < UNSURE;
const alive = (p) => p.state !== "gone";

// -- data ------------------------------------------------------------------------------------------
async function cuState() {
  const r = await fetch("/api/cull/state").then((x) => x.json()).catch(() => null);
  if (!r) return;
  Object.assign(cu, { shoots: r.shoots, cards: r.cards, taste: r.taste, ai: r.ai, sizes: r.sizes, versions: r.versions, fits: r.fits, labels: r.labels || [], people: r.people || [] });
  if (cu.sel && !cu.shoots.some((s) => s.id === cu.sel)) cu.sel = null;
  if (!cu.sel && cu.shoots.length) cu.sel = cu.shoots[0].id;
}
async function cuPhotos(full = false) {
  const sh = cuShoot();
  if (!sh) return false;
  if (full) { cu.photos = new Map(); cu.rev = 0; }
  const r = await fetch(`/api/cull/shoots/${sh.id}/photos?since=${cu.rev}`).then((x) => x.json()).catch(() => null);
  if (!r || cu.sel !== sh.id) return false;
  r.photos.forEach((p) => cu.photos.set(p.id, p));
  cu.rev = r.rev;
  Object.assign(sh, r.shoot);
  return r.photos.length > 0;
}
function cuPoll() {
  clearTimeout(cu.timer);
  if (st.mode !== "cull") return;
  const sh = cuShoot();
  const busy = sh && (sh.measured < sh.total || sh.thumbs < sh.total || sh.job?.state === "now");
  cu.timer = setTimeout(async () => {
    const before = JSON.stringify(cu.shoots.map((s) => [s.id, s.measured, s.keep, s.reject, s.job?.state, s.job?.done]));
    await cuState();
    const changed = await cuPhotos();
    if (changed) { cuSort(); cuPaintGrid(); cuPaintTimeline(); if (cu.view !== "grid") cuPaintMain(); cuPaintInfo(); }
    if (cuShoot()?.pass1 && !modalOpen() && !cu.finish) cuReveal();
    if (before !== JSON.stringify(cu.shoots.map((s) => [s.id, s.measured, s.keep, s.reject, s.job?.state, s.job?.done]))) { cuPaintSide(); cuPaintBar(); }
    cuJobWatch();
    cuPoll();
  }, busy ? 1000 : 4000);
}

// which photos show, in what order
function cuSort() {
  const all = [...cu.photos.values()].filter(alive);
  let list = all.filter((p) => {
    const f = flagOf(p);
    if (cu.show === "keep" && f !== "keep") return false;
    if (cu.show === "reject" && f !== "reject") return false;
    if (cu.show === "unsure" && !unsure(p)) return false;
    if (cu.show === "todo" && yours(p)) return false;
    if (cu.show === "mine" && !yours(p)) return false;
    if (cu.stars && (p.stars || 0) < cu.stars) return false;
    if (cu.issues.size && !p.issues.some((i) => cu.issues.has(i))) return false;
    if (cu.labelF.size && !cu.labelF.has(p.label || 0)) return false;
    if (cu.person && (!cu.personHits || !cu.personHits.has(p.id))) return false;
    return true;
  });
  const byTime = (a, b) => (a.t ?? 1e18) - (b.t ?? 1e18) || a.id - b.id;
  if (cu.person && cu.personHits) {  // their photos: sure ones first, the best of each burst first, then by how good a shot of them
    const h = (p) => cu.personHits.get(p.id);
    list.sort((a, b) => (h(a).status !== "sure") - (h(b).status !== "sure") || (!h(a).best) - (!h(b).best) || h(b).quality - h(a).quality || byTime(a, b));
  } else if (cu.sort === "score") list.sort((a, b) => (b.score ?? -1) - (a.score ?? -1) || byTime(a, b));
  else if (cu.sort === "unsure") list.sort((a, b) => ((a.flag ? 2 : a.auto?.[1] ?? 1) - (b.flag ? 2 : b.auto?.[1] ?? 1)) || byTime(a, b));
  else list.sort(byTime);
  // bursts as one stack: the frame that stands for it (yours kept, else the best), unless opened
  if (cu.group) {
    const lead = new Map();
    for (const p of list) {
      if (p.burst == null || p.bsize < 2 || cu.open.has(p.burst)) continue;
      const cur = lead.get(p.burst);
      const rank = (q) => (q.flag === "keep" ? 3 : 0) + (q.best ? 2 : 0) + (q.score || 0) / 1000;
      if (!cur || rank(p) > rank(cur)) lead.set(p.burst, p);
    }
    list = list.filter((p) => p.burst == null || p.bsize < 2 || cu.open.has(p.burst) || lead.get(p.burst) === p);
  }
  cu.order = list.map((p) => p.id);
  if (cu.cur == null || !cu.order.includes(cu.cur)) cu.cur = cu.order[0] ?? null;
}
function cuCounts() {
  const c = { all: 0, keep: 0, reject: 0, unsure: 0, todo: 0, mine: 0 }, iss = {};
  for (const p of cu.photos.values()) {
    if (!alive(p)) continue;
    c.all++; const f = flagOf(p);
    if (f === "keep") c.keep++; if (f === "reject") c.reject++;
    if (unsure(p)) c.unsure++; if (yours(p)) c.mine++; else c.todo++;
    p.issues.forEach((i) => iss[i] = (iss[i] || 0) + 1);
    iss["lab" + (p.label || 0)] = (iss["lab" + (p.label || 0)] || 0) + 1;
  }
  return [c, iss];
}

// -- the page ----------------------------------------------------------------------------------------
function renderCull() {
  const box = $("#cull");
  if (!cu.built) {
    cu.built = true;
    box.innerHTML = `<aside class="cu-side" id="cu-side"></aside>
      <section class="cu-main"><div class="cu-bar" id="cu-bar"></div><div class="cu-tl" id="cu-tl" title="The whole event over time: tall bars are bursts of shooting (big moments). Click to jump there."></div>
        <div class="cu-body" id="cu-body"><div class="cu-grid" id="cu-grid"><div class="cu-space" id="cu-space"></div></div><div class="cu-one" id="cu-one" hidden></div><div class="cu-sprayf" id="cu-sprayf" hidden></div><div class="cu-pplf" id="cu-pplf" hidden></div></div>
        <div class="cu-keys" id="cu-keys"></div></section>
      <aside class="cu-info" id="cu-info"></aside>
      <div class="cu-drag" data-edge="l" title="Drag to resize · double-click for the usual size"></div><div class="cu-drag" data-edge="r" title="Drag to resize · double-click for the usual size"></div>`;
    cuElastic(box);
    $("#cu-grid").addEventListener("scroll", () => requestAnimationFrame(cuPaintGrid), { passive: true });
    new ResizeObserver(() => { cu.gridSig = ""; cuPaintGrid(); cuFitPic(); }).observe($("#cu-body"));
    $("#cu-grid").addEventListener("click", cuGridClick);
    cuSprayGrid();
    $("#cu-grid").addEventListener("dblclick", (e) => { const t = e.target.closest("[data-p]"); if (t) { cu.cur = +t.dataset.p; cuSetView("one"); } });
    cuPaintKeys();
  }
  cuState().then(async () => {
    const full = cu.shootSig !== String(cu.sel);
    cu.shootSig = String(cu.sel);
    await cuPhotos(full);
    cuSort(); cuPaintAll(); cuPoll();
  });
}
// -- elastic panels: drag either edge; they remember their size and give way on a small window ----------
const CU_W = { l: [180, 420, 250], r: [220, 520, 300] };  // smallest, largest, usual
const CU_MID = 420;  // the photos keep at least this much room
function cuFit(box) {
  const total = box.clientWidth || window.innerWidth;
  let l = store.get("cull.wl", CU_W.l[2]), r = store.get("cull.wr", CU_W.r[2]);
  l = Math.min(CU_W.l[1], Math.max(CU_W.l[0], l)); r = Math.min(CU_W.r[1], Math.max(CU_W.r[0], r));
  const over = l + r + CU_MID - total;
  if (over > 0) {  // a small window: both panels give way, down to their smallest
    const room = (l - CU_W.l[0]) + (r - CU_W.r[0]) || 1;
    l -= Math.min(l - CU_W.l[0], over * (l - CU_W.l[0]) / room);
    r -= Math.min(r - CU_W.r[0], over * (r - CU_W.r[0]) / room);
  }
  box.style.setProperty("--cl", `${Math.round(l)}px`); box.style.setProperty("--cr", `${Math.round(r)}px`);
}
function cuElastic(box) {
  cuFit(box);
  new ResizeObserver(() => cuFit(box)).observe(box);
  box.querySelectorAll(".cu-drag").forEach((h) => {
    const edge = h.dataset.edge, key = edge === "l" ? "cull.wl" : "cull.wr";
    h.ondblclick = () => { store.set(key, CU_W[edge][2]); cuFit(box); };
    h.onpointerdown = (e) => {
      e.preventDefault(); h.setPointerCapture(e.pointerId); h.classList.add("on");
      const r = box.getBoundingClientRect();
      h.onpointermove = (m) => {
        const want = edge === "l" ? m.clientX - r.left : r.right - m.clientX;
        const other = parseFloat(getComputedStyle(box).getPropertyValue(edge === "l" ? "--cr" : "--cl")) || 0;
        const max = Math.min(CU_W[edge][1], r.width - other - CU_MID);
        store.set(key, Math.round(Math.min(max, Math.max(CU_W[edge][0], want))));
        cuFit(box);
      };
      h.onpointerup = () => { h.onpointermove = null; h.classList.remove("on"); cu.gridSig = ""; cuPaintGrid(); };
    };
  });
}

function cuPaintAll() { cuPaintSide(); cuPaintBar(); cuPaintTimeline(); cuPaintMain(); cuPaintInfo(); }

function cuPaintSide() {
  const side = $("#cu-side"); if (!side) return;
  const sh = cuShoot();
  const [c, iss] = cuCounts();
  const card = cu.cards[0];
  const row = (k, label, n, tip) => `<button class="cu-f${cu.show === k ? " on" : ""}" data-show="${k}" title="${esc(tip)}"><span>${label}</span><b>${n.toLocaleString()}</b></button>`;
  side.innerHTML = `<div class="ck-head"><h2>Culling</h2>
      <button class="icon-btn" id="cu-help" title="How culling works">${icon("info")}</button>
      <div class="menu-wrap"><button class="icon-btn" id="cu-add" title="Add an event" aria-haspopup="menu">${icon("plus")}</button>
        <div class="menu" id="cu-add-menu" role="menu" hidden><button role="menuitem" data-add="folder">Add a folder…<small>An event's photos (JPEG and RAW). They stay where they are</small></button>
          <button role="menuitem" data-add="card">Import from the camera card…<small>${card ? `${esc(card.name)}: ${card.photos.toLocaleString()} photos` : "Plug in the card first"}</small></button></div></div></div>
    ${card ? `<button class="cu-card" id="cu-card">${icon("card")}<span><b>${esc(card.name)}</b> card · ${card.photos.toLocaleString()} photos<small>Import and start culling while it copies</small></span></button>` : ""}
    <div class="cu-shoots">${cu.shoots.map((s) => {
      const busy = s.measured < s.total;
      return `<div class="cu-shoot${s.id === cu.sel ? " on" : ""}" data-shoot="${s.id}" title="${esc(s.folders.join("\n"))}">
        <b>${esc(s.name)}</b><small>${busy ? `<span class="spin sm"></span> Pass 1 · ${s.measured.toLocaleString()} of ${s.total.toLocaleString()} · ${say(s.left)}`
          : `${s.total.toLocaleString()} photos · <span class="good-t">${s.keep.toLocaleString()} keep</span> · <span class="bad-t">${s.reject.toLocaleString()} reject</span>`}</small>
        ${busy ? `<i class="cu-prog" style="width:${(s.measured / Math.max(1, s.total) * 100).toFixed(1)}%"></i>` : ""}
        <button class="x" data-forget="${s.id}" title="Take this event out of the list (the photos stay where they are)">${icon("x")}</button></div>`; }).join("")
      || `<div class="ck-empty"><p><b>No events yet</b></p><p>Add an event's folder, or import from the camera card.</p>
          <button class="btn primary" data-add="folder">${icon("plus")} Add a folder…</button>${card ? "" : `<button class="btn ghost" data-add="card">Import from a card…</button>`}</div>`}</div>
    ${sh && (sh.settings?.saved || []).length ? `<h4 class="sub">Your keepers went to</h4><div class="cu-saved">${sh.settings.saved.map((f) => `<button data-reveal="${esc(f)}" title="${esc(f)}">${icon("folder")}<span>${esc(f.split("/").pop())}<small>${esc(f.replace(/^\/Users\/[^/]+/, "~").split("/").slice(0, -1).join("/"))}</small></span></button>`).join("")}</div>` : ""}
    ${sh ? `<h4 class="sub">Show</h4><div class="cu-fs">
      ${row("all", "Everything", c.all, "Every photo")}
      ${row("keep", `${icon("keep")} Keep`, c.keep, "Kept by pass 1 or by you")}
      ${row("reject", `${icon("reject")} Reject`, c.reject, "Rejected by pass 1 or by you: deleted when you press Delete rejects")}
      ${row("unsure", "Pass 1 unsure", c.unsure, "Where pass 1 was least sure: the best place to spend your time")}
      ${row("todo", "Not checked by you", c.todo, "Photos with only pass 1's mark: you haven't kept or rejected them yourself")}
      ${row("mine", "Your marks", c.mine, "Photos you marked yourself")}</div>
      <h4 class="sub">Problems <small>${cu.issues.size ? `<a href="#" id="cu-iss-clear">clear</a>` : "tap to filter"}</small></h4>
      <div class="cu-chips">${Object.entries(CU_ISSUE).filter(([k]) => iss[k]).map(([k, [l, t]]) => `<button class="chip${cu.issues.has(k) ? " on" : ""}" data-iss="${k}" title="${esc(t)}">${l} <b>${iss[k]}</b></button>`).join("") || `<span class="faint">None found</span>`}</div>
      <h4 class="sub">People <small><a href="#" id="cu-ppl-add">+ find a player</a></small></h4>
      ${cu.people.length ? `<div class="cu-chips">${cu.people.map((x) => `<button class="chip${cu.person === x.id ? " on" : ""}" data-pp="${x.id}" title="Show only ${esc(x.name)}'s photos">${icon("user")} ${esc(x.name)}${x.number && !x.name.includes(x.number) ? ` <b>#${esc(x.number)}</b>` : ""}</button>`).join("")}</div>`
        : `<p class="cu-hint">Find one player's photos: click them in a photo, or type their number.</p>`}
      <h4 class="sub">Labels <small><a href="#" id="cu-lab-names">rename</a>${cu.labelF.size ? ` · <a href="#" id="cu-lab-clear">clear</a>` : ""}</small></h4>
      <div class="cu-chips">${[1, 2, 3, 4, 5].map((n) => `<button class="chip${cu.labelF.has(n) ? " on" : ""}" data-lf="${n}" title="Show only ${esc(labelName(n))}">${cuLabelDot(n)} ${esc(labelName(n))} <b>${iss["lab" + n] || 0}</b></button>`).join("")}</div>
      <h4 class="sub">Stars at least</h4><div class="cu-stars" id="cu-starsf">${[0, 1, 2, 3, 4, 5].map((n) => `<button class="${cu.stars === n ? "on" : ""}" data-sf="${n}">${n ? "★".repeat(n) : "Any"}</button>`).join("")}</div>
      <h4 class="sub">Order</h4><div class="seg small" id="cu-sort">${[["time", "Time"], ["score", "Best first"], ["unsure", "Unsure first"]].map(([k, l]) => `<button class="${cu.sort === k ? "on" : ""}" data-sort="${k}">${l}</button>`).join("")}</div>
      <div class="cu-taste" title="Every keep or reject you make teaches pass 1 what you like, on this Mac">${icon("wand")} ${cu.taste?.ready
        ? `Pass 1 uses your taste, learned from ${(cu.taste.kept + cu.taste.rejected).toLocaleString()} of your decisions`
        : `Learning your taste: ${cu.taste?.kept || 0} keeps and ${cu.taste?.rejected || 0} rejects so far (it starts helping after ${cu.taste?.need || 12} of each)`}</div>` : ""}`;
  paintIcons(side);
  $("#cu-add").onclick = (e) => { e.stopPropagation(); $("#cu-add-menu").hidden = !$("#cu-add-menu").hidden; };
  side.querySelectorAll("[data-add]").forEach((b) => b.onclick = () => { $("#cu-add-menu").hidden = true; b.dataset.add === "card" ? cuImport() : cuAddFolder(); });
  $("#cu-card")?.addEventListener("click", cuImport);
  $("#cu-help").onclick = () => { cu.guide = !cu.guide || !cuShoot(); cuPaintAll(); };
  side.querySelectorAll("[data-shoot]").forEach((r) => r.onclick = async (e) => {
    if (e.target.closest("[data-forget]")) return;
    cu.guide = false;
    cu.sel = +r.dataset.shoot; store.set("cull.sel", cu.sel); cu.shootSig = ""; cu.picked.clear(); cu.open.clear(); cu.hist = []; cu.future = [];
    renderCull();
  });
  side.querySelectorAll("[data-forget]").forEach((b) => b.onclick = async () => {
    const s = cu.shoots.find((x) => x.id === +b.dataset.forget);
    await api(`/api/cull/shoots/${s.id}`, undefined, { method: "DELETE" });
    toast(`Took “${s.name}” out of the list`, { small: "The photos and your marks are untouched: add the folder again to carry on" });
    cu.shootSig = ""; renderCull();
  });
  side.querySelectorAll("[data-show]").forEach((b) => b.onclick = () => { cu.show = b.dataset.show; cuRefilter(); });
  side.querySelectorAll("[data-reveal]").forEach((b) => b.onclick = () => api("/api/reveal", { path: b.dataset.reveal }));
  side.querySelectorAll("[data-iss]").forEach((b) => b.onclick = () => { const k = b.dataset.iss; cu.issues.has(k) ? cu.issues.delete(k) : cu.issues.add(k); cuRefilter(); });
  $("#cu-iss-clear")?.addEventListener("click", (e) => { e.preventDefault(); cu.issues.clear(); cuRefilter(); });
  side.querySelectorAll("[data-pp]").forEach((b) => b.onclick = () => cuShowPerson(b.dataset.pp));
  $("#cu-ppl-add")?.addEventListener("click", (e) => { e.preventDefault(); cuAddPerson(); });
  side.querySelectorAll("[data-lf]").forEach((b) => b.onclick = () => { const n = +b.dataset.lf; cu.labelF.has(n) ? cu.labelF.delete(n) : cu.labelF.add(n); cuRefilter(); });
  $("#cu-lab-clear")?.addEventListener("click", (e) => { e.preventDefault(); cu.labelF.clear(); cuRefilter(); });
  $("#cu-lab-names")?.addEventListener("click", (e) => { e.preventDefault(); cuRenameLabels(); });
  side.querySelectorAll("[data-sf]").forEach((b) => b.onclick = () => { cu.stars = +b.dataset.sf; cuRefilter(); });
  side.querySelectorAll("[data-sort]").forEach((b) => b.onclick = () => { cu.sort = b.dataset.sort; store.set("cull.sort", cu.sort); cuRefilter(); });
}
document.addEventListener("click", (e) => { if (!e.target.closest("#cu-add, #cu-add-menu, #cu-out, #cu-out-menu")) { $("#cu-add-menu") && ($("#cu-add-menu").hidden = true); $("#cu-out-menu") && ($("#cu-out-menu").hidden = true); } });
function cuRefilter() { cuSort(); cu.gridSig = ""; cuPaintSide(); cuPaintBar(); cuPaintMain(); cuPaintInfo(); $("#cu-grid").scrollTop = 0; }

function cuPaintBar() {
  const bar = $("#cu-bar"); if (!bar) return;
  const sh = cuShoot();
  if (!sh || cu.guide) { bar.innerHTML = ""; return; }
  const [c] = cuCounts();
  const n = cu.picked.size;
  const measuring = sh.measured < sh.total;
  bar.innerHTML = `<div class="cu-steps">
      <button class="cu-step${sh.pass1 ? " done" : ""}" id="cu-pass1" title="The app's own first pass: it marks every photo keep or reject. Change how many it keeps and how picky it is, and run it again (your own marks are never changed)">
        <span class="n">1</span><span class="t">Pass 1</span>${measuring ? `<span class="x">· ${Math.round(sh.measured / Math.max(1, sh.total) * 100)}%</span>` : sh.pass1 ? `<span class="x">: ${c.keep.toLocaleString()} keep</span>` : ""}${icon("chev")}</button>
      <button class="cu-step cu-meter${c.todo === 0 && c.all ? " done" : ""}" id="cu-pass2" style="--pct:${c.all ? Math.round(c.mine / c.all * 100) : 0}%" title="Your pass: ${c.mine} of ${c.all} checked by you. Starts with the close calls">
        <span class="n">2</span><span class="t">Your pass</span>${c.unsure ? `<span class="x">· ${c.unsure.toLocaleString()} unsure</span>` : ""}</button>
      <button class="cu-step${cu.finish ? " now" : ""}" id="cu-pass3" ${off(!c.reject && !c.keep, "Nothing marked yet")} title="Delete the rejects, then crop, copy or use the keepers">
        <span class="n">3</span><span class="t">Finish</span></button></div>
    <div class="seg small" id="cu-views">${[["grid", "grid", "Gallery (G)"], ["one", "single", "One big photo (Space)"], ["compare", "compare", "Side by side (C)"]].map(([k, ic, t]) => `<button class="${cu.view === k ? "on" : ""}" data-view="${k}" title="${t}">${icon(ic)}</button>`).join("")}</div>
    <button class="btn ghost cu-spray-btn${cu.spray ? " on" : ""}" id="cu-spray" title="Spray Can (L): sort photos into your labels by clicking or dragging across them">${icon("spray")}<span class="lbl"> Spray can</span></button>
    <button class="icon-btn cu-tog${cu.group ? " on" : ""}" id="cu-group" title="${cu.group ? "Bursts are stacked: each shows as its best frame (click to show every frame)" : "Every frame shows (click to stack each burst as its best frame)"}">${icon("stack")}</button>
    <span class="grow"></span>
    ${n > 1 ? `<span class="cu-selinfo">${n} selected</span>` : ""}
    <button class="btn danger" id="cu-del" ${off(!c.reject, "No rejects to delete")} title="Move every rejected photo to the Trash (you can undo, or put them back from the Trash)">${icon("trash")}<span class="lbl"> Delete rejects</span>${c.reject ? ` (${c.reject.toLocaleString()})` : ""}</button>
    <button class="btn ${cu.finish ? "ghost on" : "primary"}" id="cu-fin" ${off(!c.keep, "No keepers yet")} title="Step 3: delete the rejects, then crop, copy or use the keepers">Finish${c.keep ? ` · ${c.keep.toLocaleString()} keepers` : ""} ${icon("right")}</button>`;
  paintIcons(bar);
  $("#cu-pass1").onclick = cuPass1;
  $("#cu-pass2").onclick = () => { cu.finish = false; cu.show = c.unsure ? "unsure" : "todo"; cu.sort = "unsure"; store.set("cull.sort", cu.sort); cuRefilter(); if (cu.order.length) cuSetView("one");
    toast(c.unsure ? "Your pass: the photos pass 1 was least sure about come first" : "Your pass: what you haven't looked at yet", { small: "P keep · X reject · → next. Your mark replaces pass 1's" }); };
  $("#cu-pass3").onclick = cuOpenFinish;
  $("#cu-fin").onclick = () => c.keep && cuOpenFinish();
  bar.querySelectorAll("[data-view]").forEach((b) => b.onclick = () => cuSetView(b.dataset.view));
  $("#cu-spray").onclick = () => cuToggleSpray();
  const fl = $("#cu-sprayf");
  fl.hidden = !cu.spray || cu.view !== "grid" || cu.finish;
  fl.innerHTML = cu.spray ? `<span class="t">${icon("spray")} Spray can</span>${[1, 2, 3, 4, 5].map((n) => `<button class="${cu.spray === n ? "on" : ""}" data-spray="${n}" title="${n <= 4 ? `Key ${n + 5}` : ""}">${cuLabelDot(n, true)}<span>${esc(labelName(n))}</span></button>`).join("")}
    <span class="hint">Click or drag across photos · drag back over to take it off</span><button class="btn small" id="cu-spray-done">Done (Esc)</button>` : "";
  paintIcons(fl);
  fl.querySelectorAll("[data-spray]").forEach((b) => b.onclick = () => { cu.spray = cu.lastSpray = +b.dataset.spray; cuPaintBar(); });
  $("#cu-spray-done", fl)?.addEventListener("click", cuToggleSpray);
  $("#cu-group").onclick = () => { cu.group = !cu.group; store.set("cull.group", cu.group); cu.open.clear(); cuRefilter(); };
  $("#cu-del").onclick = () => c.reject && cuDeleteRejects();
}

function cuPaintKeys() {
  const k = $("#cu-keys"); if (!k) return;
  k.innerHTML = [["P", "keep"], ["X", "reject"], ["1–5", "stars"], ["←→", "next"], ["Space", "big"], ["Z", "100%"], ["C", "compare"], ["⌘Z", "undo"], ["?", "all keys"]]
    .map(([a, b]) => `<span><kbd>${a}</kbd> ${b}</span>`).join("")
    + `<label class="cu-adv" title="After you mark a photo, go to the next one"><input type="checkbox" id="cu-advance" ${cu.advance ? "checked" : ""}> Next after marking</label>`
    + `<label class="cu-sz" title="Thumbnail size">${icon("grid")}<input type="range" id="cu-size" min="120" max="420" step="10" value="${cu.tile}"></label>`;
  paintIcons(k);
  $("#cu-advance").onchange = (e) => { cu.advance = e.target.checked; store.set("cull.advance", cu.advance); };
  $("#cu-size").oninput = (e) => { cu.tile = +e.target.value; store.set("cull.tile", cu.tile); cu.gridSig = ""; if (cu.view !== "grid") cuSetView("grid"); cuPaintGrid(); };
}

// -- the timeline: the whole shoot over time --------------------------------------------------------
function cuPaintTimeline() {
  const tl = $("#cu-tl"); if (!tl) return;
  const ps = [...cu.photos.values()].filter((p) => alive(p) && p.t);
  if (ps.length < 8) { tl.innerHTML = ""; tl.hidden = true; return; }
  tl.hidden = false;
  const t0 = Math.min(...ps.map((p) => p.t)), t1 = Math.max(...ps.map((p) => p.t));
  const span = Math.max(60, t1 - t0), bins = Math.min(160, Math.max(30, Math.round(tl.clientWidth / 6) || 120));
  const count = new Array(bins).fill(0), kept = new Array(bins).fill(0);
  for (const p of ps) { const i = Math.min(bins - 1, Math.floor((p.t - t0) / span * bins)); count[i]++; if (flagOf(p) === "keep") kept[i]++; }
  const max = Math.max(...count);
  const cur = cuP(cu.cur);
  const fmt = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  tl.innerHTML = `<span class="lab">${fmt(t0)}</span><div class="bars">${count.map((n, i) => `<i data-bin="${i}" style="height:${n ? 8 + n / max * 92 : 0}%;--k:${n ? kept[i] / n : 0}" title="${fmt(t0 + span * i / bins)} · ${plural(n, "photo")}${kept[i] ? `, ${kept[i]} kept` : ""}"></i>`).join("")}
    ${cur?.t ? `<b class="now" style="left:${((cur.t - t0) / span * 100).toFixed(2)}%"></b>` : ""}</div><span class="lab">${fmt(t1)}</span>`;
  tl.querySelector(".bars").onclick = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const t = t0 + (e.clientX - r.left) / r.width * span;
    const near = cu.order.map(cuP).reduce((best, p) => (p.t && (!best || Math.abs(p.t - t) < Math.abs(best.t - t)) ? p : best), null);
    if (near) { cu.cur = near.id; cuScrollTo(near.id); cuPaintMain(); cuPaintInfo(); cuPaintTimeline(); }
  };
}

// -- the gallery (only what is on screen is drawn: thousands of photos stay quick) -------------------
function cuGeom() {
  const g = $("#cu-grid"); const W = g.clientWidth - 16;
  const gap = 8, cols = Math.max(1, Math.floor((W + gap) / (cu.tile + gap)));
  const tw = (W - gap * (cols - 1)) / cols, th = Math.round(tw * 0.72) + 26;
  return { g, cols, tw, th, gap };
}
function cuTile(p, x, y, tw, th) {
  const f = flagOf(p), mine = yours(p);
  const iss = p.issues.filter((i) => i !== "dupe" && i !== "back").slice(0, 2);
  return `<div class="cu-t${f ? " f-" + f : ""}${mine ? " mine" : ""}${p.id === cu.cur ? " cur" : ""}${cu.picked.has(p.id) ? " sel" : ""}${cu.open.has(p.burst) && p.bsize > 1 ? " inburst" : ""}" data-p="${p.id}" style="transform:translate(${x}px,${y}px);width:${tw}px;height:${th}px">
    <div class="im">${p.state === "new" ? `<span class="spin sm"></span>` : `<img src="/img/cull/${cu.sel}/${p.id}/thumb.jpg" alt="" loading="lazy" draggable="false">`}
      ${cu.marks && f ? `<span class="flag" title="${mine ? "Your mark" : `Pass 1, ${Math.round((p.auto?.[1] || 0) * 100)}% sure`}">${icon(f === "keep" ? "keep" : "reject")}</span>` : ""}
      ${p.label ? `<span class="lab-bar" style="background:${LABEL_COLORS[p.label - 1]}" title="${esc(labelName(p.label))}"></span>` : ""}
      ${p.stars ? `<span class="stars">${"★".repeat(p.stars)}</span>` : ""}
      ${cu.group && p.bsize > 1 && !cu.open.has(p.burst) ? `<button class="burst" data-burst="${p.burst}" title="A burst of ${p.bsize} frames: open it">${icon("stack")}${p.bsize}</button>` : ""}
      ${cu.marks && iss.length ? `<span class="iss">${iss.map((i) => `<i title="${esc(CU_ISSUE[i][1])}">${esc(CU_ISSUE[i][0])}</i>`).join("")}</span>` : ""}
      ${unsure(p) && cu.marks ? `<span class="unsure" title="Pass 1 wasn't sure about this one">?</span>` : ""}</div>
    <div class="cap"><span>${cuLabelDot(p.label)}${esc(p.name)}</span>${p.score != null ? `<b class="sc" style="--s:${p.score / 100}">${p.score}</b>` : ""}</div></div>`;
}
function cuPaintGrid() {
  if (cu.view !== "grid") return;
  const { g, cols, tw, th, gap } = cuGeom();
  const rows = Math.ceil(cu.order.length / cols);
  $("#cu-space").style.height = `${rows * (th + gap) + 8}px`;
  const top = g.scrollTop, h = g.clientHeight;
  const r0 = Math.max(0, Math.floor(top / (th + gap)) - 2), r1 = Math.min(rows, Math.ceil((top + h) / (th + gap)) + 2);
  const sig = [r0, r1, cols, tw, cu.rev, cu.cur, [...cu.picked].join(","), cu.order.length, cu.order[r0 * cols], cu.marks, cu.group].join("|");
  if (sig === cu.gridSig) return;
  cu.gridSig = sig;
  let html = "";
  for (let i = r0 * cols; i < Math.min(cu.order.length, r1 * cols); i++) {
    const p = cuP(cu.order[i]);
    html += cuTile(p, 8 + (i % cols) * (tw + gap), 8 + Math.floor(i / cols) * (th + gap), tw, th);
  }
  if (!cu.order.length) html = `<div class="cu-none">${cu.photos.size ? "Nothing matches what's shown: change Show or Problems on the left." : cuShoot() ? `<span class="spin"></span> Reading the photos…` : ""}</div>`;
  $("#cu-space").innerHTML = html;
  paintIcons($("#cu-space"));
}
function cuScrollTo(id) {
  if (cu.view !== "grid") return;
  const { g, cols, th, gap } = cuGeom();
  const i = cu.order.indexOf(id); if (i < 0) return;
  const y = 8 + Math.floor(i / cols) * (th + gap);
  if (y < g.scrollTop) g.scrollTop = y - 8;
  else if (y + th > g.scrollTop + g.clientHeight) g.scrollTop = y + th - g.clientHeight + 8;
  cu.gridSig = ""; cuPaintGrid();
}
function cuGridClick(e) {
  const b = e.target.closest("[data-burst]");
  if (b) { e.stopPropagation(); const k = +b.dataset.burst; cu.open.has(k) ? cu.open.delete(k) : cu.open.add(k); cuSort(); cu.gridSig = ""; cuPaintGrid(); return; }
  const t = e.target.closest("[data-p]"); if (!t) return;
  const id = +t.dataset.p;
  if (e.shiftKey && cu.anchor != null) {
    const a = cu.order.indexOf(cu.anchor), z = cu.order.indexOf(id);
    cu.order.slice(Math.min(a, z), Math.max(a, z) + 1).forEach((x) => cu.picked.add(x));
  } else if (e.metaKey || e.ctrlKey) {
    cu.picked.has(id) ? cu.picked.delete(id) : cu.picked.add(id); cu.anchor = id;
  } else { cu.picked.clear(); cu.anchor = id; }
  cu.cur = id;
  cu.gridSig = ""; cuPaintGrid(); cuPaintInfo(); cuPaintBar(); cuPaintTimeline();
}

// -- one big photo, and side by side ------------------------------------------------------------------
function cuSetView(v) {
  if (v === "compare" && !cuSurveyStart()) { toast("Nothing to survey", { small: "Select 2 to 16 photos (⌘-click or Shift-click), or stand on a burst" }); return; }
  if (v !== "compare" && cu.survey) { cu.survey = null; cu.picked.clear(); }  // (leaving the survey: its photos aren't left selected)
  cu.view = v; cu.zoom = null; cu.guide = false;
  $("#cu-grid").hidden = v !== "grid"; $("#cu-one").hidden = v === "grid";
  cu.gridSig = ""; cuPaintBar(); cuPaintMain(); cuPaintInfo();
  if (v === "grid") cuScrollTo(cu.cur);
}
// -- step 3, Finish: one page for everything after culling ------------------------------------------
// 1 clear out the rejects; 2 what to do with the keepers: crop them for posting (where, how they look,
// every crop checked with a plain label, the sharpness choice, where they go, one button), copy them
// as they are, or use them in AllProPhoto.
const CU_WHERE = [
  ["instagram", "Instagram post", "4:5 · 1,080 × 1,350"],
  ["story", "Story or Reel", "9:16 · 1,080 × 1,920"],
  ["youtube", "YouTube or widescreen", "16:9 · full detail"],
];
const CU_WHERE_MORE = [
  ["original", "Same size as the camera photo", "The crop enlarged back to the photo's full size"],
  ["ai", "Let AI choose each crop", "Its own shape and framing per photo (rate them with AI first)"],
];
const CU_LOOKS = [
  ["A", "Natural", "Clean color and light, like a pro edit. Most people want this one"],
  ["C", "Punchy", "A bit more color and contrast"],
  ["B", "Softer", "Gentler contrast, and the crop a little wider"],
  ["O", "No edits", "Just the crop, exactly as the camera made it"],
  ["D", "AI touch-up", "Gemini suggests the light and color; about $0.001–0.002 a photo"],
];
const CU_FOLDER = { instagram: "Culled - Instagram 4x5", story: "Culled - Story 9x16", youtube: "Culled - YouTube 16x9", original: "Culled - Original size", ai: "Culled - Best crop" };
const cuFin = () => cu.fin || (cu.fin = { what: store.get("cull.finWhat", "crop"), looks: new Set(store.get("cull.looks", ["A"])),
  fit: store.get("cull.fit", "widen"), out: new Set(), folder: {}, more: false });

function cuCenterBox(p, sizeKey) {
  const full = p.full || p.size || [3, 2];
  const a = sizeKey === "story" ? 9 / 16 : sizeKey === "youtube" ? 16 / 9 : sizeKey === "instagram" ? 4 / 5 : full[0] / full[1];
  const r = full[0] / full[1];
  const w = r > a ? a / r : 1, h = r > a ? 1 : r / a;
  return [(1 - w) / 2, (1 - h) / 2, (1 + w) / 2, (1 + h) / 2];
}
/* What the crop for this keeper will be, and a plain label saying why. */
function cuPlan(p, sizeKey, fit) {
  const mine = p.crop && !Array.isArray(p.crop) ? p.crop[sizeKey] : (Array.isArray(p.crop) ? p.crop : null);
  let box, kind = mine ? "yours" : "action";
  if (sizeKey === "ai" && !mine) {
    if (p.ai?.crop) { box = p.ai.crop; kind = "ai"; }
    else { box = p.crops?.best; kind = box ? "noai" : "none"; }
  } else box = mine || p.crops?.[CU_SHAPE[sizeKey]];
  if (!box) { box = cuCenterBox(p, sizeKey); kind = "none"; }
  let q = cuQual(p, sizeKey, box), f = q ? q.f : 1, fixed = "";
  if (f > 1.01 && fit === "widen") {
    const wide = cuWidened(p, sizeKey, box), wq = cuQual(p, sizeKey, wide);
    box = wide; fixed = wq && wq.f > 1.01 ? "softer" : "widened"; f = wq ? wq.f : 1;
  } else if (f > 1.01) fixed = fit === "native" ? "small" : "softer";
  const whole = (box[2] - box[0]) * (box[3] - box[1]) > 0.94;
  const L = {
    action: ["ok", "Cropped on the action"], yours: ["mine", "Your crop"], ai: ["ok", "AI's crop"],
    noai: ["warn", "Not rated by AI yet: the app's crop"], none: ["grey", "No players found: centered"],
  }[kind];
  let label = L, why = "";
  if (fixed === "widened") { label = ["ok", whole ? "Whole photo, to stay sharp" : "Widened a little to stay sharp"];
    why = sizeKey === "original" ? "Same size as the camera can only stay sharp uncropped" : "The crop was zoomed in too far for this size"; }
  else if (fixed === "softer") label = ["warn", `Softer: enlarged ${f.toFixed(1)}×`];
  else if (fixed === "small") label = ["grey", `Smaller file: ${q.cw.toLocaleString()} × ${q.ch.toLocaleString()} px`];
  else if (whole && kind !== "none") label = ["grey", "Whole photo: already framed well"];
  if (kind === "action" && p.team_fit?.[CU_SHAPE[sizeKey]]) { label = ["ok", "Whole team, on a soft border"];
    why = "A team photo is too wide for this shape: everyone stays in, with a blurred border above and below"; }
  return { box, label, why, f, kind, needsFit: q && q.f > 1.01 };
}

function cuFinishIds() {
  return [...cu.photos.values()].filter((p) => alive(p) && flagOf(p) === "keep").sort((a, b) => (a.t ?? 0) - (b.t ?? 0) || a.id - b.id).map((p) => p.id);
}
function cuOpenFinish() {
  cu.finish = true; cu.guide = false; cu.fromFinish = null; cuFin();
  $("#cu-grid").hidden = true; cuPaintAll();
}
function cuCloseFinish() { cu.finish = false; cu.fromFinish = null; cuPaintAll(); if (cu.view === "grid") { cu.gridSig = ""; cuPaintGrid(); } }

function cuPaintFinish(one) {
  const sh = cuShoot(), F = cuFin();
  const [c] = cuCounts();
  const all = cuFinishIds(), ids = all.filter((id) => !F.out.has(id));
  const size = cuSizeKey();
  const job = sh.job && (sh.job.what === "edit" || sh.job.what === "copy") ? sh.job : null;
  const made = (what) => !!(job && job.what === what && job.state !== "now" && job.state !== "failed" && (job.folder || "").split("/").pop() === folder);  // (then the next step is the folder)
  const plans = F.what === "crop" ? all.map((id) => [id, cuPlan(cuP(id), size, F.fit)]) : [];
  const enlargedN = plans.filter(([id, pl]) => !F.out.has(id) && pl.needsFit).length;
  const unrated = size === "ai" ? ids.filter((id) => !cuP(id).ai?.crop).length : 0;
  const folder = F.folder[F.what === "copy" ? "copy" : size] || (F.what === "copy" ? "Picks" : CU_FOLDER[size]);
  const where = (sh.folders[0] || "").split("/").filter(Boolean).pop() || "your photos";
  const looks = [...F.looks].filter((k) => k !== "D" || cu.ai);
  const tile = (k, ic, t, s) => `<button class="cu-what${F.what === k ? " on" : ""}" data-what="${k}">${icon(ic)}<b>${t}</b><span>${s}</span></button>`;
  const chip = (lab) => `<span class="cu-lab ${lab[0]}">${esc(lab[1])}</span>`;
  const keepScroll = one.querySelector(".cu-fin")?.scrollTop || 0;  // (a redraw never jumps you back to the top)
  const counts = {};
  plans.forEach(([id, pl]) => { if (!F.out.has(id)) counts[pl.label[1]] = [pl.label[0], (counts[pl.label[1]]?.[1] || 0) + 1]; });
  one.innerHTML = `<div class="cu-fin">
    <header class="cu-fin-h"><div><h1>Finish</h1><p>${plural(c.keep, "keeper")} · ${plural(c.reject, "reject")}</p></div>
      <button class="btn ghost" id="fin-back">${icon("left")} Back to the photos</button></header>

    <section class="cu-sec"><h2><span class="n">1</span> Clear out the rejects</h2>
      ${c.reject ? `<p>${plural(c.reject, "photo")} marked reject (by you or the app). Deleting moves ${c.reject === 1 ? "it" : "them"} to the Trash, with their RAW files: you can undo, or take ${c.reject === 1 ? "it" : "them"} back out of the Trash.</p>
        <div class="cu-row"><button class="btn" id="fin-look">${icon("eye")} Look at them first</button><button class="btn danger" id="fin-del">${icon("trash")} Delete ${plural(c.reject, "reject")}</button></div>`
      : `<p class="cu-done-t">${icon("check")} No rejects left. Nice.</p>`}</section>

    <section class="cu-sec"><h2><span class="n">2</span> What do you want to do with your ${plural(ids.length, "keeper")}?</h2>
      <div class="cu-whats">${tile("crop", "crop", "Crop them for posting", "Instagram, Story or YouTube, cropped on the action and edited")}
        ${tile("copy", "copy", "Copy them as they are", "The original files (and RAW), untouched, into one folder")}
        ${tile("use", "layers", "Use them in AllProPhoto", "Make looks, posters and reels from them")}</div>

    ${F.what === "crop" ? `
      <div class="cu-q-h"><b>Where will they be posted?</b></div>
      <div class="cu-wheres">${CU_WHERE.map(([k, t, s]) => `<button class="cu-where${size === k ? " on" : ""}" data-where="${k}"><b>${t}</b><span>${s}</span></button>`).join("")}</div>
      <button class="cu-more" id="fin-more">${F.more || CU_WHERE_MORE.some(([k]) => k === size) ? "Fewer choices" : "More choices"} ${icon("chev")}</button>
      ${F.more || CU_WHERE_MORE.some(([k]) => k === size) ? `<div class="cu-wheres more">${CU_WHERE_MORE.map(([k, t, s]) => `<button class="cu-where${size === k ? " on" : ""}" data-where="${k}"><b>${t}</b><span>${s}</span></button>`).join("")}</div>` : ""}
      ${size === "ai" && unrated ? `<div class="cu-note warn">${icon("info")}<span>${plural(unrated, "keeper")} ${unrated === 1 ? "hasn't" : "haven't"} been rated by AI yet, so ${unrated === 1 ? "it uses" : "they use"} the app's crop. <button class="btn small" id="fin-rate">Rate them with AI</button></span></div>` : ""}

      <div class="cu-q-h"><b>How should they look?</b><small>Pick one or more: you get one picture of each</small></div>
      <div class="cu-looks">${CU_LOOKS.map(([k, t, s]) => `<label class="cu-look${F.looks.has(k) ? " on" : ""}${k === "D" && !cu.ai ? " dis" : ""}" title="${esc(k === "D" && !cu.ai ? "Needs a Gemini key (add it to ~/.zshrc)" : s)}"><input type="checkbox" data-look="${k}" ${F.looks.has(k) ? "checked" : ""} ${k === "D" && !cu.ai ? "disabled" : ""}><b>${t}</b><span>${s}</span></label>`).join("")}</div>

      <div class="cu-q-h"><b>Check your crops</b><small>Click a photo to change its crop · × to leave it out</small></div>
      <div class="cu-sum">${Object.entries(counts).map(([t, [k, n]]) => `<span class="cu-lab ${k}">${n} · ${esc(t)}</span>`).join("")}</div>
      <div class="cu-crops">${plans.map(([id, pl]) => { const p = cuP(id), b = pl.box, out = F.out.has(id);
        return `<div class="cu-cc${out ? " out" : ""}" data-cc="${id}" title="${esc(p.name)}${pl.why ? ": " + esc(pl.why) : ""}">
          <div class="im"><img src="/img/cull/${cu.sel}/${id}/thumb.jpg" alt="" loading="lazy">
            <span class="cu-cbox" style="left:${b[0] * 100}%;top:${b[1] * 100}%;width:${(b[2] - b[0]) * 100}%;height:${(b[3] - b[1]) * 100}%"></span></div>
          ${out ? `<span class="cu-lab grey">Left out</span>` : chip(pl.label)}
          <button class="x" data-out="${id}" title="${out ? "Put it back in" : "Leave this one out"}">${icon(out ? "plus" : "x")}</button></div>`; }).join("")}</div>

      ${enlargedN ? `<div class="cu-q-h"><b>${plural(enlargedN, "crop is", "crops are")} zoomed in further than ${size === "original" ? "the camera size" : "this size"} can hold</b><small>${size === "original" ? "Same size as the camera always enlarges a crop" : "Making them bigger would make them softer"}</small></div>
        <div class="cu-fits">${[["widen", "Widen them just enough to stay sharp", "Recommended: no quality lost"], ["native", "Keep their own pixels", "A smaller picture, never enlarged"], ["enlarge", "Enlarge them anyway", "Full size, but softer"]]
          .map(([k, t, s]) => `<label class="cu-fit2${F.fit === k ? " on" : ""}"><input type="radio" name="fin-fit" value="${k}" ${F.fit === k ? "checked" : ""}><b>${t}</b><span>${s}</span></label>`).join("")}</div>` : ""}

      <div class="cu-q-h"><b>Where they go</b></div>
      <div class="cu-dest">${icon("folder")}<span>A new folder next to your photos in “${esc(where)}”:</span><input id="fin-folder" value="${esc(folder)}" spellcheck="false"></div>
      <div class="cu-make">${job?.state === "now" ? cuJobBar(job) : `<button class="btn ${made("edit") ? "ghost" : "primary big"}" id="fin-go" ${off(!ids.length || !looks.length, !ids.length ? "No keepers to make" : "Choose how they should look")}>
          ${icon("crop")} ${made("edit") ? "Make them again" : `Make ${plural(ids.length * Math.max(1, looks.length), "picture")}`}</button><small>${plural(ids.length, "keeper")} × ${plural(looks.length, "look")}. Your originals are never changed.</small>`}</div>
      ${made("edit") || (job?.what === "edit" && job.state === "failed") ? cuJobDone(job) : ""}` : ""}

    ${F.what === "copy" ? `
      <div class="cu-dest">${icon("folder")}<span>A new folder next to your photos in “${esc(where)}”:</span><input id="fin-folder" value="${esc(folder)}" spellcheck="false"></div>
      ${ids.some((id) => cuP(id).label) ? `<label class="cu-fit2 cu-bylabel${F.byLabel !== false ? " on" : ""}"><input type="checkbox" id="fin-bylabel" ${F.byLabel !== false ? "checked" : ""}><b>A folder for each label inside it</b><span>${[1, 2, 3, 4, 5].filter((n) => ids.some((id) => cuP(id).label === n)).map((n) => `${cuLabelDot(n)} ${esc(labelName(n))} (${ids.filter((id) => cuP(id).label === n).length})`).join(" · ")}${ids.some((id) => !cuP(id).label) ? ` · the rest (${ids.filter((id) => !cuP(id).label).length}) in the folder itself` : ""}</span></label>` : ""}
      <div class="cu-make">${job?.state === "now" ? cuJobBar(job) : `<button class="btn ${made("copy") ? "ghost" : "primary big"}" id="fin-go" ${off(!ids.length, "No keepers")}>${icon("copy")} ${made("copy") ? "Copy them again" : `Copy ${plural(ids.length, "photo")}`}</button><small>Exactly as they are, with their RAW files. Nothing is changed or moved.</small>`}</div>
      ${made("copy") || (job?.what === "copy" && job.state === "failed") ? cuJobDone(job) : ""}` : ""}

    ${F.what === "use" ? `<div class="cu-uses">
      <button class="cu-use2" data-send="looks">${icon("wand")}<b>Make looks</b><span>Your ${plural(ids.length, "keeper")} go into the Looks tab: make looks, posters and team posters from them</span></button>
      <button class="cu-use2" data-send="reel">${icon("film")}<b>Make a reel</b><span>They go into Looks; make a look of each, then build the Instagram reel</span></button></div>` : ""}
    </section></div>`;
  paintIcons(one);
  one.querySelector(".cu-fin").scrollTop = keepScroll;
  if (cu.finScrollTo) { const el = one.querySelector(cu.finScrollTo); cu.finScrollTo = null; el?.scrollIntoView({ block: "center", behavior: "smooth" }); }
  $("#fin-back", one).onclick = cuCloseFinish;
  $("#fin-del", one)?.addEventListener("click", cuDeleteRejects);
  $("#fin-look", one)?.addEventListener("click", () => { cu.finish = false; cu.show = "reject"; cu.sort = "score"; cu.issues.clear(); cuRefilter(); cuSetView("grid");
    toast("The rejects, the ones the app liked best first", { small: "P keeps one. Back to Finish with the 3 button at the top" }); });
  one.querySelectorAll("[data-what]").forEach((b) => b.onclick = () => { F.what = b.dataset.what; store.set("cull.finWhat", F.what); cuPaintFinish(one); });
  one.querySelectorAll("[data-where]").forEach((b) => b.onclick = () => { cuSetSize(b.dataset.where); cuPaintFinish(one); });
  $("#fin-more", one)?.addEventListener("click", () => { F.more = !(F.more || CU_WHERE_MORE.some(([k]) => k === size)); if (!F.more && CU_WHERE_MORE.some(([k]) => k === size)) cuSetSize("instagram"); cuPaintFinish(one); });
  $("#fin-rate", one)?.addEventListener("click", () => cuOut("ai", ids));
  one.querySelectorAll("[data-look]").forEach((x) => x.onchange = () => { x.checked ? F.looks.add(x.dataset.look) : F.looks.delete(x.dataset.look); store.set("cull.looks", [...F.looks]); cuPaintFinish(one); });
  one.querySelectorAll("input[name=fin-fit]").forEach((x) => x.onchange = () => { F.fit = x.value; store.set("cull.fit", F.fit); cuPaintFinish(one); });
  one.querySelectorAll("[data-out]").forEach((b) => b.onclick = (e) => { e.stopPropagation(); const id = +b.dataset.out; F.out.has(id) ? F.out.delete(id) : F.out.add(id); cuPaintFinish(one); });
  one.querySelectorAll("[data-cc]").forEach((el) => el.onclick = () => {
    cu.cur = +el.dataset.cc; cu.fromFinish = cuSizeKey(); cu.finish = false; cu.cropShow = true; store.set("cull.crop", true);
    cuSetView("one");
  });
  $("#fin-bylabel", one)?.addEventListener("change", (e) => { F.byLabel = e.target.checked; cuPaintFinish(one); });
  $("#fin-folder", one)?.addEventListener("change", (e) => { F.folder[F.what === "copy" ? "copy" : size] = e.target.value.trim(); });
  $("#fin-go", one)?.addEventListener("click", async () => {
    if (!ids.length) return;
    const name = ($("#fin-folder", one)?.value || "").trim() || folder;
    if (F.what === "copy") await api(`/api/cull/shoots/${sh.id}/export`, { what: "copy", ids, folder: name, by_label: F.byLabel !== false });
    else { if (!looks.length) return; await api(`/api/cull/shoots/${sh.id}/export`, { what: "edit", ids, size, versions: looks.join(""), fit: F.fit, folder: name, crops: Object.fromEntries(plans.filter(([id]) => !F.out.has(id)).map(([id, pl]) => [id, pl.box])) }); }
    cu.finScrollTo = ".cu-make"; await cuState(); cuPaintFinish(one); cuPoll();
  });
  one.querySelectorAll("[data-send]").forEach((b) => b.onclick = () => cuOut(b.dataset.send, ids));
  one.querySelectorAll("[data-open]").forEach((b) => b.onclick = () => api("/api/reveal", { path: b.dataset.open }));
  $("#fin-again", one)?.addEventListener("click", () => { sh.job = null; cuPaintFinish(one); });
}
function cuJobBar(j) {
  const pct = j.total ? Math.round(j.done / j.total * 100) : 0;
  return `<div class="cu-prog2"><b>${j.what === "copy" ? "Copying" : "Making"} ${j.done} of ${j.total}…</b><i><u style="width:${pct}%"></u></i><small>You can keep culling meanwhile</small></div>`;
}
function cuJobDone(j) {
  if (j.state === "failed") return `<div class="cu-note bad">${icon("info")}<span>It stopped: ${esc(j.error || "")}</span></div>`;
  const f = j.folder || "";
  return `<div class="cu-done">${icon("check")}<div><b>All done! ${plural(j.done, j.what === "copy" ? "photo" : "keeper")} ${j.what === "copy" ? "copied" : "made"}</b>
    <span class="next">Next: open the folder to see them, post them or send them.</span>
    <span>${esc(f.replace(/^\/Users\/[^/]+/, "~"))}</span></div><button class="btn primary" data-open="${esc(f)}">${icon("folder")} Open the folder</button>
    ${j.what === "edit" ? `<button class="btn ghost" id="fin-again">Make another size</button>` : ""}</div>
    ${(() => { const best = [...cu.photos.values()].filter((p) => alive(p) && flagOf(p) === "keep").sort((a, b) => (b.score ?? 0) - (a.score ?? 0)).slice(0, 6);
      return best.length >= 3 ? `<div class="cu-bestof"><b>${icon("star")} The best of the event</b><div>${best.map((p) => `<img src="/img/cull/${cu.sel}/${p.id}/thumb.jpg" alt="" title="${esc(p.name)}">`).join("")}</div></div>` : ""; })()}`;
}

// -- the fun parts: pass 1's reveal, a snappy mark, and the best of the event ----------------------
/* Pass 1 just finished: what it found, your best shot of the event, and one big button to start. */
function cuReveal(force = false) {
  const sh = cuShoot(); if (!sh || !sh.pass1) return;
  const seen = store.get("cull.revealed", {});
  if (!force && seen[sh.id]) return;
  seen[sh.id] = 1; store.set("cull.revealed", seen);
  const all = [...cu.photos.values()].filter(alive), [c, iss] = cuCounts();
  const keepers = all.filter((p) => flagOf(p) === "keep").sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
  const hero = keepers[0], more = keepers.slice(1, 5);
  if (!hero) return;
  const bursts = new Set(all.filter((p) => p.bsize > 1).map((p) => p.burst)).size;
  const secs = sh.took ? Math.round(sh.took) : null;
  const m = modal(`<div class="cu-reveal">
      <div class="hero"><img src="/img/cull/${cu.sel}/${hero.id}/view.jpg" alt=""><span class="tag">${icon("star")} Your best shot of the event</span></div>
      <div class="side"><h2>Pass 1 is done!</h2>
        <div class="big"><b>${all.length.toLocaleString()}</b><span>photos</span>${icon("right")}<b class="g">${c.keep.toLocaleString()}</b><span>keepers</span></div>
        ${secs ? `<p class="took">in ${secs < 90 ? plural(secs, "second") : say(secs).replace("about ", "")}, on your Mac</p>` : ""}
        <ul>${[iss.dupe ? `${plural(iss.dupe, "near copy", "near copies")} set aside${bursts ? ` from ${plural(bursts, "burst")}` : ""}` : "",
          iss.blur ? `${plural(iss.blur, "soft photo")} caught` : "", iss.eyes ? `${plural(iss.eyes, "closed-eye shot")} caught` : "",
          `<b>${plural(c.unsure, "photo")}</b> for you to check, the close calls`].filter(Boolean).map((x) => `<li>${x}</li>`).join("")}</ul>
        <div class="more">${more.map((p) => `<img src="/img/cull/${cu.sel}/${p.id}/thumb.jpg" alt="">`).join("")}</div>
        <button class="btn primary big" id="rv-go">Start your pass${c.unsure ? ` (${c.unsure} close calls)` : ""}</button>
        <button class="btn ghost" data-close>Look around first</button></div></div>`);
  paintIcons(m);
  m.classList.add("wide");
  $("#rv-go", m).onclick = () => { closeModal(); $("#cu-pass2")?.click(); };
}
/* A quick, satisfying pop on each keep or reject. */
function cuPop(flag) {
  if (!flag) return;
  const host = cu.view === "grid" ? $(`#cu-space [data-p="${cu.cur}"] .im`) : $("#cu-stage");
  if (!host) return;
  const el = document.createElement("span");
  el.className = `cu-pop ${flag}`; el.innerHTML = icon(flag === "keep" ? "keep" : "reject");
  host.appendChild(el); paintIcons(host);
  setTimeout(() => el.remove(), 650);
}

// -- the start page: the three things culling does, and how ------------------------------------------
const CU_THREE = [
  ["keep", "Find the keepers in minutes", "The app goes through the whole event for you and marks the best frame of every moment: sharp on the player, eyes open, the ball in play. Each mark says why."],
  ["trash", "Clear out the rest, safely", "You check its picks fast (the ones it's unsure about first), then delete the rejects in one go. They go to the Trash, with undo: nothing is lost by accident."],
  ["export", "Get the best ready to post", "Each keeper is cropped on the action for Instagram, Story or YouTube with a clean edit, copied to a Picks folder, or sent to Looks and Reel."],
];
function cuGuide(one, back) {
  const card = cu.cards[0];
  one.innerHTML = `<div class="cu-guide">
    ${back ? `<button class="btn ghost" id="cu-guide-back">${icon("left")} Back to ${esc(cuShoot()?.name || "the photos")}</button>` : ""}
    <h1>Culling</h1><p class="lead">From a full memory card to the photos worth sharing.</p>
    <div class="cu-three">${CU_THREE.map(([ic, t, s], i) => `<div class="cu-three-c"><span class="n">${i + 1}</span>${icon(ic)}<b>${t}</b><p>${s}</p></div>`).join("")}</div>
    ${back ? "" : `<div class="cu-go"><button class="btn primary big" data-go="folder">${icon("plus")} Add an event's folder…</button>
      <button class="btn big" data-go="card">${icon("card")} ${card ? `Import from ${esc(card.name)} (${card.photos.toLocaleString()} photos)` : "Import from the camera card…"}</button></div>
      <p class="faint">Your photos stay where they are. Nothing leaves your Mac unless you ask the AI to rate (it shows the cost first).</p>`}
    <h2>How it goes</h2>
    <ol class="ck-steps">
      <li><span class="n">1</span><div><b>Pass 1: the app</b><p>Marks every photo keep or reject, with the reason and how sure it is. Bursts become one stack with the best frame on top. A thousand photos take about 8 minutes, and you can start looking straight away.</p></div></li>
      <li><span class="n">2</span><div><b>Your pass</b><p>Press <b>Your pass</b>: unsure photos first. <kbd>P</kbd> keep, <kbd>X</kbd> reject, <kbd>→</kbd> next, <kbd>Space</kbd> big, <kbd>Z</kbd> 100% on the face, <kbd>C</kbd> compare a burst. Your mark always wins, and teaches the app your taste.</p></div></li>
      <li><span class="n">3</span><div><b>Finish</b><p><b>Delete rejects</b>, then <b>Keepers</b>: crop and edit, copy, or send to Looks and Reel.</p></div></li></ol></div>`;
  paintIcons(one);
  one.querySelectorAll("[data-go]").forEach((b) => b.onclick = () => b.dataset.go === "card" ? cuImport() : cuAddFolder());
  $("#cu-guide-back", one)?.addEventListener("click", () => { cu.guide = false; cuPaintAll(); });
}

function cuPaintMain() {
  const showGuide = cu.guide || !cuShoot();
  $("#cull").classList.toggle("guiding", showGuide || !!cu.finish);
  if (showGuide) { $("#cu-grid").hidden = true; const one = $("#cu-one"); one.hidden = false; cuGuide(one, !!cuShoot()); return; }
  if (cu.finish) { $("#cu-grid").hidden = true; const one = $("#cu-one"); one.hidden = false; cuPaintFinish(one); return; }
  if (cu.view === "grid") { $("#cu-grid").hidden = false; $("#cu-one").hidden = true; cuPaintGrid(); return; }
  if (cu.view === "compare") return cuPaintCompare();
  const one = $("#cu-one"), p = cuP(cu.cur);
  if (!p) { one.innerHTML = `<div class="cu-none">Nothing to show</div>`; return; }
  const f = flagOf(p);
  const frames = p.bsize > 1 ? [...cu.photos.values()].filter((q) => alive(q) && q.burst === p.burst).sort((a, b) => (a.t ?? 0) - (b.t ?? 0) || a.id - b.id) : [];
  const sizeKey = cuSizeKey(), box = cuCropOf(p, sizeKey), q = box && cuQual(p, sizeKey, box);
  const fromFin = cu.fromFinish ? `<div class="cu-adjust">${icon("crop")}<span><b>Changing the crop for ${esc((CU_WHERE.concat(CU_WHERE_MORE).find(([k]) => k === cu.fromFinish) || [0, CU_SIZE_NAME[cu.fromFinish]])[1])}</b> · drag it to move, scroll on it to resize · ← → for the next keeper</span><button class="btn primary" id="cu-adjust-done">${icon("check")} Done: back to Finish</button></div>` : "";
  one.classList.toggle("adjusting", !!fromFin);
  one.innerHTML = fromFin + `<div class="cu-stage${f ? " f-" + f : ""}" id="cu-stage">
      ${cu.zoom ? `<div class="cu-zoom"><img src="/img/cull/${cu.sel}/${p.id}/zoom.jpg?x=${cu.zoom.x.toFixed(4)}&y=${cu.zoom.y.toFixed(4)}&w=${Math.round(one.clientWidth * devicePixelRatio)}&h=${Math.round((one.clientHeight - 120) * devicePixelRatio)}" alt="">
          <span class="tag">100% · click to look elsewhere · Z or Esc to go back</span></div>`
      : `<div class="cu-pic" id="cu-pic"><img id="cu-img" src="/img/cull/${cu.sel}/${p.id}/view.jpg" alt="" draggable="false">
          ${cu.cropShow && box ? `<div class="cu-crop" id="cu-crop" style="left:${box[0] * 100}%;top:${box[1] * 100}%;width:${(box[2] - box[0]) * 100}%;height:${(box[3] - box[1]) * 100}%" title="The crop on the action: drag to move it; scroll to resize"><i></i><span class="cu-px${q && q.f > 1.01 ? " soft" : ""}" id="cu-px">${q ? cuQualText(q, true) : ""}</span></div>` : ""}
          ${p.focus && cu.marks ? `<span class="cu-af" style="left:${p.focus[0] * 100}%;top:${p.focus[1] * 100}%" title="Where the camera focused"></span>` : ""}</div>`}
      <div class="cu-verdict">${f ? `<span class="v-${f}">${icon(f === "keep" ? "keep" : "reject")} ${f === "keep" ? "Keep" : "Reject"}</span><small>${yours(p) ? "your mark" : `pass 1 · ${Math.round((p.auto?.[1] || 0) * 100)}% sure`}</small>` : `<small>Not marked yet</small>`}</div></div>
    <div class="cu-strip">
      ${p.faces?.length ? `<div class="cu-faces" title="Faces up close: check the eyes">${p.faces.slice(0, 4).map((fc, i) => `<button class="cu-face" data-face="${i}" title="See this face at 100%" style="${cuFaceStyle(p, fc)}">${fc.eyes != null && fc.px >= 60 && fc.eyes < 0.17 ? `<em>eyes?</em>` : ""}</button>`).join("")}</div>` : ""}
      ${frames.length ? `<div class="cu-frames"><small>Burst · ${frames.length} frames</small>${frames.map((q) => `<button class="cu-fr${q.id === p.id ? " on" : ""}${flagOf(q) ? " f-" + flagOf(q) : ""}" data-fr="${q.id}" title="${esc(q.name)} · score ${q.score ?? "-"}${q.best ? " · the best of the burst" : ""}"><img src="/img/cull/${cu.sel}/${q.id}/thumb.jpg" alt="">${q.best ? "<b>★</b>" : ""}</button>`).join("")}</div>` : ""}
      <div class="cu-acts"><button class="btn${f === "keep" ? " primary" : ""}" data-mk="keep" title="Keep (P)">${icon("keep")} Keep</button><button class="btn${f === "reject" ? " danger" : ""}" data-mk="reject" title="Reject (X)">${icon("reject")} Reject</button></div></div>`;
  paintIcons(one);
  one.querySelectorAll("[data-mk]").forEach((b) => b.onclick = () => cuMark(b.dataset.mk));
  $("#cu-adjust-done", one)?.addEventListener("click", cuOpenFinish);
  one.querySelectorAll("[data-fr]").forEach((b) => b.onclick = () => { cu.cur = +b.dataset.fr; cuPaintMain(); cuPaintInfo(); cuPaintTimeline(); });
  one.querySelectorAll("[data-face]").forEach((b) => b.onclick = () => { const fc = p.faces[+b.dataset.face]; cu.zoom = { x: (fc.box[0] + fc.box[2]) / 2, y: (fc.box[1] + fc.box[3]) / 2 }; cuPaintMain(); });
  $("#cu-img")?.addEventListener("click", (e) => { const r = e.target.getBoundingClientRect(); cu.zoom = { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height }; cuPaintMain(); });
  $(".cu-zoom img", one)?.addEventListener("click", (e) => {
    const r = e.target.getBoundingClientRect(), z = cu.zoom, img = e.target;
    const box = (img.dataset.box || "").split(",").map(Number);
    const fw = img.naturalWidth, fh = img.naturalHeight; if (!fw) return;
    // move by how far from the middle of the 100% view you clicked
    const dx = ((e.clientX - r.left) / r.width - 0.5), dy = ((e.clientY - r.top) / r.height - 0.5);
    const share = box.length === 4 ? [box[2] - box[0], box[3] - box[1]] : [0.3, 0.3];
    cu.zoom = { x: Math.min(1, Math.max(0, z.x + dx * share[0])), y: Math.min(1, Math.max(0, z.y + dy * share[1])) };
    cuPaintMain();
  });
  const zi = $(".cu-zoom img", one);
  if (zi) fetch(zi.src).then((r) => { const b = r.headers.get("X-Box"); if (b) zi.dataset.box = b; }).catch(() => {});
  cuFitPic();
  if (cu.picking) cuPickLayer();
  cuCropDrag(p);
  // the next and previous ones load while you look
  [1, -1].forEach((d) => { const q = cu.order[cu.order.indexOf(p.id) + d]; if (q != null) new Image().src = `/img/cull/${cu.sel}/${q}/view.jpg`; });
}
function cuFitPic() {
  const st = $("#cu-stage"), img = $("#cu-img"); if (!st || !img) return;
  img.style.maxHeight = `${Math.max(120, st.clientHeight - 24)}px`;
  img.style.maxWidth = `${Math.max(120, st.clientWidth - 24)}px`;
}
const CU_SHAPE = { instagram: "4:5", story: "9:16", youtube: "16:9", original: "wide", ai: "best" };
const CU_TARGET = { instagram: [1080, 1350], story: [1080, 1920] };
const CU_SIZE_NAME = { instagram: "Instagram", story: "Story", youtube: "YouTube", original: "Original", ai: "Best crop" };
// the size you chose wins on this screen (a refresh from the server a moment before it's saved can't undo it)
const cuSizeKey = () => (cu.sizeLocal || {})[cu.sel] || cuShoot()?.settings?.size || "instagram";
function cuSetSize(k) {
  const sh = cuShoot(); if (!sh) return;
  (cu.sizeLocal || (cu.sizeLocal = {}))[sh.id] = k; sh.settings.size = k;
  api(`/api/cull/shoots/${sh.id}`, { settings: { size: k } }, { method: "PATCH" }).catch(() => {});
}
/* Your crop for this size (kept per size), else the automatic one. */
function cuCropOf(p, sizeKey) {
  const mine = p.crop && !Array.isArray(p.crop) ? p.crop[sizeKey] : p.crop;
  return mine || p.crops?.[CU_SHAPE[sizeKey] || "best"] || null;
}
/* How many real pixels the crop has, what the size needs, and how much it would be enlarged (f > 1: softer). */
function cuQual(p, sizeKey, box) {
  const full = p.full || p.size; if (!full || !box) return null;
  const cw = Math.round((box[2] - box[0]) * full[0]), ch = Math.round((box[3] - box[1]) * full[1]);
  const t = sizeKey === "original" ? full : CU_TARGET[sizeKey];
  const f = t ? Math.max(t[0] / Math.max(1, cw), t[1] / Math.max(1, ch)) : 1;
  return { cw, ch, t, f };
}
function cuQualText(q, short = false) {
  const px = `${q.cw.toLocaleString()} × ${q.ch.toLocaleString()} px`;
  if (!q.t) return short ? `${px} · full detail` : `${px}: saved at its own size, full detail`;
  if (q.f <= 1.01) return short ? `${px} · sharp` : `${px}: sharp at ${q.t[0].toLocaleString()} × ${q.t[1].toLocaleString()}, nothing enlarged`;
  return short ? `${px} · enlarged ${q.f.toFixed(1)}×` : `${px}: would be enlarged ${q.f.toFixed(1)}× to ${q.t[0].toLocaleString()} × ${q.t[1].toLocaleString()}, so softer`;
}
/* The crop grown around its middle (same shape) until nothing is enlarged, inside the photo. */
function cuWidened(p, sizeKey, box) {
  const q = cuQual(p, sizeKey, box); if (!q || q.f <= 1) return box;
  let w = (box[2] - box[0]) * q.f, h = (box[3] - box[1]) * q.f;
  if (w > 1 || h > 1) { const s = 1 / Math.max(w, h); w *= s; h *= s; }
  const cx = (box[0] + box[2]) / 2, cy = (box[1] + box[3]) / 2;
  const x = Math.min(Math.max(cx - w / 2, 0), 1 - w), y = Math.min(Math.max(cy - h / 2, 0), 1 - h);
  return [x, y, x + w, y + h].map((v) => +v.toFixed(4));
}
function cuSaveCrop(p, sizeKey, box, label) {
  const all = p.crop && !Array.isArray(p.crop) ? { ...p.crop } : {};
  if (box) all[sizeKey] = box; else delete all[sizeKey];
  cuSet([p.id], { crop: Object.keys(all).length ? all : null }, label);
}
function cuFaceStyle(p, fc) {
  const [x0, y0, x1, y1] = fc.box, w = x1 - x0, h = y1 - y0, pad = 0.6;
  const W = w * (1 + pad * 2), H = h * (1 + pad * 2), cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  return `background-image:url(/img/cull/${cu.sel}/${p.id}/view.jpg);background-size:${100 / W}% ${100 / H}%;background-position:${((cx - W / 2) / Math.max(1e-6, 1 - W)) * 100}% ${((cy - H / 2) / Math.max(1e-6, 1 - H)) * 100}%`;
}
function cuCropDrag(p) {
  const c = $("#cu-crop"); if (!c) return;
  const pic = $("#cu-pic");
  const cur = () => [parseFloat(c.style.left) / 100, parseFloat(c.style.top) / 100, (parseFloat(c.style.left) + parseFloat(c.style.width)) / 100, (parseFloat(c.style.top) + parseFloat(c.style.height)) / 100];
  const put = (b) => { c.style.left = `${b[0] * 100}%`; c.style.top = `${b[1] * 100}%`; c.style.width = `${(b[2] - b[0]) * 100}%`; c.style.height = `${(b[3] - b[1]) * 100}%`; };
  const clampB = (b) => { const w = b[2] - b[0], h = b[3] - b[1]; const x = Math.min(Math.max(b[0], 0), 1 - w), y = Math.min(Math.max(b[1], 0), 1 - h); return [x, y, x + w, y + h]; };
  let saveT = null;
  const sizeKey = cuSizeKey();
  const label = () => { const q = cuQual(p, sizeKey, cur()); const el = $("#cu-px"); if (q && el) { el.textContent = cuQualText(q, true); el.classList.toggle("soft", q.f > 1.01); } };
  const save = (b) => { label(); clearTimeout(saveT); saveT = setTimeout(() => cuSaveCrop(p, sizeKey, b.map((v) => +v.toFixed(4)), "Move the crop"), 350); };
  c.onpointerdown = (e) => {
    e.preventDefault(); c.setPointerCapture(e.pointerId);
    const r = pic.getBoundingClientRect(), start = cur(), sx = e.clientX, sy = e.clientY;
    c.onpointermove = (m) => { put(clampB([start[0] + (m.clientX - sx) / r.width, start[1] + (m.clientY - sy) / r.height, start[2] + (m.clientX - sx) / r.width, start[3] + (m.clientY - sy) / r.height])); label(); };
    c.onpointerup = () => { c.onpointermove = null; save(cur()); };
  };
  c.onwheel = (e) => {
    e.preventDefault();
    const b = cur(), k = e.deltaY > 0 ? 1.03 : 0.97, cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2;
    let w = (b[2] - b[0]) * k, h = (b[3] - b[1]) * k;
    if (w > 1 || h > 1) { const s = 1 / Math.max(w, h); w *= s; h *= s; }
    if (w < 0.12) return;
    const nb = clampB([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]); put(nb); save(nb);
  };
}
function cuCompareIds() {
  if (cu.picked.size >= 2) return [...cu.picked].slice(0, 4);
  const p = cuP(cu.cur);
  if (p && p.bsize > 1) return [...cu.photos.values()].filter((q) => alive(q) && q.burst === p.burst).sort((a, b) => (b.score ?? 0) - (a.score ?? 0)).slice(0, 4).map((q) => q.id);
  return [];
}
function cuPaintCompare() {
  const one = $("#cu-one"), ids = cuCompareIds();
  if (ids.length < 2) { cuSetView("one"); return; }
  if (!ids.includes(cu.cur)) cu.cur = ids[0];
  const z = cu.zoom;
  one.innerHTML = `<div class="cu-cmp" style="--n:${ids.length}">${ids.map((id) => { const p = cuP(id), f = flagOf(p);
      const face = p.faces?.find((x) => x.main) || p.faces?.[0];
      const at = z || (face ? { x: (face.box[0] + face.box[2]) / 2, y: (face.box[1] + face.box[3]) / 2 } : p.subject ? { x: (p.subject[0] + p.subject[2]) / 2, y: (p.subject[1] + p.subject[3]) / 2 } : { x: 0.5, y: 0.5 });
      return `<div class="cu-c${id === cu.cur ? " cur" : ""}${f ? " f-" + f : ""}" data-c="${id}">
        <div class="im">${cu.zoom !== null ? `<img src="/img/cull/${cu.sel}/${id}/zoom.jpg?x=${at.x.toFixed(4)}&y=${at.y.toFixed(4)}&w=700&h=700" alt="">` : `<img src="/img/cull/${cu.sel}/${id}/view.jpg" alt="">`}</div>
        <div class="cap"><b>${esc(p.name)}</b><span>${p.score ?? "-"}${p.best ? " · best of burst" : ""}</span>${p.issues.filter((i) => i !== "dupe").map((i) => `<i>${esc(CU_ISSUE[i][0])}</i>`).join("")}</div>
        <div class="acts"><button class="btn small${f === "keep" ? " primary" : ""}" data-ck="${id}" title="Keep this one">${icon("keep")}</button><button class="btn small${f === "reject" ? " danger" : ""}" data-cx="${id}" title="Reject this one">${icon("reject")}</button>
          <button class="btn small ghost" data-only="${id}" title="Keep this one and reject the others shown">Only this one</button></div></div>`; }).join("")}</div>
    <div class="cu-cmp-tip">${cu.zoom !== null ? "Faces at 100%, side by side · Z to see whole photos" : "Z: the faces at 100%, side by side"} · click one to make it current</div>`;
  paintIcons(one);
  one.querySelectorAll("[data-c]").forEach((el) => el.onclick = (e) => { if (e.target.closest("button")) return; cu.cur = +el.dataset.c; cuPaintCompare(); cuPaintInfo(); });
  one.querySelectorAll("[data-ck]").forEach((b) => b.onclick = () => cuSet([+b.dataset.ck], { flag: "keep" }, "Keep"));
  one.querySelectorAll("[data-cx]").forEach((b) => b.onclick = () => cuSet([+b.dataset.cx], { flag: "reject" }, "Reject"));
  one.querySelectorAll("[data-only]").forEach((b) => b.onclick = () => {
    const keep = +b.dataset.only;
    cuSet(ids, (id) => ({ flag: id === keep ? "keep" : "reject" }), "Keep only this one");
  });
}

// -- Survey: up to 16 side by side; drop the weaker ones until the best are left ------------------
// (Aftershoot's Survey Mode, plus: drop instead of reject while deciding, one click to keep what's left
// and reject the dropped (one undo), and every photo zooming to 100% on the same spot together)
const SURVEY_MAX = 16;
function cuSurveyStart() {
  let ids = [];
  if (cu.picked.size >= 2) ids = [...cu.picked];
  else {
    const p = cuP(cu.cur);
    if (p && p.bsize > 1) ids = [...cu.photos.values()].filter((q) => alive(q) && q.burst === p.burst).sort((a, b) => (b.score ?? 0) - (a.score ?? 0)).map((q) => q.id);
  }
  ids = ids.filter((id) => cuP(id) && alive(cuP(id))).slice(0, SURVEY_MAX);
  cu.survey = ids.length >= 2 ? { ids, dropped: new Set(), at: null } : null;
  return !!cu.survey;
}
function cuCompareIds() { return cu.survey ? cu.survey.ids.filter((id) => !cu.survey.dropped.has(id)) : []; }
function cuPaintCompare() {
  const one = $("#cu-one"), sv = cu.survey;
  if (!sv) { cuSetView("one"); return; }
  const ids = cuCompareIds(), dropped = sv.ids.filter((id) => sv.dropped.has(id));
  if (!ids.includes(cu.cur)) cu.cur = ids[0];
  const n = ids.length, cols = n <= 2 ? n : n <= 4 ? 2 : n <= 9 ? 3 : 4;
  const zoomed = cu.zoom !== null;
  const spot = (p) => {
    if (sv.at) return sv.at;
    const face = p.faces?.find((x) => x.main) || p.faces?.[0];
    return face ? { x: (face.box[0] + face.box[2]) / 2, y: (face.box[1] + face.box[3]) / 2 } : p.subject ? { x: (p.subject[0] + p.subject[2]) / 2, y: (p.subject[1] + p.subject[3]) / 2 } : { x: 0.5, y: 0.5 };
  };
  const side = Math.round(Math.min(900, 1800 / cols) * devicePixelRatio);
  one.innerHTML = `<div class="cu-svbar"><b>Survey</b><span>${plural(n, "photo")} left${dropped.length ? ` · ${dropped.length} dropped` : ""}</span>
      <span class="grow"></span>
      ${dropped.length ? `<button class="btn ghost small" id="sv-back">Bring the dropped back (U)</button>` : ""}
      ${n === 1 && dropped.length ? `<button class="btn primary small" id="sv-win">${icon("keep")} Keep the winner, reject the ${dropped.length} others</button>`
        : dropped.length ? `<button class="btn primary small" id="sv-keep">${icon("keep")} Keep these ${n}, reject the ${dropped.length} dropped (Enter)</button>` : ""}
      <button class="btn ghost small" id="sv-zoom">${zoomed ? "Whole photos (Z)" : "Zoom to 100% (Z)"}</button>
      <button class="btn ghost small" id="sv-close">Done (Esc)</button></div>
    <div class="cu-cmp" style="--cols:${cols}">${ids.map((id) => { const p = cuP(id), f = flagOf(p), at = spot(p);
      return `<div class="cu-c${id === cu.cur ? " cur" : ""}${f ? " f-" + f : ""}" data-c="${id}">
        <div class="im">${zoomed ? `<img src="/img/cull/${cu.sel}/${id}/zoom.jpg?x=${at.x.toFixed(4)}&y=${at.y.toFixed(4)}&w=${side}&h=${side}" alt="" draggable="false">` : `<img src="/img/cull/${cu.sel}/${id}/view.jpg" alt="" draggable="false">`}
          <button class="sv-drop" data-drop="${id}" title="Drop it from the survey (X)">${icon("x")}</button>
          ${f ? `<span class="sv-flag">${icon(f === "keep" ? "keep" : "reject")}</span>` : ""}</div>
        <div class="cap"><b>${esc(p.name)}</b><span>${p.score ?? "-"}${p.best ? " · best of its burst" : ""}</span>${p.issues.filter((i) => i !== "dupe").map((i) => `<i>${esc(CU_ISSUE[i][0])}</i>`).join("")}</div></div>`; }).join("")}</div>
    <div class="cu-cmp-tip">Click one to choose it · double-click a spot: every photo zooms there at 100% · <kbd>X</kbd> drop · <kbd>P</kbd> keep · <kbd>←</kbd><kbd>→</kbd> move</div>`;
  paintIcons(one);
  one.querySelectorAll("[data-c]").forEach((el) => {
    el.onclick = (e) => { if (e.target.closest("button")) return; cu.cur = +el.dataset.c; cuPaintCompare(); cuPaintInfo(); cuPaintTimeline(); };
    el.ondblclick = (e) => {
      const img = el.querySelector("img"), r = img.getBoundingClientRect();
      if (zoomed) { cu.zoom = null; sv.at = null; cuPaintCompare(); return; }
      sv.at = { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) };
      cu.zoom = sv.at; cuPaintCompare();
    };
  });
  one.querySelectorAll("[data-drop]").forEach((b) => b.onclick = (e) => { e.stopPropagation(); cuSurveyDrop(+b.dataset.drop); });
  $("#sv-back", one)?.addEventListener("click", () => { sv.dropped.clear(); cuPaintCompare(); });
  $("#sv-keep", one)?.addEventListener("click", cuSurveyKeep);
  $("#sv-win", one)?.addEventListener("click", cuSurveyKeep);
  $("#sv-zoom", one).onclick = () => { cu.zoom = zoomed ? null : { x: 0.5, y: 0.5 }; sv.at = null; cuPaintCompare(); };
  $("#sv-close", one).onclick = () => cuSetView("grid");
}
function cuSurveyDrop(id) {
  const sv = cu.survey; if (!sv) return;
  if (cuCompareIds().length <= 1) { toast("That's the last one", { small: "Keep it with P or Enter, or bring the others back with U" }); return; }
  const left = cuCompareIds(), i = left.indexOf(id);
  sv.dropped.add(id);
  if (cu.cur === id) cu.cur = cuCompareIds()[Math.min(i, cuCompareIds().length - 1)];
  cuPaintCompare(); cuPaintInfo();
}
function cuSurveyKeep() {
  const sv = cu.survey; if (!sv || !sv.dropped.size) return;
  const left = new Set(cuCompareIds());
  cuSet(sv.ids, (id) => ({ flag: left.has(id) ? "keep" : "reject" }), left.size === 1 ? "Keep the winner" : `Keep ${left.size}, reject ${sv.dropped.size}`);
  toast(left.size === 1 ? "Kept the winner" : `Kept ${plural(left.size, "photo")}`, { small: `${plural(sv.dropped.size, "dropped photo")} marked reject · ⌘Z undoes it` });
  sv.ids = [...left]; sv.dropped.clear();
  if (sv.ids.length < 2) cuSetView("one"); else cuPaintCompare();
}

// -- labels and the Spray Can: sort photos into categories in one pass -----------------------------
// (Aftershoot's Spray Can Tool, plus: named labels, drag across the gallery to paint (back over them
// to erase), 6-9 like Lightroom, a filter per label, and one folder per label when you copy them)
const LABEL_COLORS = ["#ff5d5d", "#f5c443", "#4cd18a", "#4f8bff", "#b38cff"];
const labelName = (n) => (cu.labels || [])[n - 1] || `Label ${n}`;
function cuLabelDot(n, big = false) { return n ? `<i class="lab-dot${big ? " big" : ""}" style="background:${LABEL_COLORS[n - 1]}"></i>` : ""; }
function cuSetLabel(ids, n) {
  // a label means you want it: an unmarked or rejected photo becomes a keeper too
  cuSet(ids, (id) => { const p = cuP(id); return n ? { label: n, ...(flagOf(p) !== "keep" ? { flag: "keep" } : {}) } : { label: null }; },
    n ? `Label: ${labelName(n)}` : "No label");
}
function cuSprayGrid() {
  const g = $("#cu-grid");
  g.addEventListener("pointerdown", (e) => {
    if (!cu.spray || e.button !== 0) return;
    const t = e.target.closest("[data-p]"); if (!t || e.target.closest("[data-burst]")) return;
    e.preventDefault(); e.stopPropagation();
    const first = cuP(+t.dataset.p), erase = first.label === cu.spray, done = new Set();
    const paint = (el) => {
      if (!el) return; const id = +el.dataset.p; if (done.has(id)) return; done.add(id);
      el.classList.add("sprayed"); el.style.setProperty("--spray", erase ? "transparent" : LABEL_COLORS[cu.spray - 1]);
    };
    paint(t);
    const move = (m) => paint(document.elementFromPoint(m.clientX, m.clientY)?.closest?.("#cu-grid [data-p]"));
    const up = () => {
      window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up);
      cuSetLabel([...done], erase ? 0 : cu.spray);
      toast(erase ? `Took the ${labelName(cu.spray)} label off ${plural(done.size, "photo")}` : `${plural(done.size, "photo")} labeled ${labelName(cu.spray)}`, { small: "⌘Z undoes it" });
    };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
  }, true);
  g.addEventListener("click", (e) => { if (cu.spray) { e.stopPropagation(); e.preventDefault(); } }, true);
}
function cuRenameLabels() {
  const m = modal(`<header><h2>Your labels</h2></header><div class="body">
      <p style="margin-top:0">Name the five colors for the categories you sort into (Instagram, Album, Team page…). When you copy your keepers, each label can get its own folder.</p>
      ${[1, 2, 3, 4, 5].map((n) => `<label class="cu-field cu-lname">${cuLabelDot(n, true)}<input data-ln="${n}" value="${esc(labelName(n))}" maxlength="30"></label>`).join("")}</div>
    <footer><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="ln-go">Save</button></footer>`);
  $("#ln-go", m).onclick = async () => {
    const names = $$("[data-ln]", m).map((x) => x.value.trim());
    const r = await api("/api/cull/labels", { names }, { method: "PUT" }); cu.labels = r.labels; closeModal(); cuPaintAll();
  };
}

// -- People: one player's photos (a click on them, or their number), best first, one per burst -------
const cuPerson = () => cu.people.find((x) => x.id === cu.person);
async function cuLoadPerson() {
  const sh = cuShoot(), who = cuPerson();
  clearTimeout(cu.personTimer);
  if (!sh || !who) { cu.personHits = null; return; }
  let r; try { r = await api(`/api/cull/shoots/${sh.id}/people/${who.id}/photos`); } catch { return; }
  if (cu.person !== who.id) return;
  cu.personHits = new Map(Object.entries(r.photos).map(([k, v]) => [+k, v]));
  cu.personJob = r.job;
  cuRefilter(); cuPaintPeopleBar();
  if (r.job && r.job.state === "now") cu.personTimer = setTimeout(cuLoadPerson, 2000);
}
function cuShowPerson(id) {
  cu.person = cu.person === id ? null : id;
  cu.personHits = null; cu.personJob = null;
  if (cu.person) { cu.sortWas = cu.sortWas ?? cu.sort; cuLoadPerson(); }
  cuRefilter(); cuPaintPeopleBar();
}
function cuPaintPeopleBar() {
  const el = $("#cu-pplf"); if (!el) return;
  const who = cuPerson(), sh = cuShoot();
  el.hidden = !who || !!cu.spray || !!cu.finish;
  if (el.hidden) { el.innerHTML = ""; return; }
  const hits = cu.personHits, job = cu.personJob;
  const n = hits ? [...hits.values()].filter((h) => h.status === "sure").length : 0, maybe = hits ? hits.size - n : 0;
  const favored = sh?.settings?.favor === who.id;
  el.innerHTML = `<span class="t">${icon("user")} <b>${esc(who.name)}</b>${who.number && !who.name.includes(who.number) ? ` <small>#${esc(who.number)}</small>` : ""}</span>
    <span class="n">${hits ? `${plural(n, "photo")}${maybe ? ` · ${maybe} to confirm` : ""}, best first` : `<span class="spin sm"></span> Finding them…`}
      ${job && job.state === "now" ? ` · looking at the event ${Math.round(job.done / Math.max(1, job.total) * 100)}%` : ""}</span>
    <label class="fav" title="Pass 1 gives photos with ${esc(who.name)} a lift, so more of them are kept (only in this event)"><input type="checkbox" id="pp-fav" ${favored ? "checked" : ""}> Favor in pass 1</label>
    <button class="btn small ghost" id="pp-forget" title="Forget this player">Forget</button>
    <button class="btn small" id="pp-close">Everyone (Esc)</button>`;
  paintIcons(el);
  $("#pp-close", el).onclick = () => cuShowPerson(cu.person);
  $("#pp-fav", el).onchange = async (e) => {
    const on = e.target.checked; e.target.blur();  // (so Esc and the other keys work right after)
    await api(`/api/cull/shoots/${sh.id}/pass1`, { favor: on ? who.id : "" });
    toast(on ? `Pass 1 now favors ${who.name}` : "Pass 1 treats everyone the same again",
      { small: on ? "Photos with them get a lift and say why. Your own marks never change" : "Your own marks never change" });
    await cuState(); cuPaintBar();
  };
  $("#pp-forget", el).onclick = async () => {
    if (!confirm(`Forget ${who.name}? Their photos and your marks stay; only the player is forgotten.`)) return;
    await api(`/api/cull/people/${who.id}`, null, { method: "DELETE" });
    cu.people = cu.people.filter((x) => x.id !== who.id); cuShowPerson(who.id); cuPaintSide();
  };
}
function cuAddPerson() {
  const m = modal(`<header><h2>Find a player</h2></header><div class="body">
      <p style="margin-top:0">Their photos in this event, best first, one per burst. Two ways:</p>
      <button class="btn primary big wide" id="ap-click">${icon("user")} Click them in a photo</button>
      <small class="faint">Best: it learns their face, kit and number. Works when you can see their face.</small>
      <div class="cu-or"><span>or</span></div>
      <div class="cu-num"><label class="cu-field"><span>Jersey number</span><input id="ap-num" inputmode="numeric" maxlength="3" placeholder="7"></label>
        <label class="cu-field grow"><span>Name (optional)</span><input id="ap-name" maxlength="40" placeholder="Aiden"></label>
        <button class="btn" id="ap-go">Find</button></div>
      <small class="faint">A number is found only where it can be read on the shirt.</small></div>
    <footer><button class="btn ghost" data-close>Cancel</button></footer>`);
  paintIcons(m);
  $("#ap-click", m).onclick = () => {
    closeModal();
    if (cu.view === "grid") cuSetView("one");
    cu.picking = true; cuPaintMain();
  };
  const go = async () => {
    const number = $("#ap-num", m).value.trim().replace(/^#/, ""), name = $("#ap-name", m).value.trim();
    if (!/^\d{1,3}$/.test(number)) { toast("Type their jersey number", { small: "Or click them in a photo" }); return; }
    const r = await api("/api/cull/people", { number, name });
    cu.people.push(r.person); closeModal(); cuPaintSide(); cuShowPerson(r.person.id);
  };
  $("#ap-go", m).onclick = go;
  $("#ap-num", m).onkeydown = (e) => { if (e.key === "Enter") go(); };
  $("#ap-name", m).onkeydown = (e) => { if (e.key === "Enter") go(); };
}
/* Click your player: everyone the app sees in the big photo, outlined. */
async function cuPickLayer() {
  const pic = $("#cu-pic"), img = $("#cu-img"), p = cuP(cu.cur), sh = cuShoot();
  if (!pic || !img || !p) return;
  const layer = document.createElement("div");
  layer.className = "cu-pick"; layer.innerHTML = `<span class="tag"><span class="spin sm"></span> Finding everyone…</span>`;
  pic.appendChild(layer);
  let r; try { r = await api(`/api/cull/shoots/${sh.id}/people/at/${p.id}`); } catch { layer.remove(); return; }
  if (!cu.picking || cuP(cu.cur) !== p) return;
  if (!r.people.length) { layer.innerHTML = `<span class="tag">No one found here: open another photo of them (← →)</span>`; return; }
  layer.innerHTML = r.people.map((q) => { const [x0, y0, x1, y1] = q.box;
    return `<button class="who" data-i="${q.i}" style="left:${x0 * 100}%;top:${y0 * 100}%;width:${(x1 - x0) * 100}%;height:${(y1 - y0) * 100}%"
      title="${q.face ? "This one" : "This one (face not clear here: a photo with their face works better)"}">${q.number ? `<i>#${esc(q.number)}</i>` : ""}</button>`; }).join("")
    + `<span class="tag">Click your player · Esc to stop</span>`;
  layer.querySelectorAll("[data-i]").forEach((b) => b.onclick = (e) => {
    e.stopPropagation();
    const q = r.people.find((x) => x.i === +b.dataset.i);
    const m = modal(`<header><h2>Who is this?</h2></header><div class="body">
        <div class="cu-num"><label class="cu-field grow"><span>Name</span><input id="wp-name" maxlength="40" placeholder="Aiden"></label>
          <label class="cu-field"><span>Number</span><input id="wp-num" maxlength="3" inputmode="numeric" value="${esc(q.number || "")}" placeholder="7"></label></div>
        <small class="faint">The number helps where their face isn't seen. Saved for your next events too.</small></div>
      <footer><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="wp-go">Find their photos</button></footer>`);
    const save = async () => {
      const res = await api("/api/cull/people", { sid: sh.id, pid: p.id, i: q.i, name: $("#wp-name", m).value.trim(), number: $("#wp-num", m).value.trim() });
      cu.picking = false; closeModal(); cu.people.push(res.person); cuPaintSide(); cuPaintMain(); cuShowPerson(res.person.id);
      toast(`Finding ${res.person.name} in every photo`, { small: "Best first, one per burst. Close calls ask you" });
    };
    $("#wp-go", m).onclick = save;
    $("#wp-name", m).onkeydown = (e) => { if (e.key === "Enter") save(); };
    setTimeout(() => $("#wp-name", m)?.focus(), 30);
  });
}
async function cuAnswer(yes) {
  const who = cuPerson(), sh = cuShoot(), p = cuP(cu.cur); if (!who || !p) return;
  await api(`/api/cull/people/${who.id}/answer`, { sid: sh.id, photo: p.id, yes });
  toast(yes ? `Yes, ${who.name}` : `Not ${who.name}`, { small: "Thanks: the finder learns from it" });
  await cuLoadPerson(); cuPaintInfo();
}

function cuToggleSpray() {
  cu.spray = cu.spray ? null : (cu.lastSpray || 1);
  if (cu.spray) { cu.lastSpray = cu.spray; if (cu.view !== "grid") cuSetView("grid"); }
  $("#cu-grid").classList.toggle("spraying", !!cu.spray); cuPaintBar();
}

// -- the panel on the right: why, and the details --------------------------------------------------
function cuPaintInfo() {
  const box = $("#cu-info"); if (!box) return;
  const p = cuP(cu.cur), sh = cuShoot();
  if (!p || !sh || cu.guide) { box.innerHTML = ""; return; }
  const f = flagOf(p), c = p.cam || {};
  const frames = p.bsize > 1 ? [...cu.photos.values()].filter((q) => alive(q) && q.burst === p.burst) : [];
  const shutter = c.shutter ? (c.shutter >= 1 ? `${c.shutter} s` : `1/${Math.round(1 / c.shutter)}`) : null;
  box.innerHTML = `<h3 class="cu-name" title="${esc(p.name)}">${esc(p.name)}${p.raw ? ` <small class="faint">+ RAW</small>` : ""}</h3>
    ${p.state === "failed" ? `<p class="bad-t">Couldn't read this photo: ${esc(p.err || "")}</p>` : ""}
    <div class="cu-mark">
      <button class="cu-mk${f === "keep" ? " on k" : ""}" data-mk="keep" title="Keep (P)">${icon("keep")} Keep</button>
      <button class="cu-mk${f === "reject" ? " on r" : ""}" data-mk="reject" title="Reject (X)">${icon("reject")} Reject</button></div>
    <p class="cu-who">${yours(p) ? `Your mark${p.auto ? ` · pass 1 said ${p.auto[0]}` : ""} <a href="#" id="cu-undo1">back to pass 1's (U)</a>` : p.auto ? `Pass 1 · ${Math.round(p.auto[1] * 100)}% sure${p.auto[1] < UNSURE ? " · <b>worth a look</b>" : ""}` : p.state === "done" ? "Pass 1 hasn't run yet" : `<span class="spin sm"></span> Pass 1 is looking at it`}</p>
    ${p.auto ? `<p class="cu-why">${esc(p.auto[2])}</p>` : ""}
    ${(() => { const h = cu.personHits?.get(p.id), who = cuPerson(); if (!h || !who) return "";
      return h.status === "sure" ? `<p class="cu-pp">${icon("user")} ${esc(who.name)} is in it${h.best ? " · <b>their best of this moment</b>" : ""} <small class="faint">(${esc(h.why)})</small></p>`
        : `<div class="cu-pp ask">${icon("user")} Is this ${esc(who.name)}? <button class="btn small" id="pp-yes">Yes</button><button class="btn small ghost" id="pp-no">No</button></div>`; })()}
    <div class="cu-labrow">${[1, 2, 3, 4, 5].map((n) => `<button class="${p.label === n ? "on" : ""}" data-lab="${n}" title="${esc(labelName(n))}${n <= 4 ? ` (${n + 5})` : ""}">${cuLabelDot(n, true)}</button>`).join("")}${p.label ? `<span>${esc(labelName(p.label))}</span>` : `<span class="faint">No label</span>`}</div>
    <div class="cu-starrow">${[1, 2, 3, 4, 5].map((n) => `<button data-star="${n}" class="${(p.stars || 0) >= n ? "on" : ""}" title="${n} star${n > 1 ? "s" : ""} (${n})">★</button>`).join("")}</div>
    ${p.score != null ? `<div class="cu-score"><span>Score</span><i style="--s:${p.score / 100}"></i><b>${p.score}</b></div>` : ""}
    ${p.good.length ? `<ul class="cu-list good">${p.good.map((g) => `<li>${esc(g[0].toUpperCase() + g.slice(1))}</li>`).join("")}</ul>` : ""}
    ${p.issues.length ? `<ul class="cu-list bad">${p.issues.map((i) => `<li>${esc(CU_ISSUE[i][1])}</li>`).join("")}</ul>` : ""}
    ${frames.length ? `<p class="cu-burst">${icon("stack")} Burst of ${frames.length} frames${p.best ? " · <b>this is the best</b>" : ""} <a href="#" id="cu-cmp-burst">compare them (C)</a></p>` : ""}
    ${p.ai ? `<div class="cu-ai">${p.ai.error ? `<small class="bad-t">AI: ${esc(p.ai.error)}</small>` : `<b>AI ${p.ai.score}/10</b> ${esc(p.ai.reason)}`}</div>` : ""}
    <h4 class="sub">Crop on the action</h4>
    <p class="cu-for">For <b>${esc((CU_WHERE.concat(CU_WHERE_MORE).find(([k]) => k === cuSizeKey()) || [0, CU_SIZE_NAME[cuSizeKey()]])[1])}</b> · <a href="#" id="cu-for-change">change in Finish</a></p>
    ${(() => { const sk = cuSizeKey(), b = cuCropOf(p, sk), q = b && cuQual(p, sk, b); if (!q) return "";
      const soft = q.f > 1.01, wb = soft ? cuWidened(p, sk, b) : null, wq = wb && cuQual(p, sk, wb);
      return `<p class="cu-q ${soft ? "soft" : "ok"}">${icon(soft ? "info" : "check")}<span>${esc(cuQualText(q))}</span></p>
        ${soft ? `<button class="btn small" id="cu-widen" title="Grow the crop around the action until nothing is enlarged">Widen it to stay sharp${wq && wq.f > 1.01 ? ` (as far as the photo allows: ${wq.f.toFixed(1)}×)` : ""}</button>
          ${sk === "original" ? `<p class="faint cu-qnote">Original size always enlarges a crop. For full detail, choose Instagram or Story (made at their own size) or YouTube (saved at the crop's own size).</p>` : ""}` : ""}`; })()}
    <label class="check-row"><input type="checkbox" id="cu-cropshow" ${cu.cropShow ? "checked" : ""}><span>Show it on the big photo<small>Drag to move it, scroll to resize. Its pixels show on it, amber when it would be enlarged</small></span></label>
    ${p.crop && (Array.isArray(p.crop) || p.crop[cuSizeKey()]) ? `<button class="btn ghost small" id="cu-crop-reset">Back to the automatic crop</button>` : ""}
    <h4 class="sub">Camera</h4>
    <table class="ck-kv"><tbody>${[["Taken", p.t ? new Date(p.t * 1000).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit", second: "2-digit" }) : null],
      ["Shutter", shutter], ["Aperture", c.aperture ? `f/${+c.aperture.toFixed(1)}` : null], ["ISO", c.iso], ["Focal length", c.focal ? `${Math.round(c.focal)} mm` : null], ["Camera", c.camera]]
      .filter(([, v]) => v).map(([k, v]) => `<tr><th>${k}</th><td>${esc(v)}</td></tr>`).join("")}</tbody></table>
    <div class="cu-open"><button class="btn ghost small" id="cu-reveal">${icon("folder")} Show in Finder</button></div>`;
  paintIcons(box);
  box.querySelectorAll("[data-mk]").forEach((b) => b.onclick = () => cuMark(b.dataset.mk));
  $("#pp-yes", box)?.addEventListener("click", () => cuAnswer(true));
  $("#pp-no", box)?.addEventListener("click", () => cuAnswer(false));
  box.querySelectorAll("[data-lab]").forEach((b) => b.onclick = () => cuSetLabel(cuTargets(), p.label === +b.dataset.lab ? 0 : +b.dataset.lab));
  box.querySelectorAll("[data-star]").forEach((b) => b.onclick = () => cuStars(+b.dataset.star === p.stars ? 0 : +b.dataset.star));
  $("#cu-undo1")?.addEventListener("click", (e) => { e.preventDefault(); cuMark(null); });
  $("#cu-cmp-burst")?.addEventListener("click", (e) => { e.preventDefault(); cu.picked.clear(); cuSetView("compare"); });
  $("#cu-cropshow").onchange = (e) => { cu.cropShow = e.target.checked; store.set("cull.crop", cu.cropShow); if (cu.view !== "one") cuSetView("one"); else cuPaintMain(); };
  $("#cu-crop-reset")?.addEventListener("click", () => Array.isArray(p.crop) ? cuSet([p.id], { crop: null }, "Reset the crop") : cuSaveCrop(p, cuSizeKey(), null, "Reset the crop"));
  $("#cu-widen")?.addEventListener("click", () => { const sk = cuSizeKey(); cuSaveCrop(p, sk, cuWidened(p, sk, cuCropOf(p, sk)), "Widen the crop"); });
  $("#cu-for-change")?.addEventListener("click", (e) => { e.preventDefault(); cuFin().what = "crop"; cuOpenFinish(); });
  $("#cu-reveal").onclick = () => api("/api/reveal", { path: p.path || "" }).catch(() => {});
}

// -- marking, with undo ------------------------------------------------------------------------------
function cuTargets() { return cu.picked.size > 1 ? [...cu.picked] : cu.cur != null ? [cu.cur] : []; }
async function cuSet(ids, change, label, record = true) {
  const sh = cuShoot(); if (!sh || !ids.length) return;
  const items = ids.map((id) => { const p = cuP(id); const want = typeof change === "function" ? change(id) : change;
    return { id, before: { flag: p.flag ?? null, stars: p.stars || 0, crop: p.crop ?? null }, after: { flag: p.flag ?? null, stars: p.stars || 0, crop: p.crop ?? null, ...want } }; });
  items.forEach((it) => Object.assign(cuP(it.id), it.after));
  if (record) { cu.hist.push({ label, items }); cu.future = []; if (cu.hist.length > 300) cu.hist.shift(); }
  cuAfterMark();
  await api(`/api/cull/shoots/${sh.id}/mark`, { items: items.map((it) => ({ id: it.id, ...it.after })) }).catch(() => {});
}
function cuAfterMark() {
  cu.gridSig = ""; cuPaintGrid(); cuPaintTimeline(); cuPaintSide(); cuPaintBar(); if (cu.view !== "grid") cuPaintMain(); cuPaintInfo();
}
function cuMark(flag) {
  const ids = cuTargets(); if (!ids.length) return;
  const p = cuP(cu.cur);
  // pressing it again on your own mark takes it back (pass 1's mark shows again)
  const same = ids.length === 1 && flag && p.flag === flag;
  if (!same) cuPop(flag);
  cuSet(ids, { flag: same ? null : flag }, flag === "keep" ? "Keep" : flag === "reject" ? "Reject" : "Back to pass 1's");
  if (cu.advance && ids.length === 1 && flag && !same) cuStep(1);
}
function cuStars(n) { cuSet(cuTargets(), { stars: n }, n ? `${n} stars` : "No stars"); }
async function cuUndo(redo = false) {
  const from = redo ? cu.future : cu.hist, to = redo ? cu.hist : cu.future;
  const step = from.pop(); if (!step) { toast(redo ? "Nothing to redo" : "Nothing to undo"); return; }
  to.push(step);
  const sh = cuShoot();
  if (step.trash) {
    if (redo) { const r = await api(`/api/cull/shoots/${sh.id}/trash`, { ids: step.ids }); step.token = r.token; step.ids.forEach((id) => cuP(id) && (cuP(id).state = "gone")); }
    else { await api(`/api/cull/shoots/${sh.id}/untrash`, { token: step.token }); step.ids.forEach((id) => cuP(id) && (cuP(id).state = "done")); }
    cuSort(); cuAfterMark();
    toast(redo ? `Moved ${plural(step.ids.length, "photo")} to the Trash again` : `Put ${plural(step.ids.length, "photo")} back from the Trash`);
    return;
  }
  const key = redo ? "after" : "before";
  step.items.forEach((it) => Object.assign(cuP(it.id), it[key]));
  cuSort(); cuAfterMark();
  toast(`${redo ? "Redid" : "Undid"}: ${step.label}`, { small: plural(step.items.length, "photo") });
  await api(`/api/cull/shoots/${sh.id}/mark`, { items: step.items.map((it) => ({ id: it.id, ...it[key] })) }).catch(() => {});
}
function cuEndOfList() {
  const [c] = cuCounts();
  if (cu.show === "unsure" || cu.show === "todo") {
    const nextTodo = cu.show === "unsure" && c.todo > 0;
    toast(cu.show === "unsure" ? "That's every photo pass 1 was unsure about" : "You've checked them all", {
      small: nextTodo ? `${plural(c.todo, "photo")} still have only pass 1's mark. Or go to Finish` : "Next: Finish (delete the rejects, use the keepers)",
      action: nextTodo ? { label: "Check the rest", run: (ev) => { ev.target.closest(".toast")?.remove(); cu.show = "todo"; cuRefilter(); } }
        : { label: "Finish →", run: (ev) => { ev.target.closest(".toast")?.remove(); cuOpenFinish(); } } });
  } else toast("That's the last photo here", { small: c.keep ? "Next: Finish, at the top right" : "", action: c.keep ? { label: "Finish →", run: (ev) => { ev.target.closest(".toast")?.remove(); cuOpenFinish(); } } : null });
}
function cuStep(d, extend = false) {
  if (!cu.order.length) return;
  let i = cu.order.indexOf(cu.cur);
  if (d > 0 && i === cu.order.length - 1 && !extend) { cuEndOfList(); return; }
  i = Math.min(cu.order.length - 1, Math.max(0, (i < 0 ? 0 : i) + d));
  cu.cur = cu.order[i];
  if (extend) { cu.picked.add(cu.cur); } else if (!extend && cu.picked.size && cu.view === "grid") { /* keep a selection while moving with arrows only via shift */ cu.picked.clear(); }
  cu.zoom = cu.view === "one" && cu.zoom ? cu.zoom : null;
  if (cu.view === "grid") cuScrollTo(cu.cur); else cuPaintMain();
  cuPaintInfo(); cuPaintTimeline();
}

// -- pass 1 settings, deleting rejects, keepers -------------------------------------------------------
function cuPass1() {
  const sh = cuShoot(); if (!sh) return;
  const s = sh.settings;
  const m = modal(`<header><h2>Pass 1</h2></header><div class="body">
      <p class="muted" style="margin-top:0">The app's own first pass marks every photo keep or reject. Your own marks are never changed.</p>
      <label class="cu-field"><span>How many to keep</span><input id="p1-keep" value="${esc(s.keep || "")}" placeholder="The best ones (it decides)">
        <small>Leave empty for every good moment, or type a number (<b>150</b>) or a share (<b>10%</b>)</small></label>
      <label class="cu-field"><span>How picky about soft frames and closed eyes</span><input type="range" id="p1-strict" min="0" max="1" step="0.05" value="${s.strict}">
        <small class="row-between"><span>Relaxed</span><span>Strict</span></small></label>
      <label class="check-row"><input type="checkbox" id="p1-burst" ${s.per_burst ? "checked" : ""}><span>Only the best frame of each burst<small>The others in a burst are marked reject (near copies)</small></span></label>
    </div><footer><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="p1-go">Run pass 1</button></footer>`);
  $("#p1-go", m).onclick = async () => {
    const body = { keep: $("#p1-keep", m).value.trim(), strict: +$("#p1-strict", m).value, per_burst: $("#p1-burst", m).checked };
    closeModal();
    const r = await api(`/api/cull/shoots/${sh.id}/pass1`, body);
    if (r.waiting) toast("Pass 1 runs as soon as every photo has been looked at", { small: "Your settings are saved" });
    else { await cuPhotos(); cuSort(); cuPaintAll(); toast("Pass 1 is done", { small: "Your own marks are as they were" }); }
  };
}
function cuDeleteRejects() {
  const sh = cuShoot();
  const rej = [...cu.photos.values()].filter((p) => alive(p) && flagOf(p) === "reject");
  const filesN = rej.reduce((a, p) => a + (p.n || 1), 0);
  const notMine = rej.filter((p) => !yours(p)).length;
  const m = modal(`<header><h2>Delete ${plural(rej.length, "reject")}?</h2></header><div class="body">
      <p style="margin-top:0">${plural(rej.length, "photo")} (${plural(filesN, "file")}${filesN > rej.length ? ": JPEG and RAW" : ""}) move to the Trash. You can undo here (⌘Z), or put them back from the Trash.</p>
      ${notMine ? `<p class="warn-t">${plural(notMine, "of them was", "of them were")} rejected by pass 1 and not checked by you.</p>` : ""}
    </div><footer><button class="btn ghost" data-close>Cancel</button>${notMine ? `<button class="btn" id="dr-look">Take a second look first</button>` : ""}<button class="btn danger" id="dr-go">${icon("trash")} Move to Trash</button></footer>`);
  paintIcons(m);
  $("#dr-look", m)?.addEventListener("click", () => {
    closeModal(); cu.show = "reject"; cu.sort = "score"; cu.issues.clear(); cuRefilter();
    toast("Second look: the rejects pass 1 liked best come first", { small: "P keeps one. When you're happy, press Delete rejects again" });
  });
  $("#dr-go", m).onclick = async () => {
    closeModal();
    const ids = rej.map((p) => p.id);
    const r = await api(`/api/cull/shoots/${sh.id}/trash`, { ids });
    ids.forEach((id) => cuP(id).state = "gone");
    cu.hist.push({ label: "Delete rejects", trash: true, token: r.token, ids }); cu.future = [];
    cuSort(); cuAfterMark(); if (cu.finish) cuPaintFinish($("#cu-one"));
    toast(`Moved ${plural(r.moved, "photo")} to the Trash`, { small: `${plural(r.files, "file")}`, action: { label: "Undo", run: (ev) => { ev.target.closest(".toast")?.remove(); cuUndo(); } } });
  };
}
function cuKeepers() {
  const ids = cu.picked.size > 1 ? [...cu.picked].filter((id) => flagOf(cuP(id)) === "keep") : [];
  return ids.length ? ids : [...cu.photos.values()].filter((p) => alive(p) && flagOf(p) === "keep").map((p) => p.id);
}
async function cuOut(what, given) {
  const sh = cuShoot(); const ids = given || cuKeepers();
  if (!ids.length) { toast("No keepers yet"); return; }
  if (what === "looks" || what === "reel") {
    const r = await api(`/api/cull/shoots/${sh.id}/send`, { ids });
    st.mode = what === "reel" ? "reel" : "edit"; await refresh?.(); render();
    toast(`${plural(r.added, "keeper")} added to Looks${r.added < r.asked ? ` (${r.asked - r.added} were there already)` : ""}`,
      { small: what === "reel" ? "Make a look of each (or pick looks), then build the reel" : "Pick looks to make on them" });
    return;
  }
  if (what === "ai") {
    const est = await api(`/api/cull/shoots/${sh.id}/ai`, { ids, estimate: true });
    const m = modal(`<header><h2>Ask AI to rate ${plural(ids.length, "keeper")}?</h2></header><div class="body">
        <p style="margin-top:0">Gemini looks at each one and gives a score out of 10, a reason, and its own best crop (used by <b>Best crop</b> when you crop and edit).</p>
        <p>${est.calls ? `${plural(est.calls, "photo")} to rate: <b>${est.cost}</b> on your Gemini key.` : "All of them are rated already: nothing to pay."}${est.rated ? ` ${est.rated} rated before.` : ""}</p>
        ${est.key ? "" : `<p class="bad-t">No Gemini key found: add <code>export GEMINI_API_KEY=…</code> to ~/.zshrc.</p>`}</div>
      <footer><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="ai-go" ${off(!est.calls || !est.key, "Nothing to rate")}>Rate them</button></footer>`);
    $("#ai-go", m).onclick = async () => { if (!est.calls || !est.key) return; closeModal(); await api(`/api/cull/shoots/${sh.id}/ai`, { ids }); cuJobStart("Rating with AI"); };
    return;
  }
  if (what === "copy" || what === "edit") { cuFin().what = what === "copy" ? "copy" : "crop"; cuOpenFinish(); return; }
}
let cuJobToast = null, cuJobLabel = "";
function cuJobStart(label) { cuJobLabel = label; cuJobToast?.close(); cuJobToast = toast(`${label}…`, { sticky: true, spin: true }); cuState().then(() => { cuPoll(); }); }
function cuJobWatch() {
  const sh = cuShoot(), j = sh?.job;
  if (cu.finish && j && (j.what === "edit" || j.what === "copy")) {
    const sig = `${j.what}|${j.started}|${j.state}|${j.done}`;
    if (sig !== cu.finSig) { cu.finSig = sig; if (j.state !== "now") cu.finScrollTo = ".cu-done"; cuPaintFinish($("#cu-one")); if (j.state !== "now") cuState().then(cuPaintSide); }
    return;
  }
  if (!j || !cuJobToast) return;
  if (j.state === "now") cuJobToast.update(`${cuJobLabel}… ${j.done} of ${j.total}`, j.what === "import" ? "Pass 1 starts on each photo as it arrives" : "", j.total ? j.done / j.total : 0);
  else {
    const t = cuJobToast; cuJobToast = null;
    if (j.state === "failed") t.fail(`${cuJobLabel} stopped: ${j.error || ""}`);
    else if (j.what === "ai") { t.done(`Rated ${plural(j.total, "photo")} with AI`, `${(j.tokens || 0).toLocaleString()} tokens`); cuPhotos().then(() => cuPaintInfo()); }
    else if (j.what === "import") t.done(`Imported ${plural(j.copied || 0, "file")}${j.skipped ? ` (${j.skipped} were already copied)` : ""}`, j.folder?.replace(/^\/Users\/[^/]+/, "~"), { label: "Show in Finder", run: () => api("/api/reveal", { path: j.folder }) });
    else t.done(`${j.what === "copy" ? "Copied" : "Made"} ${plural(j.done, "keeper")}`, j.folder?.replace(/^\/Users\/[^/]+/, "~"), { label: "Show in Finder", run: () => api("/api/reveal", { path: j.folder }) });
    if (j.state === "done" && (j.what === "copy" || j.what === "edit")) cuState().then(cuPaintSide);  // (the folder stays listed on the left)
  }
}

// -- adding shoots -----------------------------------------------------------------------------------
async function cuAddFolder() {
  const r = await api("/api/cull/shoots", {});
  if (!r.id) return;
  cu.guide = false;
  cu.sel = r.id; store.set("cull.sel", r.id); cu.shootSig = ""; cu.hist = []; cu.future = [];
  renderCull();
  toast(`Pass 1 is looking at ${plural(r.total, "photo")}`, { small: `${say(r.total * 0.45)}. The gallery is ready in moments: start looking while it works` });
}
async function cuImport() {
  const { cards } = await api("/api/cull/cards");
  if (!cards.length) { toast("No camera card found", { small: "Plug in the card (or its reader); it shows up here by itself" }); return; }
  const card = cards[0];
  const m = modal(`<header><h2>Import from ${esc(card.name)}</h2></header><div class="body">
      <p style="margin-top:0">${card.photos.toLocaleString()} photos (JPEG and RAW; videos are left on the card). Photos already copied before are skipped. Pass 1 starts on each one as it arrives.</p>
      <label class="cu-field"><span>New folder's name</span><input id="im-name" placeholder="The day's date + Import"></label>
      <label class="check-row"><input type="checkbox" id="im-choose"><span>Choose where it goes<small>Otherwise: Pictures › AllProPhoto Imports</small></span></label>
    </div><footer><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="im-go">${icon("card")} Import and cull</button></footer>`);
  paintIcons(m);
  $("#im-go", m).onclick = async () => {
    const body = { volume: card.path, name: $("#im-name", m).value.trim() || undefined, choose: $("#im-choose", m).checked };
    closeModal();
    const r = await api("/api/cull/import", body);
    if (!r.id) return;
    cu.guide = false;
    cu.sel = r.id; store.set("cull.sel", r.id); cu.shootSig = ""; renderCull(); cuJobStart("Importing from the card");
  };
}
function cuHelp() {
  modal(`<header><h2>How culling works</h2></header><div class="body cu-helpbody">
    <ol class="ck-steps">
      <li><span class="n">1</span><div><b>Pass 1: the app</b><p>Add an event's folder (or import the camera card). The app looks at every photo on your Mac, free: is the main player sharp, are the eyes open, did the camera focus on the players, is the ball in the play, the light, and which frames are one burst. It marks each one <b>keep</b> or <b>reject</b> with the reason, and how sure it is.</p></div></li>
      <li><span class="n">2</span><div><b>Your pass</b><p>Press <b>Your pass</b>: the photos pass 1 was least sure about come first. <kbd>P</kbd> keep, <kbd>X</kbd> reject, <kbd>→</kbd> next, <kbd>Space</kbd> big, <kbd>Z</kbd> 100%, <kbd>C</kbd> compare a burst. Your mark always wins, and teaches pass 1 your taste for the next event.</p></div></li>
      <li><span class="n">3</span><div><b>Finish</b><p><b>Delete rejects</b> moves them to the Trash (undo with ⌘Z, or from the Trash). <b>Keepers</b>: copy them, crop and edit them for Instagram / Story / YouTube, or send them to Looks and Reel.</p></div></li></ol>
    <p class="faint">Bursts show as one stack (the best frame on top): open one with its ×N badge. The timeline at the top is the whole event: tall bars are the big moments. Gemini is only used when you ask (Ask AI to rate, the D edit), and shows the cost first.</p>
    </div><footer><button class="btn primary" data-close>Got it</button></footer>`);
}

// -- keys --------------------------------------------------------------------------------------------
function cullKey(e) {
  if (st.mode !== "cull" || modalOpen()) return false;
  if (e.target.closest?.("input, textarea, select")) return false;
  const k = e.key.toLowerCase(), meta = e.metaKey || e.ctrlKey;
  if (meta && k === "z") { e.preventDefault(); cuUndo(e.shiftKey).then(() => cu.finish && cuPaintFinish($("#cu-one"))); return true; }
  if (cu.finish) { if (k === "escape") { cuCloseFinish(); return true; } return false; }
  if (k === "escape" && cu.fromFinish && !cu.zoom) { cuOpenFinish(); return true; }
  if (meta && k === "a") { e.preventDefault(); cu.order.forEach((id) => cu.picked.add(id)); cu.gridSig = ""; cuPaintGrid(); cuPaintBar(); return true; }
  if (meta || e.altKey) return false;
  if (cu.view === "compare" && cu.survey) {
    const left = cuCompareIds(), i = left.indexOf(cu.cur);
    if (k === "arrowright" || k === "arrowleft") { e.preventDefault(); cu.cur = left[(i + (k === "arrowright" ? 1 : left.length - 1)) % left.length]; cuPaintCompare(); cuPaintInfo(); return true; }
    if (k === "x" || k === "delete" || k === "backspace") { e.preventDefault(); cuSurveyDrop(cu.cur); return true; }
    if (k === "enter") { e.preventDefault(); cuSurveyKeep(); return true; }
    if (k === "u") { cu.survey.dropped.clear(); cuPaintCompare(); return true; }
    if (k === "z") { cu.zoom = cu.zoom ? null : { x: 0.5, y: 0.5 }; cu.survey.at = null; cuPaintCompare(); return true; }
  }
  const cols = cu.view === "grid" ? cuGeom().cols : 1;
  if (k === "arrowright") { e.preventDefault(); cuStep(1, e.shiftKey); }
  else if (k === "arrowleft") { e.preventDefault(); cuStep(-1, e.shiftKey); }
  else if (k === "arrowdown") { e.preventDefault(); cuStep(cols, e.shiftKey); }
  else if (k === "arrowup") { e.preventDefault(); cuStep(-cols, e.shiftKey); }
  else if (k === "home") { e.preventDefault(); cu.cur = cu.order[0]; cuStep(0); }
  else if (k === "end") { e.preventDefault(); cu.cur = cu.order[cu.order.length - 1]; cuStep(0); }
  else if (k === "p" || k === "k") cuMark("keep");
  else if (k === "x" || k === "delete" || k === "backspace") { e.preventDefault(); cuMark("reject"); }
  else if (k === "u") cuMark(null);
  else if (/^[0-5]$/.test(k)) cuStars(+k);
  else if (/^[6-9]$/.test(k)) { const n = +k - 5, p = cuP(cu.cur); cuSetLabel(cuTargets(), p && p.label === n && cuTargets().length === 1 ? 0 : n); }
  else if (k === "l") cuToggleSpray();
  else if (k === " " || k === "enter") { e.preventDefault(); cuSetView(cu.view === "grid" ? "one" : "grid"); }
  else if (k === "escape" && cu.spray) { cuToggleSpray(); }
  else if (k === "escape" && cu.picking) { cu.picking = false; cuPaintMain(); }
  else if (k === "escape" && cu.person && cu.view === "grid") { cuShowPerson(cu.person); }
  else if (k === "escape") { if (cu.zoom) { cu.zoom = null; cuPaintMain(); } else if (cu.view !== "grid") cuSetView("grid"); else if (cu.picked.size) { cu.picked.clear(); cu.gridSig = ""; cuPaintGrid(); cuPaintBar(); } }
  else if (k === "z") { if (cu.view === "grid") cuSetView("one");
    const p = cuP(cu.cur), fc = p?.faces?.find((x) => x.main) || p?.faces?.[0];
    cu.zoom = cu.zoom ? null : fc ? { x: (fc.box[0] + fc.box[2]) / 2, y: (fc.box[1] + fc.box[3]) / 2 } : p?.subject ? { x: (p.subject[0] + p.subject[2]) / 2, y: (p.subject[1] + p.subject[3]) / 2 } : { x: 0.5, y: 0.5 };
    cuPaintMain(); }
  else if (k === "c") cuSetView(cu.view === "compare" ? "one" : "compare");
  else if (k === "g") { if (e.shiftKey) { const p = cuP(cu.cur); if (p?.bsize > 1) { cu.open.has(p.burst) ? cu.open.delete(p.burst) : cu.open.add(p.burst); cuSort(); cu.gridSig = ""; cuPaintGrid(); } } else cuSetView(cu.view === "grid" ? "one" : "grid"); }
  else if (k === "b") { const p = cuP(cu.cur); if (p?.bsize > 1) { cu.open.has(p.burst) ? cu.open.delete(p.burst) : cu.open.add(p.burst); cuSort(); cu.gridSig = ""; cuPaintGrid(); } }
  else if (k === "r") { cu.cropShow = !cu.cropShow; store.set("cull.crop", cu.cropShow); if (cu.view === "grid") cuSetView("one"); else cuPaintMain(); cuPaintInfo(); }
  else if (k === "m") { cu.marks = !cu.marks; store.set("cull.marks", cu.marks); cu.gridSig = ""; cuPaintMain(); }
  else if (e.key === "?") cuHelp();
  else if (k === "escape" && cu.guide) { cu.guide = false; cuPaintAll(); }
  else return false;
  return true;
}
