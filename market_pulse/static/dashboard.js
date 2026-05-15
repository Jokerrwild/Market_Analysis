let dashboardState = null;

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

function fmtMoney(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return money.format(Number(value));
}

function fmtNumber(value, digits = 4) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return Number(value).toLocaleString("en-US", {
    maximumFractionDigits: digits,
  });
}

function fmtPct(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  const sign = Number(value) > 0 ? "+" : "";
  return `${sign}${Number(value).toFixed(digits)}%`;
}

function fmtDateRange(range) {
  if (!range || !range.first || !range.latest) return "No rows yet";
  const first = new Date(range.first).toLocaleString();
  const latest = new Date(range.latest).toLocaleString();
  return `${first} to ${latest}`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  })[character]);
}

function getAssetInfo(asset) {
  const symbol = String(asset || "").toUpperCase();
  const info = dashboardState?.asset_info?.[symbol] || {};
  return {
    symbol,
    name: info.name || symbol,
    description: info.description || `${symbol} is available in the current market scan.`,
    product_id: info.product_id || `${symbol}-USD`,
    quote_currency: info.quote_currency || "USD",
    status: info.status || "",
    regulatory_tags: info.regulatory_tags || [],
    regulatory_support: info.regulatory_support || 0,
    regulatory_events: info.regulatory_events || [],
  };
}

function assetTag(asset) {
  const info = getAssetInfo(asset);
  const status = info.status ? ` · ${escapeHtml(info.status)}` : "";
  const regulatoryText = info.regulatory_tags.length
    ? `<small>${escapeHtml(info.regulatory_tags.join(", "))} · support ${Number(info.regulatory_support).toFixed(2)}</small>`
    : "";
  return `
    <span class="asset-symbol" tabindex="0">
      <span class="asset-code">${escapeHtml(info.symbol)}</span>
      <span class="asset-tooltip" role="tooltip">
        <strong>${escapeHtml(info.name)}</strong>
        <span>${escapeHtml(info.description)}</span>
        ${regulatoryText}
        <small>${escapeHtml(info.product_id)} · ${escapeHtml(info.quote_currency)}${status}</small>
      </span>
    </span>
  `;
}

function pnlClass(value) {
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "";
}

function setText(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value;
}

function setHTML(id, value) {
  const node = document.getElementById(id);
  if (node) node.innerHTML = value;
}

function setValue(id, value) {
  const node = document.getElementById(id);
  if (node) node.value = value;
}

function on(id, eventName, handler) {
  const node = document.getElementById(id);
  if (node) node.addEventListener(eventName, handler);
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

async function loadDashboard(forceRefresh = false) {
  showToast(forceRefresh ? "Collecting fresh market data..." : "Loading dashboard...");
  const payload = await requestJson(forceRefresh ? "/api/dashboard?refresh=1" : "/api/dashboard");
  dashboardState = payload;
  renderDashboard(payload);
  showToast("Dashboard updated.");
}

function renderDashboard(payload) {
  const ledger = payload.ledger;
  const goal = ledger.goal || {};
  const posture = payload.trade_posture;
  const analysis = payload.analysis;

  setText("generatedAt", `Generated ${new Date(payload.generated_at).toLocaleString()}`);
  setText(
    "dataWindowBadge",
    `${payload.data_window.crypto_lookback_days} days / ${Math.round((payload.data_window.crypto_granularity_seconds[0] || 3600) / 60)}m`
  );
  setText("totalEquity", fmtMoney(ledger.total_equity));
  setText("roiStatus", ledger.roi_pct === null ? "Set capital" : fmtPct(ledger.roi_pct));
  setText("totalPnl", fmtMoney(ledger.total_pnl));
  setText("cashBalance", fmtMoney(ledger.cash));
  setText("targetEquity", fmtMoney(goal.target_equity));
  setText("dailyPace", goal.required_daily_return_pct === null ? "n/a" : fmtPct(goal.required_daily_return_pct));
  applyValueClass("roiStatus", ledger.roi_pct);
  applyValueClass("totalPnl", ledger.total_pnl);

  setText("tradeBias", posture.bias);
  setText("tradeRegime", posture.regime);
  setText("tradeProbability", `${(posture.probability * 100).toFixed(1)}%`);
  setHTML("tradeReference", `${assetTag(posture.base_asset)} ${fmtMoney(posture.reference_price)}`);
  setText("tradePosture", posture.posture);
  setText("entryTrigger", posture.entry_trigger);
  setText("tradeInvalidation", posture.invalidation);
  setText("riskNote", posture.risk_note);
  setText("confidenceBadge", posture.confidence);

  setValue("initialCapital", ledger.initial_capital || "");
  setValue("targetRoi", ledger.target_roi_pct || "");
  setValue("targetDays", ledger.target_days || "");
  renderAssetOptions(payload.assets, payload.prices);
  renderOrderBudget(ledger);
  renderGoalPlan(payload.goal_plan, goal);
  renderWarnings(payload.warnings || []);
  renderDatabase(payload.database);
  renderRegulatoryContext(payload.regulatory_context);
  renderLedgerAudit(ledger);
  renderAssets(payload);
  renderMarketBreadth(payload.market_breadth);
  renderProbabilities(analysis.probabilities);
  renderEvidence(analysis);
  renderHoldings(ledger.holdings);
  renderTransactions(ledger.transactions);
}

function renderRegulatoryContext(context) {
  const grid = document.getElementById("regulatoryRows");
  if (!grid) return;
  grid.innerHTML = "";
  const activeAssets = context?.active_assets || [];
  setText(
    "regulatoryStatusBadge",
    context?.enabled ? `${activeAssets.length} covered assets` : "Disabled"
  );
  if (!context?.enabled) {
    grid.innerHTML = `<div class="regulatory-card">Regulatory context is disabled in configuration.</div>`;
    return;
  }
  if (!activeAssets.length) {
    grid.innerHTML = `<div class="regulatory-card">No tracked, held, or candidate assets currently match a configured regulatory event.</div>`;
    return;
  }
  activeAssets.slice(0, 12).forEach((asset) => {
    const profile = context.assets?.[asset] || {};
    const event = profile.events?.[0] || {};
    const card = document.createElement("div");
    card.className = "regulatory-card";
    card.innerHTML = `
      <div class="regulatory-head">
        <strong>${assetTag(asset)}</strong>
        <span class="badge">${escapeHtml((profile.tags || []).join(", ") || "Context")}</span>
      </div>
      <p>${escapeHtml(event.summary || "Regulatory context is configured for this asset.")}</p>
      <small>${escapeHtml(event.title || "Regulatory event")} · ${escapeHtml(event.date || "n/a")} · support ${fmtNumber(profile.support_score || 0, 2)}</small>
    `;
    grid.appendChild(card);
  });
}

function renderDatabase(database) {
  if (!database) return;
  const counts = database.counts || {};
  setText("databaseRetentionBadge", `${database.retention_days || 5} day crypto retention`);
  setText("databasePath", database.path || "market_pulse.db");
  setText("cryptoCandleCount", fmtNumber(counts.crypto_candles || 0, 0));
  setText("cryptoDataRange", fmtDateRange(database.crypto_range));
  setText("analysisRunCount", fmtNumber(counts.analysis_runs || 0, 0));
}

function renderLedgerAudit(ledger) {
  const math = ledger.math || {};
  const statusText = ledger.ledger_valid ? "Ledger Valid" : "Ledger Needs Review";
  setText("ledgerStatusBadge", statusText);
  const status = document.getElementById("ledgerStatusBadge");
  if (status) {
    status.classList.remove("positive", "negative");
    status.classList.add(ledger.ledger_valid ? "positive" : "negative");
  }
  setText(
    "ledgerCashMath",
    `${fmtMoney(ledger.initial_capital)} - ${fmtMoney(math.total_buy_cost)} + ${fmtMoney(math.total_sell_proceeds)} = ${fmtMoney(ledger.cash)}`
  );
  setText(
    "ledgerEquityMath",
    `${fmtMoney(ledger.cash)} cash + ${fmtMoney(ledger.holdings_value)} holdings = ${fmtMoney(ledger.total_equity)}`
  );
  setText(
    "ledgerPnlMath",
    `${fmtMoney(ledger.total_equity)} - ${fmtMoney(ledger.initial_capital)} = ${fmtMoney(ledger.total_pnl)}`
  );
  setText(
    "ledgerReconciliation",
    `${fmtMoney(ledger.realized_pnl)} realized + ${fmtMoney(ledger.unrealized_pnl)} unrealized = ${fmtMoney(ledger.component_total_pnl)}; delta ${fmtMoney(ledger.reconciliation_delta)}`
  );
}

function renderOrderBudget(ledger) {
  setText("orderBudget", `Available cash: ${fmtMoney(ledger.cash)}`);
  updateOrderEstimate();
}

function renderWarnings(warnings) {
  const panel = document.getElementById("warningPanel");
  const list = document.getElementById("warningList");
  list.innerHTML = "";
  if (!warnings.length) {
    panel.hidden = true;
    return;
  }
  warnings.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    list.appendChild(li);
  });
  panel.hidden = false;
}

function applyValueClass(id, value) {
  const node = document.getElementById(id);
  if (!node) return;
  node.classList.remove("positive", "negative");
  const className = pnlClass(Number(value));
  if (className) {
    node.classList.add(className);
  }
}

function renderAssetOptions(assets, prices) {
  const select = document.getElementById("assetSelect");
  if (!select) return;
  const previous = select.value;
  select.innerHTML = "";
  assets.forEach((asset) => {
    const option = document.createElement("option");
    const info = getAssetInfo(asset);
    option.value = asset;
    option.textContent = asset;
    option.title = `${info.name}: ${info.description}`;
    select.appendChild(option);
  });
  if (assets.includes(previous)) {
    select.value = previous;
  }
  if (!select.value && assets.length) {
    select.value = assets[0];
  }
  setPriceFromAsset(prices);
}

function setPriceFromAsset(prices) {
  const select = document.getElementById("assetSelect");
  const input = document.getElementById("priceInput");
  if (!select || !input) return;
  const asset = select.value;
  const price = prices?.[asset];
  if (price) {
    input.value = Number(price).toFixed(2);
  }
  updateOrderEstimate();
}

function updateOrderEstimate() {
  const form = document.getElementById("transactionForm");
  if (!form || !dashboardState) return;
  const formData = new FormData(form);
  const side = formData.get("side");
  const quantity = Number(formData.get("quantity") || 0);
  const price = Number(formData.get("price") || 0);
  const fees = Number(formData.get("fees") || 0);
  const gross = quantity * price;
  const cost = side === "SELL" ? Math.max(gross - fees, 0) : gross + fees;
  const cash = Number(dashboardState.ledger?.cash || 0);
  const prefix = side === "SELL" ? "Estimated proceeds" : "Estimated order cost";
  setText("orderEstimate", `${prefix}: ${fmtMoney(cost)}${side === "BUY" ? ` / available ${fmtMoney(cash)}` : ""}`);
  const estimate = document.getElementById("orderEstimate");
  if (estimate) {
    estimate.classList.remove("negative", "positive");
    if (side === "BUY" && cost > cash) estimate.classList.add("negative");
  }
}

function renderAssets(payload) {
  const grid = document.getElementById("assetGrid");
  if (!grid) return;
  grid.innerHTML = "";
  const crypto = payload.analysis.snapshot.crypto;
  const holdingAssets = new Set(payload.portfolio_holding_assets || []);
  if (!Object.keys(crypto).length) {
    grid.innerHTML = `<article class="asset-card">No assets are tracked yet. Use the Track buttons in ROI Goal Plan, Top Movers, or Top Traded.</article>`;
    return;
  }
  Object.entries(crypto).forEach(([asset, summary]) => {
    const isLedgerHolding = holdingAssets.has(asset.toUpperCase());
    const card = document.createElement("article");
    card.className = "asset-card";
    card.innerHTML = `
      <div class="asset-head">
        <div class="asset-title">
          <h3>${assetTag(asset)}</h3>
          <span class="label">${new Date(summary.latest_time).toLocaleString()}</span>
        </div>
        <div class="asset-price">${fmtMoney(summary.latest_close)}</div>
      </div>
      <div class="asset-stats">
        <div><span class="label">24h</span><strong class="${pnlClass(summary.change_24h_pct)}">${fmtPct(summary.change_24h_pct)}</strong></div>
        <div><span class="label">5d</span><strong class="${pnlClass(summary.change_5d_pct)}">${fmtPct(summary.change_5d_pct)}</strong></div>
        <div><span class="label">RSI</span><strong>${fmtNumber(summary.rsi_14, 1)}</strong></div>
        <div><span class="label">Trend</span><strong class="${pnlClass(summary.trend_score)}">${summary.trend_score.toFixed(2)}</strong></div>
      </div>
      <div class="chart-wrap">
        <canvas id="chart-${asset}" aria-label="${asset} chart"></canvas>
      </div>
      <div class="asset-actions">
        ${
          isLedgerHolding
            ? `<span class="badge">Ledger Holding</span>`
            : `<button class="secondary-button" data-untrack="${asset}" title="Remove ${asset} from tracked charts">Untrack</button>`
        }
      </div>
    `;
    grid.appendChild(card);
    drawChart(`chart-${asset}`, payload.charts[asset] || []);
  });
}

function renderMarketBreadth(marketBreadth) {
  if (!marketBreadth) return;
  const excluded = marketBreadth.excluded_assets || [];
  setText("moverExclusions", excluded.length ? `Excluding ${excluded.join(", ")}` : "No exclusions");
  renderMarketRows("moverRows", marketBreadth.top_movers || [], "movers");
  renderMarketRows("tradedRows", marketBreadth.top_traded || [], "traded");
}

function renderGoalPlan(goalPlan, goal) {
  if (!goalPlan) return;
  setText("goalPaceBadge", goal.pace_status || "Not set");
  setText("goalProfit", fmtMoney(goal.target_profit));
  setText("goalRemaining", fmtMoney(goal.profit_remaining));
  setText("goalDaysLeft", goal.days_remaining === null || goal.days_remaining === undefined ? "n/a" : `${goal.days_remaining}`);
  setText("goalProgress", goal.progress_pct === null || goal.progress_pct === undefined ? "n/a" : fmtPct(goal.progress_pct));
  setText("goalNarrative", goalPlan.narrative);
  applyValueClass("goalProgress", goal.progress_pct || 0);

  const body = document.getElementById("candidateRows");
  if (!body) return;
  body.innerHTML = "";
  if (!goalPlan.candidates.length) {
    body.innerHTML = `<tr><td colspan="8">Set a goal or refresh when candidates are available.</td></tr>`;
    return;
  }
  goalPlan.candidates.forEach((item) => {
    const row = document.createElement("tr");
    const summary = item.summary || {};
    row.title = item.trade_frame;
    row.innerHTML = `
      <td>${assetTag(item.asset)}</td>
      <td>${fmtMoney(summary.price ?? item.price)}</td>
      <td class="${pnlClass(summary.change_24h_pct ?? item.change_24h_pct)}">${fmtPct(summary.change_24h_pct ?? item.change_24h_pct)}</td>
      <td class="${pnlClass(summary.change_5d_pct)}">${fmtPct(summary.change_5d_pct)}</td>
      <td>${fmtNumber(summary.rsi_14, 1)}</td>
      <td class="${pnlClass(summary.trend_score)}">${fmtNumber(summary.trend_score, 2)}</td>
      <td>${fmtNumber(item.opportunity_score, 1)}</td>
      <td><button class="secondary-button" data-track="${item.asset}" data-product="${item.product_id}" title="Track ${item.asset}">Track</button></td>
    `;
    body.appendChild(row);
  });
}

function renderMarketRows(targetId, rows, mode) {
  const body = document.getElementById(targetId);
  if (!body) return;
  body.innerHTML = "";
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="5">Market scan unavailable.</td></tr>`;
    return;
  }
  rows.forEach((item) => {
    const row = document.createElement("tr");
    if (mode === "movers") {
      row.innerHTML = `
        <td>${assetTag(item.asset)}</td>
        <td class="${pnlClass(item.change_24h_pct)}">${fmtPct(item.change_24h_pct)}</td>
        <td>${fmtMoney(item.price)}</td>
        <td>${fmtMoney(item.quote_volume_24h)}</td>
        <td><button class="secondary-button" data-track="${item.asset}" data-product="${item.product_id}" title="Track ${item.asset}">Track</button></td>
      `;
    } else {
      row.innerHTML = `
        <td>${assetTag(item.asset)}</td>
        <td>${fmtMoney(item.quote_volume_24h)}</td>
        <td class="${pnlClass(item.change_24h_pct)}">${fmtPct(item.change_24h_pct)}</td>
        <td>${fmtMoney(item.price)}</td>
        <td><button class="secondary-button" data-track="${item.asset}" data-product="${item.product_id}" title="Track ${item.asset}">Track</button></td>
      `;
    }
    body.appendChild(row);
  });
}

function drawChart(canvasId, candles) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || candles.length === 0) return;
  const rect = canvas.parentElement.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(320, rect.width) * ratio;
  canvas.height = Math.max(220, rect.height) * ratio;
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);

  const width = canvas.width / ratio;
  const height = canvas.height / ratio;
  const pad = { top: 12, right: 12, bottom: 28, left: 52 };
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom - 38;
  const closes = candles.map((item) => item.close);
  const volumes = candles.map((item) => item.volume);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const volumeMax = Math.max(...volumes, 1);
  const span = max - min || 1;

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = "#dbe2ea";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + (plotHeight / 4) * i;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
  }

  candles.forEach((item, index) => {
    const x = pad.left + (index / Math.max(1, candles.length - 1)) * plotWidth;
    const barHeight = (item.volume / volumeMax) * 30;
    ctx.fillStyle = "rgba(15, 118, 110, 0.20)";
    ctx.fillRect(x, height - pad.bottom - barHeight, Math.max(1, plotWidth / candles.length - 1), barHeight);
  });

  ctx.beginPath();
  candles.forEach((item, index) => {
    const x = pad.left + (index / Math.max(1, candles.length - 1)) * plotWidth;
    const y = pad.top + (1 - (item.close - min) / span) * plotHeight;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  const first = closes[0];
  const last = closes[closes.length - 1];
  ctx.strokeStyle = last >= first ? "#047857" : "#b42318";
  ctx.lineWidth = 2.4;
  ctx.stroke();

  ctx.fillStyle = "#627085";
  ctx.font = "12px Segoe UI, Arial";
  ctx.fillText(fmtMoney(max), 6, pad.top + 10);
  ctx.fillText(fmtMoney(min), 6, pad.top + plotHeight);
  ctx.fillText(new Date(candles[0].time).toLocaleDateString(), pad.left, height - 8);
  ctx.fillText(new Date(candles[candles.length - 1].time).toLocaleDateString(), width - 98, height - 8);
}

function renderProbabilities(probabilities) {
  const body = document.getElementById("probabilityRows");
  if (!body) return;
  body.innerHTML = "";
  probabilities.forEach((item) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${item.regime}</td>
      <td>${(item.probability * 100).toFixed(1)}%</td>
      <td>${item.confidence}</td>
    `;
    body.appendChild(row);
  });
}

function renderEvidence(analysis) {
  const list = document.getElementById("evidenceList");
  if (!list) return;
  list.innerHTML = "";
  [...analysis.quantitative_evidence.slice(0, 6), ...analysis.qualitative_evidence.slice(0, 6)].forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    list.appendChild(li);
  });
}

function renderHoldings(holdings) {
  const body = document.getElementById("holdingRows");
  if (!body) return;
  body.innerHTML = "";
  if (!holdings.length) {
    body.innerHTML = `<tr><td colspan="5">No open positions.</td></tr>`;
    return;
  }
  holdings.forEach((item) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${assetTag(item.asset)}</td>
      <td>${fmtNumber(item.quantity, 8)}</td>
      <td>${fmtMoney(item.average_cost)}</td>
      <td>${fmtMoney(item.market_value)}</td>
      <td class="${pnlClass(item.unrealized_pnl)}">${fmtMoney(item.unrealized_pnl)}</td>
    `;
    body.appendChild(row);
  });
}

function renderTransactions(transactions) {
  const body = document.getElementById("transactionRows");
  if (!body) return;
  body.innerHTML = "";
  if (!transactions.length) {
    body.innerHTML = `<tr><td colspan="6">No transactions recorded.</td></tr>`;
    return;
  }
  transactions.forEach((item) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${new Date(item.timestamp).toLocaleString()}</td>
      <td>${item.side}</td>
      <td>${assetTag(item.asset)}</td>
      <td>${fmtNumber(item.quantity, 8)}</td>
      <td>${fmtMoney(item.price)}</td>
      <td><button class="delete-button" data-id="${item.id}" title="Delete transaction">X</button></td>
    `;
    body.appendChild(row);
  });
}

function showToast(message) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 2200);
}

function setDefaultTransactionTime() {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  setValue("transactionTime", now.toISOString().slice(0, 16));
}

on("refreshButton", "click", () => {
  loadDashboard(true).catch((error) => showToast(error.message));
});

on("exitButton", "click", async () => {
  const confirmed = window.confirm("Stop the Market Pulse dashboard server?");
  if (!confirmed) return;
  try {
    await requestJson("/api/shutdown", {
      method: "POST",
      body: JSON.stringify({}),
    });
    setText("generatedAt", "Market Pulse stopped. You can close this browser tab.");
    showToast("Market Pulse stopped.");
  } catch (error) {
    showToast(error.message);
  }
});

on("assetSelect", "change", () => {
  setPriceFromAsset(dashboardState?.prices || {});
});

on("transactionForm", "input", () => {
  updateOrderEstimate();
});

on("capitalForm", "submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    await requestJson("/api/goal", {
      method: "POST",
      body: JSON.stringify({
        initial_capital: Number(form.get("initial_capital")),
        target_roi_pct: Number(form.get("target_roi_pct")),
        target_days: Number(form.get("target_days")),
      }),
    });
    await loadDashboard();
  } catch (error) {
    showToast(error.message);
  }
});

on("transactionForm", "submit", async (event) => {
  event.preventDefault();
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  const payload = {
    side: form.get("side"),
    asset: form.get("asset"),
    quantity: Number(form.get("quantity")),
    price: Number(form.get("price")),
    fees: Number(form.get("fees") || 0),
    timestamp: form.get("timestamp") ? new Date(form.get("timestamp")).toISOString() : undefined,
    notes: form.get("notes"),
  };
  try {
    await requestJson("/api/transactions", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    formElement.reset();
    setDefaultTransactionTime();
    await loadDashboard();
  } catch (error) {
    showToast(error.message);
  }
});

on("transactionRows", "click", async (event) => {
  const button = event.target.closest("button[data-id]");
  if (!button) return;
  try {
    await requestJson(`/api/transactions/${encodeURIComponent(button.dataset.id)}`, {
      method: "DELETE",
    });
    await loadDashboard();
  } catch (error) {
    showToast(error.message);
  }
});

document.body?.addEventListener("click", async (event) => {
  const trackButton = event.target.closest("button[data-track]");
  const untrackButton = event.target.closest("button[data-untrack]");
  try {
    if (trackButton) {
      await requestJson("/api/tracked", {
        method: "POST",
        body: JSON.stringify({
          asset: trackButton.dataset.track,
          product_id: trackButton.dataset.product,
        }),
      });
      await loadDashboard();
      return;
    }
    if (untrackButton) {
      await requestJson(`/api/tracked/${encodeURIComponent(untrackButton.dataset.untrack)}`, {
        method: "DELETE",
      });
      await loadDashboard();
    }
  } catch (error) {
    showToast(error.message);
  }
});

window.addEventListener("resize", () => {
  if (dashboardState) renderAssets(dashboardState);
});

setDefaultTransactionTime();
loadDashboard().catch((error) => showToast(error.message));
