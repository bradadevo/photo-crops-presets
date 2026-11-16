/* AllProPhoto Studio: editing a picture. The Edit tab (light, color, the look, parts, text),
   the tools used on the picture itself (crop and straighten, remove distractions, adjust a
   part, white balance, text), and undo / redo. Loaded after app.js, whose helpers it uses. */
"use strict";

// Undo and redo ------------------------------------------------------------------------------
const hist = { undo: [], redo: [] };
const clone = (o) => JSON.parse(JSON.stringify(o ?? {}));
const snapshot = (s) => ({ adjust: { ...s.adjust }, edits: clone(s.edits) });

function pushHist(entry) {
  hist.undo.push(entry);
  if (hist.undo.length > 100) hist.undo.shift();
  hist.redo = [];
  editSig = "";
  if (st.tab === "edit") renderTabs();
}

async function undo() { await travel(hist.undo, hist.redo, "before"); }
async function redo() { await travel(hist.redo, hist.undo, "after"); }
async function travel(from, to, side) {
  const e = from.pop();
  if (!e) return;
  to.push(e);
  if (e.type === "removal") {
    const t = toast(side === "before" ? "Putting it back…" : "Removing it again…", { sticky: true, spin: true });
    try { await api(`/api/photos/${e.pid}/removals`, { removals: e[side] }); t.close(); } catch { t.close(); }
    await refresh();
  } else {
    const s = await api(`/api/slots/${e.sid}/edit`, e[side]);
    updateSlot(s);
  }
  editSig = "";
  renderTabs();
}

/* A slot back from the server: shown everywhere, the big picture swapped in without a flash. */
function updateSlot(s, { keepPane = false } = {}) {
  const i = st.slots.findIndex((x) => x.id === s.id);
  if (i < 0) return;
  st.slots[i] = s;
  if (st.current === s.id) {
    const img = $("#frame img.after");
    const sameGeometry = img && img.dataset.base === `${s.width}x${s.height}` && !st.tool && !st.fixing;
    if (sameGeometry) {
      const pre = new Image();
      pre.onload = () => { if (img.isConnected) img.src = pre.src; };
      pre.src = slotImg(s);
      viewerSig = viewerSignature(s);
      paintTexts(s);
    } else { viewerSig = ""; renderViewer(); }
  }
  if (keepPane) editSig = paneSignature(s);
  renderStrip(); renderTop();
  if (!keepPane) renderTabs();
}

async function changeEdits(cur, mutate, opts) {
  const before = snapshot(cur);
  const e = clone(cur.edits);
  mutate(e);
  const s = await api(`/api/slots/${cur.id}/edit`, { edits: e });
  pushHist({ type: "slot", sid: cur.id, before, after: snapshot(s) });
  updateSlot(s, opts);
  return s;
}

// The Edit tab ---------------------------------------------------------------------------------
const SLIDERS = {
  light: [["exposure", "Exposure", -2, 2, 0.05, "ev"], ["contrast", "Contrast", -1, 1, 0.05], ["highlights", "Highlights", -1, 1, 0.05],
    ["shadows", "Shadows", -1, 1, 0.05]],
  color: [["warmth", "Warmth", -3, 3, 0.05, "", "warm"], ["tint", "Tint", -3, 3, 0.05, "", "tint"],
    ["saturation", "Saturation", -1, 1, 0.05]],
  look: [["strength", "Look strength", 0, 100, 5, "%"], ["subject", "Player brightness", -1, 1, 0.05, "ev"],
    ["background", "Background brightness", -2, 1, 0.05, "ev"]],
};
const TEXT_STYLES = [["clean", "Clean"], ["bold", "Bold"], ["spaced", "Spaced"], ["banner", "Banner"]];
const TEXT_COLORS = ["#ffffff", "#111111", "#f5c443", "#1f2a44", "#e63946", "#86d0d8"];
const fmtVal = (k, v, unit) => k === "strength" ? `${Math.round(v)}%` : `${v > 0 ? "+" : ""}${(+v).toFixed(2)}${unit ? " " + unit : ""}`;

let editSig = "";
const paneSignature = (cur) => `${cur.id}:${cur.ver}:${st.photos.length}:${st.areaSel}:${st.textSel}:${hist.undo.length}:${hist.redo.length}:${st.tool}`;

function renderEdit(cur) {
  const sig = paneSignature(cur);
  if (sig === editSig) return;
  editSig = sig;
  const a = cur.adjust, e = cur.edits || {};
  const same = doneSlots().filter((s) => s.look === cur.look).length;
  const photo = st.photos.find((p) => p.id === cur.photo);
  const anyMatched = doneSlots().some((s) => s.matched);
  const areas = e.areas || [], texts = e.texts || [];
  const pane = $("#pane-edit");
  const val = (k) => k === "strength" ? Math.round(a.strength * 100) : a[k];
  const sliderRow = ([k, label, min, max, stp, unit, cls]) => `<div class="slider"><label for="e-${k}" title="Double-click the slider to reset">${label}</label>
    <output for="e-${k}">${fmtVal(k, val(k), unit)}</output><input type="range" class="${cls || ""}" id="e-${k}" data-k="${k}" data-unit="${unit || ""}" min="${min}" max="${max}" step="${stp}" value="${val(k)}"></div>`;
  const tool = (id, ic, label, tip) => `<button class="tool${st.tool === id || (id === "cutout" && st.fixing) ? " on" : ""}" data-tool="${id}" title="${esc(tip)}">${icon(ic)}<span>${label}</span></button>`;
  pane.innerHTML = `
    <div class="edit-head"><div class="adj-title"><b>${esc(cur.look)}</b><span>${esc(photo?.name || "")}</span></div>
      <div class="undo-btns"><button class="icon-btn" id="e-undo" title="Undo (⌘Z)" ${hist.undo.length ? "" : "disabled"}>${icon("undo")}</button>
      <button class="icon-btn" id="e-redo" title="Redo (⇧⌘Z)" ${hist.redo.length ? "" : "disabled"}>${icon("redo")}</button></div></div>
    <div class="tools">
      ${tool("crop", "crop", "Crop", "Crop and straighten (R)")}
      ${tool("remove", "eraser", "Remove", "Brush over a distraction to remove it")}
      ${tool("area", "target", "Adjust a part", "Click a face, the player or the sky to adjust just that")}
      ${tool("wb", "pipette", "White balance", "Click something white or gray")}
      ${tool("text", "type", "Text", "Add a name, a score or a date (T)")}
      ${tool("cutout", "wand", "Cut-out", "Fix what counts as the player")}
    </div>
    <div class="section"><h3>Light</h3>${SLIDERS.light.map(sliderRow).join("")}</div>
    <div class="section"><h3>Color</h3>${SLIDERS.color.map(sliderRow).join("")}</div>
    <div class="section"><h3>The look</h3>${SLIDERS.look.map(sliderRow).join("")}
      <label class="toggle"><input type="checkbox" id="e-fill" ${a.auto_fill ? "checked" : ""}><span><b>Auto fill light</b><small>Lifts a backlit or shaded player</small></span></label></div>
    ${areas.length ? `<div class="section"><h3>Parts adjusted</h3>${areas.map((ar, i) => `<div class="item${st.areaSel === i ? " on" : ""}" data-area="${i}">
      <div class="item-head"><button class="item-name" data-pick-area="${i}">${icon("target")} Part ${i + 1}</button><button class="icon-btn" data-del-area="${i}" title="Remove this adjustment">${icon("trash")}</button></div>
      ${st.areaSel === i ? [["exposure", "Brightness", -2, 2, 0.05, "ev"], ["warmth", "Warmth", -1.5, 1.5, 0.05, "", "warm"], ["saturation", "Saturation", -1, 1, 0.05]].map(([k, label, min, max, stp, unit, cls]) =>
        `<div class="slider"><label>${label}</label><output>${fmtVal(k, ar[k] || 0, unit)}</output><input type="range" class="${cls || ""}" data-area-k="${k}" data-i="${i}" data-unit="${unit || ""}" min="${min}" max="${max}" step="${stp}" value="${ar[k] || 0}"></div>`).join("") : ""}
      </div>`).join("")}</div>` : ""}
    ${texts.length ? `<div class="section"><h3>Text</h3>${texts.map((t, i) => `<div class="item${st.textSel === i ? " on" : ""}" data-text="${i}">
      <div class="item-head"><textarea class="field text-in" rows="1" data-ti="${i}" placeholder="Type here">${esc(t.text)}</textarea><button class="icon-btn" data-del-text="${i}" title="Remove this text">${icon("trash")}</button></div>
      ${st.textSel === i ? `<div class="seg full small" data-style-of="${i}">${TEXT_STYLES.map(([v, l]) => `<button data-v="${v}" class="${t.style === v ? "on" : ""}">${l}</button>`).join("")}</div>
      <div class="slider"><label>Size</label><output>${Math.round(t.size * 100)}</output><input type="range" data-size-of="${i}" min="0.02" max="0.2" step="0.005" value="${t.size}"></div>
      <div class="swatches" data-color-of="${i}">${TEXT_COLORS.map((c) => `<button data-v="${c}" class="${t.color === c ? "on" : ""}" style="background:${c}" aria-label="${c}"></button>`).join("")}</div>` : ""}
      </div>`).join("")}</div>` : ""}
    <div class="inline"><button class="btn" id="e-reset" title="Back to the look as it was made">Reset all</button>
      ${same > 1 ? `<button class="btn" id="e-all" style="flex:1" title="These light, color and look settings on every picture in this look">${icon("copy")} Use on all ${same}</button>` : ""}</div>
    <div class="section"><h3>This photo</h3><div class="actions">
      ${cur.removed ? `<p class="notes">${plural(cur.removed, "distraction")} removed from this photo · ⌘Z puts the last one back</p>` : ""}
      ${st.photos.length > 1 ? `<button class="btn" id="e-useall">${icon("layers")} Use this look on all ${st.photos.length} photos</button>
      <button class="btn" id="e-match">${icon("sun")} Match every photo's light to this one</button>` : ""}
      ${anyMatched ? `<button class="btn ghost" id="e-unmatch">${icon("undo")} Undo matching</button>` : ""}
    </div></div>
    <div class="section"><h3>Save as a preset</h3><div class="inline"><input class="field" id="e-name" placeholder="Preset name">
      <button class="btn" id="e-save">${icon("save")} Save</button></div></div>
    ${cur.notes?.length ? `<p class="notes">${esc(cur.notes.join("; "))}</p>` : ""}`;
  paintIcons(pane);
  bindEditPane(cur, pane);
}

function bindEditPane(cur, pane) {
  const vals = { ...cur.adjust };
  let dragSnap = null;
  $("#e-undo", pane).onclick = undo;
  $("#e-redo", pane).onclick = redo;
  pane.querySelectorAll("[data-tool]").forEach((b) => b.onclick = () => setTool(b.dataset.tool));
  pane.querySelectorAll("input[data-k]").forEach((r) => {
    const out = pane.querySelector(`output[for=${r.id}]`);
    r.oninput = () => {
      if (!dragSnap) dragSnap = snapshot(slotById(cur.id));
      out.textContent = fmtVal(r.dataset.k, r.value, r.dataset.unit);
      vals[r.dataset.k] = r.dataset.k === "strength" ? r.value / 100 : +r.value;
      sendAdjust(cur.id, vals);
    };
    r.onchange = () => commitDrag();
    r.ondblclick = () => { r.value = r.dataset.k === "strength" ? 100 : 0; r.oninput(); commitDrag(); };
  });
  const commitDrag = () => {
    if (!dragSnap) return;
    const before = dragSnap;
    dragSnap = null;
    afterSend(() => { const s = slotById(cur.id); pushHist({ type: "slot", sid: cur.id, before, after: snapshot(s) }); });
  };
  $("#e-fill", pane).onchange = (ev) => { const before = snapshot(slotById(cur.id)); vals.auto_fill = ev.target.checked; sendAdjust(cur.id, vals);
    afterSend(() => pushHist({ type: "slot", sid: cur.id, before, after: snapshot(slotById(cur.id)) })); };
  $("#e-reset", pane).onclick = async () => {
    const before = snapshot(cur);
    const s = await api(`/api/slots/${cur.id}/edit`, { adjust: {}, edits: {} });
    pushHist({ type: "slot", sid: cur.id, before, after: snapshot(s) });
    st.areaSel = null; st.textSel = null; updateSlot(s);
  };
  $("#e-all", pane)?.addEventListener("click", async () => {
    const r = await api(`/api/slots/${cur.id}/adjust_look`, vals);
    toast(`Used on all ${r.count} “${cur.look}” pictures`); refresh();
  });
  $("#e-useall", pane)?.addEventListener("click", async () => {
    const r = await api(`/api/slots/${cur.id}/use_on_all`, {});
    toast(`Making “${cur.look}” on ${plural(r.slots.length, "more photo")}`); refresh();
  });
  $("#e-match", pane)?.addEventListener("click", async () => {
    const t = toast("Matching every photo's light to this one…", { sticky: true, spin: true });
    try { const r = await api(`/api/slots/${cur.id}/match`, {}); t.done(`Matched ${plural(r.changed, "photo")} to this one`); } catch { t.close(); }
    editSig = ""; refresh();
  });
  $("#e-unmatch", pane)?.addEventListener("click", async () => { await api("/api/match/clear", {}); toast("Matching undone"); editSig = ""; refresh(); });
  $("#e-save", pane).onclick = async () => {
    const name = $("#e-name", pane).value.trim();
    if (!name) { $("#e-name", pane).focus(); return; }
    await api(`/api/slots/${cur.id}/save_preset`, { name });
    toast(`Saved “${name}” under Mine`); loadLooks();
  };
  // parts
  pane.querySelectorAll("[data-pick-area]").forEach((b) => b.onclick = () => {
    const i = +b.dataset.pickArea; st.areaSel = st.areaSel === i ? null : i; editSig = ""; renderTabs();
    if (st.tool === "area") { viewerSig = ""; renderViewer(); }
  });
  pane.querySelectorAll("[data-del-area]").forEach((b) => b.onclick = () => {
    const i = +b.dataset.delArea; st.areaSel = null;
    changeEdits(slotById(cur.id), (e) => { e.areas.splice(i, 1); });
  });
  let areaTimer = null, areaSnap = null;
  pane.querySelectorAll("input[data-area-k]").forEach((r) => {
    r.oninput = () => {
      const s = slotById(cur.id);
      if (!areaSnap) areaSnap = snapshot(s);
      r.previousElementSibling.textContent = fmtVal(r.dataset.areaK, r.value, r.dataset.unit);
      const e = clone(s.edits);
      e.areas[+r.dataset.i][r.dataset.areaK] = +r.value;
      clearTimeout(areaTimer);
      areaTimer = setTimeout(async () => { updateSlot(await api(`/api/slots/${cur.id}/edit`, { edits: e }), { keepPane: true }); }, 120);
    };
    r.onchange = () => setTimeout(() => {
      if (!areaSnap) return;
      const before = areaSnap; areaSnap = null;
      pushHist({ type: "slot", sid: cur.id, before, after: snapshot(slotById(cur.id)) });
    }, 400);
  });
  // text
  pane.querySelectorAll(".text-in").forEach((ta) => {
    const i = +ta.dataset.ti;
    let snap = null, timer = null;
    const grow = () => { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; };
    grow();
    ta.onfocus = () => { snap = snapshot(slotById(cur.id)); if (st.textSel !== i) { st.textSel = i; editSig = ""; renderTabs(); $(`.text-in[data-ti="${i}"]`)?.focus(); } };
    ta.oninput = () => {
      grow();
      const s = slotById(cur.id), e = clone(s.edits);
      e.texts[i].text = ta.value;
      s.edits = e; paintTexts(s);  // shown at once; saved a moment later
      clearTimeout(timer);
      timer = setTimeout(async () => { updateSlot(await api(`/api/slots/${cur.id}/edit`, { edits: e }), { keepPane: true }); }, 300);
    };
    ta.onblur = () => setTimeout(() => {
      if (snap && JSON.stringify(snap.edits) !== JSON.stringify(slotById(cur.id).edits)) pushHist({ type: "slot", sid: cur.id, before: snap, after: snapshot(slotById(cur.id)) });
      snap = null;
    }, 450);
  });
  pane.querySelectorAll("[data-del-text]").forEach((b) => b.onclick = () => {
    const i = +b.dataset.delText; st.textSel = null;
    changeEdits(slotById(cur.id), (e) => { e.texts.splice(i, 1); });
  });
  pane.querySelectorAll("[data-style-of] button").forEach((b) => b.onclick = () => {
    const i = +b.parentElement.dataset.styleOf;
    changeEdits(slotById(cur.id), (e) => { e.texts[i].style = b.dataset.v; });
  });
  pane.querySelectorAll("[data-color-of] button").forEach((b) => b.onclick = () => {
    const i = +b.parentElement.dataset.colorOf;
    changeEdits(slotById(cur.id), (e) => { e.texts[i].color = b.dataset.v; });
  });
  pane.querySelectorAll("[data-size-of]").forEach((r) => {
    let snap = null, timer = null;
    r.oninput = () => {
      const s = slotById(cur.id);
      if (!snap) snap = snapshot(s);
      r.previousElementSibling.textContent = Math.round(r.value * 100);
      const e = clone(s.edits);
      e.texts[+r.dataset.sizeOf].size = +r.value;
      s.edits = e; paintTexts(s);
      clearTimeout(timer);
      timer = setTimeout(async () => { updateSlot(await api(`/api/slots/${cur.id}/edit`, { edits: e }), { keepPane: true }); }, 200);
    };
    r.onchange = () => setTimeout(() => {
      if (snap) pushHist({ type: "slot", sid: cur.id, before: snap, after: snapshot(slotById(cur.id)) });
      snap = null;
    }, 400);
  });
}

/* The sliders: sent as you drag, only the latest waiting; afterSend runs once the last is back. */
let adjustBusy = false, adjustNext = null, afterQueue = [];
function afterSend(fn) { if (!adjustBusy && !adjustNext) fn(); else afterQueue.push(fn); }
async function sendAdjust(id, vals) {
  adjustNext = { id, vals: { ...vals } };
  if (adjustBusy) return;
  adjustBusy = true;
  while (adjustNext) {
    const job = adjustNext; adjustNext = null;
    try { updateSlot(await api(`/api/slots/${job.id}/edit`, { adjust: job.vals }), { keepPane: true }); } catch { break; }
  }
  adjustBusy = false;
  const q = afterQueue; afterQueue = [];
  q.forEach((fn) => fn());
}

// Tools on the picture --------------------------------------------------------------------------
function setTool(tool) {
  const cur = slotById(st.current);
  if (!cur || cur.state !== "done") return;
  if (tool === "cutout") { st.fixing = !st.fixing; st.tool = null; }
  else { st.tool = st.tool === tool ? null : tool; st.fixing = false; }
  st.compare = false; st.zoom.on = false; st.view = "single"; st.cropDraft = null; st.brush.strokes = [];
  if (tool === "text" && st.tool === "text" && !(cur.edits?.texts || []).length) { addText(cur); }
  if (st.tab !== "edit") st.tab = "edit";
  viewerSig = ""; editSig = ""; render();
}

async function addText(cur) {
  const n = (cur.edits?.texts || []).length;
  st.textSel = n;
  await changeEdits(cur, (e) => {
    (e.texts ||= []).push({ text: n ? "Your text" : "GAME DAY", x: 0.5, y: n ? 0.15 : 0.85, size: 0.07, style: n ? "clean" : "bold", color: "#ffffff" });
  });
  setTimeout(() => { const ta = $(`.text-in[data-ti="${n}"]`); ta?.focus(); ta?.select(); }, 60);
}

/* The tool's view: the picture to work on, and its bar of controls. */
function renderTool(v, cur) {
  const t = st.tool;
  if (t === "crop") return renderCrop(v, cur);
  if (t === "remove") return renderBrush(v, cur);
  const base = t === "area";
  const src = base ? slotImg(cur, st.areaSel != null && cur.edits?.areas?.[st.areaSel] ? `area-${st.areaSel}` : "base") : slotImg(cur);
  const bar = {
    area: `<span class="title"><b>Adjust a part</b><span>Click a face, the player, the sky or the grass</span></span><span class="sep"></span><button data-done>Done</button>`,
    wb: `<span class="title"><b>White balance</b><span>Click something that should be white or gray</span></span><span class="sep"></span><button data-done>Cancel</button>`,
    text: `<span class="title"><b>Text</b><span>Drag to place it · type in the panel</span></span><span class="sep"></span><button data-add-text>${icon("plus")} Add text</button><button data-done>Done</button>`,
  }[t];
  v.innerHTML = `<div class="frame tool-${t}" id="frame"><div class="layer"><img class="after" src="${src}" alt="" draggable="false" data-base="${base ? "" : `${cur.width}x${cur.height}`}"></div>
      ${t === "text" ? `<div class="texts" id="texts"></div>` : ""}</div>
    <div class="fixbar toolbar">${bar}</div>`;
  paintIcons(v);
  if (base) fitFrame(cur.base_width, cur.base_height); else fitFrame(cur.width, cur.height);
  if (t === "text") { paintTexts(cur); bindTexts(cur); }
  $("[data-done]", v).onclick = () => setTool(t);
  $("[data-add-text]", v)?.addEventListener("click", () => addText(slotById(cur.id)));
  const f = $("#frame");
  const at = (e) => { const r = f.getBoundingClientRect(); return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height }; };
  if (t === "area") f.onclick = async (e) => {
    const p = at(e), s = slotById(cur.id);
    st.areaSel = (s.edits?.areas || []).length;
    const tk = toast("Finding that part…", { sticky: true, spin: true });
    try { await changeEdits(s, (ed) => { (ed.areas ||= []).push({ x: p.x, y: p.y, exposure: 0.3, warmth: 0, saturation: 0 }); }); } finally { tk.close(); }
  };
  if (t === "wb") f.onclick = async (e) => {
    const p = at(e), s = slotById(cur.id), before = snapshot(s);
    const after = await api(`/api/slots/${cur.id}/whitebalance`, p);
    pushHist({ type: "slot", sid: cur.id, before, after: snapshot(after) });
    st.tool = null; updateSlot(after); viewerSig = ""; renderViewer();
    toast("White balance set", { small: "Warmth and Tint in the Edit tab fine-tune it" });
  };
}

// Text on the picture: drawn by the page while you work (the export draws the same) ---------
function paintTexts(cur) {
  const box = $("#texts");
  if (!box) return;
  const texts = cur.edits?.texts || [];
  box.innerHTML = texts.map((t, i) => `<div class="tx tx-${t.style}${st.tool === "text" && st.textSel === i ? " sel" : ""}" data-i="${i}"
    style="left:${t.x * 100}%;top:${t.y * 100}%;font-size:calc(var(--fw) * ${t.size});color:${esc(t.color)}">${esc(t.text)}</div>`).join("");
}
function bindTexts(cur) {
  const box = $("#texts"), f = $("#frame");
  if (!box) return;
  box.onpointerdown = (e) => {
    const el = e.target.closest(".tx");
    if (!el) return;
    e.preventDefault();
    const i = +el.dataset.i, r = f.getBoundingClientRect();
    if (st.textSel !== i) { st.textSel = i; editSig = ""; renderTabs(); box.querySelectorAll(".tx").forEach((x) => x.classList.toggle("sel", +x.dataset.i === i)); }
    const s0 = slotById(cur.id), t0 = s0.edits.texts[i];
    const start = { x: e.clientX, y: e.clientY, tx: t0.x, ty: t0.y };
    let moved = false, pos = { x: t0.x, y: t0.y };
    el.setPointerCapture(e.pointerId);
    el.onpointermove = (m) => {
      moved = true;
      pos = { x: Math.max(0, Math.min(1, start.tx + (m.clientX - start.x) / r.width)), y: Math.max(0, Math.min(1, start.ty + (m.clientY - start.y) / r.height)) };
      // snaps to the middle, as a guide
      if (Math.abs(pos.x - 0.5) < 0.012) pos.x = 0.5;
      el.style.left = pos.x * 100 + "%"; el.style.top = pos.y * 100 + "%";
      f.classList.toggle("snap-x", pos.x === 0.5);
    };
    el.onpointerup = () => {
      el.onpointermove = null; f.classList.remove("snap-x");
      if (moved) changeEdits(slotById(cur.id), (ed) => { ed.texts[i].x = pos.x; ed.texts[i].y = pos.y; }, { keepPane: true });
    };
  };
}

// Crop and straighten ---------------------------------------------------------------------------
const ASPECTS = [["free", "Free"], ["orig", "Original"], ["4:5", "4:5"], ["1:1", "1:1"], ["9:16", "9:16"], ["16:9", "16:9"]];
function coverScale(w, h, deg) {
  const t = Math.abs(deg) * Math.PI / 180, c = Math.cos(t), s = Math.sin(t);
  return Math.max((w * c + h * s) / w, (w * s + h * c) / h);
}
function renderCrop(v, cur) {
  const W = cur.base_width, H = cur.base_height;
  const d = st.cropDraft ||= { angle: cur.edits?.angle || 0, box: cur.edits?.crop ? [...cur.edits.crop] : [0, 0, 1, 1], aspect: "free" };
  v.innerHTML = `<div class="frame tool-crop" id="frame"><div class="layer"><img class="after" id="crop-img" src="${slotImg(cur, "base")}" alt="" draggable="false"></div>
      <div class="crop-box" id="crop-box"><i class="g1"></i><i class="g2"></i><i class="g3"></i><i class="g4"></i>
        ${["nw", "n", "ne", "e", "se", "s", "sw", "w"].map((h) => `<b class="h h-${h}" data-h="${h}"></b>`).join("")}</div></div>
    <div class="fixbar toolbar crop-bar">
      <div class="seg small" id="c-aspect">${ASPECTS.map(([k, l]) => `<button data-v="${k}" class="${d.aspect === k ? "on" : ""}">${l}</button>`).join("")}</div>
      <span class="sep"></span>
      <span class="angle">${icon("level")}<input type="range" id="c-angle" min="-20" max="20" step="0.1" value="${d.angle}"><output id="c-angle-v">${(+d.angle).toFixed(1)}°</output></span>
      <button id="c-auto" title="Level it from the field lines and posts">Auto</button>
      <span class="sep"></span>
      <button id="c-reset">Reset</button><button id="c-cancel">Cancel</button><button id="c-apply" class="on">Apply</button></div>`;
  paintIcons(v);
  fitFrame(W, H);
  const img = $("#crop-img"), box = $("#crop-box"), f = $("#frame");
  const paint = () => {
    img.style.transform = `rotate(${d.angle}deg) scale(${coverScale(W, H, d.angle)})`;
    const [x0, y0, x1, y1] = d.box;
    Object.assign(box.style, { left: x0 * 100 + "%", top: y0 * 100 + "%", width: (x1 - x0) * 100 + "%", height: (y1 - y0) * 100 + "%" });
    $("#c-angle-v").textContent = `${(+d.angle).toFixed(1)}°`;
    $("#c-angle").value = d.angle;
    $$("#c-aspect button").forEach((b) => b.classList.toggle("on", b.dataset.v === d.aspect));
  };
  const ratio = () => ({ free: null, orig: W / H, "4:5": 4 / 5, "1:1": 1, "9:16": 9 / 16, "16:9": 16 / 9 })[d.aspect];
  const fitAspect = () => {
    const r = ratio();
    if (!r) return;
    const rs = r * H / W;  // width share / height share
    let [x0, y0, x1, y1] = d.box;
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    let w = Math.min(1, x1 - x0), h = w / rs;
    if (h > (y1 - y0)) { h = y1 - y0; w = h * rs; }
    if (w > 1) { w = 1; h = w / rs; }
    if (h > 1) { h = 1; w = h * rs; }
    x0 = Math.min(Math.max(cx - w / 2, 0), 1 - w); y0 = Math.min(Math.max(cy - h / 2, 0), 1 - h);
    d.box = [x0, y0, x0 + w, y0 + h];
  };
  $$("#c-aspect button").forEach((b) => b.onclick = () => {
    d.aspect = b.dataset.v;
    if (ratio()) { d.box = [0, 0, 1, 1]; fitAspect(); }
    paint();
  });
  $("#c-angle").oninput = (e) => { d.angle = +e.target.value; paint(); };
  $("#c-angle").ondblclick = () => { d.angle = 0; paint(); };
  $("#c-auto").onclick = async () => { const r = await api(`/api/slots/${cur.id}/level`); d.angle = r.angle; paint(); toast(r.angle ? `Leveled by ${r.angle.toFixed(1)}°` : "It already looks level"); };
  $("#c-reset").onclick = () => { d.angle = 0; d.box = [0, 0, 1, 1]; d.aspect = "free"; paint(); };
  $("#c-cancel").onclick = () => setTool("crop");
  $("#c-apply").onclick = async () => {
    const angle = Math.round(d.angle * 10) / 10, full = d.box.every((v2, i) => Math.abs(v2 - [0, 0, 1, 1][i]) < 0.002);
    st.tool = null; st.cropDraft = null;
    await changeEdits(slotById(cur.id), (e) => {
      if (angle) e.angle = angle; else delete e.angle;
      if (full) delete e.crop; else e.crop = d.box.map((x) => Math.round(x * 10000) / 10000);
    });
    viewerSig = ""; renderViewer();
  };
  // dragging the box or its handles
  box.onpointerdown = (e) => {
    e.preventDefault();
    const h = e.target.dataset.h || "move", r = f.getBoundingClientRect(), start = [...d.box];
    const p0 = { x: e.clientX, y: e.clientY };
    const rs = ratio() ? ratio() * H / W : null;
    box.setPointerCapture(e.pointerId);
    box.onpointermove = (m) => {
      const dx = (m.clientX - p0.x) / r.width, dy = (m.clientY - p0.y) / r.height;
      let [x0, y0, x1, y1] = start;
      if (h === "move") {
        const w = x1 - x0, hh = y1 - y0;
        x0 = Math.min(Math.max(x0 + dx, 0), 1 - w); y0 = Math.min(Math.max(y0 + dy, 0), 1 - hh);
        d.box = [x0, y0, x0 + w, y0 + hh]; paint(); return;
      }
      if (h.includes("w")) x0 = Math.min(Math.max(0, x0 + dx), x1 - 0.05);
      if (h.includes("e")) x1 = Math.max(Math.min(1, x1 + dx), x0 + 0.05);
      if (h.includes("n")) y0 = Math.min(Math.max(0, y0 + dy), y1 - 0.05);
      if (h.includes("s")) y1 = Math.max(Math.min(1, y1 + dy), y0 + 0.05);
      if (rs) {  // keep the shape: the height follows the width, from the corner held still
        let w = x1 - x0, hh = w / rs;
        if (h === "n" || h === "s") { hh = y1 - y0; w = hh * rs; }
        const ax = h.includes("w") ? x1 : x0, ay = h.includes("n") ? y1 : y0;
        const maxW = h.includes("w") ? ax : 1 - ax, maxH = h.includes("n") ? ay : 1 - ay;
        if (w > maxW) { w = maxW; hh = w / rs; }
        if (hh > maxH) { hh = maxH; w = hh * rs; }
        x0 = h.includes("w") ? ax - w : ax; x1 = x0 + w;
        y0 = h.includes("n") ? ay - hh : ay; y1 = y0 + hh;
      }
      d.box = [x0, y0, x1, y1]; paint();
    };
    box.onpointerup = () => { box.onpointermove = null; };
  };
  paint();
}

// Removing distractions ---------------------------------------------------------------------------
function renderBrush(v, cur) {
  const W = cur.base_width, H = cur.base_height;
  const b = st.brush;
  v.innerHTML = `<div class="frame tool-remove" id="frame"><div class="layer"><img class="after" src="${slotImg(cur, "base")}" alt="" draggable="false"></div>
      <canvas id="brush"></canvas><div class="brush-ring" id="ring" hidden></div></div>
    <div class="fixbar toolbar">
      <span class="title"><b>Remove</b><span>Brush over what should go</span></span><span class="sep"></span>
      <span class="angle">Size<input type="range" id="b-size" min="0.008" max="0.09" step="0.002" value="${b.r}"></span>
      <button id="b-undo" title="Take back the last stroke">${icon("undo")}</button>
      <button id="b-clear">Clear</button><span class="sep"></span>
      <button id="b-go" class="on" ${b.strokes.length ? "" : "disabled"}>Remove it</button><button id="b-done">Done</button></div>`;
  paintIcons(v);
  fitFrame(W, H);
  const f = $("#frame"), cv = $("#brush"), ring = $("#ring");
  const size = () => {
    const r = f.getBoundingClientRect(), k = devicePixelRatio || 1;
    cv.width = r.width * k; cv.height = r.height * k; draw();
  };
  const draw = () => {
    const ctx = cv.getContext("2d"), w = cv.width, h = cv.height;
    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = ctx.fillStyle = "rgba(255, 70, 90, 0.55)";
    ctx.lineCap = ctx.lineJoin = "round";
    for (const s of b.strokes) {
      ctx.lineWidth = s.r * 2 * w;
      ctx.beginPath();
      s.pts.forEach(([x, y], i) => (i ? ctx.lineTo(x * w, y * h) : ctx.moveTo(x * w, y * h)));
      if (s.pts.length === 1) { ctx.arc(s.pts[0][0] * w, s.pts[0][1] * h, s.r * w, 0, Math.PI * 2); ctx.fill(); } else ctx.stroke();
    }
  };
  const go = () => { $("#b-go").disabled = !b.strokes.length; };
  requestAnimationFrame(size);
  const at = (e) => { const r = f.getBoundingClientRect(); return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height]; };
  const showRing = (e) => {
    const r = f.getBoundingClientRect(), d = b.r * 2 * r.width;
    ring.hidden = false;
    Object.assign(ring.style, { width: d + "px", height: d + "px", left: e.clientX - r.left - d / 2 + "px", top: e.clientY - r.top - d / 2 + "px" });
  };
  f.onpointermove = showRing;
  f.onpointerleave = () => { ring.hidden = true; };
  cv.onpointerdown = (e) => {
    e.preventDefault();
    cv.setPointerCapture(e.pointerId);
    const s = { pts: [at(e)], r: b.r };
    b.strokes.push(s); draw(); go();
    cv.onpointermove = (m) => { showRing(m); s.pts.push(at(m)); draw(); };
    cv.onpointerup = () => { cv.onpointermove = null; };
  };
  $("#b-size").oninput = (e) => { b.r = +e.target.value; store.set("brush", b.r); };
  $("#b-undo").onclick = () => { b.strokes.pop(); draw(); go(); };
  $("#b-clear").onclick = () => { b.strokes = []; draw(); go(); };
  $("#b-done").onclick = () => setTool("remove");
  $("#b-go").onclick = async () => {
    const strokes = b.strokes.map((s) => ({ pts: s.pts.map(([x, y]) => [Math.round(x * 10000) / 10000, Math.round(y * 10000) / 10000]), r: s.r }));
    b.strokes = [];
    const n = st.slots.filter((s) => s.photo === cur.photo && s.state === "done").length;
    const t = toast("Removing it…", { sticky: true, spin: true, small: n > 1 ? `then remaking this photo's ${n} looks` : "" });
    try {
      const r = await api(`/api/slots/${cur.id}/remove`, { strokes });
      pushHist({ type: "removal", pid: r.photo, before: r.removals.slice(0, -1), after: r.removals });
      t.done("Removed", "⌘Z puts it back");
    } catch { t.close(); }
    viewerSig = ""; await refresh();
  };
}
