/* VS Digital Pro Studio: editing a picture. The Edit tab (light, color, the look, parts, text),
   the tools used on the picture itself (crop and straighten, remove distractions, adjust a
   part, white balance, text), and undo / redo. Loaded after app.js, whose helpers it uses. */
"use strict";

// Undo and redo ------------------------------------------------------------------------------
const hist = { undo: [], redo: [] };
const clone = (o) => JSON.parse(JSON.stringify(o ?? {}));
const snapshot = (s) => ({ adjust: { ...s.adjust }, edits: clone(s.edits) });

const HIST_KEY = "allpro.history";
function keepHist() {
  try { localStorage.setItem(HIST_KEY, JSON.stringify({ undo: hist.undo.slice(-60), redo: hist.redo.slice(-60) })); } catch { /* full or blocked: kept for this session only */ }
}
try { const h = JSON.parse(localStorage.getItem(HIST_KEY) || "null"); if (h) { hist.undo = h.undo || []; hist.redo = h.redo || []; } } catch { /* none */ }
function pushHist(entry) {
  if (entry.type === "slot" && JSON.stringify(entry.before) === JSON.stringify(entry.after)) return;  // (nothing changed)
  hist.undo.push(entry);
  if (hist.undo.length > 100) hist.undo.shift();
  hist.redo = [];
  keepHist();
  paintUndoButtons();
  editSig = "";
  if (st.tab === "edit") {
    if (typingInPanel()) paintUndoButtons(); else renderTabs();  // (never redrawn under your typing)
  }
}

const typingInPanel = () => !!document.activeElement?.closest?.("#pane-edit input, #pane-edit textarea");
function paintUndoButtons() {
  setOff($("#e-undo"), !hist.undo.length, "Nothing to undo yet: your edits can be undone here, one step at a time.");
  setOff($("#e-redo"), !hist.redo.length, "Nothing to redo: after an undo, this puts it back.");
  $$("[data-hist]").forEach((b) => b.dataset.hist === "undo"
    ? setOff(b, !hist.undo.length, "Nothing to undo yet: your edits can be undone here, one step at a time.")
    : setOff(b, !hist.redo.length, "Nothing to redo: after an undo, this puts it back."));
}
/* Undo and redo at the start of the picture's own bar (every tool's too), while editing */
const histBtns = () => `<span class="hist-btns"><button data-hist="undo" title="Undo (⌘Z)" ${off(!hist.undo.length, "Nothing to undo yet: your edits can be undone here, one step at a time.")}>${icon("undo")}</button>
  <button data-hist="redo" title="Redo (⇧⌘Z)" ${off(!hist.redo.length, "Nothing to redo: after an undo, this puts it back.")}>${icon("redo")}</button></span><span class="sep"></span>`;
document.addEventListener("click", (e) => {
  const b = e.target.closest?.("[data-hist]");
  if (!b || b.getAttribute("aria-disabled") === "true") return;
  e.stopPropagation();
  (b.dataset.hist === "undo" ? undo : redo)();
}, true);
async function undo() { await closeBursts(); await travel(hist.undo, hist.redo, "before"); }
async function redo() { await closeBursts(); await travel(hist.redo, hist.undo, "after"); }
async function travel(from, to, side) {
  let e = from.pop();
  while (e && !(e.type === "multi" ? e.items.some((it) => slotById(it.sid)) : slotById(e.sid))) e = from.pop();  // (a picture since removed: skipped)
  if (!e) { keepHist(); toast(side === "before" ? "Nothing more to undo" : "Nothing to redo"); return; }
  to.push(e);
  keepHist();
  if (e.type === "multi") {  // a change on several pictures at once (a removal on every look, Use on all…)
    for (const it of e.items) if (slotById(it.sid)) { await flushEdits(it.sid); updateSlot(await api(`/api/slots/${it.sid}/edit`, it[side])); }
    if (e.pid != null) await api(`/api/photos/${e.pid}/future_removals`, { removals: e[side === "before" ? "futureBefore" : "futureAfter"] });
  } else {
    if (e.sid !== st.current) select(e.sid, true);  // (you see what is undone)
    await flushEdits(e.sid);  // (a save on its way first, so it cannot bring back what is undone)
    const s = await api(`/api/slots/${e.sid}/edit`, e[side]);
    updateSlot(s);
  }
  toast(side === "before" ? "Undone" : "Redone", { small: hist.undo.length ? `${plural(hist.undo.length, "more step")} to undo` : "" });
  editSig = "";
  renderTabs();
  paintUndoButtons();
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
      paintTexts(s); paintWords(s);
    } else { viewerSig = ""; renderViewer(); }
  }
  if (keepPane) editSig = paneSignature(s);
  renderStrip(); renderTop();
  if (!keepPane) renderTabs();
}

/* Saving a picture's edits, one at a time and always the latest: what you type shows at once and is
   saved a moment later; any other change waits for it and builds on it (so nothing typed is lost). */
const saving = new Map();  // slot id -> { timer, ver, sent, chain }
function pendingOf(sid) {
  if (!saving.has(sid)) saving.set(sid, { timer: null, ver: 0, sent: 0, chain: Promise.resolve() });
  return saving.get(sid);
}
function saveSoon(sid, edits, delay = 300) {
  const s = slotById(sid);
  if (!s) return;
  const p = pendingOf(sid);
  if (!p.burst) p.burst = snapshot(s);  // a run of typing or sliding: one step to undo
  clearTimeout(p.burstTimer);
  p.burstTimer = setTimeout(() => closeBurst(sid), 1200);
  s.edits = edits;
  p.ver++;
  clearTimeout(p.timer);
  p.timer = setTimeout(() => flushEdits(sid), delay);
}
/* The run of quick changes ends: it becomes one step in the undo list. */
async function closeBurst(sid) {
  const p = pendingOf(sid);
  clearTimeout(p.burstTimer);
  if (p.closing) return p.closing;  // (already closing: wait for it, so undo finds the step)
  if (!p.burst) return;
  const before = p.burst; p.burst = null;
  p.closing = (async () => {
    await flushEdits(sid);
    const s = slotById(sid);
    if (s) pushHist({ type: "slot", sid, before, after: snapshot(s) });
  })();
  try { await p.closing; } finally { p.closing = null; }
}
async function closeBursts() { for (const sid of saving.keys()) await closeBurst(sid); }
function flushEdits(sid) {
  const p = pendingOf(sid);
  clearTimeout(p.timer); p.timer = null;
  if (p.sent >= p.ver) return p.chain;
  p.chain = p.chain.then(async () => {
    const s = slotById(sid);
    if (!s || p.sent >= p.ver) return;
    const ver = p.ver;
    const got = await api(`/api/slots/${sid}/edit`, { edits: s.edits });
    p.sent = Math.max(p.sent, ver);
    if (p.ver > ver) got.edits = slotById(sid).edits;  // typed more meanwhile: kept on screen, saved next
    updateSlot(got, { keepPane: true });
  }).catch(() => {});
  return p.chain;
}
async function changeEdits(cur, mutate, opts) {
  await closeBurst(cur.id);  // what was just typed first (its own step to undo)
  const p = pendingOf(cur.id);
  const run = p.chain.then(async () => {
    const live = slotById(cur.id) || cur;  // (never an older copy of the picture)
    const before = snapshot(live);
    const e = clone(live.edits);
    mutate(e);
    const s = await api(`/api/slots/${cur.id}/edit`, { edits: e });
    pushHist({ type: "slot", sid: cur.id, before, after: snapshot(s) });
    updateSlot(s, opts);
    return s;
  });
  p.chain = run.catch(() => {});
  return run;
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
/* Advanced: folded away under one "Advanced" group, each part its own fold (pipeline.ADJUST) */
const ADVANCED = [
  ["punch", "Clarity and punch", [["vibrance", "Vibrance", -1, 1, 0.05], ["clarity", "Clarity", -1, 1, 0.05], ["texture", "Texture", -1, 1, 0.05],
    ["dehaze", "Dehaze", -1, 1, 0.05], ["whites", "Whites", -1, 1, 0.05], ["blacks", "Blacks", -1, 1, 0.05]]],
  ["player", "Player and background", [["p_clarity", "Player clarity", -1, 1, 0.05], ["p_vibrance", "Player vibrance", -1, 1, 0.05],
    ["p_warmth", "Player warmth", -1, 1, 0.05, "", "warm"], ["p_sharpen", "Player sharpness", 0, 1, 0.05, "pct"], ["face_light", "Face light", 0, 1, 0.05, "pct"],
    ["rim_light", "Rim light", 0, 1, 0.05, "pct"], ["bg_blur", "Background blur", 0, 1, 0.05, "pct"], ["bg_saturation", "Background color", -1, 1, 0.05],
    ["bg_warmth", "Background warmth", -1, 1, 0.05, "", "warm"]]],
  ["mixer", "Color mixer", null],
  ["grading", "Color grading", null],
  ["finish", "Finishing", [["noise", "Noise reduction", 0, 1, 0.05, "pct"], ["sharpen", "Sharpen", 0, 1, 0.05, "pct"], ["vignette", "Vignette", -1, 1, 0.05]]],
];
const MIX_COLORS = [["red", "Red", "#e5484d"], ["orange", "Orange", "#f08c2e"], ["yellow", "Yellow", "#f2cf1d"], ["green", "Green", "#3fb950"],
  ["aqua", "Aqua", "#2fc6c6"], ["blue", "Blue", "#3b82f6"], ["purple", "Purple", "#8b5cf6"], ["magenta", "Magenta", "#e04fbf"]];
const GRADES = [["sh", "Shadows"], ["mid", "Midtones"], ["hi", "Highlights"]];
const ADJ_DEFAULT = { strength: 100, grade_sh_hue: 210, grade_mid_hue: 30, grade_hi_hue: 40 };
/* Which Advanced sliders each fold holds (to show how many are in use) */
const ADV_KEYS = {
  punch: ADVANCED[0][2].map((r) => r[0]), player: ADVANCED[1][2].map((r) => r[0]), finish: ADVANCED[4][2].map((r) => r[0]),
  mixer: [...MIX_COLORS.flatMap(([c]) => ["h", "s", "l"].map((x) => `mix_${c}_${x}`)), "kit_pop"],
  grading: GRADES.map(([g]) => `grade_${g}`),
};
Object.assign(SLIDER_TIPS, {
  vibrance: "More color where it's dull, while skin stays natural", clarity: "Midtone punch: muscles, kit folds, faces get depth",
  texture: "Fine detail: fabric, hair, grass (left softens it)", dehaze: "Cuts haze and glare (left adds a soft haze)",
  whites: "The very brightest tones up or down", blacks: "The darkest tones: left deeper, right lifted (matte)",
  p_clarity: "Punch on the player only", p_vibrance: "Color on the player only", p_warmth: "The player alone, cooler or warmer",
  p_sharpen: "A crisper player (the background is left soft)", face_light: "Brighter faces, softly, as if lit with a reflector",
  rim_light: "A soft glow around the player's edge, like stadium backlight", bg_blur: "The background soft, like a fast lens",
  bg_saturation: "The background's color: left down to black and white", bg_warmth: "The background alone, cooler or warmer",
  noise: "Smooths grain from high ISO, keeping edges", sharpen: "A final crispness on the whole picture",
  vignette: "Left darkens the corners, right lightens them", kit_pop: "Makes the picked kit color richer and deeper, nothing else",
  ...Object.fromEntries(MIX_COLORS.flatMap(([c, l]) => [[`mix_${c}_h`, `Moves ${l.toLowerCase()}s toward the next colors`],
    [`mix_${c}_s`, `${l}s more or less colorful`], [`mix_${c}_l`, `${l}s lighter or darker`]])),
  ...Object.fromEntries(GRADES.flatMap(([g, l]) => [[`grade_${g}_hue`, `The color the ${l.toLowerCase()} lean toward`], [`grade_${g}`, `How much the ${l.toLowerCase()} lean toward it`]])),
});
const TEXT_STYLES = [["clean", "Clean"], ["bold", "Bold"], ["spaced", "Spaced"], ["banner", "Banner"]];
const TEXT_COLORS = ["#ffffff", "#111111", "#f5c443", "#1f2a44", "#e63946", "#86d0d8"];
/* The fonts any word can be set in (fonts.py), each shown in its own face, as it's exported */
const FONTS = [["vs-display", "VS Display"], ["vs-tech", "VS Tech"], ["avenir-heavy", "Avenir Heavy"], ["avenir-bold", "Avenir Bold"], ["avenir-light", "Avenir Light"], ["condensed", "Condensed"],
  ["sport-italic", "Sport Italic"], ["futura", "Futura"], ["futura-tall", "Futura Tall"], ["impact", "Impact"], ["din", "DIN Condensed"],
  ["gill-light", "Gill Sans Light"], ["rockwell", "Varsity Slab"], ["copperplate", "Copperplate"], ["didot", "Didot"], ["bodoni", "Bodoni"],
  ["baskerville", "Baskerville Italic"], ["script", "Script"], ["brush", "Brush Script"]];
(() => {
  const css = document.createElement("style");
  css.textContent = FONTS.map(([k]) => `@font-face{font-family:"app-${k}";src:url("/font/${k}.ttf") format("truetype");font-display:swap}`).join("");
  document.head.appendChild(css);
})();
const fontCss = (k) => (k ? `font-family:'app-${k}';font-weight:normal;font-style:normal;` : "");
/* A font picker: data-font-pick on the grid, each button's data-v the font ("" for the style's own) */
const fontPicker = (cur, auto, attr = "") => `<label class="sub-label">Font</label><div class="font-grid" data-font-pick ${attr}>
  <button data-v="" class="auto${cur ? "" : " on"}" title="${esc(auto)}">${esc(auto)}</button>${FONTS.map(([k, l]) => `<button data-v="${k}" class="${cur === k ? "on" : ""}" style="${fontCss(k)}">${esc(l)}</button>`).join("")}</div>`;
/* Turning a word or a piece: a slider (double-click: level) and quick turns */
const angleControl = (v, attr = "") => `<div class="angle-ctl" ${attr}><div class="slider"><label title="Turn it to any angle · on the picture, drag its round handle (hold Shift for 15° steps) · double-click to level">Angle</label><output>${Math.round(v || 0)}°</output>
  <input type="range" data-angle min="-180" max="180" step="1" value="${v || 0}"></div>
  <div class="seg full small angle-quick">${[[-90, "↺ 90°"], [-15, "↺ 15°"], [0, "Level"], [15, "↻ 15°"], [90, "↻ 90°"]].map(([d, l]) => `<button data-turn="${d}" title="${d ? `Turn ${Math.abs(d)}° ${d > 0 ? "clockwise" : "counterclockwise"}` : "Straight again"}">${l}</button>`).join("")}</div></div>`;
const normAngle = (a) => Math.round((((a + 180) % 360) + 360) % 360 - 180);
/* Binds an angleControl in root: live(a) while sliding, commit(a) when let go or a quick turn is clicked */
function bindAngle(root, get, live, commit) {
  root?.querySelectorAll(".angle-ctl").forEach((box) => {
    const r = box.querySelector("[data-angle]"), out = r.previousElementSibling;
    r.oninput = () => { out.textContent = `${r.value}°`; live?.(+r.value); };
    r.onchange = () => commit(+r.value);
    r.ondblclick = () => commit(0);
    box.querySelectorAll("[data-turn]").forEach((b) => b.onclick = () => commit(+b.dataset.turn ? normAngle(get() + +b.dataset.turn) : 0));
  });
}
/* Dragging a round handle turns el around its middle: live(a) as it turns, done(a) when let go.
   It snaps level (and to every 45°) when close; Shift turns in 15° steps. */
function rotateDrag(el, e, start, live, done) {
  e.preventDefault(); e.stopPropagation();
  const b = el.getBoundingClientRect(), cx = b.left + b.width / 2, cy = b.top + b.height / 2;
  const a0 = Math.atan2(e.clientY - cy, e.clientX - cx) * 180 / Math.PI;
  let a = start;
  const h = e.target;
  h.setPointerCapture(e.pointerId);
  h.onpointermove = (m) => {
    a = normAngle(start + Math.atan2(m.clientY - cy, m.clientX - cx) * 180 / Math.PI - a0);
    if (m.shiftKey) a = normAngle(Math.round(a / 15) * 15);
    else { const n = Math.round(a / 45) * 45; if (Math.abs(a - n) < 3) a = normAngle(n); }
    live(a);
    showTurnTip(el, `${a}°`);
  };
  h.onpointerup = () => { h.onpointermove = h.onpointerup = null; hideTurnTip(); if (a !== start) done(a); };
}
let turnTipEl = null;
function showTurnTip(el, text) {
  turnTipEl ||= Object.assign(document.createElement("div"), { className: "turn-tip" });
  if (!turnTipEl.isConnected) document.body.appendChild(turnTipEl);
  const b = el.getBoundingClientRect();
  turnTipEl.textContent = text;
  turnTipEl.style.left = b.left + b.width / 2 + "px"; turnTipEl.style.top = Math.max(8, b.top - 34) + "px";
}
function hideTurnTip() { turnTipEl?.remove(); }
/* Turning a word stands it up: a long one near an edge would run off the picture. How far to move its
   middle (shares of the frame) so all of it stays on: box in shares (as it is, level), a in degrees. */
function keepOn(box, a) {
  const f = $("#frame");
  if (!f || !box) return [0, 0];
  const W = f.clientWidth, H = f.clientHeight, t = (a * Math.PI) / 180, c = Math.abs(Math.cos(t)), s = Math.abs(Math.sin(t));
  const w = (box.x1 - box.x0) * W, h = (box.y1 - box.y0) * H, hw = (w * c + h * s) / 2, hh = (w * s + h * c) / 2;
  const cx = ((box.x0 + box.x1) / 2) * W, cy = ((box.y0 + box.y1) / 2) * H, m = Math.min(W, H) * 0.015;
  const fit = (v, half, size) => (half * 2 > size - 2 * m ? size / 2 : Math.min(Math.max(v, half + m), size - half - m));
  return [(fit(cx, hw, W) - cx) / W, (fit(cy, hh, H) - cy) / H];
}
const unionBox = (parts) => parts.length ? { x0: Math.min(...parts.map((p) => p.x0)), y0: Math.min(...parts.map((p) => p.y0)),
  x1: Math.max(...parts.map((p) => p.x1)), y1: Math.max(...parts.map((p) => p.y1)) } : null;
/* A layout word turned to a (as drawn, its own slant included), kept on the poster */
function turnWord(cur, k, a) {
  const parts = wordsList.filter((x) => x.key === k), r0 = parts[0]?.r0 || 0, [dx, dy] = keepOn(unionBox(parts), a);
  setMove(cur, k, (m) => { m.r = normAngle(a - r0); m.x += dx; m.y += dy; });
}
/* A text on the photo turned to a, kept on the picture */
function turnText(cur, i, a) {
  const el = $(`#texts .tx[data-i="${i}"]`), f = $("#frame"), t = slotById(cur.id).edits.texts[i];
  let dx = 0, dy = 0;
  if (el && f) {
    const w = el.offsetWidth / f.clientWidth, h = el.offsetHeight / f.clientHeight;
    [dx, dy] = keepOn({ x0: t.x - w / 2, x1: t.x + w / 2, y0: t.y - h / 2, y1: t.y + h / 2 }, a);
  }
  changeEdits(slotById(cur.id), (e) => { const x = e.texts[i]; if (a) x.angle = a; else delete x.angle; x.x += dx; x.y += dy; });
}
/* The round handle that turns a word or piece: above it, or below it when it is at the very top */
const turnHandle = (top) => `<span class="pc-r${top < 0.08 ? " below" : ""}" title="Drag to turn it · Shift: 15° steps"></span>`;
const fmtVal = (k, v, unit) => k === "strength" ? `${Math.round(v)}%` : unit === "pct" ? `${Math.round(v * 100)}%` : unit === "deg" ? `${Math.round(v)}°`
  : `${v > 0 ? "+" : ""}${(+v).toFixed(2)}${unit ? " " + unit : ""}`;

let editSig = "";
const paneSignature = (cur) => `${cur.id}:${cur.ver}:${familyOf(cur.edits?.poster) ? familySlots(familyOf(cur.edits.poster)).map((s) => s.id + s.state).join(",") : ""}:${st.photos.find((p) => p.id === cur.photo)?.edited}:${st.photos.length}:${st.areaSel}:${st.textSel}:${hist.undo.length}:${hist.redo.length}:${st.tool}`;

function renderEdit(cur) {
  if (cur.state !== "done") {  // a photo being got ready to edit: said plainly, right here
    const pane = $("#pane-edit"), photo = st.photos.find((p) => p.id === cur.photo);
    const sig2 = `opening:${cur.id}:${cur.state}:${cur.pct}`;
    if (editSig === sig2) return;
    editSig = sig2;
    pane.innerHTML = `<div class="opening"><div class="spin" style="width:26px;height:26px"></div>
      <h3>Getting ${esc(photo?.name || "the photo")} ready to edit</h3>
      <p>Finding the players and tracing them, once per photo: ${cur.pct ? `${cur.pct}% · ` : ""}usually about 20 seconds. The editor opens by itself.</p>
      <p class="notes">Meanwhile you can pick looks for it in the Looks tab.</p></div>`;
    return;
  }
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
    <output for="e-${k}">${fmtVal(k, val(k), unit)}</output><input type="range" class="${cls || ""}" id="e-${k}" data-k="${k}" data-unit="${unit || ""}" data-def="${ADJ_DEFAULT[k] ?? 0}" min="${min}" max="${max}" step="${stp}" value="${val(k)}"></div>`;
  const tool = (id, ic, label, tip) => `<button class="tool${st.tool === id || (id === "cutout" && st.fixing) ? " on" : ""}" data-tool="${id}" title="${esc(tip)}">${icon(ic)}<span>${label}</span></button>`;
  // what you are working on (a poster, text, a logo, a part) sits right under the tools;
  // the light and color sliders fold away meanwhile (open them any time)
  const parts = {
    area: areas.length ? `<div class="section"><h3>Parts adjusted</h3>${areas.map((ar, i) => `<div class="item${st.areaSel === i ? " on" : ""}" data-area="${i}">
      <div class="item-head"><button class="item-name" data-pick-area="${i}">${icon("target")} Part ${i + 1}</button><button class="icon-btn" data-del-area="${i}" title="Remove this adjustment">${icon("trash")}</button></div>
      ${st.areaSel === i ? [["exposure", "Brightness", -2, 2, 0.05, "ev"], ["warmth", "Warmth", -1.5, 1.5, 0.05, "", "warm"], ["saturation", "Saturation", -1, 1, 0.05]].map(([k, label, min, max, stp, unit, cls]) =>
        `<div class="slider"><label>${label}</label><output>${fmtVal(k, ar[k] || 0, unit)}</output><input type="range" class="${cls || ""}" data-area-k="${k}" data-i="${i}" data-unit="${unit || ""}" min="${min}" max="${max}" step="${stp}" value="${ar[k] || 0}"></div>`).join("") : ""}
      </div>`).join("")}</div>` : "",
    background: st.tool === "background" || e.background ? backgroundSection(e) : "",
    poster: st.tool === "poster" || e.poster ? posterSection(e) : "",
    text: texts.length ? `<div class="section"><h3>Text</h3>${texts.map((t, i) => `<div class="item${st.textSel === i ? " on" : ""}" data-text="${i}">
      <div class="item-head"><textarea class="field text-in" rows="1" data-ti="${i}" placeholder="Type here">${esc(t.text)}</textarea><button class="icon-btn" data-del-text="${i}" title="Remove this text">${icon("trash")}</button></div>
      ${st.textSel === i ? `<div class="seg full small" data-style-of="${i}">${TEXT_STYLES.map(([v, l]) => `<button data-v="${v}" class="${t.style === v ? "on" : ""}">${l}</button>`).join("")}</div>
      <div class="slider"><label>Size</label><output>${Math.round(t.size * 100)}</output><input type="range" data-size-of="${i}" min="0.02" max="0.2" step="0.005" value="${t.size}"></div>
      ${fontPicker(t.font, "Style's own", `data-font-of="${i}"`)}
      ${angleControl(t.angle, `data-angle-of="${i}"`)}
      <div class="swatches" data-color-of="${i}">${TEXT_COLORS.map((c) => `<button data-v="${c}" class="${t.color === c ? "on" : ""}" style="background:${c}" aria-label="${c}"></button>`).join("")}</div>` : ""}
      </div>`).join("")}</div>` : "",
    logo: st.tool === "logo" || (e.logos || []).length ? logoSection(e) : "",
  };
  const design = ["background", "poster", "text", "logo", "area"].includes(st.tool) && parts[st.tool] ? st.tool : null;
  const group = (g, title, body, open = !design, extra = "") => `<details class="group" data-g="${g}" ${(st.openGroups[g] ?? open) ? "open" : ""}>
    <summary><h3>${title}</h3>${extra}${icon("chev")}</summary><div class="group-body">${body}</div></details>`;
  const used = (keys) => keys.filter((k) => a[k] !== (ADJ_DEFAULT[k] ?? 0) && !(k.endsWith("_hue"))).length;
  const count = (n) => n ? `<span class="adv-n" title="${plural(n, "setting")} in use">${n}</span>` : "";
  const mixC = st.mixColor || "green";
  const advBody = {
    mixer: `<div class="mix-chips" role="group" aria-label="Color to change">${MIX_COLORS.map(([c, l, hex]) => `<button data-mix="${c}" class="${c === mixC ? "on" : ""}${used([`mix_${c}_h`, `mix_${c}_s`, `mix_${c}_l`]) ? " set" : ""}"
        style="--chip:${hex}" title="${l}${used([`mix_${c}_h`, `mix_${c}_s`, `mix_${c}_l`]) ? " (changed)" : ""}" aria-label="${l}"></button>`).join("")}</div>
      ${[["h", "Hue"], ["s", "Saturation"], ["l", "Luminance"]].map(([x, l]) => sliderRow([`mix_${mixC}_${x}`, `${MIX_COLORS.find((m) => m[0] === mixC)[1]} ${l.toLowerCase()}`, -1, 1, 0.05])).join("")}
      <div class="kit-pop"><span class="sub-label">Kit color pop</span>
        <div class="inline"><span class="kit-swatch${a.kit_color ? "" : " none"}" style="${a.kit_color ? `background:${esc(a.kit_color)}` : ""}" title="${a.kit_color ? esc(a.kit_color) : "No kit color picked yet"}"></span>
        <button class="btn small" id="e-kit-pick" title="Click the kit on the picture to pick its color">${icon("pipette")} ${a.kit_color ? "Pick again" : "Pick the kit color"}</button>
        ${a.kit_color ? `<button class="icon-btn" id="e-kit-clear" title="Forget the kit color">${icon("x")}</button>` : ""}</div>
        ${a.kit_color ? sliderRow(["kit_pop", "Pop", 0, 1, 0.05, "pct"]) : ""}</div>`,
    grading: GRADES.map(([g, l]) => `<div class="grade-row">${sliderRow([`grade_${g}_hue`, `${l} color`, 0, 360, 1, "deg", "hue"])}${sliderRow([`grade_${g}`, l, 0, 1, 0.05, "pct"])}</div>`).join(""),
  };
  const advanced = group("advanced", "Advanced",
    ADVANCED.map(([g, title, rows]) => `<details class="group sub" data-g="adv-${g}" ${st.openGroups[`adv-${g}`] ? "open" : ""}>
      <summary><h3>${title}</h3>${count(used(ADV_KEYS[g]))}${icon("chev")}</summary><div class="group-body">${rows ? rows.map(sliderRow).join("") : advBody[g]}</div></details>`).join(""),
    false, count(used(Object.values(ADV_KEYS).flat())));
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
      ${tool("poster", "layout", "Poster", "Make it a social post: Game Day, Spotlight, MVP, Goal, Matchday, Champions and more")}
      ${tool("background", "image", "Background", "Put the player in front of a new background (or right-click the picture)")}
      ${tool("cutout", "wand", "Cut-out", "Fix what counts as the player: click, paint, refine hair")}
    </div>
    ${cur.look === "Original" ? `<button class="btn wide on-top" id="e-on-top" ${off(!photo?.edited, "Edit the photo first (light, color, crop, or remove something), then put a look on top of it. Example: lower the player's light, then add Stadium Lights for a night shot.")} title="Pick looks to go on top of this edit (they keep your light, color, crop and removals)">${icon("layers")} Add a look on top of this edit</button>` : ""}
    ${design ? `<div class="working">${parts[design]}</div>` : ""}
    ${group("light", "Light", SLIDERS.light.map(sliderRow).join(""))}
    ${group("color", "Color", SLIDERS.color.map(sliderRow).join(""))}
    ${group("look", "The look", SLIDERS.look.filter(([k]) => k !== "strength" || cur.look !== "Original").map(sliderRow).join("")
       + (cur.look === "Original" ? `<p class="notes">Look strength shows once a look is on this photo (Original is the photo itself, so there's nothing to fade).</p>` : "") + `
      <label class="toggle"><input type="checkbox" id="e-fill" ${a.auto_fill ? "checked" : ""}><span><b>Auto fill light</b><small>Lifts a backlit or shaded player</small></span></label>`)}
    ${advanced}
    ${Object.entries(parts).filter(([k, html]) => k !== design && html).map(([, html]) => html).join("")}
    <div class="inline"><button class="btn" id="e-reset" title="Back to the look as it was made">Reset all</button>
      ${same > 1 ? `<button class="btn" id="e-all" style="flex:1" title="These light, color and look settings on every picture in this look">${icon("copy")} Use on all ${same}</button>` : ""}</div>
    <div class="section"><h3>This photo</h3><div class="actions">
      ${e.removals?.length ? `<p class="notes">${plural(e.removals.length, "thing")} removed from this look · ⌘Z puts the last one back</p>` : ""}
      ${st.photos.length > 1 ? `<button class="btn" id="e-useall">${icon("layers")} Use this look on all ${st.photos.length} photos</button>
      <button class="btn" id="e-match">${icon("sun")} Match every photo's light to this one</button>` : ""}
      ${anyMatched ? `<button class="btn ghost" id="e-unmatch">${icon("undo")} Undo matching</button>` : ""}
    </div></div>
    <div class="section"><h3>Save as a preset</h3><div class="inline"><input class="field" id="e-name" placeholder="Name it, then Save" value="${esc(st.presetName || "")}">
      <button class="btn" id="e-save">${icon("save")} Save</button></div>
      ${e.poster || texts.length || (e.logos || []).length ? `<label class="check-row"><input type="checkbox" id="e-design" checked>
        <span>Keep the ${[e.poster && "poster", texts.length && "text", (e.logos || []).length && "logo"].filter(Boolean).join(", ")} in it<small>Make it on any photo: the same design, with that photo in it</small></span></label>` : ""}</div>
    ${cur.notes?.length ? `<p class="notes">${esc(cur.notes.join("; "))}</p>` : ""}`;
  paintIcons(pane);
  pane.querySelectorAll("details.group").forEach((d) => d.ontoggle = () => { st.openGroups[d.dataset.g] = d.open; });
  if (st.focusField && Date.now() < st.focusField.until) { const k = st.focusField.k; requestAnimationFrame(() => focusPosterField(k)); }
  bindEditPane(cur, pane);
}

function bindEditPane(cur, pane) {
  const vals = { ...cur.adjust };
  let dragSnap = null;
  $("#e-undo", pane).onclick = undo;
  $("#e-on-top", pane)?.addEventListener("click", () => {  // pick looks for the photo as edited
    st.fromEdits = true; store.set("fromEdits", true);
    st.activePhoto = cur.photo; st.scope = "one"; st.tab = "looks"; renderTabs();
    toast("Pick looks, then Make: they go on top of your edit", { small: "\"From: My edit\" is on in the Looks panel" });
  });
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
    r.ondblclick = () => { r.value = r.dataset.def; r.oninput(); commitDrag(); };
  });
  const commitDrag = () => {
    if (!dragSnap) return;
    const before = dragSnap;
    dragSnap = null;
    afterSend(() => { const s = slotById(cur.id); pushHist({ type: "slot", sid: cur.id, before, after: snapshot(s) }); });
  };
  pane.querySelectorAll("[data-mix]").forEach((b) => b.onclick = () => { st.mixColor = b.dataset.mix; editSig = ""; renderEdit(slotById(cur.id)); });
  const setAdj = (change) => { const before = snapshot(slotById(cur.id)); change(vals); sendAdjust(cur.id, vals);
    afterSend(() => pushHist({ type: "slot", sid: cur.id, before, after: snapshot(slotById(cur.id)) })); };
  $("#e-kit-pick", pane)?.addEventListener("click", () => { const keep = { ...st.openGroups }; setTool("kitpick"); st.openGroups = keep; editSig = ""; render(); });
  $("#e-kit-clear", pane)?.addEventListener("click", () => setAdj((v) => { v.kit_color = ""; v.kit_pop = 0; }));
  $("#e-fill", pane).onchange = (ev) => { const before = snapshot(slotById(cur.id)); vals.auto_fill = ev.target.checked; sendAdjust(cur.id, vals);
    afterSend(() => pushHist({ type: "slot", sid: cur.id, before, after: snapshot(slotById(cur.id)) })); };
  $("#e-reset", pane).onclick = async () => {
    const before = snapshot(cur);
    const s = await api(`/api/slots/${cur.id}/edit`, { adjust: {}, edits: {} });
    pushHist({ type: "slot", sid: cur.id, before, after: snapshot(s) });
    st.areaSel = null; st.textSel = null; updateSlot(s);
  };
  $("#e-all", pane)?.addEventListener("click", async () => {
    const same = st.slots.filter((x) => x.state === "done" && x.look === cur.look);
    const before = new Map(same.map((x) => [x.id, snapshot(x)]));
    const r = await api(`/api/slots/${cur.id}/adjust_look`, vals);
    await refresh();
    pushHist({ type: "multi", pid: null, items: same.filter((x) => slotById(x.id)).map((x) => ({ sid: x.id, before: before.get(x.id), after: snapshot(slotById(x.id)) })) });
    toast(`Used on all ${r.count} “${cur.look}” pictures`, { small: "⌘Z undoes it on all of them" });
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
  const nameBox = $("#e-name", pane);
  nameBox.oninput = () => { st.presetName = nameBox.value; };  // (kept while the panel is drawn again)
  nameBox.onkeydown = (ev) => { if (ev.key === "Enter") { ev.preventDefault(); $("#e-save", pane).click(); } };
  $("#e-save", pane).onclick = async () => {
    const name = nameBox.value.trim();
    if (!name) { nameBox.focus(); toast("Type a name for the preset first", { small: "Then press Save (or Return)" }); return; }
    const design = !!$("#e-design", pane)?.checked;
    await api(`/api/slots/${cur.id}/save_preset`, { name, design });
    st.presetName = "";
    await loadLooks();
    st.filter = "Mine"; store.set("filter", "Mine"); renderLooks(true);  // (the Looks tab opens on your presets)
    toast(`Saved the preset “${name}”`, { small: `It's in Looks › Mine${design ? ", with its poster: pick it and Make on any photo" : ""}` });
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
      saveSoon(cur.id, e, 120);
    };
    r.onchange = () => { areaSnap = null; };
  });
  bindLogoSection(cur, pane);
  bindPosterSection(cur, pane);
  bindBackgroundSection(cur, pane);
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
      saveSoon(cur.id, e, 300);
    };
    ta.onblur = () => { snap = null; closeBurst(cur.id); };
  });
  pane.querySelectorAll("[data-del-text]").forEach((b) => b.onclick = () => {
    const i = +b.dataset.delText; st.textSel = null;
    changeEdits(slotById(cur.id), (e) => { e.texts.splice(i, 1); });
  });
  pane.querySelectorAll("[data-style-of] button").forEach((b) => b.onclick = () => {
    const i = +b.parentElement.dataset.styleOf;
    changeEdits(slotById(cur.id), (e) => { e.texts[i].style = b.dataset.v; });
  });
  pane.querySelectorAll("[data-font-of] button").forEach((b) => b.onclick = () => {
    const i = +b.parentElement.dataset.fontOf;
    changeEdits(slotById(cur.id), (e) => { if (b.dataset.v) e.texts[i].font = b.dataset.v; else delete e.texts[i].font; });
  });
  pane.querySelectorAll("[data-angle-of]").forEach((box) => {
    const i = +box.dataset.angleOf;
    bindAngle(box.parentElement, () => slotById(cur.id).edits.texts[i].angle || 0,
      (a) => { const el = $(`#texts .tx[data-i="${i}"]`); if (el) el.style.transform = `translate(-50%, -50%) rotate(${a}deg)`; },
      (a) => turnText(cur, i, a));
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
      saveSoon(cur.id, e, 200);
    };
    r.onchange = () => { snap = null; };
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
  if (tool === "crop" && cur.edits?.poster && st.tool !== "crop") {  // on a poster: move the photo in it, as you see it
    toast("On a poster, drag the photo to move it", { small: "Photo zoom is in the Poster panel. Crop works on pictures without a poster." });
    tool = "poster";
    if (st.tool === "poster") return;
  }
  if (tool === "cutout") { st.fixing = !st.fixing; st.tool = null; }
  else { st.tool = st.tool === tool ? null : tool; st.fixing = false; }
  st.compare = false; st.zoom.on = false; st.view = "single"; st.cropDraft = null; st.openGroups = {};
  st.brush.strokes = []; st.brush.points = []; st.brush.preview = null;
  if (tool === "text" && st.tool === "text" && !(cur.edits?.texts || []).length) { addText(cur); }
  if (tool === "poster" && st.tool === "poster" && !cur.edits?.poster) {  // a first layout, to start from
    changeEdits(cur, (ed) => { ed.poster = { template: "gameday", shape: "post", color: "#1f2a44", logo: st.kit?.[0]?.id || "" }; });
  }
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
    kitpick: `<span class="title"><b>Kit color pop</b><span>Click the kit (a shirt, the shorts) to pick its color</span></span><span class="sep"></span><button data-done>Cancel</button>`,
    wb: `<span class="title"><b>White balance</b><span>Click something that should be white or gray</span></span><span class="sep"></span><button data-done>Cancel</button>`,
    text: `<span class="title"><b>Text</b><span>Drag to place it · type in the panel</span></span><span class="sep"></span><button data-add-text>${icon("plus")} Add text</button><button data-done>Done</button>`,
    logo: `<span class="title"><b>Logo</b><span>Pick one in the panel · drag it to place it</span></span><span class="sep"></span><button data-done>Done</button>`,
    background: `<span class="title"><b>Background</b><span>Pick one in the panel · right-click the picture for more</span></span><span class="sep"></span><button data-done>Done</button>`,
    poster: `<span class="title"><b>Poster</b><span>${cur.edits?.poster?.template === "custom" ? "Drag a piece to move it · its corner resizes it · arrows nudge" : "Click a word to change it · or pick a layout in the panel"}</span></span><span class="sep"></span><button data-done>Done</button>`,
  }[t];
  v.innerHTML = `<div class="frame tool-${t}" id="frame"><div class="layer"><img class="after" src="${src}" alt="" draggable="false" data-base="${base ? "" : `${cur.width}x${cur.height}`}"></div>
      ${t === "text" || t === "logo" ? `<div class="texts" id="texts"></div>` : ""}</div>
    <div class="fixbar toolbar below">${histBtns()}${bar}</div>`;
  paintIcons(v);
  if (base) fitFrame(cur.base_width, cur.base_height); else fitFrame(cur.width, cur.height);
  if (t === "text" || t === "logo") { paintTexts(cur); bindTexts(cur); }
  if (t === "poster") { paintWords(cur); bindPhotoDrag(cur); }
  watchPicture(cur);
  $("[data-done]", v).onclick = () => { if (t !== "kitpick") return setTool(t); st.tool = null; viewerSig = ""; editSig = ""; render(); };
  $("[data-add-text]", v)?.addEventListener("click", () => addText(slotById(cur.id)));
  const f = $("#frame");
  const at = (e) => { const r = f.getBoundingClientRect(); return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height }; };
  if (t === "area") f.onclick = async (e) => {
    const p = at(e), s = slotById(cur.id);
    st.areaSel = (s.edits?.areas || []).length;
    const tk = toast("Finding that part…", { sticky: true, spin: true });
    try { await changeEdits(s, (ed) => { (ed.areas ||= []).push({ x: p.x, y: p.y, exposure: 0.3, warmth: 0, saturation: 0 }); }); } finally { tk.close(); }
  };
  if (t === "kitpick") f.onclick = (e) => {
    const p = at(e), img = $("img.after", f), s = slotById(cur.id), c = document.createElement("canvas");
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    const g = c.getContext("2d", { willReadFrequently: true }); g.drawImage(img, 0, 0);
    const r = Math.max(2, Math.round(c.width / 300)), cx = Math.round(p.x * c.width), cy = Math.round(p.y * c.height);
    const d = g.getImageData(Math.max(0, cx - r), Math.max(0, cy - r), 2 * r + 1, 2 * r + 1).data;
    let R = 0, G = 0, B = 0, n = 0;
    for (let i = 0; i < d.length; i += 4) { R += d[i]; G += d[i + 1]; B += d[i + 2]; n++; }
    const hex = "#" + [R, G, B].map((x) => Math.round(x / n).toString(16).padStart(2, "0")).join("");
    const mx = Math.max(R, G, B) / n, mn = Math.min(R, G, B) / n;
    // gray, white or black: no kit color to pick (a dark navy still counts)
    if (mx < 14 || (mx - mn) / mx < 0.15) { toast("That spot has hardly any color", { small: "Click a colored part of the kit: a red shirt, blue shorts." }); return; }
    const before = snapshot(s), adj = { ...s.adjust, kit_color: hex, kit_pop: s.adjust.kit_pop || 0.5 };
    st.tool = null; viewerSig = ""; editSig = ""; render();
    sendAdjust(cur.id, adj);
    afterSend(() => pushHist({ type: "slot", sid: cur.id, before, after: snapshot(slotById(cur.id)) }));
    toast("Kit color picked", { small: "Pop sets how much richer it gets" });
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
    style="left:${t.x * 100}%;top:${t.y * 100}%;font-size:calc(var(--fw) * ${t.size});color:${esc(t.color)};${fontCss(t.font)}${t.angle ? `transform:translate(-50%, -50%) rotate(${t.angle}deg);` : ""}">${esc(t.text)}${st.tool === "text" && st.textSel === i ? turnHandle(t.y - t.size) : ""}</div>`).join("")
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
/* Click what you built on the picture (a text, a logo, the poster) and its tool opens with it chosen. */
function bindPicks(cur) {
  const box = $("#texts"), f = $("#frame");
  if (!box || !f) return;
  box.classList.add("pickable");
  box.onpointerdown = (e) => {
    const tx = e.target.closest(".tx"), lg = e.target.closest(".lg");
    if (!tx && !lg) return;
    e.preventDefault(); e.stopPropagation();
    openPart(cur, tx ? "text" : "logo", +(tx ? tx.dataset.i : lg.dataset.li));
  };
  paintWords(cur);
  if (cur.edits?.poster) {  // the poster's words are part of the picture: a click on it opens the poster
    f.classList.add("pickable-poster");
    let wait = null;
    f.onclick = (e) => {
      if (st.zoom.on || st.compare || e.target.closest(".tx, .lg, .tag, button, .pw")) return;
      if (st.focusField && Date.now() < st.focusField.until) return;  // (a word was just clicked)
      clearTimeout(wait);
      wait = setTimeout(() => openPart(cur, "poster"), 260);  // (a double-click zooms instead)
    };
    f.addEventListener("dblclick", () => clearTimeout(wait));
  }
}
/* A layout word's own place, size, font and angle (the poster's moves) */
function setMove(cur, k, fn) {
  changeEdits(slotById(cur.id), (ed) => {
    const m = { x: 0, y: 0, s: 1, ...((ed.poster.moves || {})[k] || {}) };
    fn(m);
    if (!m.r) delete m.r;
    if (!m.f) delete m.f;
    ed.poster.moves = { ...(ed.poster.moves || {}), [k]: m };
  });
}
/* The poster's words on the picture: click one to type over it (its box in the panel opens, selected). */
let wordsKey = "", wordsList = [], wordsTurn = 0;
async function paintWords(cur) {
  const turn = ++wordsTurn;  // only the latest call draws them
  const f = $("#frame"), p = cur.edits?.poster;
  f?.querySelectorAll(".pwords").forEach((x) => x.remove());
  if (!f || !p || st.compare || st.zoom.on || st.fixing) return;
  const key = JSON.stringify(p);
  if (key !== wordsKey) {
    try { wordsList = (await api("/api/poster/words", { poster: p, logo: !!p.logo })).words; wordsKey = key; } catch { return; }
  }
  if (turn !== wordsTurn || !f.isConnected || slotById(st.current)?.id !== cur.id) return;
  f.querySelectorAll(".pwords").forEach((x) => x.remove());
  if (p.template === "custom") return paintPieces(cur, f, wordsList);
  const box = document.createElement("div");
  box.className = "pwords" + (st.tool === "poster" ? " live" : "");
  const label = (k) => (POSTER_FIELDS[p.template] || []).find(([x]) => x === k)?.[1] || "Text";
  const place = (w) => `left:${w.x0 * 100}%;top:${w.y0 * 100}%;width:${(w.x1 - w.x0) * 100}%;height:${(w.y1 - w.y0) * 100}%`;
  box.classList.add("pieces-layer");
  const live = st.tool === "poster";
  const turnOrigin = (w) => {  // a word in parts turns around the whole word's middle (as the app draws it)
    const parts = wordsList.filter((x) => x.key === w.key);
    const mx = (Math.min(...parts.map((x) => x.x0)) + Math.max(...parts.map((x) => x.x1))) / 2;
    const my = (Math.min(...parts.map((x) => x.y0)) + Math.max(...parts.map((x) => x.y1))) / 2;
    return `${((mx - w.x0) / (w.x1 - w.x0)) * 100}% ${((my - w.y0) / (w.y1 - w.y0)) * 100}%`;
  };
  box.innerHTML = wordsList.filter((w) => !w.key.startsWith("el:")).map((w) => w.key === "logo"
    ? `<div class="pc pc-logo${st.pieceSel === "logo" ? " sel" : ""}" data-pc="logo" title="Drag the logo anywhere · its corner resizes it · Delete takes it off" style="${place(w)}">${live ? `<span class="pc-h"></span>` : ""}</div>`
    : `<div class="pc pc-word${st.pieceSel === "w:" + w.key ? " sel" : ""}" data-pc="w:${w.key}" data-pk="${w.key}" role="button" aria-label="${esc(label(w.key))}: click to type, drag to move, its round handle turns it" style="${place(w)}${w.r ? `;rotate:${w.r}deg;transform-origin:${turnOrigin(w)}` : ""}">${live && st.pieceSel === "w:" + w.key && wordsList.find((x) => x.key === w.key) === w ? `<span class="pc-h"></span>${turnHandle(w.y0)}` : ""}</div>`).join("");
  f.appendChild(box);
  // a word: click to type it, drag to move it, its corner to make it bigger or smaller
  box.querySelectorAll(".pc-word").forEach((el) => dragPiece(el, f, cur, (dx, dy, resize, kx, ky, r) => {
    const k = el.dataset.pk;
    changeEdits(slotById(cur.id), (ed) => {
      const m = { x: 0, y: 0, s: 1, ...((ed.poster.moves || {})[k] || {}) };
      if (resize) {  // grown from its top left corner: its middle moves by half the growth
        const w = wordsList.find((x) => x.key === k), sc = Math.max(kx, ky);
        m.s *= sc;
        if (w) { m.x += (w.x1 - w.x0) * (sc - 1) / 2; m.y += (w.y1 - w.y0) * (sc - 1) / 2; }
      } else { m.x += dx / r.width; m.y += dy / r.height; }
      ed.poster.moves = { ...(ed.poster.moves || {}), [k]: m };
    });
  }, () => {  // only a click: its box in the panel (and its style), ready to type
    const k = el.dataset.pk;
    st.focusField = { k, until: Date.now() + 2500 };
    if (st.stylePk !== k) { st.stylePk = k; st.colorPk = null; if (st.tool === "poster") { editSig = ""; renderTabs(); } }
    if (st.tool !== "poster") openPart(cur, "poster");
    focusPosterField(k);
  }, (a) => turnWord(cur, el.dataset.pk, a)));
  box.querySelectorAll(".pc-word").forEach((el) => el.oncontextmenu = (e) => wordMenu(e, slotById(cur.id), el.dataset.pk));
  paintPieces(cur, f, wordsList);  // (pieces added on top of the layout: stripes, text…)
  box.querySelectorAll(".pc-logo").forEach((el) => dragPiece(el, f, cur, (dx, dy, resize, kx, ky, r) => {
    const w = wordsList.find((x) => x.key === "logo");
    if (!w) return;
    changeEdits(slotById(cur.id), (ed) => {  // the logo where you put it (its size by its width)
      const cx = (w.x0 + w.x1) / 2 + dx / r.width, cy = (w.y0 + w.y1) / 2 + dy / r.height;
      const size = (w.x1 - w.x0) * (resize ? Math.max(kx, ky) : 1);
      ed.poster.logo_at = { x: resize ? w.x0 + size / 2 : cx, y: resize ? w.y0 + (w.y1 - w.y0) * Math.max(kx, ky) / 2 : cy, size };
    }, { keepPane: false });
  }));
  box.querySelectorAll(".pw").forEach((b) => b.onpointerdown = (e) => {  // (on press: the layer may be drawn again before release)
    e.preventDefault(); e.stopPropagation();
    const k = b.dataset.pk;
    st.focusField = { k, until: Date.now() + 2500 };  // (kept through the panel being drawn again)
    if (st.tool !== "poster") openPart(cur, "poster");
    focusPosterField(k);
  });
}
document.addEventListener("input", (e) => { if (e.target.classList?.contains("poster-in")) st.focusField = null; });
function focusPosterField(k) {
  const inp = $(`.poster-in[data-pk="${k}"]`);
  if (!inp) return;
  inp.scrollIntoView({ block: "center", behavior: "smooth" });
  inp.focus(); inp.select();
  inp.closest(".fld")?.classList.add("flash"); setTimeout(() => inp.closest(".fld")?.classList.remove("flash"), 900);
}
function openPart(cur, tool, i) {
  if (tool === "text") st.textSel = i;
  if (tool === "logo") st.logoSel = i;
  st.tool = null;
  setTool(tool);
  if (tool === "text") setTimeout(() => { const ta = $(`.text-in[data-ti="${i}"]`); ta?.focus(); ta?.select(); }, 80);
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
    if (e.target.closest(".pc-r")) {  // its round handle: turn it
      const a0 = slotById(cur.id).edits.texts[i].angle || 0;
      return rotateDrag(el, e, a0, (a) => { el.style.transform = `translate(-50%, -50%) rotate(${a}deg)`; },
        (a) => turnText(cur, i, a));
    }
    if (st.textSel !== i) { st.textSel = i; editSig = ""; renderTabs(); box.querySelectorAll(".tx").forEach((x) => x.classList.toggle("sel", +x.dataset.i === i)); box.querySelectorAll(".pc-r").forEach((x) => x.remove()); const tt = slotById(cur.id).edits.texts[i]; el.insertAdjacentHTML("beforeend", turnHandle(tt.y - tt.size)); }
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

// Posters ---------------------------------------------------------------------------------------------
const POSTERS = [["gameday", "Game Day", "The player in front of a big title"], ["spotlight", "Spotlight", "The player breaking out of a card, their number on a badge"],
  ["final", "Final Score", "The score on a clean panel"], ["mvp", "MVP", "A cover title behind the player"],
  ["name", "Name Stack", "Their name three times, big, behind them"], ["goal", "Goal", "GOAL behind the scorer, their name and the minute"],
  ["teamcolor", "Team Color", "The background in your team color, the player in full color"],
  ["matchday", "Matchday", "The opponent on a team-color band, when and where below"],
  ["champions", "Champions", "Gold title behind the team, the event below"],
  ["jersey", "Jersey Number", "Their number, giant, in the team color behind them"],
  ["cover", "Cover Story", "A magazine cover: the title behind their head, a headline below"],
  ["split", "Diagonal Split", "A team-color panel on the diagonal with their name, their number big"],
  ["card", "Player Card", "A collector's card: a team-color frame, a gold rule and a nameplate"],
  ["cinematic", "Cinematic", "Film letterbox bars, the name between thin gold rules"],
  ["banner", "Stadium Banner ★", "The team name huge in chrome over a stadium glow, the player in front, their name in script"],
  ["smoke", "Smoke Burst ★", "Team-color powder smoke and light slashes behind the player, the name big below"],
  ["featured", "Featured Split ★", "Half black-and-white texture, half team color; a script title, a brushed number and a role"],
  ["storm", "Storm Night ★", "A storm sky with a floodlight breaking through, the name glowing below"],
  ["collector", "Collector's Edition ★", "A magazine cover: chrome title, a script badge and a ribbon across the corner"],
  ["custom", "Custom ✦", "Your own: move, resize and restyle every piece (starts from the layout you are on)"]];
const POSTER_FIELDS = { gameday: [["title", "Title"], ["line", "Line under it"]], spotlight: [["title", "Name"], ["line", "Position"], ["number", "Number"]],
  final: [["title", "Above the score"], ["home", "Your team"], ["home_score", "Their score"], ["away", "The other team"], ["away_score", "Its score"]],
  mvp: [["title", "Title"], ["line", "Line under it"]],
  name: [["title", "Name"], ["line", "Line under it"]], goal: [["title", "Title"], ["name", "Scorer"], ["minute", "Minute"]],
  teamcolor: [["title", "Name or title"], ["line", "Line under it"]],
  matchday: [["title", "Small title"], ["away", "Opponent"], ["line", "When and where"]],
  champions: [["title", "Title"], ["line", "The event"]],
  jersey: [["number", "Number"], ["title", "Name"], ["line", "Line under it"]],
  cover: [["title", "Magazine title"], ["line", "Issue line"], ["name", "Headline"], ["away", "Line under the headline"]],
  split: [["title", "Name"], ["line", "Line under it"], ["number", "Number"]],
  card: [["title", "Name"], ["line", "Position or year"], ["number", "Number"]],
  cinematic: [["title", "Name"], ["line", "Line under it"]],
  banner: [["line", "Club (small, above)"], ["title", "Team name"], ["name", "Player's name (script)"]],
  smoke: [["line", "Club (small, above)"], ["title", "Team name"], ["name", "Player's name (first last)"]],
  featured: [["line", "Year"], ["title", "Script word"], ["away", "Small script word"], ["number", "Number"], ["home", "Role"], ["name", "Player's name"]],
  storm: [["title", "Name"], ["line", "Line under it"], ["number", "Number (faint, behind)"]],
  collector: [["title", "Magazine title"], ["line", "Issue line"], ["minute", "Year"], ["away", "Script badge"], ["home", "Ribbon"]],
  fillband: [["title", "Name"], ["line", "Line under it"]], lowerthird: [["title", "Name"], ["line", "Role or team"]],
  knockout: [["title", "Cut-out word (its color is the panel's)"], ["line", "Line under it"]], sidelabel: [["title", "Name (standing up)"], ["line", "Small line"]],
  cornertag: [["title", "Corner tag"], ["name", "Name"], ["line", "Small line"]], outlinestack: [["title", "First line (outlined)"], ["name", "Second line (solid)"], ["line", "Small line"]],
  frosted: [["title", "Name"], ["line", "Line under it"]] };
/* Clean overlays: the photo as it is, the words on a quiet fill */
const CLEAN_POSTERS = [["fillband", "Fill Band", "A see-through dark band across the lower third, the name big and clean in it"],
  ["lowerthird", "Lower Third", "A broadcast name plate in the team color, a slim strip with the role under it"],
  ["knockout", "Knockout", "A solid panel with the name cut out of it: the photo shows through the letters"],
  ["sidelabel", "Side Label", "The name standing up along the left edge on a slim team-color strip"],
  ["cornertag", "Corner Tag", "A small team-color tag in the corner, the name clean and large at the bottom"],
  ["outlinestack", "Outline Stack", "Two lines at the bottom: the first outlined, the second solid"],
  ["frosted", "Frosted Panel", "A frosted-glass panel over the photo with the name and a line"]];
const POSTER_SHAPES = [["post", "Post", "Instagram post, 4:5", 4, 5], ["square", "Square", "Instagram or Facebook square, 1:1", 1, 1],
  ["story", "Story", "Instagram or TikTok story or reel, 9:16", 9, 16], ["wide", "Wide", "YouTube, X or Facebook, 16:9", 16, 9]];
const WORD_COLORS = ["#ffffff", "#111111", "#d4af37", "#c8102e", "#0b3d91", "#1f2a44", "#0f5f3a", "#d97706", "#5b2a86", "#7dd3fc"];
const TEAM_COLORS = ["#1f2a44", "#0b3d91", "#b3121a", "#0f5f3a", "#5b2a86", "#d97706", "#111111"];
function posterSection(e) {
  const p = e.poster;
  const cur = slotById(st.current);
  return `<div class="section"><h3>Poster</h3>
    ${p && cur ? inThisPoster(cur) : ""}
    ${p && cur ? teamSection(cur, p) : ""}
    ${(st.posters || []).length ? `<h4 class="sub">Your posters <small>click one to put this picture in it</small></h4><div class="my-posters">${st.posters.map((q) => `<span class="chip-x"><button data-my-poster="${esc(q.name)}" title="${esc(q.about)}">${esc(q.name)}</button><button class="x" data-del-poster="${esc(q.name)}" title="Delete this saved poster">${icon("x")}</button></span>`).join("")}</div>` : ""}
    <div class="poster-picks">${POSTERS.map(([v, l, tip]) => `<button data-poster="${v}" class="${p?.template === v ? "on" : ""}" title="${esc(tip)}">${l}</button>`).join("")}</div>
    <label class="sub-label">Clean overlays <small class="faint">· your photo as it is, the words on a quiet fill</small></label>
    <div class="poster-picks">${CLEAN_POSTERS.map(([v, l, tip]) => `<button data-poster="${v}" class="${p?.template === v ? "on" : ""}" title="${esc(tip)}">${l}</button>`).join("")}</div>
    ${p ? `<div class="fld"><label>Shape <small class="faint">· what you see is what's exported</small></label><div class="shape-picks" id="pp-shape">${POSTER_SHAPES.map(([v, l, sub, w, h]) => `<button data-v="${v}" class="${p.shape === v ? "on" : ""}" title="${esc(sub)}"><i style="aspect-ratio:${w}/${h}"></i><b>${l}</b><small>${esc(sub)}</small></button>`).join("")}</div></div>
      <div class="slider"><label title="Drag the photo on the poster to move it; pinch on the trackpad to zoom too">Photo zoom</label><output>${Math.round((p.pic?.zoom || 1) * 100)}%</output><input type="range" id="pp-zoom" min="1" max="4" step="0.05" value="${p.pic?.zoom || 1}"></div>
      ${p.pic ? `<button class="btn ghost small-btn" id="pp-pic-reset" title="The photo placed as the layout had it">${icon("undo")} Photo back to its place</button>` : `<p class="notes">Drag the photo on the poster to move it in its frame.</p>`}
      <div class="slider"><label title="Make every word and banner smaller or bigger (they already fit the shape you pick)">Words and banners size</label><output>${Math.round((p.size || 1) * 100)}%</output><input type="range" id="pp-size" min="0.6" max="1.5" step="0.05" value="${p.size || 1}"></div>
      ${p.moves ? `<button class="btn ghost small-btn" id="pp-moves-reset" title="Every word moved or resized on the picture goes back to where the layout puts it">${icon("undo")} Words back to their places</button>` : ""}
      ${p.template === "custom" ? customSection(p) : `${customSection(p)}<button class="btn wide" id="pp-customize" title="Make this layout your own: every word, panel and band becomes a piece you can move, resize and restyle">${icon("layout")} Customize this layout</button>`}
      ${p.template === "spotlight" ? `<div class="fld"><label>Number</label><div class="seg full small" id="pp-numstyle">
        <button data-v="badge" class="${(p.number_style || "badge") === "badge" ? "on" : ""}" title="A solid badge on the card's corner, in front">Badge</button>
        <button data-v="behind" class="${p.number_style === "behind" ? "on" : ""}" title="Big, behind the card">Big, behind</button></div></div>` : ""}
      ${(POSTER_FIELDS[p.template] || []).map(([k, l]) => `<div class="fld"><label>${l}</label><div class="fld-row"><textarea class="field poster-in" rows="1" data-pk="${k}" placeholder="(left off the poster)" title="Return starts a new line (up to 3)">${esc(p[k] ?? "")}</textarea>
        ${k === "away_score" ? "" : `<button class="color-dot${p.colors?.[k] ? "" : " auto"}" data-color-pk="${k}" style="${p.colors?.[k] ? `background:${p.colors[k]}` : ""}" title="Its color" aria-label="Color of ${esc(l)}"></button>`}
        ${k === "away_score" ? "" : `<button class="aa-btn${st.stylePk === k ? " on" : ""}${p.moves?.[k]?.f || p.moves?.[k]?.r ? " set" : ""}" data-style-pk="${k}" title="Its font, size and angle" aria-label="Style of ${esc(l)}">Aa</button>`}
        <button class="icon-btn" data-clear-pk="${k}" title="Take this off the poster" ${off(!(p[k] ?? ""), "It's already off the poster: type in the box to put it back.")}>${icon("x")}</button></div>
        ${st.stylePk === k ? `<div class="word-style" data-word-style="${k}">
          <div class="slider"><label title="Or drag its corner on the picture">Size</label><output>${Math.round((p.moves?.[k]?.s || 1) * 100)}%</output><input type="range" data-word-size min="0.3" max="4" step="0.05" value="${p.moves?.[k]?.s || 1}"></div>
          ${fontPicker(p.moves?.[k]?.f, "Layout's own")}${angleControl(p.moves?.[k]?.r)}
          <p class="notes">Drag it on the picture to place it; its round handle turns it.</p></div>` : ""}
        ${st.colorPk === k ? `<div class="swatches word-colors" data-word-colors="${k}"><button data-v="" class="auto${p.colors?.[k] ? "" : " on"}" title="As the layout has it" aria-label="As the layout has it">A</button>${WORD_COLORS.map((c) => `<button data-v="${c}" class="${p.colors?.[k] === c ? "on" : ""}" style="background:${c}" aria-label="${c}"></button>`).join("")}
          <label class="pick-own" title="Any color"><input type="color" data-own-color="${k}" value="${p.colors?.[k] || "#ffffff"}"></label></div>` : ""}</div>`).join("")}
      <div class="swatches" id="pp-color" title="Team color">${TEAM_COLORS.map((c) => `<button data-v="${c}" class="${p.color === c ? "on" : ""}" style="background:${c}" aria-label="${c}"></button>`).join("")}</div>
      ${(st.kit || []).length && p.template !== "custom" ? `<div class="kit-grid small" id="pp-logo" title="Logo on the poster">
        <button class="kit-logo${!p.logo ? " on" : ""}" data-v="" title="No logo">${icon("x")}</button>${st.kit.map((k) => `<button class="kit-logo${p.logo === k.id ? " on" : ""}" data-v="${k.id}" title="${esc(k.name)}"><img src="/img/logo/${enc(k.id)}/original.png" alt=""></button>`).join("")}</div>` : ""}
      <div class="inline save-poster"><input class="field" id="pp-name" placeholder="Name this poster">
        <button class="btn" id="pp-save" title="Save this poster (layout, words, text, logo) to put any picture into it">${icon("save")} Save poster</button></div>
      <button class="btn ghost" id="pp-off">${icon("trash")} No poster</button>` : ""}
  </div>`;
}
function bindPosterSection(cur, pane) {
  const s0 = () => slotById(cur.id);
  const set = (fn) => changeEdits(s0(), (ed) => { ed.poster ||= { template: "gameday", shape: "post", color: "#1f2a44" }; fn(ed.poster); });
  const customize = async () => {  // the layout you are on, as pieces you can move and restyle
    const now = s0().edits?.poster;
    if (!now || now.template === "custom") return;
    const r = await api("/api/poster/customize", { poster: now });
    st.pieceSel = null;
    await changeEdits(s0(), (ed) => { ed.poster = r.poster; });
    toast("Your own layout now", { small: "Drag any piece on the picture; its corner resizes it. Add more above." });
  };
  $("#pp-customize", pane)?.addEventListener("click", async () => {
    if (!store.get("seen.customize", false)) {  // said once: what it does, and that it's rarely needed
      const ok = await new Promise((resolve) => {
        const m = modal(`<header><h2>Customize this layout?</h2></header><div class="body">
          <p>Every word, panel and band becomes a free piece: move, resize, restyle or delete any of them. Its word boxes (name, number…) become those pieces.</p>
          <p class="notes">You can already drag any word and add stripes, text or logos to this layout without it. ⌘Z undoes it.</p></div>
          <footer><button class="btn ghost" id="cz-no">Keep this layout</button><button class="btn primary" id="cz-yes">Customize</button></footer>`);
        $("#cz-yes", m).onclick = () => { closeModal(); resolve(true); };
        $("#cz-no", m).onclick = () => { closeModal(); resolve(false); };
      });
      store.set("seen.customize", true);
      if (!ok) return;
    }
    customize();
  });
  $("#pp-moves-reset", pane)?.addEventListener("click", () => set((p) => { delete p.moves; }));
  bindTeam(cur, pane);
  bindInThisPoster(cur, pane);
  bindCustom(cur, pane, set);
  pane.querySelectorAll("[data-poster]").forEach((b) => b.onclick = () => {
    if (s0().edits?.poster?.template === b.dataset.poster) return;  // the layout you are on: its words stay
    if (b.dataset.poster === "custom") return customize();
    set((p) => {
      const words = Object.fromEntries((POSTER_FIELDS[p.template] || []).map(([k]) => [k, p[k] ?? ""]));
      const kept = { ...(p.kept || {}), [p.template]: words };  // what you typed, for coming back to this layout
      const keptMoves = { ...(p.kept_moves || {}), [p.template]: p.moves || {} };  // and where, how big, which font, what angle
      const keep = { shape: p.shape, color: p.color, logo: p.logo ?? (st.kit?.[0]?.id || ""), ...(p.colors ? { colors: p.colors } : {}),
        ...(p.size ? { size: p.size } : {}), ...(p.family ? { family: p.family } : {}), kept, kept_moves: keptMoves };
      const back = keptMoves[b.dataset.poster];
      for (const k of Object.keys(p)) delete p[k];
      Object.assign(p, keep, { template: b.dataset.poster }, kept[b.dataset.poster] || {}, back && Object.keys(back).length ? { moves: back } : {});
    });
  });
  const ppName = $("#pp-name", pane);
  if (ppName) {
    ppName.value = st.posterName || "";
    ppName.oninput = () => { st.posterName = ppName.value; };
    ppName.onkeydown = (ev) => { if (ev.key === "Enter") { ev.preventDefault(); $("#pp-save", pane).click(); } };
  }
  $("#pp-save", pane)?.addEventListener("click", async () => {
    const name = ppName.value.trim();
    if (!name) { ppName.focus(); toast("Type a name for the poster first", { small: "Then press Save poster (or Return)" }); return; }
    await api("/api/posters", { name, slot: cur.id });
    st.posterName = "";
    await loadPosters(); editSig = ""; renderTabs();
    toast(`Saved the poster “${name}”`, { small: "It's under Your posters, at the top of the Poster panel on any picture" });
  });
  pane.querySelectorAll("[data-my-poster]").forEach((b) => b.onclick = async () => {
    const q = await api(`/api/posters/${enc(b.dataset.myPoster)}`);
    changeEdits(s0(), (ed) => { Object.assign(ed, JSON.parse(JSON.stringify(q.design))); });
    toast(`This picture is in “${q.name}” now`, { small: "Change its words here: the saved poster stays as it is" });
  });
  pane.querySelectorAll("[data-del-poster]").forEach((b) => b.onclick = async () => {
    const r0 = await api(`/api/posters/${enc(b.dataset.delPoster)}`, undefined, { method: "DELETE" });
    await loadPosters(); editSig = ""; renderTabs();
    if (r0.poster) toast(`Deleted the poster “${r0.poster.name}”`, { action: { label: "Undo", run: async (ev) => {
      ev.target.closest(".toast")?.remove();
      await api("/api/posters/restore", { poster: r0.poster }); await loadPosters(); editSig = ""; renderTabs();
    } } });
  });
  pane.querySelectorAll("[data-color-pk]").forEach((b) => b.onclick = () => {  // its palette opens under it
    st.colorPk = st.colorPk === b.dataset.colorPk ? null : b.dataset.colorPk; editSig = ""; renderTabs();
  });
  pane.querySelectorAll("[data-style-pk]").forEach((b) => b.onclick = () => {  // its font, size and angle open under it
    st.stylePk = st.stylePk === b.dataset.stylePk ? null : b.dataset.stylePk; st.colorPk = null; editSig = ""; renderTabs();
  });
  pane.querySelectorAll("[data-word-style]").forEach((box) => {
    const k = box.dataset.wordStyle, mv = () => s0().edits.poster?.moves?.[k] || {};
    const word = () => document.querySelector(`.pc-word[data-pk="${k}"]`);
    box.querySelectorAll("[data-font-pick] button").forEach((b) => b.onclick = () => setMove(cur, k, (m) => { m.f = b.dataset.v; }));
    const size = box.querySelector("[data-word-size]");
    size.oninput = () => { size.previousElementSibling.textContent = `${Math.round(size.value * 100)}%`; };
    size.onchange = () => setMove(cur, k, (m) => { m.s = +size.value; });  // (grown from where the layout anchors it)
    size.ondblclick = () => setMove(cur, k, (m) => { m.s = 1; });
    const r0 = () => wordsList.find((x) => x.key === k)?.r0 || 0;
    bindAngle(box, () => mv().r || 0, (a) => { const el = word(); if (el) el.style.rotate = `${a + r0()}deg`; }, (a) => turnWord(cur, k, a + r0()));
  });
  const wordColor = (k, c) => set((p) => { p.colors ||= {}; if (c) p.colors[k] = c; else delete p.colors[k]; });
  pane.querySelectorAll("[data-word-colors] button").forEach((b) => b.onclick = () => wordColor(b.parentElement.dataset.wordColors, b.dataset.v));
  pane.querySelectorAll("[data-own-color]").forEach((inp) => inp.onchange = () => wordColor(inp.dataset.ownColor, inp.value));
  pane.querySelectorAll("#pp-numstyle button").forEach((b) => b.onclick = () => set((p) => { p.number_style = b.dataset.v; }));
  pane.querySelectorAll("[data-clear-pk]").forEach((b) => b.onclick = () => {
    const k = b.dataset.clearPk;
    set((p) => { p[k] = ""; });
    toast("Taken off the poster", { small: "Type in its box to put it back, or ⌘Z" });
  });
  pane.querySelectorAll("#pp-shape button").forEach((b) => b.onclick = () => set((p) => { p.shape = b.dataset.v; }));
  const zoom = $("#pp-zoom", pane);
  if (zoom) {
    zoom.oninput = () => { zoom.previousElementSibling.textContent = `${Math.round(zoom.value * 100)}%`; };
    zoom.onchange = () => set((p) => { p.pic = { ...(p.pic || { x: 0, y: 0 }), zoom: +zoom.value }; });
  }
  $("#pp-pic-reset", pane)?.addEventListener("click", () => set((p) => { delete p.pic; }));
  const size = $("#pp-size", pane);
  if (size) {
    size.oninput = () => { size.previousElementSibling.textContent = `${Math.round(size.value * 100)}%`; };
    size.onchange = () => set((p) => { p.size = +size.value; });
    size.ondblclick = () => set((p) => { p.size = 1; });
  }
  pane.querySelectorAll("#pp-color button").forEach((b) => b.onclick = () => set((p) => { p.color = b.dataset.v; }));
  pane.querySelectorAll("#pp-logo button").forEach((b) => b.onclick = () => set((p) => { p.logo = b.dataset.v; }));
  $("#pp-off", pane)?.addEventListener("click", () => { st.tool = null; changeEdits(s0(), (ed) => { delete ed.poster; }); });
  pane.querySelectorAll(".poster-in").forEach((inp) => {
    let snap = null, timer = null;
    const grow = () => { inp.style.height = "auto"; inp.style.height = inp.scrollHeight + "px"; };
    requestAnimationFrame(grow); inp.addEventListener("input", grow);
    inp.onfocus = () => { snap = snapshot(s0()); };
    inp.oninput = () => {
      const s = s0(), e2 = clone(s.edits);
      if (!e2.poster) return;
      e2.poster[inp.dataset.pk] = inp.value;
      clearTimeout(timer);
      saveSoon(cur.id, e2, 450);
    };
    inp.onblur = () => setTimeout(() => {
      snap = null; closeBurst(cur.id);
    }, 600);
  });
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
      <div class="kit-grid">${kit.map((k) => `<button class="kit-logo" data-kit="${k.id}" draggable="true" title="${esc(k.name)}: click to put it on, or drag it onto the picture"><img src="/img/logo/${enc(k.id)}/original.png" alt="${esc(k.name)}">
        <span class="kit-x" data-kit-del="${k.id}" title="Delete it from your logos">${icon("x")}</span></button>`).join("")}
        <label class="kit-add" title="Add a logo: SVG, PDF, Illustrator (.ai), PNG, a JPG on white, or a screenshot of it">${icon("plus")}<span>Add a logo</span><input type="file" id="kit-file" accept="image/*,.svg,.svgz,.pdf,.ai,image/svg+xml,application/pdf" hidden></label></div>
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
    const lid = b.dataset.kitDel, name = st.kit?.find((k) => k.id === lid)?.name || "Logo";
    await api(`/api/logos/${lid}`, undefined, { method: "DELETE" });
    await loadKit();
    toast(`${name} taken out of your logos`, { action: { label: "Undo", run: async (ev) => {
      ev.target.closest(".toast")?.remove();
      await api(`/api/logos/${enc(lid)}/restore`, {}); await loadKit(); editSig = ""; renderTabs();
    } } });
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
      saveSoon(cur.id, e2, 200);
    };
    r.onchange = () => { snap = null; };
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
async function addLogo(file, quiet) {
  const fd = new FormData(); fd.append("file", file, file.name);
  const t = toast("Adding your logo…", { sticky: true, spin: true, small: "Taking its background away" });
  let meta = null;
  try { meta = await api("/api/logos", fd); if (quiet) t.close(); else t.done("Logo added", "Click it to put it on the picture"); } catch { t.close(); }
  await loadKit();
  return meta;
}

// Crop and straighten ---------------------------------------------------------------------------
const ASPECTS = [["free", "Free"], ["orig", "Original"], ["4:5", "4:5"], ["1:1", "1:1"], ["9:16", "9:16"], ["16:9", "16:9"]];
function coverScale(w, h, deg) {
  const t = Math.abs(deg) * Math.PI / 180, c = Math.cos(t), s = Math.sin(t);
  return Math.max((w * c + h * s) / w, (w * s + h * c) / h);
}
/* The crop's real size (the photo's own pixels), and what an Instagram export does with it */
const fullSizes = {};
async function cropPixels(cur, box) {
  const el = $("#c-px");
  if (!el) return;
  let full = fullSizes[cur.id];
  if (!full) {
    el.textContent = "";
    try { full = fullSizes[cur.id] = (await api(`/api/slots/${cur.id}/fullsize`)).full; } catch { return; }
    if (!full) return;
  }
  const w = Math.round((box[2] - box[0]) * full[0]), h = Math.round((box[3] - box[1]) * full[1]);
  const grow = 1080 / w, size = `${w.toLocaleString()} × ${h.toLocaleString()} px`;
  el.classList.toggle("ai", grow >= 1.15);
  el.classList.toggle("tight", grow > 4);
  el.textContent = grow >= 1.15 ? `✦ ${size} · AI sharpens it ${grow.toFixed(1)}x for Instagram` : `${size} · sharp for Instagram`;
  el.title = grow > 4 ? "Very tight: even with the AI enlarger it will look soft on Instagram. Widen the crop a little."
    : grow >= 1.15 ? "Fewer pixels than an Instagram post (1,080 wide): the export enlarges it with the AI detail enlarger. Zoom in (Z) after Apply to see it."
    : "More pixels than an Instagram post needs (1,080 wide): no enlarging.";
}
function renderCrop(v, cur) {
  const W = cur.base_width, H = cur.base_height;
  const d = st.cropDraft ||= { angle: cur.edits?.angle || 0, box: cur.edits?.crop ? [...cur.edits.crop] : [0, 0, 1, 1], aspect: "free" };
  v.innerHTML = `<div class="frame tool-crop" id="frame"><div class="layer"><img class="after" id="crop-img" src="${slotImg(cur, "base")}" alt="" draggable="false"></div>
      <div class="crop-box" id="crop-box"><i class="g1"></i><i class="g2"></i><i class="g3"></i><i class="g4"></i>
        ${["nw", "n", "ne", "e", "se", "s", "sw", "w"].map((h) => `<b class="h h-${h}" data-h="${h}"></b>`).join("")}<span class="crop-px" id="c-px"></span></div></div>
    <div class="fixbar toolbar crop-bar below">${histBtns()}
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
    cropPixels(cur, d.box);
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
/* Remove, in three plain steps: ① pick what goes (click a person or a thing, or brush), ② Remove it,
   ③ check the fill: hold to compare, try another fill, or copy from a spot you choose (drag the circle
   to grass, sky, crowd: the area is filled from there, its light matched at the edge). */
const FILL_NAMES = ["AI fill", "AI fill, wider view", "AI fill, smooth", "Blend from around it"];
function renderBrush(v, cur) {
  const b = st.brush;
  b.mode ||= "click";
  b.scope ||= "look";
  b.stage ||= "pick";
  const nRemoved = (cur.edits?.removals || []).length;
  if (b.stage !== "pick" && (b.sid !== cur.id || nRemoved < (b.count || 0))) { b.stage = "pick"; b.copy = null; }  // (undone, or another look)
  const others = st.slots.filter((s) => s.photo === cur.photo && s.state === "done").length;
  const step = (n, label) => `<span class="rm-step${b.stage === "pick" ? (n === 1 ? " on" : "") : n === 3 ? " on" : " done"}"><i>${n}</i>${label}</span>`;
  const steps = `<span class="rm-steps">${step(1, "Pick what goes")}${step(2, "Remove")}${step(3, "Check the fill")}</span><span class="sep"></span>`;
  const last = (cur.edits?.removals || [])[nRemoved - 1] || {};
  const fillNow = last.fill?.from ? "Copied from a spot" : FILL_NAMES[last.fill?.try || 0];
  const bar = b.stage === "pick" ? `
      <div class="seg small" id="rm-mode"><button data-v="click" title="Click a person or a thing: all of it goes">${icon("target")} Click</button><button data-v="brush" title="Paint over what should go (small spots too: then fill them from a spot you choose)">${icon("eraser")} Brush</button></div>
      <span class="angle" id="rm-size" ${b.mode === "brush" ? "" : "hidden"}>Size<input type="range" id="b-size" min="0.006" max="0.08" step="0.002" value="${b.r}"></span>
      <button id="rm-people" title="Select every person who is not one of the players kept" hidden>${icon("plus")} Background people</button>
      <span class="sep"></span>
      ${others > 1 ? `<div class="seg small" id="rm-scope"><button data-v="look" title="Only this look">This look</button><button data-v="photo" title="Every look of this photo, and the looks made of it later">All ${others} looks</button></div><span class="sep"></span>` : ""}
      <button id="b-undo" title="Take back the last click or stroke">${icon("undo")} Last pick</button>
      <button id="b-go" class="on">Remove it</button><button id="b-done">Done</button>`
    : b.stage === "check" ? `
      <button id="rm-hold" title="Hold to see it before the removal">${icon("compare")} Hold to compare</button>
      <button id="rm-try" title="Fill it another way (four to choose from; each sees the area differently)">${icon("refresh")} Try another fill <small>${esc(fillNow)}</small></button>
      <button id="rm-copy" title="Choose the spot it's filled from: drag the circle to grass, sky, crowd…">${icon("target")} Copy from a spot</button>
      <span class="sep"></span>
      <button id="rm-keep" class="on" title="Keep it and remove something else">${icon("check")} Keep</button><button id="b-done">Done</button>`
    : `
      <span class="title"><b>Copy from a spot</b><span>Drag the circle to what should fill it · let go to apply</span></span><span class="sep"></span>
      <button id="rm-copy-done" class="on">${icon("check")} Done copying</button>`;
  v.innerHTML = `<div class="frame tool-remove mode-${b.stage === "pick" ? b.mode : b.stage}" id="frame"><div class="layer"><img class="after" src="${slotImg(cur, "base")}" alt="" draggable="false"></div>
      <img class="rm-before" id="rm-before" alt="" hidden>
      <img class="rm-preview" id="rm-preview" alt="" hidden><canvas id="brush"></canvas><canvas id="rm-copy-cv" hidden></canvas><div class="brush-ring" id="ring" hidden></div>
      <div class="rm-src" id="rm-src" hidden title="Drag me to the spot it's filled from"></div><div class="rm-dst" id="rm-dst" hidden></div>
      <span class="tag l rm-status" id="rm-status" hidden></span></div>
    <div class="fixbar toolbar rm-bar below">${histBtns()}${steps}${bar}</div>`;
  paintIcons(v);
  fitFrame(cur.base_width, cur.base_height);
  const f = $("#frame"), cv = $("#brush"), ring = $("#ring"), prev = $("#rm-preview"), status = $("#rm-status"), img = $("#frame img.after");
  const say = (html) => { if (!status.isConnected) return; status.hidden = !html; status.innerHTML = html || ""; };
  $("#b-done")?.addEventListener("click", () => { b.stage = "pick"; b.copy = null; setTool("remove"); });

  if (b.stage === "check") {  // ③ check the fill
    say(`<b>③</b> Does it look right? Hold to compare · try another fill · or copy from a spot`);
    const hold = $("#rm-hold"), before = $("#rm-before");
    if (b.beforeUrl) before.src = b.beforeUrl; else hold.hidden = true;
    const show = (on) => { before.hidden = !on; hold.classList.toggle("on", on); };
    hold.onpointerdown = () => show(true);
    ["pointerup", "pointerleave", "pointercancel"].forEach((ev) => hold.addEventListener(ev, () => show(false)));
    $("#rm-keep").onclick = () => { b.stage = "pick"; viewerSig = ""; renderViewer(); toast("Kept", { small: "Pick the next thing to remove, or Done" }); };
    $("#rm-copy").onclick = () => { b.stage = "copy"; viewerSig = ""; renderViewer(); };
    $("#rm-try").onclick = async () => {
      const s0 = slotById(cur.id), was = last.fill?.try || 0, next = last.fill?.from ? 1 : (was + 1) % FILL_NAMES.length;
      const t = toast(`Filling it: ${FILL_NAMES[next]}…`, { sticky: true, spin: true });
      try {
        const s = await api(`/api/slots/${cur.id}/remove/fill`, { fill: next ? { try: next } : null });
        pushHist({ type: "slot", sid: cur.id, before: snapshot(s0), after: snapshot(s) });
        updateSlot(s); t.done(FILL_NAMES[next], `${next + 1} of ${FILL_NAMES.length} · Try again for the next one`);
      } catch { t.close(); }
      viewerSig = ""; renderViewer();
    };
    return;
  }

  if (b.stage === "copy") {  // copy from a spot: a circle to drag, the fill shown live from there
    const cc = $("#rm-copy-cv"), src = $("#rm-src"), dst = $("#rm-dst");
    say(`Drag the <b>◎</b> circle to what should fill the area (it's shown live) · let go to apply`);
    const mask = new Image();
    mask.src = `/api/slots/${cur.id}/remove/mask/${cur.ver}.png`;
    const base = new Image();
    base.src = b.beforeUrl || slotImg(cur, "base");
    Promise.all([mask.decode(), base.decode()]).then(() => {
      const W = mask.naturalWidth, H = mask.naturalHeight;
      // the area's middle and size (from the mask, at a small scale)
      const k = Math.min(1, 240 / Math.max(W, H)), sw = Math.max(1, Math.round(W * k)), sh = Math.max(1, Math.round(H * k));
      const t = document.createElement("canvas"); t.width = sw; t.height = sh;
      const tc = t.getContext("2d"); tc.drawImage(mask, 0, 0, sw, sh);
      const d = tc.getImageData(0, 0, sw, sh).data;
      let x0 = sw, y0 = sh, x1 = 0, y1 = 0, n = 0, mx = 0, my = 0;
      for (let y = 0; y < sh; y++) for (let x = 0; x < sw; x++) if (d[(y * sw + x) * 4 + 3] > 127) { n++; mx += x; my += y; x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
      if (!n) { say("Nothing to fill here"); return; }
      const cx = mx / n / sw, cy = my / n / sh, aw = (x1 - x0 + 1) / sw, ah = (y1 - y0 + 1) / sh;
      if (!b.copy || b.copy.sid !== cur.id) {  // a first spot beside it (right, or left near the edge)
        const dx = cx + aw * 1.25 < 0.97 ? aw * 1.25 : -aw * 1.25;
        b.copy = { sid: cur.id, dx: last.fill?.from?.[0] ?? dx, dy: last.fill?.from?.[1] ?? 0 };
      }
      const r = f.getBoundingClientRect();
      cc.width = Math.round(r.width * devicePixelRatio); cc.height = Math.round(r.height * devicePixelRatio); cc.hidden = false;
      const ctx = cc.getContext("2d");
      const paint = () => {
        const { dx, dy } = b.copy, cw = cc.width, ch = cc.height;
        ctx.clearRect(0, 0, cw, ch);
        ctx.globalCompositeOperation = "source-over";
        ctx.drawImage(base, -dx * cw, -dy * ch, cw, ch);  // the photo moved so the chosen spot sits over the area
        ctx.globalCompositeOperation = "destination-in";
        ctx.drawImage(mask, 0, 0, cw, ch);  // only inside the area
        ctx.globalCompositeOperation = "source-over";
        const size = Math.max(aw * r.width, ah * r.height, 28);
        Object.assign(dst.style, { left: `${cx * 100}%`, top: `${cy * 100}%`, width: `${aw * 100}%`, height: `${ah * 100}%` });
        Object.assign(src.style, { left: `${(cx + dx) * 100}%`, top: `${(cy + dy) * 100}%`, width: `${size}px`, height: `${size}px` });
        src.hidden = dst.hidden = false;
      };
      paint();
      const apply = async () => {
        const s0 = slotById(cur.id), { dx, dy } = b.copy;
        say(`<span class="spin"></span> Copying it from there…`);
        try {
          const s = await api(`/api/slots/${cur.id}/remove/fill`, { fill: { from: [Math.round(dx * 1e4) / 1e4, Math.round(dy * 1e4) / 1e4] } });
          pushHist({ type: "slot", sid: cur.id, before: snapshot(s0), after: snapshot(s) });
          updateSlot(s, { keepPane: true });
          img.src = slotImg(s, "base");
          say(`Filled from there · drag again to try another spot, or <b>Done copying</b>`);
        } catch { say("Couldn't copy from there: try another spot"); }
      };
      src.onpointerdown = (e) => {
        e.preventDefault(); src.setPointerCapture(e.pointerId);
        const start = { x: e.clientX, y: e.clientY, dx: b.copy.dx, dy: b.copy.dy };
        src.onpointermove = (m) => {
          b.copy.dx = Math.max(-cx, Math.min(1 - cx, start.dx + (m.clientX - start.x) / r.width));
          b.copy.dy = Math.max(-cy, Math.min(1 - cy, start.dy + (m.clientY - start.y) / r.height));
          paint();
        };
        src.onpointerup = () => { src.onpointermove = src.onpointerup = null; apply(); };
      };
    }).catch(() => say("Couldn't load the area: Done copying, then try again"));
    $("#rm-copy-done").onclick = () => { b.stage = "check"; viewerSig = ""; renderViewer(); };
    return;
  }

  // ① pick what goes
  const paintBar = () => {
    if (!f.isConnected || !$("#rm-size")) return;  // (moved on to another step meanwhile)
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
    if (!b.strokes.length && !b.points.length) {
      prev.hidden = true; b.preview = null;
      say(`<b>①</b> ${b.mode === "click" ? "Click a person or a thing to remove" : "Brush over what should go"}`);
      return;
    }
    previewTimer = setTimeout(async () => {
      const ask = ++previewAsk;
      say('<span class="spin"></span> Finding it…');
      try {
        const res = await fetch(`/api/slots/${cur.id}/remove/preview`, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ points: b.points, strokes: b.strokes }) });
        if (!res.ok || ask !== previewAsk || !f.isConnected) return;
        const url = URL.createObjectURL(await res.blob());
        if (b.preview) URL.revokeObjectURL(b.preview);
        b.preview = url; prev.src = url; prev.hidden = false;
        say(`<b>②</b> Red goes · click more, or <b>Remove it</b>`);
      } catch { say(""); }
    }, 150);
  };
  requestAnimationFrame(() => { if (!f.isConnected) return; size(); if (b.preview) { prev.src = b.preview; prev.hidden = false; } paintBar(); if (!b.preview) preview(); });
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
  $$("#rm-mode button").forEach((x) => x.onclick = () => { b.mode = x.dataset.v; paintBar(); preview(); });
  $$("#rm-scope button").forEach((x) => x.onclick = () => { b.scope = x.dataset.v; paintBar(); });
  $("#b-size").oninput = (e) => { b.r = +e.target.value; store.set("brush", b.r); };
  $("#b-undo").onclick = () => {
    const l = (b.order || []).pop();
    if (l === "s") b.strokes.pop(); else if (l === "p") b.points.pop();
    draw(); preview();
  };
  // the background people: one click selects them all
  api(`/api/slots/${cur.id}/people`).then((r) => {
    const btn = $("#rm-people");
    if (!btn || !r.people.length) return;
    btn.hidden = false;
    btn.innerHTML = `${icon("plus")} ${plural(r.people.length, "background person", "background people")}`;
    btn.onclick = () => { r.people.forEach((p) => { b.points.push([p.x, p.y]); (b.order ||= []).push("p"); }); preview(); };
  }).catch(() => {});
  $("#b-go").onclick = async () => {
    if (!(b.strokes.length || b.points.length)) return;
    const body = { points: b.points.map(([x, y]) => [Math.round(x * 1e4) / 1e4, Math.round(y * 1e4) / 1e4]),
      strokes: b.strokes.map((s2) => ({ pts: s2.pts.map(([x, y]) => [Math.round(x * 1e4) / 1e4, Math.round(y * 1e4) / 1e4]), r: s2.r })),
      scope: b.scope };
    const affected = b.scope === "photo" ? st.slots.filter((s2) => s2.photo === cur.photo && s2.state === "done") : [cur];
    const before = new Map(affected.map((s2) => [s2.id, snapshot(s2)]));
    try {  // the picture as it was, kept for "Hold to compare" and for copying from
      if (b.beforeUrl) URL.revokeObjectURL(b.beforeUrl);
      b.beforeUrl = URL.createObjectURL(await (await fetch(img.src)).blob());
    } catch { b.beforeUrl = null; }
    say('<span class="spin"></span> Removing it and filling the area…');
    try {
      const r = await api(`/api/slots/${cur.id}/remove`, body);
      const items = r.slots.filter((s2) => before.has(s2.id)).map((s2) => ({ sid: s2.id, before: before.get(s2.id), after: snapshot(s2) }));
      pushHist({ type: "multi", items, pid: b.scope === "photo" ? cur.photo : null,
        futureBefore: (r.future || []).slice(0, -1), futureAfter: r.future || [] });
      r.slots.forEach((s2) => updateSlot(s2));
      b.stage = "check"; b.sid = cur.id; b.count = (slotById(cur.id).edits?.removals || []).length; b.copy = null;
    } catch { say(""); }
    b.strokes = []; b.points = []; b.order = [];
    if (b.preview) URL.revokeObjectURL(b.preview);
    b.preview = null;
    viewerSig = ""; renderViewer();
  };
}

async function loadPosters() {
  try { st.posters = (await fetch("/api/posters").then((r) => r.json())).posters; } catch { st.posters = []; }
}
document.addEventListener("DOMContentLoaded", loadPosters);

/* In the Poster tool, the photo itself moves: drag it (anywhere but on a word, the logo or a piece) to
   place it in the poster's frame; pinch on the trackpad to zoom. What you see is what is exported. */
function bindPhotoDrag(cur) {
  const f = $("#frame"), img = f?.querySelector("img.after");
  if (!f || !img) return;
  f.classList.add("photo-drag");
  f.onpointerdown = (e) => {
    if (e.button !== 0 || e.target.closest(".pw, .pc, .tag, button, .fixbar")) return;
    e.preventDefault();
    const r = f.getBoundingClientRect(), x0 = e.clientX, y0 = e.clientY;
    let dx = 0, dy = 0;
    f.setPointerCapture(e.pointerId); f.classList.add("dragging-photo");
    f.onpointermove = (m) => { dx = m.clientX - x0; dy = m.clientY - y0; img.style.transform = `translate(${dx}px, ${dy}px)`; };
    f.onpointerup = () => {
      f.onpointermove = f.onpointerup = null; f.classList.remove("dragging-photo");
      if (Math.abs(dx) + Math.abs(dy) < 3) {  // a click on the photo, not on a word: nothing chosen any more
        img.style.transform = "";
        st.focusField = null;
        if (st.pieceSel || st.stylePk) { st.pieceSel = null; st.stylePk = null; st.colorPk = null; editSig = ""; viewerSig = ""; render(); }
        return;
      }
      changeEdits(slotById(cur.id), (ed) => {
        const pic = ed.poster.pic || { x: 0, y: 0, zoom: 1 };
        ed.poster.pic = { ...pic, x: (pic.x || 0) + dx / r.width, y: (pic.y || 0) + dy / r.height };
      });
    };
  };
  let wheelTimer = null, pending = null;
  f.onwheel = (e) => {  // a pinch on the trackpad (or ⌘ + scroll): zoom the photo
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    const now = slotById(cur.id).edits.poster.pic?.zoom || 1;
    pending = Math.max(1, Math.min(4, (pending ?? now) * Math.exp(-e.deltaY * 0.01)));
    img.style.transform = `scale(${pending / now})`;
    clearTimeout(wheelTimer);
    wheelTimer = setTimeout(() => {
      const z = pending; pending = null;
      changeEdits(slotById(cur.id), (ed) => { ed.poster.pic = { ...(ed.poster.pic || { x: 0, y: 0 }), zoom: +z.toFixed(3) }; });
    }, 350);
  };
}

/* The window closing (or the app quitting) with a change not yet saved: it is sent on the way out. */
function sendUnsaved() {
  for (const [sid, p] of saving) {
    if (!p.timer && !p.burst) continue;
    const s = slotById(sid);
    if (!s) continue;
    clearTimeout(p.timer); p.timer = null;
    if (p.burst) {  // (its step to undo, kept with the rest)
      clearTimeout(p.burstTimer);
      if (JSON.stringify(p.burst) !== JSON.stringify(snapshot(s))) { hist.undo.push({ type: "slot", sid, before: p.burst, after: snapshot(s) }); hist.redo = []; }
      p.burst = null;
    }
    try { navigator.sendBeacon(`/api/slots/${sid}/edit`, new Blob([JSON.stringify({ edits: s.edits })], { type: "application/json" })); } catch { /* (closing anyway) */ }
  }
  keepHist();
}
window.addEventListener("pagehide", sendUnsaved);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") sendUnsaved(); });
