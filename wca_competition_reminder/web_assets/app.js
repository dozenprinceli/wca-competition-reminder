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

const EVENT_LABELS_EN = {
  "333": "3x3 Cube",
  "222": "2x2 Cube",
  "444": "4x4 Cube",
  "555": "5x5 Cube",
  "666": "6x6 Cube",
  "777": "7x7 Cube",
  "333bf": "3x3 Blindfolded",
  "333fm": "3x3 Fewest Moves",
  "333oh": "3x3 One-Handed",
  clock: "Clock",
  minx: "Megaminx",
  pyram: "Pyraminx",
  skewb: "Skewb",
  sq1: "Square-1",
  "444bf": "4x4 Blindfolded",
  "555bf": "5x5 Blindfolded",
  "333mbf": "3x3 Multi-Blind",
};

const TRANSLATIONS = {
  zh: {
    pageTitle: "WCA 比赛公示提醒 | 邮件订阅",
    subscriptionOperations: "订阅操作",
    brandName: "比赛公示提醒",
    emailChannelOnline: "邮件通道在线",
    subscriptionMode: "订阅模式",
    modeRegisterLabel: "注册公示提醒",
    modeModifyLabel: "修改偏好",
    modeCancelLabel: "取消订阅",
    railFootCopy: "这里注册的是 WCA 比赛公示提醒服务，不是比赛报名。新比赛公示后，提醒会发送到你的邮箱。",
    heroLine1: "订阅 WCA 比赛",
    heroLine2: "公示提醒邮件。",
    currentTime: "当前时间",
    subscriptionStatus: "订阅状态",
    languageLabel: "语言",
    languageSwitchLabel: "语言切换",
    languageZh: "中文",
    languageEn: "EN",
    switchToChinese: "切换到中文",
    switchToEnglish: "切换到英文",
    emailLabel: "邮箱地址",
    nameLabel: "称呼",
    namePlaceholder: "例如：Alex",
    latitudeLabel: "纬度",
    latitudeHint: "可选，需与经度同时填写",
    longitudeLabel: "经度",
    longitudeHint: "留空时邮件中的距离显示为 -",
    distanceLabel: "最远直线距离（km）",
    distancePlaceholder: "例如：300",
    distanceHint: "可选；设置后经纬度必填",
    verificationLabel: "邮箱验证码",
    verificationPlaceholder: "6 位验证码",
    verificationHint: "验证码 5 分钟内有效",
    loadedSubscription: "当前订阅已载入",
    eventsSection: "关注项目",
    eventsSectionNote: "不选 = 全部项目",
    eventsLegend: "选择 WCA 项目",
    loadingEvents: "正在载入项目列表…",
    regionsSection: "地区筛选",
    regionsSectionNote: "已设置的筛选条件同时生效",
    countryLabel: "国家 / 地区",
    countryPlaceholder: "搜索 WCA 国家或地区",
    countryOptionsLabel: "WCA 国家和地区",
    loadingCountries: "正在从 WCA 载入目录…",
    continentLabel: "大洲",
    loadingContinents: "正在载入…",
    continentHint: "不选表示不限制大洲",
    consent: "我同意接收 WCA 比赛公示提醒邮件",
    activeChannels: "个活动订阅通道",
    healthFootnote: "服务每分钟检查一次 WCA 新公示比赛。",
    logicEventTitle: "项目命中",
    logicEventCopy: "只看你选中的 WCA 项目",
    logicRegionTitle: "地区命中",
    logicRegionCopy: "比赛所在国家/地区或大洲匹配",
    logicDistanceTitle: "距离命中",
    logicDistanceCopy: "可选，仅提醒设定半径内比赛",
    logicDeliveryTitle: "邮件送达",
    logicDeliveryCopy: "自动重试临时投递失败",
    registerKicker: "NEW CHANNEL",
    registerTitle: "注册比赛公示提醒",
    registerDescription: "这里注册的是提醒服务，不是比赛报名。WCA 公示符合你筛选条件的新比赛后，我们会发送邮件提醒。",
    registerSubmit: "订阅公示提醒",
    registerEmailHint: "用于接收比赛公示提醒，也是订阅的唯一标识",
    modifyKicker: "EDIT CHANNEL",
    modifyTitle: "修改公示提醒偏好",
    modifyDescription: "填写邮箱后会自动读取当前订阅，再在原设置上修改。",
    modifySubmit: "读取当前订阅",
    modifyEmailHint: "输入注册邮箱以载入现有设置",
    cancelKicker: "CLOSE CHANNEL",
    cancelTitle: "取消比赛公示提醒",
    cancelDescription: "只需填写注册邮箱；取消后，排队通知也会停止。",
    cancelSubmit: "取消订阅",
    cancelEmailHint: "无需验证码或管理令牌",
    reset: "清空",
    resetLookup: "重新查询",
    saveChanges: "保存修改",
    loadingSubscription: "正在读取",
    sendCode: "获取验证码",
    cooldown: "{{seconds}}s 后重试",
    countryDirectoryUnavailable: "WCA 地区目录暂时不可用",
    countryCount: "{{count}} / {{total}} 个 WCA 国家或地区",
    noCountryMatch: "没有匹配的地区",
    retryLater: "请稍后刷新重试",
    updatedAt: "更新于 {{value}}",
    loadedDescription: "当前设置已载入，修改后保存即可用于后续比赛。",
    invalidEmail: "请先填写有效的邮箱地址。",
    missingName: "请填写邮件中的称呼。",
    coordinatesTogether: "纬度和经度需要同时填写或同时留空。",
    latitudeRange: "纬度必须在 -90 到 90 之间。",
    longitudeRange: "经度必须在 -180 到 180 之间。",
    distancePositive: "最远直线距离必须大于 0 公里。",
    distanceNeedsCoordinates: "设置最远距离时，请同时填写纬度和经度。",
    verificationRequired: "请输入邮件中的 6 位验证码。",
    consentRequired: "注册前请勾选同意接收 WCA 比赛公示提醒邮件。",
    serviceUnavailable: "服务暂时不可用，请稍后重试。",
    loadedToast: "已载入当前订阅设置。",
    missingSubscription: "该邮箱还未注册，已切换到注册界面。",
    readFailure: "读取订阅失败，请稍后重试。",
    codeSent: "验证码已发送，请在 5 分钟内完成注册。",
    alreadySubscribedLoading: "该邮箱已经订阅，正在载入当前设置。",
    codeFailure: "验证码发送失败，请稍后重试。",
    registrationSuccess: "订阅已建立，当前设置已载入。",
    updateSuccess: "提醒设置已更新，将用于后续比赛。",
    cancelSuccess: "订阅已取消，排队中的通知不会再发送。",
    operationFailure: "操作失败，请稍后重试。",
    apiInvalidRequest: "请求内容无效，请检查后重试。",
    apiAlreadySubscribed: "该邮箱已经订阅。",
    apiNotFound: "找不到对应的订阅。",
    apiRateLimited: "请求过于频繁，请在 {{seconds}} 秒后重试。",
    apiEmailUnavailable: "验证码邮件暂时无法发送，请稍后重试。",
    apiGeneric: "请求失败，请稍后重试。",
  },
  en: {
    pageTitle: "WCA Competition Announcement Alerts | Email Subscription",
    subscriptionOperations: "Subscription controls",
    brandName: "Announcement Alerts",
    emailChannelOnline: "Email channel online",
    subscriptionMode: "Subscription mode",
    modeRegisterLabel: "Subscribe",
    modeModifyLabel: "Edit preferences",
    modeCancelLabel: "Unsubscribe",
    railFootCopy: "This registers for WCA competition announcement alerts, not a competition entry. We email you after a new competition is announced.",
    heroLine1: "Get WCA competition",
    heroLine2: "announcement alerts.",
    currentTime: "Local time",
    subscriptionStatus: "Subscription status",
    languageLabel: "Language",
    languageSwitchLabel: "Language switcher",
    languageZh: "ZH",
    languageEn: "EN",
    switchToChinese: "Switch to Chinese",
    switchToEnglish: "Switch to English",
    emailLabel: "Email address",
    nameLabel: "Name",
    namePlaceholder: "e.g. Alex",
    latitudeLabel: "Latitude",
    latitudeHint: "Optional; enter together with longitude",
    longitudeLabel: "Longitude",
    longitudeHint: "Leave blank to show - for distance in emails",
    distanceLabel: "Max straight-line distance (km)",
    distancePlaceholder: "e.g. 300",
    distanceHint: "Optional; latitude and longitude are required",
    verificationLabel: "Email verification code",
    verificationPlaceholder: "6-digit code",
    verificationHint: "Code valid for 5 minutes",
    loadedSubscription: "Current subscription loaded",
    eventsSection: "Events",
    eventsSectionNote: "None selected = all events",
    eventsLegend: "Choose WCA events",
    loadingEvents: "Loading event list…",
    regionsSection: "Region filters",
    regionsSectionNote: "All selected filters apply together",
    countryLabel: "Country / region",
    countryPlaceholder: "Search WCA countries or regions",
    countryOptionsLabel: "WCA countries and regions",
    loadingCountries: "Loading directory from WCA…",
    continentLabel: "Continent",
    loadingContinents: "Loading…",
    continentHint: "Leave blank for all continents",
    consent: "I agree to receive WCA competition announcement alert emails",
    activeChannels: "active subscription channels",
    healthFootnote: "The service checks for newly announced WCA competitions every minute.",
    logicEventTitle: "Event match",
    logicEventCopy: "Only the WCA events you selected",
    logicRegionTitle: "Region match",
    logicRegionCopy: "Match the competition's country, region, or continent",
    logicDistanceTitle: "Distance match",
    logicDistanceCopy: "Optional; only notify within your radius",
    logicDeliveryTitle: "Email delivery",
    logicDeliveryCopy: "Temporary delivery failures are retried automatically",
    registerKicker: "NEW CHANNEL",
    registerTitle: "Subscribe to announcement alerts",
    registerDescription: "This signs you up for alerts, not a competition. When WCA announces a new competition matching your filters, we'll notify you by email.",
    registerSubmit: "Subscribe to alerts",
    registerEmailHint: "Used for announcement alerts and as your unique subscription key",
    modifyKicker: "EDIT CHANNEL",
    modifyTitle: "Edit announcement alert preferences",
    modifyDescription: "Enter your email to load the current subscription, then edit its settings.",
    modifySubmit: "Load subscription",
    modifyEmailHint: "Use the email address you registered with",
    cancelKicker: "CLOSE CHANNEL",
    cancelTitle: "Cancel announcement alerts",
    cancelDescription: "Enter your registered email; queued notifications will stop after cancellation.",
    cancelSubmit: "Cancel subscription",
    cancelEmailHint: "No verification code or admin token required",
    reset: "Clear",
    resetLookup: "Search again",
    saveChanges: "Save changes",
    loadingSubscription: "Loading",
    sendCode: "Send code",
    cooldown: "Retry in {{seconds}}s",
    countryDirectoryUnavailable: "WCA region directory is temporarily unavailable",
    countryCount: "{{count}} / {{total}} WCA countries or regions",
    noCountryMatch: "No matching regions",
    retryLater: "Refresh and try again later",
    updatedAt: "Updated {{value}}",
    loadedDescription: "Current settings are loaded; save your changes for future competitions.",
    invalidEmail: "Enter a valid email address first.",
    missingName: "Enter the name used in your emails.",
    coordinatesTogether: "Enter latitude and longitude together, or leave both blank.",
    latitudeRange: "Latitude must be between -90 and 90.",
    longitudeRange: "Longitude must be between -180 and 180.",
    distancePositive: "The maximum distance must be greater than 0 km.",
    distanceNeedsCoordinates: "Enter latitude and longitude when setting a maximum distance.",
    verificationRequired: "Enter the 6-digit code from your email.",
    consentRequired: "Agree to receive WCA competition announcement alert emails before subscribing.",
    serviceUnavailable: "The service is temporarily unavailable. Please try again later.",
    loadedToast: "Current subscription settings loaded.",
    missingSubscription: "That email is not registered; switching to the subscribe view.",
    readFailure: "Could not load the subscription. Please try again later.",
    codeSent: "Verification code sent. Complete registration within 5 minutes.",
    alreadySubscribedLoading: "That email is already subscribed; loading its current settings.",
    codeFailure: "Could not send the verification code. Please try again later.",
    registrationSuccess: "Subscription created; current settings are loaded.",
    updateSuccess: "Reminder settings updated for future competitions.",
    cancelSuccess: "Subscription cancelled; queued notifications will not be sent.",
    operationFailure: "The operation failed. Please try again later.",
    apiInvalidRequest: "The request is invalid. Check the details and try again.",
    apiAlreadySubscribed: "This email is already subscribed.",
    apiNotFound: "The requested subscription could not be found.",
    apiRateLimited: "Too many requests. Try again in {{seconds}} seconds.",
    apiEmailUnavailable: "Verification email delivery is temporarily unavailable.",
    apiGeneric: "The request failed. Please try again later.",
  },
};

const FALLBACK_EVENT_IDS = Object.keys(EVENT_LABELS);
const STORAGE_KEY = "wca-reminder-email";
const LANGUAGE_STORAGE_KEY = "wca-reminder-language";
const CHINESE_REGION_CODES = new Set(["CN", "HK", "MO", "TW"]);
const CHINESE_REGION_TIME_ZONES = new Set([
  "Asia/Shanghai",
  "Asia/Chongqing",
  "Asia/Chungking",
  "Asia/Harbin",
  "Asia/Urumqi",
  "Asia/Hong_Kong",
  "Asia/Macau",
  "Asia/Macao",
  "Asia/Taipei",
]);
const APPLICATION_BASE_PATH =
  document.querySelector('meta[name="application-base-path"]')?.content || "";

function applicationUrl(path) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${APPLICATION_BASE_PATH}${normalizedPath}`;
}

function normalizeLanguage(value) {
  return value === "zh" || value === "en" ? value : null;
}

function browserRegionLanguage() {
  const locale = navigator.languages?.[0] || navigator.language || "";
  let region = "";
  try {
    const parsedLocale = new Intl.Locale(String(locale).replaceAll("_", "-"));
    region = parsedLocale.region || parsedLocale.maximize().region || "";
  } catch (_error) {
    region = String(locale).match(/(?:^|-)(CN|HK|MO|TW)(?:-|$)/i)?.[1] || "";
  }
  if (CHINESE_REGION_CODES.has(region.toUpperCase())) return "zh";

  try {
    const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (CHINESE_REGION_TIME_ZONES.has(timeZone)) return "zh";
  } catch (_error) {
    // Fall through to English when browser region information is unavailable.
  }
  return "en";
}

function initialLanguage() {
  const requestedLanguage = normalizeLanguage(
    new URLSearchParams(window.location.search).get("lang"),
  );
  if (requestedLanguage) return requestedLanguage;

  try {
    const storedLanguage = normalizeLanguage(window.localStorage.getItem(LANGUAGE_STORAGE_KEY));
    if (storedLanguage) return storedLanguage;
  } catch (_error) {
    // Continue with browser region detection when storage is unavailable.
  }
  return browserRegionLanguage();
}

const state = {
  language: initialLanguage(),
  mode: "register",
  subscriptionLoaded: false,
  loadingSubscription: false,
  options: {
    events: FALLBACK_EVENT_IDS,
    continents: [],
    countries: [],
  },
  optionsLoaded: false,
  selectedCountries: new Set(),
  toastTimer: null,
  toastMessageFactory: null,
  verificationTimer: null,
  verificationDeadline: 0,
  verificationEmail: null,
  loadedSubscription: null,
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
const languageButtons = document.querySelectorAll(".language-button");

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

function t(key, variables = {}) {
  const languageCopy = TRANSLATIONS[state.language] || TRANSLATIONS.zh;
  const template = languageCopy[key] ?? TRANSLATIONS.zh[key] ?? key;
  return String(template).replace(/\{\{(\w+)\}\}/g, (_match, name) => {
    return variables[name] === undefined ? `{{${name}}}` : String(variables[name]);
  });
}

function persistLanguage(language) {
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch (_error) {
    // Language selection still applies for the current page when storage is unavailable.
  }
}

function replaceLanguageQuery(language) {
  const url = new URL(window.location.href);
  url.searchParams.set("lang", language);
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}

function formatUpdatedAt(value) {
  const updatedAt = new Date(value);
  if (Number.isNaN(updatedAt.getTime())) return "";
  const locale = state.language === "en" ? "en-US" : "zh-CN";
  return t("updatedAt", {
    value: new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(
      updatedAt,
    ),
  });
}

function updateVerificationButton() {
  if (state.verificationDeadline > Date.now()) {
    const remaining = Math.max(1, Math.ceil((state.verificationDeadline - Date.now()) / 1000));
    sendCodeButton.disabled = true;
    sendCodeButton.textContent = t("cooldown", { seconds: remaining });
    return;
  }
  state.verificationDeadline = 0;
  sendCodeButton.disabled = false;
  sendCodeButton.textContent = t("sendCode");
}

function applyModeCopy() {
  const modeCopy = {
    register: {
      kicker: "registerKicker",
      title: "registerTitle",
      description: "registerDescription",
      submit: "registerSubmit",
      symbol: "↗",
      emailHint: "registerEmailHint",
    },
    modify: {
      kicker: "modifyKicker",
      title: "modifyTitle",
      description: "modifyDescription",
      submit: "modifySubmit",
      symbol: "→",
      emailHint: "modifyEmailHint",
    },
    cancel: {
      kicker: "cancelKicker",
      title: "cancelTitle",
      description: "cancelDescription",
      submit: "cancelSubmit",
      symbol: "×",
      emailHint: "cancelEmailHint",
    },
  }[state.mode];
  setText("#form-kicker", t(modeCopy.kicker));
  setText("#form-title", t(modeCopy.title));
  setText("#form-description", t(modeCopy.description));
  setText("#email-hint", t(modeCopy.emailHint));
  submitLabel.textContent = t(modeCopy.submit);
  submitSymbol.textContent = modeCopy.symbol;
  resetButton.textContent = t("reset");
  sendCodeButton.textContent = t("sendCode");
  if (state.subscriptionLoaded && state.mode === "modify") {
    setText("#form-description", t("loadedDescription"));
    submitLabel.textContent = t("saveChanges");
    resetButton.textContent = t("resetLookup");
    if (state.loadedSubscription) {
      setText("#loaded-updated-at", formatUpdatedAt(state.loadedSubscription.updated_at));
    }
  }
  if (state.loadingSubscription) submitLabel.textContent = t("loadingSubscription");
  updateVerificationButton();
}

function applyLanguage(language, { persist = true } = {}) {
  state.language = language === "en" ? "en" : "zh";
  if (persist) {
    persistLanguage(state.language);
    replaceLanguageQuery(state.language);
  }
  document.documentElement.lang = state.language === "en" ? "en" : "zh-CN";
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    element.textContent = t(element.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((element) => {
    element.setAttribute("placeholder", t(element.dataset.i18nPlaceholder));
  });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((element) => {
    element.setAttribute("aria-label", t(element.dataset.i18nAriaLabel));
  });
  document.title = t("pageTitle");
  languageButtons.forEach((button) => {
    const active = button.dataset.language === state.language;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  if (toast.classList.contains("is-visible") && state.toastMessageFactory) {
    toast.textContent = state.toastMessageFactory();
  }
  applyModeCopy();
  renderOptions();
  updateClock();
}

function showToast(message, isError = false, messageFactory = null) {
  if (state.toastTimer) window.clearTimeout(state.toastTimer);
  state.toastMessageFactory = messageFactory;
  toast.textContent = message;
  toast.classList.toggle("is-error", isError);
  toast.classList.add("is-visible");
  state.toastTimer = window.setTimeout(() => {
    toast.classList.remove("is-visible");
    state.toastMessageFactory = null;
  }, 4600);
}

function showTranslationToast(key, isError = false, variables = {}) {
  const messageFactory = () => t(key, variables);
  showToast(messageFactory(), isError, messageFactory);
}

function showLocalizedToast(error, fallbackKey = "operationFailure") {
  const messageFactory = () => localizedErrorMessage(error, fallbackKey);
  showToast(messageFactory(), true, messageFactory);
}

function localizedErrorMessage(error, fallbackKey = "operationFailure") {
  if (!(error instanceof ApiError)) {
    return error instanceof Error && error.message ? error.message : t(fallbackKey);
  }
  if (state.language === "zh" && error.message) return error.message;
  const code = error.body?.error;
  if (code === "rate_limited") {
    return t("apiRateLimited", {
      seconds: error.body?.retry_after_seconds || 60,
    });
  }
  const errorKeys = {
    invalid_request: "apiInvalidRequest",
    already_subscribed: "apiAlreadySubscribed",
    not_found: "apiNotFound",
    email_unavailable: "apiEmailUnavailable",
    unauthorized: "apiGeneric",
  };
  return t(errorKeys[code] || "apiGeneric");
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
  state.loadedSubscription = null;
  emailInput.readOnly = false;
  setProfileVisible(false);
  loadedBanner.classList.add("is-hidden");
  applyModeCopy();
}

function setMode(mode) {
  state.mode = mode;
  state.subscriptionLoaded = false;
  state.loadedSubscription = null;
  state.loadingSubscription = false;
  emailInput.readOnly = false;
  loadedBanner.classList.add("is-hidden");
  clearInvalidState();

  document.querySelectorAll(".mode-button").forEach((button) => {
    const active = button.dataset.mode === mode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });

  applyModeCopy();
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
  const selectedEvents = new Set(selectedValues("events"));
  const selectedContinents = new Set(selectedValues("continents"));
  const eventContainer = document.querySelector("#event-options");
  eventContainer.replaceChildren();
  state.options.events.forEach((event) => {
    const id = typeof event === "string" ? event : event.id;
    const choice = makeChoice({
      name: "events",
      value: id,
      label:
        (state.language === "en" ? EVENT_LABELS_EN[id] : EVENT_LABELS[id]) ||
        (state.language === "en" ? id : typeof event === "object" ? event.name : id),
      code: id,
    });
    choice.querySelector("input").checked = selectedEvents.has(id);
    eventContainer.append(choice);
  });

  const continentContainer = document.querySelector("#continent-options");
  continentContainer.replaceChildren();
  state.options.continents.forEach((continent) => {
    const choice = makeChoice({ name: "continents", value: continent, label: continent });
    choice.querySelector("input").checked = selectedContinents.has(continent);
    continentContainer.append(choice);
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
    setText("#country-count", t(state.optionsLoaded ? "countryDirectoryUnavailable" : "loadingCountries"));
    return;
  }
  const count = state.selectedCountries.size ? state.selectedCountries.size : visibleCount;
  setText("#country-count", t("countryCount", { count, total }));
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
    empty.textContent = state.options.countries.length ? t("noCountryMatch") : t("retryLater");
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
  state.optionsLoaded = true;
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
    showTranslationToast("invalidEmail", true);
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
    showTranslationToast("missingName", true);
    nameInput.focus();
    return false;
  }

  const latitudeMissing = payload.latitude === null;
  const longitudeMissing = payload.longitude === null;
  if (latitudeMissing !== longitudeMissing) {
    latitudeInput.setAttribute("aria-invalid", "true");
    longitudeInput.setAttribute("aria-invalid", "true");
    showTranslationToast("coordinatesTogether", true);
    (latitudeMissing ? latitudeInput : longitudeInput).focus();
    return false;
  }
  if (!latitudeMissing && (!Number.isFinite(payload.latitude) || payload.latitude < -90 || payload.latitude > 90)) {
    latitudeInput.setAttribute("aria-invalid", "true");
    showTranslationToast("latitudeRange", true);
    latitudeInput.focus();
    return false;
  }
  if (!longitudeMissing && (!Number.isFinite(payload.longitude) || payload.longitude < -180 || payload.longitude > 180)) {
    longitudeInput.setAttribute("aria-invalid", "true");
    showTranslationToast("longitudeRange", true);
    longitudeInput.focus();
    return false;
  }
  if (
    payload.max_distance_km !== null &&
    (!Number.isFinite(payload.max_distance_km) || payload.max_distance_km <= 0)
  ) {
    maxDistanceInput.setAttribute("aria-invalid", "true");
    showTranslationToast("distancePositive", true);
    maxDistanceInput.focus();
    return false;
  }
  if (payload.max_distance_km !== null && latitudeMissing) {
    latitudeInput.setAttribute("aria-invalid", "true");
    longitudeInput.setAttribute("aria-invalid", "true");
    maxDistanceInput.setAttribute("aria-invalid", "true");
    showTranslationToast("distanceNeedsCoordinates", true);
    latitudeInput.focus();
    return false;
  }
  if (state.mode === "register" && !/^\d{6}$/.test(payload.verification_code)) {
    verificationCodeInput.setAttribute("aria-invalid", "true");
    showTranslationToast("verificationRequired", true);
    verificationCodeInput.focus();
    return false;
  }
  if (state.mode === "register" && payload.notification_consent !== true) {
    notificationConsentInput.setAttribute("aria-invalid", "true");
    showTranslationToast("consentRequired", true);
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
    throw new ApiError(body.message || t("serviceUnavailable"), response.status, body);
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
  state.loadedSubscription = subscription;
  emailInput.readOnly = true;
  setProfileVisible(true);
  loadedBanner.classList.remove("is-hidden");
  setText("#loaded-updated-at", formatUpdatedAt(subscription.updated_at));
  setText("#form-description", t("loadedDescription"));
  submitLabel.textContent = t("saveChanges");
  submitSymbol.textContent = "✓";
  resetButton.textContent = t("resetLookup");
}

async function loadSubscriptionForModify() {
  if (state.mode !== "modify" || state.subscriptionLoaded || state.loadingSubscription) return;
  if (!validateEmail()) return;
  state.loadingSubscription = true;
  submitButton.disabled = true;
  submitButton.setAttribute("aria-busy", "true");
  submitLabel.textContent = t("loadingSubscription");
  try {
    const query = new URLSearchParams({ email: emailInput.value.trim() });
    const result = await requestJson(`/api/subscriptions?${query.toString()}`, {
      headers: { Accept: "application/json" },
    });
    showLoadedSubscription(result.subscription);
    window.localStorage.setItem(STORAGE_KEY, result.subscription.email);
    showTranslationToast("loadedToast");
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      showTranslationToast("missingSubscription", true);
      setMode("register");
      nameInput.focus();
    } else {
      showLocalizedToast(error, "readFailure");
      submitLabel.textContent = t("modifySubmit");
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
  state.verificationDeadline = 0;
  updateVerificationButton();
}

function startVerificationCooldown(seconds = 60) {
  if (state.verificationTimer) window.clearInterval(state.verificationTimer);
  const deadline = Date.now() + seconds * 1000;
  state.verificationDeadline = deadline;
  const update = () => {
    if (Date.now() >= deadline) {
      stopVerificationCooldown();
      return;
    }
    updateVerificationButton();
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
    showTranslationToast("codeSent");
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 429) stopVerificationCooldown();
    if (error instanceof ApiError && error.status === 409) {
      showTranslationToast("alreadySubscribedLoading", true);
      setMode("modify");
      await loadSubscriptionForModify();
      return;
    }
    showLocalizedToast(error, "codeFailure");
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
      showTranslationToast("registrationSuccess");
    } else if (state.mode === "modify") {
      showLoadedSubscription(result.subscription);
      showTranslationToast("updateSuccess");
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
      form.reset();
      resetSelections();
      setMode("register");
      showTranslationToast("cancelSuccess");
    }
    refreshHealth();
  } catch (error) {
    showLocalizedToast(error);
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
    new Intl.DateTimeFormat(state.language === "en" ? "en-US" : "zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
      timeZone: "Asia/Shanghai",
    }).format(now),
  );
}

function bindEvents() {
  languageButtons.forEach((button) => {
    button.addEventListener("click", () => applyLanguage(button.dataset.language));
  });
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
applyLanguage(state.language, { persist: false });
setMode("register");
try {
  emailInput.value = window.localStorage.getItem(STORAGE_KEY) || "";
} catch (_error) {
  emailInput.value = "";
}
updateClock();
window.setInterval(updateClock, 1000);

async function init() {
  await loadOptions();
  refreshHealth();
}

init();
