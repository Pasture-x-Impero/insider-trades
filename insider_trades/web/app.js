/* Insider Trades frontend. No build step, no dependencies. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];

  const state = {
    market: "", type: "", q: "", from: "", to: "", minv: "",
    sort: "published_at", order: "desc", limit: 50, offset: 0, total: 0,
  };
  const TYPE_LABEL = {
    buy: "Buy", sell: "Sell", option_exercise: "Option exercise", allotment: "Allotment",
    other: "Other", unknown: "Unparsed",
  };
  const MARKET_LABEL = { NO: "Oslo", SE: "Stockholm" };
  const CURRENCY_DEFAULT = { NO: "NOK", SE: "SEK" };

  const fmtNum = (n, digits = 0) =>
    n == null ? "" : n.toLocaleString("en-GB", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
  const fmtMoney = (n, cur) => (n == null ? "" : `${fmtNum(n, 0)} ${cur || ""}`.trim());
  const fmtPrice = (n, cur) => (n == null ? "" : `${fmtNum(n, 2)} ${cur || ""}`.trim());
  const fmtDate = (iso) => (iso ? iso.slice(0, 10) : "");
  const compact = (n) => {
    if (n == null) return "";
    const abs = Math.abs(n);
    if (abs >= 1e9) return (n / 1e9).toFixed(1) + " bn";
    if (abs >= 1e6) return (n / 1e6).toFixed(1) + " m";
    if (abs >= 1e3) return (n / 1e3).toFixed(0) + " k";
    return fmtNum(n);
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  async function getJSON(url, opts) {
    const r = await fetch(url, opts);
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  }

  function params() {
    const p = new URLSearchParams();
    if (state.market) p.set("market", state.market);
    if (state.type) p.set("type", state.type);
    if (state.q) p.set("q", state.q);
    if (state.from) p.set("from", state.from);
    if (state.to) p.set("to", state.to);
    if (state.minv) p.set("min_value", state.minv);
    p.set("sort", state.sort);
    p.set("order", state.order);
    p.set("limit", state.limit);
    p.set("offset", state.offset);
    return p;
  }

  // ----- table -------------------------------------------------------------

  async function loadTrades() {
    const tbody = $("#trades tbody");
    tbody.innerHTML = `<tr><td colspan="8" class="empty">Loading…</td></tr>`;
    try {
      const data = await getJSON(`/api/trades?${params()}`);
      state.total = data.total;
      renderRows(data.items);
      $("#count").textContent = data.total
        ? `${state.offset + 1}–${Math.min(state.offset + state.limit, data.total)} of ${fmtNum(data.total)}`
        : "No trades match";
      $("#prev").disabled = state.offset === 0;
      $("#next").disabled = state.offset + state.limit >= data.total;
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="8" class="empty">${esc(e.message)}</td></tr>`;
    }
    $$("th.sortable").forEach((th) => {
      th.classList.toggle("active", th.dataset.sort === state.sort);
      th.classList.toggle("asc", th.dataset.sort === state.sort && state.order === "asc");
    });
  }

  function renderRows(items) {
    const tbody = $("#trades tbody");
    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="empty">No trades match these filters. Try widening the date range or press Sync now.</td></tr>`;
      return;
    }
    tbody.innerHTML = items.map((t) => {
      const cur = t.currency || CURRENCY_DEFAULT[t.market];
      const who = t.insider_name || "<span class=\"muted\">Unknown</span>";
      const role = [t.position, t.close_associate ? "close associate" : ""].filter(Boolean).join(", ");
      return `<tr data-id="${t.id}" class="${t.parse_confidence < 0.6 ? "low" : ""}">
        <td>${fmtDate(t.published_at)}</td>
        <td><span class="flag">${MARKET_LABEL[t.market] || t.market}</span></td>
        <td>${esc(t.issuer)}${t.ticker ? `<span class="sub">${esc(t.ticker)}</span>` : ""}</td>
        <td>${who}${role ? `<span class="sub">${esc(role)}</span>` : ""}</td>
        <td><span class="badge ${t.trade_type}">${TYPE_LABEL[t.trade_type] || t.trade_type}</span></td>
        <td class="num">${fmtNum(t.quantity)}</td>
        <td class="num">${fmtPrice(t.price, cur)}</td>
        <td class="num">${fmtMoney(t.value, cur)}</td>
      </tr>`;
    }).join("");
  }

  // ----- summary tiles -----------------------------------------------------

  async function loadSummary() {
    try {
      const p = params();
      ["sort", "order", "limit", "offset"].forEach((k) => p.delete(k));
      const s = await getJSON(`/api/summary?${p}`);
      const buy = s.by_type.buy || { count: 0, value: 0 };
      const sell = s.by_type.sell || { count: 0, value: 0 };
      const topBuy = s.top_buys[0];
      const topSell = s.top_sells[0];
      $("#tiles").innerHTML = [
        tile("Trades matching filters", fmtNum(s.total), ""),
        tile("Buys", fmtNum(buy.count), `${compact(buy.value)} total`),
        tile("Sells", fmtNum(sell.count), `${compact(sell.value)} total`),
        tile("Most bought", topBuy ? esc(topBuy.issuer) : "–", topBuy ? `${compact(topBuy.v)} in ${topBuy.n} trades` : ""),
        tile("Most sold", topSell ? esc(topSell.issuer) : "–", topSell ? `${compact(topSell.v)} in ${topSell.n} trades` : ""),
      ].join("");
      renderSync(s.last_sync);
    } catch (e) {
      $("#tiles").innerHTML = "";
    }
  }
  const tile = (label, val, hint) =>
    `<div class="tile"><div class="label">${label}</div><div class="val">${val}</div><div class="hint">${hint}</div></div>`;

  function renderSync(last) {
    const parts = Object.entries(last || {}).map(([m, r]) => {
      const when = r.finished_at ? new Date(r.finished_at).toLocaleString() : "never";
      return `${MARKET_LABEL[m] || m}: ${r.error ? "failed" : when}`;
    });
    $("#sync-status").textContent = parts.length ? `Last sync – ${parts.join(" · ")}` : "Not synced yet";
    $("#sync-status").title = Object.values(last || {}).map((r) => r.error || "").filter(Boolean).join("\n");
  }

  // ----- detail panel ------------------------------------------------------

  async function openDetail(id) {
    const panel = $("#detail");
    const body = $("#detail-body");
    panel.hidden = false;
    body.innerHTML = `<p class="muted">Loading…</p>`;
    let t;
    try {
      t = await getJSON(`/api/trades/${id}`);
    } catch (e) {
      body.innerHTML = `<p class="muted">${esc(e.message)}</p>`;
      return;
    }
    const cur = t.currency || CURRENCY_DEFAULT[t.market];
    const rows = [
      ["Published", t.published_at.replace("T", " ").slice(0, 16)],
      ["Trade date", t.transaction_date || "unknown"],
      ["Insider", [t.insider_name, t.position].filter(Boolean).join(", ") || "unknown"],
      ["Close associate", t.close_associate ? "yes" : "no"],
      ["Type", TYPE_LABEL[t.trade_type]],
      ["Instrument", t.instrument || ""],
      ["Quantity", fmtNum(t.quantity)],
      ["Price", fmtPrice(t.price, cur)],
      ["Value", fmtMoney(t.value, cur)],
      ["Venue", t.venue || ""],
      ["Status", t.status || ""],
      ["ISIN", t.isin || ""],
    ].filter(([, v]) => v !== "");
    body.innerHTML = `
      <h2>${esc(t.issuer)} ${t.ticker ? `<span class="muted">${esc(t.ticker)}</span>` : ""}</h2>
      <div class="muted">${esc(t.title || "")}</div>
      <dl>${rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
      ${t.market === "NO" ? `<p class="notes">Parsed from free text with confidence ${Math.round(t.parse_confidence * 100)}%. Check the original below.</p>` : ""}
      ${t.raw_text ? `<pre>${esc(t.raw_text)}</pre>` : ""}
      ${t.source_url ? `<p><a href="${esc(t.source_url)}" target="_blank" rel="noopener">Open source announcement</a></p>` : ""}
      <div class="chart" id="chart"><h3>Share price around the trade</h3><p class="muted">Loading prices…</p></div>`;
    loadChart(t);
  }

  async function loadChart(t) {
    const el = $("#chart");
    try {
      const d = await getJSON(`/api/prices/${t.id}`);
      renderChart(el, d, t);
    } catch (e) {
      el.innerHTML = `<h3>Share price around the trade</h3><p class="muted">${esc(e.message)}</p>`;
    }
  }

  function renderChart(el, d, t) {
    const pts = d.points;
    if (!pts.length) { el.innerHTML = `<h3>Share price</h3><p class="muted">No price data.</p>`; return; }
    const W = 520, H = 200, m = { t: 10, r: 12, b: 24, l: 48 };
    const xs = pts.map((p) => new Date(p.date).getTime());
    const ys = pts.map((p) => p.close);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    let y0 = Math.min(...ys), y1 = Math.max(...ys);
    if (t.price != null) { y0 = Math.min(y0, t.price); y1 = Math.max(y1, t.price); }
    const pad = (y1 - y0) * 0.08 || 1; y0 -= pad; y1 += pad;
    const X = (v) => m.l + ((v - x0) / (x1 - x0 || 1)) * (W - m.l - m.r);
    const Y = (v) => m.t + (1 - (v - y0) / (y1 - y0)) * (H - m.t - m.b);
    const path = pts.map((p, i) => `${i ? "L" : "M"}${X(xs[i]).toFixed(1)},${Y(p.close).toFixed(1)}`).join("");
    const ticks = 4;
    const step = (y1 - y0) / ticks;
    const decimals = step >= 10 ? 0 : step >= 1 ? 1 : step >= 0.1 ? 2 : 3;
    const grid = [...Array(ticks + 1)].map((_, i) => {
      const v = y0 + step * i;
      return `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${m.l - 6}" y="${Y(v) + 4}" text-anchor="end">${v.toFixed(decimals)}</text>`;
    }).join("");
    const xt = [0, 0.5, 1].map((f) => {
      const v = x0 + (x1 - x0) * f;
      return `<text x="${X(v)}" y="${H - 6}" text-anchor="${f === 0 ? "start" : f === 1 ? "end" : "middle"}">${new Date(v).toISOString().slice(0, 10)}</text>`;
    }).join("");
    const anchorTs = new Date(d.trade_date).getTime();
    const marker = d.anchor_close != null
      ? `<circle class="marker" cx="${X(anchorTs)}" cy="${Y(d.anchor_close)}" r="5"><title>Trade date ${d.trade_date}</title></circle>`
      : "";
    const chg = d.change_since_trade;
    const chgText = chg == null ? "" :
      `Since the trade: <b class="${chg >= 0 ? "up" : "down"}">${chg >= 0 ? "+" : ""}${(chg * 100).toFixed(1)}%</b>`;
    el.innerHTML = `<h3>${esc(d.name || d.symbol)} (${esc(d.symbol)}) – daily close, ${esc(d.currency || "")}</h3>
      <div class="wrap">
        <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Daily closing price with the trade date marked">
          <g class="grid axis">${grid}</g><g class="axis">${xt}</g>
          <path class="line" d="${path}"/>${marker}
          <line class="cross" x1="0" x2="0" y1="${m.t}" y2="${H - m.b}" opacity="0"/>
          <circle class="marker hover" r="4" opacity="0"/>
        </svg>
        <div class="tip" hidden></div>
      </div>
      <div class="stat">${chgText}${d.last != null ? ` · Last ${fmtNum(d.last, 2)}` : ""}${t.price != null ? ` · Trade price ${fmtNum(t.price, 2)}` : ""}</div>`;
    const svg = $("svg", el), tip = $(".tip", el), cross = $(".cross", svg), hov = $(".hover", svg);
    svg.addEventListener("mousemove", (ev) => {
      const r = svg.getBoundingClientRect();
      const px = ((ev.clientX - r.left) / r.width) * W;
      let best = 0, bd = Infinity;
      xs.forEach((x, i) => { const dd = Math.abs(X(x) - px); if (dd < bd) { bd = dd; best = i; } });
      const cx = X(xs[best]), cy = Y(ys[best]);
      cross.setAttribute("x1", cx); cross.setAttribute("x2", cx); cross.setAttribute("opacity", "1");
      hov.setAttribute("cx", cx); hov.setAttribute("cy", cy); hov.setAttribute("opacity", "1");
      tip.hidden = false;
      tip.textContent = `${pts[best].date}: ${fmtNum(ys[best], 2)}`;
      tip.style.left = `${Math.min((cx / W) * r.width + 10, r.width - 130)}px`;
      tip.style.top = `${(cy / H) * r.height - 30}px`;
    });
    svg.addEventListener("mouseleave", () => { tip.hidden = true; cross.setAttribute("opacity", "0"); hov.setAttribute("opacity", "0"); });
  }

  // ----- wiring ------------------------------------------------------------

  const debounce = (fn, ms) => { let h; return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); }; };
  const refresh = () => { state.offset = 0; loadTrades(); loadSummary(); };

  $$(".seg button").forEach((b) => b.addEventListener("click", () => {
    $$(".seg button").forEach((x) => x.classList.toggle("on", x === b));
    state.market = b.dataset.market; refresh();
  }));
  $("#type").addEventListener("change", (e) => { state.type = e.target.value; refresh(); });
  $("#q").addEventListener("input", debounce((e) => { state.q = e.target.value.trim(); refresh(); }, 250));
  $("#from").addEventListener("change", (e) => { state.from = e.target.value; refresh(); });
  $("#to").addEventListener("change", (e) => { state.to = e.target.value; refresh(); });
  $("#minv").addEventListener("change", (e) => { state.minv = e.target.value; refresh(); });
  $$("th.sortable").forEach((th) => th.addEventListener("click", () => {
    const s = th.dataset.sort;
    state.order = state.sort === s && state.order === "desc" ? "asc" : "desc";
    state.sort = s; state.offset = 0; loadTrades();
  }));
  $("#prev").addEventListener("click", () => { state.offset = Math.max(0, state.offset - state.limit); loadTrades(); });
  $("#next").addEventListener("click", () => { state.offset += state.limit; loadTrades(); });
  $("#trades tbody").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-id]");
    if (tr) openDetail(tr.dataset.id);
  });
  $("#close").addEventListener("click", () => { $("#detail").hidden = true; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#detail").hidden = true; });
  $("#sync-btn").addEventListener("click", async () => {
    const btn = $("#sync-btn");
    btn.disabled = true; $("#sync-status").textContent = "Syncing…";
    try {
      const r = await getJSON("/api/sync", { method: "POST" });
      const failed = Object.entries(r).filter(([, v]) => v.error);
      if (failed.length) alert(failed.map(([m, v]) => `${m}: ${v.error}`).join("\n"));
    } catch (e) { alert(e.message); }
    btn.disabled = false;
    refresh();
  });

  refresh();
})();
