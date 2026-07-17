const EVENT_LABELS = {
  "333": "三阶魔方",
  "222": "二阶魔方",
  "444": "四阶魔方",
  "555": "五阶魔方",
  "666": "六阶魔方",
  "777": "七阶魔方",
  "333bf": "三阶盲拧",
  "333fm": "三阶最少步",
  "333oh": "三阶单手",
  clock: "魔表",
  minx: "五魔方",
  pyram: "金字塔",
  skewb: "斜转魔方",
  sq1: "Square-1",
  "444bf": "四阶盲拧",
  "555bf": "五阶盲拧",
  "333mbf": "三阶多盲",
};

const FALLBACK_EVENT_IDS = Object.keys(EVENT_LABELS);
const STORAGE_KEY = "wca-reminder-email";
const APPLICATION_BASE_PATH =
  document.querySelector('meta[name="application-base-path"]')?.content || "";

function applicationUrl(path) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${APPLICATION_BASE_PATH}${normalizedPath}`;
}

const state = {
  mode: "register",
  subscriptionLoaded: false,
  loadingSubscription: false,
  options: {
    events: FALLBACK_EVENT_IDS,
    continents: [],
    countries: [],
  },
  selectedCountries: new Set(),
  toastTimer: null,
  verificationTimer: null,
  verificationEmail: null,
};

const form = document.querySelector("#subscription-form");
const emailInput = document.querySelector("#email");
const nameInput = document.querySelector("#name");
const latitudeInput = document.querySelector("#latitude");
const longitudeInput = document.querySelector("#longitude");
const maxDistanceInput = document.querySelector("#max-distance-km");
const verificationCodeInput = document.querySelector("#verification-code");
const notificationConsentInput = document.querySelector("#notification-consent");
const notificationConsentField = document.querySelector("#notification-consent-field");
const countrySearch = document.querySelector("#country-search");
const countryOptions = document.querySelector("#country-options");
const profileFields = document.querySelector("#profile-fields");
const verificationField = document.querySelector("#verification-field");
const preferences = document.querySelector("#preferences");
const loadedBanner = document.querySelector("#loaded-banner");
const sendCodeButton = document.querySelector("#send-code-button");
const resetButton = document.querySelector("#reset-button");
const submitButton = document.querySelector("#submit-button");
const submitLabel = document.querySelector("#submit-label");
const submitSymbol = document.querySelector("#submit-symbol");
const toast = document.querySelector("#toast");

class ApiError extends Error {
  constructor(message, status, body = {}) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

function setText(selector, value) {
  const element = document.querySelector(selector);
  if (element) element.textContent = value;
}

function showToast(message, isError = false) {
  if (state.toastTimer) window.clearTimeout(state.toastTimer);
  toast.textContent = message;
  toast.classList.toggle("is-error", isError);
  toast.classList.add("is-visible");
  state.toastTimer = window.setTimeout(() => toast.classList.remove("is-visible"), 4600);
}

function clearInvalidState() {
  [
    emailInput,
    nameInput,
    latitudeInput,
    longitudeInput,
    maxDistanceInput,
    verificationCodeInput,
    notificationConsentInput,
  ].forEach((input) => {
    input.removeAttribute("aria-invalid");
  });
}

function resetSelections() {
  document.querySelectorAll('input[type="checkbox"]').forEach((input) => {
    input.checked = false;
  });
  state.selectedCountries.clear();
  countrySearch.value = "";
  renderCountries();
}

function setProfileVisible(visible) {
  profileFields.classList.toggle("is-hidden", !visible);
  preferences.classList.toggle("is-hidden", !visible);
  nameInput.required = visible;
}

function resetModifyLookup() {
  state.subscriptionLoaded = false;
  emailInput.readOnly = false;
  setProfileVisible(false);
  loadedBanner.classList.add("is-hidden");
  submitLabel.textContent = "读取当前订阅";
  submitSymbol.textContent = "→";
  resetButton.textContent = "清空";
  setText("#form-description", "填写邮箱后会自动读取当前订阅，再在原设置上修改。");
}

function setMode(mode) {
  state.mode = mode;
  state.subscriptionLoaded = false;
  state.loadingSubscription = false;
  emailInput.readOnly = false;
  loadedBanner.classList.add("is-hidden");
  clearInvalidState();

  document.querySelectorAll(".mode-button").forEach((button) => {
    const active = button.dataset.mode === mode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });

  const copy = {
    register: {
      kicker: "NEW CHANNEL",
      title: "注册邮件提醒",
      description: "验证邮箱，设置你的比赛提醒范围。",
      submit: "建立提醒",
      symbol: "↗",
      emailHint: "该邮箱将作为订阅的唯一标识",
    },
    modify: {
      kicker: "EDIT CHANNEL",
      title: "修改提醒偏好",
      description: "填写邮箱后会自动读取当前订阅，再在原设置上修改。",
      submit: "读取当前订阅",
      symbol: "→",
      emailHint: "输入注册邮箱以载入现有设置",
    },
    cancel: {
      kicker: "CLOSE CHANNEL",
      title: "取消邮件提醒",
      description: "只需填写注册邮箱；取消后，排队通知也会停止。",
      submit: "取消订阅",
      symbol: "×",
      emailHint: "无需验证码或管理令牌",
    },
  }[mode];

  setText("#form-kicker", copy.kicker);
  setText("#form-title", copy.title);
  setText("#form-description", copy.description);
  setText("#email-hint", copy.emailHint);
  submitLabel.textContent = copy.submit;
  submitSymbol.textContent = copy.symbol;
  resetButton.textContent = "清空";
  submitButton.classList.toggle("is-danger", mode === "cancel");
  verificationField.classList.toggle("is-hidden", mode !== "register");
  verificationCodeInput.required = mode === "register";
  notificationConsentField.classList.toggle("is-hidden", mode !== "register");
  notificationConsentInput.required = mode === "register";
  setProfileVisible(mode === "register");
  if (mode === "cancel") preferences.classList.add("is-hidden");

  if (mode !== "register" && !emailInput.value) {
    emailInput.value = window.localStorage.getItem(STORAGE_KEY) || "";
  }
}

function makeChoice({ name, value, label, code = "" }) {
  const wrapper = document.createElement("label");
  wrapper.className = "choice";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.name = name;
  input.value = value;
  const mark = document.createElement("span");
  mark.className = "choice-mark";
  mark.textContent = "✓";
  const text = document.createElement("span");
  text.className = "choice-label";
  text.textContent = label;
  wrapper.append(input, mark, text);
  if (code) {
    const codeElement = document.createElement("span");
    codeElement.className = "choice-code";
    codeElement.textContent = code;
    wrapper.append(codeElement);
  }
  return wrapper;
}

function renderOptions() {
  const eventContainer = document.querySelector("#event-options");
  eventContainer.replaceChildren();
  state.options.events.forEach((event) => {
    const id = typeof event === "string" ? event : event.id;
    eventContainer.append(
      makeChoice({
        name: "events",
        value: id,
        label: EVENT_LABELS[id] || (typeof event === "object" ? event.name : id),
        code: id,
      }),
    );
  });

  const continentContainer = document.querySelector("#continent-options");
  continentContainer.replaceChildren();
  state.options.continents.forEach((continent) => {
    continentContainer.append(
      makeChoice({ name: "continents", value: continent, label: continent }),
    );
  });
  renderCountries();
}

function matchingCountries(query = countrySearch.value.trim().toLowerCase()) {
  return state.options.countries.filter((country) => {
    if (!query) return true;
    return `${country.name} ${country.iso2} ${country.continent}`.toLowerCase().includes(query);
  });
}

function updateCountryCount(visibleCount = matchingCountries().length) {
  const total = state.options.countries.length;
  if (!total) {
    setText("#country-count", "WCA 地区目录暂时不可用");
    return;
  }
  const count = state.selectedCountries.size ? state.selectedCountries.size : visibleCount;
  setText("#country-count", `${count} / ${total} 个 WCA 国家或地区`);
}

function renderCountries(query = countrySearch.value.trim().toLowerCase()) {
  countryOptions.replaceChildren();
  const countries = matchingCountries(query);
  updateCountryCount(countries.length);
  countries.forEach((country) => {
    const choice = makeChoice({
      name: "countries",
      value: country.name,
      label: country.name,
      code: country.iso2,
    });
    choice.querySelector("input").checked = state.selectedCountries.has(country.name);
    countryOptions.append(choice);
  });
  if (!countries.length) {
    const empty = document.createElement("span");
    empty.className = "loading-copy";
    empty.textContent = state.options.countries.length ? "没有匹配的地区" : "请稍后刷新重试";
    countryOptions.append(empty);
  }
}

async function loadOptions() {
  try {
    const options = await requestJson("/api/options", {
      headers: { Accept: "application/json" },
    });
    if (Array.isArray(options.events) && options.events.length) state.options.events = options.events;
    if (Array.isArray(options.continents) && options.continents.length) {
      state.options.continents = options.continents;
    }
    if (Array.isArray(options.countries)) state.options.countries = options.countries;
  } catch (_error) {
    // The fallback event list keeps registration usable while the WCA directory reloads.
  }
  renderOptions();
}

function selectedValues(name) {
  return [...document.querySelectorAll(`input[name="${name}"]:checked`)].map(
    (input) => input.value,
  );
}

function optionalNumber(input) {
  return input.value.trim() === "" ? null : Number(input.value);
}

function collectPayload() {
  const payload = { email: emailInput.value.trim() };
  if (state.mode === "cancel" || (state.mode === "modify" && !state.subscriptionLoaded)) {
    return payload;
  }
  payload.name = nameInput.value.trim();
  payload.latitude = optionalNumber(latitudeInput);
  payload.longitude = optionalNumber(longitudeInput);
  payload.max_distance_km = optionalNumber(maxDistanceInput);
  payload.events = selectedValues("events");
  payload.countries = [...state.selectedCountries];
  payload.continents = selectedValues("continents");
  if (state.mode === "register") {
    payload.verification_code = verificationCodeInput.value.trim();
    payload.notification_consent = notificationConsentInput.checked;
  }
  return payload;
}

function validateEmail() {
  emailInput.removeAttribute("aria-invalid");
  if (!emailInput.validity.valid || !emailInput.value.trim()) {
    emailInput.setAttribute("aria-invalid", "true");
    showToast("请先填写有效的邮箱地址。", true);
    emailInput.focus();
    return false;
  }
  return true;
}

function validatePayload(payload) {
  clearInvalidState();
  if (!validateEmail()) return false;
  if (state.mode === "cancel" || (state.mode === "modify" && !state.subscriptionLoaded)) {
    return true;
  }
  if (!payload.name) {
    nameInput.setAttribute("aria-invalid", "true");
    showToast("请填写邮件中的称呼。", true);
    nameInput.focus();
    return false;
  }

  const latitudeMissing = payload.latitude === null;
  const longitudeMissing = payload.longitude === null;
  if (latitudeMissing !== longitudeMissing) {
    latitudeInput.setAttribute("aria-invalid", "true");
    longitudeInput.setAttribute("aria-invalid", "true");
    showToast("纬度和经度需要同时填写或同时留空。", true);
    (latitudeMissing ? latitudeInput : longitudeInput).focus();
    return false;
  }
  if (!latitudeMissing && (!Number.isFinite(payload.latitude) || payload.latitude < -90 || payload.latitude > 90)) {
    latitudeInput.setAttribute("aria-invalid", "true");
    showToast("纬度必须在 -90 到 90 之间。", true);
    latitudeInput.focus();
    return false;
  }
  if (!longitudeMissing && (!Number.isFinite(payload.longitude) || payload.longitude < -180 || payload.longitude > 180)) {
    longitudeInput.setAttribute("aria-invalid", "true");
    showToast("经度必须在 -180 到 180 之间。", true);
    longitudeInput.focus();
    return false;
  }
  if (
    payload.max_distance_km !== null &&
    (!Number.isFinite(payload.max_distance_km) || payload.max_distance_km <= 0)
  ) {
    maxDistanceInput.setAttribute("aria-invalid", "true");
    showToast("最远直线距离必须大于 0 公里。", true);
    maxDistanceInput.focus();
    return false;
  }
  if (payload.max_distance_km !== null && latitudeMissing) {
    latitudeInput.setAttribute("aria-invalid", "true");
    longitudeInput.setAttribute("aria-invalid", "true");
    maxDistanceInput.setAttribute("aria-invalid", "true");
    showToast("设置最远距离时，请同时填写纬度和经度。", true);
    latitudeInput.focus();
    return false;
  }
  if (state.mode === "register" && !/^\d{6}$/.test(payload.verification_code)) {
    verificationCodeInput.setAttribute("aria-invalid", "true");
    showToast("请输入邮件中的 6 位验证码。", true);
    verificationCodeInput.focus();
    return false;
  }
  if (state.mode === "register" && payload.notification_consent !== true) {
    notificationConsentInput.setAttribute("aria-invalid", "true");
    showToast("注册前请勾选同意接收 WCA 比赛通知邮件。", true);
    notificationConsentInput.focus();
    return false;
  }
  return true;
}

async function requestJson(url, options = {}) {
  const response = await fetch(applicationUrl(url), options);
  let body = {};
  try {
    body = await response.json();
  } catch (_error) {
    body = {};
  }
  if (!response.ok) {
    throw new ApiError(body.message || "服务暂时不可用，请稍后重试。", response.status, body);
  }
  return body;
}

async function requestSubscription(method, payload) {
  return requestJson("/api/subscriptions", {
    method,
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload),
  });
}

function populateSubscription(subscription) {
  emailInput.value = subscription.email || "";
  nameInput.value = subscription.name || "";
  latitudeInput.value = subscription.latitude ?? "";
  longitudeInput.value = subscription.longitude ?? "";
  maxDistanceInput.value = subscription.max_distance_km ?? "";
  state.selectedCountries = new Set(subscription.countries || []);
  countrySearch.value = "";
  document.querySelectorAll('input[name="events"]').forEach((input) => {
    input.checked = Array.isArray(subscription.events) && subscription.events.includes(input.value);
  });
  document.querySelectorAll('input[name="continents"]').forEach((input) => {
    input.checked =
      Array.isArray(subscription.continents) && subscription.continents.includes(input.value);
  });
  renderCountries();
}

function showLoadedSubscription(subscription) {
  populateSubscription(subscription);
  state.subscriptionLoaded = true;
  emailInput.readOnly = true;
  setProfileVisible(true);
  loadedBanner.classList.remove("is-hidden");
  const updatedAt = new Date(subscription.updated_at);
  setText(
    "#loaded-updated-at",
    Number.isNaN(updatedAt.getTime())
      ? ""
      : `更新于 ${new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(updatedAt)}`,
  );
  setText("#form-description", "当前设置已载入，修改后保存即可用于后续比赛。");
  submitLabel.textContent = "保存修改";
  submitSymbol.textContent = "✓";
  resetButton.textContent = "重新查询";
}

async function loadSubscriptionForModify() {
  if (state.mode !== "modify" || state.subscriptionLoaded || state.loadingSubscription) return;
  if (!validateEmail()) return;
  state.loadingSubscription = true;
  submitButton.disabled = true;
  submitButton.setAttribute("aria-busy", "true");
  submitLabel.textContent = "正在读取";
  try {
    const query = new URLSearchParams({ email: emailInput.value.trim() });
    const result = await requestJson(`/api/subscriptions?${query.toString()}`, {
      headers: { Accept: "application/json" },
    });
    showLoadedSubscription(result.subscription);
    window.localStorage.setItem(STORAGE_KEY, result.subscription.email);
    showToast("已载入当前订阅设置。", false);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      showToast("该邮箱还未注册，已切换到注册界面。", true);
      setMode("register");
      nameInput.focus();
    } else {
      showToast(error instanceof Error ? error.message : "读取订阅失败，请稍后重试。", true);
      submitLabel.textContent = "读取当前订阅";
    }
  } finally {
    state.loadingSubscription = false;
    submitButton.disabled = false;
    submitButton.removeAttribute("aria-busy");
  }
}

function stopVerificationCooldown() {
  if (state.verificationTimer) window.clearInterval(state.verificationTimer);
  state.verificationTimer = null;
  sendCodeButton.disabled = false;
  sendCodeButton.textContent = "获取验证码";
}

function startVerificationCooldown(seconds = 60) {
  if (state.verificationTimer) window.clearInterval(state.verificationTimer);
  const deadline = Date.now() + seconds * 1000;
  const update = () => {
    const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
    if (remaining === 0) {
      stopVerificationCooldown();
      return;
    }
    sendCodeButton.disabled = true;
    sendCodeButton.textContent = `${remaining}s 后重试`;
  };
  update();
  state.verificationTimer = window.setInterval(update, 250);
}

async function sendVerificationCode() {
  if (!validateEmail()) return;
  const email = emailInput.value.trim().toLowerCase();
  startVerificationCooldown(60);
  try {
    await requestJson("/api/verification-codes", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ email }),
    });
    state.verificationEmail = email;
    verificationCodeInput.focus();
    showToast("验证码已发送，请在 5 分钟内完成注册。", false);
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 429) stopVerificationCooldown();
    if (error instanceof ApiError && error.status === 409) {
      showToast("该邮箱已经订阅，正在载入当前设置。", true);
      setMode("modify");
      await loadSubscriptionForModify();
      return;
    }
    showToast(error instanceof Error ? error.message : "验证码发送失败，请稍后重试。", true);
  }
}

async function submitForm(event) {
  event.preventDefault();
  if (state.mode === "modify" && !state.subscriptionLoaded) {
    await loadSubscriptionForModify();
    return;
  }
  const payload = collectPayload();
  if (!validatePayload(payload)) return;
  submitButton.disabled = true;
  submitButton.setAttribute("aria-busy", "true");
  try {
    const method = state.mode === "register" ? "POST" : state.mode === "modify" ? "PUT" : "DELETE";
    const result = await requestSubscription(method, payload);
    if (state.mode === "register") {
      window.localStorage.setItem(STORAGE_KEY, result.subscription.email);
      verificationCodeInput.value = "";
      stopVerificationCooldown();
      setMode("modify");
      showLoadedSubscription(result.subscription);
      showToast("订阅已建立，当前设置已载入。", false);
    } else if (state.mode === "modify") {
      showLoadedSubscription(result.subscription);
      showToast("提醒设置已更新，将用于后续比赛。", false);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
      form.reset();
      resetSelections();
      setMode("register");
      showToast("订阅已取消，排队中的通知不会再发送。", false);
    }
    refreshHealth();
  } catch (error) {
    showToast(error instanceof Error ? error.message : "操作失败，请稍后重试。", true);
  } finally {
    submitButton.disabled = false;
    submitButton.removeAttribute("aria-busy");
  }
}

function resetForm() {
  if (state.mode === "modify" && state.subscriptionLoaded) {
    const email = emailInput.value;
    form.reset();
    resetSelections();
    emailInput.value = email;
    resetModifyLookup();
    emailInput.focus();
    return;
  }
  form.reset();
  resetSelections();
  clearInvalidState();
  state.verificationEmail = null;
  if (state.mode === "modify") resetModifyLookup();
  emailInput.focus();
}

async function refreshHealth() {
  try {
    const result = await requestJson("/api/health", {
      headers: { Accept: "application/json" },
    });
    setText("#subscriber-count", String(result.active_subscribers ?? "—"));
  } catch (_error) {
    setText("#subscriber-count", "—");
  }
}

function updateClock() {
  const now = new Date();
  setText(
    "#local-clock",
    new Intl.DateTimeFormat("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
      timeZone: "Asia/Shanghai",
    }).format(now),
  );
}

function bindEvents() {
  document.querySelectorAll(".mode-button").forEach((button) => {
    button.addEventListener("click", () => setMode(button.dataset.mode));
  });
  form.addEventListener("submit", submitForm);
  resetButton.addEventListener("click", resetForm);
  sendCodeButton.addEventListener("click", sendVerificationCode);
  emailInput.addEventListener("change", () => {
    if (state.mode === "modify" && !state.subscriptionLoaded) {
      void loadSubscriptionForModify();
    }
    if (
      state.mode === "register" &&
      state.verificationEmail &&
      emailInput.value.trim().toLowerCase() !== state.verificationEmail
    ) {
      verificationCodeInput.value = "";
    }
  });
  countrySearch.addEventListener("input", () => renderCountries());
  countryOptions.addEventListener("change", (event) => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement) || input.name !== "countries") return;
    if (input.checked) state.selectedCountries.add(input.value);
    else state.selectedCountries.delete(input.value);
    updateCountryCount();
  });
}

bindEvents();
setMode("register");
emailInput.value = window.localStorage.getItem(STORAGE_KEY) || "";
updateClock();
window.setInterval(updateClock, 1000);

async function init() {
  await loadOptions();
  refreshHealth();
}

init();
