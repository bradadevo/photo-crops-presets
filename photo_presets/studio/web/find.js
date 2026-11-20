/* VS Digital Pro Studio: finding a player in every photo. Click them once; the photos with them
   are found (the best first, one per burst), and close calls are asked: "Is this your player?" */
"use strict";

function startFinding() {
  if (!st.photos.length) return;
  st.finding = true; st.current = null; st.tool = null; st.view = "single"; st.survey = [];
  viewerSig = ""; render();
}

/* The photo with everyone the app sees outlined: click your player. */
async function renderFindPick(v) {
  const pid = st.activePhoto, p = st.photos.find((x) => x.id === pid);
  v.classList.remove("grid-mode", "survey-mode");
  v.innerHTML = `<div class="frame finding" id="frame"><div class="layer"><img class="after" src="/img/photo/${pid}/view.jpg" alt="${esc(p.name)}" draggable="false"></div>
      <div class="people" id="people"><span class="tag l"><span class="spin"></span> Finding everyone…</span></div></div>
    <div class="fixbar toolbar"><span class="title"><b>Find a player</b><span>Click your player</span></span><span class="sep"></span>
      <button id="find-cancel">Cancel</button></div>`;
  paintIcons(v);
  fitPhotoFrame();
  $("#find-cancel").onclick = () => { st.finding = false; viewerSig = ""; render(); };
  let r;
  try { r = await api(`/api/players/people/${pid}`); } catch { return; }
  const box = $("#people");
  if (!box || st.activePhoto !== pid) return;
  if (!r.people.length) { box.innerHTML = `<span class="tag l">No one found in this photo: open another photo of them</span>`; return; }
  box.innerHTML = r.people.map((q) => { const [x0, y0, x1, y1] = q.box;
    return `<button class="who" data-person="${q.person}" style="left:${x0 * 100}%;top:${y0 * 100}%;width:${(x1 - x0) * 100}%;height:${(y1 - y0) * 100}%"
      title="${q.face ? "This one" : "This one (their face is not clear here: a photo with their face shows works better)"}"></button>`; }).join("")
    + `<span class="tag l">Click your player</span>`;
  box.querySelectorAll(".who").forEach((b) => b.onclick = async () => {
    st.finding = false; viewerSig = ""; render();
    await api("/api/players/find", { photo: pid, person: +b.dataset.person });
    refresh();
  });
}

function renderPlayerPanel() {
  const panel = $("#player-panel"), pl = st.player;
  panel.hidden = !pl;
  setOff($("#find-btn"), !st.photos.length, "Add photos first: then click your player once to find them in all of them.");
  $("#find-btn").onclick = startFinding;
  if (!pl) return;
  const ask = pl.results.filter((h) => h.status === "maybe");
  panel.innerHTML = `<div class="pp-head"><img src="/img/person/${pl.photo}/${pl.person}.jpg" alt="">
      <div><b>Your player</b><small>${plural(pl.sure, "photo")}${ask.length ? ` · ${ask.length} to check` : ""}</small></div>
      <button class="icon-btn" id="pp-close" title="Stop showing them">${icon("x")}</button></div>
    <div class="seg full small" id="pp-show"><button data-v="all" title="Every photo">All</button><button data-v="with" title="The photos with your player, best first">Theirs</button><button data-v="best" title="One per moment: the best of each burst">Best</button></div>
    <button class="btn primary wide" id="pp-choose" ${off(!pl.best.length, "No photos of them yet: answer the questions below, or click your player in another photo.")} title="Choose these photos, then pick looks and Make: the looks are made on them only">${icon("check")} Choose the best ${pl.best.length}</button>
    ${ask.length ? `<div class="pp-ask"><span>Is this your player?</span>${ask.slice(0, 8).map((h) => `<div class="pp-q" data-photo="${h.photo}" data-person="${h.person}">
      <img src="/img/person/${h.photo}/${h.person}.jpg" alt="">
      <div><button class="yes" title="Yes, it's them">${icon("check")}</button><button class="no" title="No, someone else">${icon("x")}</button></div></div>`).join("")}</div>` : ""}`;
  paintIcons(panel);
  $$("#pp-show button", panel).forEach((b) => { b.classList.toggle("on", b.dataset.v === st.railShow); b.onclick = () => { st.railShow = b.dataset.v; renderRail(); }; });
  $("#pp-close", panel).onclick = async () => { await api("/api/players/clear", {}); st.railShow = "all"; refresh(); };
  $("#pp-choose", panel).onclick = () => {
    st.chosen = new Set(pl.best); st.scope = "chosen"; st.railShow = "best";
    toast(`${plural(pl.best.length, "photo")} chosen`, { small: "Pick looks on the right, then Make: they are made on these" });
    render();
  };
  $$(".pp-q", panel).forEach((q) => q.querySelectorAll("button").forEach((b) => b.onclick = async () => {
    q.classList.add("answered");
    st.player = await api("/api/players/answer", { photo: +q.dataset.photo, person: +q.dataset.person, yes: b.classList.contains("yes") });
    renderRail();
  }));
}
