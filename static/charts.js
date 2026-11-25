// FinAI C — "Charts & tables" page. Plain SVG, no external libraries (works offline).
// Every chart has a data-table view and a PNG export (for the paper).
(() => {
  // ---------------------------------------------------------------- palette (validated: dataviz reference palette)
  const C = {
    ink: "#0b0b0b", ink2: "#52514e", muted: "#8a8984", grid: "#ecebe8", axis: "#c9c8c3", surface: "#ffffff",
    model: { gemma: "#2a78d6", qwen: "#eb6834", bonsai: "#1baf7a", embed: "#eda100", rules: "#8a8984", other: "#6250d6" },
    approach: { "No generative model": "#2a78d6", "OCR + text LLM": "#eb6834", "Vision model (page images)": "#1baf7a" },
    pair: ["#2a78d6", "#eb6834"],
    seq: ["#eef4fd", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
  };
  const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

  // ---------------------------------------------------------------- labels
  const PIPE = {
    vlm_page: "VLM · page by page", vlm_document: "VLM · whole document", hybrid: "Hybrid · image + OCR text",
    ocr_llm: "OCR → LLM copies amounts", ocr_llm_rowpick: "OCR → LLM picks rows", ocr_rules: "OCR + rules",
    ocr_embeddings: "OCR + embeddings", vlm_ocr_rules: "AI OCR + rules",
  };
  const modelKey = (m) => {
    m = String(m || "").toLowerCase();
    if (m.includes("embeddinggemma")) return "embed";
    if (m.includes("gemma")) return "gemma";
    if (m.includes("qwen")) return "qwen";
    if (m.includes("bonsai")) return "bonsai";
    if (!m || m.includes("rules") || m === "—") return "rules";
    return "other";
  };
  const MODEL_NAME = { gemma: "Gemma 3n E2B", qwen: "Qwen2.5-VL 3B", bonsai: "Bonsai 8B (1-bit)", embed: "EmbeddingGemma",
    rules: "No model", other: "Other" };
  const approachOf = (p) => (p === "ocr_rules" || p === "ocr_embeddings" || p === "vlm_ocr_rules") ? "No generative model"
    : (p === "ocr_llm" || p === "ocr_llm_rowpick") ? "OCR + text LLM" : "Vision model (page images)";
  const isPhone = (d) => !!d && !String(d).toLowerCase().includes("laptop");

  function methodOf(r) {
    const mk = modelKey(r.model), cfg = String(r.config || "");
    const shot = cfg.includes("one-shot") ? "one-shot" : cfg.includes("zero-shot") ? "zero-shot" : "";
    const extra = [];
    if (shot === "one-shot") extra.push("one-shot");
    if (cfg.includes("constrained")) extra.push("constrained");
    if (cfg.includes("thinking")) extra.push("thinking");
    const px = cfg.match(/max (\d+) px/);
    if (px && px[1] !== "1024") extra.push(px[1] + " px");
    if (isPhone(r.device)) extra.push("phone");
    let label;
    if (r.pipeline === "ocr_rules") label = "OCR + rules";
    else if (r.pipeline === "ocr_embeddings") label = "OCR + embeddings (EmbeddingGemma)";
    else label = `${MODEL_NAME[mk] === "Other" ? String(r.model).split("/").pop() : MODEL_NAME[mk]} · ${PIPE[r.pipeline] || r.pipeline}`;
    if (extra.length) label += ` · ${extra.join(", ")}`;
    return { label, mk, shot, phone: isPhone(r.device) };
  }

  function docLabel(d) {
    const comp = String(d.company || "");
    const par = comp.match(/\(([^)]+)\)/);
    let name = par ? par[1] : (comp.split(/\s+/).find((w) => w && !/^(sc|sa|srl)$/i.test(w)) || String(d.filename));
    if (!par) name = name.charAt(0).toUpperCase() + name.slice(1).toLowerCase();
    if (name.length > 12) name = name.slice(0, 12);
    const year = (String(d.filename).match(/20\d\d/) || [""])[0];
    return `${name} ${year}`.trim();
  }

  // ---------------------------------------------------------------- data
  let RUNS = [], DOCMAP = {};
  const mean = (a) => a.length ? a.reduce((s, x) => s + x, 0) / a.length : null;
  const sd = (a) => { if (a.length < 2) return 0; const m = mean(a); return Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / (a.length - 1)); };
  const vals = (rs, k) => rs.map((r) => r[k]).filter((v) => v != null && !Number.isNaN(v));

  function prepare(runs, docs) {
    DOCMAP = Object.fromEntries(docs.map((d) => [d.id, { ...d, label: docLabel(d), long: (d.pages || 0) > 5 }]));
    RUNS = runs.filter((r) => r.metrics && r.has_gt && DOCMAP[r.document_id]).map((r) => {
      const m = r.metrics, meth = methodOf(r), doc = DOCMAP[r.document_id];
      return {
        id: r.id, job: r.job_id, doc: r.document_id, docLabel: doc.label, long: doc.long, pipe: r.pipeline,
        approach: approachOf(r.pipeline), method: meth.label, mk: meth.mk, shot: meth.shot, phone: meth.phone,
        f1: m.f1, acc: m.accuracy, prec: m.precision, hall: m.hallucination_rate, ind: m.indicator_error,
        cons: m.consistency, time: r.total_time || null, tps: r.tokens_per_sec || null, err: !!r.error,
        json: r.json_valid, perField: m.per_field || {},
      };
    });
  }

  function aggregate(rs) {
    const g = {};
    rs.forEach((r) => (g[r.method] = g[r.method] || []).push(r));
    return Object.entries(g).map(([method, a]) => ({
      method, mk: a[0].mk, approach: a[0].approach, pipe: a[0].pipe, phone: a[0].phone, shot: a[0].shot, runs: a,
      n: a.length, nDocs: new Set(a.map((r) => r.doc)).size, nErr: a.filter((r) => r.err).length,
      f1: mean(vals(a, "f1")), f1sd: sd(vals(a, "f1")), acc: mean(vals(a, "acc")), prec: mean(vals(a, "prec")),
      hall: mean(vals(a, "hall")), ind: mean(vals(a, "ind")), time: mean(vals(a, "time").filter((t) => t > 0)),
      tps: mean(vals(a, "tps").filter((t) => t > 0)), json: mean(vals(a, "json")),
    })).sort((x, y) => (y.f1 ?? -1) - (x.f1 ?? -1));
  }

  // ---------------------------------------------------------------- filters
  const F = { docs: "short", device: "all" };
  function filtered({ ignoreDocs = false, ignoreDevice = false } = {}) {
    return RUNS.filter((r) => {
      if (!ignoreDevice && F.device === "laptop" && r.phone) return false;
      if (!ignoreDevice && F.device === "phone" && !r.phone) return false;
      if (ignoreDocs || F.docs === "all") return true;
      if (F.docs === "short") return !r.long;
      if (F.docs === "long") return r.long;
      return String(r.doc) === F.docs;
    });
  }

  // ---------------------------------------------------------------- formatting
  const f2 = (x) => x == null ? "—" : x.toFixed(2);
  const pc = (x, d = 0) => x == null ? "—" : (x * 100).toFixed(d) + "%";
  const sec = (x) => x == null ? "—" : x < 10 ? x.toFixed(1) + " s" : Math.round(x) + " s";
  const e = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const T = (x, y, s, o = {}) => `<text x="${x}" y="${y}" font-family='${FONT}' font-size="${o.size || 12}" fill="${o.fill || C.ink2}"${o.anchor ? ` text-anchor="${o.anchor}"` : ""}${o.weight ? ` font-weight="${o.weight}"` : ""}${o.extra || ""}>${e(s)}</text>`;
  const clip = (s, n) => s.length > n ? s.slice(0, n - 1) + "…" : s;

  // bar with the data end rounded (4 px) and the baseline end square
  function hbarPath(x, y, w, h, r = 4) {
    if (w <= 0) return "";
    r = Math.min(r, w, h / 2);
    return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
  }

  // ---------------------------------------------------------------- chart: horizontal bars
  function hbars(items, { max = 1, fmt = f2, labelW = 330, W = 820, ticks = [0, 0.25, 0.5, 0.75, 1], tickFmt = (t) => t } = {}) {
    const rowH = 26, top = 24, bh = 14;
    const H = top + items.length * rowH + 28;
    const x0 = labelW, x1 = W - 70, sx = (v) => x0 + (Math.max(0, v) / max) * (x1 - x0);
    let s = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" style="width:100%;max-width:${W}px;background:${C.surface}">`;
    s += ticks.map((t) => `<line x1="${sx(t)}" y1="${top - 6}" x2="${sx(t)}" y2="${H - 26}" stroke="${t === 0 ? C.axis : C.grid}"/>` +
      T(sx(t), H - 10, tickFmt(t), { anchor: "middle", size: 11, fill: C.muted })).join("");
    items.forEach((it, i) => {
      const y = top + i * rowH;
      s += T(labelW - 10, y + bh - 2, clip(it.label, 52), { anchor: "end", fill: C.ink, size: 12 });
      s += `<g data-tip="${e(it.tip || it.label)}"><rect x="0" y="${y - 5}" width="${W}" height="${rowH}" fill="transparent"/>`;
      s += `<path d="${hbarPath(x0, y, sx(it.value ?? 0) - x0, bh)}" fill="${it.color}"/>`;
      s += T(sx(it.value ?? 0) + 6, y + bh - 2, fmt(it.value), { size: 11.5, fill: C.ink, weight: 600 }) + `</g>`;
    });
    return s + `</svg>`;
  }

  // ---------------------------------------------------------------- chart: grouped horizontal bars (2 series)
  function hbars2(groups, series, { max = 1, fmt = f2, labelW = 330, W = 820 } = {}) {
    const bh = 11, gap = 2, rowH = bh * 2 + gap + 14, top = 40;
    const H = top + groups.length * rowH + 26;
    const x0 = labelW, x1 = W - 70, sx = (v) => x0 + (Math.max(0, v) / max) * (x1 - x0);
    let s = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" style="width:100%;max-width:${W}px;background:${C.surface}">`;
    series.forEach((sr, k) => {
      const lx = x0 + k * 230;
      s += `<rect x="${lx}" y="8" width="12" height="12" rx="3" fill="${C.pair[k]}"/>` + T(lx + 18, 18.5, sr, { fill: C.ink, size: 12 });
    });
    [0, 0.25, 0.5, 0.75, 1].map((t) => t * max).forEach((t) => {
      s += `<line x1="${sx(t)}" y1="${top - 6}" x2="${sx(t)}" y2="${H - 24}" stroke="${t === 0 ? C.axis : C.grid}"/>` +
        T(sx(t), H - 8, fmt === pc ? pc(t) : +t.toFixed(2), { anchor: "middle", size: 11, fill: C.muted });
    });
    groups.forEach((g, i) => {
      const y = top + i * rowH;
      s += T(labelW - 10, y + bh + 6, clip(g.label, 52), { anchor: "end", fill: C.ink, size: 12 });
      g.values.forEach((v, k) => {
        const yy = y + k * (bh + gap);
        s += `<g data-tip="${e(g.label + " — " + series[k] + ": " + (v == null ? "not tested" : fmt(v)) + (g.tips?.[k] ? " · " + g.tips[k] : ""))}">`;
        s += `<rect x="0" y="${yy - 1}" width="${W}" height="${bh + 2}" fill="transparent"/>`;
        if (v == null) s += T(x0 + 4, yy + bh - 1, "not tested", { size: 10.5, fill: C.muted });
        else s += `<path d="${hbarPath(x0, yy, sx(v) - x0, bh)}" fill="${C.pair[k]}"/>` + T(sx(v) + 6, yy + bh - 1, fmt(v), { size: 11, fill: C.ink });
        s += `</g>`;
      });
    });
    return s + `</svg>`;
  }

  // ---------------------------------------------------------------- chart: scatter F1 vs time (log x)
  function scatter(points) {
    const W = 820, H = 380, L = 56, R = 24, Tp = 36, B = 46;
    const ts = points.map((p) => p.time);
    const lo = Math.floor(Math.log10(Math.min(...ts) * 0.8)), hi = Math.ceil(Math.log10(Math.max(...ts) * 1.25));
    const sx = (t) => L + ((Math.log10(t) - lo) / ((hi - lo) || 1)) * (W - L - R);
    const sy = (f) => H - B - f * (H - B - Tp);
    let s = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" style="width:100%;max-width:${W}px;background:${C.surface}">`;
    Object.entries(C.approach).forEach(([k, col], i) => {
      const lx = L + i * 240;
      s += `<circle cx="${lx + 6}" cy="14" r="6" fill="${col}"/>` + T(lx + 18, 18.5, k, { fill: C.ink, size: 12 });
    });
    [0, 0.25, 0.5, 0.75, 1].forEach((f) => {
      s += `<line x1="${L}" y1="${sy(f)}" x2="${W - R}" y2="${sy(f)}" stroke="${f === 0 ? C.axis : C.grid}"/>` + T(L - 8, sy(f) + 4, f, { anchor: "end", size: 11, fill: C.muted });
    });
    for (let p = lo; p <= hi; p++) {
      const t = 10 ** p;
      s += `<line x1="${sx(t)}" y1="${Tp}" x2="${sx(t)}" y2="${H - B}" stroke="${C.grid}"/>` + T(sx(t), H - B + 16, t >= 1 ? t + " s" : t + " s", { anchor: "middle", size: 11, fill: C.muted });
    }
    s += T((L + W - R) / 2, H - 8, "Time per document (seconds, log scale) — left = faster", { anchor: "middle", size: 12, fill: C.ink2 });
    s += T(16, (Tp + H - B) / 2, "F1", { anchor: "middle", size: 12, fill: C.ink2, extra: ` transform="rotate(-90 16 ${(Tp + H - B) / 2})"` });
    // Pareto front: no other method is both faster and more accurate
    const front = points.filter((p) => !points.some((q) => q !== p && q.time <= p.time && q.f1 >= p.f1 && (q.time < p.time || q.f1 > p.f1)));
    points.forEach((p) => {
      s += `<g data-tip="${e(p.method)} — F1 ${f2(p.f1)}, ${sec(p.time)}/doc"><circle cx="${sx(p.time)}" cy="${sy(p.f1)}" r="12" fill="transparent"/>` +
        `<circle cx="${sx(p.time)}" cy="${sy(p.f1)}" r="5.5" fill="${C.approach[p.approach]}" stroke="#fff" stroke-width="2"/></g>`;
    });
    const placed = [];
    front.sort((a, b) => b.f1 - a.f1).forEach((p) => {
      const x = sx(p.time), right = x < W - 260, txt = clip(p.method, 46), w = txt.length * 6.2;
      const x0 = right ? x + 10 : x - 10 - w;
      let y = sy(p.f1) - 8;
      while (placed.some((b) => Math.abs(b.y - y) < 14 && x0 < b.x0 + b.w && b.x0 < x0 + w)) y += 14;
      placed.push({ x0, y, w });
      if (Math.abs(y - (sy(p.f1) - 8)) > 1) s += `<line x1="${x}" y1="${sy(p.f1)}" x2="${right ? x0 - 2 : x0 + w + 2}" y2="${y - 4}" stroke="${C.axis}"/>`;
      s += T(right ? x + 10 : x - 10, y, txt, { anchor: right ? "start" : "end", size: 11, fill: C.ink });
    });
    return s + `</svg>`;
  }

  // ---------------------------------------------------------------- chart: heatmap (sequential blue)
  function heatmap(rows, cols, get, { labelW = 330, cellW = 74, fmt = (v) => Math.round(v * 100), top = 70, rot = -30, maxc = 14, lo = "0", hi = "100 (%)" } = {}) {
    const cellH = 24;
    const W = labelW + cols.length * cellW + 70, H = top + rows.length * cellH + 46;
    const col = (v) => C.seq[Math.min(C.seq.length - 1, Math.floor(v * (C.seq.length - 0.001)))];
    let s = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" style="width:100%;max-width:${W}px;background:${C.surface}">`;
    cols.forEach((c, j) => {
      const x = labelW + j * cellW + cellW / 2;
      s += T(x - 4, top - 8, clip(c.label, maxc), { anchor: "start", size: 11, fill: C.ink, extra: ` transform="rotate(${rot} ${x - 4} ${top - 8})"` });
    });
    rows.forEach((r, i) => {
      const y = top + i * cellH;
      s += T(labelW - 10, y + 16, clip(r.label, 52), { anchor: "end", size: 12, fill: C.ink });
      cols.forEach((c, j) => {
        const v = get(r, c), x = labelW + j * cellW;
        if (v == null) { s += `<rect x="${x + 1}" y="${y + 1}" width="${cellW - 2}" height="${cellH - 2}" rx="3" fill="#f6f6f4"/>`; return; }
        const bg = col(v), dark = v >= 0.5;
        s += `<g data-tip="${e(r.label + " — " + c.label + ": " + fmt(v) + (c.unit || ""))}"><rect x="${x + 1}" y="${y + 1}" width="${cellW - 2}" height="${cellH - 2}" rx="3" fill="${bg}"/>` +
          T(x + cellW / 2, y + 16, fmt(v), { anchor: "middle", size: 11, fill: dark ? "#ffffff" : C.ink }) + `</g>`;
      });
    });
    // sequential legend
    const ly = H - 26, lw = 26;
    s += T(labelW, ly + 12, lo, { size: 11, fill: C.muted, anchor: "end", extra: ` dx="-6"` });
    C.seq.forEach((c, k) => (s += `<rect x="${labelW + k * lw}" y="${ly}" width="${lw - 2}" height="14" rx="2" fill="${c}"/>`));
    s += T(labelW + C.seq.length * lw + 4, ly + 12, hi, { size: 11, fill: C.muted });
    s += `<rect x="${labelW + C.seq.length * lw + 70}" y="${ly}" width="24" height="14" rx="2" fill="#f6f6f4"/>` + T(labelW + C.seq.length * lw + 100, ly + 12, "not tested / no such row", { size: 11, fill: C.muted });
    return s + `</svg>`;
  }

  // ---------------------------------------------------------------- tables
  function table(head, rows) {
    return `<div class="scroll"><table><tr>${head.map((h, i) => `<th${i ? ' class="num"' : ""}>${e(h)}</th>`).join("")}</tr>` +
      rows.map((r) => `<tr>${r.map((c, i) => `<td${i ? ' class="num"' : ""}>${c}</td>`).join("")}</tr>`).join("") + `</table></div>`;
  }
  const legendModels = (mks) => `<div class="legend">${mks.map((k) => `<span><i style="background:${C.model[k]}"></i>${e(MODEL_NAME[k])}</span>`).join("")}</div>`;

  // ---------------------------------------------------------------- card plumbing
  function card(id, title, sub, svg, tableHtml, note = "") {
    return `<div class="card chart-card" id="ch-${id}">
      <div class="chart-head"><div><h3>${e(title)}</h3>${sub ? `<div class="muted small">${sub}</div>` : ""}</div>
        <div class="chart-btns"><button class="small" data-tbl="${id}">Table</button><button class="small" data-png="${id}" data-name="${e(title)}">⬇ PNG</button></div></div>
      <div class="chart-svg">${svg}</div><div class="chart-tbl" hidden>${tableHtml}</div>${note ? `<p class="muted small">${note}</p>` : ""}</div>`;
  }
  const empty = (id, title, msg) => `<div class="card chart-card" id="ch-${id}"><h3>${e(title)}</h3><p class="muted">${e(msg)}</p></div>`;

  function exportPng(id, name) {
    const svg = document.querySelector(`#ch-${id} .chart-svg svg`);
    if (!svg) return;
    const w = +svg.getAttribute("width"), h = +svg.getAttribute("height"), scale = 2;
    const clone = svg.cloneNode(true);
    clone.removeAttribute("style");
    const xml = new XMLSerializer().serializeToString(clone);
    const img = new Image();
    img.onload = () => {
      const cv = document.createElement("canvas");
      cv.width = w * scale; cv.height = h * scale;
      const cx = cv.getContext("2d");
      cx.fillStyle = "#fff"; cx.fillRect(0, 0, cv.width, cv.height);
      cx.drawImage(img, 0, 0, cv.width, cv.height);
      const a = document.createElement("a");
      a.href = cv.toDataURL("image/png");
      a.download = "FinAI-C_" + name.replace(/[^\w]+/g, "_").replace(/^_|_$/g, "") + ".png";
      a.click();
    };
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(xml);
  }

  // ---------------------------------------------------------------- model tables: each model alone, and all models × a chosen dimension
  const M = { dim: "method", val: "f1", shot: "zero", pipe: "best" };
  const PIPE_ORDER = Object.keys(PIPE);
  const MODEL_ORDER = ["gemma", "qwen", "bonsai", "embed", "rules", "other"];
  const VALUES = {
    f1: { label: "F1", get: (a) => mean(vals(a, "f1")), fmt: f2, scale: "unit" },
    acc: { label: "Accuracy (exact values)", get: (a) => mean(vals(a, "acc")), fmt: (v) => pc(v), scale: "unit" },
    prec: { label: "Precision", get: (a) => mean(vals(a, "prec")), fmt: (v) => pc(v), scale: "unit" },
    hall: { label: "Hallucinations (lower is better)", get: (a) => mean(vals(a, "hall")), fmt: (v) => pc(v), scale: "unit" },
    ind: { label: "Indicator error (lower is better)", get: (a) => mean(vals(a, "ind")), fmt: (v) => pc(v, 1), scale: "unit" },
    time: { label: "Time per document (lower is better)", get: (a) => mean(vals(a, "time").filter((t) => t > 0)), fmt: sec, scale: "max" },
    tps: { label: "Tokens per second", get: (a) => mean(vals(a, "tps").filter((t) => t > 0)), fmt: (v) => v.toFixed(1), scale: "max" },
  };
  const DIMS = { method: "Method (pipeline)", document: "Document", field: "Field (item extracted)", prompt: "Prompt (zero-/one-shot)", device: "Device (laptop / phone)" };

  const rowKey = (r, dim) => r.mk + (r.phone && dim !== "device" ? "|phone" : "");
  const rowLabel = (k) => { const [mk, ph] = k.split("|"); return (mk === "rules" ? "No model (rules)" : MODEL_NAME[mk]) + (ph ? " — phone" : ""); };
  const rowSort = (a, b) => (MODEL_ORDER.indexOf(a.split("|")[0]) - MODEL_ORDER.indexOf(b.split("|")[0])) || a.localeCompare(b);
  const shotOf = (r) => r.shot || "n/a";

  function fieldExact(runs, f) {
    let ok = 0, tot = 0;
    runs.forEach((r) => { const s = r.perField[f]; if (s && s !== "correct_null" && s !== "hallucinated") { tot++; ok += s === "correct"; } });
    return tot ? ok / tot : null;
  }

  function cellBg(v, scale, max) {
    if (v == null) return "";
    const t = scale === "unit" ? Math.max(0, Math.min(1, v)) : (max ? v / max : 0);
    const c = C.seq[Math.min(C.seq.length - 1, Math.floor(t * (C.seq.length - 0.001)))];
    return ` style="background:${c};color:${t >= 0.5 ? "#fff" : C.ink}"`;
  }

  function modelMatrix() {
    const dim = M.dim, isField = dim === "field";
    const V = isField ? { label: "Exact extraction (% of runs)", fmt: (v) => pc(v), scale: "unit" } : VALUES[M.val];
    let rs = filtered({ ignoreDocs: dim === "document", ignoreDevice: dim === "device" })
      .filter((r) => dim === "prompt" || M.shot === "both" || (M.shot === "one" ? r.shot === "one-shot" || r.shot === "" : r.shot !== "one-shot"));
    let cols;
    if (dim === "method") cols = PIPE_ORDER.filter((p) => rs.some((r) => r.pipe === p)).map((p) => ({ id: p, label: PIPE[p], test: (r) => r.pipe === p }));
    else if (dim === "document") cols = [...new Set(rs.map((r) => r.doc))].sort((a, b) => (DOCMAP[a].long - DOCMAP[b].long) || a - b)
      .map((id) => ({ id, label: `${DOCMAP[id].label} (${DOCMAP[id].pages} p.)`, test: (r) => r.doc === id }));
    else if (dim === "prompt") cols = ["zero-shot", "one-shot", "n/a"].filter((s) => rs.some((r) => shotOf(r) === s))
      .map((s) => ({ id: s, label: s === "n/a" ? "no prompt (rules / embeddings)" : s, test: (r) => shotOf(r) === s }));
    else if (dim === "device") cols = [["laptop", "Laptop (CPU)"], ["phone", "Phone (Samsung S25, GPU)"]].filter(([d]) => rs.some((r) => r.phone === (d === "phone")))
      .map(([d, l]) => ({ id: d, label: l, test: (r) => r.phone === (d === "phone") }));
    else cols = Object.keys((typeof META !== "undefined" && META && META.numeric_fields) || {}).map((f) => ({ id: f, label: f.replace(/_/g, " "), field: f }));

    // which method of each model goes into the row (when the columns are not the method itself)
    const bestPipe = {};
    if (dim !== "method") {
      const g = {};
      rs.forEach((r) => { const k = rowKey(r, dim); ((g[k] = g[k] || {})[r.pipe] = g[k][r.pipe] || []).push(r); });
      Object.entries(g).forEach(([k, ps]) => { bestPipe[k] = Object.entries(ps).sort((a, b) => mean(vals(b[1], "f1")) - mean(vals(a[1], "f1")))[0][0]; });
      const keep = (r) => M.pipe === "all" || (M.pipe === "best" ? r.pipe === bestPipe[rowKey(r, dim)] : r.pipe === M.pipe);
      rs = rs.filter(keep);
    }
    const rows = [...new Set(rs.map((r) => rowKey(r, dim)))].sort(rowSort);
    const rowName = (rk) => rowLabel(rk) + (dim !== "method" && M.pipe === "best" && bestPipe[rk] ? ` · ${PIPE[bestPipe[rk]]}` : "");
    const cell = (rk, c) => {
      const a = rs.filter((r) => rowKey(r, dim) === rk && (c.field ? true : c.test(r)));
      if (!a.length) return { v: null, n: 0 };
      return { v: c.field ? fieldExact(a, c.field) : V.get(a), n: a.length };
    };
    const grid = rows.map((rk) => ({ rk, cells: cols.map((c) => cell(rk, c)), all: isField ? null : (() => { const a = rs.filter((r) => rowKey(r, dim) === rk); return a.length ? V.get(a) : null; })() }));
    const max = Math.max(0, ...grid.flatMap((g) => g.cells.map((c) => c.v || 0)), ...grid.map((g) => g.all || 0));
    // best per column (higher is better except hallucinations, indicator error, time)
    const lowerBetter = !isField && ["hall", "ind", "time"].includes(M.val);
    const best = cols.map((_, j) => { const vs = grid.map((g) => g.cells[j].v).filter((v) => v != null); return vs.length > 1 ? (lowerBetter ? Math.min(...vs) : Math.max(...vs)) : null; });

    const opt = (o, cur) => Object.entries(o).map(([k, l]) => `<option value="${k}"${k === cur ? " selected" : ""}>${e(typeof l === "string" ? l : l.label)}</option>`).join("");
    const head = `<tr><th>Model</th>${cols.map((c) => `<th class="num">${e(c.label)}</th>`).join("")}${isField ? "" : `<th class="num">All together</th>`}</tr>`;
    const body = grid.map((g) => `<tr><td><span class="dot" style="background:${C.model[g.rk.split("|")[0]]}"></span>${e(rowName(g.rk))}</td>` +
      g.cells.map((c, j) => c.v == null ? `<td class="num empty-cell">—</td>` :
        `<td class="num"${cellBg(c.v, V.scale, max)} title="${c.n} run${c.n === 1 ? "" : "s"}">${c.v === best[j] ? "<b>" + V.fmt(c.v) + "</b>" : V.fmt(c.v)}</td>`).join("") +
      (isField ? "" : `<td class="num all-col">${g.all == null ? "—" : V.fmt(g.all)}</td>`) + `</tr>`).join("");
    return `<div class="card chart-card" id="ch-matrix">
      <div class="chart-head"><div><h3>All models together — models × ${e(DIMS[dim].toLowerCase())}</h3>
        <div class="muted small">Rows: every model. Columns: what varies. Darker = higher value; bold = best in the column. Hover a cell for the number of runs.</div></div>
        <div class="chart-btns"><button class="small" data-csv="ch-matrix" data-name="models_x_${dim}">⬇ CSV</button></div></div>
      <div class="row mx-controls">
        <label>Columns (what varies)<select id="mx-dim">${opt(DIMS, dim)}</select></label>
        <label>Value in the cells<select id="mx-val"${isField ? " disabled" : ""}>${isField ? `<option>Exact extraction (%)</option>` : opt(VALUES, M.val)}</select></label>
        <label>Method used for each model<select id="mx-pipe"${dim === "method" ? " disabled" : ""}>
          <option value="best"${M.pipe === "best" ? " selected" : ""}>Its best method (by F1)</option>
          <option value="all"${M.pipe === "all" ? " selected" : ""}>All its methods, averaged</option>
          ${PIPE_ORDER.filter((p) => RUNS.some((r) => r.pipe === p)).map((p) => `<option value="${p}"${M.pipe === p ? " selected" : ""}>${e(PIPE[p])}</option>`).join("")}</select></label>
        <label>Prompt<select id="mx-shot"${dim === "prompt" ? " disabled" : ""}><option value="zero"${M.shot === "zero" ? " selected" : ""}>Zero-shot only (main comparison)</option>
          <option value="one"${M.shot === "one" ? " selected" : ""}>One-shot only</option><option value="both"${M.shot === "both" ? " selected" : ""}>Both, averaged</option></select></label>
      </div>
      ${rows.length ? `<div class="scroll"><table class="matrix">${head}${body}</table></div>` : `<p class="muted">No runs for this selection.</p>`}
      <p class="muted small">Values: ${e(V.label)}. Documents and device follow the filters at the top${dim === "document" ? " (the document filter is ignored here, all documents are columns)" : ""}${dim === "device" ? " (the device filter is ignored here)" : ""}. Phone runs are a separate row unless the columns are “Device”.${dim !== "method" ? (M.pipe === "best" ? " Each row uses the model's best method, named after the model." : M.pipe === "all" ? " Each row averages all methods of the model (including weak ones such as VLM)." : "") : ""}</p></div>`;
  }

  function perModelTables(rs) {
    const byModel = {};
    rs.forEach((r) => (byModel[rowKey(r, "x")] = byModel[rowKey(r, "x")] || []).push(r));
    return Object.keys(byModel).sort(rowSort).map((rk, i) => {
      const a = aggregate(byModel[rk]).sort((x, y) => (PIPE_ORDER.indexOf(x.pipe) - PIPE_ORDER.indexOf(y.pipe)) || (y.f1 ?? 0) - (x.f1 ?? 0));
      const variant = (m) => [PIPE[m.pipe] || m.pipe, m.shot === "one-shot" ? "one-shot" : m.shot === "zero-shot" ? "zero-shot" : ""].filter(Boolean).join(" · ");
      const bestF1 = Math.max(...a.map((m) => m.f1 ?? -1));
      const id = "ch-model-" + i;
      return `<div class="card chart-card" id="${id}">
        <div class="chart-head"><div><h3><span class="dot big" style="background:${C.model[rk.split("|")[0]]}"></span>${e(rowLabel(rk))}</h3>
          <div class="muted small">Every way this model was tested (filters at the top apply). Bold = its best configuration.</div></div>
          <div class="chart-btns"><button class="small" data-csv="${id}" data-name="${e(rowLabel(rk))}">⬇ CSV</button></div></div>
        ${table(["Configuration", "Runs", "Docs", "F1", "± std", "Accuracy", "Precision", "Hallucinations", "Indicator error", "Valid JSON", "Time / doc", "Tokens / s"],
          a.map((m) => [e(variant(m)), m.n + (m.nErr ? ` <span class="badge bad">${m.nErr} failed</span>` : ""), m.nDocs,
            m.f1 === bestF1 ? `<b>${f2(m.f1)}</b>` : f2(m.f1), f2(m.f1sd), pc(m.acc), pc(m.prec), pc(m.hall), pc(m.ind, 1),
            m.json == null ? "—" : pc(m.json), sec(m.time), m.tps ? m.tps.toFixed(1) : "—"]))}</div>`;
    }).join("");
  }

  function exportCsv(cardId, name) {
    const t = document.querySelector(`#${cardId} table`);
    if (!t) return;
    const csv = [...t.rows].map((tr) => [...tr.cells].map((td) => `"${td.textContent.trim().replace(/"/g, '""')}"`).join(",")).join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
    a.download = "FinAI-C_" + String(name).replace(/[^\w]+/g, "_").replace(/^_|_$/g, "") + ".csv";
    a.click();
  }

  // ---------------------------------------------------------------- render
  function render() {
    const out = [];
    const rs = filtered(), agg = aggregate(rs);
    const scope = F.docs === "short" ? "standard ANAF statements (2–3 pages)" : F.docs === "long" ? "new formats and long documents (11–23 pages)"
      : F.docs === "all" ? "all documents" : DOCMAP[F.docs]?.label;
    const n = (a) => `${a.n} run${a.n === 1 ? "" : "s"}, ${a.nDocs} doc${a.nDocs === 1 ? "" : "s"}${a.nErr ? `, ${a.nErr} failed` : ""}`;

    if (!agg.length) {
      $("#charts-body").innerHTML = `<div class="card"><p class="muted">No scored runs for this selection yet.</p></div>`;
      return;
    }

    // 0. model tables: all together, then each model alone
    out.push(`<h2 class="section-title">Models — tables</h2>`, modelMatrix(),
      `<h3 class="section-sub">Each model on its own</h3>`, perModelTables(rs), `<h2 class="section-title">Charts</h2>`);

    // 1. ranking
    out.push(card("rank", "Which method extracts best? — F1 per method", `Mean F1 over ${e(scope)}. Colour = model.`,
      hbars(agg.map((a) => ({ label: a.method, value: a.f1, color: C.model[a.mk], tip: `${a.method} — F1 ${f2(a.f1)} ± ${f2(a.f1sd)} (${n(a)})` }))) +
      legendModels([...new Set(agg.map((a) => a.mk))]),
      table(["Method", "F1", "± std", "Accuracy", "Precision", "Runs", "Documents"], agg.map((a) => [e(a.method), f2(a.f1), f2(a.f1sd), pc(a.acc), pc(a.prec), a.n, a.nDocs])),
      "F1 combines precision (are the returned numbers right?) and recall (were the existing numbers found?). 1 = perfect."));

    // 2. accuracy vs speed
    const pts = agg.filter((a) => a.time > 0 && a.f1 != null).map((a) => ({ method: a.method, f1: a.f1, time: a.time, approach: a.approach }));
    out.push(pts.length ? card("speed", "Accuracy vs. speed", `Each point is one method (${e(scope)}). Labelled points are the best trade-offs: no other method is both faster and more accurate.`,
      scatter(pts), table(["Method", "Approach", "F1", "Time / document", "Tokens / s"], agg.map((a) => [e(a.method), e(a.approach), f2(a.f1), sec(a.time), a.tps ? a.tps.toFixed(1) : "—"])),
      "Phone runs have no measured time, so they do not appear here.") : empty("speed", "Accuracy vs. speed", "No timed runs in this selection."));

    // 3. hallucinations
    const hall = [...agg].filter((a) => a.hall != null).sort((a, b) => a.hall - b.hall);
    out.push(card("hall", "Hallucinations — values invented for items that do not exist", `Share of empty items for which the method returned a number (${e(scope)}). Lower is better.`,
      hbars(hall.map((a) => ({ label: a.method, value: a.hall, color: C.model[a.mk], tip: `${a.method} — ${pc(a.hall)} (${n(a)})` })), { fmt: (v) => pc(v), tickFmt: (t) => pc(t) }) +
      legendModels([...new Set(hall.map((a) => a.mk))]),
      table(["Method", "Hallucination rate", "Indicator error"], hall.map((a) => [e(a.method), pc(a.hall), pc(a.ind, 1)]))));

    // 4. short vs long documents
    const all = aggregate(filtered({ ignoreDocs: true }).filter((r) => !r.phone || F.device !== "laptop"));
    const byGroup = (method, long) => { const a = filtered({ ignoreDocs: true }).filter((r) => r.method === method && r.long === long); return a.length ? mean(vals(a, "f1")) : null; };
    const both = all.map((a) => ({ label: a.method, values: [byGroup(a.method, false), byGroup(a.method, true)] })).filter((g) => g.values[1] != null);
    out.push(both.length ? card("length", "Standard vs. new formats and long documents", "Same method, two kinds of documents. A drop shows how much the method depends on the ANAF layout and on short inputs.",
      hbars2(both, ["ANAF statements (2–3 pages)", "New formats (11–23 pages)"]),
      table(["Method", "F1 ANAF", "F1 new formats", "Change"], both.map((g) => [e(g.label), f2(g.values[0]), f2(g.values[1]), g.values[0] == null ? "—" : (g.values[1] - g.values[0] >= 0 ? "+" : "") + f2(g.values[1] - g.values[0])]))) :
      empty("length", "Standard vs. new formats and long documents", "No runs on the long documents yet."));

    // 5. laptop vs phone
    const phoneRuns = RUNS.filter((r) => r.phone);
    if (phoneRuns.length) {
      const phoneDocs = new Set(phoneRuns.map((r) => r.doc));
      const pipes = [...new Set(phoneRuns.map((r) => r.pipe))];
      const gl = pipes.map((p) => {
        const lap = RUNS.filter((r) => !r.phone && r.mk === "gemma" && r.pipe === p && r.shot !== "one-shot" && phoneDocs.has(r.doc));
        const ph = phoneRuns.filter((r) => r.pipe === p);
        return { label: MODEL_NAME.gemma + " · " + (PIPE[p] || p), values: [lap.length ? mean(vals(lap, "f1")) : null, mean(vals(ph, "f1"))],
          tips: [`${lap.length} runs`, `${ph.length} runs`] };
      });
      out.push(card("device", "Laptop vs. phone — the same model (Gemma 3n E2B, zero-shot)", "Laptop: ASUS Zenbook, Ryzen 5 5600H, CPU only. Phone: Samsung S25, GPU (Google AI Edge Gallery). Same documents.",
        hbars2(gl, ["Laptop", "Phone"]), table(["Method", "F1 laptop", "F1 phone"], gl.map((g) => [e(g.label), f2(g.values[0]), f2(g.values[1])]))));
    }

    // 6. zero-shot vs one-shot
    const shotGroups = {};
    RUNS.filter((r) => !r.phone && r.shot && (F.docs === "all" || (F.docs === "short" ? !r.long : F.docs === "long" ? r.long : String(r.doc) === F.docs))).forEach((r) => {
      const k = `${MODEL_NAME[r.mk]} · ${PIPE[r.pipe] || r.pipe}`;
      ((shotGroups[k] = shotGroups[k] || { zero: [], one: [] })[r.shot === "one-shot" ? "one" : "zero"]).push(r);
    });
    const sg = Object.entries(shotGroups).filter(([, v]) => v.one.length && v.zero.length)
      .map(([k, v]) => ({ label: k, values: [mean(vals(v.zero, "f1")), mean(vals(v.one, "f1"))] }));
    if (sg.length) out.push(card("shot", "Zero-shot vs. one-shot prompt", "One-shot = the prompt contains one worked example. Same documents, same model.",
      hbars2(sg, ["Zero-shot", "One-shot"]), table(["Method", "F1 zero-shot", "F1 one-shot", "Change"], sg.map((g) => [e(g.label), f2(g.values[0]), f2(g.values[1]), (g.values[1] - g.values[0] >= 0 ? "+" : "") + f2(g.values[1] - g.values[0])]))));

    // 7. method × document heatmap
    const hmRuns = filtered({ ignoreDocs: true }), hmAgg = aggregate(hmRuns);
    const docsUsed = [...new Set(hmRuns.map((r) => r.doc))].sort((a, b) => (DOCMAP[a].long - DOCMAP[b].long) || a - b).map((id) => ({ id, label: DOCMAP[id].label }));
    const cellF1 = (row, c) => { const a = row.runs.filter((r) => r.doc === c.id); return a.length ? mean(vals(a, "f1")) : null; };
    out.push(card("docs", "F1 per method and document", "Every document, every method (device filter applies). Grey = not tested on that document.",
      heatmap(hmAgg.map((a) => ({ label: a.method, runs: a.runs })), docsUsed, cellF1, { fmt: (v) => v.toFixed(2), lo: "F1 0", hi: "1" }),
      table(["Method", ...docsUsed.map((d) => d.label)], hmAgg.map((a) => [e(a.method), ...docsUsed.map((d) => { const v = cellF1(a, d); return v == null ? "—" : f2(v); })]))));

    // 8. per-field accuracy
    const fields = Object.keys((typeof META !== "undefined" && META && META.numeric_fields) || {});
    if (fields.length) {
      const fieldAcc = (row, c) => {
        let ok = 0, tot = 0;
        row.runs.forEach((r) => { const s = r.perField[c.id]; if (s && s !== "correct_null" && s !== "hallucinated") { tot++; ok += s === "correct"; } });
        return tot ? ok / tot : null;
      };
      const fcols = fields.map((k) => ({ id: k, label: k.replace(/_/g, " "), unit: "% exact" }));
      out.push(card("fields", "Which items are hard? — exact extraction per field", `% of runs in which the item was extracted exactly (${e(scope)}). Grey = the item does not exist in these documents.`,
        heatmap(agg.map((a) => ({ label: a.method, runs: a.runs })), fcols, fieldAcc, { cellW: 58, top: 110, rot: -45, maxc: 22 }),
        table(["Method", ...fcols.map((c) => c.label)], agg.map((a) => [e(a.method), ...fcols.map((c) => { const v = fieldAcc(a, c); return v == null ? "—" : pc(v); })]))));
    }

    // 9. reproducibility
    const rep = aggregate(filtered()).map((a) => {
      const byDoc = {};
      a.runs.forEach((r) => (byDoc[r.doc] = byDoc[r.doc] || []).push(r));
      const multi = Object.values(byDoc).filter((x) => x.length > 1);
      const f1sd = multi.length ? mean(multi.map((x) => sd(vals(x, "f1")))) : null;
      const same = multi.length ? multi.filter((x) => sd(vals(x, "f1")) < 1e-9).length / multi.length : null;
      const tcv = multi.length ? mean(multi.map((x) => { const t = vals(x, "time").filter((v) => v > 0); return t.length > 1 ? sd(t) / mean(t) : null; }).filter((v) => v != null)) : null;
      return { a, multi: multi.length, maxRep: Math.max(...Object.values(byDoc).map((x) => x.length)), f1sd, same, tcv };
    });
    out.push(`<div class="card chart-card"><h3>Reproducibility — the same test repeated</h3>
      <div class="muted small">For each method and document with more than one run: how much F1 and time change between repetitions (${e(scope)}).</div>
      ${table(["Method", "Documents repeated", "Runs per document", "F1 (mean)", "F1 std between repetitions", "Identical F1 in all repetitions", "Time variation (CV)"],
        rep.map((x) => [e(x.a.method), x.multi || "—", x.maxRep, f2(x.a.f1), x.f1sd == null ? "—" : x.f1sd.toFixed(3), x.same == null ? "—" : pc(x.same), x.tcv == null ? "—" : "±" + pc(x.tcv, 1)]))}
      <p class="muted small">Models run with temperature 0, so the answers are expected to repeat; time varies with laptop load and temperature.</p></div>`);

    // 10. full summary table
    out.push(`<div class="card chart-card" id="ch-summary"><div class="chart-head"><div><h3>Summary table (${e(scope)})</h3>
      <div class="muted small">All metrics per method. Use “Table” on any chart for the data behind it.</div></div></div>
      ${table(["Method", "Approach", "Runs", "Docs", "F1", "Accuracy", "Precision", "Hallucinations", "Indicator error", "Valid JSON", "Time / doc", "Tokens / s"],
        agg.map((a) => [e(a.method), e(a.approach), a.n + (a.nErr ? ` <span class="badge bad">${a.nErr} failed</span>` : ""), a.nDocs, `<b>${f2(a.f1)}</b>`, pc(a.acc), pc(a.prec), pc(a.hall), pc(a.ind, 1),
          a.json == null ? "—" : pc(a.json), sec(a.time), a.tps ? a.tps.toFixed(1) : "—"]))}</div>`);

    $("#charts-body").innerHTML = out.join("");
  }

  // ---------------------------------------------------------------- tooltip + buttons
  const tip = document.createElement("div");
  tip.id = "chart-tip";
  document.body.appendChild(tip);
  document.addEventListener("mousemove", (ev) => {
    const g = ev.target.closest && ev.target.closest("#v-charts [data-tip]");
    if (!g) { tip.style.display = "none"; return; }
    tip.textContent = g.getAttribute("data-tip");
    tip.style.display = "block";
    const x = Math.min(ev.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
    tip.style.left = x + "px"; tip.style.top = ev.clientY + 14 + "px";
  });
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest && ev.target.closest("#v-charts button[data-tbl], #v-charts button[data-png], #v-charts button[data-csv]");
    if (!b) return;
    if (b.dataset.csv) return exportCsv(b.dataset.csv, b.dataset.name);
    if (b.dataset.png) return exportPng(b.dataset.png, b.dataset.name);
    const cardEl = document.getElementById("ch-" + b.dataset.tbl), t = cardEl.querySelector(".chart-tbl");
    t.hidden = !t.hidden;
    b.textContent = t.hidden ? "Table" : "Hide table";
  });

  // ---------------------------------------------------------------- loader
  async function load() {
    const [runs, docs] = await Promise.all([api("/api/runs"), api("/api/documents")]);
    prepare(runs, docs);
    const sel = $("#ch-docs"), cur = F.docs;
    sel.innerHTML = `<option value="short">ANAF statements, 2–3 pages (all methods tested)</option>
      <option value="long">New formats and long documents (11–23 pages)</option><option value="all">All documents</option>` +
      docs.filter((d) => d.has_gt).map((d) => `<option value="${d.id}">#${d.id} ${e(DOCMAP[d.id].label)} — ${e(d.filename)} (${d.pages} p.)</option>`).join("");
    sel.value = cur;
    $("#ch-count").textContent = `${RUNS.length} scored runs · ${Object.values(DOCMAP).filter((d) => d.has_gt).length} documents with correct values`;
    render();
  }
  $("#ch-docs").onchange = (ev) => { F.docs = ev.target.value; render(); };
  $("#ch-device").onchange = (ev) => { F.device = ev.target.value; render(); };
  $("#ch-refresh").onclick = load;
  document.addEventListener("change", (ev) => {
    const id = ev.target && ev.target.id;
    if (id === "mx-dim") M.dim = ev.target.value; else if (id === "mx-pipe") M.pipe = ev.target.value; else if (id === "mx-val") M.val = ev.target.value; else if (id === "mx-shot") M.shot = ev.target.value; else return;
    render();
    document.getElementById("ch-matrix")?.scrollIntoView({ block: "nearest" });
  });
  TITLES.charts = "Charts & tables";
  LOADERS.charts = load;
})();
