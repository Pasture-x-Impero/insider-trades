/* Insider Trades frontend. No build step, no dependencies.
   Runs in two modes: against the HTTP API, or fully offline when the page carries
   its data in a <script id="insider-data" type="application/json"> block. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];

  const state = {
    view: "trades", market: "", type: "", q: "", from: "", to: "", minv: "", issuer: "",
    sort: "published_at", order: "desc", limit: 50, offset: 0, total: 0,
    csort: "net_pct_of_cap", corder: "desc",
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
  const fmtPct = (x) => (x == null ? "" : `${x >= 0 ? "+" : ""}${(x * 100).toFixed(2)}%`);
  const compact = (n) => {
    if (n == null) return "";
    const abs = Math.abs(n);
    if (abs >= 1e12) return (n / 1e12).toFixed(1) + " tn";
    if (abs >= 1e9) return (n / 1e9).toFixed(1) + " bn";
    if (abs >= 1e6) return (n / 1e6).toFixed(1) + " m";
    if (abs >= 1e3) return (n / 1e3).toFixed(0) + " k";
    return fmtNum(n);
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ----- data layer --------------------------------------------------------

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
    if (state.issuer) p.set("issuer", state.issuer);
    return p;
  }

  const remote = {
    mode: "live",
    trades() {
      const p = params();
      p.set("sort", state.sort); p.set("order", state.order);
      p.set("limit", state.limit); p.set("offset", state.offset);
      return getJSON(`/api/trades?${p}`);
    },
    summary() { return getJSON(`/api/summary?${params()}`); },
    companies() { const p = params(); p.delete("issuer"); p.delete("type"); return getJSON(`/api/companies?${p}`); },
    trade(id) { return getJSON(`/api/trades/${id}`); },
    prices(t) { return getJSON(`/api/prices/${t.id}`); },
    sync() { return getJSON("/api/sync", { method: "POST" }); },
  };

  function embedded(data) {
    const all = data.trades;
    const matches = (t, opts = {}) => {
      if (state.market && t.market !== state.market) return false;
      if (!opts.ignoreType && state.type && t.trade_type !== state.type) return false;
      if (!opts.ignoreIssuer && state.issuer && t.issuer !== state.issuer) return false;
      if (state.from && t.published_at < state.from) return false;
      if (state.to && t.published_at.slice(0, 10) > state.to) return false;
      if (state.minv && !(t.value >= Number(state.minv))) return false;
      if (state.q) {
        const q = state.q.toLowerCase();
        const hay = [t.issuer, t.ticker, t.insider_name, t.title].join(" ").toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    };
    const filtered = () => all.filter(matches);
    return {
      mode: "static",
      generated_at: data.generated_at,
      async trades() {
        const items = filtered();
        const k = state.sort, dir = state.order === "asc" ? 1 : -1;
        items.sort((a, b) => {
          const av = a[k], bv = b[k];
          if (av == null && bv == null) return b.published_at.localeCompare(a.published_at);
          if (av == null) return 1;
          if (bv == null) return -1;
          const c = typeof av === "number" ? av - bv : String(av).localeCompare(String(bv));
          return c ? c * dir : b.published_at.localeCompare(a.published_at);
        });
        return { total: items.length, items: items.slice(state.offset, state.offset + state.limit) };
      },
      async summary() {
        const items = filtered();
        const by_type = {};
        const agg = {};
        for (const t of items) {
          const bt = (by_type[t.trade_type] ||= { count: 0, value: 0 });
          bt.count += 1; bt.value += t.value || 0;
          if ((t.trade_type === "buy" || t.trade_type === "sell") && t.value != null) {
            const key = `${t.trade_type}|${t.market}|${t.issuer}`;
            const a = (agg[key] ||= { issuer: t.issuer, ticker: t.ticker, market: t.market, n: 0, v: 0, type: t.trade_type });
            a.n += 1; a.v += t.value;
          }
        }
        const top = (type) => Object.values(agg).filter((a) => a.type === type).sort((a, b) => b.v - a.v).slice(0, 10);
        return { total: items.length, by_type, top_buys: top("buy"), top_sells: top("sell"), last_sync: data.last_sync || {} };
      },
      async companies() {
        const agg = {};
        for (const t of all) {
          if (!matches(t, { ignoreType: true, ignoreIssuer: true })) continue;
          const key = `${t.market}|${t.issuer}`;
          const a = (agg[key] ||= {
            market: t.market, issuer: t.issuer, ticker: t.ticker, symbol: t.symbol, buy_count: 0, buy_value: 0,
            sell_count: 0, sell_value: 0, trade_count: 0, insiders: new Set(), market_cap: null,
          });
          a.trade_count += 1;
          if (t.insider_name) a.insiders.add(t.insider_name);
          if (t.symbol && !a.symbol) a.symbol = t.symbol;
          if (t.trade_type === "buy") { a.buy_count += 1; a.buy_value += t.value || 0; }
          if (t.trade_type === "sell") { a.sell_count += 1; a.sell_value += t.value || 0; }
        }
        return Object.values(agg).map((a) => {
          const q = a.symbol && data.quotes ? data.quotes[a.symbol] : null;
          // Only a market cap in the trade currency gives a meaningful share.
          const cap = q && q.market_cap && q.currency === CURRENCY_DEFAULT[a.market] ? q.market_cap : null;
          const net = a.buy_value - a.sell_value;
          return { ...a, insiders: a.insiders.size, net_value: net, market_cap: cap,
            net_pct_of_cap: cap ? net / cap : null };
        });
      },
      async trade(id) {
        const t = all.find((x) => String(x.id) === String(id));
        if (!t) throw new Error("trade not found");
        return t;
      },
      async prices(t) {
        const series = t.symbol && data.prices && data.prices[t.symbol];
        if (!series) throw new Error("No price history was embedded for this issuer.");
        const anchor = t.transaction_date || t.published_at.slice(0, 10);
        const from = new Date(anchor); from.setDate(from.getDate() - 30);
        const points = series.points.filter((p) => p.date >= from.toISOString().slice(0, 10));
        const anchorPt = points.find((p) => p.date >= anchor);
        const last = points.length ? points[points.length - 1].close : null;
        return {
          ...series, points, trade_date: anchor, anchor_close: anchorPt ? anchorPt.close : null,
          change_since_trade: anchorPt && last ? last / anchorPt.close - 1 : null,
        };
      },
      async sync() { throw new Error("This is a static snapshot. Regenerate it with: insider-trades render"); },
    };
  }

  const dataEl = $("#insider-data");
  const api = dataEl ? embedded(JSON.parse(dataEl.textContent)) : remote;

  // ----- table -------------------------------------------------------------

  async function loadTrades() {
    const tbody = $("#trades tbody");
    tbody.innerHTML = `<tr><td colspan="8" class="empty">Loading…</td></tr>`;
    try {
      const data = await api.trades();
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
    $$("#trades th.sortable").forEach((th) => {
      th.classList.toggle("active", th.dataset.sort === state.sort);
      th.classList.toggle("asc", th.dataset.sort === state.sort && state.order === "asc");
    });
  }

  function renderRows(items) {
    const tbody = $("#trades tbody");
    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="empty">No trades match these filters. Try widening the date range.</td></tr>`;
      return;
    }
    tbody.innerHTML = items.map((t) => {
      const cur = t.currency || CURRENCY_DEFAULT[t.market];
      const who = t.insider_name ? esc(t.insider_name) : "<span class=\"muted\">Unknown</span>";
      const role = [t.position, t.close_associate ? "close associate" : ""].filter(Boolean).join(", ");
      return `<tr data-id="${t.id}" class="${t.parse_confidence < 0.6 ? "low" : ""}">
        <td>${fmtDate(t.published_at)}</td>
        <td><span class="flag">${MARKET_LABEL[t.market] || t.market}</span></td>
        <td>${esc(t.issuer)}${t.ticker ? `<span class="sub">${esc(t.ticker)}</span>` : ""}</td>
        <td>${who}${role ? `<span class="sub">${esc(role)}</span>` : ""}</td>
        <td><span class="badge ${t.trade_type}">${TYPE_LABEL[t.trade_type] || t.trade_type}</span></td>
        <td class="num"><b>${fmtMoney(t.value, cur)}</b></td>
        <td class="num">${fmtNum(t.quantity)}</td>
        <td class="num">${fmtPrice(t.price, cur)}</td>
      </tr>`;
    }).join("");
  }

  // ----- companies view ----------------------------------------------------

  let companyRows = [];

  async function loadCompanies() {
    const tbody = $("#companies tbody");
    tbody.innerHTML = `<tr><td colspan="9" class="empty">Loading…</td></tr>`;
    try {
      companyRows = await api.companies();
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="9" class="empty">${esc(e.message)}</td></tr>`;
      return;
    }
    renderCompanies();
  }

  function renderCompanies() {
    const tbody = $("#companies tbody");
    const k = state.csort, dir = state.corder === "asc" ? 1 : -1;
    const rows = [...companyRows].sort((a, b) => {
      const av = a[k], bv = b[k];
      if (av == null && bv == null) return b.net_value - a.net_value;
      if (av == null) return 1;
      if (bv == null) return -1;
      const c = typeof av === "number" ? av - bv : String(av).localeCompare(String(bv));
      return c ? c * dir : b.net_value - a.net_value;
    });
    $$("#companies th.sortable").forEach((th) => {
      th.classList.toggle("active", th.dataset.csort === state.csort);
      th.classList.toggle("asc", th.dataset.csort === state.csort && state.corder === "asc");
    });
    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="9" class="empty">No companies match these filters.</td></tr>`;
      return;
    }
    tbody.innerHTML = rows.map((r) => {
      const cur = CURRENCY_DEFAULT[r.market];
      const pct = r.net_pct_of_cap;
      const strong = pct != null && Math.abs(pct) >= 0.005 ? "strong" : "";
      const dirCls = pct != null && pct < 0 ? "down" : "";
      return `<tr data-issuer="${esc(r.issuer)}" data-market="${r.market}">
        <td>${esc(r.issuer)}${r.ticker ? `<span class="sub">${esc(r.ticker)}</span>` : ""}</td>
        <td><span class="flag">${MARKET_LABEL[r.market] || r.market}</span></td>
        <td class="num">${r.buy_value ? `${compact(r.buy_value)} ${cur}` : ""}<span class="sub">${r.buy_count || 0} buys</span></td>
        <td class="num">${r.sell_value ? `${compact(r.sell_value)} ${cur}` : ""}<span class="sub">${r.sell_count || 0} sells</span></td>
        <td class="num ${r.net_value > 0 ? "up" : r.net_value < 0 ? "down" : ""}">${r.net_value ? `${r.net_value > 0 ? "+" : ""}${compact(r.net_value)} ${cur}` : ""}</td>
        <td class="num">${fmtNum(r.trade_count)}</td>
        <td class="num">${fmtNum(r.insiders)}</td>
        <td class="num">${r.market_cap ? `${compact(r.market_cap)} ${cur}` : "<span class=\"muted\">n/a</span>"}</td>
        <td class="num pct ${strong} ${dirCls} ${pct > 0 ? "up" : pct < 0 ? "down" : ""}">${fmtPct(pct)}</td>
      </tr>`;
    }).join("");
  }

  function setView(view) {
    state.view = view;
    $$(".seg button[data-view]").forEach((b) => b.classList.toggle("on", b.dataset.view === view));
    $("#trades-view").hidden = view !== "trades";
    $("#companies-view").hidden = view !== "companies";
    $("#type").disabled = view === "companies";
    if (view === "companies") loadCompanies(); else loadTrades();
  }

  function setIssuer(issuer) {
    state.issuer = issuer || "";
    $("#issuer-chip").hidden = !state.issuer;
    $("#issuer-chip-name").textContent = state.issuer;
    refresh();
  }

  // ----- summary tiles -----------------------------------------------------

  async function loadSummary() {
    try {
      const s = await api.summary();
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
    const prefix = api.mode === "static" && api.generated_at
      ? `Snapshot ${new Date(api.generated_at).toLocaleString()}`
      : "Last sync";
    $("#sync-status").textContent = parts.length ? `${prefix} – ${parts.join(" · ")}` : "Not synced yet";
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
      t = await api.trade(id);
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
      ${t.suspect ? `<p class="notes warn">Price and value hidden: ${esc(t.suspect)}. Check the source filing.</p>` : ""}
      ${t.market === "NO" ? `<p class="notes">Parsed from free text with confidence ${Math.round(t.parse_confidence * 100)}%. Check the original below.</p>` : ""}
      ${t.raw_text ? `<pre>${esc(t.raw_text)}</pre>` : ""}
      ${t.source_url ? `<p><a href="${esc(t.source_url)}" target="_blank" rel="noopener">Open source announcement</a></p>` : ""}
      <div class="chart" id="chart"><h3>Share price around the trade</h3><p class="muted">Loading prices…</p></div>`;
    loadChart(t);
  }

  async function loadChart(t) {
    const el = $("#chart");
    try {
      const d = await api.prices(t);
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
  const refresh = () => {
    state.offset = 0;
    if (state.view === "companies") loadCompanies(); else loadTrades();
    loadSummary();
  };

  $$(".seg button[data-market]").forEach((b) => b.addEventListener("click", () => {
    $$(".seg button[data-market]").forEach((x) => x.classList.toggle("on", x === b));
    state.market = b.dataset.market; refresh();
  }));
  $$(".seg button[data-view]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
  $$("#companies th.sortable").forEach((th) => th.addEventListener("click", () => {
    const k = th.dataset.csort;
    state.corder = state.csort === k && state.corder === "desc" ? "asc" : "desc";
    state.csort = k; renderCompanies();
  }));
  $("#companies tbody").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-issuer]");
    if (!tr) return;
    setView("trades");
    setIssuer(tr.dataset.issuer);
  });
  $("#issuer-clear").addEventListener("click", () => setIssuer(""));
  $("#type").addEventListener("change", (e) => { state.type = e.target.value; refresh(); });
  $("#q").addEventListener("input", debounce((e) => { state.q = e.target.value.trim(); refresh(); }, 250));
  $("#from").addEventListener("change", (e) => { state.from = e.target.value; refresh(); });
  $("#to").addEventListener("change", (e) => { state.to = e.target.value; refresh(); });
  $("#minv").addEventListener("change", (e) => { state.minv = e.target.value; refresh(); });
  $$("#trades th.sortable").forEach((th) => th.addEventListener("click", () => {
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
  const syncBtn = $("#sync-btn");
  if (api.mode === "static") syncBtn.hidden = true;
  syncBtn.addEventListener("click", async () => {
    syncBtn.disabled = true; $("#sync-status").textContent = "Syncing…";
    try {
      const r = await api.sync();
      const failed = Object.entries(r).filter(([, v]) => v.error);
      if (failed.length) alert(failed.map(([m, v]) => `${m}: ${v.error}`).join("\n"));
    } catch (e) { alert(e.message); }
    syncBtn.disabled = false;
    refresh();
  });

  refresh();
})();
