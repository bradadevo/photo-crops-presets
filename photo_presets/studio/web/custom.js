/* VS Digital Pro: the custom poster. Your own layout from the same pieces the ready-made ones use
   (text in any style, a number badge, a panel or band, a line, a logo), each moved by dragging it
   on the picture, resized by its corner, changed in the panel, in front of the players or behind
   them. The app draws the poster (what you see is what is exported); the page draws only the
   outlines you drag. Loaded after edit.js, whose helpers it uses. */

/* A custom poster's pieces are its elements; on a ready-made layout, the pieces you add are its extras. */
const PK = (p) => (p?.template === "custom" ? "elements" : "extras");
const PIECE_NAMES = { text: "Text", badge: "Number", box: "Panel", rule: "Line", logo: "Logo", card: "Photo card", stripes: "Stripes" };
/* Ready stripe sets (the team color is the poster's) */
const STRIPE_SETS = [["Red · Blue", ["#c8102e", "#0b3d91"]], ["Red · White · Blue", ["#c8102e", "#ffffff", "#0b3d91"]],
  ["Navy · Gold", ["#1f2a44", "#d4af37"]], ["Navy · White · Red", ["#1f2a44", "#ffffff", "#c8102e"]], ["Green · White", ["#0f5f3a", "#ffffff"]],
  ["Black · Gold", ["#111111", "#d4af37"]], ["Orange · Black", ["#d97706", "#111111"]], ["Purple · Gold", ["#5b2a86", "#d4af37"]],
  ["Sky · White · Navy", ["#7dd3fc", "#ffffff", "#1f2a44"]], ["Team · White", ["team", "#ffffff"]], ["Team · Gold", ["team", "#d4af37"]]];
const PIECE_STYLES = [["heavy", "Heavy"], ["bold", "Bold"], ["clean", "Clean"], ["spaced", "Spaced"], ["outline", "Outline"], ["banner", "Banner"]];
const newId = () => "p" + Math.random().toString(36).slice(2, 8);
/* The poster's pieces from back to front: those behind the players, the players, those in front.
   (Spotlight's players are in its card: there, the pieces are only ordered among themselves.) */
const canBehind = (p) => p?.template !== "spotlight";
function pieceStack(p) {
  const els = p?.[PK(p)] || [];
  if (!canBehind(p)) return els.map((e) => e.id);
  return [...els.filter((e) => e.behind).map((e) => e.id), "PLAYERS", ...els.filter((e) => !e.behind).map((e) => e.id)];
}
/* Moves a piece: "forward", "backward", "front" (in front of everything) or "back" (behind everything,
   the players too). Returns where it ended up, in words, or null when it couldn't move. */
function layerPiece(p, id, how) {
  const stack = pieceStack(p), i = stack.indexOf(id);
  if (i < 0) return null;
  let j = { forward: i + 1, backward: i - 1, front: stack.length - 1, back: 0 }[how];
  if (how === "forward" || how === "backward") {  // past the next thing it actually overlaps (else no change shows)
    const dir = how === "forward" ? 1 : -1;
    for (let k = i + dir; k >= 0 && k < stack.length; k += dir) {
      if (stack[k] === "PLAYERS" || piecesOverlap(id, stack[k])) { j = k; break; }
    }
  }
  if (j < 0 || j >= stack.length || j === i) return null;
  stack.splice(i, 1); stack.splice(j, 0, id);
  const els = p[PK(p)], players = stack.indexOf("PLAYERS");
  p[PK(p)] = stack.filter((x) => x !== "PLAYERS").map((x) => els.find((e) => e.id === x));
  if (players >= 0) p[PK(p)].forEach((e) => { e.behind = stack.indexOf(e.id) < players; });
  const el = p[PK(p)].find((e) => e.id === id);
  return players < 0 ? "Moved" : el.behind ? "Behind the players" : "In front of the players";
}
/* Whether two pieces cover any of the same spot on the poster (from where they were last drawn) */
function piecesOverlap(a, b) {
  const box = (id) => {
    const parts = (typeof wordsList !== "undefined" ? wordsList : []).filter((w) => w.key === "el:" + id);
    if (!parts.length) return null;
    return { x0: Math.min(...parts.map((w) => w.x0)), y0: Math.min(...parts.map((w) => w.y0)), x1: Math.max(...parts.map((w) => w.x1)), y1: Math.max(...parts.map((w) => w.y1)) };
  };
  const A = box(a), B = box(b);
  if (!A || !B) return true;  // (not known: treated as overlapping, one step)
  return A.x0 < B.x1 && B.x0 < A.x1 && A.y0 < B.y1 && B.y0 < A.y1;
}
/* The layout's own words that this added piece covers (a ready-made layout draws your pieces over its words) */
function layoutWordsUnder(id) {
  const parts = (typeof wordsList !== "undefined" ? wordsList : []).filter((w) => w.key === "el:" + id);
  if (!parts.length) return [];
  const A = { x0: Math.min(...parts.map((w) => w.x0)), y0: Math.min(...parts.map((w) => w.y0)), x1: Math.max(...parts.map((w) => w.x1)), y1: Math.max(...parts.map((w) => w.y1)) };
  return wordsList.filter((w) => !w.key.startsWith("el:") && w.key !== "logo" && A.x0 < w.x1 && w.x0 < A.x1 && A.y0 < w.y1 && w.y0 < A.y1).map((w) => w.key);
}
/* Forward, backward, front or back, as the eye expects. On a ready-made layout, sending a piece behind
   one of the layout's own words (a banner behind the title) makes the layout your own first, so the
   title becomes a piece it can go behind. */
async function arrangePiece(cur, id, how) {
  const s = slotById(cur.id), p = s.edits?.poster;
  if (!p) return;
  const under = p.template !== "custom" && (how === "backward" || how === "back") ? layoutWordsUnder(id) : [];
  const stack = pieceStack(p), i = stack.indexOf(id);
  const nothingBelow = !stack.slice(0, Math.max(0, i)).some((k) => k === "PLAYERS" || piecesOverlap(id, k));  // (only the layout's words left to go behind)
  if (under.length && (how === "back" || nothingBelow)) {
    const r = await api("/api/poster/customize", { poster: p });
    const els = r.poster.elements || [];
    const me = els.find((e) => e.id === id || e.id === "x" + id);
    if (me) {
      // behind the lowest layout word it covers (its piece now): there, or at the very back
      const words = under.map((k) => String(p[k] ?? "").trim().toUpperCase()).filter(Boolean);
      const targets = els.filter((e) => e !== me && e.type === "text" && words.includes(String(e.text || "").trim().toUpperCase()));
      const rest = els.filter((e) => e !== me);
      let at = how === "back" ? 0 : Math.min(...targets.map((t) => rest.indexOf(t)).filter((x) => x >= 0), rest.length);
      if (how === "back") me.behind = true; else if (targets[0]) me.behind = !!targets[0].behind;
      rest.splice(at, 0, me);
      r.poster.elements = rest;
      st.pieceSel = me.id;
    }
    await changeEdits(s, (ed) => { ed.poster = r.poster; });
    toast(how === "back" ? "Sent to the back" : "Behind the title now", { small: "The layout is now your own, so its words can be layered too. ⌘Z undoes it." });
    return;
  }
  const said = layerPiece(clone(p), id, how);
  editSig = "";
  await changeEdits(s, (ed) => { layerPiece(ed.poster, id, how); });
  if (said) toast(said);
}
function pieceEnds(p, id) {  // [at the very back, at the very front]
  const stack = pieceStack(p), i = stack.indexOf(id);
  return [i === 0, i === stack.length - 1];
}
/* Right-click on a piece: move it forward or back, duplicate or delete it. */
function pieceMenu(e, cur, id) {
  e.preventDefault(); e.stopPropagation();
  closeMenus(); document.querySelector(".ctx-menu")?.remove();
  const p = cur.edits?.poster;
  if (!p) return;
  st.pieceSel = id;
  const [atBack, front] = pieceEnds(p, id), behindOk = canBehind(p), back = atBack && !(p.template !== "custom" && layoutWordsUnder(id).length);
  const it0 = (p[PK(p)] || []).find((x) => x.id === id);
  const items = [["front", "Bring to front", "In front of everything", front], ["forward", "Bring forward", "One step toward the front", front],
    ["backward", "Send backward", behindOk ? "One step back (behind the players, after your other pieces)" : "One step back", back],
    ["back", "Send to back", behindOk ? "Behind everything, the players too" : "Behind your other pieces", back]];
  const m = document.createElement("div");
  m.className = "menu ctx-menu";
  m.innerHTML = items.map(([k, l, sub, no]) => `<button data-layer="${k}" ${no ? "disabled" : ""}><span>${l}</span><small>${sub}</small></button>`).join("")
    + (it0?.type === "card" ? "" : `<hr><button data-turn="90"><span>Turn 90° ↻</span><small>Stand it up the other way</small></button><button data-turn="-90"><span>Turn 90° ↺</span></button>
      <button data-turn="0" ${it0?.angle ? "" : "disabled"}><span>Make it level</span></button>`)
    + `<hr><button data-ctx="dup"><span>Duplicate</span></button><button data-ctx="del"><span>Delete</span></button>`;
  ctxPlace(m, e);
  const close = ctxKeep(m);
  const edit = (fn) => { close(); editSig = ""; changeEdits(slotById(cur.id), (ed) => fn(ed.poster)); };
  m.querySelectorAll("[data-layer]").forEach((b) => b.onclick = () => { close(); arrangePiece(cur, id, b.dataset.layer); });
  m.querySelectorAll("[data-turn]").forEach((b) => b.onclick = () => { close(); editSig = ""; setAngle(cur, id, +b.dataset.turn ? normAngle((it0?.angle || 0) + +b.dataset.turn) : 0); });
  m.querySelector('[data-ctx="dup"]').onclick = () => {
    const nid = newId();
    edit((pp) => { const el = pp[PK(pp)].find((x) => x.id === id); if (el) pp[PK(pp)].push({ ...clone(el), id: nid, x: Math.min(0.95, el.x + 0.04), y: Math.min(0.95, el.y + 0.04) }); });
    st.pieceSel = nid;
  };
  m.querySelector('[data-ctx="del"]').onclick = () => { st.pieceSel = null; edit((pp) => { pp[PK(pp)] = pp[PK(pp)].filter((x) => x.id !== id); }); };
}

/* A right-click menu stays open until you choose, click away or press Escape (not closed by the click
   or redraw that some Macs send right after a right-click). Returns its close(). */
function ctxKeep(m) {
  const opened = Date.now();
  const away = (ev) => { if (!m.contains(ev.target) && (Date.now() - opened > 350 || (ev.button === 0 && !ev.ctrlKey))) close(); };
  const esc = (k) => { if (k.key === "Escape") { k.stopPropagation(); close(); } };
  function close() { m.remove(); document.removeEventListener("pointerdown", away, true); document.removeEventListener("keydown", esc, true); }
  setTimeout(() => { document.addEventListener("pointerdown", away, true); document.addEventListener("keydown", esc, true); }, 0);
  return close;
}
function ctxPlace(m, e) {
  document.body.appendChild(m);
  const r = m.getBoundingClientRect();
  m.style.left = Math.max(8, Math.min(e.clientX, innerWidth - r.width - 8)) + "px";
  m.style.top = Math.max(8, Math.min(e.clientY, innerHeight - r.height - 8)) + "px";
}

/* Right-click on a word of a ready-made layout: the same choices as a piece. Moving it forward or back
   makes the layout your own first (Customize), so it can be layered. */
function wordMenu(e, cur, k) {
  e.preventDefault(); e.stopPropagation();
  document.querySelector(".ctx-menu")?.remove();
  const p = cur.edits?.poster;
  if (!p) return;
  const mv = (p.moves || {})[k] || {}, ang = wordsList.find((w) => w.key === k)?.r || 0;
  const m = document.createElement("div");
  m.className = "menu ctx-menu";
  m.innerHTML = `<button data-w="type"><span>Change the words</span><small>Type over them in the panel</small></button>
    <button data-w="style"><span>Font and color…</span></button><hr>
    ${[["front", "Bring to front"], ["forward", "Bring forward"], ["backward", "Send backward"], ["back", "Send to back"]].map(([h, l]) =>
      `<button data-wl="${h}"><span>${l}</span><small>Makes the layout your own, then moves it</small></button>`).join("")}<hr>
    <button data-wt="90"><span>Turn 90° ↻</span></button><button data-wt="-90"><span>Turn 90° ↺</span></button>
    <button data-wt="0" ${ang ? "" : "disabled"}><span>Make it level</span></button>
    <button data-w="place" ${mv.x || mv.y || (mv.s && mv.s !== 1) || mv.r ? "" : "disabled"}><span>Back to its place</span></button><hr>
    <button data-w="off"><span>Take it off the poster</span><small>Type in its box to put it back</small></button>`;
  ctxPlace(m, e);
  const close = ctxKeep(m);
  const s0 = () => slotById(cur.id);
  m.querySelector('[data-w="type"]').onclick = () => { close(); st.focusField = { k, until: Date.now() + 2500 }; if (st.tool !== "poster") openPart(s0(), "poster"); focusPosterField(k); };
  m.querySelector('[data-w="style"]').onclick = () => { close(); st.stylePk = k; st.colorPk = null; if (st.tool !== "poster") openPart(s0(), "poster"); else { editSig = ""; renderTabs(); } };
  m.querySelectorAll("[data-wt]").forEach((b) => b.onclick = () => { close(); turnWord(s0(), k, +b.dataset.wt ? normAngle(ang + +b.dataset.wt) : 0); });
  m.querySelector('[data-w="place"]').onclick = () => { close(); changeEdits(s0(), (ed) => { if (ed.poster.moves) delete ed.poster.moves[k]; }); };
  m.querySelector('[data-w="off"]').onclick = () => { close(); changeEdits(s0(), (ed) => { ed.poster[k] = ""; }); };
  m.querySelectorAll("[data-wl]").forEach((b) => b.onclick = async () => {
    close();
    const now = s0().edits?.poster, text = String(now?.[k] ?? "").trim().toUpperCase();
    const r = await api("/api/poster/customize", { poster: now });
    const els = r.poster[PK(r.poster)] || [];
    const el = els.find((x) => (x.type === "text" || x.type === "badge") && String(x.text || "").trim().toUpperCase() === text);
    const said = el ? layerPiece(r.poster, el.id, b.dataset.wl) : null;
    st.pieceSel = el?.id || null;
    await changeEdits(s0(), (ed) => { ed.poster = r.poster; });
    toast(said || "Your own layout now", { small: "The layout is now yours: every word is a piece you can layer, move and restyle. ⌘Z undoes it." });
  });
}

/* What "Add" puts on the poster (some add several pieces: a score banner is a panel and its words). */
function piecesToAdd(kind, p) {
  const team = p.color || "#1f2a44";
  switch (kind) {
    case "title": return [{ type: "text", text: "TITLE", style: "heavy", size: 0.2, x: 0.5, y: 0.13, behind: true }];
    case "text": return [{ type: "text", text: "Your words", style: "bold", size: 0.045, x: 0.5, y: 0.86 }];
    case "badge": return [{ type: "badge", text: "7", size: 0.076, x: 0.16, y: 0.24 }];
    case "score": return [
      { type: "box", w: 0.86, h: 0.2, x: 0.5, y: 0.82, color: "#0a0c10", opacity: 0.66, accent: true },
      { type: "text", text: "FINAL", style: "bold", size: 0.026, x: 0.5, y: 0.76 },
      { type: "text", text: "3  –  1", style: "heavy", size: 0.075, x: 0.5, y: 0.83 },
      { type: "text", text: "HOME", style: "clean", size: 0.03, x: 0.22, y: 0.83 },
      { type: "text", text: "AWAY", style: "clean", size: 0.03, x: 0.78, y: 0.83 }];
    case "band": return [{ type: "box", w: 1.1, h: 0.2, x: 0.5, y: 0.13, color: team, opacity: 0.92, round: false, behind: true }];
    case "panel": return [{ type: "box", w: 0.6, h: 0.14, x: 0.5, y: 0.8, color: "#0a0c10", opacity: 0.66 }];
    case "line": return [{ type: "rule", w: 0.3, thick: 0.004, x: 0.5, y: 0.9, color: "#ffffff" }];
    case "logo": return [{ type: "logo", logo: st.kit?.[0]?.id || "", size: 0.13, x: 0.88, y: 0.9 }];
    case "card": return [{ type: "card", w: 0.82, h: 0.6, x: 0.5, y: 0.5 }];
    case "stripes": return [{ type: "stripes", colors: ["#c8102e", "#ffffff", "#0b3d91"], dir: "h", w: 1.1, h: 0.06, x: 0.5, y: 0.035 }];
  }
  return [];
}
const ADD_KINDS = [["title", "Title"], ["text", "Text"], ["badge", "Number"], ["score", "Score banner"], ["band", "Color band"],
  ["panel", "Panel"], ["line", "Line"], ["logo", "Logo"], ["stripes", "Stripes"], ["card", "Photo card"]];

function pieceLabel(el) {
  if (el.type === "text" || el.type === "badge") return (el.text || "").trim() || PIECE_NAMES[el.type];
  if (el.type === "logo") return st.kit?.find((k) => k.id === el.logo)?.name || "Logo";
  if (el.type === "stripes") return `<span class="mini-stripes">${el.colors.map((c) => `<i style="background:${c}"></i>`).join("")}</span>`;
  return PIECE_NAMES[el.type];
}

function customSection(p) {
  const els = p[PK(p)] || [];
  const sel = els.find((x) => x.id === st.pieceSel);
  const sl = (prop, label, min, max, step, v, unit = "") => `<div class="slider"><label>${label}</label><output>${unit === "%" ? Math.round(v * 100) + "%" : (+v).toFixed(2)}</output>
    <input type="range" data-prop="${prop}" data-unit="${unit}" min="${min}" max="${max}" step="${step}" value="${v}"></div>`;
  const colors = (prop, v, auto) => `<div class="swatches word-colors" data-prop-color="${prop}">${auto ? `<button data-v="" class="auto${v ? "" : " on"}" title="${esc(auto)}">A</button>` : ""}${WORD_COLORS.map((c) => `<button data-v="${c}" class="${v === c ? "on" : ""}" style="background:${c}" aria-label="${c}"></button>`).join("")}
    <label class="pick-own" title="Any color"><input type="color" data-prop-own="${prop}" value="${v || "#ffffff"}"></label></div>`;
  const toggle = (prop, label, sub) => `<label class="toggle"><input type="checkbox" data-prop-check="${prop}" ${sel?.[prop] ? "checked" : ""}><span><b>${label}</b>${sub ? `<small>${sub}</small>` : ""}</span></label>`;
  let props = `<p class="notes">Click a piece on the picture, or below, to change it. Drag it to move it; drag its corner to make it bigger or smaller.</p>`;
  if (sel) {
    const t = sel.type;
    props = `<div class="piece-props"><div class="fld"><label>${esc(PIECE_NAMES[t])}</label>
      ${t === "text" ? `<textarea class="field" rows="1" data-prop-text placeholder="Type here" title="Return starts a new line (up to 3)">${esc(sel.text)}</textarea>
        <div class="seg full small" data-prop-style>${PIECE_STYLES.map(([v, l]) => `<button data-v="${v}" class="${sel.style === v ? "on" : ""}">${l}</button>`).join("")}</div>
        <label class="sub-label">Text color</label>${colors("color", sel.color)}${sl("size", "Size", 0.015, 0.4, 0.005, sel.size)}${fontPicker(sel.font, "Style's own")}` : ""}
      ${t === "badge" ? `<input class="field" data-prop-text value="${esc(sel.text)}" maxlength="4" placeholder="Number">
        ${sl("size", "Size", 0.03, 0.25, 0.005, sel.size)}<label class="sub-label">Circle</label>${colors("color", sel.color, "Team color")}<label class="sub-label">Number</label>${colors("ink", sel.ink)}` : ""}
      ${t === "box" ? `${sl("w", "Width", 0.05, 1.1, 0.01, sel.w)}${sl("h", "Height", 0.01, 1, 0.005, sel.h)}${sl("opacity", "Strength", 0.05, 1, 0.05, sel.opacity, "%")}
        ${colors("color", sel.color)}${toggle("round", "Rounded corners")}${toggle("accent", "Team-color edge", "A bar down its left side")}` : ""}
      ${t === "rule" ? `${sl("w", "Length", 0.03, 1.1, 0.01, sel.w)}${sl("thick", "Thickness", 0.001, 0.03, 0.001, sel.thick)}${colors("color", sel.color)}` : ""}
      ${t === "logo" ? `${(st.kit || []).length ? `<div class="kit-grid small" data-prop-logo>${st.kit.map((k) => `<button class="kit-logo${sel.logo === k.id ? " on" : ""}" data-v="${k.id}" title="${esc(k.name)}"><img src="/img/logo/${enc(k.id)}/original.png" alt=""></button>`).join("")}</div>`
        : `<p class="notes">Add a logo with the Logo tool first (SVG, PDF, PNG…).</p>`}${sl("size", "Size", 0.03, 0.6, 0.01, sel.size)}` : ""}
      ${t === "stripes" ? `<div class="stripe-colors">${sel.colors.map((c, i) => `<span class="sc"><button class="color-dot" data-stripe-i="${i}" style="background:${c}" title="Change this color"></button>${sel.colors.length > 2 ? `<button class="x" data-stripe-x="${i}" title="Take this color off">×</button>` : ""}</span>`).join("")}
          ${sel.colors.length < 6 ? `<button class="chip-btn" data-stripe-add title="Another color">${icon("plus")}</button>` : ""}</div>
        ${st.stripeI != null && sel.colors[st.stripeI] ? colors("stripe", sel.colors[st.stripeI]) : ""}
        <div class="seg full small" data-prop-dir><button data-v="h" class="${sel.dir === "h" ? "on" : ""}">Across</button><button data-v="v" class="${sel.dir === "v" ? "on" : ""}">Up and down</button></div>
        ${sl("w", "Width", 0.01, 1.2, 0.01, sel.w)}${sl("h", "Height", 0.005, 1.2, 0.005, sel.h)}${sl("opacity", "Strength", 0.05, 1, 0.05, sel.opacity, "%")}` : ""}
      ${t === "card" ? `${sl("w", "Width", 0.2, 1, 0.01, sel.w)}${sl("h", "Height", 0.2, 1, 0.01, sel.h)}${toggle("border", "White edge")}
        <p class="notes">The photo sits in the card, the player breaking out of its top. Drag the photo in it to move it; Photo zoom is above.</p>` : ""}
      ${t === "card" ? "" : angleControl(sel.angle)}
      ${t === "card" || p.template === "spotlight" ? "" : toggle("behind", "Behind the players", "They stand in front of it. Only the players in the play count: to tuck it behind a teammate, the ball or the goal too, add them with Cut-out → Add")}
      <div class="inline piece-acts"><button class="btn" data-piece-dup>${icon("copy")} Duplicate</button><button class="btn ghost" data-piece-del>${icon("trash")} Delete</button></div>
      </div></div>`;
  }
  const custom = p.template === "custom";
  return `<div class="custom-poster">
    <div class="fld"><label>${custom ? "Add" : "Add to this poster"}</label><div class="add-pieces">${ADD_KINDS.filter(([k]) => custom || k !== "card").map(([k, l]) => `<button class="chip-btn" data-add-piece="${k}">${icon("plus")} ${l}</button>`).join("")}</div></div>
    <div class="fld"><label>Stripes <small class="faint">· across the top; drag them anywhere</small></label><div class="stripe-sets">${STRIPE_SETS.map(([l, cs], i) => `<button data-stripe-set="${i}" title="${esc(l)}">${cs.map((c) => `<i style="background:${c === "team" ? p.color || "#1f2a44" : c}"></i>`).join("")}</button>`).join("")}</div></div>
    ${els.length ? `<div class="pieces">${els.map((el, i) => `<div class="piece-row${el.id === st.pieceSel ? " on" : ""}" data-piece="${el.id}">
      <button class="pick" data-pick-piece="${el.id}"><span class="kind">${esc(PIECE_NAMES[el.type])}</span>${el.type === "text" || el.type === "badge" ? `<span class="what">${esc(pieceLabel(el))}</span>` : el.type === "stripes" ? pieceLabel(el) : ""}${el.behind ? `<span class="behind" title="Behind the players">behind</span>` : ""}</button>
      <button class="icon-btn" data-piece-up="${el.id}" title="Bring forward${canBehind(p) && el.behind ? " (in front of the players next)" : ""} · or right-click it" ${off(pieceEnds(p, el.id)[1], "It's already at the very front.")}>▲</button>
      <button class="icon-btn" data-piece-down="${el.id}" title="Send back${canBehind(p) && !el.behind ? " (behind the players next)" : ""} · or right-click it" ${off(pieceEnds(p, el.id)[0] && !(p.template !== "custom" && layoutWordsUnder(el.id).length), canBehind(p) ? "It's already at the very back, behind the players." : "It's already behind your other pieces.")}>▼</button>
      <button class="icon-btn" data-piece-x="${el.id}" title="Delete">${icon("x")}</button></div>`).join("")}</div>` : `<p class="notes">${custom ? "Nothing on it yet: add a title, a score banner, your logo…" : "Nothing added on top yet. The layout's own words are below."}</p>`}
    ${props}
    ${custom ? "" : "<!--"}${sl("fade_top", "Dark fade at the top", 0, 0.9, 0.05, p.fade_top ?? 0.35, "%").replace('data-prop="fade_top"', 'data-fade="fade_top"')}
    ${sl("fade_bottom", "Dark fade at the bottom", 0, 0.9, 0.05, p.fade_bottom ?? 0.55, "%").replace('data-prop="fade_bottom"', 'data-fade="fade_bottom"')}${custom ? "" : "-->"}
  </div>`;
}

function bindCustom(cur, pane, set) {
  const box = pane.querySelector(".custom-poster");
  if (!box) return;
  const s0 = () => slotById(cur.id);
  const piece = (fn) => set((p) => { const el = (p[PK(p)] || []).find((x) => x.id === st.pieceSel); if (el) fn(el, p); });
  const pieceSoon = (fn, delay = 350) => {  // typing and sliding: shown at once, saved a moment later
    const e2 = clone(s0().edits);
    const el = (e2.poster?.[PK(e2.poster)] || []).find((x) => x.id === st.pieceSel);
    if (!el) return;
    fn(el);
    saveSoon(cur.id, e2, delay);
  };
  box.querySelectorAll("[data-add-piece]").forEach((b) => b.onclick = () => {
    const added = piecesToAdd(b.dataset.addPiece, s0().edits.poster).map((x) => ({ id: newId(), ...x }));
    if (!added.length) return;
    if (b.dataset.addPiece === "logo" && !st.kit?.length) toast("Add a logo with the Logo tool first", { small: "Then pick it here" });
    st.pieceSel = added[added.length - 1].id;
    set((p) => { p[PK(p)] = [...(p[PK(p)] || []), ...added]; });
  });
  box.querySelectorAll("[data-pick-piece]").forEach((b) => b.onclick = () => {
    st.pieceSel = st.pieceSel === b.dataset.pickPiece ? null : b.dataset.pickPiece; editSig = ""; renderTabs(); paintWords(s0());
  });
  const move = (id, by) => arrangePiece(s0(), id, by > 0 ? "forward" : "backward");
  box.querySelectorAll("[data-piece]").forEach((row) => row.oncontextmenu = (e) => pieceMenu(e, s0(), row.dataset.piece));
  box.querySelectorAll("[data-piece-up]").forEach((b) => b.onclick = () => move(b.dataset.pieceUp, 1));
  box.querySelectorAll("[data-piece-down]").forEach((b) => b.onclick = () => move(b.dataset.pieceDown, -1));
  box.querySelectorAll("[data-piece-x]").forEach((b) => b.onclick = () => {
    if (st.pieceSel === b.dataset.pieceX) st.pieceSel = null;
    set((p) => { p[PK(p)] = p[PK(p)].filter((x) => x.id !== b.dataset.pieceX); });
  });
  box.querySelector("[data-piece-del]")?.addEventListener("click", () => {
    const id = st.pieceSel; st.pieceSel = null;
    set((p) => { p[PK(p)] = p[PK(p)].filter((x) => x.id !== id); });
  });
  box.querySelector("[data-piece-dup]")?.addEventListener("click", () => {
    const id = newId(), from = st.pieceSel;  // (the copy is made after the new one is chosen)
    set((p) => {
      const el = p[PK(p)].find((x) => x.id === from);
      if (el) p[PK(p)].push({ ...clone(el), id, x: Math.min(0.95, el.x + 0.04), y: Math.min(0.95, el.y + 0.04) });
    });
    st.pieceSel = id;
  });
  box.querySelectorAll("[data-stripe-set]").forEach((b) => b.onclick = () => {
    const [, cs] = STRIPE_SETS[+b.dataset.stripeSet], team = s0().edits.poster.color || "#1f2a44";
    const id = newId();
    st.pieceSel = id;
    set((p) => { p[PK(p)] = [...(p[PK(p)] || []), { id, type: "stripes", colors: cs.map((c) => (c === "team" ? team : c)), dir: "h", w: 1.1, h: 0.06, x: 0.5, y: 0.035 }]; });
  });
  box.querySelectorAll("[data-stripe-i]").forEach((b) => b.onclick = () => { st.stripeI = st.stripeI === +b.dataset.stripeI ? null : +b.dataset.stripeI; editSig = ""; renderTabs(); });
  box.querySelectorAll("[data-stripe-x]").forEach((b) => b.onclick = () => piece((el) => { el.colors.splice(+b.dataset.stripeX, 1); st.stripeI = null; }));
  box.querySelector("[data-stripe-add]")?.addEventListener("click", () => piece((el) => { el.colors.push("#ffffff"); st.stripeI = el.colors.length - 1; }));
  box.querySelectorAll("[data-prop-dir] button").forEach((b) => b.onclick = () => piece((el) => {
    if (el.dir === b.dataset.v) return;
    el.dir = b.dataset.v;
    if (el.dir === "v") { el.w = 0.08; el.h = 1.2; el.x = 0.06; el.y = 0.5; } else { el.w = 1.1; el.h = 0.06; el.x = 0.5; el.y = 0.035; }
  }));
  const ta = box.querySelector("[data-prop-text]");
  if (ta) {
    ta.oninput = () => pieceSoon((el) => { el.text = ta.value; }, 450);
    if (ta.tagName === "TEXTAREA") { const grow = () => { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; }; grow(); ta.addEventListener("input", grow); }
  }
  box.querySelectorAll("[data-prop-style] button").forEach((b) => b.onclick = () => piece((el) => { el.style = b.dataset.v; }));
  box.querySelectorAll("input[data-prop]").forEach((r) => {
    const out = r.previousElementSibling;
    r.oninput = () => { out.textContent = r.dataset.unit === "%" ? Math.round(r.value * 100) + "%" : (+r.value).toFixed(2); };
    r.onchange = () => pieceSoon((el) => { el[r.dataset.prop] = +r.value; }, 60);
  });
  box.querySelectorAll("input[data-fade]").forEach((r) => {
    const out = r.previousElementSibling;
    r.oninput = () => { out.textContent = Math.round(r.value * 100) + "%"; };
    r.onchange = () => set((p) => { p[r.dataset.fade] = +r.value; });
  });
  const setColor = (el, prop, v) => { if (prop === "stripe") { if (v && st.stripeI != null) el.colors[st.stripeI] = v; } else el[prop] = v; };
  box.querySelectorAll("[data-prop-color] button").forEach((b) => b.onclick = () => piece((el) => setColor(el, b.parentElement.dataset.propColor, b.dataset.v)));
  box.querySelectorAll("[data-prop-own]").forEach((inp) => inp.onchange = () => piece((el) => setColor(el, inp.dataset.propOwn, inp.value)));
  box.querySelectorAll("[data-prop-check]").forEach((c) => c.onchange = () => piece((el) => { el[c.dataset.propCheck] = c.checked; }));
  box.querySelectorAll("[data-prop-logo] button").forEach((b) => b.onclick = () => piece((el) => { el.logo = b.dataset.v; }));
  box.querySelectorAll("[data-font-pick] button").forEach((b) => b.onclick = () => piece((el) => { if (b.dataset.v) el.font = b.dataset.v; else delete el.font; }));
  const id = st.pieceSel;
  bindAngle(box.querySelector(".piece-props"), () => (s0().edits.poster?.[PK(s0().edits.poster)] || []).find((x) => x.id === id)?.angle || 0,
    (a) => { const el = document.querySelector(`.pieces-layer .pc[data-pc="${id}"]`); if (el) el.style.rotate = `${a}deg`; },
    (a) => setAngle(cur, id, a));
}

/* Dragging something on the poster: moved (snapping to the middle) or, by its corner, resized. When let
   go, done(dx, dy, resized, kx, ky, frame box) in screen pixels; nothing if it was only a click. */
function dragPiece(el, f, cur, done, clicked, turned) {
  el.onpointerdown = (e) => {
    if (e.button === 2 || e.ctrlKey) return;  // (right-click: its menu)
    e.preventDefault(); e.stopPropagation();
    if (st.tool !== "poster") { if (el.dataset.pc) st.pieceSel = el.dataset.pc; if (clicked) clicked(); else openPart(cur, "poster"); return; }
    if (turned && e.target.closest(".pc-r")) {  // its round handle: turn it
      return rotateDrag(el, e, parseFloat(el.style.rotate) || 0, (a) => { el.style.rotate = `${a}deg`; }, turned);
    }
    if (el.dataset.pc && st.pieceSel !== el.dataset.pc) {  // chosen: Delete takes it off, the panel shows it
      st.pieceSel = el.dataset.pc;
      f.querySelectorAll(".pc").forEach((x) => x.classList.toggle("sel", x === el));
      f.querySelectorAll(".pc-r").forEach((x) => x.remove());
      if (!el.querySelector(".pc-h")) el.insertAdjacentHTML("beforeend", `<span class="pc-h"></span>`);
      if (turned) el.insertAdjacentHTML("beforeend", turnHandle(el.offsetTop / f.offsetHeight));
    }
    const resize = !!e.target.closest(".pc-h");
    const r = f.getBoundingClientRect(), start = { x: e.clientX, y: e.clientY, l: el.offsetLeft, t: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight };
    let moved = false, dx = 0, dy = 0;
    el.setPointerCapture(e.pointerId);
    el.onpointermove = (m) => {
      dx = m.clientX - start.x; dy = m.clientY - start.y;
      if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
      if (resize) { el.style.width = Math.max(8, start.w + dx) + "px"; el.style.height = Math.max(6, start.h + dy) + "px"; return; }
      let cx = (start.l + start.w / 2 + dx) / r.width;
      if (Math.abs(cx - 0.5) < 0.012) { cx = 0.5; dx = r.width / 2 - start.l - start.w / 2; }
      f.classList.toggle("snap-x", cx === 0.5);
      el.style.left = start.l + dx + "px"; el.style.top = start.t + dy + "px";
    };
    el.onpointerup = () => {
      el.onpointermove = el.onpointerup = null; f.classList.remove("snap-x");
      if (moved) done(dx, dy, resize, Math.max(0.1, (start.w + dx) / start.w), Math.max(0.1, (start.h + dy) / start.h), r);
      else if (clicked) clicked();
    };
  };
}

/* The pieces' outlines on the picture: drag to move, the corner to resize, click to choose. */
function paintPieces(cur, f, boxes) {
  const p = cur.edits?.poster;
  const layer = document.createElement("div");
  layer.className = "pwords pieces-layer" + (st.tool === "poster" ? " live" : "");
  layer.innerHTML = boxes.filter((w) => w.key.startsWith("el:")).map((w) => {
    const id = w.key.slice(3), on = id === st.pieceSel;
    const turns = (p?.[PK(p)] || []).find((x) => x.id === id)?.type !== "card";
    return `<div class="pc${on ? " sel" : ""}" data-pc="${id}" style="left:${w.x0 * 100}%;top:${w.y0 * 100}%;width:${(w.x1 - w.x0) * 100}%;height:${(w.y1 - w.y0) * 100}%${w.r ? `;rotate:${w.r}deg` : ""}">
      ${on ? `<span class="pc-h" data-pc-h="${id}" title="Drag to make it bigger or smaller"></span>${turns ? turnHandle(w.y0) : ""}` : ""}</div>`;
  }).join("");
  f.appendChild(layer);
  layer.querySelectorAll(".pc").forEach((el) => el.oncontextmenu = (e) => pieceMenu(e, slotById(cur.id), el.dataset.pc));
  layer.querySelectorAll(".pc").forEach((el) => el.onpointerdown = (e) => {
    if (e.button === 2 || e.ctrlKey) return;  // (right-click: its menu)
    e.preventDefault(); e.stopPropagation();
    const id = el.dataset.pc, resize = !!e.target.closest(".pc-h");
    if (st.tool !== "poster") { st.pieceSel = id; openPart(cur, "poster"); return; }
    if (e.target.closest(".pc-r")) {  // its round handle: turn it to any angle
      return rotateDrag(el, e, parseFloat(el.style.rotate) || 0, (a) => { el.style.rotate = `${a}deg`; }, (a) => setAngle(cur, id, a));
    }
    if (st.pieceSel !== id) {
      st.pieceSel = id; editSig = ""; renderTabs(); layer.querySelectorAll(".pc").forEach((x) => x.classList.toggle("sel", x.dataset.pc === id));
      requestAnimationFrame(() => $(".piece-props")?.scrollIntoView({ block: "nearest", behavior: "smooth" }));  // (its settings in view)
    }
    const r = f.getBoundingClientRect(), start = { x: e.clientX, y: e.clientY, l: el.offsetLeft, t: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight };
    let moved = false, dx = 0, dy = 0;
    el.setPointerCapture(e.pointerId);
    el.onpointermove = (m) => {
      dx = m.clientX - start.x; dy = m.clientY - start.y;
      if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
      if (resize) {
        el.style.width = Math.max(8, start.w + dx) + "px"; el.style.height = Math.max(6, start.h + dy) + "px";
      } else {
        let cx = (start.l + start.w / 2 + dx) / r.width;
        if (Math.abs(cx - 0.5) < 0.012) { cx = 0.5; dx = r.width / 2 - start.l - start.w / 2; }  // snaps to the middle
        f.classList.toggle("snap-x", cx === 0.5);
        el.style.left = start.l + dx + "px"; el.style.top = start.t + dy + "px";
      }
    };
    el.onpointerup = () => {
      el.onpointermove = el.onpointerup = null; f.classList.remove("snap-x");
      if (!moved) return;
      const kx = Math.max(0.1, (start.w + dx) / start.w), ky = Math.max(0.1, (start.h + dy) / start.h);
      changeEdits(slotById(cur.id), (ed) => {
        const it = (ed.poster?.[PK(ed.poster)] || []).find((x) => x.id === id);
        if (!it) return;
        if (!resize) { it.x += dx / r.width; it.y += dy / r.height; return; }
        const k = Math.max(kx, ky);
        if (it.type === "box" || it.type === "card" || it.type === "stripes") { it.w *= kx; it.h *= ky; } else if (it.type === "rule") { it.w *= kx; } else { it.size *= k; }
      }, { keepPane: false });
    };
  });
}

function setAngle(cur, id, a) {  // (kept on the poster: a long piece stood up near an edge is moved in)
  const p = slotById(cur.id).edits?.poster, kind = (p?.[PK(p)] || []).find((x) => x.id === id)?.type;
  const [dx, dy] = ["text", "badge", "logo"].includes(kind) ? keepOn(wordsList.find((w) => w.key === "el:" + id), a) : [0, 0];  // (bands may run past the edges)
  changeEdits(slotById(cur.id), (ed) => {
    const it = (ed.poster?.[PK(ed.poster)] || []).find((x) => x.id === id);
    if (it) { if (a) it.angle = a; else delete it.angle; it.x += dx; it.y += dy; }
  });
}

/* Arrow keys nudge what's chosen on the picture (Shift: bigger steps): a poster's word or logo, a piece
   (a band, stripes, a badge…), or a text or logo put on the picture. They do while the last thing you
   clicked was the picture, even when that click put the cursor in the word's box; once you click in
   a box or type, they move the cursor again. Delete takes the chosen thing off (not while typing). */
document.addEventListener("pointerdown", (e) => {
  if (e.target.closest?.("#frame, #texts")) st.nudgeArmed = true;
  else if (e.target.closest?.("input, textarea, [contenteditable], select")) st.nudgeArmed = false;
}, true);
document.addEventListener("input", (e) => { if (e.target.closest?.("input:not([type=range]), textarea, [contenteditable]")) st.nudgeArmed = false; }, true);

function nudgeChosen(cur, dx, dy) {
  const e2 = clone(cur.edits), p = e2.poster, sel = st.pieceSel;
  const shift = (q) => document.querySelectorAll(q).forEach((el) => {  // (its outline moves at once; the picture follows)
    if (el.style.left.endsWith("%")) el.style.left = parseFloat(el.style.left) + dx * 100 + "%";
    if (el.style.top.endsWith("%")) el.style.top = parseFloat(el.style.top) + dy * 100 + "%";
  });
  const clamp = (v) => Math.max(0, Math.min(1, v));
  let done = false;
  if (st.tool === "poster" && sel && p) {
    if (sel.startsWith("w:")) {
      const k = sel.slice(2), m = { x: 0, y: 0, s: 1, ...((p.moves || {})[k] || {}) };
      m.x += dx; m.y += dy;
      p.moves = { ...(p.moves || {}), [k]: m };
      done = true;
    } else if (sel === "logo" && p.template !== "custom") {
      const w = wordsList.find((x) => x.key === "logo");
      const at = p.logo_at || (w && { x: (w.x0 + w.x1) / 2, y: (w.y0 + w.y1) / 2, size: w.x1 - w.x0 });
      if (at) { p.logo_at = { ...at, x: at.x + dx, y: at.y + dy }; done = true; }
    } else {
      const it = (p[PK(p)] || []).find((x) => x.id === sel);
      if (it) { it.x += dx; it.y += dy; done = true; }
    }
    if (done) shift(`.pc[data-pc="${CSS.escape(sel)}"]`);
  } else if (st.tool === "text" && st.textSel != null && e2.texts?.[st.textSel]) {
    const t = e2.texts[st.textSel];
    t.x = clamp(t.x + dx); t.y = clamp(t.y + dy); done = true;
    shift(`#texts .tx[data-i="${st.textSel}"]`);
  } else if (st.tool === "logo" && st.logoSel != null && e2.logos?.[st.logoSel]) {
    const l = e2.logos[st.logoSel];
    l.x = clamp(l.x + dx); l.y = clamp(l.y + dy); done = true;
    shift(`#texts .lg[data-li="${st.logoSel}"]`);
  }
  if (done) saveSoon(cur.id, e2, 250);
  return done;
}

document.addEventListener("keydown", (e) => {
  if (e.target.closest?.("#look-grid, #look-search")) return;  // (the looks list has its own arrows)
  const arrow = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
  const typing = e.target.closest?.("input, textarea, [contenteditable], select");
  if ((typing && !(arrow && st.nudgeArmed && !e.target.matches?.("[type=range]"))) || e.metaKey || e.ctrlKey || e.altKey) return;
  const cur = slotById(st.current);
  if (!cur?.edits || cur.state !== "done") return;
  if (arrow) {
    const step = e.shiftKey ? 0.02 : 0.004;
    if (nudgeChosen(cur, arrow[0] * step, arrow[1] * step)) { e.preventDefault(); e.stopPropagation(); }
    return;
  }
  if (typing) return;
  const del = e.key === "Delete" || e.key === "Backspace";
  if (st.tool === "poster" && st.pieceSel?.startsWith("w:") && cur.edits.poster && del) {
    e.preventDefault(); e.stopPropagation();
    const k = st.pieceSel.slice(2); st.pieceSel = null;
    changeEdits(cur, (ed) => { ed.poster[k] = ""; });
    toast("Taken off the poster", { small: "Type in its box to put it back, or ⌘Z" });
    return;
  }
  if (st.tool === "poster" && st.pieceSel === "logo" && cur.edits.poster && cur.edits.poster.template !== "custom") {
    if (!del) return;
    e.preventDefault(); e.stopPropagation(); st.pieceSel = null;
    changeEdits(cur, (ed) => { ed.poster.logo = ""; delete ed.poster.logo_at; });
    toast("Logo taken off the poster", { small: "⌘Z puts it back · pick one again in the Poster panel" });
    return;
  }
  if (st.tool === "poster" && st.pieceSel && cur.edits.poster?.[PK(cur.edits.poster)]) {
    if (del) {
      e.preventDefault(); e.stopPropagation();
      const id = st.pieceSel; st.pieceSel = null;
      changeEdits(cur, (ed) => { ed.poster[PK(ed.poster)] = ed.poster[PK(ed.poster)].filter((x) => x.id !== id); });
    }
    return;
  }
  if (del && st.tool === "text" && st.textSel != null && cur.edits.texts?.[st.textSel]) {
    e.preventDefault(); e.stopPropagation();
    const i = st.textSel; st.textSel = null;
    changeEdits(cur, (ed) => { ed.texts.splice(i, 1); });
  } else if (del && st.tool === "logo" && st.logoSel != null && cur.edits.logos?.[st.logoSel]) {
    e.preventDefault(); e.stopPropagation();
    const i = st.logoSel; st.logoSel = null;
    changeEdits(cur, (ed) => { ed.logos.splice(i, 1); });
  }
}, true);

/* A team's posters: the same design for each player, only their picture, name and number changed. */
const NAME_KEY = { spotlight: "title", name: "title", teamcolor: "title", goal: "name", mvp: "line",
  jersey: "title", cover: "name", split: "title", card: "title", cinematic: "title",
  banner: "name", smoke: "name", featured: "name", storm: "title",
  fillband: "title", lowerthird: "title", knockout: "title", sidelabel: "title", cornertag: "name", outlinestack: "title", frosted: "title" };
const NUMBER_KEY = { spotlight: "number", jersey: "number", split: "number", card: "number", featured: "number", storm: "number" };
function playerFields(p) {  // (as the app finds them: see poster.player_fields)
  const out = {};
  if (!p) return out;
  if (p.template === "custom") {
    const els = p.elements || [];
    let texts = els.filter((e) => e.type === "text" && ["heavy", "outline"].includes(e.style));
    if (!texts.length) texts = els.filter((e) => e.type === "text");
    if (texts.length) { const big = texts.reduce((a, b) => (b.size > a.size ? b : a)); out.name = { el: big.id, value: big.text || "" }; }
    const badge = els.find((e) => e.type === "badge");
    if (badge) out.number = { el: badge.id, value: badge.text || "" };
    return out;
  }
  if (NAME_KEY[p.template]) out.name = { key: NAME_KEY[p.template], value: p[NAME_KEY[p.template]] || "" };
  if (NUMBER_KEY[p.template]) out.number = { key: NUMBER_KEY[p.template], value: p[NUMBER_KEY[p.template]] || "" };
  return out;
}
function setPlayerField(p, which, value) {
  const f = playerFields(p)[which];
  if (!f) return;
  if (f.el) { const e = p.elements.find((x) => x.id === f.el); if (e) e.text = value; } else p[f.key] = value;
}
const familyOf = (p) => p?.family || null;
const familySlots = (family) => st.slots.filter((s) => s.state !== "failed" && familyOf(s.edits?.poster) === family);

function teamSection(cur, p) {
  const others = st.photos.filter((x) => x.id !== cur.photo);
  const family = familyOf(p);
  const fields = playerFields(p);
  let html = "";
  if (family) {
    const mates = familySlots(family);
    html += `<div class="team-box"><h4 class="sub">This poster for the team <small>${mates.length} players · type each name and number</small></h4>
      <div class="team-list">${mates.map((s) => {
        const pf = playerFields(s.edits?.poster);
        const photo = st.photos.find((x) => x.id === s.photo);
        return `<div class="team-row${s.id === cur.id ? " on" : ""}" data-team-slot="${s.id}">
          <button class="team-pic" data-open-slot="${s.id}" title="Open this one: drag the photo to place this player">${s.state === "done" ? `<img src="${slotImg(s, "thumb")}" alt="">` : `<span class="spin"></span>`}</button>
          ${pf.name ? `<input class="field" data-team-name="${s.id}" value="${esc(pf.name.value === "NAME" ? "" : pf.name.value)}" placeholder="Name" aria-label="Name for ${esc(photo?.name || "")}">` : ""}
          ${pf.number ? `<input class="field num" data-team-number="${s.id}" value="${esc(pf.number.value)}" placeholder="#" maxlength="4" aria-label="Number">` : ""}
          </div>`;
      }).join("")}</div>
      ${others.length > mates.length - 1 ? `<button class="btn wide" id="pp-team">${icon("layers")} Add more players…</button>` : ""}
      <p class="notes">Numbers are read off each player's shirt (check them). Click a picture to open it and drag the photo to place that player.</p></div>`;
  } else if (others.length) {
    html += `<button class="btn primary wide team-cta" id="pp-team" title="The same poster for other players: only their photo, name and number change">${icon("layers")} Make this poster for the team</button>`;
  }
  if (!fields.name && !fields.number && family) html += `<p class="notes">This layout has no player name or number: each poster keeps the same words.</p>`;
  return html;
}

function bindTeam(cur, pane) {
  $("#pp-team", pane)?.addEventListener("click", () => openTeamPicker(cur));
  pane.querySelectorAll("[data-open-slot]").forEach((b) => b.onclick = () => { select(+b.dataset.openSlot); st.tab = "edit"; st.tool = "poster"; viewerSig = ""; editSig = ""; render(); });
  const typing = new Map();
  const onType = (inp, which) => {
    const sid = +(inp.dataset.teamName || inp.dataset.teamNumber);
    inp.oninput = () => {
      clearTimeout(typing.get(inp));
      typing.set(inp, setTimeout(() => {
        const s = slotById(sid);
        if (!s?.edits?.poster) return;
        const e2 = clone(s.edits);
        setPlayerField(e2.poster, which, inp.value.trim() || (which === "name" ? "NAME" : ""));
        saveSoon(sid, e2, 10);
      }, 350));
    };
    inp.onkeydown = (ev) => {  // Return: the next player's box
      if (ev.key !== "Enter") return;
      ev.preventDefault();
      const all = [...pane.querySelectorAll(`[data-team-${which}]`)], i = all.indexOf(inp);
      (all[i + 1] || all[0])?.focus();
    };
  };
  pane.querySelectorAll("[data-team-name]").forEach((i) => onType(i, "name"));
  pane.querySelectorAll("[data-team-number]").forEach((i) => onType(i, "number"));
}

function openTeamPicker(cur) {
  const p = cur.edits?.poster, family = familyOf(p);
  const have = new Set(family ? familySlots(family).map((s) => s.photo) : [cur.photo]);
  const choices = st.photos.filter((x) => !have.has(x.id));
  if (!choices.length) { toast("Every photo already has this poster"); return; }
  const chosen = new Set(choices.map((x) => x.id));
  const m = modal(`<header><h2>This poster for the team</h2><p class="notes" style="margin:4px 0 0">The same design (${esc(cur.look)}) on each photo you pick. Each player's number is read off their shirt; you type the names after.</p></header>
    <div class="body"><div class="team-pick">${choices.map((x) => `<button class="tp on" data-tp="${x.id}"><img src="/img/photo/${x.id}/thumb.jpg" alt=""><span class="check"></span><small>${esc(x.name)}</small></button>`).join("")}</div></div>
    <footer><button class="btn ghost" id="tp-none">Pick none</button><span style="flex:1"></span><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="tp-go"></button></footer>`);
  const paint = () => {
    m.querySelectorAll("[data-tp]").forEach((b) => b.classList.toggle("on", chosen.has(+b.dataset.tp)));
    const go = $("#tp-go", m);
    go.textContent = `Make ${plural(chosen.size, "poster")}`;
    setOff(go, !chosen.size, "Pick at least one photo above.");
    $("#tp-none", m).textContent = chosen.size ? "Pick none" : "Pick all";
  };
  m.querySelectorAll("[data-tp]").forEach((b) => b.onclick = () => { const id = +b.dataset.tp; chosen.has(id) ? chosen.delete(id) : chosen.add(id); paint(); });
  $("#tp-none", m).onclick = () => { if (chosen.size) chosen.clear(); else choices.forEach((x) => chosen.add(x.id)); paint(); };
  $("#tp-go", m).onclick = async () => {
    if (!chosen.size) return;
    closeModal();
    await api(`/api/slots/${cur.id}/team`, { photos: [...chosen] });
    await refresh();
    editSig = ""; renderTabs();
    toast(`Making ${plural(chosen.size, "poster")} for the team…`, { small: "Type each player's name in the Poster panel as they come in" });
  };
  paint();
}

/* "In this poster": its photo and its look, each changed in one click (the words, logo and pieces stay). */
function inThisPoster(cur) {
  const photo = st.photos.find((x) => x.id === cur.photo);
  return `<div class="in-poster"><img src="/img/photo/${cur.photo}/thumb.jpg" alt="">
    <div class="ip-text"><b>${esc(photo?.name || "Photo")}</b><small>Look: ${esc(cur.look === "Original" || cur.look === "Poster" ? "the photo as it is" : cur.look)}</small></div>
    <div class="ip-acts"><button class="btn" id="ip-photo" title="Put another photo in this poster: its words, logo and pieces stay">${icon("image")} Change photo…</button>
      <button class="btn" id="ip-look" title="This poster with another look on the photo">${icon("sun")} Change look…</button></div></div>`;
}
function bindInThisPoster(cur, pane) {
  $("#ip-photo", pane)?.addEventListener("click", () => pickPhotoForPoster(cur));
  $("#ip-look", pane)?.addEventListener("click", () => pickLookForPoster(cur));
}
async function swapInto(cur, body, what) {
  const r = await api(`/api/slots/${cur.id}/swap`, body);
  await refresh();
  select(r.slot); st.tab = "edit"; st.editWhenReady = r.slot; st.toolWhenReady = "poster";
  render();
  toast(`The poster with ${what}`, { small: "Your first one is kept too (it's next to it in the strip)" });
}
function pickPhotoForPoster(cur) {
  const others = st.photos.filter((x) => x.id !== cur.photo);
  const m = modal(`<header><h2>Put another photo in this poster</h2><p class="notes" style="margin:4px 0 0">Its words, logo and pieces stay; the photo is framed on its player (drag it to adjust).</p></header>
    <div class="body">${others.length ? `<div class="team-pick">${others.map((x) => `<button class="tp" data-swap-photo="${x.id}"><img src="/img/photo/${x.id}/thumb.jpg" alt=""><small>${esc(x.name)}</small></button>`).join("")}</div>`
      : `<p class="notes">No other photos yet.</p>`}</div>
    <footer><button class="btn" id="ip-add">${icon("plus")} Add photos…</button><span style="flex:1"></span><button class="btn ghost" data-close>Cancel</button></footer>`);
  m.querySelectorAll("[data-swap-photo]").forEach((b) => b.onclick = () => { closeModal(); swapInto(cur, { photo: +b.dataset.swapPhoto }, "the new photo"); });
  $("#ip-add", m).onclick = async () => {
    closeModal();
    const added = await addPhotos("files");
    if (added?.length) { await refresh(); swapInto(cur, { photo: added[0] }, "the new photo"); }
  };
}
function pickLookForPoster(cur) {
  const looks = st.looks.filter((l) => !l.design && !l.own);
  const m = modal(`<header><h2>This poster with another look</h2><p class="notes" style="margin:4px 0 0">The same photo and poster; the look you pick on the photo.</p></header>
    <div class="body"><div class="team-pick">
      <button class="tp" data-swap-look="Original"><img src="/img/photo/${cur.photo}/thumb.jpg" alt=""><small>The photo as it is</small></button>
      ${looks.map((l) => `<button class="tp" data-swap-look="${esc(l.name)}"><img src="/img/example/${enc(l.name)}.jpg?v=${pageStamp}" alt="" onerror="this.style.visibility='hidden'"><small>${esc(l.name)}${l.ai ? " · AI" : ""}</small></button>`).join("")}
    </div></div><footer><button class="btn ghost" data-close>Cancel</button></footer>`);
  m.querySelectorAll("[data-swap-look]").forEach((b) => b.onclick = () => { closeModal(); swapInto(cur, { look: b.dataset.swapLook }, b.dataset.swapLook === "Original" ? "the photo as it is" : b.dataset.swapLook); });
}

/* Dropped on the picture: your logos (dragged from the kit) and logo files go on it where they land;
   a photo dropped on a poster asks once: the poster's new photo, or a graphic on it. */
document.addEventListener("dragstart", (e) => {
  const k = e.target.closest?.(".kit-logo[data-kit]");
  if (k) { e.dataTransfer.setData("application/x-allpro-logo", k.dataset.kit); e.dataTransfer.effectAllowed = "copy"; }
});
async function droppedOnPicture(e) {
  const cur = slotById(st.current), f = $("#frame");
  if (!cur || cur.state !== "done" || !f || st.mode !== "edit") return false;
  const r = f.getBoundingClientRect();
  const at = { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height };
  const kitId = e.dataTransfer?.getData("application/x-allpro-logo");
  if (kitId) { placeGraphic(cur, kitId, at); return true; }
  const files = [...(e.dataTransfer?.files || [])].filter((x) => x.type.startsWith("image/") || /\.(svgz?|pdf|ai|heic|png|jpe?g|webp)$/i.test(x.name));
  if (!files.length) return false;
  const file = files[0];
  const drawn = /\.(svgz?|pdf|ai)$/i.test(file.name) || file.type === "image/svg+xml";
  let as = "graphic";
  if (!drawn) as = await askDrop(cur, file);
  if (!as) return true;
  if (as === "photo") {
    const added = await upload([file]);
    if (added?.length) { await refresh(); if (cur.edits?.poster) swapInto(cur, { photo: added[0] }, "the new photo"); }
    return true;
  }
  const meta = await addLogo(file, true);
  if (meta?.id) placeGraphic(cur, meta.id, at);
  return true;
}
function askDrop(cur, file) {
  return new Promise((resolve) => {
    const poster = !!cur.edits?.poster;
    const m = modal(`<header><h2>${esc(file.name)}</h2></header><div class="body"><p>What should it be?</p></div>
      <footer><button class="btn ghost" data-close>Cancel</button><span style="flex:1"></span>
        <button class="btn" id="dz-graphic">${icon("badge")} A logo or graphic on the picture</button>
        <button class="btn primary" id="dz-photo">${icon("image")} ${poster ? "The photo in this poster" : "A new photo"}</button></footer>`);
    $("#dz-graphic", m).onclick = () => { closeModal(); resolve("graphic"); };
    $("#dz-photo", m).onclick = () => { closeModal(); resolve("photo"); };
    m.querySelector("[data-close]").addEventListener("click", () => resolve(null));
  });
}
function placeGraphic(cur, id, at) {
  const art = (st.kit || []).find((k) => k.id === id);
  const size = 0.18;
  changeEdits(slotById(cur.id), (ed) => {
    if (ed.poster) {  // on a poster: one of its pieces (drag it, its corner resizes it, Delete takes it off)
      const k = PK(ed.poster);
      ed.poster[k] = [...(ed.poster[k] || []), { id: newId(), type: "logo", logo: id, size, x: at.x, y: at.y }];
      if (st.tool !== "poster") st.toolWhenReady = "poster";
    } else {
      ed.logos = [...(ed.logos || []), { id, x: at.x, y: at.y, size, color: art?.flat ? "auto" : "original", opacity: 1 }];
    }
  });
  toast(`${art?.name || "Logo"} placed`, { small: "Drag it to move it, its corner to resize it · Delete takes it off" });
}

/* ⌘C / ⌘V copy and paste the chosen poster piece (a banner, a band, text, a badge, stripes…); ⌘D
   duplicates it. The copy lands a little down and right, chosen, ready to drag. A layout's own word
   is copied as a text piece with its words. (The Mac app sends ⌘V as a paste, so that is caught too.) */
function copyPiece(cur) {
  const p = cur.edits?.poster;
  if (!p || !st.pieceSel) return false;
  if (st.pieceSel.startsWith("w:")) {
    const k = st.pieceSel.slice(2), text = String(p[k] ?? "").trim();
    if (!text) return false;
    const w = wordsList.find((x) => x.key === k);
    st.pieceClip = { type: "text", text, style: "heavy", size: w ? Math.max(0.03, Math.min(0.3, (w.y1 - w.y0) / (text.split("\n").length) * 0.9)) : 0.08,
      x: w ? (w.x0 + w.x1) / 2 : 0.5, y: w ? (w.y0 + w.y1) / 2 : 0.5, color: (p.colors || {})[k] || "#ffffff" };
    return true;
  }
  const el = (p[PK(p)] || []).find((x) => x.id === st.pieceSel);
  if (!el) return false;
  st.pieceClip = clone(el);
  return true;
}
function pastePiece(cur) {
  if (!st.pieceClip || !cur.edits?.poster) return false;
  const nid = newId(), el = { ...clone(st.pieceClip), id: nid };
  el.x = Math.min(0.95, (el.x ?? 0.5) + 0.03); el.y = Math.min(0.95, (el.y ?? 0.5) + 0.03);
  st.pieceClip = { ...st.pieceClip, x: el.x, y: el.y };  // (the next paste lands further on)
  st.pieceSel = nid; editSig = "";
  changeEdits(cur, (ed) => { const pp = ed.poster; pp[PK(pp)] = [...(pp[PK(pp)] || []), el]; });
  toast("Pasted", { small: "Drag it into place · ⌘Z takes it back" });
  return true;
}
const typingSomewhere = (e) => !!e.target.closest?.("input, textarea, [contenteditable]");
document.addEventListener("keydown", (e) => {
  if (!(e.metaKey || e.ctrlKey) || e.altKey || typingSomewhere(e) || st.tool !== "poster") return;
  const cur = slotById(st.current), k = e.key.toLowerCase();
  if (!cur?.edits?.poster || cur.state !== "done") return;
  if (k === "c" && !String(window.getSelection()) && copyPiece(cur)) { e.preventDefault(); e.stopImmediatePropagation(); toast("Copied", { small: "⌘V pastes it · ⌘D duplicates in one go" }); }
  else if (k === "v" && st.pieceClip && pastePiece(cur)) { e.preventDefault(); e.stopImmediatePropagation(); }
  else if (k === "d" && copyPiece(cur)) { e.preventDefault(); e.stopImmediatePropagation(); pastePiece(cur); }
}, true);
document.addEventListener("paste", (e) => {
  if (typingSomewhere(e) || st.tool !== "poster" || !st.pieceClip) return;
  if ([...(e.clipboardData?.items || [])].some((it) => it.kind === "file")) return;  // (a picture pasted: the app's own paste)
  const cur = slotById(st.current);
  if (cur?.state === "done" && pastePiece(cur)) { e.preventDefault(); e.stopImmediatePropagation(); }
}, true);
