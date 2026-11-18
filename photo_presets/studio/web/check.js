/* AllProPhoto Studio: the Check tab. How a clip or photo was shot, what is holding it back, fixes for
   the file (a new copy; the original is never changed), what to change next time, files compared side
   by side, and the assessment exported. Loaded after app.js, whose helpers it uses. */
"use strict";

const ck = { files: [], sel: store.get("check.sel", null), detail: null, picked: new Set(), view: "file",
  t: 0, moment: null, split: 50, after: true, marks: false, cmp: null, onlyDiff: store.get("check.onlyDiff", false),
  timer: null, sideSig: "", mainSig: "" };
const KIND_ICON = { video: "film", photo: "image" };
const MOMENT_COLOR = { soft_pan: "#f5a623", shaky: "#ff5d5d", jump: "#b38cff", dark: "#4f8bff", bright: "#f5c443" };

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
    box.innerHTML = `<aside class="ck-files"><div class="ck-head"><h2>Check <span class="count" id="ck-count"></span></h2>
        <div class="menu-wrap"><button class="icon-btn" id="ck-add" title="Add clips or photos to check" aria-haspopup="menu">${icon("plus")}</button>
          <div class="menu" id="ck-add-menu" role="menu" hidden><button role="menuitem" data-ck-add="files">Add clips or photos…<small>Videos, JPG, HEIC or RAW</small></button>
            <button role="menuitem" data-ck-add="folder">Add a folder…<small>Every clip and photo in it</small></button></div></div></div>
        <div class="ck-list" id="ck-list"></div>
        <div class="ck-foot" id="ck-foot"></div></aside>
      <section class="ck-main" id="ck-main"></section>
      <aside class="ck-side" id="ck-side"></aside>`;
    paintIcons(box);
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
  if (!ok.length) { toast("Those aren't clips or photos", { small: "Videos (MP4, MOV…) and photos (JPG, HEIC, RAW)" }); return; }
  const fd = new FormData(); ok.forEach((f) => fd.append("files", f, f.name));
  const t = toast(`Adding ${plural(ok.length, "file")}…`, { sticky: true, spin: true, small: "Big videos take a moment to copy in; Add… keeps them where they are" });
  try { const r = await api("/api/check/upload", fd); t.close(); ckAdded(r.added); } catch { t.close(); }
}
async function ckAdded(ids) {
  if (!ids?.length) return;
  await ckRefresh();
  ck.view = "file";
  $("#check").classList.remove("comparing");
  await ckLoad(ids[0]);
  ckPoll();
  const left = ck.files.filter((f) => ids.includes(f.id)).reduce((a, f) => a + (f.left || 0), 0);
  toast(`Checking ${plural(ids.length, "file")}`, { small: left > 8 ? `About ${say(left)}` : "" });
}

// The list of files --------------------------------------------------------------------------------
function ckStatus(f) {
  if (f.state === "wait") return `<span class="faint">Waiting · about ${say(f.left || 5)}</span>`;
  if (f.state === "now") return `<span class="spin sm"></span> Checking · ${say(f.left || 3)} left`;
  if (f.state === "failed") return `<span class="bad-t">Couldn't read it</span>`;
  if (f.job?.state === "now") return `<span class="spin sm"></span> Making the fixed copy · ${Math.round(f.job.pct * 100)}%`;
  return f.problems ? `<span class="warn-t">${plural(f.problems, "thing")} to improve</span>` : `<span class="good-t">Looks good</span>`;
}
function renderCkFiles() {
  const list = $("#ck-list");
  if (!list) return;
  $("#ck-count").textContent = ck.files.length || "";
  list.innerHTML = ck.files.length ? ck.files.map((f) => `<div class="ck-row${f.id === ck.sel && ck.view === "file" ? " on" : ""}" data-ck="${f.id}" title="${esc(f.path)}">
      <label class="ck-tick" title="Tick files to compare or export them together"><input type="checkbox" data-ck-pick="${f.id}" ${ck.picked.has(f.id) ? "checked" : ""}></label>
      <div class="ck-thumb">${f.state === "done" || f.state === "failed" ? `<img src="/img/check/${f.id}/thumb.jpg" alt="" loading="lazy" onerror="this.remove()">` : ""}<span class="kind">${icon(KIND_ICON[f.kind] || "image")}</span></div>
      <div class="ck-txt"><b>${esc(f.name)}</b><small>${ckStatus(f)}</small></div></div>`).join("")
    : `<div class="ck-empty"><p><b>Check a clip or photo</b></p><p>How it was shot, what's holding it back, how to fix the file, and what to change next time. No AI: your camera's own settings and measurements of the picture.</p>
       <button class="btn primary" data-ck-add2="files">${icon("plus")} Add clips or photos…</button><button class="btn ghost" data-ck-add2="folder">Add a folder…</button><p class="faint">or drop them here</p></div>`;
  paintIcons(list);
  list.querySelectorAll("[data-ck-add2]").forEach((b) => b.onclick = () => ckChoose(b.dataset.ckAdd2));
  list.querySelectorAll("[data-ck]").forEach((row) => row.onclick = (e) => {
    if (e.target.closest(".ck-tick")) return;
    ck.view = "file"; $("#check").classList.remove("comparing");
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
    <button class="btn${ck.view === "compare" ? " primary" : ""}" id="ck-compare" ${off(picked.length < 2, "Tick two or more checked files (the boxes on the left), then compare them side by side.")}>${icon("compare")} Compare${picked.length ? ` (${picked.length})` : ""}</button>
    <div class="menu-wrap"><button class="btn" id="ck-export" ${off(!forExport.length, "Nothing checked yet to export.")}>${icon("export")} Export ${picked.length ? `(${picked.length})` : "all"}</button>
      <div class="menu up" id="ck-export-menu" role="menu" hidden>
        <button role="menuitem" data-fmt="both">Word report + spreadsheet<small>Opens in Word or Google Drive</small></button>
        <button role="menuitem" data-fmt="docx">Word report only</button>
        <button role="menuitem" data-fmt="csv">Spreadsheet only (CSV)<small>One row per file</small></button></div></div>
    <small class="faint">${picked.length ? `${plural(picked.length, "file")} ticked` : "Tick files to compare or export some"}</small>` : "";
  paintIcons(foot);
  $("#ck-compare")?.addEventListener("click", () => {
    if (picked.length < 2) return;
    ck.view = ck.view === "compare" ? "file" : "compare";
    $("#check").classList.toggle("comparing", ck.view === "compare");
    if (ck.view === "compare") renderCompare(); else { ck.mainSig = ""; renderCkMain(); renderCkSide(); }
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

function renderCkMain() {
  const main = $("#ck-main");
  if (!main || ck.view !== "file") return;
  const d = ck.detail;
  if (!d) { main.innerHTML = ck.files.length ? "" : `<div class="ck-hello">${icon("target")}<h1>Shot check</h1><p>Add a clip or photo on the left: you'll see how it was shot, what's holding it back, a fix for the file itself and what to change next time.</p></div>`; paintIcons(main); return; }
  if (d.state !== "done") {
    main.innerHTML = `<div class="ck-hello">${d.state === "failed" ? `${icon("info")}<h1>${esc(d.name)}</h1><p>Couldn't read this file: ${esc(d.error || "")}</p>`
      : `<div class="spin" style="width:28px;height:28px"></div><h1>${esc(d.name)}</h1><p>Checking it · about ${say(d.left || 5)}</p><p class="faint">Videos take about a third of their length; photos a second or two.</p>`}</div>`;
    paintIcons(main); return;
  }
  const isVid = d.kind === "video";
  const problems = d.findings.filter((x) => !/^(No problems|Focus:|Focus mode|The sharpest detail)/.test(x) && !/fps: smooth motion|holds up well/.test(x));
  const info = d.findings.filter((x) => !problems.includes(x));
  main.innerHTML = `<header class="ck-title"><div><h1>${esc(d.name)}</h1><p>${esc(d.summary)}</p></div>
      <div class="ck-acts"><button class="btn ghost" id="ck-open" title="Open it in ${isVid ? "QuickTime" : "Preview"}">${icon("image")} Open</button>
        <button class="btn ghost" id="ck-reveal">${icon("folder")} Show in Finder</button>
        <button class="icon-btn" id="ck-remove" title="Take it out of this list (the file stays where it is)">${icon("x")}</button></div></header>
    <div class="ck-viewer" id="ck-viewer"></div>
    ${isVid ? `<div class="ck-timeline" id="ck-timeline" title="Click anywhere to see that moment">${d.moments.map((m, i) => `<span class="mo" data-mo="${i}" style="left:${m.start / d.duration * 100}%;width:${Math.max(0.6, (m.end - m.start) / d.duration * 100)}%;background:${MOMENT_COLOR[m.kind]}" title="${esc(m.clock)} · ${esc(m.label)}"></span>`).join("")}<span class="head" id="ck-head" style="left:${ck.t / d.duration * 100}%"></span></div>
      <div class="ck-legend">${[...new Set(d.moments.map((m) => m.kind))].map((k) => `<span><i style="background:${MOMENT_COLOR[k]}"></i>${esc(d.moments.find((m) => m.kind === k).label)}</span>`).join("")}${d.moments.length ? "" : `<span class="faint">No problem moments found</span>`}</div>` : ""}
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
  $("#ck-remove").onclick = async () => {
    const r = await api(`/api/check/file/${d.id}`, undefined, { method: "DELETE" });
    ck.detail = null; ck.picked.delete(d.id);
    await ckRefresh(); renderCkFiles(); if (ck.sel) ckLoad(ck.sel); else { renderCkMain(); renderCkSide(); }
    toast(`Took ${d.name} out of the list`, { small: "The file itself is untouched", action: { label: "Undo", run: async (ev) => {
      ev.target.closest(".toast")?.remove(); const back = await api("/api/check/restore", { entry: r.entry }); await ckRefresh(); ckLoad(back.id); } } });
  };
  main.querySelectorAll("[data-mo]").forEach((b) => b.onclick = (e) => { e.stopPropagation(); ckMoment(+b.dataset.mo); });
  $("#ck-timeline")?.addEventListener("click", (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    ck.t = Math.max(0, Math.min(d.duration - 0.05, (e.clientX - r.left) / r.width * d.duration)); ck.moment = null;
    $("#ck-head").style.left = `${ck.t / d.duration * 100}%`;
    main.querySelectorAll(".ck-mo").forEach((x) => x.classList.remove("on"));
    paintCkViewer();
  });
  paintCkViewer();
}
function ckMoment(i) {
  const d = ck.detail, m = d.moments[i];
  ck.moment = i; ck.t = (m.start + m.end) / 2;
  $("#ck-head").style.left = `${ck.t / d.duration * 100}%`;
  $$("#ck-main .ck-mo").forEach((x) => x.classList.toggle("on", +x.dataset.mo === i));
  paintCkViewer();
}

function paintCkViewer() {
  const v = $("#ck-viewer"), d = ck.detail;
  if (!v || !d) return;
  const fixed = anyFixOn(d) && ck.after;
  const isVid = d.kind === "video";
  const m = ck.moment != null ? d.moments[ck.moment] : null;
  v.innerHTML = `<div class="ck-pic" id="ck-pic" style="aspect-ratio:${d.width}/${d.height}">
      <img class="before" src="${ck.marks ? `/img/check/${d.id}/marks.jpg` : ckViewUrl(d, false)}" alt="">
      ${fixed && !ck.marks ? `<img class="after" id="ck-after" src="${ckViewUrl(d, true)}" alt="" style="clip-path:inset(0 0 0 ${ck.split}%)"><span class="split" id="ck-split" style="left:${ck.split}%"></span><span class="tag l">Before</span><span class="tag r">After</span>` : ""}
      ${!isVid && d.focus_spot && ck.marks ? `<span class="spot" style="left:${d.focus_spot[0] * 100}%;top:${d.focus_spot[1] * 100}%" title="The sharpest detail"></span>` : ""}
      <span class="ck-loading" id="ck-loading"><span class="spin sm"></span></span>
    </div>
    <div class="ck-vbar">${isVid ? `<span class="faint">${moClock(ck.t)} of ${moClock(d.duration)}</span>${m ? `<button class="btn ghost sm" id="ck-play">${icon("film")} Play this moment</button>` : ""}` : `<button class="chip-btn${ck.marks ? " on" : ""}" id="ck-marks" title="Pure white areas in red, pure black in blue, the sharpest detail circled">${icon("target")} Problem areas</button>`}
      <span style="flex:1"></span>
      ${anyFixOn(d) ? `<div class="seg small"><button class="${ck.after ? "" : "on"}" data-ba="0">Original</button><button class="${ck.after ? "on" : ""}" data-ba="1">Before / after</button></div>` : `<span class="faint">Switch on a fix to see it here</span>`}</div>`;
  paintIcons(v);
  const imgs = v.querySelectorAll("img"); let left = imgs.length;
  const loaded = () => { if (--left <= 0) $("#ck-loading")?.remove(); };
  imgs.forEach((im) => { if (im.complete) loaded(); else { im.onload = loaded; im.onerror = loaded; } });
  v.querySelectorAll("[data-ba]").forEach((b) => b.onclick = () => { ck.after = b.dataset.ba === "1"; paintCkViewer(); });
  $("#ck-marks")?.addEventListener("click", () => { ck.marks = !ck.marks; paintCkViewer(); });
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
const moClock = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;

// The fixes ----------------------------------------------------------------------------------------
function renderCkSide() {
  const side = $("#ck-side"), d = ck.detail;
  if (!side) return;
  if (ck.view !== "file" || !d || d.state !== "done") { side.innerHTML = ""; return; }
  const isVid = d.kind === "video";
  side.innerHTML = `<h3>Fix this file</h3><p class="faint">Makes a new, fixed copy next to it; the original is never changed.</p>
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
    r.ondblclick = () => { const s = (d.suggestedValues || {})[f.id]; if (s != null) { r.value = f.value = s; r.oninput(); } };
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
