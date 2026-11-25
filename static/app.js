// FinAI C — user interface (plain JavaScript, no external dependencies: works fully offline)
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let META = null, COMPANIES = [], DOCS = [];

async function api(url, opts = {}) {
  if (opts.json !== undefined) {
    opts.body = JSON.stringify(opts.json);
    opts.headers = { "Content-Type": "application/json" };
    delete opts.json;
  }
  const r = await fetch(url, opts);
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) {
    const d = data && data.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => x.msg).join("; ") : `Error ${r.status}`);
  }
  return data;
}

function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show" + (err ? " err" : "");
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.className = ""), err ? 6000 : 2500);
}

const money = (n, d = 2) => n == null ? "—" : Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (x, d = 1) => x == null ? "—" : (x * 100).toFixed(d) + "%";
const num = (x, d = 2) => x == null ? "—" : Number(x).toFixed(d);
const pm = (m, s, f) => m == null ? "—" : f(m) + (s ? ` <span class="muted small">±${f(s)}</span>` : "");
const secs = (x) => x == null ? "—" : num(x, 1) + " s";

// ------------------------------------------------------------------ navigation
const TITLES = { dashboard: "Dashboard", transactions: "Income & expenses", documents: "Financial statements",
  run: "Run local models", compare: "Model comparison", phone: "Results from the phone", settings: "Settings" };
const LOADERS = {};

function show(view) {
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "v-" + view));
  $$("nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $("#title").textContent = TITLES[view];
  if (location.hash.slice(1) !== view) history.replaceState(null, "", "#" + view);
  LOADERS[view] && LOADERS[view]();
}
window.addEventListener("hashchange", () => TITLES[location.hash.slice(1)] && show(location.hash.slice(1)));
$$("nav button").forEach((b) => (b.onclick = () => show(b.dataset.view)));

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    const d = (ok) => `<span class="dot ${ok ? "ok" : "bad"}"></span>`;
    $("#status").innerHTML = `${d(s.ollama)}Ollama<br>${d(s.openai)}OpenAI-compatible server<br>${d(s.tesseract)}Tesseract OCR<br>
      <span class="muted">${s.n_models} local models found</span>`;
  } catch { $("#status").textContent = "Backend unavailable"; }
}

async function loadCompanies() {
  COMPANIES = await api("/api/companies");
  $$(".sel-company").forEach((sel) => {
    const cur = sel.value;
    const first = sel.dataset.none ? `<option value="">— choose —</option>` : sel.dataset.all ? `<option value="">All companies</option>` : "";
    sel.innerHTML = first + COMPANIES.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
    if (cur) sel.value = cur;
  });
}

const docOptions = () => DOCS.map((d) => `<option value="${d.id}">#${d.id} ${esc(d.filename)}</option>`).join("");

// ------------------------------------------------------------------ dashboard
LOADERS.dashboard = async () => {
  const data = await api("/api/dashboard");
  if (!data.length) {
    $("#dash").innerHTML = `<div class="card muted">No companies yet. Start from "Financial statements" or "Income &amp; expenses".</div>`;
    return;
  }
  $("#dash").innerHTML = data.map((c) => {
    const ind = c.indicators || {};
    const kp = Object.entries(META.indicators).map(([k, l]) =>
      `<div class="kpi"><div class="l">${esc(l)}</div><div class="v">${ind[k] == null ? "—" : money(ind[k], 2)}</div></div>`).join("");
    const max = Math.max(1, ...c.monthly.map((m) => Math.max(m.income, m.expenses)));
    const months = c.monthly.map((m) => `<tr><td>${m.month}</td>
      <td><div class="bar" style="width:${(m.income / max) * 100}%;background:var(--ok)"></div></td>
      <td><div class="bar" style="width:${(m.expenses / max) * 100}%;background:var(--bad)"></div></td>
      <td class="num">${money(m.income - m.expenses)}</td></tr>`).join("");
    return `<div class="card">
      <h3>${esc(c.name)} <span class="muted small">${c.tax_id ? "Tax ID " + esc(c.tax_id) : ""} · ${c.n_documents} documents</span></h3>
      <div class="kpis" style="margin-bottom:14px">
        <div class="kpi"><div class="l">Income (transactions)</div><div class="v" style="color:var(--ok)">${money(c.income)}</div></div>
        <div class="kpi"><div class="l">Expenses (transactions)</div><div class="v" style="color:var(--bad)">${money(c.expenses)}</div></div>
        <div class="kpi"><div class="l">Result</div><div class="v">${money(c.result)}</div></div>
      </div>
      ${c.values ? `<p class="small muted">Indicators from the statement: <b>${esc(c.document.filename)}</b></p><div class="kpis">${kp}</div>`
        : `<p class="muted small">No accepted statement for this company yet.</p>`}
      ${months ? `<h3 style="margin-top:16px">Recent months</h3><table><tr><th>Month</th><th>Income</th><th>Expenses</th><th class="num">Balance</th></tr>${months}</table>` : ""}
    </div>`;
  }).join("");
};

// ------------------------------------------------------------------ transactions
function fillCategories() {
  $("#tr-cat").innerHTML = META.categories[$("#tr-type").value].map((c) => `<option>${esc(c)}</option>`).join("");
}
$("#tr-type").onchange = fillCategories;
$("#tr-date").valueAsDate = new Date();

LOADERS.transactions = async () => {
  await loadCompanies();
  const c = $("#tr-filter-company").value, m = $("#tr-filter-month").value;
  const qs = new URLSearchParams();
  if (c) qs.set("company_id", c);
  if (m) qs.set("month", m);
  const rows = await api("/api/transactions?" + qs);
  $("#tr-table").innerHTML = `<tr><th>Date</th><th>Company</th><th>Type</th><th>Category</th><th>Description</th><th class="num">Amount</th><th></th></tr>` +
    (rows.map((t) => `<tr><td>${t.date}</td><td>${esc(t.company)}</td>
      <td><span class="badge ${t.type === "income" ? "ok" : "bad"}">${t.type}</span></td>
      <td>${esc(t.category)}</td><td class="muted">${esc(t.description)}</td><td class="num">${money(t.amount)}</td>
      <td><button class="small danger" data-del="${t.id}">✕</button></td></tr>`).join("") ||
      `<tr><td colspan="7" class="muted">No transactions.</td></tr>`);
  $$("[data-del]", $("#tr-table")).forEach((b) => (b.onclick = async () => {
    await api("/api/transactions/" + b.dataset.del, { method: "DELETE" });
    LOADERS.transactions();
  }));
  const sum = {};
  rows.forEach((t) => { sum[t.type + "|" + t.category] = (sum[t.type + "|" + t.category] || 0) + t.amount; });
  const inc = rows.filter((t) => t.type === "income").reduce((a, t) => a + t.amount, 0);
  const exp = rows.filter((t) => t.type === "expense").reduce((a, t) => a + t.amount, 0);
  $("#tr-summary").innerHTML = `<table>${Object.entries(sum).sort((a, b) => b[1] - a[1]).map(([k, v]) => {
    const [type, cat] = k.split("|");
    return `<tr><td><span class="badge ${type === "income" ? "ok" : "bad"}">${type === "income" ? "+" : "−"}</span> ${esc(cat)}</td><td class="num">${money(v)}</td></tr>`;
  }).join("")}<tr><th>Income − expenses</th><th class="num">${money(inc - exp)}</th></tr></table>`;
};
$("#tr-filter-company").onchange = $("#tr-filter-month").onchange = () => LOADERS.transactions();
$("#f-tr").onsubmit = async (e) => {
  e.preventDefault();
  const d = Object.fromEntries(new FormData(e.target));
  if (!d.company_id) return toast("Add a company first (from \"Financial statements\").", true);
  try {
    await api("/api/transactions", { method: "POST", json: { ...d, company_id: +d.company_id, amount: +d.amount } });
    e.target.amount.value = ""; e.target.description.value = "";
    toast("Transaction saved");
    LOADERS.transactions();
  } catch (err) { toast(err.message, true); }
};

// ------------------------------------------------------------------ documents
LOADERS.documents = async () => {
  await loadCompanies();
  DOCS = await api("/api/documents");
  $("#doc-table").innerHTML = `<tr><th>#</th><th>Company</th><th>File</th><th>Pages</th><th>Text layer</th>
    <th>Ground truth</th><th>Runs</th><th>In dashboard</th><th></th></tr>` +
    (DOCS.map((d) => `<tr class="click" data-id="${d.id}"><td>${d.id}</td><td>${esc(d.company)}</td><td>${esc(d.filename)}</td>
      <td>${d.pages}</td><td>${d.has_text ? '<span class="badge">yes</span>' : '<span class="badge warn">scanned</span>'}</td>
      <td>${d.has_gt ? '<span class="badge ok">filled in</span>' : '<span class="badge warn">missing</span>'}</td>
      <td>${d.n_runs}</td><td>${d.accepted_run ? "✓" : ""}</td>
      <td><button class="small danger" data-del="${d.id}">Delete</button></td></tr>`).join("") ||
      `<tr><td colspan="9" class="muted">No documents yet.</td></tr>`);
  $$("tr.click", $("#doc-table")).forEach((tr) => (tr.onclick = (e) => { if (!e.target.dataset.del) openDoc(+tr.dataset.id); }));
  $$("[data-del]", $("#doc-table")).forEach((b) => (b.onclick = async () => {
    if (!confirm("Delete the document and all its runs?")) return;
    await api("/api/documents/" + b.dataset.del, { method: "DELETE" });
    $("#doc-detail").innerHTML = "";
    LOADERS.documents();
  }));
};

$("#f-upload").onsubmit = async (e) => {
  e.preventDefault();
  const f = e.target, files = [...f.file.files];
  if (!f.company_id.value && !f.new_company.value.trim()) return toast("Choose a company or type the name of a new one.", true);
  let companyId = f.company_id.value;
  try {
    for (const file of files) {
      const fd = new FormData();
      fd.append("file", file);
      if (companyId) fd.append("company_id", companyId);
      else { fd.append("new_company", f.new_company.value); if (f.tax_id.value) fd.append("tax_id", f.tax_id.value); }
      const r = await api("/api/documents", { method: "POST", body: fd });
      companyId = companyId || r.company_id;
    }
    f.reset();
    toast(`${files.length} document(s) uploaded`);
    await LOADERS.documents();
  } catch (err) { toast(err.message, true); }
};

const STATUS_ICON = { correct: "✓", close: "≈", wrong_column: "⇄", scale_error: "×10", wrong_sign: "±", wrong: "✗", missing: "∅", hallucinated: "!", correct_null: "·" };

async function openDoc(id) {
  const [d, runs] = await Promise.all([api("/api/documents/" + id), api("/api/runs?document_id=" + id)]);
  const gt = d.ground_truth || {};
  const pages = Array.from({ length: d.pages }, (_, i) =>
    `<img src="/api/documents/${id}/page/${i + 1}" loading="lazy" onclick="this.classList.toggle('zoom')" alt="page ${i + 1}">`).join("");
  const val = (v) => v == null ? "" : money(v);
  const gtRows = Object.entries(META.text_fields).map(([k, l]) =>
    `<tr><td>${esc(l)}</td><td colspan="2"><input data-k="${k}" value="${esc(gt[k] ?? "")}"></td></tr>`).join("") +
    Object.entries(META.numeric_fields).map(([k, l]) => {
      const g = gt[k] || {};
      return `<tr><td>${esc(l)}</td><td><input data-k="${k}" data-c="end" value="${esc(val(g.end))}" placeholder="empty = not in document"></td>
        <td><input data-k="${k}" data-c="start" value="${esc(val(g.start))}"></td></tr>`;
    }).join("");
  const fields = Object.keys(META.numeric_fields);
  const runRows = runs.map((r) => {
    const m = r.metrics || {}, pf = m.per_field || {};
    return `<tr><td>${r.id}</td><td>${esc(r.model)}<br><span class="muted small">${esc(META.pipelines[r.pipeline] || r.pipeline)} · ${esc(r.device)}${r.config ? " · " + esc(r.config) : ""}</span></td>
      <td class="num">${pct(m.accuracy, 0)}</td><td class="num">${num(m.f1)}</td><td class="num">${secs(r.total_time)}</td>
      <td>${r.error ? `<span class="badge bad" title="${esc(r.error)}">error</span>` :
        fields.map((k) => `<span class="st-${pf[k] || ""}" title="${k}: ${esc(META.statuses[pf[k]] || "")}">${STATUS_ICON[pf[k]] || "?"}</span>`).join(" ")}</td>
      <td><button class="small" data-raw="${r.id}">Details</button>
        ${r.error ? "" : `<button class="small" data-acc="${r.id}">${d.accepted_run === r.id ? "✓ in dashboard" : "Use in dashboard"}</button>`}
        <button class="small danger" data-delrun="${r.id}">✕</button></td></tr>`;
  }).join("");

  $("#doc-detail").innerHTML = `
    <div class="card"><h3>${esc(d.filename)} <span class="muted small">· ${esc(d.company)} · ${d.pages} pages</span></h3>
      <div class="pages">${pages}</div></div>
    <div class="grid2">
      <form class="card gt" id="f-gt"><h3>Ground truth (correct values)</h3>
        <p class="muted small">Fill these in once, by hand, looking at the document. All models are scored against them.
          Leave a field empty if the item <b>does not exist</b> in the document: if a model still returns a value, it counts as a
          hallucination. Amounts can be typed as in the document (e.g. 1.689.799,07).</p>
        <table><tr><th>Field</th><th>End of period</th><th>Start of period</th></tr>${gtRows}</table>
        <div class="row" style="margin-top:12px"><button class="primary">Save and rescore</button>
          <label style="margin:0">Import JSON<input type="file" accept=".json" id="gt-file"></label></div>
      </form>
      <div class="card"><h3>Runs on this document</h3>
        <div class="legend">${Object.entries(STATUS_ICON).map(([k, v]) => `<span class="st-${k}">${v} ${esc(META.statuses[k])}</span>`).join("")}</div>
        <div class="scroll"><table><tr><th>#</th><th>Model</th><th class="num">Acc.</th><th class="num">F1</th><th class="num">Time</th>
          <th>Fields</th><th></th></tr>${runRows || `<tr><td colspan="7" class="muted">No runs. Go to "Run models".</td></tr>`}</table></div>
        <div id="run-raw"></div>
      </div>
    </div>`;
  $("#doc-detail").scrollIntoView({ behavior: "smooth" });

  $("#f-gt").onsubmit = async (e) => {
    e.preventDefault();
    const v = {};
    $$("input[data-k]", e.target).forEach((i) => {
      const k = i.dataset.k, c = i.dataset.c, x = i.value.trim() || null;
      if (!c) v[k] = x; else (v[k] = v[k] || {})[c] = x;   // the server reads both 1,234.56 and 1.234,56
    });
    try { await api(`/api/documents/${id}/ground-truth`, { method: "PUT", json: { values: v } }); toast("Saved; metrics recomputed"); openDoc(id); }
    catch (err) { toast(err.message, true); }
  };
  $("#gt-file").onchange = async (e) => {
    try {
      const v = JSON.parse(await e.target.files[0].text());
      await api(`/api/documents/${id}/ground-truth`, { method: "PUT", json: { values: v } });
      toast("Ground truth imported"); openDoc(id);
    } catch (err) { toast("Invalid JSON: " + err.message, true); }
  };
  $$("[data-acc]").forEach((b) => (b.onclick = async () => {
    await api(`/api/documents/${id}/accept/${b.dataset.acc}`, { method: "POST" });
    toast("The values of this run are now used in the dashboard"); openDoc(id);
  }));
  $$("[data-delrun]").forEach((b) => (b.onclick = async () => {
    await api("/api/runs/" + b.dataset.delrun, { method: "DELETE" }); openDoc(id);
  }));
  $$("[data-raw]").forEach((b) => (b.onclick = async () => {
    const r = await api("/api/runs/" + b.dataset.raw);
    const m = r.metrics || {}, ex = r.extracted || {}, pf = m.per_field || {};
    const g = (k) => (gt[k] && typeof gt[k] === "object") ? gt[k].end : null;
    $("#run-raw").innerHTML = `<h3 style="margin-top:16px">Run #${r.id}: ${esc(r.model)}</h3>
      <table><tr><th>Field</th><th class="num">Extracted</th><th class="num">Correct</th><th>Status</th></tr>
      ${Object.entries(META.numeric_fields).map(([k, l]) => `<tr><td>${esc(l)}</td><td class="num">${money(ex[k])}</td>
        <td class="num">${money(g(k))}</td><td class="st-${pf[k] || ""}">${esc(META.statuses[pf[k]] || "")}</td></tr>`).join("")}</table>
      <p class="small"><b>Accounting checks:</b> ${(m.checks || []).map((v) => `${v.ok === true ? "✓" : v.ok === false ? "✗" : "·"} ${esc(v.name)}`).join(" &nbsp; ")}</p>
      <p class="small muted">Valid JSON: ${r.json_valid == null ? "—" : r.json_valid ? "yes" : "no (recovered from text)"} ·
        tokens: ${r.tokens_generated ?? "—"} · ${num(r.tokens_per_sec, 1)} tok/s · model load: ${secs(r.load_time)} · memory: ${r.memory_mb ? money(r.memory_mb, 0) + " MB" : "—"}</p>
      ${r.error ? `<p class="badge bad">${esc(r.error)}</p>` : ""}
      <h3>Raw model output</h3><pre class="pre small">${esc(r.raw_output)}</pre>`;
  }));
}

// ------------------------------------------------------------------ run
async function loadModels() {
  $("#run-models").innerHTML = `<span class="muted">Looking for models…</span>`;
  const m = await api("/api/models");
  const errs = Object.keys(m.errors).map((k) => `<p class="small muted">${k === "ollama" ? "Ollama" : "OpenAI-compatible server"}: unavailable</p>`).join("");
  $("#run-models").innerHTML = (m.models.map((x) => `<label><input type="checkbox" value="${esc(x.id)}">${esc(x.name)}
      ${x.vision ? "👁" : ""}${x.embedding ? '<span class="badge">embedding</span>' : ""}<span class="meta">${[x.parameters, x.quantization, x.size_gb ? x.size_gb + " GB" : "", x.runtime === "openai" ? "OpenAI-compat" : ""].filter(Boolean).join(" · ")}</span></label>`).join("") ||
    `<p class="muted small">No models found. Start Ollama and pull models (see README), then press ↻.</p>`) + errs;
}
$("#btn-refresh-models").onclick = loadModels;

LOADERS.run = async () => {
  DOCS = await api("/api/documents");
  $("#run-docs").innerHTML = DOCS.map((d) => `<label><input type="checkbox" value="${d.id}" checked>#${d.id} ${esc(d.filename)}
    <span class="meta">${d.has_gt ? "" : "no ground truth"}</span></label>`).join("") || `<p class="muted">Upload a document first.</p>`;
  $("#run-pipes").innerHTML = Object.entries(META.pipelines).map(([k, l]) =>
    `<label><input type="checkbox" value="${k}">${esc(l)}</label>`).join("");
  const s = await api("/api/settings");
  $("#run-config").innerHTML = `Current settings: <b>${s.prompt_example === "yes" ? "one-shot" : "zero-shot"}</b> prompt,
    <b>${s.constrained_output === "yes" ? "constrained" : "free"}</b> output, max image side ${esc(s.max_side_px)} px,
    device "${esc(s.device)}". <a href="#settings">Change</a>`;
  loadModels();
  renderJobs();
};

$("#btn-run").onclick = async () => {
  const body = {
    documents: $$("#run-docs input:checked").map((i) => +i.value),
    models: $$("#run-models input:checked").map((i) => i.value),
    pipelines: $$("#run-pipes input:checked").map((i) => i.value),
    repetitions: +$("#run-rep").value || 1,
  };
  $("#btn-run").disabled = true;
  try {
    const j = await api("/api/runs", { method: "POST", json: body });
    toast(`Benchmark started: ${j.total} runs`);
    renderJobs();
  } catch (err) { toast(err.message, true); }
  finally { $("#btn-run").disabled = false; }
};

let jobTimer = null;
async function renderJobs() {
  const jobs = await api("/api/jobs");
  $("#jobs").innerHTML = jobs.map((j) => `<div class="card">
    <h3>Job ${j.id} <span class="badge ${j.state === "finished" ? "ok" : j.state === "cancelled" ? "bad" : ""}">${j.state}</span>
      ${j.state === "running" || j.state === "queued" ? `<button class="small danger" data-cancel="${j.id}">Cancel</button>` : ""}</h3>
    <div class="progress"><div style="width:${j.total ? (j.done / j.total) * 100 : 0}%"></div></div>
    <p class="small">${j.done} / ${j.total} runs${j.errors ? ` · <span style="color:var(--bad)">${j.errors} errors</span>` : ""}
      ${j.current ? `<br>Now: <b>${esc(j.current)}</b>` : ""}</p>
    <details><summary class="small muted">Log</summary><pre class="pre small">${esc(j.log.join("\n"))}</pre></details></div>`).join("");
  $$("[data-cancel]").forEach((b) => (b.onclick = () => api(`/api/jobs/${b.dataset.cancel}/cancel`, { method: "POST" })));
  clearTimeout(jobTimer);
  if (jobs.some((j) => j.state === "running" || j.state === "queued") && $("#v-run").classList.contains("active"))
    jobTimer = setTimeout(renderJobs, 1500);
}

// ------------------------------------------------------------------ comparison
const ERR_COLORS = { correct: "#2f9e44", close: "#94d82d", wrong_column: "#fab005", scale_error: "#fd7e14",
  wrong_sign: "#e64980", wrong: "#c92a2a", missing: "#868e96", hallucinated: "#7048e8" };

LOADERS.compare = async () => {
  DOCS = await api("/api/documents");
  const sel = $("#cmp-doc"), cur = sel.value;
  sel.innerHTML = `<option value="">All documents</option>` + docOptions();
  sel.value = cur;
  const qs = cur ? "?document_id=" + cur : "";
  $("#exp-summary").href = "/api/export/summary.csv" + qs;
  $("#exp-runs").href = "/api/export/runs.csv" + qs;
  const rows = await api("/api/compare" + qs);
  if (!rows.length) {
    $("#cmp-table").innerHTML = `<tr><td class="muted">No runs yet.</td></tr>`;
    $("#cmp-fields").innerHTML = $("#cmp-errors").innerHTML = $("#cmp-scatter").innerHTML = "";
    return;
  }
  const name = (r) => `${esc(r.model)}<br><span class="muted small">${esc(r.pipeline_name)} · ${esc(r.device)}${r.config ? " · " + esc(r.config) : ""}</span>`;
  $("#cmp-table").innerHTML = `<tr><th>Model / pipeline</th><th class="num">Runs</th><th class="num">Accuracy</th><th class="num">Acc. ±1%</th>
    <th class="num">Precision</th><th class="num">F1</th><th class="num">Hallucinations</th><th class="num">Indicator error</th>
    <th class="num">Consistency</th><th class="num">Valid JSON</th><th class="num">Time / doc</th><th class="num">Load</th>
    <th class="num">Tok/s</th><th class="num">Memory</th></tr>` +
    rows.map((r) => `<tr><td>${name(r)}</td><td class="num">${r.n_runs}${r.n_errors ? ` <span class="badge bad">${r.n_errors} err</span>` : ""}</td>
      <td class="num">${pm(r.accuracy, r.accuracy_std, (x) => pct(x, 0))}</td><td class="num">${pct(r.accuracy_tolerant, 0)}</td>
      <td class="num">${pct(r.precision, 0)}</td><td class="num"><b>${num(r.f1)}</b></td><td class="num">${pct(r.hallucination_rate, 0)}</td>
      <td class="num">${pct(r.indicator_error, 1)}</td><td class="num">${pct(r.consistency, 0)}</td><td class="num">${pct(r.json_valid, 0)}</td>
      <td class="num">${pm(r.total_time, r.total_time_std, (x) => num(x, 1) + " s")}</td><td class="num">${secs(r.load_time)}</td>
      <td class="num">${num(r.tokens_per_sec, 1)}</td><td class="num">${r.memory_mb ? money(r.memory_mb / 1024, 1) + " GB" : "—"}</td></tr>`).join("");

  const fields = Object.keys(META.numeric_fields);
  const color = (v) => v == null ? "#f1f3f5" : `hsl(${v * 120}, 60%, ${88 - v * 30}%)`;
  $("#cmp-fields").innerHTML = `<table><tr><th>Model</th>${fields.map((k) => `<th class="cell" title="${esc(META.numeric_fields[k])}">${k.replace(/_/g, " ")}</th>`).join("")}</tr>` +
    rows.map((r) => `<tr><td class="small">${esc(r.model)}<br><span class="muted">${esc(r.pipeline)}${r.config ? " · " + esc(r.config) : ""}</span></td>${fields.map((k) => {
      const v = r.per_field[k];
      return `<td class="cell" style="background:${color(v)}">${v == null ? "" : Math.round(v * 100)}</td>`;
    }).join("")}</tr>`).join("") + `</table><p class="muted small">% of runs in which the field was extracted exactly. Empty = the item does not exist in the documents with ground truth.</p>`;

  $("#cmp-errors").innerHTML = rows.map((r) => {
    const c = r.error_types, tot = Object.entries(c).filter(([k]) => k !== "correct_null").reduce((a, [, v]) => a + v, 0) || 1;
    return `<div style="margin-bottom:10px"><div class="small">${esc(r.model)} <span class="muted">· ${esc(r.pipeline)}${r.config ? " · " + esc(r.config) : ""}</span></div>
      <div class="stack">${Object.entries(ERR_COLORS).map(([k, col]) => c[k] ? `<div title="${esc(META.statuses[k])}: ${c[k]}" style="width:${(c[k] / tot) * 100}%;background:${col}"></div>` : "").join("")}</div></div>`;
  }).join("") + `<div class="legend">${Object.entries(ERR_COLORS).map(([k, c]) => `<span><i style="background:${c}"></i>${esc(META.statuses[k])}</span>`).join("")}</div>`;

  // scatter: time (x, log scale) vs F1 (y)
  const pts = rows.filter((r) => r.total_time != null && r.f1 != null && r.total_time > 0);
  if (!pts.length) { $("#cmp-scatter").innerHTML = ""; return; }
  const W = 760, H = 320, P = 50;
  const tmin = Math.min(...pts.map((r) => r.total_time)), tmax = Math.max(...pts.map((r) => r.total_time));
  const lo = Math.log10(tmin * 0.8), hi = Math.log10(tmax * 1.25);
  const lx = (t) => P + ((Math.log10(t) - lo) / ((hi - lo) || 1)) * (W - 2 * P);
  const ly = (f) => H - P - f * (H - 2 * P);
  $("#cmp-scatter").innerHTML = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:${W}px">
    <line x1="${P}" y1="${H - P}" x2="${W - P}" y2="${H - P}" stroke="#ccc"/><line x1="${P}" y1="${P}" x2="${P}" y2="${H - P}" stroke="#ccc"/>
    ${[0, 0.25, 0.5, 0.75, 1].map((f) => `<text x="${P - 8}" y="${ly(f) + 4}" font-size="11" text-anchor="end" fill="#888">${f}</text>
      <line x1="${P}" y1="${ly(f)}" x2="${W - P}" y2="${ly(f)}" stroke="#f1f1f1"/>`).join("")}
    <text x="${W / 2}" y="${H - 12}" font-size="12" text-anchor="middle" fill="#666">Time per document (s, log scale) — further left = faster</text>
    <text x="14" y="${H / 2}" font-size="12" text-anchor="middle" fill="#666" transform="rotate(-90 14 ${H / 2})">F1</text>
    ${pts.map((r) => `<circle cx="${lx(r.total_time)}" cy="${ly(r.f1)}" r="6" fill="${r.device && !r.device.toLowerCase().includes("laptop") ? "#e8590c" : "#3b5bdb"}" opacity=".8"><title>${esc(r.model)} · ${esc(r.pipeline)} · ${esc(r.device)}: F1 ${num(r.f1)}, ${num(r.total_time, 1)} s</title></circle>
      <text x="${lx(r.total_time) + 9}" y="${ly(r.f1) + 4}" font-size="11" fill="#444">${esc(r.model.split("/").pop())} (${esc(r.pipeline)})</text>`).join("")}
  </svg><p class="muted small">Blue = laptop, orange = other devices (phone).</p>`;
};
$("#cmp-doc").onchange = () => LOADERS.compare();

// ------------------------------------------------------------------ phone
async function loadPrompt() {
  const mode = $("#ph-mode").value, doc = $("#ph-doc-prompt").value;
  $("#prompt-text").textContent = "Preparing…";
  try {
    $("#prompt-text").textContent = await api(`/api/prompt?pipeline=${mode}` + (doc ? `&document_id=${doc}` : ""));
  } catch (err) { $("#prompt-text").textContent = err.message; }
}
LOADERS.phone = async () => {
  DOCS = await api("/api/documents");
  const cur = $("#ph-doc-prompt").value;
  $("#ph-doc").innerHTML = $("#ph-doc-prompt").innerHTML = docOptions();
  if (cur) $("#ph-doc-prompt").value = $("#ph-doc").value = cur;
  const s = await api("/api/settings");
  $("#ph-example-note").textContent = `The prompt is ${s.prompt_example === "yes" ? "one-shot (with an example answer)" : "zero-shot (without an example)"}, as set in Settings. Use the same setting on the laptop so the comparison is fair.`;
  loadPrompt();
};
$("#ph-mode").onchange = () => { $("#ph-pipe").value = $("#ph-mode").value; loadPrompt(); };
$("#ph-doc-prompt").onchange = () => { $("#ph-doc").value = $("#ph-doc-prompt").value; loadPrompt(); };
$("#btn-copy-prompt").onclick = async () => {
  try { await navigator.clipboard.writeText($("#prompt-text").textContent); toast("Prompt copied"); }
  catch { toast("Select the text and copy it by hand.", true); }
};
$("#f-phone").onsubmit = async (e) => {
  e.preventDefault();
  const d = Object.fromEntries(new FormData(e.target));
  for (const k of ["total_time", "tokens_per_sec", "memory_mb"]) d[k] = d[k] ? +d[k] : null;
  d.document_id = +d.document_id;
  try {
    const r = await api("/api/runs/external", { method: "POST", json: d });
    const m = r.metrics;
    $("#ph-result").innerHTML = `<p>Saved as run #${r.id}. Accuracy: <b>${pct(m.accuracy, 0)}</b>, F1: <b>${num(m.f1)}</b>,
      hallucinations: ${pct(m.hallucination_rate, 0)} ${m.accuracy == null ? '<span class="muted">(the document has no ground truth)</span>' : ""}</p>`;
    e.target.answer.value = "";
    toast("Result saved");
  } catch (err) { toast(err.message, true); }
};

// ------------------------------------------------------------------ settings
LOADERS.settings = async () => {
  const s = await api("/api/settings");
  for (const [k, v] of Object.entries(s)) if ($("#f-settings")[k]) $("#f-settings")[k].value = v;
};
$("#f-settings").onsubmit = async (e) => {
  e.preventDefault();
  await api("/api/settings", { method: "POST", json: Object.fromEntries(new FormData(e.target)) });
  toast("Settings saved"); refreshStatus();
};

// ------------------------------------------------------------------ start
(async () => {
  META = await api("/api/meta");
  fillCategories();
  await loadCompanies();
  refreshStatus();
  show(TITLES[location.hash.slice(1)] ? location.hash.slice(1) : "dashboard");
})();
