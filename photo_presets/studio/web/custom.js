/* AllProPhoto: the custom poster. Your own layout from the same pieces the ready-made ones use
   (text in any style, a number badge, a panel or band, a line, a logo), each moved by dragging it
   on the picture, resized by its corner, changed in the panel, in front of the players or behind
   them. The app draws the poster (what you see is what is exported); the page draws only the
   outlines you drag. Loaded after edit.js, whose helpers it uses. */

const PIECE_NAMES = { text: "Text", badge: "Number", box: "Panel", rule: "Line", logo: "Logo", card: "Photo card" };
const PIECE_STYLES = [["heavy", "Heavy"], ["bold", "Bold"], ["clean", "Clean"], ["spaced", "Spaced"], ["outline", "Outline"], ["banner", "Banner"]];
const newId = () => "p" + Math.random().toString(36).slice(2, 8);

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
  }
  return [];
}
const ADD_KINDS = [["title", "Title"], ["text", "Text"], ["badge", "Number"], ["score", "Score banner"], ["band", "Color band"],
  ["panel", "Panel"], ["line", "Line"], ["logo", "Logo"], ["card", "Photo card"]];

function pieceLabel(el) {
  if (el.type === "text" || el.type === "badge") return (el.text || "").trim() || PIECE_NAMES[el.type];
  if (el.type === "logo") return st.kit?.find((k) => k.id === el.logo)?.name || "Logo";
  return PIECE_NAMES[el.type];
}

function customSection(p) {
  const els = p.elements || [];
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
      ${t === "text" ? `<textarea class="field" rows="1" data-prop-text placeholder="Type here">${esc(sel.text)}</textarea>
        <div class="seg full small" data-prop-style>${PIECE_STYLES.map(([v, l]) => `<button data-v="${v}" class="${sel.style === v ? "on" : ""}">${l}</button>`).join("")}</div>
        ${sl("size", "Size", 0.015, 0.4, 0.005, sel.size)}${colors("color", sel.color)}` : ""}
      ${t === "badge" ? `<input class="field" data-prop-text value="${esc(sel.text)}" maxlength="4" placeholder="Number">
        ${sl("size", "Size", 0.03, 0.25, 0.005, sel.size)}<label class="sub-label">Circle</label>${colors("color", sel.color, "Team color")}<label class="sub-label">Number</label>${colors("ink", sel.ink)}` : ""}
      ${t === "box" ? `${sl("w", "Width", 0.05, 1.1, 0.01, sel.w)}${sl("h", "Height", 0.01, 1, 0.005, sel.h)}${sl("opacity", "Strength", 0.05, 1, 0.05, sel.opacity, "%")}
        ${colors("color", sel.color)}${toggle("round", "Rounded corners")}${toggle("accent", "Team-color edge", "A bar down its left side")}` : ""}
      ${t === "rule" ? `${sl("w", "Length", 0.03, 1.1, 0.01, sel.w)}${sl("thick", "Thickness", 0.001, 0.03, 0.001, sel.thick)}${colors("color", sel.color)}` : ""}
      ${t === "logo" ? `${(st.kit || []).length ? `<div class="kit-grid small" data-prop-logo>${st.kit.map((k) => `<button class="kit-logo${sel.logo === k.id ? " on" : ""}" data-v="${k.id}" title="${esc(k.name)}"><img src="/img/logo/${enc(k.id)}/original.png" alt=""></button>`).join("")}</div>`
        : `<p class="notes">Add a logo with the Logo tool first (SVG, PDF, PNG…).</p>`}${sl("size", "Size", 0.03, 0.6, 0.01, sel.size)}` : ""}
      ${t === "card" ? `${sl("w", "Width", 0.2, 1, 0.01, sel.w)}${sl("h", "Height", 0.2, 1, 0.01, sel.h)}${toggle("border", "White edge")}
        <p class="notes">The photo sits in the card, the player breaking out of its top. Drag the photo in it to move it; Photo zoom is above.</p>` : ""}
      ${t === "card" ? "" : toggle("behind", "Behind the players", "They stand in front of it")}
      <div class="inline piece-acts"><button class="btn" data-piece-dup>${icon("copy")} Duplicate</button><button class="btn ghost" data-piece-del>${icon("trash")} Delete</button></div>
      </div></div>`;
  }
  return `<div class="custom-poster">
    <div class="fld"><label>Add</label><div class="add-pieces">${ADD_KINDS.map(([k, l]) => `<button class="chip-btn" data-add-piece="${k}">${icon("plus")} ${l}</button>`).join("")}</div></div>
    ${els.length ? `<div class="pieces">${els.map((el, i) => `<div class="piece-row${el.id === st.pieceSel ? " on" : ""}" data-piece="${el.id}">
      <button class="pick" data-pick-piece="${el.id}"><span class="kind">${esc(PIECE_NAMES[el.type])}</span>${el.type === "text" || el.type === "badge" ? `<span class="what">${esc(pieceLabel(el))}</span>` : ""}${el.behind ? `<span class="behind" title="Behind the players">behind</span>` : ""}</button>
      <button class="icon-btn" data-piece-up="${el.id}" title="Bring forward" ${off(i === els.length - 1, "It's already in front of the others.")}>▲</button>
      <button class="icon-btn" data-piece-down="${el.id}" title="Send back" ${off(i === 0, "It's already behind the others.")}>▼</button>
      <button class="icon-btn" data-piece-x="${el.id}" title="Delete">${icon("x")}</button></div>`).join("")}</div>` : `<p class="notes">Nothing on it yet: add a title, a score banner, your logo…</p>`}
    ${props}
    ${sl("fade_top", "Dark fade at the top", 0, 0.9, 0.05, p.fade_top ?? 0.35, "%").replace('data-prop="fade_top"', 'data-fade="fade_top"')}
    ${sl("fade_bottom", "Dark fade at the bottom", 0, 0.9, 0.05, p.fade_bottom ?? 0.55, "%").replace('data-prop="fade_bottom"', 'data-fade="fade_bottom"')}
  </div>`;
}

function bindCustom(cur, pane, set) {
  const box = pane.querySelector(".custom-poster");
  if (!box) return;
  const s0 = () => slotById(cur.id);
  const piece = (fn) => set((p) => { const el = (p.elements || []).find((x) => x.id === st.pieceSel); if (el) fn(el, p); });
  const pieceSoon = (fn, delay = 350) => {  // typing and sliding: shown at once, saved a moment later
    const e2 = clone(s0().edits);
    const el = (e2.poster?.elements || []).find((x) => x.id === st.pieceSel);
    if (!el) return;
    fn(el);
    saveSoon(cur.id, e2, delay);
  };
  box.querySelectorAll("[data-add-piece]").forEach((b) => b.onclick = () => {
    const added = piecesToAdd(b.dataset.addPiece, s0().edits.poster).map((x) => ({ id: newId(), ...x }));
    if (!added.length) return;
    if (b.dataset.addPiece === "logo" && !st.kit?.length) toast("Add a logo with the Logo tool first", { small: "Then pick it here" });
    st.pieceSel = added[added.length - 1].id;
    set((p) => { p.elements = [...(p.elements || []), ...added]; });
  });
  box.querySelectorAll("[data-pick-piece]").forEach((b) => b.onclick = () => {
    st.pieceSel = st.pieceSel === b.dataset.pickPiece ? null : b.dataset.pickPiece; editSig = ""; renderTabs(); paintWords(s0());
  });
  const move = (id, by) => set((p) => {
    const i = p.elements.findIndex((x) => x.id === id), j = i + by;
    if (i < 0 || j < 0 || j >= p.elements.length) return;
    [p.elements[i], p.elements[j]] = [p.elements[j], p.elements[i]];
  });
  box.querySelectorAll("[data-piece-up]").forEach((b) => b.onclick = () => move(b.dataset.pieceUp, 1));
  box.querySelectorAll("[data-piece-down]").forEach((b) => b.onclick = () => move(b.dataset.pieceDown, -1));
  box.querySelectorAll("[data-piece-x]").forEach((b) => b.onclick = () => {
    if (st.pieceSel === b.dataset.pieceX) st.pieceSel = null;
    set((p) => { p.elements = p.elements.filter((x) => x.id !== b.dataset.pieceX); });
  });
  box.querySelector("[data-piece-del]")?.addEventListener("click", () => {
    const id = st.pieceSel; st.pieceSel = null;
    set((p) => { p.elements = p.elements.filter((x) => x.id !== id); });
  });
  box.querySelector("[data-piece-dup]")?.addEventListener("click", () => {
    const id = newId();
    set((p) => {
      const el = p.elements.find((x) => x.id === st.pieceSel);
      if (el) p.elements.push({ ...clone(el), id, x: Math.min(0.95, el.x + 0.04), y: Math.min(0.95, el.y + 0.04) });
    });
    st.pieceSel = id;
  });
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
  box.querySelectorAll("[data-prop-color] button").forEach((b) => b.onclick = () => piece((el) => { el[b.parentElement.dataset.propColor] = b.dataset.v; }));
  box.querySelectorAll("[data-prop-own]").forEach((inp) => inp.onchange = () => piece((el) => { el[inp.dataset.propOwn] = inp.value; }));
  box.querySelectorAll("[data-prop-check]").forEach((c) => c.onchange = () => piece((el) => { el[c.dataset.propCheck] = c.checked; }));
  box.querySelectorAll("[data-prop-logo] button").forEach((b) => b.onclick = () => piece((el) => { el.logo = b.dataset.v; }));
}

/* Dragging something on the poster: moved (snapping to the middle) or, by its corner, resized. When let
   go, done(dx, dy, resized, kx, ky, frame box) in screen pixels; nothing if it was only a click. */
function dragPiece(el, f, cur, done) {
  el.onpointerdown = (e) => {
    e.preventDefault(); e.stopPropagation();
    if (st.tool !== "poster") { openPart(cur, "poster"); return; }
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
    return `<div class="pc${on ? " sel" : ""}" data-pc="${id}" style="left:${w.x0 * 100}%;top:${w.y0 * 100}%;width:${(w.x1 - w.x0) * 100}%;height:${(w.y1 - w.y0) * 100}%">
      ${on ? `<span class="pc-h" data-pc-h="${id}" title="Drag to make it bigger or smaller"></span>` : ""}</div>`;
  }).join("");
  f.appendChild(layer);
  layer.querySelectorAll(".pc").forEach((el) => el.onpointerdown = (e) => {
    e.preventDefault(); e.stopPropagation();
    const id = el.dataset.pc, resize = !!e.target.closest(".pc-h");
    if (st.tool !== "poster") { st.pieceSel = id; openPart(cur, "poster"); return; }
    if (st.pieceSel !== id) { st.pieceSel = id; editSig = ""; renderTabs(); layer.querySelectorAll(".pc").forEach((x) => x.classList.toggle("sel", x.dataset.pc === id)); }
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
        const it = (ed.poster?.elements || []).find((x) => x.id === id);
        if (!it) return;
        if (!resize) { it.x += dx / r.width; it.y += dy / r.height; return; }
        const k = Math.max(kx, ky);
        if (it.type === "box" || it.type === "card") { it.w *= kx; it.h *= ky; } else if (it.type === "rule") { it.w *= kx; } else { it.size *= k; }
      }, { keepPane: false });
    };
  });
}

/* Arrow keys nudge the chosen piece; Delete takes it off (not while typing). */
document.addEventListener("keydown", (e) => {
  if (st.tool !== "poster" || !st.pieceSel || e.target.closest?.("input, textarea, [contenteditable]")) return;
  const cur = slotById(st.current);
  if (!cur?.edits?.poster?.elements) return;
  const step = e.shiftKey ? 0.02 : 0.004;
  const by = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
  if (by) {
    e.preventDefault();
    const e2 = clone(cur.edits), it = e2.poster.elements.find((x) => x.id === st.pieceSel);
    if (it) { it.x += by[0]; it.y += by[1]; saveSoon(cur.id, e2, 250); }
  } else if (e.key === "Delete" || e.key === "Backspace") {
    e.preventDefault();
    const id = st.pieceSel; st.pieceSel = null;
    changeEdits(cur, (ed) => { ed.poster.elements = ed.poster.elements.filter((x) => x.id !== id); });
  }
});

/* A team's posters: the same design for each player, only their picture, name and number changed. */
const NAME_KEY = { spotlight: "title", name: "title", teamcolor: "title", goal: "name", mvp: "line" };
const NUMBER_KEY = { spotlight: "number" };
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
