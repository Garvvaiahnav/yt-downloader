"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const icon = (n, cls = "i") => `<svg class="${cls}"><use href="#i-${n}"/></svg>`;
const CODEC = { h264: "H.264", vp9: "VP9", av1: "AV1", hevc: "HEVC", prores: "ProRes 422", aac: "AAC", opus: "Opus",
                vorbis: "Vorbis", mp3: "MP3", pcm: "PCM", unknown: "Not listed" };

const fmt = {
  bytes(n) {
    if (!n) return "—";
    if (n >= 1e9) return (n / 1e9).toFixed(2) + " GB";
    if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e8 ? 0 : 1) + " MB";
    return Math.max(1, Math.round(n / 1e3)) + " KB";
  },
  kbps(k) {
    if (!k) return "—";
    return k >= 1000 ? (k / 1000).toFixed(1) + " Mbps" : Math.round(k) + " kbps";
  },
  time(s) {
    if (s == null || !isFinite(s)) return "";
    s = Math.round(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = String(s % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${x}` : `${m}:${x}`;
  },
  speed(b) { return b ? fmt.bytes(b) + "/s" : ""; },
};

async function api(path, body, method) {
  const r = await fetch(path, {
    method: method || (body ? "POST" : "GET"),
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || data.detail || `HTTP ${r.status}`);
  return data;
}

let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 3200);
}

/* ---------------- state ---------------- */

let info = null;   // probe result
let sys = null;    // /api/system
let sel = {};      // current choices

function verdict(container, vfam, afam) {
  const rules = info.rules[container], rank = { ok: 0, warn: 1, no: 2 };
  let worst = ["ok", ""];
  for (const [kind, fam] of [["video", vfam], ["audio", afam]]) {
    if (!fam) continue;
    let r = rules[kind][fam] ?? "ok";
    if (typeof r === "string") r = [r, ""];
    if (rank[r[0]] > rank[worst[0]]) worst = r;
  }
  return worst;
}

const resKey = v => `${v.label_h}|${v.fps}`;
const vById = id => info.video.find(v => v.id === id);
const aById = id => info.audio.find(a => a.id === id);

function streamsAt(key) { return info.video.filter(v => resKey(v) === key); }

// At one resolution, prefer what editors can open (H.264/HEVC, or an
// unreported codec, which on social sites is H.264), SDR, highest bitrate.
function bestVideoAt(key) {
  const rows = [...streamsAt(key)].sort((a, b) => b.kbps - a.kbps);
  const editable = r => ["h264", "hevc", "unknown"].includes(r.fam);
  return rows.find(r => !r.hdr && editable(r)) || rows.find(r => !r.hdr) || rows[0];
}

function defaultAudio() {
  return info.audio.find(a => a.fam === "aac" && !a.drc) || info.audio.find(a => !a.drc) || info.audio[0];
}

// Audio family of the current video selection: inside the stream, or the separate audio pick.
function curAfam() {
  const v = vById(sel.vid);
  if (v?.muxed) return v.afam;
  return aById(sel.aid)?.fam || null;
}

function fixContainer() {
  const v = vById(sel.vid);
  if (!v) return;
  if (verdict(sel.container, v.fam, curAfam())[0] !== "no") return;
  sel.container = ["mp4", "webm", "mkv"].find(c => verdict(c, v.fam, curAfam())[0] === "ok") || "mkv";
}

function fixEditor() {
  const v = vById(sel.vid);
  if (!v) return;
  const enc = info.encoders;
  if (!enc[sel.ecodec] || (sel.ecodec === "h264" && v.hdr)) {
    sel.ecodec = ["h264", "hevc", "prores"].find(c => enc[c] && !(c === "h264" && v.hdr)) || sel.ecodec;
  }
  const e = v.editor[sel.ecodec];
  if (e && !e.choices.includes(sel.mbps)) sel.mbps = e.rec;
}

function fixAudioOut() {
  const a = aById(sel.aid);
  if (!a) return;
  if (sel.aout === "m4a" && a.fam !== "aac") sel.aout = a.fam === "opus" ? "opus" : "mp3";
  if (sel.aout === "opus" && a.fam !== "opus") sel.aout = a.fam === "aac" ? "m4a" : "mp3";
}

function initSel() {
  const top = info.video[0];
  const key = top ? resKey(top) : null;
  const v = key ? bestVideoAt(key) : null;
  const a = defaultAudio();
  sel = {
    kind: v ? "video" : "audio",
    res: key, vid: v?.id, aid: a?.id,
    out: "original", container: "mp4",
    ecodec: "h264", mbps: null,
    aout: a?.fam === "opus" ? "opus" : "m4a", mp3: 320,
  };
  if (v) {
    // Start on a container with no caveats (VP9 4K defaults to MKV, not a limited MP4).
    sel.container = ["mp4", "webm", "mkv"].find(c => verdict(c, v.fam, curAfam())[0] === "ok") || "mkv";
    fixEditor();
  }
}

/* Premiere Pro / After Effects compatibility of what the current choices
   would write. Returns {state: "ok"|"no"|"check", why: [...]} */
function editCompat() {
  const t = info.compat, why = [];
  let check = false;
  const look = (table, key, label) => {
    const st = t[table][key] ?? "ok";
    if (st === "no") why.push(label);
    if (st === "check") check = true;
  };
  if (sel.kind === "audio") {
    look("container", sel.aout, `${sel.aout.toUpperCase()} audio`);
  } else if (sel.out === "editor") {
    return { state: "ok", why };
  } else {
    const v = vById(sel.vid), afam = curAfam();
    look("video", v.fam, `${CODEC[v.fam] || v.fam} video`);
    if (afam) look("audio", afam, `${CODEC[afam] || afam} audio`);
    look("container", sel.container, `${sel.container.toUpperCase()} file`);
  }
  return { state: why.length ? "no" : check ? "check" : "ok", why };
}

/* ---------------- mascot ----------------
   Sits on the link bar; jumps while a link is fetched, hops once when it
   loads, droops when it fails. */
function mascot(mode) {
  const m = $("#mascot");
  m.classList.remove("jump", "hop", "sad");
  void m.offsetWidth;  // restart the animation
  m.classList.add(mode);
}
$("#mascot").addEventListener("animationend", e => {
  if (!e.target.classList.contains("jump")) e.target.classList.remove("hop", "sad");
});

/* ---------------- probe ---------------- */

$("#probeForm").addEventListener("submit", async e => {
  e.preventDefault();
  const url = $("#url").value.trim();
  if (!url) return $("#url").focus();
  const btn = $("#probeBtn"), err = $("#probeErr");
  btn.disabled = true;
  btn.textContent = "Fetching…";
  err.hidden = true;
  $("#picker").innerHTML = "";
  mascot("jump");
  try {
    info = await api("/api/probe", { url });
    initSel();
    render();
    $("#srcName").textContent = info.platform;
    mascot("hop");
  } catch (ex) {
    info = null;
    mascot("sad");
    err.innerHTML = icon("alert") + `<span>${esc(ex.message)}</span>` +
      (/Sign in to YouTube/.test(ex.message) && acct?.can_sign_in && !acct.signed_in ? `<button class="btn pri sm" data-signin>Sign in to YouTube</button>` : "");
    err.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = "Fetch";
  }
});

$("#url").addEventListener("paste", () => setTimeout(() => {
  const v = $("#url").value.trim();
  if (/^(https?:\/\/)?([\w-]+\.)?(youtube\.com|youtu\.be|instagram\.com|facebook\.com|fb\.watch|x\.com|twitter\.com|threads\.(net|com)|tiktok\.com)\//i.test(v)) $("#probeForm").requestSubmit();
}, 0));

/* ---------------- picker ---------------- */

function render() {
  if (!info) return;
  const blocked = { is_live: "Live streams can be downloaded after they end.",
                    is_upcoming: "This premiere or stream has not started.",
                    post_live: "This stream just ended and is still processing." }[info.live_status];
  const vertical = info.vertical;
  let html = `
  <div class="card vid">
    <div class="thumb${vertical ? " vert" : ""}" style="background-image:url('${esc(info.thumbnail)}')"></div>
    <div class="vmeta">
      <div class="vtitle">${esc(info.title)}</div>
      <div class="vsub">
        <span class="pill">${esc(info.platform)}</span>
        <span>${esc(info.channel || "")}</span>${info.duration ? `<span>· ${fmt.time(info.duration)}</span>` : ""}
        ${info.max ? `<span class="pill acc">Max ${esc(info.max)}</span>` : ""}
        ${vertical ? `<span class="pill">Vertical</span>` : ""}
      </div>
    </div>
  </div>`;
  if (info.notice) html += `<p class="err warn">${icon("alert")}<span>${esc(info.notice)}</span></p>`;
  if (info.items) {
    html += `<div class="card items"><span class="muted">This post has ${info.items.length} videos</span><div class="chips">${info.items.map(it =>
      `<button class="chip${it.index === info.item ? " on" : ""}" data-item="${it.index}">Video ${it.index}</button>`).join("")}</div></div>`;
  }
  if (blocked) {
    $("#picker").innerHTML = html + `<div class="card pick"><div class="live">${icon("alert")}<span>${blocked}</span></div></div>`;
    return;
  }
  html += `<div class="card pick">
    <div class="blk"><div class="seg" role="tablist">
      <button data-kind="video" class="${sel.kind === "video" ? "on" : ""}" ${info.video.length ? "" : "disabled"}>Video</button>
      <button data-kind="audio" class="${sel.kind === "audio" ? "on" : ""}" ${info.audio.length ? "" : "disabled"}>Audio only</button>
    </div></div>
    ${sel.kind === "video" ? videoBlocks() : audioBlocks()}
    ${compatBlock()}
    ${goBar()}
  </div>`;
  $("#picker").innerHTML = html;
}

function videoBlocks() {
  const keys = [...new Set(info.video.map(resKey))];
  const resChips = keys.map(k => {
    const rows = streamsAt(k), v = rows[0];
    const hdr = rows.some(r => r.hdr);
    // Two frame rates at one height (144p at 30 and at 15) would read as twins.
    const twin = keys.filter(x => streamsAt(x)[0].label === v.label).length > 1;
    return `<button class="chip${sel.res === k ? " on" : ""}" data-res="${k}">${esc(v.label)}${twin ? ` <small>${v.fps}fps</small>` : ""}${hdr ? " <small>HDR</small>" : ""}</button>`;
  }).join("");

  const vrows = streamsAt(sel.res).map(v => `
    <button class="row${sel.vid === v.id ? " on" : ""}" data-vid="${esc(v.id)}">
      <span class="dot"></span>
      <span class="c1">${CODEC[v.fam] || esc(v.fam)} ${v.hdr ? `<span class="pill am">${esc(v.dynamic_range)}</span>` : ""}${v.muxed ? `<span class="pill">With audio</span>` : ""}</span>
      <span class="num">${fmt.kbps(v.kbps)}</span>
      <span class="num r">${fmt.bytes(v.size)}</span>
      <span class="c4 r muted">${v.width && v.height ? `${v.width}×${v.height}` : ""}</span>
    </button>`).join("");

  const v = vById(sel.vid);
  const anyEnc = info.encoders.h264 || info.encoders.hevc || info.encoders.prores;
  const out = `
    <div class="blk">
      <div class="sech"><h3>Output</h3></div>
      <div class="seg">
        <button data-out="original" class="${sel.out === "original" ? "on" : ""}">Original</button>
        <button data-out="editor" class="${sel.out === "editor" ? "on" : ""}" ${anyEnc ? "" : "disabled"}>Convert for editing</button>
      </div>
      ${sel.out === "original" ? containerBlock() : editorBlock()}
    </div>`;

  let audio;
  if (v.muxed) audio = `<p class="muted small">Included in the video stream.</p>`;
  else if (info.audio.length) audio = audioRows();
  else audio = `<p class="muted small">This video has no audio track.</p>`;

  return `
    <div class="blk">
      <div class="sech"><h3>Resolution</h3></div>
      <div class="chips">${resChips}</div>
    </div>
    <div class="blk">
      <div class="sech"><h3>Video</h3></div>
      <div class="rowh"><span></span><span>Codec</span><span>Bitrate</span><span class="r">Size</span><span class="c4 r">Frame size</span></div>
      <div class="rows">${vrows}</div>
    </div>
    <div class="blk">
      <div class="sech"><h3>Audio</h3></div>
      ${audio}
    </div>
    ${out}`;
}

function audioRows() {
  const rows = info.audio.map(a => {
    const lang = a.language ? `<span class="pill">${esc(a.language)}</span>` : "";
    const note = /original/i.test(a.note) ? `<span class="pill bl">Original</span>` : "";
    const drc = a.drc ? `<span class="pill" title="Dynamic range compressed: loudness evened out">DRC</span>` : "";
    return `
    <button class="row${sel.aid === a.id ? " on" : ""}" data-aid="${esc(a.id)}">
      <span class="dot"></span>
      <span class="c1">${CODEC[a.fam] || esc(a.fam)} ${lang}${note}${drc}</span>
      <span class="num">${fmt.kbps(a.kbps)}</span>
      <span class="num r">${fmt.bytes(a.size)}</span>
      <span class="c4 r muted">${a.asr ? (a.asr / 1000).toFixed(1) + " kHz" : ""}</span>
    </button>`;
  }).join("");
  return `<div class="rowh"><span></span><span>Codec</span><span>Bitrate</span><span class="r">Size</span><span class="c4 r">Sample rate</span></div><div class="rows">${rows}</div>`;
}

function containerBlock() {
  const v = vById(sel.vid), afam = curAfam();
  const chips = ["mp4", "webm", "mkv"].map(c => {
    const [vd, why] = verdict(c, v.fam, afam);
    return `<button class="chip${sel.container === c ? " on" : ""}" data-container="${c}" ${vd === "no" ? "disabled" : ""} ${why ? `title="${esc(why)}"` : ""}>${c.toUpperCase()}</button>`;
  }).join("");
  return `<div class="chips" style="margin-top:12px">${chips}</div>`;
}

const EDIT_OUT = {
  h264: ["H.264 MP4", "Opens everywhere. Smallest files."],
  hevc: ["HEVC MP4", "Smaller than H.264 at the same quality. Keeps HDR."],
  prores: ["ProRes 422 MOV", "Smoothest editing, best for After Effects. Large files."],
};

function editorBlock() {
  const v = vById(sel.vid), enc = info.encoders;
  const codecs = ["h264", "hevc", "prores"].map(c => {
    const off = !enc[c] || (c === "h264" && v.hdr);
    const title = !enc[c] ? "No working encoder on this machine" : off ? "HDR source: use HEVC or ProRes" : EDIT_OUT[c][1];
    return `<button class="chip${sel.ecodec === c ? " on" : ""}" data-ecodec="${c}" ${off ? "disabled" : ""} title="${esc(title)}">${EDIT_OUT[c][0]}</button>`;
  }).join("");
  let rates = "";
  if (sel.ecodec !== "prores") {
    const e = v.editor[sel.ecodec];
    rates = `<div class="sech" style="margin-top:14px"><h3>Bitrate</h3>${v.kbps ? `<span class="hint">Source ${fmt.kbps(v.kbps)} ${CODEC[v.fam] || v.fam}</span>` : ""}</div>
      <div class="chips">${e.choices.map(m => `<button class="chip${sel.mbps === m ? " on" : ""}" data-mbps="${m}">${m} Mbps</button>`).join("")}</div>`;
  }
  return `
    <div class="sech" style="margin-top:14px"><h3>Format</h3><span class="hint">Constant frame rate · ${enc[sel.ecodec] ? esc(encLabel(enc[sel.ecodec])) : ""}</span></div>
    <div class="chips">${codecs}</div>
    <p class="muted small" style="margin-top:8px">${esc(EDIT_OUT[sel.ecodec][1])}</p>
    ${rates}`;
}

function encLabel(name) {
  return name.includes("videotoolbox") ? "Apple VideoToolbox" : name.includes("nvenc") ? "NVIDIA NVENC" : name.includes("qsv") ? "Intel Quick Sync"
    : name.includes("amf") ? "AMD AMF" : "CPU";
}

/* "This format won't open in Premiere Pro or After Effects. Convert to: …" */
function compatBlock() {
  const c = editCompat();
  if (c.state === "ok") {
    return `<div class="compat ok">${icon("check")}<span>Opens in Premiere Pro and After Effects.</span></div>`;
  }
  if (c.state === "check") {
    return `<div class="compat">${icon("alert")}<span>The site doesn't report this codec. Check the Verified details after download; if Premiere Pro or After Effects won't open it, use Convert for editing.</span></div>`;
  }
  let opts;
  if (sel.kind === "audio") {
    const a = aById(sel.aid);
    opts = [...(a.fam === "aac" ? [["m4a", "M4A (AAC)", "Same quality as the source."]] : []),
            ["wav", "WAV", "Uncompressed. Best for editing."],
            ["mp3", "MP3", "Smallest, plays anywhere."]]
      .map(([k, l, d]) => `<button class="copt" data-fixaout="${k}"><b>${l}</b><span>${d}</span></button>`).join("");
  } else {
    const v = vById(sel.vid);
    opts = ["h264", "hevc", "prores"].filter(k => info.encoders[k] && !(k === "h264" && v.hdr))
      .map(k => `<button class="copt" data-fixcodec="${k}"><b>${EDIT_OUT[k][0]}</b><span>${EDIT_OUT[k][1]}</span></button>`).join("");
  }
  return `<div class="compat no">
    <div class="ch">${icon("alert")}<span><b>This format won't open in Premiere Pro or After Effects</b> (${esc(c.why.join(", "))}). Convert it to one of these:</span></div>
    <div class="copts">${opts}</div>
  </div>`;
}

function audioBlocks() {
  const a = aById(sel.aid);
  const outs = [
    ["m4a", "M4A", a.fam !== "aac" ? "Requires an AAC source" : ""],
    ["opus", "Opus", a.fam !== "opus" ? "Requires an Opus source" : ""],
    ["mp3", "MP3", ""],
    ["wav", "WAV", ""],
  ];
  const chips = outs.map(([k, l, why]) => `<button class="chip${sel.aout === k ? " on" : ""}" data-aout="${k}" ${why ? `disabled title="${esc(why)}"` : ""}>${l}</button>`).join("");
  let extra = "";
  if (sel.aout === "mp3") {
    extra = `<div class="sech" style="margin-top:14px"><h3>MP3 bitrate</h3></div>
      <div class="chips">${[320, 256, 192, 128].map(k => `<button class="chip${sel.mp3 === k ? " on" : ""}" data-mp3="${k}">${k} kbps</button>`).join("")}</div>`;
  }
  return `
    <div class="blk"><div class="sech"><h3>Source</h3></div>${audioRows()}</div>
    <div class="blk"><div class="sech"><h3>Format</h3></div><div class="chips">${chips}</div>${extra}</div>`;
}

function estimate() {
  const dur = info.duration || 0;
  const a = aById(sel.aid);
  if (sel.kind === "audio") {
    if (sel.aout === "mp3") return sel.mp3 * 1000 / 8 * dur;
    if (sel.aout === "wav") return 48000 * 2 * 2 * dur;
    return a.size;
  }
  const v = vById(sel.vid);
  const sepAudio = v.muxed ? null : a;
  if (sel.out === "editor") {
    if (sel.ecodec === "prores") {
      // ProRes 422 runs about 147 Mbps at 1080p29.97; it scales with pixels x frames.
      const px = (v.width || 1920) * (v.height || 1080) * (v.fps || 30);
      return (px * 2.37 / 8 + 192000) * dur;
    }
    return (sel.mbps * 1e6 / 8 + 40000) * dur;
  }
  return (v.size || 0) + (sepAudio?.size || 0);
}

function summary() {
  const a = aById(sel.aid);
  if (sel.kind === "audio") return `${sel.aout.toUpperCase()}${sel.aout === "mp3" ? " " + sel.mp3 + " kbps" : ""} · ${CODEC[a.fam] || a.fam} source`;
  const v = vById(sel.vid);
  const base = `${v.label}${v.hdr ? " HDR" : ""}`;
  if (sel.out === "editor") {
    return `${base} · ${CODEC[v.fam] || v.fam} → ${EDIT_OUT[sel.ecodec][0]}${sel.ecodec === "prores" ? "" : ` ${sel.mbps} Mbps`}`;
  }
  const codecs = [v.fam, curAfam()].filter(f => f && f !== "unknown").map(f => CODEC[f] || f).join(" + ");
  return [base, codecs, sel.container.toUpperCase()].filter(Boolean).join(" · ");
}

function goBar() {
  const est = estimate();
  return `<div class="go">
    <div class="sum"><b>${esc(summary())}</b><span>${est ? "≈ " + fmt.bytes(est) : ""}</span></div>
    <button class="btn pri" id="goBtn">${icon("download")}Download</button>
  </div>`;
}

async function loadItem(index) {
  try {
    info = await api("/api/probe", { url: info.source_url, item: index });
    initSel();
    render();
  } catch (ex) { toast(ex.message); }
}

$("#picker").addEventListener("click", async e => {
  const b = e.target.closest("button");
  if (!b || b.disabled) return;
  const d = b.dataset;
  if (d.item) return loadItem(Number(d.item));
  if (d.kind) sel.kind = d.kind;
  else if (d.res) { sel.res = d.res; sel.vid = bestVideoAt(d.res).id; fixContainer(); fixEditor(); }
  else if (d.vid) { sel.vid = d.vid; fixContainer(); fixEditor(); }
  else if (d.aid) { sel.aid = d.aid; if (sel.vid) fixContainer(); fixAudioOut(); }
  else if (d.out) { sel.out = d.out; fixEditor(); }
  else if (d.container) sel.container = d.container;
  else if (d.ecodec) { sel.ecodec = d.ecodec; sel.mbps = null; fixEditor(); }
  else if (d.fixcodec) { sel.out = "editor"; sel.ecodec = d.fixcodec; sel.mbps = null; fixEditor(); }
  else if (d.fixaout) sel.aout = d.fixaout;
  else if (d.mbps) sel.mbps = Number(d.mbps);
  else if (d.aout) sel.aout = d.aout;
  else if (d.mp3) sel.mp3 = Number(d.mp3);
  else if (b.id === "goBtn") return startJob(b);
  else return;
  render();
});

async function startJob(btn) {
  const body = { url: info.source_url, item: info.item, kind: sel.kind };
  if (sel.kind === "video") {
    body.video_id = sel.vid;
    if (!vById(sel.vid).muxed && sel.aid) body.audio_id = sel.aid;
    if (sel.out === "editor") body.editor = { codec: sel.ecodec, mbps: sel.mbps };
    else body.container = sel.container;
  } else {
    body.audio_id = sel.aid;
    body.audio_out = sel.aout;
    if (sel.aout === "mp3") body.mp3_kbps = sel.mp3;
  }
  btn.disabled = true;
  try {
    await api("/api/jobs", body);
    toast("Added to queue");
  } catch (ex) {
    toast(ex.message);
  } finally {
    btn.disabled = false;
  }
}

/* ---------------- queue ---------------- */

let jobs = [];
const openVerify = new Set();

function connect() {
  const es = new EventSource("/api/events");
  es.onmessage = e => { jobs = JSON.parse(e.data); renderQueue(); };
  es.onerror = () => { es.close(); setTimeout(connect, 2000); };
}

function renderQueue() {
  const active = jobs.filter(j => !["done", "error", "cancelled"].includes(j.status)).length;
  $("#qcount").textContent = jobs.length ? (active ? `${active} active` : `${jobs.length}`) : "";
  if (!jobs.length) {
    $("#queue").innerHTML = `<div class="empty">No downloads</div>`;
    return;
  }
  // Progress events arrive several times a second; rebuild only the cards
  // whose markup changed, so thumbnails and hover states stay put.
  const box = $("#queue");
  box.querySelector(".empty")?.remove();
  const seen = new Set();
  let prev = null;
  for (const j of jobs) {
    seen.add(j.id);
    const html = jobCard(j);
    let el = box.querySelector(`[data-job="${j.id}"]`);
    if (!el || el._html !== html) {
      const t = document.createElement("template");
      t.innerHTML = html.trim();
      const fresh = t.content.firstElementChild;
      fresh._html = html;
      el ? el.replaceWith(fresh) : box.prepend(fresh);
      el = fresh;
    }
    if (prev ? prev.nextElementSibling !== el : box.firstElementChild !== el) {
      prev ? prev.after(el) : box.prepend(el);
    }
    prev = el;
  }
  box.querySelectorAll("[data-job]").forEach(el => { if (!seen.has(el.dataset.job)) el.remove(); });
}

function jobCard(j) {
  const running = !["done", "error", "cancelled"].includes(j.status);
  const indeterminate = ["queued", "merging", "converting", "verifying"].includes(j.status) || (j.status === "downloading" && !j.progress);
  let body = "";
  if (running) {
    const pct = Math.round(j.progress * 100);
    body = `<div class="bar${indeterminate ? " ind" : ""}"><i style="width:${pct}%"></i></div>
      <div class="jline"><span>${esc(j.stage)}${indeterminate ? "" : ` · ${pct}%`}</span><span class="num">${[fmt.speed(j.speed), j.eta != null ? fmt.time(j.eta) + " left" : ""].filter(Boolean).join(" · ")}</span></div>`;
  } else if (j.status === "error") {
    body = `<div class="jerr">${esc(j.error)}</div>`;
  } else if (j.status === "cancelled") {
    body = `<div class="jline"><span>Cancelled</span></div>`;
  } else {
    const v = j.verify;
    const bad = v ? v.rows.filter(r => !r.ok).length : 0;
    const pill = v ? (v.ok ? `<span class="pill gr">${icon("check")}Verified</span>`
                           : `<span class="pill am">${icon("alert")}${bad} ${bad === 1 ? "mismatch" : "mismatches"}</span>`) : "";
    const open = openVerify.has(j.id);
    body = `<div class="jact">
        <button class="btn ghost sm" data-verify="${j.id}" title="ffprobe report">${pill}</button>
        <span style="flex:1"></span>
        <button class="btn sec sm" data-reveal="${j.id}">${icon("folder")}${navigator.platform.startsWith("Mac") ? "Show in Finder" : "Show in Explorer"}</button>
      </div>
      ${open && v ? `<table class="vt">${v.rows.map(r => `<tr class="${r.ok ? "ok" : "bad"}"><td class="mk">${icon(r.ok ? "check" : "alert")}</td><td>${esc(r.field)}</td><td>${esc(r.expected)}</td><td>${esc(r.actual)}</td></tr>`).join("")}</table>
        <div class="jlabel" title="${esc(j.file)}">${esc(j.filename)} · ${fmt.bytes(v.size)}</div>` : ""}`;
  }
  return `<div class="card job" data-job="${j.id}">
    <div class="jtop">
      <div class="jthumb" style="background-image:url('${esc(j.thumbnail)}')"></div>
      <div class="jmeta"><div class="jtitle" title="${esc(j.title)}">${esc(j.title)}</div><div class="jlabel">${esc(j.label)}</div></div>
      ${running ? `<button class="jx" data-cancel="${j.id}" title="Cancel">${icon("stop")}</button>`
                : `<button class="jx" data-remove="${j.id}" title="Remove">${icon("x")}</button>`}
    </div>
    ${body}
  </div>`;
}

$("#queue").addEventListener("click", async e => {
  const b = e.target.closest("[data-cancel],[data-remove],[data-reveal],[data-verify]");
  if (!b) return;
  const d = b.dataset;
  try {
    if (d.cancel) await api(`/api/jobs/${d.cancel}/cancel`, {});
    else if (d.remove) await api(`/api/jobs/${d.remove}`, null, "DELETE");
    else if (d.reveal) await api(`/api/jobs/${d.reveal}/reveal`, {});
    else if (d.verify) { openVerify.has(d.verify) ? openVerify.delete(d.verify) : openVerify.add(d.verify); renderQueue(); }
  } catch (ex) { toast(ex.message); }
});

/* ---------------- engine + settings ---------------- */

async function loadSystem() {
  sys = await api("/api/system");
  renderEngine();
  renderSettings();
  renderQueue();
}

function renderEngine() {
  $("#engine").innerHTML = `<span class="pill" title="yt-dlp version">yt-dlp ${esc(sys.ytdlp)}</span>
    ${sys.update_available ? `<button class="btn sec sm" data-update>${icon("refresh")}Update ${esc(sys.ytdlp_latest)}</button>` : ""}`;
}

let acct = null;

async function loadAccount() {
  try { acct = await api("/api/account"); } catch { return; }
  renderAccount();
}

function renderAccount() {
  const card = $("#acctCard");
  if (!card || !acct) return;
  const s = sys.settings;
  const browsers = sys.browsers.filter(Boolean);
  card.innerHTML = `
    <h3>YouTube account</h3>
    <p>Needed only when YouTube asks to "confirm you're not a bot", and for age-restricted or members-only videos.</p>
    ${acct.signed_in
      ? `<div class="acct ok">${icon("check")}<span>Signed in${acct.since ? ` since ${esc(acct.since)}` : ""}.</span><button class="btn sec sm" data-signout>Sign out</button></div>`
      : acct.can_sign_in
        ? `<button class="btn pri" data-signin>Sign in to YouTube</button>
           <p class="muted small" style="margin:8px 0 0">Opens Google's sign-in page in a window of this app. The session stays on this computer.</p>`
        : `<p class="muted small" style="margin:0">Sign-in is available in the installed app.</p>`}
    ${browsers.length ? `<details class="adv"><summary>Use a browser's cookies instead</summary>
      <div class="field"><select id="cookies">${["", ...browsers].map(b => `<option value="${b}" ${b === s.cookies_browser ? "selected" : ""}>${b ? b[0].toUpperCase() + b.slice(1) : "Off"}</option>`).join("")}</select></div>
      <p class="muted small" style="margin:8px 0 0">${navigator.platform.startsWith("Win") ? "On Windows only Firefox works: Chrome, Edge and Brave lock their cookies." : "macOS asks once for Keychain access; Safari needs Full Disk Access."}</p>
    </details>` : ""}`;
}

async function startSignin() {
  try {
    await api("/api/account/signin", {});
    toast("Sign in in the new window. It closes by itself when you're done.");
    const until = Date.now() + 15 * 60 * 1000;
    const poll = async () => {
      await loadAccount();
      if (acct.signed_in) { toast("Signed in to YouTube"); return; }
      if (Date.now() < until) setTimeout(poll, 2000);
    };
    setTimeout(poll, 2000);
  } catch (ex) { toast(ex.message); }
}

document.addEventListener("click", async e => {
  const b = e.target.closest("[data-signin],[data-signout]");
  if (!b) return;
  if (b.hasAttribute("data-signin")) return startSignin();
  await api("/api/account/signout", {});
  toast("Signed out");
  loadAccount();
});

function renderSettings() {
  const s = sys.settings;
  const enc = sys.encoders;
  const encTxt = c => enc[c] ? `${esc(enc[c].label)} <span class="muted">(${esc(enc[c].name)})</span>` : `<span class="muted">Not found</span>`;
  $("#settings").innerHTML = `
  <div class="card">
    <h3>Download folder</h3>
        <form class="field" id="dirForm"><input id="dir" value="${esc(s.download_dir)}" spellcheck="false"><button class="btn sec">Save</button></form>
  </div>
  <div class="card" id="acctCard"></div>
  <div class="card">
    <h3>Engine</h3>
    <dl class="kv">
      <dt>yt-dlp</dt><dd>${esc(sys.ytdlp)} ${sys.ytdlp_latest ? (sys.update_available ? `<span class="pill am">${esc(sys.ytdlp_latest)} available</span>` : `<span class="pill gr">latest</span>`) : ""}</dd>
      <dt>ffmpeg</dt><dd>${esc(sys.ffmpeg || "Not found")}</dd>
      <dt>Deno</dt><dd>${esc(sys.deno || "Not found")}</dd>
      <dt>H.264 encoder</dt><dd>${encTxt("h264")}</dd>
      <dt>HEVC encoder</dt><dd>${encTxt("hevc")}</dd>
      <dt>ProRes encoder</dt><dd>${encTxt("prores")}</dd>
    </dl>
    <div style="margin-top:14px"><button class="btn sec" data-update>${icon("refresh")}Update yt-dlp</button></div>
  </div>
  <div class="card" id="updCard"></div>
  <div class="card about">
    <img src="mascot-still.png" alt="" width="44" height="65">
    <div><h3>Video Downloader ${esc(sys.version || "")}</h3><p>Made by Garv. Built between chai breaks.</p></div>
  </div>`;
  if (upd) renderUpdate();
  renderAccount();
}

$("#settings").addEventListener("submit", async e => {
  if (e.target.id !== "dirForm") return;
  e.preventDefault();
  try {
    sys.settings = await api("/api/settings", { download_dir: $("#dir").value });
    toast("Saved");
    renderSettings();
  } catch (ex) { toast(ex.message); }
});

$("#settings").addEventListener("change", async e => {
  if (e.target.id !== "cookies") return;
  try {
    sys.settings = await api("/api/settings", { cookies_browser: e.target.value });
    toast("Saved");
  } catch (ex) { toast(ex.message); }
});

document.addEventListener("click", async e => {
  const b = e.target.closest("[data-update]");
  if (!b || b.disabled) return;
  b.disabled = true;
  const old = b.innerHTML;
  b.innerHTML = `${icon("refresh")}Updating…`;
  try {
    const r = await api("/api/update", {});
    toast(r.changed ? `yt-dlp ${r.version} downloaded. Restart the app to use it.` : `yt-dlp ${r.version} is up to date`);
    b.innerHTML = old;
    b.disabled = r.changed;
  } catch (ex) {
    toast(ex.message);
    b.innerHTML = old;
    b.disabled = false;
  }
});

/* ---------------- app updates ----------------
   The server checks GitHub on launch and every few hours, verifies the
   release signature, and reports here. Installing is always a click. */

let upd = null, updTimer = null;

async function loadUpdate() {
  try { upd = await api("/api/app-update"); } catch { return; }
  renderUpdate();
  clearTimeout(updTimer);
  updTimer = setTimeout(loadUpdate, ["installing", "restarting"].includes(upd.status) ? 500 : 60000);
}

function checkList(checks) {
  return checks.length ? `<ul class="uchecks">${checks.map(c =>
    `<li class="${c.ok ? "ok" : "bad"}">${icon(c.ok ? "check" : "alert")}<span>${esc(c.name)}</span><small>${esc(c.detail)}</small></li>`).join("")}</ul>` : "";
}

function renderUpdate() {
  const bar = $("#updateBar");
  const a = upd.available;
  if (upd.status === "available" && a) {
    bar.innerHTML = `${icon("refresh")}<span><b>Update ${esc(a.version)} is ready.</b> ${esc(a.notes.split("\n")[0].replace(/^- /, ""))}</span>
      <button class="btn sec sm" data-view-go="settings">What's new</button><button class="btn pri sm" data-install>Update and restart</button>`;
  } else if (upd.status === "installing" || upd.status === "restarting") {
    const pct = Math.round(upd.progress * 100);
    bar.innerHTML = `${icon("refresh")}<span><b>${upd.status === "restarting" ? "Verified. Restarting…" : `Updating… ${pct}%`}</b></span>
      <div class="bar" style="flex:1;max-width:220px"><i style="width:${pct}%"></i></div>`;
  } else if (upd.status === "error") {
    bar.innerHTML = `${icon("alert")}<span>${esc(upd.error)}</span><button class="btn sec sm" data-dismiss>Dismiss</button>`;
  }
  bar.hidden = !["available", "installing", "restarting", "error"].includes(upd.status) || bar.dataset.dismissed === upd.status;
  bar.className = "upbar" + (upd.status === "error" ? " bad" : "");

  const card = $("#updCard");
  if (!card) return;
  let body;
  if (upd.status === "dev") body = `<p>Updates apply to the installed app.</p>`;
  else if (upd.status === "available") body = `<p><b>${esc(a.version)}</b> is available (${fmt.bytes(a.size)}).</p>
      <div class="notes">${esc(a.notes).replace(/^- /gm, "• ").replace(/\n/g, "<br>")}</div>
      <button class="btn pri" data-install style="margin-top:12px">Update and restart</button>`;
  else if (upd.status === "installing" || upd.status === "restarting") body = `<p>Installing…</p>${checkList(upd.checks)}`;
  else if (upd.status === "error") body = `<p class="err" style="margin:0">${esc(upd.error)}</p>${checkList(upd.checks)}`;
  else body = `<p>You're on the latest version (${esc(sys?.version || "")}).</p>`;
  card.innerHTML = `<h3>App updates</h3>${body}
    <p class="muted small" style="margin:10px 0 0">Every update is checked before it installs: release signature, version, file size and SHA-256 checksum${navigator.platform.startsWith("Mac") ? ", and the new app's code signature and identity" : ""}.</p>
    ${["dev", "installing", "restarting"].includes(upd.status) ? "" : `<button class="btn ghost sm" data-check style="margin-top:8px">Check now</button>`}`;
}

document.addEventListener("click", async e => {
  const b = e.target.closest("[data-install],[data-check],[data-dismiss],[data-view-go]");
  if (!b) return;
  if (b.dataset.viewGo) return document.querySelector(`.ri[data-view="${b.dataset.viewGo}"]`).click();
  if (b.hasAttribute("data-dismiss")) { $("#updateBar").dataset.dismissed = upd.status; $("#updateBar").hidden = true; return; }
  b.disabled = true;
  try {
    upd = await api(b.hasAttribute("data-install") ? "/api/app-update/install" : "/api/app-update/check", {});
    if (b.hasAttribute("data-check") && upd.status === "current") toast("You're on the latest version");
  } catch (ex) { toast(ex.message); }
  b.disabled = false;
  loadUpdate();
});

/* ---------------- views ---------------- */

document.querySelectorAll(".ri[data-view]").forEach(b => b.addEventListener("click", () => {
  document.querySelectorAll(".ri[data-view]").forEach(x => x.classList.toggle("on", x === b));
  $("#v-download").hidden = b.dataset.view !== "download";
  $("#v-settings").hidden = b.dataset.view !== "settings";
  $("#viewTitle").textContent = b.dataset.view === "download" ? "Download" : "Settings";
}));

renderQueue();
connect();
loadSystem().then(() => { loadUpdate(); loadAccount(); }).catch(ex => toast(ex.message));
$("#url").focus();
