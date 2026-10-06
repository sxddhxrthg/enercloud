// ENERCloud dashboard - plain JavaScript, no framework.
const REFRESH_MS = 5000;
const $ = (id) => document.getElementById(id);
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const SVG_NS = "http://www.w3.org/2000/svg";

// Dashboard routes (GET /dashboard, POST /export) do not need the API key.
// The key is required only on POST /readings (sensors).
const config = { url: localStorage.getItem("enercloud_api_url") || "" };
const isMock = () => !config.url;

// ------------------------------------------------------------- data access (unchanged behaviour)
async function loadDashboard() {
  if (isMock()) return { data: buildMockDashboard(), ms: null };
  const start = performance.now();
  const res = await fetch(`${config.url.replace(/\/$/, "")}/dashboard`);
  const ms = Math.round(performance.now() - start);
  if (!res.ok) throw new Error(`GET /dashboard returned HTTP ${res.status}. Check the API URL.`);
  return { data: await res.json(), ms };
}

async function exportReport() {
  const msg = $("export-msg");
  const btn = $("export-btn");
  const label = btn.querySelector("span");
  msg.className = "export__msg";
  if (isMock()) { msg.textContent = "Export needs a live API connection."; return; }
  btn.disabled = true;
  label.textContent = "Exporting…";
  msg.textContent = "";
  try {
    const res = await fetch(`${config.url.replace(/\/$/, "")}/export`, {
      method: "POST",
    });
    const body = await res.json();
    if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
    msg.className = "export__msg is-success";
    msg.replaceChildren(
      el("strong", "✓ Export complete"),
      el("span", `${body.records} records, JSON + CSV`),
      el("code", `s3://${body.bucket}/${body.json_key}`),
    );
  } catch (err) {
    msg.className = "export__msg is-error";
    msg.textContent = `Export failed: ${err.message}`;
  } finally {
    btn.disabled = false;
    label.textContent = "Export to S3";
  }
}

// ------------------------------------------------------------- display names
// Presentation only: building_id values from the API are never changed.
const BUILDING_NAMES = {
  "ACAD-A":   { name: "MAIN BLOCK",          subtitle: "Main Block, Academic Campus" },
  "LAB-1":    { name: "TECH PARK",           subtitle: "Tech Park, Engineering & Computing" },
  "LIB":      { name: "PG BLOCK",            subtitle: "PG Block, Postgraduate Studies" },
  "HOSTEL-A": { name: "N BLOCK",             subtitle: "N Block, Student Residence" },
  "ADMIN":    { name: "UNIVERSITY BUILDING", subtitle: "University Building, Administration" },
};
const displayName = (id) => (BUILDING_NAMES[id] ? BUILDING_NAMES[id].name : id);
const displaySubtitle = (id, fallback) => (BUILDING_NAMES[id] ? BUILDING_NAMES[id].subtitle : fallback);

// ------------------------------------------------------------- helpers
// Values are inserted with textContent (never innerHTML), so data from the
// database cannot inject HTML or script into the page.
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (className) node.className = className;
  return node;
}
const fmtTime = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour12: false }) : "–");
const fmtKw = (n) => (typeof n === "number" ? n.toFixed(2) : "–");
const fmtNum = (n, d = 1) => (typeof n === "number" ? n.toFixed(d) : "–");

function tween(node, to, decimals = 2) {
  if (typeof to !== "number") { node.textContent = "–"; delete node.dataset.v; return; }
  const from = node.dataset.v === undefined ? to : parseFloat(node.dataset.v);
  node.dataset.v = to;
  if (reducedMotion || from === to) { node.textContent = to.toFixed(decimals); return; }
  const start = performance.now();
  const step = (now) => {
    if (parseFloat(node.dataset.v) !== to) return; // a newer value took over
    const t = Math.min(1, (now - start) / 600);
    node.textContent = (from + (to - from) * (1 - Math.pow(1 - t, 3))).toFixed(decimals);
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function parseReason(reason) {
  const i = reason.indexOf(": ");
  if (i === -1) return { rule: "", detail: reason };
  const rule = reason.slice(0, i);
  return { rule: rule.charAt(0) + rule.slice(1).toLowerCase(), detail: reason.slice(i + 2) };
}

function statusTag(status) {
  const known = status === "NORMAL" || status === "ANOMALY";
  return el("span", known ? status.toLowerCase() : "no data", `status status--${known ? status : "NODATA"}`);
}

const icon = (path) => {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 20 20");
  svg.setAttribute("aria-hidden", "true");
  const p = document.createElementNS(SVG_NS, "path");
  p.setAttribute("d", path);
  svg.append(p);
  return svg;
};
const ICON_WARN = "M10 2 1 18h18L10 2zm-1 6h2v5H9V8zm0 6h2v2H9v-2z";
const ICON_CHECK = "M4 10.5 8 14.5 16 5.5";

// Sparkline: values drawn into an SVG with a fixed viewBox. Optional dashed limit line.
function sparkline(svg, values, { color, limit } = {}) {
  const [, , W, H] = svg.getAttribute("viewBox").split(" ").map(Number);
  svg.replaceChildren();
  if (values.length < 2) {
    const t = document.createElementNS(SVG_NS, "text");
    t.setAttribute("x", 0); t.setAttribute("y", H - 4); t.setAttribute("class", "empty");
    t.textContent = "collecting readings…";
    svg.append(t);
    return;
  }
  const top = Math.max(...values, limit || 0) * 1.12 || 1;
  const x = (i) => (i / (values.length - 1)) * W;
  const y = (v) => H - (v / top) * (H - 2) - 1;
  const line = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const fill = document.createElementNS(SVG_NS, "path");
  fill.setAttribute("d", `${line}L${W},${H}L0,${H}Z`);
  fill.setAttribute("class", "fill");
  fill.setAttribute("fill", color);
  fill.setAttribute("fill-opacity", "0.12");
  const stroke = document.createElementNS(SVG_NS, "path");
  stroke.setAttribute("d", line);
  stroke.setAttribute("class", "line");
  stroke.setAttribute("stroke", color);
  svg.append(fill, stroke);
  if (limit) {
    const l = document.createElementNS(SVG_NS, "line");
    l.setAttribute("x1", 0); l.setAttribute("x2", W);
    l.setAttribute("y1", y(limit)); l.setAttribute("y2", y(limit));
    l.setAttribute("class", "limit");
    svg.append(l);
  }
}

// ------------------------------------------------------------- session history
// Built only from readings the API actually returned while this page is open.
const history = { source: null, campus: [], buildings: new Map() };
const telemetry = { refreshes: 0, errors: 0 };

function recordHistory(data) {
  if (history.source !== config.url) {
    history.source = config.url;
    history.campus = [];
    history.buildings.clear();
  }
  const last = history.campus[history.campus.length - 1];
  if (!last || last.t !== data.generated_at) {
    history.campus.push({ t: data.generated_at, kw: data.summary.total_power_kw });
    if (history.campus.length > 40) history.campus.shift();
  }
  const readings = [...data.recent_readings, ...data.buildings.map((b) => b.latest).filter(Boolean)];
  readings.forEach((r) => {
    if (!history.buildings.has(r.building_id)) history.buildings.set(r.building_id, new Map());
    history.buildings.get(r.building_id).set(r.ts, r.power_kw);
  });
  history.buildings.forEach((series, id) => {
    const sorted = [...series.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1)).slice(-24);
    history.buildings.set(id, new Map(sorted));
  });
}

// ------------------------------------------------------------- rendering
function renderTopbar(ms, generatedAt) {
  const m = config.url.match(/execute-api\.([a-z0-9-]+)\.amazonaws\.com/);
  $("env-chip").textContent = isMock() ? "Local mock" : m ? `AWS ${m[1]}` : "Custom API";
  $("stat-latency").textContent = ms === null ? "n/a" : `${ms} ms`;
  $("stat-updated").textContent = fmtTime(generatedAt);
}

function renderLoad(data) {
  const total = data.summary.total_power_kw;
  tween($("total-kw"), total);
  sparkline($("campus-spark"), history.campus.map((p) => p.kw), { color: "#ffb000" });

  const delta = $("load-delta");
  const pts = history.campus;
  if (pts.length >= 2 && pts[pts.length - 2].kw > 0) {
    const pct = ((pts[pts.length - 1].kw / pts[pts.length - 2].kw) - 1) * 100;
    delta.className = "delta " + (pct > 0.05 ? "is-up" : pct < -0.05 ? "is-down" : "");
    delta.textContent = `${Math.abs(pct).toFixed(1)}% vs previous refresh`;
  } else {
    delta.className = "delta";
    delta.textContent = "collecting trend…";
  }

  const mix = $("mix");
  const legend = $("mix-legend");
  const live = data.buildings.filter((b) => b.latest && b.latest.power_kw > 0);
  while (mix.children.length > live.length) mix.lastChild.remove();
  while (mix.children.length < live.length) mix.append(el("span"));
  legend.replaceChildren();
  live.forEach((b, i) => {
    const anomaly = b.latest.status === "ANOMALY";
    const seg = mix.children[i];
    seg.style.flexGrow = b.latest.power_kw;
    seg.className = anomaly ? "is-anomaly" : "";
    seg.title = `${displayName(b.building_id)}: ${fmtKw(b.latest.power_kw)} kW`;
    const li = el("li", displayName(b.building_id), anomaly ? "is-anomaly" : "");
    li.append(el("b", total ? `${Math.round((b.latest.power_kw / total) * 100)}%` : "–"));
    legend.append(li);
  });
}

function renderTiles(s) {
  $("stat-buildings").textContent = s.total_buildings;
  $("stat-sensors").textContent = s.active_sensors;
  $("stat-readings").textContent = s.readings_count;
  $("stat-anomalies").textContent = s.anomaly_count;
  $("anomaly-stat").classList.toggle("has-alerts", s.anomaly_count > 0);
}

const seenAlerts = new Set();
function renderAlerts(buildings) {
  const box = $("alerts");
  const active = buildings.filter((b) => b.latest && b.latest.status === "ANOMALY");
  const count = $("alert-count");
  count.textContent = active.length;
  count.classList.toggle("is-hot", active.length > 0);
  box.replaceChildren();
  if (!active.length) {
    const ok = el("p", `All ${buildings.length} buildings within normal range`, "all-clear");
    const check = icon(ICON_CHECK);
    ok.prepend(check);
    box.append(ok);
    return;
  }
  active.forEach((b) => {
    const r = b.latest;
    const key = `${b.building_id}|${r.ts}`;
    const card = el("article", null, "alert" + (seenAlerts.has(key) ? "" : " is-new"));
    seenAlerts.add(key);
    const ic = el("span", null, "alert__icon");
    ic.append(icon(ICON_WARN));

    const body = el("div");
    const name = el("div", displayName(b.building_id), "alert__name");
    const rules = (r.reasons || []).map((x) => parseReason(x).rule);
    const parts = [];
    if (rules.includes("Threshold")) parts.push(`limit ${fmtNum(b.max_kw)} kW exceeded`);
    if (typeof r.baseline_kw === "number" && r.baseline_kw > 0) {
      parts.push(`+${Math.round((r.power_kw / r.baseline_kw - 1) * 100)}% vs baseline`);
    }
    body.append(name, el("div", parts.join(", ") || "anomaly flagged", "alert__why"));

    const kw = el("div", `${fmtKw(r.power_kw)} kW`, "alert__kw");
    const time = el("time", fmtTime(r.ts));
    time.dateTime = r.ts;
    kw.append(time);
    card.append(ic, body, kw);
    box.append(card);
  });
}

const cards = new Map();
function renderBuildings(buildings) {
  const box = $("meters");
  buildings.forEach((b) => {
    let c = cards.get(b.building_id);
    if (!c) {
      c = { root: el("article", null, "bcard") };
      const top = el("div", null, "bcard__top");
      top.append(el("span", displayName(b.building_id), "bcard__code"));
      c.status = statusTag("NODATA");
      top.append(c.status);
      c.name = el("div", null, "bcard__name");
      const kw = el("div", null, "bcard__kw");
      c.kw = el("span", "–");
      kw.append(c.kw, el("span", "kW", "unit"));
      c.meter = el("div", null, "meter");
      c.meter.setAttribute("role", "img");
      c.band = el("div", null, "meter__band");
      c.fill = el("div", null, "meter__fill");
      c.limit = el("div", null, "meter__limit");
      c.meter.append(el("div", null, "meter__track"), c.band, c.fill, c.limit);
      c.spark = document.createElementNS(SVG_NS, "svg");
      c.spark.setAttribute("viewBox", "0 0 200 34");
      c.spark.setAttribute("preserveAspectRatio", "none");
      c.spark.setAttribute("class", "spark spark--card");
      c.spark.setAttribute("aria-hidden", "true");
      const stats = el("dl", null, "bcard__stats");
      const stat = (label) => { const d = el("div"); const v = el("dd", "–"); d.append(el("dt", label), v); stats.append(d); return v; };
      c.v = stat("Voltage");
      c.a = stat("Current");
      c.lim = stat("Limit");
      c.root.append(top, c.name, kw, c.meter, c.spark, stats);
      box.append(c.root);
      cards.set(b.building_id, c);
    }

    const r = b.latest;
    const status = r ? r.status : "NODATA";
    const scale = b.max_kw * 1.6; // bar runs past the limit so spikes stay visible
    const pct = (v) => `${Math.min(100, (v / scale) * 100)}%`;

    c.root.classList.toggle("is-anomaly", status === "ANOMALY");
    c.name.textContent = displaySubtitle(b.building_id, `${b.name}, ${b.type}`);
    const tag = statusTag(status);
    if (tag.className !== c.status.className) { c.status.replaceWith(tag); c.status = tag; }
    tween(c.kw, r ? r.power_kw : null);
    c.band.style.left = pct(b.normal_min_kw);
    c.band.style.width = `calc(${pct(b.normal_max_kw)} - ${pct(b.normal_min_kw)})`;
    c.limit.style.left = pct(b.max_kw);
    c.fill.style.width = r ? pct(r.power_kw) : "0%";
    c.meter.setAttribute("aria-label",
      `${displayName(b.building_id)}: ${r ? fmtKw(r.power_kw) : "no"} kW, normal ${b.normal_min_kw} to ${b.normal_max_kw} kW, limit ${b.max_kw} kW`);
    const series = history.buildings.get(b.building_id);
    sparkline(c.spark, series ? [...series.values()] : [],
      { color: status === "ANOMALY" ? "#ff3b30" : "#ffb000", limit: b.max_kw });
    c.v.textContent = r ? `${fmtNum(r.voltage)} V` : "–";
    c.a.textContent = r ? `${fmtNum(r.current)} A` : "–";
    c.lim.textContent = `${fmtNum(b.max_kw)} kW`;
  });
}

function renderReadings(rows) {
  const tbody = $("recent-rows");
  tbody.replaceChildren();
  if (!rows.length) {
    const tr = el("tr", null, "empty");
    const td = el("td", "No readings yet. Start the sensor simulator.");
    td.colSpan = 6;
    tr.append(td);
    tbody.append(tr);
    return;
  }
  rows.slice(0, 12).forEach((r) => {
    const tr = el("tr", null, r.status === "ANOMALY" ? "is-anomaly" : "");
    const status = el("td");
    status.append(statusTag(r.status));
    tr.append(el("td", fmtTime(r.ts), "time"), el("td", displayName(r.building_id), "b"),
      el("td", `${fmtNum(r.voltage)} V`, "num"), el("td", `${fmtNum(r.current, 2)} A`, "num"),
      el("td", `${fmtKw(r.power_kw)} kW`, "num pw"), status);
    tbody.append(tr);
  });
}

function renderLog(anomalies) {
  const list = $("anomaly-rows");
  list.replaceChildren();
  $("log-count").textContent = anomalies.length ? `${anomalies.length} recorded` : "";
  if (!anomalies.length) { list.append(el("li", "No anomalies recorded.", "empty")); return; }
  anomalies.slice(0, 10).forEach((r) => {
    const li = el("li");
    const head = el("div", null, "tl__head");
    const who = el("span", `${displayName(r.building_id)} `);
    who.append(el("b", `${fmtKw(r.power_kw)} kW`));
    const time = el("time", fmtTime(r.ts));
    time.dateTime = r.ts;
    head.append(who, time);
    li.append(head);
    (r.reasons || []).map(parseReason).forEach(({ rule, detail }) => {
      const line = el("div", detail, "tl__rule");
      if (rule) line.prepend(el("em", rule));
      li.append(line);
    });
    list.append(li);
  });
}

function renderSystem(state) {
  const source = $("sys-source");
  source.textContent = state === "live" ? "AWS (live)" : state === "error" ? "Unreachable" : "Browser mock";
  source.className = state === "live" ? "ok" : state === "error" ? "bad" : "warn";
  let host = "–";
  try { host = isMock() ? "none" : new URL(config.url).host; } catch (e) { host = "invalid URL"; }
  $("sys-endpoint").textContent = host;
  $("sys-endpoint").title = config.url;
  $("sys-endpoint").className = "info";
  $("sys-poll").textContent = `every ${REFRESH_MS / 1000} s`;
  $("sys-refreshes").textContent = telemetry.refreshes;
  $("sys-errors").textContent = telemetry.errors;
  $("sys-errors").className = telemetry.errors ? "bad" : "";
}

function setConnection(state, label) {
  $("conn").dataset.state = state;
  $("conn-label").textContent = label;
}

function render({ data, ms }) {
  recordHistory(data);
  renderTopbar(ms, data.generated_at);
  renderLoad(data);
  renderTiles(data.summary);
  renderAlerts(data.buildings);
  renderBuildings(data.buildings);
  renderReadings(data.recent_readings);
  renderLog(data.anomalies);
}

async function refresh() {
  $("mock-banner").hidden = !isMock();
  try {
    render(await loadDashboard());
    telemetry.refreshes += 1;
    $("error-banner").hidden = true;
    const state = isMock() ? "mock" : "live";
    setConnection(state, state === "live" ? "Live" : "Mock");
    renderSystem(state);
  } catch (err) {
    telemetry.errors += 1;
    $("error-banner").textContent = err.message.includes("Failed to fetch")
      ? "Could not reach the API. Check the URL, your internet connection, and CORS settings."
      : err.message;
    $("error-banner").hidden = false;
    setConnection("error", "Error");
    renderSystem("error");
  }
}

// ------------------------------------------------------------- settings (unchanged behaviour)
function initSettings() {
  $("api-url").value = config.url;
  $("save-settings").addEventListener("click", () => {
    config.url = $("api-url").value.trim();
    localStorage.setItem("enercloud_api_url", config.url);
    refresh();
  });
  $("use-mock").addEventListener("click", () => {
    config.url = "";
    localStorage.removeItem("enercloud_api_url");
    $("api-url").value = "";
    refresh();
  });
  $("export-btn").addEventListener("click", exportReport);
}

initSettings();
refresh();
setInterval(refresh, REFRESH_MS);
