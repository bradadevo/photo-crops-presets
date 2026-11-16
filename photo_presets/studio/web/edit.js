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
  if (e.type === "multi") {  // a removal on every look of a photo
    for (const it of e.items) updateSlot(await api(`/api/slots/${it.sid}/edit`, it[side]));
    if (e.pid != null) await api(`/api/photos/${e.pid}/future_removals`, { removals: e[side === "before" ? "futureBefore" : "futureAfter"] });
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
const SLIDER_TIPS = {
  exposure: "Brighter or darker, all over", contrast: "Flatter (left) or punchier (right)",
  highlights: "Left brings back bright areas: a white kit, the sky", shadows: "Right opens up dark areas: a shaded face",
  warmth: "Cooler blue (left) or warmer amber (right)", tint: "Greener (left) or more magenta (right)",
  saturation: "Less color (left, down to black and white) or more (right)", strength: "How much of the look shows: 0% is the photo as it was",
  subject: "The player alone, brighter or darker", background: "Everything behind the player, brighter or darker",
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
  const sliderRow = ([k, label, min, max, stp, unit, cls]) => `<div class="slider"><label for="e-${k}" title="${esc(SLIDER_TIPS[k])} · double-click the slider to reset">${label}</label>
    <output for="e-${k}">${fmtVal(k, val(k), unit)}</output><input type="range" class="${cls || ""}" id="e-${k}" data-k="${k}" data-unit="${unit || ""}" min="${min}" max="${max}" step="${stp}" value="${val(k)}"></div>`;
  const tool = (id, ic, label, tip) => `<button class="tool${st.tool === id || (id === "cutout" && st.fixing) ? " on" : ""}" data-tool="${id}" title="${esc(tip)}">${icon(ic)}<span>${label}</span></button>`;
  pane.innerHTML = `
    <div class="edit-head"><div class="adj-title"><b>${esc(cur.look)}</b><span>${esc(photo?.name || "")}</span></div>
      <div class="undo-btns"><button class="icon-btn" id="e-undo" title="Undo (⌘Z)" ${off(!hist.undo.length, "Nothing to undo yet: your edits can be undone here, one step at a time.")}>${icon("undo")}</button>
      <button class="icon-btn" id="e-redo" title="Redo (⇧⌘Z)" ${off(!hist.redo.length, "Nothing to redo: after an undo, this puts it back.")}>${icon("redo")}</button></div></div>
    <div class="tools">
      ${tool("crop", "crop", "Crop", "Crop and straighten (R)")}
      ${tool("remove", "eraser", "Remove", "Brush over a distraction to remove it")}
      ${tool("area", "target", "Adjust a part", "Click a face, the player or the sky to adjust just that")}
      ${tool("wb", "pipette", "White balance", "Click something white or gray")}
      ${tool("text", "type", "Text", "Add a name, a score or a date (T)")}
      ${tool("logo", "badge", "Logo", "Put your logo on it: a team crest, a sponsor, your own mark")}
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
    ${st.tool === "logo" || (e.logos || []).length ? logoSection(e) : ""}
    <div class="inline"><button class="btn" id="e-reset" title="Back to the look as it was made">Reset all</button>
      ${same > 1 ? `<button class="btn" id="e-all" style="flex:1" title="These light, color and look settings on every picture in this look">${icon("copy")} Use on all ${same}</button>` : ""}</div>
    <div class="section"><h3>This photo</h3><div class="actions">
      ${e.removals?.length ? `<p class="notes">${plural(e.removals.length, "thing")} removed from this look · ⌘Z puts the last one back</p>` : ""}
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
  bindLogoSection(cur, pane);
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
  st.compare = false; st.zoom.on = false; st.view = "single"; st.cropDraft = null;
  st.brush.strokes = []; st.brush.points = []; st.brush.preview = null;
  if (tool === "text" && st.tool === "text" && !(cur.edits?.texts || []).length) { addText(cur); }
  if (tool === "logo" && st.tool === "logo" && st.kit?.length === 1 && !(cur.edits?.logos || []).length) {
    // one logo in the kit: on it goes, bottom right (drag it, or pick a corner)
    const k = st.kit[0], [x, y] = cornerPlace("br", 0.18, k.width / k.height, cur.width, cur.height);
    st.logoSel = 0;
    changeEdits(cur, (ed) => { ed.logos = [{ id: k.id, x, y, size: 0.18, color: "auto", opacity: 1 }]; });
  }
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
    logo: `<span class="title"><b>Logo</b><span>Pick one in the panel · drag it to place it</span></span><span class="sep"></span><button data-done>Done</button>`,
  }[t];
  v.innerHTML = `<div class="frame tool-${t}" id="frame"><div class="layer"><img class="after" src="${src}" alt="" draggable="false" data-base="${base ? "" : `${cur.width}x${cur.height}`}"></div>
      ${t === "text" || t === "logo" ? `<div class="texts" id="texts"></div>` : ""}</div>
    <div class="fixbar toolbar">${bar}</div>`;
  paintIcons(v);
  if (base) fitFrame(cur.base_width, cur.base_height); else fitFrame(cur.width, cur.height);
  if (t === "text" || t === "logo") { paintTexts(cur); bindTexts(cur); }
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
    style="left:${t.x * 100}%;top:${t.y * 100}%;font-size:calc(var(--fw) * ${t.size});color:${esc(t.color)}">${esc(t.text)}</div>`).join("")
    + (cur.edits?.logos || []).map((l, i) => `<img class="lg${st.tool === "logo" && st.logoSel === i ? " sel" : ""}" data-li="${i}" alt="" draggable="false"
      src="/img/logo/${enc(l.id)}/${l.color === "auto" ? autoColor(l) : l.color}.png" style="left:${l.x * 100}%;top:${l.y * 100}%;width:${l.size * 100}%;opacity:${l.opacity}">`).join("");
}

/* "auto": white on a dark spot of the picture, black on a light one (as the export decides). */
let lumCanvas = null, lumSrc = "";
function autoColor(l) {
  if ((st.kit || []).find((k) => k.id === l.id)?.flat === false) return "original";  // a crest shows as it is
  const img = $("#frame img.after");
  if (!img || !img.complete || !img.naturalWidth) return "white";
  if (lumSrc !== img.src) {
    lumCanvas = document.createElement("canvas");
    lumCanvas.width = 200; lumCanvas.height = Math.max(1, Math.round(200 * img.naturalHeight / img.naturalWidth));
    try { lumCanvas.getContext("2d").drawImage(img, 0, 0, lumCanvas.width, lumCanvas.height); lumSrc = img.src; } catch { return "white"; }
  }
  const W = lumCanvas.width, H = lumCanvas.height, w = Math.max(1, Math.round(l.size * W));
  const art = (st.kit || []).find((k) => k.id === l.id), hh = Math.max(1, Math.round(w * (art ? art.height / art.width : 0.5)));
  const x0 = Math.max(0, Math.round(l.x * W - w / 2)), y0 = Math.max(0, Math.round(l.y * H - hh / 2));
  const d = lumCanvas.getContext("2d").getImageData(x0, y0, Math.min(w, W - x0) || 1, Math.min(hh, H - y0) || 1).data;
  let sum = 0;
  for (let i = 0; i < d.length; i += 4) sum += d[i] * 0.299 + d[i + 1] * 0.587 + d[i + 2] * 0.114;
  return sum / (d.length / 4) / 255 > 0.62 ? "black" : "white";
}
function bindTexts(cur) {
  const box = $("#texts"), f = $("#frame");
  if (!box) return;
  box.onpointerdown = (e) => {
    const lg = e.target.closest(".lg");
    if (lg && st.tool === "logo") return dragLogo(cur, lg, e, f);
    const el = e.target.closest(".tx");
    if (!el || st.tool !== "text") return;
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

function dragLogo(cur, el, e, f) {
  e.preventDefault();
  const i = +el.dataset.li, r = f.getBoundingClientRect();
  if (st.logoSel !== i) { st.logoSel = i; editSig = ""; renderTabs(); $$("#texts .lg").forEach((x) => x.classList.toggle("sel", +x.dataset.li === i)); }
  const l0 = slotById(cur.id).edits.logos[i];
  const start = { x: e.clientX, y: e.clientY, lx: l0.x, ly: l0.y };
  let moved = false, pos = { x: l0.x, y: l0.y };
  el.setPointerCapture(e.pointerId);
  el.onpointermove = (m) => {
    moved = true;
    pos = { x: Math.max(0, Math.min(1, start.lx + (m.clientX - start.x) / r.width)), y: Math.max(0, Math.min(1, start.ly + (m.clientY - start.y) / r.height)) };
    if (Math.abs(pos.x - 0.5) < 0.012) pos.x = 0.5;
    el.style.left = pos.x * 100 + "%"; el.style.top = pos.y * 100 + "%";
    f.classList.toggle("snap-x", pos.x === 0.5);
  };
  el.onpointerup = () => {
    el.onpointermove = null; f.classList.remove("snap-x");
    if (moved) changeEdits(slotById(cur.id), (ed) => { ed.logos[i].x = pos.x; ed.logos[i].y = pos.y; }, { keepPane: true });
  };
}

// The brand kit and the logos on this picture ------------------------------------------------------
const CORNER_ICONS = [["tl", "↖"], ["tr", "↗"], ["bc", "↓"], ["bl", "↙"], ["br", "↘"]];
function logoSection(e) {
  const placed = e.logos || [];
  const kit = st.kit || [];
  const sel = placed[st.logoSel ?? -1];
  return `<div class="section"><h3>Logo</h3>
    ${placed.map((l, i) => { const k = kit.find((x) => x.id === l.id);
      return `<div class="item${st.logoSel === i ? " on" : ""}"><div class="item-head"><button class="item-name" data-pick-logo="${i}">
        <img class="kit-mini" src="/img/logo/${enc(l.id)}/original.png" alt="">${esc(k?.name || "Logo")}</button>
        <button class="icon-btn" data-del-logo="${i}" title="Take it off this picture">${icon("trash")}</button></div>
        ${st.logoSel === i ? `<div class="corners">${CORNER_ICONS.map(([c, a]) => `<button data-corner="${c}" title="Move it to this corner">${a}</button>`).join("")}</div>
        <div class="seg full small" data-logo-color>${[["auto", "Auto"], ["original", "As it is"], ["white", "White"], ["black", "Black"]].map(([v, t]) => `<button data-v="${v}" class="${l.color === v ? "on" : ""}" title="${v === "auto" ? "A one-color logo goes white on dark spots and black on light ones; a crest shows as it is" : ""}">${t}</button>`).join("")}</div>
        <div class="slider"><label>Size</label><output>${Math.round(l.size * 100)}%</output><input type="range" data-logo-k="size" min="0.04" max="0.6" step="0.01" value="${l.size}"></div>
        <div class="slider"><label>Strength</label><output>${Math.round(l.opacity * 100)}%</output><input type="range" data-logo-k="opacity" min="0.1" max="1" step="0.05" value="${l.opacity}"></div>` : ""}
      </div>`; }).join("")}
    <div class="kit kit-drop" id="kit"><span class="kit-title">Your logos <small>· click one to put it on</small></span>
      <div class="kit-grid">${kit.map((k) => `<button class="kit-logo" data-kit="${k.id}" title="${esc(k.name)}: put it on this picture"><img src="/img/logo/${enc(k.id)}/original.png" alt="${esc(k.name)}">
        <span class="kit-x" data-kit-del="${k.id}" title="Delete it from your logos">${icon("x")}</span></button>`).join("")}
        <label class="kit-add" title="Add a logo: a PNG, a JPG on white, or a screenshot of it">${icon("plus")}<span>Add a logo</span><input type="file" id="kit-file" accept="image/*" hidden></label></div>
      <small class="notes">Drop a logo here. Any background is taken away: a JPG on white or a screenshot works.</small></div>
  </div>`;
}
function bindLogoSection(cur, pane) {
  const s0 = () => slotById(cur.id);
  pane.querySelectorAll("[data-kit]").forEach((b) => b.onclick = (ev) => {
    if (ev.target.closest("[data-kit-del]")) return;
    const k = st.kit.find((x) => x.id === b.dataset.kit), s = s0();
    const n = (s.edits?.logos || []).length;
    const size = 0.18, aspect = k.width / k.height;
    const [x, y] = cornerPlace("br", size, aspect, s.width, s.height);
    st.logoSel = n;
    if (st.tool !== "logo") { st.tool = "logo"; viewerSig = ""; }
    changeEdits(s, (ed) => { (ed.logos ||= []).push({ id: k.id, x, y, size, color: "auto", opacity: 1 }); });
  });
  pane.querySelectorAll("[data-kit-del]").forEach((b) => b.onclick = async (ev) => {
    ev.stopPropagation();
    await api(`/api/logos/${b.dataset.kitDel}`, undefined, { method: "DELETE" });
    await loadKit();
  });
  $("#kit-file", pane)?.addEventListener("change", (ev) => { const f = ev.target.files[0]; if (f) addLogo(f); });
  pane.querySelectorAll("[data-pick-logo]").forEach((b) => b.onclick = () => {
    const i = +b.dataset.pickLogo; st.logoSel = st.logoSel === i ? null : i; editSig = "";
    if (st.tool !== "logo") { st.tool = "logo"; viewerSig = ""; renderViewer(); }
    renderTabs();
  });
  pane.querySelectorAll("[data-del-logo]").forEach((b) => b.onclick = () => {
    const i = +b.dataset.delLogo; st.logoSel = null;
    changeEdits(s0(), (ed) => { ed.logos.splice(i, 1); });
  });
  pane.querySelectorAll("[data-corner]").forEach((b) => b.onclick = () => {
    const i = st.logoSel, s = s0(), l = s.edits.logos[i], k = st.kit.find((x) => x.id === l.id);
    const [x, y] = cornerPlace(b.dataset.corner, l.size, k ? k.width / k.height : 2, s.width, s.height);
    changeEdits(s, (ed) => { ed.logos[i].x = x; ed.logos[i].y = y; });
  });
  pane.querySelectorAll("[data-logo-color] button").forEach((b) => b.onclick = () => {
    const i = st.logoSel;
    changeEdits(s0(), (ed) => { ed.logos[i].color = b.dataset.v; });
  });
  pane.querySelectorAll("input[data-logo-k]").forEach((r) => {
    let snap = null, timer = null;
    r.oninput = () => {
      const s = s0(), i = st.logoSel, k = r.dataset.logoK;
      if (!snap) snap = snapshot(s);
      r.previousElementSibling.textContent = Math.round(r.value * 100) + "%";
      const e2 = clone(s.edits); e2.logos[i][k] = +r.value;
      s.edits = e2; paintTexts(s);
      clearTimeout(timer);
      timer = setTimeout(async () => { updateSlot(await api(`/api/slots/${cur.id}/edit`, { edits: e2 }), { keepPane: true }); }, 200);
    };
    r.onchange = () => setTimeout(() => { if (snap) pushHist({ type: "slot", sid: cur.id, before: snap, after: snapshot(s0()) }); snap = null; }, 400);
  });
}
/* Where a logo's middle goes to sit in a corner with a margin (as brand.corner_place). */
function cornerPlace(corner, size, aspect, w, h) {
  const m = 0.035, lh = size * w / h / Math.max(aspect, 1e-3);
  const cx = { l: m + size / 2, r: 1 - m - size / 2, c: 0.5 }[corner[1]];
  const cy = { t: m * w / h + lh / 2, b: 1 - m * w / h - lh / 2 }[corner[0]];
  return [cx, cy];
}
async function loadKit() {
  try { st.kit = (await api("/api/logos")).logos; } catch { st.kit = []; }
  editSig = "";
  if (st.tab === "edit") renderTabs();
}
async function addLogo(file) {
  const fd = new FormData(); fd.append("file", file, file.name);
  const t = toast("Adding your logo…", { sticky: true, spin: true, small: "Taking its background away" });
  try { await api("/api/logos", fd); t.done("Logo added", "Click it to put it on the picture"); } catch { t.close(); }
  await loadKit();
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
/* Click a person or a thing to remove it (the app takes all of them: their edge and their shadow
   too), or brush over it. What will go shows in red before anything is removed; then this look
   only, or every look of this photo. It never takes the players kept in the look unless you
   brush right over them. */
function renderBrush(v, cur) {
  const b = st.brush;
  b.mode ||= "click";
  b.scope ||= "look";
  const others = st.slots.filter((s) => s.photo === cur.photo && s.state === "done").length;
  v.innerHTML = `<div class="frame tool-remove mode-${b.mode}" id="frame"><div class="layer"><img class="after" src="${slotImg(cur, "base")}" alt="" draggable="false"></div>
      <img class="rm-preview" id="rm-preview" alt="" hidden><canvas id="brush"></canvas><div class="brush-ring" id="ring" hidden></div>
      <span class="tag l rm-status" id="rm-status" hidden></span></div>
    <div class="fixbar toolbar rm-bar">
      <div class="seg small" id="rm-mode"><button data-v="click" title="Click a person or a thing: all of it goes">${icon("target")} Click</button><button data-v="brush" title="Paint over what should go">${icon("eraser")} Brush</button></div>
      <span class="angle" id="rm-size" ${b.mode === "brush" ? "" : "hidden"}>Size<input type="range" id="b-size" min="0.006" max="0.08" step="0.002" value="${b.r}"></span>
      <button id="rm-people" title="Select every person who is not one of the players kept" hidden>${icon("plus")} Background people</button>
      <span class="sep"></span>
      ${others > 1 ? `<div class="seg small" id="rm-scope"><button data-v="look" title="Only this look">This look</button><button data-v="photo" title="Every look of this photo, and the looks made of it later">All ${others} looks</button></div><span class="sep"></span>` : ""}
      <button id="b-undo" title="Take back the last click or stroke">${icon("undo")}</button>
      <button id="b-go" class="on">Remove it</button><button id="b-done">Done</button></div>`;
  paintIcons(v);
  fitFrame(cur.base_width, cur.base_height);
  const f = $("#frame"), cv = $("#brush"), ring = $("#ring"), prev = $("#rm-preview"), status = $("#rm-status");
  const paintBar = () => {
    $$("#rm-mode button").forEach((x) => x.classList.toggle("on", x.dataset.v === b.mode));
    $$("#rm-scope button").forEach((x) => x.classList.toggle("on", x.dataset.v === b.scope));
    $("#rm-size").hidden = b.mode !== "brush";
    f.classList.toggle("mode-brush", b.mode === "brush"); f.classList.toggle("mode-click", b.mode === "click");
    setOff($("#b-go"), !(b.strokes.length || b.points.length), b.mode === "click"
      ? "Click a person or a thing on the picture first: it turns red, then Remove it."
      : "Brush over what should go first (drag on the picture).");
    setOff($("#b-undo"), !(b.strokes.length || b.points.length), "Nothing picked yet.");
  };
  const size = () => {
    const r = f.getBoundingClientRect(), k = devicePixelRatio || 1;
    cv.width = r.width * k; cv.height = r.height * k; draw();
  };
  const draw = () => {  // the brush strokes while painting (the red preview shows what will really go)
    const ctx = cv.getContext("2d"), w = cv.width, h = cv.height;
    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = ctx.fillStyle = "rgba(255, 70, 90, 0.35)";
    ctx.lineCap = ctx.lineJoin = "round";
    for (const s2 of b.strokes) {
      ctx.lineWidth = s2.r * 2 * w;
      ctx.beginPath();
      s2.pts.forEach(([x, y], i) => (i ? ctx.lineTo(x * w, y * h) : ctx.moveTo(x * w, y * h)));
      if (s2.pts.length === 1) { ctx.arc(s2.pts[0][0] * w, s2.pts[0][1] * h, s2.r * w, 0, Math.PI * 2); ctx.fill(); } else ctx.stroke();
    }
  };
  let previewTimer = null, previewAsk = 0;
  const preview = () => {  // what will go, worked out by the app: whole people and things, edges, shadows
    clearTimeout(previewTimer);
    paintBar();
    if (!b.strokes.length && !b.points.length) { prev.hidden = true; status.hidden = true; b.preview = null; return; }
    previewTimer = setTimeout(async () => {
      const ask = ++previewAsk;
      status.hidden = false; status.innerHTML = '<span class="spin"></span> Finding it…';
      try {
        const res = await fetch(`/api/slots/${cur.id}/remove/preview`, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ points: b.points, strokes: b.strokes }) });
        if (!res.ok || ask !== previewAsk) return;
        const url = URL.createObjectURL(await res.blob());
        if (b.preview) URL.revokeObjectURL(b.preview);
        b.preview = url; prev.src = url; prev.hidden = false;
        status.innerHTML = "Red goes · click more, or Remove it";
      } catch { status.hidden = true; }
    }, 150);
  };
  requestAnimationFrame(() => { size(); if (b.preview) { prev.src = b.preview; prev.hidden = false; } paintBar(); });
  const at = (e) => { const r = f.getBoundingClientRect(); return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height]; };
  const showRing = (e) => {
    if (b.mode !== "brush") { ring.hidden = true; return; }
    const r = f.getBoundingClientRect(), d = b.r * 2 * r.width;
    ring.hidden = false;
    Object.assign(ring.style, { width: d + "px", height: d + "px", left: e.clientX - r.left - d / 2 + "px", top: e.clientY - r.top - d / 2 + "px" });
  };
  f.onpointermove = showRing;
  f.onpointerleave = () => { ring.hidden = true; };
  cv.onpointerdown = (e) => {
    e.preventDefault();
    if (b.mode === "click") { b.points.push(at(e)); b.order = [...(b.order || []), "p"]; preview(); return; }
    cv.setPointerCapture(e.pointerId);
    const s2 = { pts: [at(e)], r: b.r };
    b.strokes.push(s2); b.order = [...(b.order || []), "s"]; draw();
    cv.onpointermove = (m) => { showRing(m); s2.pts.push(at(m)); draw(); };
    cv.onpointerup = () => { cv.onpointermove = null; preview(); };
  };
  $$("#rm-mode button").forEach((x) => x.onclick = () => { b.mode = x.dataset.v; paintBar(); });
  $$("#rm-scope button").forEach((x) => x.onclick = () => { b.scope = x.dataset.v; paintBar(); });
  $("#b-size").oninput = (e) => { b.r = +e.target.value; store.set("brush", b.r); };
  $("#b-undo").onclick = () => {
    const last = (b.order || []).pop();
    if (last === "s") b.strokes.pop(); else if (last === "p") b.points.pop();
    draw(); preview();
  };
  $("#b-done").onclick = () => setTool("remove");
  // the background people: one click selects them all
  api(`/api/slots/${cur.id}/people`).then((r) => {
    const btn = $("#rm-people");
    if (!btn || !r.people.length) return;
    btn.hidden = false;
    btn.innerHTML = `${icon("plus")} ${plural(r.people.length, "background person", "background people")}`;
    btn.onclick = () => { r.people.forEach((p) => { b.points.push([p.x, p.y]); (b.order ||= []).push("p"); }); preview(); };
  }).catch(() => {});
  $("#b-go").onclick = async () => {
    const body = { points: b.points.map(([x, y]) => [Math.round(x * 1e4) / 1e4, Math.round(y * 1e4) / 1e4]),
      strokes: b.strokes.map((s2) => ({ pts: s2.pts.map(([x, y]) => [Math.round(x * 1e4) / 1e4, Math.round(y * 1e4) / 1e4]), r: s2.r })),
      scope: b.scope };
    const affected = b.scope === "photo" ? st.slots.filter((s2) => s2.photo === cur.photo && s2.state === "done") : [cur];
    const before = new Map(affected.map((s2) => [s2.id, snapshot(s2)]));
    const t = toast(affected.length > 1 ? `Removing it from ${plural(affected.length, "look")}…` : "Removing it…", { sticky: true, spin: true });
    try {
      const r = await api(`/api/slots/${cur.id}/remove`, body);
      const items = r.slots.filter((s2) => before.has(s2.id)).map((s2) => ({ sid: s2.id, before: before.get(s2.id), after: snapshot(s2) }));
      pushHist({ type: "multi", items, pid: b.scope === "photo" ? cur.photo : null,
        futureBefore: (r.future || []).slice(0, -1), futureAfter: r.future || [] });
      r.slots.forEach((s2) => updateSlot(s2));
      t.done("Removed", "⌘Z puts it back");
    } catch { t.close(); }
    b.strokes = []; b.points = []; b.order = [];
    if (b.preview) URL.revokeObjectURL(b.preview);
    b.preview = null;
    viewerSig = ""; renderViewer();
  };
}
