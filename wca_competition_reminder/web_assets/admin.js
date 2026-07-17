const COMPETITION_STATUS_LABELS = {
  baseline: "基线记录",
  ignored_no_minx: "已忽略",
  ignored_no_official_events: "无官方项目",
  ignored_cancelled: "已取消比赛",
  pending_details: "等待详情",
  pending_coordinates: "等待坐标",
  queued: "已完成处理",
};

const DELIVERY_STATUS_LABELS = {
  pending: "待投递",
  sending: "投递中",
  sent: "已发送",
  blocked: "已阻塞",
};

const VIEW_META = {
  overview: { index: "01", title: "运行概览" },
  subscribers: { index: "02", title: "订阅用户" },
  competitions: { index: "03", title: "比赛数据" },
  deliveries: { index: "04", title: "投递记录" },
};

const APPLICATION_BASE_PATH =
  document.querySelector('meta[name="application-base-path"]')?.content || "";

function applicationUrl(path) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${APPLICATION_BASE_PATH}${normalizedPath}`;
}

const appState = {
  view: "overview",
  snapshot: null,
  loading: false,
  refreshTimer: null,
};

const authView = document.querySelector("#auth-view");
const adminView = document.querySelector("#admin-view");
const loginForm = document.querySelector("#login-form");
const loginButton = document.querySelector("#login-button");
const loginMessage = document.querySelector("#login-message");
const usernameInput = document.querySelector("#username");
const passwordInput = document.querySelector("#password");
const showPasswordInput = document.querySelector("#show-password");
const refreshButton = document.querySelector("#refresh-button");
const logoutButton = document.querySelector("#logout-button");
const loadBanner = document.querySelector("#load-banner");
const loadMessage = document.querySelector("#load-message");

class ApiError extends Error {
  constructor(message, status, body = {}) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function requestJson(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(applicationUrl(path), {
    ...options,
    headers,
    credentials: "same-origin",
  });
  const text = await response.text();
  let body = {};
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      throw new ApiError("服务器返回了无法识别的数据", response.status);
    }
  }
  if (!response.ok) {
    throw new ApiError(body.message || `请求失败（${response.status}）`, response.status, body);
  }
  return body;
}

function setText(selector, value) {
  const element = document.querySelector(selector);
  if (element) element.textContent = String(value);
}

function createElement(tagName, className = "", text = null) {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  if (text !== null) element.textContent = String(text);
  return element;
}

function showAuth(message = "") {
  authView.hidden = false;
  adminView.hidden = true;
  loginMessage.textContent = message;
  appState.snapshot = null;
  if (appState.refreshTimer) {
    window.clearInterval(appState.refreshTimer);
    appState.refreshTimer = null;
  }
}

function showAdmin(username) {
  authView.hidden = true;
  adminView.hidden = false;
  setText("#admin-username", username || "admin");
  if (!appState.refreshTimer) {
    appState.refreshTimer = window.setInterval(loadSnapshot, 60_000);
  }
}

function setLoading(message) {
  appState.loading = true;
  loadMessage.textContent = message;
  loadBanner.classList.remove("is-idle", "is-error");
  refreshButton.classList.add("is-loading");
  refreshButton.disabled = true;
}

function clearLoading() {
  appState.loading = false;
  loadBanner.classList.add("is-idle");
  loadBanner.classList.remove("is-error");
  refreshButton.classList.remove("is-loading");
  refreshButton.disabled = false;
}

function showLoadError(message) {
  appState.loading = false;
  loadMessage.textContent = message;
  loadBanner.classList.remove("is-idle");
  loadBanner.classList.add("is-error");
  refreshButton.classList.remove("is-loading");
  refreshButton.disabled = false;
}

function setView(view) {
  if (!VIEW_META[view]) return;
  appState.view = view;
  document.querySelectorAll(".nav-item").forEach((button) => {
    const active = button.dataset.view === view;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll("[data-section]").forEach((section) => {
    section.hidden = section.dataset.section !== view;
  });
  setText("#view-index", VIEW_META[view].index);
  setText("#view-title", VIEW_META[view].title);
}

function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatDateRange(start, end) {
  if (!start) return "—";
  if (!end || start === end) return start;
  return `${start} — ${end}`;
}

function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value || 0));
}

function sumStatuses(counts, statuses) {
  return statuses.reduce((total, status) => total + Number(counts?.[status] || 0), 0);
}

function addTextCell(row, primary, secondary = null, className = "") {
  const cell = createElement("td", className);
  cell.append(createElement("span", "cell-primary", primary || "—"));
  if (secondary) cell.append(createElement("span", "cell-secondary", secondary));
  row.append(cell);
  return cell;
}

function addStatusCell(row, status, label) {
  const cell = createElement("td");
  const badge = createElement("span", "status-badge", label);
  badge.dataset.status = status;
  cell.append(badge);
  row.append(cell);
}

function renderEmptyRow(container, columnCount, message) {
  const row = createElement("tr", "empty-row");
  const cell = createElement("td", "", message);
  cell.colSpan = columnCount;
  row.append(cell);
  container.replaceChildren(row);
}

function renderOverview(snapshot) {
  const subscriberCounts = snapshot.counts?.subscribers || {};
  const competitionCounts = snapshot.counts?.competitions || {};
  const deliveryCounts = snapshot.counts?.deliveries || {};
  const queueCount = sumStatuses(deliveryCounts, ["pending", "sending"]);
  const pendingCompetitions = sumStatuses(competitionCounts, [
    "pending_details",
    "pending_coordinates",
  ]);
  const deliveryTotal = Number(deliveryCounts.total || 0);
  const sentTotal = Number(deliveryCounts.sent || 0);
  const successRate = deliveryTotal ? Math.round((sentTotal / deliveryTotal) * 100) : null;

  setText("#metric-subscribers", formatNumber(subscriberCounts.effective));
  setText(
    "#metric-subscriber-note",
    `网页活动 ${formatNumber(subscriberCounts.active)} · 配置 ${formatNumber(subscriberCounts.configured)}`,
  );
  setText("#metric-competitions", formatNumber(competitionCounts.total));
  setText("#metric-competition-note", `等待处理 ${formatNumber(pendingCompetitions)}`);
  setText("#metric-queue", formatNumber(queueCount));
  setText("#metric-queue-note", `累计投递 ${formatNumber(deliveryTotal)}`);
  setText("#metric-success-rate", successRate === null ? "—" : `${successRate}%`);
  document.querySelector("#success-rate-bar").style.width = `${successRate || 0}%`;
  setText("#metric-blocked", formatNumber(deliveryCounts.blocked));
  setText(
    "#metric-blocked-note",
    Number(deliveryCounts.blocked || 0) ? "需要检查投递错误" : "当前没有阻塞",
  );

  renderCheckpoints(snapshot.checkpoints || {});
  renderDistribution(deliveryCounts);
  renderIssues(snapshot);
}

function renderCheckpoints(checkpoints) {
  const definitions = [
    ["01", "基线初始化", checkpoints.baseline_completed_at],
    ["02", "增量扫描", checkpoints.incremental_checkpoint_at],
    ["03", "完整同步", checkpoints.last_full_success_at],
  ];
  const container = document.querySelector("#checkpoint-list");
  const items = definitions.map(([index, label, timestamp]) => {
    const item = createElement("div", "checkpoint-item");
    item.append(createElement("span", "checkpoint-index", index));
    const copy = createElement("div", "checkpoint-copy");
    copy.append(createElement("b", "", label));
    copy.append(createElement("small", "", formatDateTime(timestamp)));
    item.append(copy);
    const status = createElement(
      "span",
      `checkpoint-state${timestamp ? "" : " is-missing"}`,
      timestamp ? "已完成" : "未初始化",
    );
    item.append(status);
    return item;
  });
  container.replaceChildren(...items);
}

function renderDistribution(counts) {
  const definitions = [
    ["sent", "已发送"],
    ["pending", "待投递"],
    ["sending", "投递中"],
    ["blocked", "已阻塞"],
  ];
  const total = Math.max(1, Number(counts.total || 0));
  const container = document.querySelector("#delivery-distribution");
  const items = definitions.map(([status, label]) => {
    const count = Number(counts[status] || 0);
    const item = createElement("div", "distribution-item");
    item.dataset.status = status;
    item.append(createElement("span", "", label));
    const track = createElement("span", "distribution-track");
    const fill = createElement("i");
    fill.style.width = `${Math.round((count / total) * 100)}%`;
    track.append(fill);
    item.append(track);
    item.append(createElement("b", "", formatNumber(count)));
    return item;
  });
  container.replaceChildren(...items);
}

function renderIssues(snapshot) {
  const issues = [];
  (snapshot.competitions || []).forEach((competition) => {
    if (competition.last_error) {
      issues.push({
        source: "比赛",
        subject: competition.name || competition.id,
        detail: competition.id,
        status: competition.status,
        statusLabel: COMPETITION_STATUS_LABELS[competition.status] || competition.status,
        error: competition.last_error,
        time: competition.discovered_at,
      });
    }
  });
  (snapshot.deliveries || []).forEach((delivery) => {
    if (delivery.last_error || delivery.status === "blocked") {
      issues.push({
        source: "投递",
        subject: delivery.recipient_email,
        detail: delivery.competition_name || delivery.competition_id,
        status: delivery.status,
        statusLabel: DELIVERY_STATUS_LABELS[delivery.status] || delivery.status,
        error: delivery.last_error || "投递已阻塞",
        time: delivery.sent_at || delivery.created_at,
      });
    }
  });
  issues.sort((left, right) => String(right.time).localeCompare(String(left.time)));
  const visibleIssues = issues.slice(0, 10);
  setText("#issue-count", `${issues.length} ITEMS`);
  const container = document.querySelector("#issue-rows");
  if (!visibleIssues.length) {
    renderEmptyRow(container, 5, "暂无异常记录");
    return;
  }
  const rows = visibleIssues.map((issue) => {
    const row = createElement("tr");
    addTextCell(row, issue.source);
    addTextCell(row, issue.subject, issue.detail);
    addStatusCell(row, issue.status, issue.statusLabel);
    addTextCell(row, issue.error, null, "error-copy");
    addTextCell(row, formatDateTime(issue.time));
    return row;
  });
  container.replaceChildren(...rows);
}

function subscriberRecords(snapshot) {
  const webRecords = (snapshot.subscribers || []).map((record) => ({
    ...record,
    source: "web",
    effective: Boolean(record.active),
  }));
  const configRecords = (snapshot.configured_recipients || []).map((record) => ({
    ...record,
    active: Boolean(record.effective),
    source: "config",
    created_at: null,
    updated_at: null,
  }));
  return [...webRecords, ...configRecords];
}

function listSummary(values, emptyText) {
  if (values === null || values === undefined) return emptyText;
  if (!Array.isArray(values) || !values.length) return emptyText;
  if (values.length <= 3) return values.join("、");
  return `${values.slice(0, 3).join("、")} +${values.length - 3}`;
}

function renderSubscribers() {
  if (!appState.snapshot) return;
  const search = document.querySelector("#subscriber-search").value.trim().toLocaleLowerCase();
  const filter = document.querySelector("#subscriber-filter").value;
  const records = subscriberRecords(appState.snapshot).filter((record) => {
    const searchable = [record.name, record.email, ...(record.events || []), ...(record.countries || [])]
      .filter(Boolean)
      .join(" ")
      .toLocaleLowerCase();
    const matchesSearch = !search || searchable.includes(search);
    let matchesFilter = true;
    if (filter === "active") matchesFilter = Boolean(record.effective);
    if (filter === "inactive") matchesFilter = !record.effective;
    if (filter === "config") matchesFilter = record.source === "config";
    return matchesSearch && matchesFilter;
  });
  setText("#subscriber-result-count", `${records.length} 条`);
  const container = document.querySelector("#subscriber-rows");
  if (!records.length) {
    renderEmptyRow(container, 6, "没有匹配的订阅用户");
    return;
  }
  const rows = records.map((record) => {
    const row = createElement("tr");
    addTextCell(row, record.name || "未命名", record.email);

    const sourceCell = createElement("td");
    const source = createElement(
      "span",
      "source-badge",
      record.source === "config" ? "CONFIG" : "WEB",
    );
    source.dataset.source = record.source;
    sourceCell.append(source);
    row.append(sourceCell);

    const active = Boolean(record.effective);
    const statusLabel = active ? "活动中" : record.source === "config" ? "已覆盖" : "已取消";
    addStatusCell(row, active ? "active" : "inactive", statusLabel);

    const eventSummary = listSummary(record.events, "全部项目");
    const regions = [...(record.countries || []), ...(record.continents || [])];
    addTextCell(row, eventSummary, listSummary(regions, "全球"));

    const distance = record.max_distance_km ? `${formatNumber(record.max_distance_km)} km` : "不限";
    const coordinates =
      record.latitude !== null && record.latitude !== undefined
        ? `${Number(record.latitude).toFixed(3)}, ${Number(record.longitude).toFixed(3)}`
        : null;
    addTextCell(row, distance, coordinates);
    addTextCell(
      row,
      record.updated_at ? formatDateTime(record.updated_at) : "随配置加载",
      record.cancelled_at ? `取消于 ${formatDateTime(record.cancelled_at)}` : null,
    );
    return row;
  });
  container.replaceChildren(...rows);
}

function populateCompetitionFilter(competitions) {
  const select = document.querySelector("#competition-filter");
  const current = select.value;
  const statuses = [...new Set(competitions.map((competition) => competition.status))].sort();
  const options = [createElement("option", "", "全部状态")];
  options[0].value = "all";
  statuses.forEach((status) => {
    const option = createElement("option", "", COMPETITION_STATUS_LABELS[status] || status);
    option.value = status;
    options.push(option);
  });
  select.replaceChildren(...options);
  select.value = statuses.includes(current) ? current : "all";
}

function renderCompetitions() {
  if (!appState.snapshot) return;
  const search = document.querySelector("#competition-search").value.trim().toLocaleLowerCase();
  const filter = document.querySelector("#competition-filter").value;
  const records = (appState.snapshot.competitions || []).filter((competition) => {
    const searchable = [competition.id, competition.name, competition.city, competition.country_iso2]
      .filter(Boolean)
      .join(" ")
      .toLocaleLowerCase();
    return (!search || searchable.includes(search)) && (filter === "all" || competition.status === filter);
  });
  setText("#competition-result-count", `${records.length} 条`);
  const container = document.querySelector("#competition-rows");
  if (!records.length) {
    renderEmptyRow(container, 6, "没有匹配的比赛记录");
    return;
  }
  const rows = records.map((competition) => {
    const row = createElement("tr");
    addTextCell(row, competition.name || competition.id, competition.id);
    addTextCell(row, formatDateRange(competition.start_date, competition.end_date));
    addTextCell(row, competition.city || "—", competition.country_iso2 || null);
    addStatusCell(
      row,
      competition.status,
      COMPETITION_STATUS_LABELS[competition.status] || competition.status,
    );
    addTextCell(row, listSummary(competition.events, "—"));
    addTextCell(
      row,
      formatDateTime(competition.discovered_at),
      competition.last_error ||
        (competition.enrichment_attempts ? `详情尝试 ${competition.enrichment_attempts} 次` : null),
      competition.last_error ? "error-copy" : "",
    );
    return row;
  });
  container.replaceChildren(...rows);
}

function renderDeliveries() {
  if (!appState.snapshot) return;
  const search = document.querySelector("#delivery-search").value.trim().toLocaleLowerCase();
  const filter = document.querySelector("#delivery-filter").value;
  const records = (appState.snapshot.deliveries || []).filter((delivery) => {
    const searchable = [
      delivery.recipient_email,
      delivery.recipient_name,
      delivery.competition_id,
      delivery.competition_name,
      delivery.subject,
    ]
      .filter(Boolean)
      .join(" ")
      .toLocaleLowerCase();
    return (!search || searchable.includes(search)) && (filter === "all" || delivery.status === filter);
  });
  setText("#delivery-result-count", `${records.length} 条`);
  const container = document.querySelector("#delivery-rows");
  if (!records.length) {
    renderEmptyRow(container, 6, "没有匹配的投递记录");
    return;
  }
  const rows = records.map((delivery) => {
    const row = createElement("tr");
    addTextCell(row, delivery.recipient_name || "未命名", delivery.recipient_email);
    addTextCell(row, delivery.competition_name || delivery.competition_id, delivery.competition_id);
    addStatusCell(row, delivery.status, DELIVERY_STATUS_LABELS[delivery.status] || delivery.status);
    addTextCell(row, formatNumber(delivery.attempts), delivery.last_error || null, delivery.last_error ? "error-copy" : "");
    addTextCell(row, formatDateTime(delivery.created_at));
    const finalTime = delivery.sent_at || delivery.next_attempt_at;
    addTextCell(row, formatDateTime(finalTime), delivery.sent_at ? "发送完成" : "下次尝试");
    return row;
  });
  container.replaceChildren(...rows);
}

function renderSnapshot(snapshot) {
  appState.snapshot = snapshot;
  const subscriberCount = (snapshot.subscribers || []).length + (snapshot.configured_recipients || []).length;
  setText("#nav-subscriber-count", formatNumber(subscriberCount));
  setText("#nav-competition-count", formatNumber(snapshot.counts?.competitions?.total));
  setText("#nav-delivery-count", formatNumber(snapshot.counts?.deliveries?.total));
  setText("#last-updated", formatDateTime(snapshot.generated_at));
  setText("#timezone-label", `TIMEZONE ${snapshot.timezone || "—"}`);
  setText("#admin-username", snapshot.admin?.username || "admin");
  populateCompetitionFilter(snapshot.competitions || []);
  renderOverview(snapshot);
  renderSubscribers();
  renderCompetitions();
  renderDeliveries();
}

async function loadSnapshot() {
  if (appState.loading || adminView.hidden) return;
  setLoading("正在读取管理数据");
  try {
    const snapshot = await requestJson("/api/admin/snapshot");
    renderSnapshot(snapshot);
    clearLoading();
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      showAuth("会话已过期，请重新登录");
      return;
    }
    showLoadError(error instanceof Error ? error.message : "管理数据读取失败");
  }
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginMessage.textContent = "";
  if (!loginForm.reportValidity()) return;
  loginButton.disabled = true;
  try {
    const session = await requestJson("/api/admin/login", {
      method: "POST",
      body: JSON.stringify({
        username: usernameInput.value,
        password: passwordInput.value,
      }),
    });
    passwordInput.value = "";
    showAdmin(session.username);
    await loadSnapshot();
  } catch (error) {
    loginMessage.textContent = error instanceof Error ? error.message : "登录失败";
    passwordInput.select();
  } finally {
    loginButton.disabled = false;
  }
});

showPasswordInput.addEventListener("change", () => {
  passwordInput.type = showPasswordInput.checked ? "text" : "password";
});

refreshButton.addEventListener("click", loadSnapshot);

logoutButton.addEventListener("click", async () => {
  logoutButton.disabled = true;
  try {
    await requestJson("/api/admin/logout", { method: "POST", body: "{}" });
  } catch {
    // The local session is discarded even when the server is unavailable.
  } finally {
    logoutButton.disabled = false;
    showAuth();
    usernameInput.focus();
  }
});

document.querySelectorAll(".nav-item").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});

document.querySelector("#subscriber-search").addEventListener("input", renderSubscribers);
document.querySelector("#subscriber-filter").addEventListener("change", renderSubscribers);
document.querySelector("#competition-search").addEventListener("input", renderCompetitions);
document.querySelector("#competition-filter").addEventListener("change", renderCompetitions);
document.querySelector("#delivery-search").addEventListener("input", renderDeliveries);
document.querySelector("#delivery-filter").addEventListener("change", renderDeliveries);

async function initialize() {
  setView("overview");
  try {
    const session = await requestJson("/api/admin/session");
    showAdmin(session.username);
    await loadSnapshot();
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      showAuth();
      return;
    }
    showAuth(error instanceof Error ? error.message : "无法连接管理服务");
  }
}

initialize();
