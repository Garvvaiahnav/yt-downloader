"use strict";
// Video Downloader panel for After Effects. Downloads go through the desktop
// app's local API (it does the probing, converting and ffprobe checks); this
// panel only picks the output and imports the finished file into AE.
//
// Inside AE the API is reached with Node's http module (CEP has no CORS
// exemption for file:// pages); in a plain browser preview, with fetch.

const node = window.cep_node ? window.cep_node.require : (typeof require === "function" ? require : null);
const inAE = !!window.__adobe_cep__;
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let port = null, info = null, mode = "prores", maxH = null, watching = null;

function call(method, path, body) {
  if (!node) {
    return fetch(path, { method, headers: { "X-VD": "1", "Content-Type": "application/json" },
                         body: body ? JSON.stringify(body) : undefined })
      .then(async r => { const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(d.error || d.detail || r.status); return d; });
  }
  return new Promise((resolve, reject) => {
    const data = body ? JSON.stringify(body) : null;
    const req = node("http").request({ host: "127.0.0.1", port, path, method, timeout: 120000,
      headers: { "X-VD": "1", "Content-Type": "application/json", ...(data ? { "Content-Length": Buffer.byteLength(data) } : {}) } },
      res => {
        let buf = "";
        res.setEncoding("utf8");
        res.on("data", c => (buf += c));
        res.on("end", () => {
          let d = {};
          try { d = JSON.parse(buf); } catch (_) { /* empty body */ }
          res.statusCode < 300 ? resolve(d) : reject(new Error(d.error || d.detail || `HTTP ${res.statusCode}`));
        });
      });
    req.on("error", reject);
    req.on("timeout", () => req.destroy(new Error("No answer from Video Downloader")));
    if (data) req.write(data);
    req.end();
  });
}

// The app listens on the first free port from 8765; find the one that is ours.
async function findApp() {
  if (!node) { port = location.port; return call("GET", "/api/system"); }
  for (let p = 8765; p < 8815; p++) {
    port = p;
    try {
      const sys = await call("GET", "/api/system");
      if (sys && sys.version && "encoders" in sys) return sys;
    } catch (_) { /* not this port */ }
  }
  port = null;
  return null;
}

async function connect() {
  const sys = await findApp();
  $("#offline").hidden = !!sys;
  $("#main").hidden = !sys;
  $("#conn").textContent = sys ? `Connected · v${sys.version}` : "App not running";
  $("#conn").className = sys ? "ok" : "";
  if (sys) loadRecent();
  return sys;
}

function extensionDir() {
  let p = window.__adobe_cep__.getSystemPath("extension");
  p = decodeURIComponent(p.replace(/^file:\/{2,3}/, process.platform === "win32" ? "" : "/"));
  return p;
}

$("#launch").addEventListener("click", async () => {
  const btn = $("#launch");
  btn.disabled = true;
  btn.textContent = "Opening…";
  try {
    const cfg = JSON.parse(node("fs").readFileSync(node("path").join(extensionDir(), "app.json"), "utf8"));
    if (!cfg.app) throw new Error("app path unknown");
    const cp = node("child_process");
    if (process.platform === "darwin") cp.spawn("open", [cfg.app], { detached: true, stdio: "ignore" }).unref();
    else cp.spawn(cfg.app, [], { detached: true, stdio: "ignore" }).unref();
    for (let i = 0; i < 30 && !(await connect()); i++) await new Promise(r => setTimeout(r, 1000));
  } catch (e) {
    $("#conn").textContent = "Open Video Downloader yourself, then come back.";
  }
  btn.disabled = false;
  btn.textContent = "Open Video Downloader";
});

function showErr(msg) {
  $("#err").textContent = msg || "";
  $("#err").hidden = !msg;
}

$("#getForm").addEventListener("submit", async e => {
  e.preventDefault();
  const url = $("#url").value.trim();
  if (!url) return;
  showErr("");
  $("#video").hidden = true;
  $("#getBtn").disabled = true;
  $("#getBtn").textContent = "…";
  try {
    info = await call("POST", "/api/probe", { url });
    renderVideo();
  } catch (ex) {
    showErr(ex.message);
  }
  $("#getBtn").disabled = false;
  $("#getBtn").textContent = "Get";
});

function renderVideo() {
  $("#thumb").style.backgroundImage = info.thumbnail ? `url('${info.thumbnail}')` : "";
  $("#title").textContent = info.title || info.url;
  $("#meta").textContent = [info.platform, info.max && `max ${info.max}`].filter(Boolean).join(" · ");
  const heights = [...new Set(info.video.map(v => v.label_h).filter(Boolean))].sort((a, b) => b - a).slice(0, 4);
  maxH = null;
  $("#res").innerHTML = [`<button data-h="" class="on">Best</button>`,
    ...heights.slice(1).map(h => `<button data-h="${h}">${h}p</button>`)].join("");
  $("#video").hidden = false;
}

$("#modes").addEventListener("click", e => {
  const b = e.target.closest("button");
  if (!b) return;
  mode = b.dataset.mode;
  document.querySelectorAll("#modes button").forEach(x => x.classList.toggle("on", x === b));
});

$("#res").addEventListener("click", e => {
  const b = e.target.closest("button");
  if (!b) return;
  maxH = b.dataset.h ? Number(b.dataset.h) : null;
  document.querySelectorAll("#res button").forEach(x => x.classList.toggle("on", x === b));
});

$("#go").addEventListener("click", async () => {
  $("#go").disabled = true;
  showErr("");
  try {
    const job = await call("POST", "/api/quick", { url: info.source_url, item: info.item, mode, max_h: maxH });
    follow(job.id, $("#toComp").checked);
  } catch (ex) {
    showErr(ex.message);
    $("#go").disabled = false;
  }
});

function setJob(text, pct, cls) {
  $("#job").hidden = false;
  $("#barFill").style.width = `${Math.round((pct || 0) * 100)}%`;
  $("#jobText").textContent = text;
  $("#jobText").className = cls || "";
}

// Poll the job until it's done, then import it.
function follow(id, toComp) {
  clearInterval(watching);
  setJob("Starting…", 0);
  watching = setInterval(async () => {
    let j;
    try { j = (await call("GET", "/api/jobs")).find(x => x.id === id); } catch (_) { return; }
    if (!j) return;
    if (j.status === "error" || j.status === "cancelled") {
      clearInterval(watching);
      setJob(j.error || "Cancelled", 0, "bad");
      $("#go").disabled = false;
    } else if (j.status === "done") {
      clearInterval(watching);
      setJob(j.verify && !j.verify.ok ? "Downloaded (with a check mismatch). Importing…" : "Verified. Importing…", 1);
      const msg = await importFile(j.file, toComp);
      setJob(msg.text, 1, msg.ok ? "ok" : "bad");
      $("#go").disabled = false;
      loadRecent();
    } else {
      setJob(`${j.stage}${j.progress ? ` · ${Math.round(j.progress * 100)}%` : ""}`, j.progress);
    }
  }, 700);
}

function importFile(path, toComp) {
  return new Promise(resolve => {
    if (!inAE) return resolve({ ok: true, text: `Saved: ${path}` });
    window.__adobe_cep__.evalScript(`vdImport(${JSON.stringify(path)}, ${toComp ? "true" : "false"})`, res => {
      const r = String(res || "");
      resolve(r.startsWith("ok:") ? { ok: true, text: r.slice(3) }
                                   : { ok: false, text: r.replace(/^error:/, "") || "Import failed" });
    });
  });
}

async function loadRecent() {
  let list = [];
  try { list = (await call("GET", "/api/jobs")).filter(j => j.status === "done" && j.file).slice(0, 8); } catch (_) { return; }
  $("#recent").innerHTML = list.length ? list.map(j => `
    <div class="rec">
      <div class="thumb" style="background-image:url('${esc(j.thumbnail || "")}')"></div>
      <div><b title="${esc(j.title)}">${esc(j.title)}</b><small>${esc(j.label)}</small></div>
      <button data-file="${esc(j.file)}">Import</button>
    </div>`).join("") : `<small class="muted">Nothing yet.</small>`;
}

$("#recent").addEventListener("click", async e => {
  const b = e.target.closest("button[data-file]");
  if (!b) return;
  b.disabled = true;
  const msg = await importFile(b.dataset.file, $("#toComp") ? $("#toComp").checked : false);
  setJob(msg.text, 1, msg.ok ? "ok" : "bad");
  b.disabled = false;
});

connect();
setInterval(() => { if (!port) connect(); }, 5000);
