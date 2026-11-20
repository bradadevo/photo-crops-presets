/* Backgrounds and the cut-out, the expert way.
   - Right-click the picture: replace the background, fix the cut-out, or go back to the original.
   - The Background tool: backgrounds made here (in the team color) or your own picture, with blur,
     darker, match the light and light wrap; the player put in front the way a retoucher would.
   - The Cut-out tool: click a whole thing in or out, paint in or out with a brush, the refine-edge
     brush for hair, softness and shift for the whole edge, and four ways to look at it. */

const BG_COLORS = ["#1f2a44", "#0b3d91", "#b3121a", "#0f5f3a", "#5b2a86", "#d97706", "#111111", "#7dd3fc"];
let bgList = null;
async function loadBackgrounds(force) {
  if (!bgList || force) { try { bgList = await api("/api/backgrounds"); } catch { bgList = { made: [], own: [] }; } }
  return bgList;
}

function backgroundSection(e) {
  const bg = e.background;
  const list = bgList || { made: [], own: [] };
  if (!bgList) loadBackgrounds().then(() => { editSig = ""; renderTabs(); });
  const color = bg?.color || e.poster?.color || "#1f2a44";
  const tile = (b) => `<button class="bg-tile${bg?.src === b.src ? " on" : ""}" data-bg="${esc(b.src)}" title="${esc(b.about)}">
    <img src="/img/bg/${enc(b.src)}.jpg?color=${enc(color)}" alt="" loading="lazy"><span>${esc(b.src.startsWith("file:") ? b.about : b.src)}</span></button>`;
  const sl = (k, label, tip, v) => `<div class="slider"><label title="${esc(tip)}">${label}</label><output>${Math.round(v * 100)}%</output>
    <input type="range" data-bg-k="${k}" min="0" max="1" step="0.05" value="${v}"></div>`;
  return `<div class="section bg-section"><h3>Background</h3>
    <p class="notes">The player stays; what's behind them changes. Right-click the picture any time for this.</p>
    <div class="bg-grid">${list.made.map(tile).join("")}${list.own.map(tile).join("")}
      <label class="bg-tile add" title="Your own picture: a stadium, a street, a famous field"><input type="file" id="bg-file" accept="image/*" hidden>${icon("plus")}<span>Your own picture…</span></label></div>
    ${bg ? `${bg.src.startsWith("file:") ? "" : `<div class="swatches" id="bg-color" title="Its color">${BG_COLORS.map((c) => `<button data-v="${c}" class="${color === c ? "on" : ""}" style="background:${c}" aria-label="${c}"></button>`).join("")}
        <label class="pick-own" title="Any color"><input type="color" id="bg-own-color" value="${color}"></label></div>`}
      ${sl("blur", "Blur", "Out of focus, like a fast lens: the player stands out", bg.blur)}
      ${sl("dim", "Darker", "A darker background makes the player pop", bg.dim)}
      ${sl("match", "Match the light", "The player's color nudged toward the new background's light", bg.match)}
      ${sl("wrap", "Light wrap", "The background's light around the player's edge, so they sit in it", bg.wrap)}
      <div class="inline"><button class="btn" id="bg-fix" title="Paint in what was missed, paint out what wasn't the player, refine hair">${icon("wand")} Fix the cut-out</button>
        <button class="btn ghost" id="bg-off" title="The photo's own background back">${icon("undo")} Original background</button></div>` : ""}
  </div>`;
}

function bindBackgroundSection(cur, pane) {
  const box = pane.querySelector(".bg-section");
  if (!box) return;
  const s0 = () => slotById(cur.id);
  const set = (fn) => changeEdits(s0(), (ed) => { fn(ed); });
  const color0 = () => s0().edits?.background?.color || s0().edits?.poster?.color || "#1f2a44";
  box.querySelectorAll("[data-bg]").forEach((b) => b.onclick = () => set((ed) => {
    ed.background = { blur: 0.15, dim: 0, match: 0.35, wrap: 0.5, ...(ed.background || {}), src: b.dataset.bg, color: color0() };
  }));
  box.querySelector("#bg-file")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const fd = new FormData(); fd.append("file", file);
    const t = toast("Adding your background…", { sticky: true, spin: true });
    try {
      const r = await fetch("/api/backgrounds", { method: "POST", body: fd });
      if (!r.ok) throw new Error((await r.json()).detail || "It couldn't be added");
      const { src } = await r.json();
      await loadBackgrounds(true);
      t.done("Added: it's kept for every photo");
      set((ed) => { ed.background = { blur: 0.1, dim: 0, match: 0.35, wrap: 0.5, ...(ed.background || {}), src, color: color0() }; });
    } catch (err) { t.close(); toast(String(err.message || err), { bad: true }); }
  });
  box.querySelectorAll("#bg-color [data-v]").forEach((b) => b.onclick = () => set((ed) => { ed.background.color = b.dataset.v; }));
  box.querySelector("#bg-own-color")?.addEventListener("change", (e) => set((ed) => { ed.background.color = e.target.value; }));
  box.querySelectorAll("[data-bg-k]").forEach((r) => {
    r.oninput = () => { r.previousElementSibling.textContent = Math.round(r.value * 100) + "%"; };
    r.onchange = () => set((ed) => { ed.background[r.dataset.bgK] = +r.value; });
  });
  box.querySelector("#bg-off")?.addEventListener("click", () => set((ed) => { delete ed.background; }));
  box.querySelector("#bg-fix")?.addEventListener("click", () => setTool("cutout"));
}

/* Right-click on the picture */
document.addEventListener("contextmenu", (e) => {
  const f = e.target.closest?.("#frame");
  if (!f || e.target.closest(".pc, .ctx-menu")) return;
  const cur = slotById(st.current);
  if (!cur || cur.state !== "done" || st.mode === "cull" || st.mode === "check") return;
  e.preventDefault();
  document.querySelector(".ctx-menu")?.remove();
  const has = !!cur.edits?.background;
  const items = [["bg", has ? "Change the background…" : "Replace the background…", "Put the player in front of a new one: made here, or your own picture"],
    ["fix", "Fix the cut-out…", "Paint in what was missed, paint out what wasn't the player, refine hair"],
    ...(has ? [["off", "Original background", "The photo's own background back"]] : []),
    ["poster", "Make it a poster…", "Game Day, Spotlight, Stadium Banner and more"]];
  const m = document.createElement("div");
  m.className = "menu ctx-menu";
  m.innerHTML = items.map(([k, l, sub]) => `<button data-ctx="${k}"><span>${l}</span><small>${sub}</small></button>`).join("");
  ctxPlace(m, e);
  const close = ctxKeep(m);
  m.querySelectorAll("[data-ctx]").forEach((b) => b.onclick = () => {
    close();
    const k = b.dataset.ctx;
    if (k === "bg") { if (st.tool !== "background") setTool("background"); }
    else if (k === "fix") { if (!st.fixing) setTool("cutout"); }
    else if (k === "off") changeEdits(slotById(cur.id), (ed) => { delete ed.background; });
    else if (k === "poster") { if (st.tool !== "poster") setTool("poster"); }
  });
});

/* The Cut-out tool's bar: what a click or a stroke does, the brush size, the whole edge, the view */
const FIX_MODES = [["click-add", "plus", "Add", "Click something: all of it becomes the player"],
  ["click-out", "x", "Take out", "Click something: all of it stops being the player"],
  ["brush-add", "brush", "Paint in", "Paint over what was missed (an arm, a ball, a stick)"],
  ["brush-out", "eraser", "Paint out", "Paint over what isn't the player (grass, a net, a teammate)"],
  ["edge", "wand", "Refine edge", "Paint along hair or a fuzzy edge: the edge follows the photo's own"]];
const FIX_VIEWS = [["tint", "Blue"], ["black", "On black"], ["white", "On white"], ["mask", "Mask"]];
function fixBar() {
  const mode = st.fixMode || (st.fixAdd === false ? "click-out" : "click-add");
  const tune = st.fixTune || [0, 0];
  return `<div class="fixbar toolbar below cut-bar">
    <div class="seg small">${FIX_MODES.map(([k, ic, l, tip]) => `<button data-fix-mode="${k}" class="${mode === k ? "on" : ""}" title="${esc(tip)}">${icon(ic)} ${l}</button>`).join("")}</div>
    ${mode.startsWith("click") ? "" : `<span class="angle" title="Brush size · [ and ] keys">Size<input type="range" id="fix-r" min="0.004" max="0.08" step="0.002" value="${st.fixR || 0.02}"></span>`}
    <span class="sep"></span>
    <div class="seg small" title="How to look at the cut-out">${FIX_VIEWS.map(([k, l]) => `<button data-fix-view="${k}" class="${(st.fixView || "tint") === k ? "on" : ""}">${l}</button>`).join("")}</div>
    <span class="row2">
      <span class="angle" title="Soften the whole edge (feather)">Soft edge<input type="range" id="fix-soft" min="0" max="1" step="0.05" value="${tune[0]}"></span>
      <span class="angle" title="Move the whole edge in (left) or out (right)">Shift edge<input type="range" id="fix-shift" min="-1" max="1" step="0.05" value="${tune[1]}"></span>
      <span class="sep"></span>
      <button data-fix="undo" title="Undo the last fix">${icon("undo")}</button>
      <button data-fix="reset" title="Throw away every fix: the automatic cut-out">Automatic</button>
      <span class="sep"></span>
      <button data-fix="remake" class="on">Remake this photo's looks</button>
      <button data-fix="done">Done</button></span></div>`;
}

/* Painting on the picture while fixing the cut-out (the bar's own buttons are wired in app.js) */
function bindFixBrush(cur, v) {
  const f = $("#frame");
  if (!f) return;
  const mode = () => st.fixMode || (st.fixAdd === false ? "click-out" : "click-add");
  const send = async (body) => {
    await api(`/api/slots/${cur.id}/fix`, body);
    st.fixVer++; viewerSig = ""; renderViewer();
  };
  v.querySelectorAll("[data-fix-mode]").forEach((b) => b.onclick = (e) => {
    e.stopPropagation(); st.fixMode = b.dataset.fixMode; st.fixAdd = st.fixMode !== "click-out"; viewerSig = ""; renderViewer();
  });
  v.querySelectorAll("[data-fix-view]").forEach((b) => b.onclick = (e) => { e.stopPropagation(); st.fixView = b.dataset.fixView; viewerSig = ""; renderViewer(); });
  v.querySelector("#fix-r")?.addEventListener("input", (e) => { st.fixR = +e.target.value; store.set("fixR", st.fixR); });
  const tune = () => send({ kind: "tune", soft: +$("#fix-soft").value, shift: +$("#fix-shift").value });
  ["#fix-soft", "#fix-shift"].forEach((id) => v.querySelector(id)?.addEventListener("change", () => { st.fixTune = [+$("#fix-soft").value, +$("#fix-shift").value]; tune(); }));
  v.querySelectorAll(".cut-bar input").forEach((i) => i.onclick = (e) => e.stopPropagation());
  // the brush: a ring that follows the pointer, the stroke drawn as you paint
  const cv = document.createElement("canvas"), ring = document.createElement("div");
  cv.className = "fix-canvas"; ring.className = "brush-ring"; ring.hidden = true;
  f.append(cv, ring);
  const fit = () => { const r = f.getBoundingClientRect(); cv.width = r.width; cv.height = r.height; };
  fit();
  const ctx = cv.getContext("2d");
  let pts = null;
  const at = (e) => { const r = f.getBoundingClientRect(); return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height]; };
  f.onpointermove = (e) => {
    const m = mode();
    if (m.startsWith("click")) { ring.hidden = true; return; }
    const r = f.getBoundingClientRect(), d = (st.fixR || 0.02) * r.width * 2;
    ring.hidden = false;
    Object.assign(ring.style, { width: d + "px", height: d + "px", left: e.clientX - r.left - d / 2 + "px", top: e.clientY - r.top - d / 2 + "px" });
    ring.className = "brush-ring " + m;
    if (!pts) return;
    const p = at(e), q = pts[pts.length - 1];
    pts.push(p);
    ctx.strokeStyle = m === "brush-out" ? "rgba(240,60,70,.55)" : m === "edge" ? "rgba(255,210,60,.55)" : "rgba(60,220,110,.55)";
    ctx.lineWidth = d; ctx.lineCap = "round"; ctx.lineJoin = "round";
    ctx.beginPath(); ctx.moveTo(q[0] * cv.width, q[1] * cv.height); ctx.lineTo(p[0] * cv.width, p[1] * cv.height); ctx.stroke();
  };
  f.onpointerleave = () => { ring.hidden = true; };
  f.onpointerdown = (e) => {
    if (e.button !== 0 || mode().startsWith("click") || e.target.closest(".cut-bar")) return;
    e.preventDefault(); f.setPointerCapture(e.pointerId); fit();
    pts = [at(e)];
    f.onpointermove(e);
  };
  f.onpointerup = async () => {
    if (!pts) return;
    const m = mode(), stroke = pts; pts = null;
    const t = toast(m === "edge" ? "Refining the edge…" : "Fixing the cut-out…", { spin: true, sticky: true });
    try { await send({ kind: m === "edge" ? "edge" : "brush", add: m !== "brush-out", points: stroke, r: st.fixR || 0.02 }); } finally { t.close(); }
  };
  f.onclick = async (e) => {  // a click: the whole thing there in or out
    const m = mode();
    if (!m.startsWith("click") || e.target.closest(".cut-bar")) return;
    const [x, y] = at(e);
    await send({ x, y, add: m === "click-add" });
  };
}
document.addEventListener("keydown", (e) => {  // [ and ] make the brush smaller or bigger
  if (!st.fixing || e.target.closest?.("input, textarea") || (e.key !== "[" && e.key !== "]")) return;
  st.fixR = Math.min(0.08, Math.max(0.004, (st.fixR || 0.02) * (e.key === "]" ? 1.25 : 0.8)));
  store.set("fixR", st.fixR);
  const r = $("#fix-r"); if (r) r.value = st.fixR;
});
