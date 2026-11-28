/* VS Digital Pro Studio: the Assessor tab (internally "check"). How a clip or photo was shot, what is holding it back, fixes for
   the file (a new copy; the original is never changed), what to change next time, files compared side
   by side, and the assessment exported. Loaded after app.js, whose helpers it uses. */
"use strict";

const ck = { files: [], sel: store.get("check.sel", null), detail: null, picked: new Set(), view: "file",
  t: 0, moment: null, split: 50, after: true, marks: false, cmp: null, onlyDiff: store.get("check.onlyDiff", false),
  timer: null, sideSig: "", mainSig: "", guide: !store.get("check.seenGuide", false), focusView: false, picking: false, people: null };
const KIND_ICON = { video: "film", photo: "image" };
const MOMENT_COLOR = { soft_pan: "#f5a623", shaky: "#ff5d5d", jump: "#b38cff", dark: "#4f8bff", bright: "#f5c443",
  focus: "#2ad4c4", frame_soft: "#8fa3b8" };

async function ckRefresh() {
  const data = await fetch("/api/check/state").then((r) => r.json()).catch(() => null);
  if (!data) return;
  const before = JSON.stringify(ck.files);
  ck.files = data.files;
  if (ck.sel && !ck.files.some((f) => f.id === ck.sel)) ck.sel = null;
  if (!ck.sel && ck.files.length) ck.sel = ck.files[0].id;
  [...ck.picked].forEach((id) => { if (!ck.files.some((f) => f.id === id)) ck.picked.delete(id); });
  if (JSON.stringify(ck.files) !== before) {
    renderCkFiles();
    const f = ckFile(ck.sel);
    if (f && ck.view === "file" && (!ck.detail || ck.detail.id !== f.id || ck.detail.state !== f.state)) await ckLoad(f.id);
    else if (f && ck.detail) { ck.detail.job = f.job; ck.detail.fixed = ck.detail.fixed || []; ckPaintJob(); }
  }
}
const ckFile = (id) => ck.files.find((f) => f.id === id);

/* Take files out of the list (one Undo puts them all back). The files themselves are never deleted: a
   file dropped on the window was the app's own copy, and that copy goes to the Trash when the app next starts. */
async function ckRemove(ids) {
  ids = ids.filter((id) => ckFile(id));
  if (!ids.length) return;
  const names = ids.map((id) => ckFile(id).name);
  const order = ck.files.map((f) => f.id);
  const next = order.slice(order.indexOf(ck.sel) + 1).concat(order.slice(0, order.indexOf(ck.sel)).reverse()).find((id) => !ids.includes(id));
  const gone = [];
  for (const id of ids) gone.push(await api(`/api/check/file/${id}`, undefined, { method: "DELETE" }).catch(() => null));
  const done = gone.filter(Boolean);
  ids.forEach((id) => ck.picked.delete(id));
  if (ids.includes(ck.sel)) { ck.sel = next ?? null; ck.detail = null; }
  await ckRefresh(); renderCkFiles();
  if (ck.view === "file") { if (ck.sel) ckLoad(ck.sel); else { renderCkMain(); renderCkSide(); } }
  const dropped = done.some((r) => r.dropped);
  toast(done.length === 1 ? `Took ${names[0]} out of the list` : `Took ${done.length} files out of the list`, {
    small: dropped ? "A file you dropped on the window was the app's own copy: it goes to the Trash when the app next starts. Your originals are untouched" : "The files themselves are untouched",
    action: { label: "Undo", run: async (ev) => {
      ev.target.closest(".toast")?.remove();
      let back = null;
      for (const r of done) back = await api("/api/check/restore", { entry: r.entry }).catch(() => back);
      await ckRefresh(); if (back) ckLoad(back.id); } } });
}
document.addEventListener("keydown", (e) => {
  if (st.mode !== "check" || e.metaKey || e.ctrlKey || e.altKey || modalOpen?.() || e.target.closest?.('input:not([type="checkbox"]), textarea, select')) return;
  if (e.key === "Escape" && ck.picking) { ck.picking = false; paintCkViewer(); return; }
  if (e.key !== "Delete" && e.key !== "Backspace") return;
  const ids = ck.picked.size ? [...ck.picked] : ck.view === "file" && ck.sel ? [ck.sel] : [];
  if (ids.length) { e.preventDefault(); ckRemove(ids); }
});
function ckPoll() {
  clearTimeout(ck.timer);
  if (st.mode !== "check") return;
  const busy = ck.files.some((f) => f.state === "wait" || f.state === "now" || f.job?.state === "now");
  ck.timer = setTimeout(async () => { await ckRefresh(); ckPoll(); }, busy ? 900 : 4000);
}

async function ckLoad(id) {
  ck.sel = id; store.set("check.sel", id);
  const d = await api(`/api/check/file/${id}`).catch(() => null);
  if (!d || ck.sel !== id) return;
  const keepT = ck.detail?.id === id;
  ck.detail = d;
  if (!keepT) { ck.t = d.kind === "video" ? Math.min(1, (d.duration || 2) / 2) : 0; ck.moment = null; ck.marks = false; }
  ck.mainSig = ""; ck.sideSig = "";
  renderCkFiles(); renderCkMain(); renderCkSide();
}

function renderCheck() {
  const box = $("#check");
  if (!box.dataset.built) {
    box.dataset.built = "1";
    box.innerHTML = `<aside class="ck-files"><div class="ck-head"><h2>Assessor <span class="count" id="ck-count"></span></h2>
        <button class="icon-btn" id="ck-help" title="What this is for, and the steps">${icon("info")}</button>
        <div class="menu-wrap"><button class="icon-btn" id="ck-add" title="Add clips or photos to check" aria-haspopup="menu">${icon("plus")}</button>
          <div class="menu" id="ck-add-menu" role="menu" hidden><button role="menuitem" data-ck-add="files">Add clips or photos…<small>Videos, JPG, HEIC or RAW</small></button>
            <button role="menuitem" data-ck-add="folder">Add a folder…<small>Every clip and photo in it</small></button></div></div></div>
        <div class="ck-list" id="ck-list"></div>
        <div class="ck-foot" id="ck-foot"></div></aside>
      <section class="ck-main" id="ck-main"></section>
      <aside class="ck-side" id="ck-side"></aside>`;
    paintIcons(box);
    $("#ck-help").onclick = () => {
      ck.guide = !ck.guide || ck.view !== "file"; ck.view = "file"; box.classList.remove("comparing");
      ck.mainSig = ""; renderCkFiles(); renderCkMain(); renderCkSide();
    };
    $("#ck-add").onclick = (e) => { e.stopPropagation(); $("#ck-add-menu").hidden = !$("#ck-add-menu").hidden; };
    box.querySelectorAll("[data-ck-add]").forEach((b) => b.onclick = () => { $("#ck-add-menu").hidden = true; ckChoose(b.dataset.ckAdd); });
    document.addEventListener("click", (e) => { if (!e.target.closest("#ck-add, #ck-add-menu")) $("#ck-add-menu") && ($("#ck-add-menu").hidden = true); });
  }
  box.classList.toggle("comparing", ck.view === "compare");
  ckRefresh().then(() => { renderCkFiles(); if (ck.view === "compare") renderCompare(); else if (ck.sel) ckLoad(ck.sel); else { renderCkMain(); renderCkSide(); } ckPoll(); });
}

async function ckChoose(kind) {
  const r = await api("/api/check/choose", { kind });
  ckAdded(r.added);
}
async function ckUpload(files) {
  const ok = files.filter((f) => /^(video|image)\//.test(f.type) || /\.(mp4|mov|m4v|mts|mxf|avi|mkv|jpe?g|png|heic|heif|tiff?|webp|arw|dng|cr2|cr3|nef|raf|orf|rw2)$/i.test(f.name));
  const notes = files.find((f) => /M\d\d\.xml$/i.test(f.name));
  if (!ok.length && notes) {
    const clip = notes.name.replace(/M\d\d\.xml$/i, "");
    toast(`${notes.name} is the camera's notes file`, { small: `Add the clip itself (${clip}.MP4): the same notes are inside it, with the focus and exposure of every frame.` });
    return;
  }
  if (!ok.length) { toast("Those aren't clips or photos", { small: "Videos (MP4, MOV…) and photos (JPG, HEIC, RAW)" }); return; }
  const fd = new FormData(); ok.forEach((f) => fd.append("files", f, f.name));
  const t = toast(`Adding ${plural(ok.length, "file")}…`, { sticky: true, spin: true, small: "Big videos take a moment to copy in; Add… keeps them where they are" });
  try { const r = await api("/api/check/upload", fd); t.close(); ckAdded(r.added); } catch { t.close(); }
}
async function ckAdded(ids) {
  if (!ids?.length) return;
  await ckRefresh();
  ck.view = "file"; ck.guide = false;
  $("#check").classList.remove("comparing");
  await ckLoad(ids[0]);
  ckPoll();
  const left = ck.files.filter((f) => ids.includes(f.id)).reduce((a, f) => a + (f.left || 0), 0);
  toast(`Checking ${plural(ids.length, "file")}`, { small: left > 8 ? `About ${say(left)}` : "" });
}

// The start page: what it's for and the steps ----------------------------------------------------
const CK_USES = [
  ["info", "A clip or photo came out wrong", "Blurry, dark, shaky, grainy or washed out, and you want to know why."],
  ["wand", "Fix something you already shot", "Brighter, steadier, cleaner or sharper. It makes a new copy; your original is never touched."],
  ["target", "Shoot better next time", "The exact camera settings to change, and why, based on what this file shows."],
  ["compare", "Compare cameras, settings or events", "Two or more files side by side, best and weakest marked on every line."],
  ["export", "Keep or share the notes", "A Word report (opens in Google Drive too) and a spreadsheet."],
];
const CK_STEPS = [
  ["Add", "Click <b>+</b> at the top left, or drop clips and photos anywhere on this window. Checking takes about a third of a video's length, a second or two per photo."],
  ["See what's holding it back", "Click a file on the left. On a video, the colored marks on the timeline are the problem moments: click one to see it, or play it."],
  ["Fix the file <span class=\"faint\">(optional)</span>", "On the right, turn fixes on and drag the line across the picture to compare before and after. Then <b>Make a fixed copy</b>: it goes in a <i>Clip Analysis/Fixed</i> folder next to the original."],
  ["Next time you shoot", "Below the picture: the settings to change and the habits that help."],
  ["Compare or export <span class=\"faint\">(optional)</span>", "Tick the boxes beside two or more files, then <b>Compare</b> or <b>Export</b> at the bottom left."],
];
function ckGuideHtml(back) {
  return `<div class="ck-guide">
    ${back ? `<button class="btn ghost ck-back" id="ck-guide-back">${icon("left")} Back to ${esc(ck.detail?.name || "the file")}</button>` : ""}
    <div class="ck-intro">${icon("target")}<div><h1>Assessor</h1><p>Tells you how a clip or photo was shot, what's holding it back, fixes the file, and what to change next time. No AI and nothing leaves your Mac: it reads your camera's own settings from the file and measures the picture.</p></div></div>
    ${back ? "" : `<div class="ck-guide-go"><button class="btn primary" data-ck-go="files">${icon("plus")} Add clips or photos…</button><button class="btn ghost" data-ck-go="folder">Add a folder…</button><span class="faint">or drop them on this window</span></div>`}
    <h2>Use it when you want to…</h2>
    <div class="ck-uses">${CK_USES.map(([ic, t, s]) => `<div class="ck-use">${icon(ic)}<b>${t}</b><span>${s}</span></div>`).join("")}</div>
    <h2>How it works</h2>
    <ol class="ck-steps">${CK_STEPS.map(([t, s], i) => `<li><span class="n">${i + 1}</span><div><b>${t}</b><p>${s}</p></div></li>`).join("")}</ol>
    <h2>Good to know</h2>
    <ul class="ck-know">
      <li>Fixes help a file; they can't rescue missed focus or a too-slow shutter. The notes on each fix say what it can't do.</li>
      <li>Steadying smooths camera shake. When players fill the frame it may not help: the app checks its own result and tells you.</li>
      <li>Sharpness and grain numbers compare best between files from the same camera.</li>
      <li>Taking a file out of the list never deletes it. A file dropped on the window is copied into the app; once you take that one out, the app's copy goes to the Trash (your original stays where it was).</li>
    </ul></div>`;
}
function ckShowGuide(main, back) {
  store.set("check.seenGuide", true);
  main.innerHTML = ckGuideHtml(back);
  paintIcons(main);
  main.querySelectorAll("[data-ck-go]").forEach((b) => b.onclick = () => ckChoose(b.dataset.ckGo));
  $("#ck-guide-back")?.addEventListener("click", () => { ck.guide = false; ck.mainSig = ""; renderCkMain(); renderCkSide(); });
}

// The list of files --------------------------------------------------------------------------------
function ckStatus(f) {
  if (f.state === "wait") return `<span class="faint">Waiting · about ${say(f.left || 5)}</span>`;
  if (f.state === "now") return `<span class="spin sm"></span> Checking · ${say(f.left || 3)} left`;
  if (f.state === "failed") return `<span class="bad-t">Couldn't read it</span>`;
  if (f.job?.state === "now") return `<span class="spin sm"></span> Making the fixed copy · ${Math.round(f.job.pct * 100)}%`;
  if (f.verdict) return `<span class="${f.level === "good" ? "good-t" : f.level === "fix" ? "fix-t" : "warn-t"}">${esc(f.verdict)}</span>`;
  return f.problems ? `<span class="warn-t">${plural(f.problems, "thing")} to improve</span>` : `<span class="good-t">Looks good</span>`;
}
function renderCkFiles() {
  const list = $("#ck-list");
  if (!list) return;
  $("#ck-count").textContent = ck.files.length || "";
  list.innerHTML = ck.files.length ? ck.files.map((f) => `<div class="ck-row${f.id === ck.sel && ck.view === "file" ? " on" : ""}" data-ck="${f.id}" title="${esc(f.path)}">
      <label class="ck-tick" title="Tick files to compare or export them together"><input type="checkbox" data-ck-pick="${f.id}" ${ck.picked.has(f.id) ? "checked" : ""}></label>
      <div class="ck-thumb">${f.state === "done" || f.state === "failed" ? `<img src="/img/check/${f.id}/thumb.jpg" alt="" loading="lazy" onerror="this.remove()">` : ""}<span class="kind">${icon(KIND_ICON[f.kind] || "image")}</span></div>
      <div class="ck-txt"><b>${esc(f.name)}</b><small>${ckStatus(f)}</small></div>
      <button class="ck-x" data-ck-x="${f.id}" title="Take it out of this list (Delete key). The file itself stays where it is" aria-label="Take ${esc(f.name)} out of the list">${icon("x")}</button></div>`).join("")
    : `<div class="ck-empty"><p><b>Nothing added yet</b></p><p>Start with step 1: add a clip or photo.</p>
       <button class="btn primary" data-ck-add2="files">${icon("plus")} Add clips or photos…</button><button class="btn ghost" data-ck-add2="folder">Add a folder…</button><p class="faint">or drop them here</p></div>`;
  paintIcons(list);
  list.querySelectorAll("[data-ck-add2]").forEach((b) => b.onclick = () => ckChoose(b.dataset.ckAdd2));
  list.querySelectorAll("[data-ck-x]").forEach((b) => b.onclick = (e) => { e.stopPropagation(); ckRemove([+b.dataset.ckX]); });
  list.querySelectorAll("[data-ck]").forEach((row) => row.onclick = (e) => {
    if (e.target.closest(".ck-tick, .ck-x")) return;
    ck.view = "file"; ck.guide = false; $("#check").classList.remove("comparing");
    ckLoad(+row.dataset.ck);
  });
  list.querySelectorAll("[data-ck-pick]").forEach((c) => c.onchange = () => {
    c.checked ? ck.picked.add(+c.dataset.ckPick) : ck.picked.delete(+c.dataset.ckPick);
    renderCkFoot();
    if (ck.view === "compare") renderCompare();
  });
  renderCkFoot();
}
function renderCkFoot() {
  const foot = $("#ck-foot");
  if (!foot) return;
  const done = ck.files.filter((f) => f.state === "done");
  const picked = [...ck.picked].filter((id) => ckFile(id)?.state === "done");
  const forExport = picked.length ? picked : done.map((f) => f.id);
  foot.innerHTML = ck.files.length ? `
    <button class="btn${ck.view === "summary" ? " primary" : ""}" id="ck-summary" ${off(!done.length, "Nothing checked yet: the summary appears once a file has been checked.")} title="What to fix now and change next time, across ${picked.length >= 2 ? "the ticked files" : "every checked file"}">${icon("list")} Recommendations</button>
    <button class="btn${ck.view === "compare" ? " primary" : ""}" id="ck-compare" ${off(picked.length < 2, "Tick two or more checked files (the boxes on the left), then compare them side by side.")}>${icon("compare")} Compare${picked.length ? ` (${picked.length})` : ""}</button>
    <div class="menu-wrap"><button class="btn" id="ck-export" ${off(!forExport.length, "Nothing checked yet to export.")}>${icon("export")} Export ${picked.length ? `(${picked.length})` : "all"}</button>
      <div class="menu up" id="ck-export-menu" role="menu" hidden>
        <button role="menuitem" data-fmt="both">Word report + spreadsheet<small>Opens in Word or Google Drive</small></button>
        <button role="menuitem" data-fmt="docx">Word report only</button>
        <button role="menuitem" data-fmt="csv">Spreadsheet only (CSV)<small>One row per file</small></button></div></div>
    ${ck.picked.size ? `<button class="btn" id="ck-remove-ticked" title="Take the ticked files out of this list (Delete key). The files themselves stay where they are">${icon("x")} Remove (${ck.picked.size})</button>` : ""}
    <small class="faint">${picked.length ? `${plural(picked.length, "file")} ticked` : "Tick files to compare, export or remove some"}</small>` : "";
  paintIcons(foot);
  $("#ck-remove-ticked")?.addEventListener("click", () => ckRemove([...ck.picked]));
  $("#ck-compare")?.addEventListener("click", () => {
    if (picked.length < 2) return;
    ck.view = ck.view === "compare" ? "file" : "compare"; ck.guide = false;
    $("#check").classList.toggle("comparing", ck.view === "compare");
    if (ck.view === "compare") renderCompare(); else { ck.mainSig = ""; renderCkMain(); renderCkSide(); }
    renderCkFiles();
  });
  $("#ck-summary")?.addEventListener("click", () => {
    if (!done.length) return;
    ck.view = ck.view === "summary" ? "file" : "summary"; ck.guide = false;
    $("#check").classList.toggle("comparing", ck.view === "summary");
    if (ck.view === "summary") renderCkSummary(); else { ck.mainSig = ""; renderCkMain(); renderCkSide(); }
    renderCkFiles();
  });
  $("#ck-export")?.addEventListener("click", (e) => { e.stopPropagation(); if (forExport.length) $("#ck-export-menu").hidden = !$("#ck-export-menu").hidden; });
  foot.querySelectorAll("[data-fmt]").forEach((b) => b.onclick = () => { $("#ck-export-menu").hidden = true; ckExport(forExport, b.dataset.fmt); });
}
document.addEventListener("click", (e) => { if (!e.target.closest("#ck-export, #ck-export-menu")) { const m = $("#ck-export-menu"); if (m) m.hidden = true; } });

async function ckExport(ids, format) {
  const t = toast("Writing the report…", { sticky: true, spin: true });
  try {
    const r = await api("/api/check/export", { ids, format });
    t.done(`Saved ${r.files.length > 1 ? "the report and spreadsheet" : r.files[0].endsWith(".csv") ? "the spreadsheet" : "the report"}`,
      r.folder.replace(/^\/Users\/[^/]+/, "~"), { label: "Show in Finder", run: () => api("/api/reveal", { path: r.files[0] }) });
  } catch { t.close(); }
}

// One file -----------------------------------------------------------------------------------------
function ckViewUrl(d, fixed) {
  const s = fixed ? `&s=${encodeURIComponent(JSON.stringify(ckSettings(d)))}` : "";
  return `/img/check/${d.id}/view.jpg?t=${d.kind === "video" ? ck.t.toFixed(2) : 0}&fixed=${fixed ? 1 : 0}${s}`;
}
const ckSettings = (d) => Object.fromEntries(d.fixes.map((f) => [f.id, { on: !!f.on, value: f.value }]));
const anyFixOn = (d) => d.fixes?.some((f) => f.on && f.value);

/* In short: the file's verdict and its few most useful actions, in order (now, next time, a habit) */
const REC_WHEN = { now: "Fix now", next: "Next time", habit: "Habit" };
function ckShort(r) {
  if (!r) return "";
  return `<section class="ck-card ck-short ${r.level}"><h3>In short <span class="ck-verdict">${esc(r.verdict)}</span></h3>
    ${r.items.length ? `<ol class="ck-recs">${r.items.map((x) => `<li class="${x.when}"><span class="when">${REC_WHEN[x.when]}</span><span><b>${esc(x.title.replace(/^(Fix this file|Next time): /, ""))}</b>${x.why ? `<small>${esc(x.why)}</small>` : ""}</span></li>`).join("")}</ol>
      ${r.more ? `<p class="faint">${plural(r.more, "more recommendation")} below.</p>` : ""}` : `<p class="muted">Nothing to change: the settings were right and nothing needs fixing.</p>`}</section>`;
}

/* The recommendations across the ticked files (or every checked file) */
async function renderCkSummary() {
  const main = $("#ck-main");
  const picked = [...ck.picked].filter((id) => ckFile(id)?.state === "done");
  const ids = picked.length >= 2 ? picked : [];
  main.innerHTML = `<div class="ck-hello"><div class="spin" style="width:24px;height:24px"></div></div>`;
  $("#ck-side").innerHTML = "";
  const s = await api("/api/check/summary", { ids });
  const link = (nm) => `<button class="ck-link" data-goto="${s.ids[nm]}">${esc(nm)}</button>`;
  const group = (cls, title, names) => names.length ? `<div class="ck-sum-group ${cls}"><b>${names.length}</b><span>${title}</span><div>${names.map(link).join("")}</div></div>` : "";
  main.innerHTML = `<header class="ck-title"><div><h1>Recommendations</h1><p>${ids.length ? `The ${plural(ids.length, "ticked file")}` : `All ${plural(s.count, "checked file")}`} · what to fix now and what to change next time</p></div>
      <div class="ck-acts"><button class="btn" id="ck-sum-export">${icon("export")} Word report</button><button class="btn ghost" id="ck-sum-back">Done</button></div></header>
    <section class="ck-card ck-short"><h3>In short</h3><p class="ck-headline">${esc(s.headline)}</p>
      <div class="ck-sum-groups">${group("good", "ready to use as they are", s.good)}${group("fix", "good with a quick fix", s.fix)}${group("attention", "need attention", s.attention)}</div></section>
    ${s.changes.length ? `<section class="ck-card"><h3>Change next time</h3><table class="ck-table"><thead><tr><th>Setting</th><th>Change to</th><th>Files</th><th>Why</th></tr></thead>
      <tbody>${s.changes.map((c) => `<tr><td><b>${esc(c.setting)}</b></td><td>${esc(c.change)}</td><td title="${esc(c.files.join(", "))}">${c.count} of ${s.count}</td><td class="muted">${esc(c.why)}</td></tr>`).join("")}</tbody></table></section>` : ""}
    ${s.fixes.length ? `<section class="ck-card"><h3>Fixes that help most</h3><ul class="ck-find">${s.fixes.map((x) => `<li class="info">${esc(x.label)} <span class="faint">· ${x.count} of ${s.count} files</span></li>`).join("")}</ul><p class="faint">Open a file to turn its fixes on or off and make a fixed copy.</p></section>` : ""}
    ${s.worst.length ? `<section class="ck-card"><h3>Look at these first</h3><ul class="ck-find">${s.worst.map((w) => `<li class="warn">${link(w.name)} <span class="faint">· ${plural(w.problems, "thing")} to improve</span></li>`).join("")}</ul></section>` : ""}
    ${s.habits.length ? `<section class="ck-card"><h3>Habits that help</h3><ol class="ck-habits">${s.habits.map((h) => `<li>${esc(h.text)}</li>`).join("")}</ol></section>` : ""}`;
  paintIcons(main);
  const back = () => { ck.view = "file"; $("#check").classList.remove("comparing"); ck.mainSig = ""; renderCkFiles(); };
  $("#ck-sum-back").onclick = () => { back(); ckLoad(ck.sel || Object.values(s.ids)[0]); };
  $("#ck-sum-export").onclick = () => ckExport(ids.length ? ids : Object.values(s.ids), "docx");
  main.querySelectorAll("[data-goto]").forEach((b) => b.onclick = () => { back(); ckLoad(+b.dataset.goto); });
}

function renderCkMain() {
  const main = $("#ck-main");
  if (!main || ck.view !== "file") return;
  const d = ck.detail;
  $("#check").classList.toggle("guiding", !d || ck.guide);
  if (!d || ck.guide) { ckShowGuide(main, !!d && ck.guide); return; }
  if (d.state !== "done") {
    main.innerHTML = `<div class="ck-hello">${d.state === "failed" ? `${icon("info")}<h1>${esc(d.name)}</h1><p>Couldn't read this file: ${esc(d.error || "")}</p>`
      : `<div class="spin" style="width:28px;height:28px"></div><h1>${esc(d.name)}</h1><p>Checking it · about ${say(d.left || 5)}</p><p class="faint">Videos take about a third of their length; photos a second or two.</p>`}</div>`;
    paintIcons(main); return;
  }
  const isVid = d.kind === "video";
  const problems = d.findings.filter((x) => !/^(No problems|Focus:|Focus mode|The sharpest detail)/.test(x) && !/fps: smooth motion|holds up well/.test(x));
  let info = d.findings.filter((x) => !problems.includes(x));
  if (isVid && d.moments.length) {  // (never "no problems" above a timeline of problem moments)
    info = info.filter((x) => !x.startsWith("No problems"));
    problems.push(`${plural(d.moments.length, "moment")} to look at: ${[...new Set(d.moments.map((m) => m.label.toLowerCase()))].join(", ")} (on the timeline above, and below).`);
  }
  main.innerHTML = `<header class="ck-title"><div><h1>${esc(d.name)}</h1><p>${esc(d.summary)}</p></div>
      <div class="ck-acts"><button class="btn ghost" id="ck-open" title="Open it in ${isVid ? "QuickTime" : "Preview"}">${icon("image")} Open</button>
        <button class="btn ghost" id="ck-reveal">${icon("folder")} Show in Finder</button>
        <button class="icon-btn" id="ck-remove" title="Take it out of this list (the file stays where it is)">${icon("x")}</button></div></header>
    ${ckShort(d.recommend)}
    <div class="ck-viewer" id="ck-viewer"></div>
    ${isVid ? `<div class="ck-timeline" id="ck-timeline" title="Click anywhere to see that moment">${d.moments.map((m, i) => `<span class="mo" data-mo="${i}" style="left:${m.start / d.duration * 100}%;width:${Math.max(0.6, (m.end - m.start) / d.duration * 100)}%;background:${MOMENT_COLOR[m.kind]}" title="${esc(m.clock)} · ${esc(m.label)}"></span>`).join("")}<span class="head" id="ck-head" style="left:${ck.t / d.duration * 100}%"></span></div>
      <div class="ck-legend">${[...new Set(d.moments.map((m) => m.kind))].map((k) => `<span><i style="background:${MOMENT_COLOR[k]}"></i>${esc(d.moments.find((m) => m.kind === k).label)}</span>`).join("")}${d.moments.length ? "" : `<span class="faint">No problem moments found</span>`}</div>` : ""}
    ${isVid && d.focus ? ckFocusCard(d) : ""}
    <section class="ck-card"><h3>${problems.length ? "What's holding it back" : "How it looks"}</h3>
      <ul class="ck-find">${problems.map((x) => `<li class="warn">${esc(x)}</li>`).join("")}${(problems.length || info.some((x) => x.startsWith("No problems")) ? [] : ["No problems found."]).map((x) => `<li class="ok">${esc(x)}</li>`).join("")}${info.map((x) => `<li class="${x.startsWith("No problems") ? "ok" : "info"}">${esc(x)}</li>`).join("")}</ul>
      ${isVid && d.moments.length ? `<h4>When it happens <small class="faint">click one to see it</small></h4><div class="ck-moments">${d.moments.map((m, i) => `<button class="ck-mo${ck.moment === i ? " on" : ""}" data-mo="${i}"><i style="background:${MOMENT_COLOR[m.kind]}"></i><b>${esc(m.clock)}</b><span><b>${esc(m.label)}</b> ${esc(m.detail)}</span></button>`).join("")}</div>` : ""}</section>
    <section class="ck-card"><h3>Next time you shoot</h3>
      ${d.advice.length ? `<table class="ck-table"><thead><tr><th>Setting</th><th>Change to</th><th>Why</th></tr></thead><tbody>${d.advice.map(([a, b, c]) => `<tr><td><b>${esc(a)}</b></td><td>${esc(b)}</td><td class="muted">${esc(c)}</td></tr>`).join("")}</tbody></table>` : `<p class="muted">Your settings were right for this; nothing to change.</p>`}
      ${d.habits.length ? `<h4>Habits that help</h4><ol class="ck-habits">${d.habits.map((h) => `<li>${esc(h)}</li>`).join("")}</ol>` : ""}</section>
    <section class="ck-card"><h3>How it was shot</h3><div class="ck-grid2">
      <table class="ck-kv"><tbody>${d.camera.filter(([, v]) => v && v !== "-").map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join("")}</tbody></table>
      <table class="ck-kv"><tbody>${d.measured.map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join("")}</tbody></table></div>
      <p class="faint">Settings come from the camera's own data in the file; sharpness, grain, brightness and panning are measured from the picture. Sharpness and grain compare best between files from the same camera.</p></section>`;
  paintIcons(main);
  $("#ck-open").onclick = () => api("/api/check/open", { path: d.path });
  $("#ck-reveal").onclick = () => api("/api/reveal", { path: d.path });
  $("#ck-remove").onclick = () => ckRemove([d.id]);
  main.querySelectorAll("[data-mo]").forEach((b) => b.onclick = (e) => { e.stopPropagation(); ckMoment(+b.dataset.mo); });
  const seekFrom = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    ckSeek((e.clientX - r.left) / r.width * d.duration);
  };
  $("#ck-timeline")?.addEventListener("click", seekFrom);
  $("#ck-fchart")?.addEventListener("click", seekFrom);
  $("#ck-pick")?.addEventListener("click", () => { ck.picking = !ck.picking; ck.focusView = true; renderCkMain(); });
  $("#ck-auto")?.addEventListener("click", () => ckSetSubject({}));
  paintCkViewer();
}
function ckSeek(t) {
  const d = ck.detail;
  ck.t = Math.max(0, Math.min(d.duration - 0.05, t)); ck.moment = null;
  $("#ck-head").style.left = `${ck.t / d.duration * 100}%`;
  if ($("#ck-fhead")) $("#ck-fhead").style.left = `${ck.t / d.duration * 100}%`;
  $$("#ck-main .ck-mo").forEach((x) => x.classList.remove("on"));
  paintCkViewer();
}
function ckMoment(i) {
  const d = ck.detail, m = d.moments[i];
  ck.moment = i; ck.t = (m.start + m.end) / 2;
  if ((m.kind === "focus" || m.kind === "frame_soft") && d.focus) ck.focusView = true;
  $("#ck-head").style.left = `${ck.t / d.duration * 100}%`;
  if ($("#ck-fhead")) $("#ck-fhead").style.left = `${ck.t / d.duration * 100}%`;
  $$("#ck-main .ck-mo").forEach((x) => x.classList.toggle("on", +x.dataset.mo === i));
  paintCkViewer();
}

function paintCkViewer() {
  const v = $("#ck-viewer"), d = ck.detail;
  if (!v || !d) return;
  const isVid = d.kind === "video";
  const focusing = isVid && d.focus && ck.focusView;
  const fixed = anyFixOn(d) && ck.after && !focusing;
  const m = ck.moment != null ? d.moments[ck.moment] : null;
  v.innerHTML = `<div class="ck-pic" id="ck-pic" style="aspect-ratio:${d.width}/${d.height}">
      <img class="before" src="${ck.marks ? `/img/check/${d.id}/marks.jpg` : ckViewUrl(d, false)}" alt="">
      ${fixed && !ck.marks ? `<img class="after" id="ck-after" src="${ckViewUrl(d, true)}" alt="" style="clip-path:inset(0 0 0 ${ck.split}%)"><span class="split" id="ck-split" style="left:${ck.split}%"></span><span class="tag l">Before</span><span class="tag r">After</span>` : ""}
      ${!isVid && d.focus_spot && ck.marks ? `<span class="spot" style="left:${d.focus_spot[0] * 100}%;top:${d.focus_spot[1] * 100}%" title="The sharpest detail"></span>` : ""}
      ${focusing ? `<div class="ck-fover${ck.picking ? " picking" : ""}" id="ck-fover"></div>` : ""}
      ${focusing && ck.picking ? `<span class="tag l pickhint">Click the person who should have been sharp · Esc to cancel</span>` : ""}
      <span class="ck-loading" id="ck-loading"><span class="spin sm"></span></span>
    </div>
    <div class="ck-vbar">${isVid ? `<span class="faint">${moClock(ck.t)} of ${moClock(d.duration)}</span>${m ? `<button class="btn ghost sm" id="ck-play">${icon("film")} Play this moment</button>` : ""}${d.focus ? `<button class="chip-btn${ck.focusView ? " on" : ""}" id="ck-fview" title="Your subject's box (green sharp, red out of focus), the sharpest part of the picture (yellow) and everyone else found">${icon("target")} Focus</button>` : ""}` : `<button class="chip-btn${ck.marks ? " on" : ""}" id="ck-marks" title="Pure white areas in red, pure black in blue, the sharpest detail circled">${icon("target")} Problem areas</button>`}
      <span style="flex:1"></span>
      ${focusing ? `<span class="faint">The original, with your subject and the sharpest part marked</span>` : anyFixOn(d) ? `<div class="seg small"><button class="${ck.after ? "" : "on"}" data-ba="0">Original</button><button class="${ck.after ? "on" : ""}" data-ba="1">Before / after</button></div>` : `<span class="faint">Switch on a fix to see it here</span>`}</div>`;
  paintIcons(v);
  const imgs = v.querySelectorAll("img"); let left = imgs.length;
  const loaded = () => { if (--left <= 0) $("#ck-loading")?.remove(); };
  imgs.forEach((im) => { if (im.complete) loaded(); else { im.onload = loaded; im.onerror = loaded; } });
  v.querySelectorAll("[data-ba]").forEach((b) => b.onclick = () => { ck.after = b.dataset.ba === "1"; paintCkViewer(); });
  $("#ck-marks")?.addEventListener("click", () => { ck.marks = !ck.marks; paintCkViewer(); });
  $("#ck-fview")?.addEventListener("click", () => { ck.focusView = !ck.focusView; if (!ck.focusView) ck.picking = false; paintCkViewer(); });
  if (focusing) ckPaintFocus(d);
  $("#ck-play")?.addEventListener("click", () => {
    $("#ck-pic").innerHTML = `<video src="/media/check/${d.id}/moment/${ck.moment}.mp4" autoplay controls playsinline loop></video><span class="ck-loading"><span class="spin sm"></span> Getting the moment ready…</span>`;
    const vid = $("#ck-pic video"); vid.oncanplay = () => $("#ck-pic .ck-loading")?.remove();
  });
  const pic = $("#ck-pic"), split = $("#ck-split");
  if (split) {
    const move = (e) => { const r = pic.getBoundingClientRect(); ck.split = Math.max(0, Math.min(100, (e.clientX - r.left) / r.width * 100));
      $("#ck-after").style.clipPath = `inset(0 0 0 ${ck.split}%)`; split.style.left = `${ck.split}%`; };
    pic.onpointerdown = (e) => { move(e); pic.setPointerCapture(e.pointerId); pic.onpointermove = move; };
    pic.onpointerup = () => { pic.onpointermove = null; };
  }
}
/* Focus on the subject: how sharp they are next to the sharpest part of the picture, over time */
const F_STATE = { sharp: "As sharp as anything in the picture", slightly_soft: "A little soft", soft: "Out of focus",
  frame_soft: "The whole picture is soft", unknown: "Too small or hidden to judge" };
function ckFocusCard(d) {
  const f = d.focus, W = 600, H = 80, dur = d.duration;
  const x = (t) => t / dur * W;
  const v = (r) => r ? Math.min(1, 1 / r) : null;  // 1: as sharp as the sharpest part of the frame
  const y = (k) => 4 + (1 - k) * (H - 8);
  let path = "", prev = null;
  for (const p of f.points) {
    const k = v(p.ratio);
    if (k == null) { prev = null; continue; }
    path += `${prev != null && p.t - prev <= 0.8 ? "L" : "M"}${x(p.t).toFixed(1)},${y(k).toFixed(1)} `; prev = p.t;
  }
  const step = f.points.length > 1 ? f.points[1].t - f.points[0].t : 0.25;
  const strip = f.points.map((p) => `<rect x="${x(p.t - step / 2).toFixed(1)}" width="${Math.max(1, x(step)).toFixed(1)}" y="0" height="8" class="${p.state}"><title>${moClock(p.t)} · ${F_STATE[p.state]}</title></rect>`).join("");
  const bands = f.runs.map((r) => `<rect x="${x(r.start).toFixed(1)}" y="0" width="${Math.max(1, x(r.end) - x(r.start)).toFixed(1)}" height="${H}" class="band ${r.kind}"/>`).join("");
  const soft = y(1 / f.soft);
  return `<section class="ck-card ck-focus"><h3>Focus on your subject <small class="faint">${f.picked ? "the person you picked" : "picked for you: the person the camera followed"}</small></h3>
    <p class="ck-fsay ${f.missed ? "warn" : "ok"}">${esc(f.finding)}</p>
    <div class="ck-fchart" id="ck-fchart" title="How sharp your subject is next to the sharpest part of the picture. Click to see that moment">
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" class="plot">${bands}<line x1="0" x2="${W}" y1="${y(1)}" y2="${y(1)}" class="top"/><line x1="0" x2="${W}" y1="${soft.toFixed(1)}" y2="${soft.toFixed(1)}" class="soft"/><path d="${path}" class="line"/></svg>
      <svg viewBox="0 0 ${W} 8" preserveAspectRatio="none" class="fstrip">${strip}</svg>
      <span class="lab hi">Sharp</span><span class="lab lo" style="top:${(soft / H * 100).toFixed(1)}%">Out of focus below</span>
      <span class="head" id="ck-fhead" style="left:${ck.t / dur * 100}%"></span></div>
    <div class="ck-frow"><span class="ck-fkey"><i class="sharp"></i>Sharp <i class="slightly_soft"></i>A little soft <i class="soft"></i>Out of focus <i class="frame_soft"></i>Whole picture soft</span>
      <span style="flex:1"></span>
      <button class="btn ghost sm${ck.picking ? " on" : ""}" id="ck-pick" title="Click the person on the picture who should have been sharp">${icon("target")} ${ck.picking ? "Click them on the picture…" : "Not who you meant? Pick someone"}</button>
      ${f.picked ? `<button class="btn ghost sm" id="ck-auto" title="Back to the person the camera followed">Automatic</button>` : ""}</div></section>`;
}
async function ckPaintFocus(d) {
  const box = $("#ck-fover"), f = d.focus;
  if (!box || !f) return;
  const t = ck.t;
  const near = f.points.reduce((a, p) => Math.abs(p.t - t) < Math.abs(a.t - t) ? p : a, f.points[0]);
  const close = Math.abs(near.t - t) <= 0.5;
  const pos = (b) => `left:${b[0] * 100}%;top:${b[1] * 100}%;width:${(b[2] - b[0]) * 100}%;height:${(b[3] - b[1]) * 100}%`;
  const softer = (r) => r == null ? "" : r < f.sharp ? "sharp" : `${r.toFixed(1)}x softer than the sharpest part`;
  const draw = (people) => {
    if (ck.t !== t || !$("#ck-fover")) return;
    let html = "";
    if (close) html += near.sharp_boxes.map((b, i) => `<div class="fb sharpest" style="${pos(b)}">${i === 0 ? `<span>Sharpest${near.named && near.state === "soft" ? ` (the ${esc(near.named)})` : ""}</span>` : ""}</div>`).join("");
    for (const p of people || []) {
      if (p.subject) continue;
      html += `<button class="fb other" style="${pos(p.box)}" data-px="${(p.box[0] + p.box[2]) / 2}" data-py="${(p.box[1] + p.box[3]) / 2}" title="${ck.picking ? "This is who should have been sharp" : `Someone else${p.ratio ? ` · ${softer(p.ratio)}` : ""}`}"></button>`;
    }
    if (close) html += `<div class="fb subject ${near.state}" style="${pos(near.box)}"><span>Your subject · ${esc(near.ratio == null ? F_STATE[near.state] : near.state === "frame_soft" ? F_STATE.frame_soft : softer(near.ratio))}</span></div>`;
    else html += `<span class="fnote">Your subject isn't in the picture here</span>`;
    $("#ck-fover").innerHTML = html;
    $("#ck-fover").querySelectorAll("[data-px]").forEach((b) => b.onclick = (e) => {
      if (!ck.picking) return;
      e.stopPropagation(); ckSetSubject({ t: ck.peopleT ?? t, x: +b.dataset.px, y: +b.dataset.py });
    });
  };
  draw(null);
  const r = await api(`/api/check/file/${d.id}/people?t=${t.toFixed(2)}`, undefined, { quiet: true }).catch(() => null);
  if (r) { ck.peopleT = r.t; draw(r.people); }
}
async function ckSetSubject(pick) {
  const d = ck.detail;
  ck.picking = false;
  await api(`/api/check/file/${d.id}/subject`, pick);
  ck.focusView = true;
  await ckLoad(d.id);
  toast(pick.t != null ? "Checking focus on the person you picked" : "Back to the person the camera followed", { small: "The focus card, the timeline and the advice now follow them" });
}
const moClock = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;

// The fixes ----------------------------------------------------------------------------------------
function renderCkSide() {
  const side = $("#ck-side"), d = ck.detail;
  if (!side) return;
  if (ck.view !== "file" || !d || d.state !== "done" || ck.guide) { side.innerHTML = ""; return; }
  const isVid = d.kind === "video";
  side.innerHTML = `<h3>Fix this file <small class="faint">optional</small></h3><p class="faint">Turn on what you want, drag the line on the picture to compare, then make the copy. It goes next to the original, which is never changed.</p>
    <div class="ck-fixes">${d.fixes.map((f) => `<div class="ck-fix${f.on ? " on" : ""}" data-fx="${f.id}">
      <div class="top"><label class="switch"><input type="checkbox" data-fx-on ${f.on ? "checked" : ""}><span></span></label><b>${esc(f.label)}</b><output>${fxValue(f)}</output></div>
      <input type="range" min="${f.lo}" max="${f.hi}" step="${f.step}" value="${f.value}" data-fx-v ${f.on ? "" : 'class="dim"'}>
      <p class="why">${esc(f.why)}</p>
      <p class="limit">${esc(f.what)} <span>${esc(f.limit)}</span></p>
      ${isVid && (f.id === "even" || f.id === "steady") ? `<p class="limit"><span>Shows in the fixed copy, not in the still above.</span></p>` : ""}</div>`).join("")}</div>
    <button class="btn ghost sm" id="ck-suggested" title="Back to the fixes suggested for this file">${icon("undo")} Suggested settings</button>
    <div class="ck-make" id="ck-make"></div>
    ${d.fixed?.length ? `<h4>Fixed copies</h4><div class="ck-made">${d.fixed.slice().reverse().map((x) => `<div class="ck-done"><b>${esc(x.name)}</b><small>${esc(x.fixes.join(" · "))}</small>${x.note ? `<small class="note">${esc(x.note)}</small>` : ""}
      <div><button class="btn ghost sm" data-open="${esc(x.path)}">Open</button><button class="btn ghost sm" data-reveal="${esc(x.path)}">Show in Finder</button></div></div>`).join("")}</div>` : ""}`;
  paintIcons(side);
  ckPaintJob();
  let timer = null;
  const changed = (redraw) => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const r = await api(`/api/check/file/${d.id}/fixes`, { fixes: ckSettings(d) }, { method: "PUT" }).catch(() => null);
      if (r) d.estimate = r.estimate;
      ckPaintJob();
      paintCkViewer();
    }, redraw ? 0 : 350);
  };
  side.querySelectorAll("[data-fx]").forEach((row) => {
    const f = d.fixes.find((x) => x.id === row.dataset.fx);
    const r = row.querySelector("[data-fx-v]"), sw = row.querySelector("[data-fx-on]");
    r.oninput = () => { f.value = +r.value; if (!f.on) { f.on = true; sw.checked = true; row.classList.add("on"); r.classList.remove("dim"); } row.querySelector("output").textContent = fxValue(f); changed(); };
    r.title = "Double-click: back to the suggested value";
    r.ondblclick = () => { const s = f.suggested_value; if (s != null) { r.value = f.value = s; r.oninput(); } };
    sw.onchange = () => { f.on = sw.checked; if (f.on && !f.value) f.value = f.id === "exposure" ? 0.3 : 0.5; ck.sideSig = ""; renderCkSide(); changed(true); };
  });
  $("#ck-suggested").onclick = async () => {
    await api(`/api/check/file/${d.id}/fixes`, { fixes: {} }, { method: "PUT" });
    ckLoad(d.id);
  };
  side.querySelectorAll("[data-open]").forEach((b) => b.onclick = () => api("/api/check/open", { path: b.dataset.open }));
  side.querySelectorAll("[data-reveal]").forEach((b) => b.onclick = () => api("/api/reveal", { path: b.dataset.reveal }));
}
const fxValue = (f) => !f.on ? "Off" : f.unit === "stops" ? `${f.value > 0 ? "+" : ""}${(+f.value).toFixed(2)}` : `${Math.round(f.value * 100)}%`;

function ckPaintJob() {
  const box = $("#ck-make"), d = ck.detail;
  if (!box || !d) return;
  const job = ckFile(d.id)?.job || d.job;
  const on = d.fixes.filter((f) => f.on && f.value);
  if (job?.state === "now") {
    const left = Math.max(1, job.estimate * (1 - job.pct) * (job.pct > 0.05 ? (Date.now() / 1000 - job.started) / (job.estimate * job.pct) : 1));
    box.innerHTML = `<div class="ck-prog"><div class="bar"><span style="width:${Math.round(job.pct * 100)}%"></span></div><small>${esc(job.phase || "Making the fixed copy")} · ${Math.round(job.pct * 100)}% · about ${say(left)} left</small></div>`;
    return;
  }
  box.innerHTML = `${job?.state === "failed" ? `<p class="bad-t">The fixed copy failed: ${esc(job.error || "")}</p>` : ""}
    <button class="btn primary big" id="ck-make-btn" ${off(!on.length, "Switch on at least one fix above.")}>${icon("wand")} Make a fixed copy</button>
    <small class="faint">${on.length ? `${on.map((f) => f.label).join(" · ")} · takes ${say(d.estimate || 5)}` : "Switch on the fixes you want"}</small>`;
  paintIcons(box);
  $("#ck-make-btn").onclick = async () => {
    if (!on.length) return;
    await api(`/api/check/file/${d.id}/fixes`, { fixes: ckSettings(d) }, { method: "PUT" });
    const r = await api(`/api/check/file/${d.id}/fix`, {});
    toast("Making the fixed copy", { small: `${r.dest.split("/").slice(-3).join("/")} · about ${say(r.estimate)}` });
    await ckRefresh(); ckPaintJob(); ckPoll();
    ck.watchJob = d.id;
  };
}
/* The fixed copy is done: its card shows (with Open and Show in Finder). */
let ckJobWas = {};
setInterval(() => {
  if (st.mode !== "check") return;
  for (const f of ck.files) {
    const was = ckJobWas[f.id], now = f.job?.state;
    if (was === "now" && now === "done") {
      toast(`Fixed copy of ${f.name} is ready`, { small: f.job.note || "", action: { label: "Show in Finder", run: () => api("/api/reveal", { path: f.job.dest }) } });
      if (ck.detail?.id === f.id) ckLoad(f.id);
    } else if (was === "now" && now === "failed") toast(`Couldn't make the fixed copy of ${f.name}`, { bad: true, small: f.job.error || "" });
    ckJobWas[f.id] = now;
  }
}, 700);

// Comparing ----------------------------------------------------------------------------------------
async function renderCompare() {
  const main = $("#ck-main");
  const ids = [...ck.picked].filter((id) => ckFile(id)?.state === "done");
  if (ids.length < 2) { ck.view = "file"; $("#check").classList.remove("comparing"); ck.mainSig = ""; renderCkMain(); renderCkSide(); return; }
  main.innerHTML = `<div class="ck-hello"><div class="spin" style="width:24px;height:24px"></div></div>`;
  $("#ck-side").innerHTML = "";
  const c = ck.cmp = await api("/api/check/compare", { ids });
  const n = c.files.length;
  const best = (row) => {
    if (!row.better || row.same) return [];
    const vals = row.nums.map((x, i) => [x, i]).filter(([x]) => x != null);
    if (vals.length < 2) return [];
    // (brightness: anything in the range that looks right scores the same; only too dark or too bright loses)
    const score = ([x]) => row.better === "high" ? x : row.better === "low" ? -x : -(Math.max(0, 0.36 - x) + Math.max(0, x - 0.62));
    const sorted = vals.slice().sort((a, b) => score(b) - score(a));
    if (score(sorted[0]) === score(sorted[sorted.length - 1])) return [];
    return [sorted[0][1], sorted[sorted.length - 1][1]];
  };
  const bar = (row, i) => {
    if (!row.better || row.nums[i] == null) return "";
    const max = Math.max(...row.nums.filter((x) => x != null).map(Math.abs), 1e-9);
    return `<i class="bar" style="width:${Math.max(3, Math.abs(row.nums[i]) / max * 100)}%"></i>`;
  };
  const diffs = c.groups.reduce((a, g) => a + g.rows.filter((r) => !r.same).length, 0);
  main.innerHTML = `<header class="ck-title"><div><h1>Side by side</h1><p>${plural(n, "file")} · ${plural(diffs, "difference")} · <span class="good-t">■</span> best and <span class="warn-t">■</span> weakest on each measurement</p></div>
      <div class="ck-acts"><label class="switch-row"><label class="switch"><input type="checkbox" id="ck-only" ${ck.onlyDiff ? "checked" : ""}><span></span></label> Only what differs</label>
        <button class="btn" id="ck-cmp-export">${icon("export")} Export</button><button class="btn ghost" id="ck-back">Done</button></div></header>
    ${c.notes.some((x) => x.notes.length) ? `<section class="ck-card"><h3>What's different</h3>${c.notes.map((x) => `<h4>${esc(x.title)}</h4><ul class="ck-find">${(x.notes.length ? x.notes : ["No notable differences in settings or measurements."]).map((t) => `<li class="info">${esc(t)}</li>`).join("")}</ul>`).join("")}</section>` : ""}
    <div class="ck-cmp-wrap"><table class="ck-cmp${ck.onlyDiff ? " only" : ""}" style="--n:${n}">
      <thead><tr><th class="lab"></th>${c.files.map((f) => `<th><button class="ck-cmp-file" data-goto="${f.id}" title="Open its assessment"><img src="/img/check/${f.id}/thumb.jpg" alt=""><b>${esc(f.name)}</b><small>${f.problems ? `<span class="warn-t">${plural(f.problems, "thing")} to improve</span>` : `<span class="good-t">Looks good</span>`}</small></button></th>`).join("")}</tr></thead>
      <tbody>${c.groups.map((g) => `<tr class="grp"><th colspan="${n + 1}">${esc(g.name)}</th></tr>${g.rows.map((row) => { const [b, w] = best(row);
        return `<tr class="${row.same ? "same" : "diff"}"><th class="lab">${esc(row.label)}</th>${row.values.map((v, i) => `<td class="${i === b ? "best" : i === w ? "worst" : ""}"><span>${esc(v)}</span>${bar(row, i)}</td>`).join("")}</tr>`; }).join("")}`).join("")}</tbody></table></div>`;
  paintIcons(main);
  $("#ck-only").onchange = (e) => { ck.onlyDiff = e.target.checked; store.set("check.onlyDiff", ck.onlyDiff); $(".ck-cmp").classList.toggle("only", ck.onlyDiff); };
  $("#ck-back").onclick = () => { ck.view = "file"; $("#check").classList.remove("comparing"); ck.mainSig = ""; renderCkFiles(); ckLoad(ck.sel || ids[0]); };
  $("#ck-cmp-export").onclick = () => ckExport(ids, "both");
  main.querySelectorAll("[data-goto]").forEach((b) => b.onclick = () => { ck.view = "file"; $("#check").classList.remove("comparing"); renderCkFiles(); ckLoad(+b.dataset.goto); });
}
