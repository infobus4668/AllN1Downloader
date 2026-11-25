"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const urlInput = $("#urlInput");
const analyzeForm = $("#analyzeForm");
const analyzeBtn = $("#analyzeBtn");
const pasteBtn = $("#pasteBtn");
const sourceTabs = $("#sourceTabs");
const batchBox = $("#batchBox");
const batchInput = $("#batchInput");
const batchMode = $("#batchMode");
const batchQuality = $("#batchQuality");
const batchQualityWrap = $("#batchQualityWrap");
const batchFormat = $("#batchFormat");
const batchBtn = $("#batchBtn");
const mediaCard = $("#mediaCard");
const mediaThumb = $("#mediaThumb");
const thumbWrap = $("#thumbWrap");
const mediaDuration = $("#mediaDuration");
const mediaTitle = $("#mediaTitle");
const mediaChips = $("#mediaChips");
const mediaMeta = $("#mediaMeta");
const modeSwitch = $("#modeSwitch");
const presetButtons = $("#presetButtons");
const qualityGroup = $("#qualityGroup");
const qualitySelect = $("#qualitySelect");
const codecGroup = $("#codecGroup");
const codecSelect = $("#codecSelect");
const formatSelect = $("#formatSelect");
const bitrateGroup = $("#bitrateGroup");
const bitrateSelect = $("#bitrateSelect");
const estimateLine = $("#estimateLine");
const expectedLine = $("#expectedLine");
const clipDetails = $("#clipDetails");
const clipStart = $("#clipStart");
const clipEnd = $("#clipEnd");
const clipPrecise = $("#clipPrecise");
const clipPreciseWrap = $("#clipPreciseWrap");
const subsToggle = $("#subsToggle");
const subsCheck = $("#subsCheck");
const subLangWrap = $("#subLangWrap");
const subLangSelect = $("#subLangSelect");
const embedCheck = $("#embedCheck");
const sponsorCheck = $("#sponsorCheck");
const ratelimitSelect = $("#ratelimitSelect");
const proxyInput = $("#proxyInput");
const cookiesSelect = $("#cookiesSelect");
const playlistBox = $("#playlistBox");
const playlistList = $("#playlistList");
const plCount = $("#plCount");
const plNote = $("#plNote");
const plSearch = $("#plSearch");
const selectAll = $("#selectAll");
const invertBtn = $("#invertBtn");
const downloadBtn = $("#downloadBtn");
const downloadBtnText = $("#downloadBtnText");
const jobList = $("#jobList");
const emptyQueue = $("#emptyQueue");
const emptyTitle = $("#emptyTitle");
const emptyText = $("#emptyText");
const queueCount = $("#queueCount");
const queueSummary = $("#queueSummary");
const queueSearch = $("#queueSearch");
const retryFailedBtn = $("#retryFailedBtn");
const clearBtn = $("#clearBtn");
const openDownloadsBtn = $("#openDownloadsBtn");
const filters = $("#filters");
const toasts = $("#toasts");
const engineBadge = $("#engineBadge");
const engineText = $("#engineText");
const updateBtn = $("#updateBtn");
const settingsBtn = $("#settingsBtn");
const settingsPanel = $("#settingsPanel");
const closeSettings = $("#closeSettings");
const swatches = $("#swatches");
const notifyCheck = $("#notifyCheck");
const settingsInfo = $("#settingsInfo");
const versionInfo = $("#versionInfo");
const diskInfo = $("#diskInfo");
const dropOverlay = $("#dropOverlay");
const jobTemplate = $("#jobTpl");

const FORMATS = {
  video: [
    ["mp4", "MP4 · H.264 / AV1"],
    ["mkv", "MKV · max quality"],
    ["webm", "WebM · VP9 / AV1"],
  ],
  audio: [
    ["original", "Original · no re-encode (best)"],
    ["mp3", "MP3 · re-encode"],
    ["m4a", "M4A · AAC"],
    ["opus", "Opus"],
    ["wav", "WAV · lossless"],
    ["flac", "FLAC · lossless"],
  ],
};

const CODEC_LABELS = {
  auto: "Auto (best)",
  h264: "H.264 · compatible",
  vp9: "VP9 · efficient",
  av1: "AV1 · smallest",
  h265: "H.265 · HEVC",
};

const CODEC_DISPLAY = { h264: "H.264", vp9: "VP9", av1: "AV1", h265: "H.265" };

const AUDIO_BITRATES = {
  mp3: ["320", "256", "192", "128"],
  m4a: ["256", "192", "128"],
};

const EMBED_CONTAINERS = new Set(["mp3", "m4a", "flac", "mp4", "mkv"]);
const ACTIVE_STATUSES = new Set(["queued", "downloading", "processing"]);
const STATUS_LABELS = {
  queued: "Queued",
  downloading: "Downloading",
  processing: "Processing",
  completed: "Completed",
  error: "Failed",
  cancelled: "Cancelled",
};
const THEMES = ["violet", "cyan", "emerald", "rose", "amber"];
const DEFAULT_SETTINGS = {
  cookies: "",
  proxy: "",
  ratelimit: "",
  sponsorblock: false,
  embed: false,
  notifications: false,
  theme: "violet",
  batch: { mode: "video", quality: "best", format: "mp4" },
};

const state = {
  info: null,
  sourceUrl: "",
  mode: "video",
  source: "single",
  filter: "all",
  queueSearch: "",
  activePreset: "",
  selected: new Set(),
  jobs: new Map(),
  platform: "desktop",
  distribution: "source",
  update: null,
  health: null,
};

let settings = loadSettings();
let refreshing = false;
let dragDepth = 0;

function loadSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem("aio.settings") || "{}");
    return {
      ...DEFAULT_SETTINGS,
      ...saved,
      batch: { ...DEFAULT_SETTINGS.batch, ...(saved.batch || {}) },
    };
  } catch {
    return { ...DEFAULT_SETTINGS, batch: { ...DEFAULT_SETTINGS.batch } };
  }
}

function saveSettings() {
  try {
    localStorage.setItem("aio.settings", JSON.stringify(settings));
  } catch {
    /* storage may be unavailable */
  }
}

function toast(message, type = "info", duration = 4200) {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  toasts.append(el);
  setTimeout(() => {
    el.classList.add("leaving");
    setTimeout(() => el.remove(), 300);
  }, duration);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let message = response.statusText || "Request failed";
    let details = null;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") {
        message = data.detail;
      } else if (data.detail && typeof data.detail === "object") {
        details = data.detail;
        if (typeof data.detail.message === "string") message = data.detail.message;
      }
    } catch {
      /* keep status text */
    }
    const error = new Error(message);
    error.details = details;
    throw error;
  }
  return response.json();
}

function formatBytes(value) {
  if (!value || value < 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let amount = value;
  let index = 0;
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024;
    index += 1;
  }
  const digits = index === 0 || amount >= 100 ? 0 : 1;
  return `${amount.toFixed(digits)} ${units[index]}`;
}

function formatDuration(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) return "";
  const total = Math.round(Number(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return hours ? `${hours}:${pad(minutes)}:${pad(secs)}` : `${minutes}:${pad(secs)}`;
}

function parseClipInput(text) {
  const value = String(text || "").trim();
  if (!value) return null;
  if (!/^(?:\d{1,3}:){0,2}\d{1,2}(?:\.\d{1,3})?$/.test(value)) return NaN;
  const parts = value.split(":").map(Number);
  if (parts.some((part) => !Number.isFinite(part) || part < 0)) return NaN;
  if (parts.length > 1 && parts[parts.length - 1] >= 60) return NaN;
  if (parts.length === 3 && parts[1] >= 60) return NaN;
  return parts.reduce((total, part) => total * 60 + part, 0);
}

function formatEta(seconds) {
  if (seconds == null) return "—";
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  return `${minutes}m ${String(secs).padStart(2, "0")}s`;
}

function formatViews(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "";
  try {
    return `${new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(value)} views`;
  } catch {
    return `${value} views`;
  }
}

function formatDate(value) {
  const text = String(value || "");
  if (!/^\d{8}$/.test(text)) return "";
  const date = new Date(`${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}T00:00:00`);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function truncate(text, limit) {
  if (!text) return "";
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function isTyping(el) {
  if (!el) return false;
  return ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || el.isContentEditable;
}

const encodePath = (path) => path.split("/").map(encodeURIComponent).join("/");
const fileUrl = (jobId, rel) => `/api/jobs/${encodeURIComponent(jobId)}/files/${encodePath(rel)}`;

function applyTheme(theme) {
  const name = THEMES.includes(theme) ? theme : "violet";
  document.documentElement.dataset.theme = name;
}

function updateSwatches() {
  for (const button of $$(".swatch", swatches)) {
    const active = button.dataset.theme === settings.theme;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
}

function applySettingsToUI() {
  applyTheme(settings.theme);
  cookiesSelect.value = settings.cookies;
  proxyInput.value = settings.proxy;
  ratelimitSelect.value = settings.ratelimit;
  sponsorCheck.checked = Boolean(settings.sponsorblock);
  notifyCheck.checked = Boolean(settings.notifications);
  updateSwatches();
}

function setMode(mode) {
  state.mode = mode;
  state.activePreset = "";
  for (const button of modeSwitch.querySelectorAll(".seg")) {
    const active = button.dataset.mode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  }
  const audio = mode === "audio";
  qualityGroup.classList.toggle("hidden", audio);
  codecGroup.classList.toggle("hidden", audio);
  subsToggle.classList.toggle("hidden", audio);
  subLangWrap.classList.toggle("hidden", audio || !subsCheck.checked);
  clipPreciseWrap.classList.toggle("hidden", audio);
  formatSelect.innerHTML = "";
  for (const [value, label] of FORMATS[mode]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    formatSelect.append(option);
  }
  formatSelect.value = audio ? "original" : "mp4";
  syncCodecs();
  syncBitrates();
  syncEmbed();
  renderPresets();
  updateEstimate();
  updateSelectionUI();
}

function renderPresets() {
  const presets = state.mode === "audio"
    ? [
      ["original", "Original", "Keep the source audio untouched"],
      ["mp3", "MP3 320", "Portable MP3 at 320 kbps"],
      ["m4a", "M4A 256", "AAC audio at 256 kbps"],
    ]
    : [
      ["max", "Maximum quality", "Highest available resolution and codec"],
      ["compatible", "Device compatible", "Prefer H.264 MP4 up to 1080p"],
      ["efficient", "Smaller file · AV1", "Prefer efficient AV1 video"],
    ];
  presetButtons.innerHTML = "";
  for (const [id, label, hint] of presets) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "preset-btn";
    button.dataset.preset = id;
    button.textContent = label;
    button.title = hint;
    button.setAttribute("aria-pressed", String(state.activePreset === id));
    button.classList.toggle("active", state.activePreset === id);
    presetButtons.append(button);
  }
}

function applyPreset(id) {
  if (state.mode === "audio") {
    const audioPreset = { original: "original", mp3: "mp3", m4a: "m4a" }[id];
    if (!audioPreset) return;
    formatSelect.value = audioPreset;
    syncBitrates();
    if (id === "mp3") bitrateSelect.value = "320";
    if (id === "m4a") bitrateSelect.value = "256";
  } else if (id === "max") {
    qualitySelect.value = "best";
    formatSelect.value = "mkv";
    syncCodecs();
    codecSelect.value = "auto";
  } else if (id === "compatible") {
    const heights = (state.info && state.info.qualities || []).map((quality) => quality.height);
    const compatibleHeight = heights.find((height) => height <= 1080);
    qualitySelect.value = compatibleHeight ? String(compatibleHeight) : "best";
    formatSelect.value = "mp4";
    syncCodecs();
    codecSelect.value = [...codecSelect.options].some((option) => option.value === "h264") ? "h264" : "auto";
  } else if (id === "efficient") {
    qualitySelect.value = "best";
    formatSelect.value = "mkv";
    syncCodecs();
    codecSelect.value = [...codecSelect.options].some((option) => option.value === "av1")
      ? "av1"
      : [...codecSelect.options].some((option) => option.value === "vp9") ? "vp9" : "auto";
  } else {
    return;
  }
  state.activePreset = id;
  syncBitrates();
  syncEmbed();
  renderPresets();
  updateEstimate();
  updateSelectionUI();
}

function populateQualities(info) {
  qualitySelect.innerHTML = "";
  const top = info.qualities && info.qualities[0];
  const best = document.createElement("option");
  best.value = "best";
  best.textContent = top ? `Best available · up to ${top.height}p` : "Best available";
  qualitySelect.append(best);
  for (const quality of info.qualities || []) {
    let largest = quality.formats[0];
    for (const format of quality.formats) {
      if ((format.filesize || 0) > (largest.filesize || 0)) largest = format;
    }
    const badge = quality.height >= 2160 ? " · 4K" : quality.height >= 1440 ? " · 2K" : quality.height >= 1080 ? " · Full HD" : quality.height >= 720 ? " · HD" : "";
    const size = largest && largest.filesize ? ` · ~${formatBytes(largest.filesize)}` : "";
    const option = document.createElement("option");
    option.value = String(quality.height);
    option.textContent = `${quality.height}p${badge}${size}`;
    qualitySelect.append(option);
  }
}

function currentQuality() {
  const info = state.info;
  if (!info || !info.qualities || !info.qualities.length) return null;
  if (qualitySelect.value === "best") return info.qualities[0];
  return info.qualities.find((quality) => String(quality.height) === qualitySelect.value) || null;
}

function syncCodecs() {
  const info = state.info;
  const previous = codecSelect.value;
  const available = new Set();
  const qualities = qualitySelect.value === "best"
    ? (info && info.qualities) || []
    : [currentQuality()].filter(Boolean);
  for (const quality of qualities) {
    for (const format of quality.formats || []) available.add(format.codec);
  }
  codecSelect.innerHTML = "";
  for (const codec of ["auto", "h264", "vp9", "av1", "h265"]) {
    if (codec !== "auto" && !available.has(codec)) continue;
    const option = document.createElement("option");
    option.value = codec;
    option.textContent = CODEC_LABELS[codec];
    codecSelect.append(option);
  }
  codecSelect.value = previous === "auto" || available.has(previous) ? previous : "auto";
  if (!codecSelect.value) codecSelect.value = "auto";
}

function syncBitrates() {
  const rates = state.mode === "audio" ? AUDIO_BITRATES[formatSelect.value] : null;
  bitrateGroup.classList.toggle("hidden", !rates);
  if (!rates) {
    bitrateSelect.innerHTML = "";
    return;
  }
  const previous = bitrateSelect.value;
  bitrateSelect.innerHTML = "";
  for (const rate of rates) {
    const option = document.createElement("option");
    option.value = rate;
    option.textContent = `${rate} kbps`;
    bitrateSelect.append(option);
  }
  bitrateSelect.value = rates.includes(previous) ? previous : rates[0];
}

function syncEmbed() {
  const supported = EMBED_CONTAINERS.has(formatSelect.value);
  embedCheck.disabled = !supported;
  embedCheck.checked = Boolean(settings.embed) && supported;
  embedCheck.closest(".check").classList.toggle("disabled", !supported);
}

function expectedVariant(container, codec, cap) {
  const info = state.info;
  if (!info || !info.qualities) return null;
  const limit = cap === "best" ? Infinity : Number(cap);
  const exact = [];
  const codecMatch = [];
  const all = [];
  for (const quality of info.qualities) {
    if (Number.isFinite(limit) && quality.height > limit) continue;
    for (const format of quality.formats || []) {
      const candidate = { ...format, height: quality.height };
      all.push(candidate);
      const codecOk = codec === "auto" || format.codec === codec;
      if (codecOk) codecMatch.push(candidate);
      if (codecOk && format.ext === container) exact.push(candidate);
    }
  }
  let pool;
  if (container === "webm") {
    const webm = all.filter((format) => format.ext === "webm");
    if (!webm.length) return null;
    pool = exact.length ? exact : webm;
  } else if (container === "mp4") {
    pool = exact.length ? exact : codecMatch.length ? codecMatch : all;
  } else {
    pool = codecMatch.length ? codecMatch : all;
  }
  if (!pool.length) return null;
  return pool.reduce((best, item) => {
    if (!best || item.height > best.height) return item;
    if (item.height < best.height) return best;
    const size = item.filesize || 0;
    const bestSize = best.filesize || 0;
    return size > bestSize || (size === bestSize && (item.tbr || 0) > (best.tbr || 0)) ? item : best;
  }, null);
}

function renderExpected() {
  expectedLine.textContent = "";
  const info = state.info;
  if (!info) return;
  if (info.is_playlist) {
    expectedLine.textContent = "Each selected item applies these settings when its download starts.";
    return;
  }
  if (state.mode === "audio") {
    const container = formatSelect.value;
    if (container === "original") {
      const source = info.source_audio;
      const detail = source
        ? [source.codec ? String(source.codec).toUpperCase() : "", source.abr ? `${Math.round(source.abr)} kbps` : ""].filter(Boolean).join(" · ")
        : "";
      expectedLine.textContent = detail
        ? `Expected: original ${detail} kept untouched.`
        : "Expected: original audio kept untouched.";
    } else {
      const rate = bitrateSelect.value;
      const lossless = container === "wav" || container === "flac" ? " · lossless" : "";
      expectedLine.textContent = `Expected: ${container.toUpperCase()}${rate && !lossless ? ` · ${rate} kbps` : ""}${lossless}.`;
    }
    return;
  }
  const container = formatSelect.value;
  const variant = expectedVariant(container, codecSelect.value, qualitySelect.value);
  if (!variant) {
    expectedLine.textContent = container === "webm"
      ? "WebM is not offered for this source. Choose MP4 or MKV."
      : "Video formats are not published for this source.";
    return;
  }
  const overall = (info.qualities && info.qualities[0] && info.qualities[0].height) || 0;
  let text = `Expected: ${container.toUpperCase()} · ${variant.height}p · ${CODEC_DISPLAY[variant.codec] || variant.codec}`;
  if (variant.hdr) text += " · HDR";
  if (container !== "mkv" && overall > variant.height) {
    text += ` — ${overall}p is available in MKV for maximum quality.`;
  }
  expectedLine.textContent = text;
}

function updateEstimate() {
  renderExpected();
  const info = state.info;
  if (!info) {
    estimateLine.textContent = "";
    return;
  }
  if (info.is_playlist && !(info.qualities && info.qualities.length)) {
    estimateLine.textContent = state.mode === "audio"
      ? `${formatSelect.value === "original" ? "Original audio" : formatSelect.value.toUpperCase()} is applied to every selected item when the download starts.`
      : "Quality and size are resolved for each item when the download starts.";
    return;
  }
  const duration = Number(info.duration) || 0;
  if (state.mode === "audio") {
    const container = formatSelect.value;
    if (container === "original") {
      let size = info.source_audio && info.source_audio.filesize;
      if (!size && info.source_audio && info.source_audio.abr && duration) {
        size = (info.source_audio.abr * 1000 / 8) * duration;
      }
      estimateLine.textContent = size
        ? `Estimated size ≈ ${formatBytes(size)} · original ${info.source_audio.codec || "audio"} kept untouched`
        : "Original audio is kept untouched — size appears when the download starts.";
      return;
    }
    const rate = Number(bitrateSelect.value);
    if (!rate) {
      estimateLine.textContent = `${container.toUpperCase()} output size depends on the source and encoder.`;
      return;
    }
    if (duration) {
      estimateLine.textContent = `Estimated size ≈ ${formatBytes((rate * 1000 / 8) * duration)} · ${container.toUpperCase()} at ${rate} kbps`;
    } else {
      estimateLine.textContent = `Encoded as ${container.toUpperCase()} at ${rate} kbps`;
    }
    return;
  }
  const quality = currentQuality();
  if (!quality) {
    estimateLine.textContent = "Video formats are not available for this source.";
    return;
  }
  const variant = expectedVariant(formatSelect.value, codecSelect.value, qualitySelect.value);
  let audioSize = (info.source_audio && info.source_audio.filesize) || 0;
  if (!audioSize && info.source_audio && info.source_audio.abr && duration) {
    audioSize = (info.source_audio.abr * 1000 / 8) * duration;
  }
  const videoSize = (variant && variant.filesize) || 0;
  if (!videoSize && !audioSize) {
    estimateLine.textContent = "Estimated size is not published for this source.";
    return;
  }
  const total = videoSize + audioSize;
  const details = [videoSize ? `video ${formatBytes(videoSize)}` : "", audioSize ? `audio ${formatBytes(audioSize)}` : ""].filter(Boolean).join(" + ");
  estimateLine.textContent = `Estimated size ≈ ${formatBytes(total)}${details ? ` · ${details}` : ""}`;
}

function addChip(text, accent = false) {
  if (!text) return;
  const chip = document.createElement("span");
  chip.className = `chip${accent ? " accent" : ""}`;
  chip.textContent = text;
  mediaChips.append(chip);
}

function updateSelectionUI() {
  const info = state.info;
  if (!info) {
    downloadBtnText.textContent = "Download";
    downloadBtn.disabled = false;
    return;
  }
  const unavailable = !info.is_playlist && state.mode === "video"
    && !expectedVariant(formatSelect.value, codecSelect.value, qualitySelect.value);
  if (!info.is_playlist) {
    downloadBtnText.textContent = unavailable ? "Format unavailable" : "Download";
    downloadBtn.disabled = unavailable;
    return;
  }
  const total = info.entries.length;
  const count = state.selected.size;
  plCount.textContent = `(${count}/${total} selected)`;
  selectAll.checked = count === total;
  selectAll.indeterminate = count > 0 && count < total;
  downloadBtn.disabled = count === 0 || unavailable;
  downloadBtnText.textContent = count
    ? `Download ${count} item${count === 1 ? "" : "s"}`
    : "Select items";
}

function renderPlaylist(info) {
  playlistList.innerHTML = "";
  plSearch.value = "";
  state.selected = new Set(info.entries.map((entry) => entry.index));
  const fragment = document.createDocumentFragment();
  for (const entry of info.entries) {
    const label = document.createElement("label");
    label.className = "pl-item";
    label.dataset.title = entry.title.toLowerCase();

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = true;
    checkbox.dataset.index = String(entry.index);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.selected.add(entry.index);
      else state.selected.delete(entry.index);
      updateSelectionUI();
    });

    const num = document.createElement("span");
    num.className = "pl-num";
    num.textContent = entry.index;

    const thumb = document.createElement("img");
    thumb.className = "pl-thumb";
    thumb.alt = "";
    thumb.loading = "lazy";
    if (entry.thumbnail) thumb.src = entry.thumbnail;
    else thumb.classList.add("missing");

    const title = document.createElement("span");
    title.className = "pl-title";
    title.textContent = entry.title;
    title.title = entry.title;

    const duration = document.createElement("span");
    duration.className = "pl-dur";
    duration.textContent = entry.duration ? formatDuration(entry.duration) : "";

    label.append(checkbox, num, thumb, title, duration);
    fragment.append(label);
  }
  playlistList.append(fragment);

  const total = info.playlist_count || info.entries.length;
  const truncated = total > info.entries.length;
  plNote.textContent = truncated
    ? `Previewing ${info.entries.length} of ${total} items. Only checked items will be downloaded.`
    : "";
  plNote.classList.toggle("hidden", !truncated);
  updateSelectionUI();
}

function renderMedia(info, sourceUrl) {
  state.info = info;
  state.sourceUrl = sourceUrl;
  mediaTitle.textContent = info.title || "Untitled";

  if (info.thumbnail) {
    thumbWrap.classList.remove("no-thumb");
    mediaThumb.src = info.thumbnail;
    mediaThumb.onerror = () => thumbWrap.classList.add("no-thumb");
  } else {
    thumbWrap.classList.add("no-thumb");
    mediaThumb.removeAttribute("src");
    mediaThumb.onerror = null;
  }

  if (info.duration) {
    mediaDuration.textContent = formatDuration(info.duration);
    mediaDuration.classList.remove("hidden");
  } else {
    mediaDuration.classList.add("hidden");
  }

  mediaChips.innerHTML = "";
  addChip(info.extractor, true);
  if (info.uploader) addChip(info.uploader);
  if (info.is_playlist) addChip(`Playlist · ${info.playlist_count || info.entries.length} items`);
  else if (info.qualities && info.qualities.length) addChip(`Up to ${info.qualities[0].height}p`);
  if (info.audio_formats && info.audio_formats.length && info.audio_only) {
    const source = info.source_audio;
    addChip(source ? `Source: ${source.codec}${source.abr ? ` ${Math.round(source.abr)} kbps` : ""}` : "Audio source");
  }
  if (info.view_count) addChip(formatViews(info.view_count));
  const uploaded = formatDate(info.upload_date);
  if (uploaded) addChip(uploaded);
  if (info.is_live) addChip("Live", true);

  let host = "";
  try {
    host = new URL(info.webpage_url).hostname.replace(/^www\./, "");
  } catch {
    host = "";
  }
  mediaMeta.textContent = [
    host,
    info.is_playlist ? "playlist" : info.audio_only ? "audio only" : "video",
    info.duration ? formatDuration(info.duration) : "",
  ]
    .filter(Boolean)
    .join(" · ");

  populateQualities(info);
  qualitySelect.value = "best";
  const audioOnly = Boolean(info.audio_only);
  for (const button of modeSwitch.querySelectorAll(".seg")) {
    button.disabled = audioOnly && button.dataset.mode === "video";
  }
  setMode(audioOnly ? "audio" : "video");
  subsCheck.checked = false;
  subLangWrap.classList.add("hidden");
  subLangSelect.value = "en";

  const isPlaylist = Boolean(info.is_playlist && info.entries && info.entries.length);
  clipStart.value = "";
  clipEnd.value = "";
  clipPrecise.checked = false;
  clipDetails.open = false;
  clipDetails.classList.toggle("hidden", isPlaylist);
  playlistBox.classList.toggle("hidden", !isPlaylist);
  if (isPlaylist) renderPlaylist(info);
  else {
    state.selected.clear();
    playlistList.innerHTML = "";
    plSearch.value = "";
  }

  mediaCard.classList.remove("hidden");
  updateSelectionUI();
  mediaCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function setAnalyzing(active) {
  analyzeBtn.disabled = active;
  analyzeBtn.querySelector("span").textContent = active ? "Analyzing…" : "Analyze";
}

async function analyze(event) {
  if (event) event.preventDefault();
  if (analyzeBtn.disabled) return;
  const url = urlInput.value.trim();
  const feedback = $("#analysisStatus");
  if (!isMediaLink(url)) {
    feedback.textContent = "Enter a complete link beginning with http:// or https://.";
    urlInput.setAttribute("aria-invalid", "true");
    mediaCard.classList.add("hidden");
    urlInput.focus();
    return;
  }
  setAnalyzing(true);
  feedback.textContent = "Checking this link for media and available formats…";
  urlInput.removeAttribute("aria-invalid");
  mediaCard.classList.add("hidden");
  try {
    const info = await api("/api/info", {
      method: "POST",
      body: JSON.stringify({
        url,
        cookies_browser: settings.cookies || null,
        proxy: settings.proxy || null,
      }),
    });
    if (urlInput.value.trim() !== url || state.source !== "single") {
      feedback.textContent = "Link changed. Analyze the new link to continue.";
      return;
    }
    renderMedia(info, url);
    feedback.textContent = "";
    toast(
      info.is_playlist ? `Playlist found · ${info.entries.length} items` : "Ready to download",
      "success"
    );
  } catch (error) {
    feedback.textContent = `Could not analyze this link: ${error.message}`;
  } finally {
    setAnalyzing(false);
  }
}

async function startDownload() {
  if (downloadBtn.disabled) return;
  const info = state.info;
  if (!info) return;

  const audio = state.mode === "audio";
  const clipFrom = info.is_playlist ? null : parseClipInput(clipStart.value);
  const clipTo = info.is_playlist ? null : parseClipInput(clipEnd.value);
  if (Number.isNaN(clipFrom) || Number.isNaN(clipTo)) {
    clipDetails.open = true;
    toast("Use seconds, mm:ss, or hh:mm:ss for clip times", "error");
    (Number.isNaN(clipFrom) ? clipStart : clipEnd).focus();
    return;
  }
  if (clipFrom != null && clipTo != null && clipFrom >= clipTo) {
    clipDetails.open = true;
    toast("Clip end must be after the start", "error");
    clipEnd.focus();
    return;
  }
  const body = {
    url: info.webpage_url || state.sourceUrl,
    mode: state.mode,
    quality: audio ? "best" : qualitySelect.value || "best",
    container: formatSelect.value,
    codec: audio ? "auto" : codecSelect.value || "auto",
    audio_quality: audio && bitrateSelect.value ? bitrateSelect.value : null,
    subtitles: !audio && subsCheck.checked,
    subtitle_lang: subLangSelect.value,
    is_playlist: Boolean(info.is_playlist),
    cookies_browser: settings.cookies || null,
    embed_thumbnail: embedCheck.checked,
    sponsorblock: Boolean(settings.sponsorblock),
    ratelimit: settings.ratelimit ? Number(settings.ratelimit) : null,
    proxy: settings.proxy || null,
    clip_start: clipFrom != null ? clipStart.value.trim() : null,
    clip_end: clipTo != null ? clipEnd.value.trim() : null,
    clip_precise: !audio && clipPrecise.checked,
    title: info.title,
    thumbnail: info.thumbnail || null,
  };

  if (info.is_playlist) {
    if (!state.selected.size) {
      toast("Select at least one playlist item", "error");
      return;
    }
    body.playlist_items = [...state.selected].sort((a, b) => a - b);
  }

  downloadBtn.disabled = true;
  const previousLabel = downloadBtnText.textContent;
  downloadBtnText.textContent = "Adding…";
  try {
    await api("/api/download", { method: "POST", body: JSON.stringify(body) });
    window.AllN1DownloaderAndroid?.onDownloadQueued?.();
    toast("Added to download queue", "success");
    refreshJobs();
  } catch (error) {
    if (error.details && error.details.job_id) {
      focusJob(error.details.job_id);
      if (confirm(`${error.message}\n\nAdd another copy?`)) {
        try {
          await api("/api/download", { method: "POST", body: JSON.stringify({ ...body, force: true }) });
          window.AllN1DownloaderAndroid?.onDownloadQueued?.();
          toast("Added another copy to the queue", "success");
          refreshJobs();
        } catch (retryError) {
          toast(retryError.message, "error", 7000);
        }
      }
    } else {
      toast(error.message, "error", 7000);
    }
  } finally {
    downloadBtnText.textContent = previousLabel;
    updateSelectionUI();
  }
}

function syncBatchFormats(preferredFormat) {
  const mode = batchMode.value;
  batchFormat.innerHTML = "";
  for (const [value, label] of FORMATS[mode]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    batchFormat.append(option);
  }
  const fallback = mode === "video" ? "mp4" : "mp3";
  const wanted = preferredFormat || fallback;
  batchFormat.value = [...batchFormat.options].some((option) => option.value === wanted) ? wanted : fallback;
  batchQualityWrap.classList.toggle("hidden", mode === "audio");
  settings.batch = {
    mode,
    quality: batchQuality.value,
    format: batchFormat.value,
  };
  saveSettings();
}

function isMediaLink(value) {
  try {
    return /^https?:\/\//i.test(value) && !/\s/.test(value) && value.length <= 4096 && Boolean(new URL(value).hostname);
  } catch { return false; }
}

async function submitBatch() {
  if (batchBtn.disabled) return;
  const feedback = $("#batchStatus");
  const lines = batchInput.value.split(/\r?\n/).map(line => line.trim());
  const invalid = lines.findIndex(line => line && !isMediaLink(line));
  const urls = [...new Set(lines.filter(Boolean))];
  if (invalid !== -1 || !urls.length || urls.length > 50) {
    feedback.textContent = invalid !== -1 ? `Check line ${invalid + 1}: enter a complete HTTP(S) link.`
      : urls.length > 50 ? `Found ${urls.length} distinct links. Submit up to 50 at a time.` : "Paste at least one link.";
    batchInput.focus();
    return;
  }
  const audio = batchMode.value === "audio";
  const container = batchFormat.value;
  const quality = audio ? "best" : batchQuality.value;
  batchBtn.disabled = true;
  batchInput.readOnly = true;
  const previousLabel = batchBtn.textContent;
  batchBtn.textContent = "Queueing…";
  let queued = 0;
  let skipped = 0;
  const failed = [];
  let lastError = "";
  for (const [index, url] of urls.entries()) {
    feedback.textContent = `Adding link ${index + 1} of ${urls.length}…`;
    try {
      await api("/api/download", {
        method: "POST",
        body: JSON.stringify({
          url,
          mode: audio ? "audio" : "video",
          quality,
          container,
          is_playlist: false,
          cookies_browser: settings.cookies || null,
          embed_thumbnail: Boolean(settings.embed) && EMBED_CONTAINERS.has(container),
          sponsorblock: Boolean(settings.sponsorblock),
          ratelimit: settings.ratelimit ? Number(settings.ratelimit) : null,
          proxy: settings.proxy || null,
        }),
      });
      queued += 1;
    } catch (error) {
      if (error.details && error.details.job_id) {
        skipped += 1;
        continue;
      }
      lastError = error.message;
      failed.push(url);
    }
  }
  batchBtn.disabled = false;
  batchInput.readOnly = false;
  batchBtn.textContent = previousLabel;
  batchInput.value = failed.join("\n");
  feedback.textContent = `Added ${queued} of ${urls.length} links.`
    + (skipped ? ` ${skipped} already queued or saved.` : "")
    + (failed.length ? ` Unsubmitted links are still in the box. ${lastError}` : "");
  if (queued) {
    window.AllN1DownloaderAndroid?.onDownloadQueued?.();
    toast(
      `Queued ${queued} link${queued === 1 ? "" : "s"}${skipped ? ` · ${skipped} already added` : ""}${failed.length ? ` · ${failed.length} failed` : ""}`,
      failed.length ? "info" : "success"
    );
    refreshJobs();
  } else if (skipped && !failed.length) {
    toast("Already queued · nothing new added", "info");
  } else {
    toast("Could not queue those links", "error");
  }
}

function createJobEl(job) {
  const el = jobTemplate.content.firstElementChild.cloneNode(true);
  el.dataset.id = job.id;
  const thumb = el.querySelector('[data-field="thumb"]');
  thumb.addEventListener("error", () => {
    el.dataset.thumbBroken = "1";
    thumb.hidden = true;
    el.querySelector('[data-field="icon"]').hidden = false;
  });
  el.querySelector('[data-action="cancel"]').addEventListener("click", () => cancelJob(job.id));
  el.querySelector('[data-action="retry"]').addEventListener("click", () => retryJob(job.id));
  el.querySelector('[data-action="delete"]').addEventListener("click", () => deleteJob(job.id));
  el.querySelector('[data-action="forget"]').addEventListener("click", () => forgetJob(job.id));
  el.querySelector('[data-action="open"]').addEventListener("click", () => openFolder(job.id));
  el.querySelector('[data-action="open-file"]').addEventListener("click", () => openFile(job.id));
  el.querySelector('[data-action="copy"]').addEventListener("click", () => copyPath(job.id));
  el.querySelector('[data-action="logs"]').addEventListener("click", () => toggleLogs(el, job.id));
  return el;
}

function setField(el, field, value) {
  const node = el.querySelector(`[data-field="${field}"]`);
  if (node && node.textContent !== value) node.textContent = value;
}

async function toggleLogs(el, jobId) {
  const wrap = el.querySelector('[data-field="logsWrap"]');
  const button = el.querySelector('[data-action="logs"]');
  if (!wrap.classList.contains("hidden")) {
    wrap.classList.add("hidden");
    button.textContent = "Logs";
    return;
  }
  wrap.classList.remove("hidden");
  button.disabled = true;
  button.textContent = "Loading…";
  try {
    const result = await api(`/api/jobs/${encodeURIComponent(jobId)}/logs`);
    el.querySelector('[data-field="logs"]').textContent = (result.logs || []).join("\n") || "No log output yet.";
    button.textContent = "Hide logs";
  } catch (error) {
    wrap.classList.add("hidden");
    button.textContent = "Logs";
    toast(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

function verifiedNote(job) {
  const media = job.media;
  if (!media) return "";
  const parts = [];
  if (media.video) {
    parts.push([media.video.height ? `${media.video.height}p` : "", media.video.label].filter(Boolean).join(" "));
    if (media.video.fps) parts.push(`${Math.round(media.video.fps)} fps`);
  }
  if (media.audio) {
    const rate = media.audio.bitrate ? ` ${Math.round(media.audio.bitrate / 1000)} kbps` : "";
    parts.push(`${media.audio.label}${rate}`);
  }
  const label = parts.filter(Boolean).join(" · ");
  if (!label) return "";
  const notes = [];
  if (job.mode === "video" && media.video) {
    if (job.quality !== "best" && Number(job.quality) !== media.video.height) notes.push(`${job.quality}p requested`);
    if (job.codec && job.codec !== "auto" && job.codec !== media.video.codec) notes.push(`${job.codec} requested`);
  }
  const prefix = (job.file_count || 1) > 1 ? "Verified first file:" : "Verified:";
  return `${prefix} ${label}${notes.length ? ` (${notes.join(", ")})` : ""}`;
}

function updateJobEl(el, job) {
  el.dataset.status = job.status;
  el.dataset.mode = job.mode;

  const thumb = el.querySelector('[data-field="thumb"]');
  const icon = el.querySelector('[data-field="icon"]');
  if (job.thumbnail && !el.dataset.thumbBroken) {
    if (thumb.dataset.src !== job.thumbnail) {
      thumb.dataset.src = job.thumbnail;
      thumb.src = job.thumbnail;
    }
    thumb.hidden = false;
    icon.hidden = true;
  } else {
    thumb.hidden = true;
    icon.hidden = false;
    icon.textContent = job.mode === "audio" ? "♪" : "↓";
  }

  setField(el, "title", job.title || "Untitled");
  const tagParts = [job.mode, job.container];
  if (job.mode === "video" && job.quality !== "best") tagParts.push(`${job.quality}p`);
  if (job.mode === "video" && job.codec && job.codec !== "auto") tagParts.push(job.codec);
  if (job.clip_start != null || job.clip_end != null) {
    const from = formatDuration(job.clip_start || 0);
    const to = job.clip_end != null ? formatDuration(job.clip_end) : "end";
    tagParts.push(`clip ${from}–${to}`);
  }
  setField(el, "tag", tagParts.join(" · "));
  setField(el, "status", STATUS_LABELS[job.status] || job.status);

  const fileCount = Number.isFinite(job.file_count) ? job.file_count : job.files.length;
  const totalSize = Number.isFinite(job.total_size)
    ? job.total_size
    : job.files.reduce((sum, file) => sum + (file.size || 0), 0);
  let sub = "";
  if (job.status === "queued") sub = "Waiting in queue";
  else if (job.status === "downloading") sub = job.current_item ? `Downloading · ${job.current_item}` : "Downloading…";
  else if (job.status === "processing") sub = "Merging audio & video, converting…";
  else if (job.status === "completed") {
    sub = `${fileCount} file${fileCount === 1 ? "" : "s"} · ${formatBytes(totalSize)}`;
  } else if (job.status === "error") sub = job.error || "Download failed";
  else if (job.status === "cancelled") sub = "Cancelled";
  setField(el, "sub", sub);

  let stats = "";
  if (job.status === "downloading") {
    const parts = [];
    if (job.playlist_index && job.playlist_count) parts.push(`${job.playlist_index}/${job.playlist_count}`);
    parts.push(`${Math.round(job.progress)}%`);
    if (job.downloaded) {
      parts.push(`${formatBytes(job.downloaded)}${job.total ? ` / ${formatBytes(job.total)}` : ""}`);
    }
    if (job.speed) parts.push(`${formatBytes(job.speed)}/s`);
    if (job.eta != null) parts.push(`ETA ${formatEta(job.eta)}`);
    stats = parts.join(" · ");
  } else if (job.status === "processing") {
    stats = "Finalizing…";
  } else if (job.status === "completed" && job.finished_at && job.started_at) {
    const seconds = Math.max(0, Math.round(job.finished_at - job.started_at));
    stats = `Finished in ${formatEta(seconds)}`;
  }
  if (job.status === "completed") {
    const verified = verifiedNote(job);
    if (verified) stats = stats ? `${stats} · ${verified}` : verified;
  }
  setField(el, "stats", stats);

  let percent = job.progress;
  if (job.status === "completed") percent = 100;
  if (job.status === "queued") percent = 0;
  percent = Math.min(100, Math.max(0, percent || 0));
  el.querySelector('[data-field="fill"]').style.width = `${percent}%`;

  const filesKey = `${fileCount}:${totalSize}:` + job.files.map((file) => `${file.rel}:${file.size}`).join("|");
  if (el.dataset.filesKey !== filesKey) {
    el.dataset.filesKey = filesKey;
    const box = el.querySelector('[data-field="files"]');
    box.innerHTML = "";
    const shown = job.files.slice(0, 5);
    for (const file of shown) {
      const link = document.createElement("a");
      link.className = "file-link";
      link.href = fileUrl(job.id, file.rel);
      link.download = file.name;
      link.title = `${file.name} · ${formatBytes(file.size)}`;
      link.textContent = `${truncate(file.name, 46)} · ${formatBytes(file.size)}`;
      box.append(link);
    }
    if (fileCount > shown.length) {
      const more = document.createElement("span");
      more.className = "file-link";
      more.textContent = `+${fileCount - shown.length} more · use ZIP`;
      box.append(more);
    }
  }

  const logsWrap = el.querySelector('[data-field="logsWrap"]');
  const logsPre = el.querySelector('[data-field="logs"]');
  const logCount = Number.isFinite(job.log_count) ? job.log_count : (job.logs || []).length;
  const logsBtn = el.querySelector('[data-action="logs"]');
  logsBtn.classList.toggle("hidden", logCount === 0);
  if (logCount === 0) {
    logsWrap.classList.add("hidden");
    logsPre.textContent = "";
    logsBtn.textContent = "Logs";
  }

  const isActive = ACTIVE_STATUSES.has(job.status);
  const isDone = job.status === "completed";
  const isFailed = job.status === "error" || job.status === "cancelled";

  el.querySelector('[data-action="cancel"]').classList.toggle("hidden", !isActive);
  el.querySelector('[data-action="retry"]').classList.toggle("hidden", !(isFailed && job.can_retry));
  el.querySelector('[data-action="forget"]').classList.toggle("hidden", !(isDone || isFailed));
  el.querySelector('[data-action="copy"]').classList.toggle("hidden", state.platform === "android");

  const saveLink = el.querySelector('[data-action="save"]');
  const singleFile = isDone && fileCount === 1;
  saveLink.classList.toggle("hidden", !singleFile);
  if (singleFile) saveLink.href = fileUrl(job.id, job.files[0].rel);

  const zipLink = el.querySelector('[data-action="zip"]');
  const multipleFiles = isDone && fileCount > 1;
  zipLink.classList.toggle("hidden", !multipleFiles);
  if (multipleFiles) zipLink.href = `/api/jobs/${encodeURIComponent(job.id)}/zip`;

  el.querySelector('[data-action="open-file"]').classList.toggle("hidden", !(isDone && job.has_playable));
}

function matchesFilter(job) {
  let statusMatch = true;
  if (state.filter === "active") statusMatch = ACTIVE_STATUSES.has(job.status);
  else if (state.filter === "done") statusMatch = job.status === "completed";
  else if (state.filter === "failed") statusMatch = job.status === "error" || job.status === "cancelled";
  if (!statusMatch) return false;
  if (!state.queueSearch) return true;
  const query = state.queueSearch.toLowerCase();
  return [job.title, job.url, job.id, job.error]
    .some((value) => String(value || "").toLowerCase().includes(query));
}

function updateQueueChrome() {
  const entries = [...state.jobs.values()];
  const active = entries.filter((entry) => ACTIVE_STATUSES.has(entry.data.status)).length;
  const failed = entries.filter((entry) =>
    (entry.data.status === "error" || entry.data.status === "cancelled") && entry.data.can_retry
  ).length;
  const completed = entries.filter((entry) => entry.data.status === "completed");
  const savedBytes = completed.reduce((sum, entry) => sum + (entry.data.total_size || 0), 0);
  queueCount.classList.toggle("hidden", active === 0);
  queueCount.textContent = `${active} active`;
  queueSummary.textContent = entries.length
    ? `${entries.length} job${entries.length === 1 ? "" : "s"} · ${completed.length} completed · ${formatBytes(savedBytes)} saved`
    : "Ready for your next download";
  retryFailedBtn.classList.toggle("hidden", failed === 0);

  const visible = entries.filter((entry) => matchesFilter(entry.data));
  emptyQueue.classList.toggle("hidden", visible.length > 0);
  if (!visible.length) {
    if (!entries.length) {
      emptyTitle.textContent = "Nothing here yet";
      emptyText.textContent = "Analyze a link above and your downloads will appear here.";
    } else if (state.queueSearch) {
      emptyTitle.textContent = "No matching downloads";
      emptyText.textContent = "Try another title, URL, or job ID.";
    } else if (state.filter === "active") {
      emptyTitle.textContent = "No active downloads";
      emptyText.textContent = "Queued and running downloads show up here.";
    } else if (state.filter === "done") {
      emptyTitle.textContent = "No completed downloads";
      emptyText.textContent = "Finished downloads will be listed here.";
    } else {
      emptyTitle.textContent = "No failed downloads";
      emptyText.textContent = "Failed and cancelled downloads will be listed here.";
    }
  }
}

function notify(job, kind) {
  if (!settings.notifications) return;
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  if (!document.hidden) return;
  try {
    const note = new Notification(kind === "completed" ? "Download complete" : "Download failed", {
      body: truncate(job.title || "Download", 120),
      tag: `aio-${job.id}`,
    });
    note.onclick = () => window.focus();
  } catch {
    /* notifications may be blocked */
  }
}

function syncJobs(jobs) {
  const seen = new Set();
  let added = false;

  for (const job of jobs) {
    seen.add(job.id);
    let entry = state.jobs.get(job.id);
    if (!entry) {
      const el = createJobEl(job);
      entry = { el, status: job.status, data: job };
      state.jobs.set(job.id, entry);
      added = true;
    } else {
      entry.data = job;
    }
    updateJobEl(entry.el, job);
    entry.el.classList.toggle("hidden", !matchesFilter(job));
    if (entry.status !== job.status) {
      if (job.status === "completed") {
        toast(`Download complete · ${truncate(job.title, 60)}`, "success");
        notify(job, "completed");
      } else if (job.status === "error") {
        toast(`Failed · ${truncate(job.error || job.title, 100)}`, "error", 7000);
        notify(job, "error");
      }
      entry.status = job.status;
    }
  }

  for (const [id, entry] of state.jobs) {
    if (!seen.has(id)) {
      entry.el.remove();
      state.jobs.delete(id);
    }
  }

  if (added) {
    for (const job of [...jobs].reverse()) {
      const entry = state.jobs.get(job.id);
      if (entry) jobList.prepend(entry.el);
    }
  }

  updateQueueChrome();
}

async function refreshJobs() {
  if (refreshing) return;
  refreshing = true;
  try {
    const jobs = await api("/api/jobs");
    syncJobs(jobs);
  } catch {
    /* server may be restarting; try again on next tick */
  } finally {
    refreshing = false;
  }
}

async function cancelJob(id) {
  try {
    await api(`/api/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" });
    toast("Download cancelled", "info");
    refreshJobs();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function retryJob(id) {
  try {
    await api(`/api/jobs/${encodeURIComponent(id)}/retry`, { method: "POST" });
    window.AllN1DownloaderAndroid?.onDownloadQueued?.();
    toast("Retrying download", "info");
    refreshJobs();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function retryFailedJobs() {
  const failed = [...state.jobs.entries()]
    .filter(([, entry]) =>
      (entry.data.status === "error" || entry.data.status === "cancelled") && entry.data.can_retry
    );
  if (!failed.length) return;
  retryFailedBtn.disabled = true;
  const previousLabel = retryFailedBtn.textContent;
  retryFailedBtn.textContent = "Retrying…";
  const results = await Promise.allSettled(
    failed.map(([id]) => api(`/api/jobs/${encodeURIComponent(id)}/retry`, { method: "POST" }))
  );
  const retried = results.filter((result) => result.status === "fulfilled").length;
  retryFailedBtn.disabled = false;
  retryFailedBtn.textContent = previousLabel;
  if (retried) window.AllN1DownloaderAndroid?.onDownloadQueued?.();
  toast(retried ? `Retrying ${retried} download${retried === 1 ? "" : "s"}` : "Could not retry downloads", retried ? "success" : "error");
  refreshJobs();
}

function focusJob(id) {
  const flash = (entry) => {
    if (!entry) return;
    entry.el.scrollIntoView({ behavior: "smooth", block: "center" });
    entry.el.classList.add("flash");
    setTimeout(() => entry.el.classList.remove("flash"), 1800);
  };
  const entry = state.jobs.get(id);
  if (entry) {
    flash(entry);
    return;
  }
  refreshJobs().then(() => flash(state.jobs.get(id)));
}

async function deleteJob(id) {
  const entry = state.jobs.get(id);
  const title = entry && entry.data ? entry.data.title : "this download";
  if (!confirm(`Delete "${title}" and its downloaded files?`)) return;
  try {
    await api(`/api/jobs/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (entry) {
      entry.el.remove();
      state.jobs.delete(id);
    }
    updateQueueChrome();
    toast("Deleted", "info");
    refreshJobs();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function forgetJob(id) {
  const entry = state.jobs.get(id);
  const title = entry && entry.data ? entry.data.title : "this download";
  if (!confirm(`Remove "${title}" from history? The downloaded files stay in the downloads folder.`)) return;
  try {
    await api(`/api/jobs/${encodeURIComponent(id)}/forget`, { method: "POST" });
    if (entry) {
      entry.el.remove();
      state.jobs.delete(id);
    }
    updateQueueChrome();
    toast("Removed from history", "info");
    refreshJobs();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function openFolder(id) {
  try {
    const result = await api(`/api/jobs/${encodeURIComponent(id)}/reveal`, { method: "POST" });
    if (result.path) window.AllN1DownloaderAndroid?.openFolder?.(result.path);
  } catch (error) {
    toast(error.message, "error");
  }
}

async function openFile(id) {
  try {
    const result = await api(`/api/jobs/${encodeURIComponent(id)}/open-file`, { method: "POST" });
    if (result.path) window.AllN1DownloaderAndroid?.openFile?.(result.path);
  } catch (error) {
    toast(error.message, "error");
  }
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch {
      ok = false;
    }
    area.remove();
    return ok;
  }
}

async function copyPath(id) {
  const entry = state.jobs.get(id);
  if (!entry) return;
  const path = entry.data.dir || "";
  const ok = await copyText(path);
  toast(ok ? "Folder path copied" : "Could not copy the path", ok ? "success" : "error");
}

async function clearFinished() {
  if (!confirm("Remove all finished, failed and cancelled downloads, including their files?")) return;
  try {
    const result = await api("/api/jobs/clear-finished", { method: "POST" });
    toast(result.removed ? `Cleared ${result.removed} download(s)` : "Nothing to clear", "info");
    refreshJobs();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function openDownloads() {
  try {
    const result = await api("/api/open-downloads", { method: "POST" });
    if (result.path) window.AllN1DownloaderAndroid?.openDownloads?.(result.path);
  } catch (error) {
    toast(error.message, "error");
  }
}

function addInfoRow(label, value) {
  const row = document.createElement("div");
  row.className = "info-row";
  const key = document.createElement("span");
  key.textContent = label;
  const val = document.createElement("b");
  val.textContent = value;
  row.append(key, val);
  settingsInfo.append(row);
}

function renderHealthInfo(health) {
  settingsInfo.innerHTML = "";
  if (!health) {
    addInfoRow("Status", "Offline");
    return;
  }
  addInfoRow("Version", health.version);
  addInfoRow("yt-dlp", health.yt_dlp);
  addInfoRow("FFmpeg", health.ffmpeg ? "Ready" : "Missing");
  addInfoRow("JS runtime", health.js_runtime || "None");
  if (health.update) {
    const updateStatus = health.update.available
      ? `Version ${health.update.latest_version} available`
      : ({ current: "Up to date", checking: "Checking…", no_release: "No release published",
           release_asset_missing: "No package for this platform" })[health.update.status] || "Unavailable";
    addInfoRow("App updates", updateStatus);
  }
  addInfoRow(
    "Disk free",
    health.disk_total ? `${formatBytes(health.disk_free)} of ${formatBytes(health.disk_total)}` : "Unknown"
  );
}

async function loadHealth() {
  try {
    const health = await api("/api/health");
    state.health = health;
    state.platform = health.platform || "desktop";
    state.distribution = health.distribution || "source";
    state.update = health.update || null;
    const android = state.platform === "android";
    $("#notifyLabel").classList.toggle("hidden", android);
    $("#cookiesControl").classList.toggle("hidden", android);
    if (android) {
      settings.cookies = "";
      settings.notifications = false;
      cookiesSelect.value = "";
      notifyCheck.checked = false;
      saveSettings();
      $("#connectionHint").textContent = "Proxy settings apply to this device. Browser-cookie extraction is not available in the Android app.";
    }
    engineBadge.classList.toggle("ok", Boolean(health.ffmpeg));
    engineBadge.classList.toggle("warn", !health.ffmpeg);
    engineText.textContent = `yt-dlp ${health.yt_dlp}${health.ffmpeg ? "" : " · FFmpeg missing"}`;
    engineBadge.title = [
      `AllN1Downloader v${health.version}`,
      `yt-dlp ${health.yt_dlp}`,
      health.ffmpeg ? `FFmpeg: ${health.ffmpeg_path}` : "FFmpeg not found",
      health.js_runtime ? `JS runtime: ${health.js_runtime}` : "",
    ].filter(Boolean).join(" · ");
    versionInfo.textContent = `AllN1Downloader v${health.version}`;
    renderUpdateButton();
    if (state.update && state.update.status === "checking") {
      setTimeout(refreshUpdateStatus, 1500);
    }
    diskInfo.textContent = health.disk_total
      ? `${formatBytes(health.disk_free)} free of ${formatBytes(health.disk_total)}`
      : "";
    renderHealthInfo(health);
  } catch {
    state.health = null;
    engineBadge.classList.remove("ok");
    engineBadge.classList.add("warn");
    engineText.textContent = "engine offline";
    renderHealthInfo(null);
  }
}

function renderUpdateButton() {
  const update = state.update;
  const visible = Boolean(update?.available && state.platform !== "android");
  updateBtn.classList.toggle("hidden", !visible);
  updateBtn.disabled = false;
  if (!visible) return;
  updateBtn.textContent = state.distribution === "frozen" && update.platform === "windows"
    ? `Install v${update.latest_version}`
    : state.distribution === "frozen" && update.platform === "linux"
      ? `APT update v${update.latest_version}`
      : `Get v${update.latest_version}`;
  updateBtn.title = `Current version ${update.current_version}; ${update.latest_version} is available`;
}

async function refreshUpdateStatus(attemptsRemaining = 8) {
  let update;
  try {
    update = await api("/api/update", { signal: AbortSignal.timeout(4000) });
  } catch {
    update = { status: "unavailable", available: false };
  }
  if (update.status === "checking" && attemptsRemaining <= 1) {
    update = { ...update, status: "unavailable", available: false };
  }
  state.update = update;
  if (state.health) {
    state.health = { ...state.health, update };
    renderHealthInfo(state.health);
  }
  renderUpdateButton();
  if (update.status === "checking") setTimeout(() => refreshUpdateStatus(attemptsRemaining - 1), 2500);
}

async function applyApplicationUpdate() {
  const update = state.update;
  if (!update || !update.available) return;
  if (state.distribution === "frozen" && ["windows", "linux"].includes(update.platform)) {
    updateBtn.disabled = true;
    updateBtn.textContent = "Preparing update…";
    try {
      const result = await api("/api/update/apply", { method: "POST" });
      if (result.status === "restarting") toast(`Installing AllN1Downloader ${result.version}…`, "success", 6000);
      else if (result.status === "installing") toast("Package update started. Reopen the app when it finishes.", "success", 7000);
      else if (result.release_url) window.open(result.release_url, "_blank", "noopener");
    } catch (error) {
      toast(error.message || "Update could not be installed", "error", 7000);
      renderUpdateButton();
    }
    return;
  }
  if (update.release_url) window.open(update.release_url, "_blank", "noopener");
}

function setSource(source) {
  state.source = source;
  for (const button of sourceTabs.querySelectorAll(".source-tab")) {
    const active = button.dataset.source === source;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  }
  const batch = source === "batch";
  $("#analysisStatus").classList.toggle("hidden", batch);
  mediaCard.classList.toggle("hidden", batch || !state.info || state.sourceUrl !== urlInput.value.trim());
  analyzeForm.classList.toggle("hidden", batch);
  batchBox.classList.toggle("hidden", !batch);
  if (batch) batchInput.focus();
  else urlInput.focus();
}

function applyFilter(filter) {
  state.filter = filter;
  for (const button of filters.querySelectorAll(".filter")) {
    const active = button.dataset.filter === filter;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  }
  for (const entry of state.jobs.values()) {
    entry.el.classList.toggle("hidden", !matchesFilter(entry.data));
  }
  updateQueueChrome();
}

analyzeForm.addEventListener("submit", analyze);
urlInput.addEventListener("input", () => {
  mediaCard.classList.add("hidden");
  state.info = null;
  urlInput.removeAttribute("aria-invalid");
  $("#analysisStatus").textContent = "";
});
pasteBtn.addEventListener("click", async () => {
  try {
    const text = (await navigator.clipboard.readText()).trim();
    if (!text) {
      toast("Clipboard is empty", "info");
      return;
    }
    urlInput.value = text;
    urlInput.dispatchEvent(new Event("input"));
    urlInput.focus();
  } catch {
    urlInput.focus();
    toast("Press Ctrl+V to paste your link", "info");
  }
});

sourceTabs.addEventListener("click", (event) => {
  const button = event.target.closest(".source-tab");
  if (button) setSource(button.dataset.source);
});

modeSwitch.addEventListener("click", (event) => {
  const button = event.target.closest(".seg");
  if (button) setMode(button.dataset.mode);
});

qualitySelect.addEventListener("change", () => {
  state.activePreset = "";
  renderPresets();
  syncCodecs();
  updateEstimate();
  updateSelectionUI();
});

codecSelect.addEventListener("change", () => {
  state.activePreset = "";
  renderPresets();
  updateEstimate();
  updateSelectionUI();
});

formatSelect.addEventListener("change", () => {
  state.activePreset = "";
  renderPresets();
  syncBitrates();
  syncEmbed();
  updateEstimate();
  updateSelectionUI();
});

bitrateSelect.addEventListener("change", () => {
  state.activePreset = "";
  renderPresets();
  updateEstimate();
});

presetButtons.addEventListener("click", (event) => {
  const button = event.target.closest(".preset-btn");
  if (button) applyPreset(button.dataset.preset);
});

subsCheck.addEventListener("change", () => {
  subLangWrap.classList.toggle("hidden", !subsCheck.checked);
});

embedCheck.addEventListener("change", () => {
  settings.embed = embedCheck.checked;
  saveSettings();
});

sponsorCheck.addEventListener("change", () => {
  settings.sponsorblock = sponsorCheck.checked;
  saveSettings();
});

cookiesSelect.addEventListener("change", () => {
  settings.cookies = cookiesSelect.value;
  saveSettings();
});

ratelimitSelect.addEventListener("change", () => {
  settings.ratelimit = ratelimitSelect.value;
  saveSettings();
});

proxyInput.addEventListener("change", () => {
  settings.proxy = proxyInput.value.trim();
  proxyInput.value = settings.proxy;
  saveSettings();
});

notifyCheck.addEventListener("change", async () => {
  if (notifyCheck.checked) {
    if (!("Notification" in window)) {
      notifyCheck.checked = false;
      toast("This browser does not support notifications", "error");
      return;
    }
    if (Notification.permission !== "granted") {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        notifyCheck.checked = false;
        settings.notifications = false;
        saveSettings();
        toast("Notification permission was not granted", "error");
        return;
      }
    }
  }
  settings.notifications = notifyCheck.checked;
  saveSettings();
});

swatches.addEventListener("click", (event) => {
  const button = event.target.closest(".swatch");
  if (!button) return;
  settings.theme = button.dataset.theme;
  applyTheme(settings.theme);
  updateSwatches();
  saveSettings();
});

settingsBtn.addEventListener("click", () => settingsPanel.showModal());
closeSettings.addEventListener("click", () => settingsPanel.close());
settingsPanel.addEventListener("click", (event) => {
  if (event.target !== settingsPanel) return;
  const rect = settingsPanel.getBoundingClientRect();
  if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) settingsPanel.close();
});

batchMode.addEventListener("change", () => syncBatchFormats());
batchQuality.addEventListener("change", () => {
  settings.batch.quality = batchQuality.value;
  saveSettings();
});
batchFormat.addEventListener("change", () => {
  settings.batch.format = batchFormat.value;
  saveSettings();
});
batchBtn.addEventListener("click", submitBatch);

selectAll.addEventListener("change", () => {
  if (!state.info) return;
  for (const checkbox of playlistList.querySelectorAll('input[type="checkbox"]')) {
    checkbox.checked = selectAll.checked;
  }
  state.selected = selectAll.checked
    ? new Set(state.info.entries.map((entry) => entry.index))
    : new Set();
  updateSelectionUI();
});

invertBtn.addEventListener("click", () => {
  if (!state.info) return;
  for (const checkbox of playlistList.querySelectorAll('input[type="checkbox"]')) {
    checkbox.checked = !checkbox.checked;
    const index = Number(checkbox.dataset.index);
    if (checkbox.checked) state.selected.add(index);
    else state.selected.delete(index);
  }
  updateSelectionUI();
});

plSearch.addEventListener("input", () => {
  const query = plSearch.value.trim().toLowerCase();
  for (const item of playlistList.children) {
    item.classList.toggle("hidden", Boolean(query) && !item.dataset.title.includes(query));
  }
});

filters.addEventListener("click", (event) => {
  const button = event.target.closest(".filter");
  if (button) applyFilter(button.dataset.filter);
});

queueSearch.addEventListener("input", () => {
  state.queueSearch = queueSearch.value.trim();
  applyFilter(state.filter);
});

downloadBtn.addEventListener("click", startDownload);
clearBtn.addEventListener("click", clearFinished);
retryFailedBtn.addEventListener("click", retryFailedJobs);
openDownloadsBtn.addEventListener("click", openDownloads);
updateBtn.addEventListener("click", applyApplicationUpdate);

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshJobs();
});

document.addEventListener("keydown", (event) => {
  if (settingsPanel.open) return;
  if (event.key === "Escape") {
    dropOverlay.classList.remove("active");
    dragDepth = 0;
  }
  if (event.key === "/" && !isTyping(event.target)) {
    event.preventDefault();
    (state.source === "batch" ? batchInput : urlInput).focus();
  }
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    if (state.source === "batch") submitBatch();
    else if (!mediaCard.classList.contains("hidden")) startDownload();
    else analyzeForm.requestSubmit();
  }
});

window.addEventListener("dragenter", (event) => {
  const types = event.dataTransfer ? [...event.dataTransfer.types] : [];
  if (!types.includes("text/plain") && !types.includes("text/uri-list")) return;
  dragDepth += 1;
  dropOverlay.classList.add("active");
});

window.addEventListener("dragover", (event) => event.preventDefault());

window.addEventListener("dragleave", () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) dropOverlay.classList.remove("active");
});

window.addEventListener("drop", (event) => {
  event.preventDefault();
  dragDepth = 0;
  dropOverlay.classList.remove("active");
  const text = (event.dataTransfer && (event.dataTransfer.getData("text/uri-list") || event.dataTransfer.getData("text/plain"))) || "";
  const url = text.split(/\r?\n/).map((line) => line.trim()).find((line) => /^https?:\/\//i.test(line));
  if (!url) {
    toast("Drop a link starting with http(s)", "error");
    return;
  }
  setSource("single");
  urlInput.value = url;
  analyze();
});

applySettingsToUI();
batchMode.value = settings.batch.mode;
batchQuality.value = settings.batch.quality;
syncBatchFormats(settings.batch.format);
loadHealth();
refreshJobs();
setInterval(refreshJobs, 1200);
setInterval(loadHealth, 60000);
