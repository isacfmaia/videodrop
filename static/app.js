// DOM references and shared UI state.
const form = document.querySelector("#probeForm");
const input = document.querySelector("#urlInput");
const results = document.querySelector("#results");
const previewFrame = document.querySelector("#previewFrame");
const previewTitle = document.querySelector("#previewTitle");
const previewMeta = document.querySelector("#previewMeta");
const statusPill = document.querySelector("#statusPill");
const pasteHint = document.querySelector("#pasteHint");
const formatTemplate = document.querySelector("#formatTemplate");
const themeToggle = document.querySelector("#themeToggle");
const primaryButton = form.querySelector(".primary-button");
const copyrightYear = document.querySelector("#copyrightYear");
const shareSheet = document.querySelector("#shareSheet");
const shareSheetMeta = document.querySelector("#shareSheetMeta");
const shareNowButton = document.querySelector("#shareNowButton");
const shareSheetDownload = document.querySelector("#shareSheetDownload");
const shareSheetClose = document.querySelector("#shareSheetClose");
const shareSheetCancel = document.querySelector("#shareSheetCancel");
const screenRecordButton = document.querySelector("#screenRecordButton");
const systemAudioToggle = document.querySelector("#systemAudioToggle");
const microphoneToggle = document.querySelector("#microphoneToggle");
const recorderSupportNote = document.querySelector("#recorderSupportNote");
const browserAuthPanel = document.querySelector("#browserAuthPanel");
const browserAuthToggle = document.querySelector("#browserAuthToggle");
const browserLoginButton = document.querySelector("#browserLoginButton");
const recordingDock = document.querySelector("#recordingDock");
const recordingTimer = document.querySelector("#recordingTimer");
const recordingStopButton = document.querySelector("#recordingStopButton");
const ANALYZE_TIMEOUT_MS = 120000;
const DOWNLOAD_READY_TIMEOUT_MS = 30 * 60 * 1000;
const DOWNLOAD_READY_POLL_MS = 400;
const DOWNLOAD_READY_COOKIE_PREFIX = "videodrop_download_";
const BROWSER_AUTH_ENABLED_STORAGE_KEY = "videodrop-browser-auth-enabled";
const DEDICATED_LOGIN_ERROR_MARKERS = [
  "instagram nao entregou",
  "instagram ainda nao entregou",
  "login dedicado do videodrop",
  "cookies do login dedicado"
];
const RECORDER_MIME_TYPES = [
  "video/webm;codecs=vp9,opus",
  "video/webm;codecs=vp8,opus",
  "video/webm"
];
const CAPTION_LANGUAGE = "pt-BR";
const MICROPHONE_REQUEST_TIMEOUT_MS = 10000;

let currentUrl = "";
let currentData = null;
let activeController = null;
let analyzeRunId = 0;
let preparedSharePayload = null;
let preparedShareObjectUrl = "";
let screenStream = null;
let microphoneStream = null;
let recordingStream = null;
let recordingAudioContext = null;
let recordingAudioSources = [];
let mediaRecorder = null;
let recordedChunks = [];
let recordingObjectUrl = "";
let recordingStartedAt = 0;
let recordingTimerId = 0;
let recordingStopping = false;
let recordingMetaSuffix = "WebM local";
let recordingWarningMessage = "";
let captionsRequestedForRecording = false;
let captionsSupportedForRecording = false;
let captionRecognition = null;
let captionRecognitionActive = false;
let captionRestartTimerId = 0;
let captionSegments = [];
let captionInterimText = "";
let captionLastSegmentEnd = 0;
let captionObjectUrl = "";
let captionStatusMessage = "";

// Theme handling.
function setTheme(theme, persist = true) {
  document.documentElement.dataset.theme = theme;
  themeToggle?.setAttribute("aria-label", theme === "dark" ? "Ativar tema claro" : "Ativar tema escuro");
  themeToggle?.setAttribute("title", theme === "dark" ? "Ativar tema claro" : "Ativar tema escuro");
  if (persist) localStorage.setItem("videodrop-theme", theme);
}

function setupTheme() {
  const storedTheme = localStorage.getItem("videodrop-theme");
  const canDetectTheme = typeof matchMedia === "function";
  const prefersLight = canDetectTheme && matchMedia("(prefers-color-scheme: light)").matches;
  setTheme(storedTheme || (prefersLight ? "light" : "dark"), Boolean(storedTheme));

  if (!storedTheme && canDetectTheme) {
    matchMedia("(prefers-color-scheme: light)").addEventListener("change", (event) => {
      if (!localStorage.getItem("videodrop-theme")) setTheme(event.matches ? "light" : "dark", false);
    });
  }
}

function browserCookieAuthAvailable() {
  return ["localhost", "127.0.0.1", "::1"].includes(window.location.hostname);
}

function isInstagramUrl(value) {
  try {
    const url = new URL(value.trim());
    const host = url.hostname.toLowerCase();
    return host === "instagram.com" || host.endsWith(".instagram.com");
  } catch {
    return false;
  }
}

function activeCookieBrowser(urlValue = currentUrl || input?.value || "") {
  if (!browserCookieAuthAvailable() || !browserAuthToggle?.checked) return "";
  return isInstagramUrl(urlValue) ? "firefox" : "";
}

function syncBrowserAuthSelectState() {
  if (browserLoginButton && browserAuthToggle) {
    browserLoginButton.disabled = !browserAuthToggle.checked;
  }
}

function setupBrowserAuthControls() {
  if (!browserAuthPanel || !browserAuthToggle || !browserLoginButton) return;
  if (!browserCookieAuthAvailable()) return;

  browserAuthPanel.hidden = false;
  browserAuthToggle.checked = localStorage.getItem(BROWSER_AUTH_ENABLED_STORAGE_KEY) === "1";
  syncBrowserAuthSelectState();

  browserAuthToggle.addEventListener("change", () => {
    localStorage.setItem(BROWSER_AUTH_ENABLED_STORAGE_KEY, browserAuthToggle.checked ? "1" : "0");
    syncBrowserAuthSelectState();
  });
  browserLoginButton.addEventListener("click", openDedicatedInstagramLogin);
}

function enableDedicatedLogin() {
  if (!browserAuthToggle) return;
  browserAuthToggle.checked = true;
  localStorage.setItem(BROWSER_AUTH_ENABLED_STORAGE_KEY, "1");
  syncBrowserAuthSelectState();
}

async function openDedicatedInstagramLogin() {
  if (!browserCookieAuthAvailable() || !browserLoginButton) return;

  enableDedicatedLogin();
  const previousLabel = browserLoginButton.textContent;
  browserLoginButton.disabled = true;
  browserLoginButton.textContent = "Abrindo...";
  pasteHint.textContent = "Abrindo login do Instagram no Firefox...";

  try {
    const response = await fetch("/api/browser-login/instagram", { method: "POST" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "Nao consegui abrir o Firefox.");
    pasteHint.textContent = "Faca login no Instagram pela janela do Firefox aberta pelo VideoDrop.";
  } catch (error) {
    setError(error.message);
  } finally {
    browserLoginButton.textContent = previousLabel;
    syncBrowserAuthSelectState();
  }
}

// Small formatting and timing helpers used by multiple UI states.
function isProbablyUrl(value) {
  try {
    const url = new URL(value.trim());
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function formatBytes(bytes, estimated = false) {
  if (!bytes) return "tamanho indisponível";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const precision = value >= 10 || unit === 0 ? 0 : 1;
  return `${estimated ? "~" : ""}${value.toFixed(precision)} ${units[unit]}`;
}

function formatDuration(seconds) {
  if (!seconds) return "";
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${mins}:${secs}`;
}

function formatClock(seconds) {
  const totalSeconds = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(totalSeconds / 3600);
  const mins = Math.floor((totalSeconds % 3600) / 60).toString().padStart(2, "0");
  const secs = Math.floor(totalSeconds % 60).toString().padStart(2, "0");
  return hours ? `${hours}:${mins}:${secs}` : `${mins}:${secs}`;
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[char]));
}

function shouldOfferDedicatedLogin(message) {
  if (!browserCookieAuthAvailable() || !browserAuthToggle || !browserLoginButton) return false;
  const normalizedMessage = message.toLowerCase();
  return DEDICATED_LOGIN_ERROR_MARKERS.some((marker) => normalizedMessage.includes(marker));
}

function renderErrorActions(message) {
  if (!shouldOfferDedicatedLogin(message)) return "";
  return `
    <div class="error-actions">
      <button class="ghost-button error-retry-button" type="button" data-open-instagram-login>
        Entrar no Instagram
      </button>
      <button class="ghost-button error-retry-button" type="button" data-retry-dedicated-login>
        Tentar com login
      </button>
      <p>Use a janela do Firefox aberta pelo VideoDrop.</p>
    </div>
  `;
}

function wireErrorActions() {
  const loginButton = results.querySelector("[data-open-instagram-login]");
  loginButton?.addEventListener("click", openDedicatedInstagramLogin);

  const retryButton = results.querySelector("[data-retry-dedicated-login]");
  if (!retryButton) return;
  retryButton.addEventListener("click", () => {
    enableDedicatedLogin();
    pasteHint.textContent = "Tentando de novo com Login dedicado...";
    if (currentUrl) analyze(currentUrl);
  });
}

function waitForPaint() {
  return new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(resolve));
  });
}

function setAnalyzingState(isAnalyzing) {
  primaryButton.disabled = isAnalyzing;
  primaryButton.classList.toggle("is-loading", isAnalyzing);
  primaryButton.querySelector("span").textContent = isAnalyzing ? "Analisando" : "Analisar";
  input.setAttribute("aria-busy", String(isAnalyzing));
}

// Preview and results rendering.
function setLoading(url) {
  statusPill.textContent = "Analisando link";
  previewTitle.textContent = "Buscando o vídeo...";
  previewMeta.textContent = url;
  renderThumbnailLoading("Analisando link");
  results.innerHTML = `
    <div class="loading-state">
      <img class="loading-brand" src="/videodrop_loader_animado.svg" alt="" aria-hidden="true" />
      <p>Consultando resoluções e tamanhos disponíveis.</p>
    </div>
    <div class="format-card skeleton-card" aria-hidden="true">
      <div>
        <span></span>
        <p></p>
      </div>
      <div class="format-actions">
        <i></i>
        <i></i>
      </div>
    </div>
    <div class="format-card skeleton-card" aria-hidden="true">
      <div>
        <span></span>
        <p></p>
      </div>
      <div class="format-actions">
        <i></i>
        <i></i>
      </div>
    </div>
  `;
}

function setError(message) {
  statusPill.textContent = "Não foi possível carregar";
  previewTitle.textContent = "Oops, não deu certo";
  previewMeta.textContent = "Tente outro link público ou confira se o conteúdo exige login.";
  renderPreviewError();
  results.innerHTML = `
    <div class="error-state">
      <p>${escapeHtml(message)}</p>
      ${renderErrorActions(message)}
    </div>
  `;
  wireErrorActions();
}

function setRecorderStartError(message) {
  statusPill.textContent = "Gravação não iniciada";
  previewTitle.textContent = "Não consegui gravar";
  previewMeta.textContent = "Confira as permissões do navegador e tente novamente.";
  renderPreviewError();
  results.innerHTML = `<div class="error-state"><p>${message}</p></div>`;
}

function renderPreviewPlaceholder() {
  previewFrame.innerHTML = `
    <div class="preview-placeholder">
      <svg class="play-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M8 5v14l11-7Z" />
      </svg>
    </div>
  `;
}

function renderPreviewError() {
  previewFrame.innerHTML = `
    <div class="preview-error-icon" aria-hidden="true">!</div>
  `;
}

function renderThumbnailLoading(label = "Carregando miniatura") {
  previewFrame.innerHTML = `
    <div class="thumbnail-loading" aria-label="${label}">
      <img class="thumbnail-loader-brand" src="/videodrop_loader_animado.svg" alt="" aria-hidden="true" />
      <span>${label}</span>
    </div>
  `;
}

function renderPreview(data) {
  statusPill.textContent = `${data.site} detectado`;
  previewTitle.textContent = data.title;
  const videoFormats = data.formats.filter((format) => !isAudioFormat(format));
  const hasAudioMp3 = data.formats.some(isAudioFormat);
  previewMeta.textContent = [
    data.duration ? formatDuration(data.duration) : null,
    `${videoFormats.length} ${videoFormats.length === 1 ? "resolução" : "resoluções"} em MP4`,
    hasAudioMp3 ? "áudio MP3 disponível" : null,
    data.can_merge ? "merge de audio ativo" : "somente formatos com audio"
  ].filter(Boolean).join(" - ");

  const thumbnailUrl = data.thumbnail_proxy || data.thumbnail;
  if (thumbnailUrl) {
    renderThumbnailLoading();
    const image = document.createElement("img");
    image.alt = "Miniatura do vídeo";
    image.loading = "lazy";
    image.referrerPolicy = "no-referrer";
    image.className = "is-loading";
    image.addEventListener("load", () => {
      image.classList.remove("is-loading");
      previewFrame.querySelector(".thumbnail-loading")?.remove();
    });
    image.addEventListener("error", () => {
      if (data.thumbnail && image.src !== data.thumbnail) {
        image.src = data.thumbnail;
        return;
      }
      renderPreviewPlaceholder();
    });
    previewFrame.appendChild(image);
    image.src = thumbnailUrl;
  } else {
    renderPreviewPlaceholder();
  }
}

// Format actions and download/share helpers.
function downloadUrl(formatId, downloadToken = "") {
  const params = new URLSearchParams({ url: currentUrl, format_id: formatId });
  if (downloadToken) params.set("download_token", downloadToken);
  const cookieBrowser = activeCookieBrowser(currentUrl);
  if (cookieBrowser) params.set("cookie_browser", cookieBrowser);
  return `/api/download?${params.toString()}`;
}

function isAudioFormat(format) {
  return format.kind === "audio" || format.format_id === "audio-mp3";
}

function shareFileName(format) {
  return isAudioFormat(format) ? "videodrop-audio.mp3" : `videodrop-video-${format.resolution}.mp4`;
}

function shareMimeType(format) {
  return isAudioFormat(format) ? "audio/mpeg" : "video/mp4";
}

function resetPasteHint(delay = 1200) {
  window.setTimeout(() => {
    pasteHint.textContent = "Ctrl + V em qualquer lugar detecta URLs automaticamente";
    pasteHint.classList.remove("flash");
  }, delay);
}

function createDownloadToken() {
  const tokenSource = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return tokenSource.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 48);
}

function hasCookie(name) {
  return document.cookie.split("; ").some((cookie) => cookie.startsWith(`${name}=`));
}

function clearCookie(name) {
  document.cookie = `${name}=; Max-Age=0; path=/`;
}

function waitForDownloadReady(cookieName) {
  return new Promise((resolve) => {
    const startedAt = Date.now();
    const intervalId = window.setInterval(() => {
      if (hasCookie(cookieName)) {
        window.clearInterval(intervalId);
        clearCookie(cookieName);
        resolve(true);
        return;
      }

      if (Date.now() - startedAt > DOWNLOAD_READY_TIMEOUT_MS) {
        window.clearInterval(intervalId);
        resolve(false);
      }
    }, DOWNLOAD_READY_POLL_MS);
  });
}

function setDownloadState(triggerLink, isLoading) {
  triggerLink.dataset.loading = isLoading ? "1" : "0";
  triggerLink.classList.toggle("is-loading", isLoading);
  triggerLink.setAttribute("aria-busy", String(isLoading));
  triggerLink.textContent = isLoading ? "Preparando..." : (triggerLink.dataset.originalText || "Baixar");
}

function startBrowserDownload(href) {
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = "";
  anchor.rel = "noopener";
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

async function prepareDownload(format, triggerLink, event) {
  event.preventDefault();
  if (triggerLink.dataset.loading === "1") {
    return;
  }

  const downloadToken = createDownloadToken();
  const cookieName = `${DOWNLOAD_READY_COOKIE_PREFIX}${downloadToken}`;
  const href = downloadUrl(format.format_id, downloadToken);
  triggerLink.dataset.originalText = triggerLink.textContent;
  triggerLink.href = href;
  setDownloadState(triggerLink, true);
  pasteHint.textContent = "Preparando download...";
  pasteHint.classList.add("flash");
  startBrowserDownload(href);

  const isReady = await waitForDownloadReady(cookieName);
  setDownloadState(triggerLink, false);
  pasteHint.textContent = isReady
    ? "Download pronto. Confira a barra de downloads do navegador."
    : "O download ainda pode estar em andamento no navegador.";
  pasteHint.classList.add("flash");
  resetPasteHint(isReady ? 2200 : 5200);
}

// Screen recording flow.
function screenRecordingSupported() {
  return Boolean(navigator.mediaDevices?.getDisplayMedia && window.MediaRecorder);
}

function screenRecordingUnsupportedMessage() {
  if (!window.isSecureContext) {
    return "Gravação de tela indisponível nesta origem. Abra pelo app ou por http://127.0.0.1:8000.";
  }
  return "Gravação de tela indisponível neste navegador. Use Chrome ou Edge em HTTPS ou localhost.";
}

function setRecorderButtonState(state) {
  if (!screenRecordButton) return;

  screenRecordButton.classList.toggle("is-loading", state === "starting");
  screenRecordButton.disabled = state !== "idle";
  const label = screenRecordButton.querySelector("span");
  if (!label) return;

  if (state === "unsupported") label.textContent = "Indisponível";
  else if (state === "starting") label.textContent = "Abrindo seletor";
  else if (state === "recording") label.textContent = "Gravando";
  else label.textContent = "Gravar tela";
}

function setupScreenRecorderSupport() {
  if (!screenRecordButton) return;

  if (!screenRecordingSupported()) {
    setRecorderButtonState("unsupported");
    if (recorderSupportNote) {
      recorderSupportNote.textContent = screenRecordingUnsupportedMessage();
    }
    return;
  }

  setRecorderButtonState("idle");
}

function selectRecorderMimeType() {
  if (!window.MediaRecorder?.isTypeSupported) return "";
  return RECORDER_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

function recordingFileName() {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  return `videodrop-gravacao-${stamp}.webm`;
}

function captionFileName(videoFileName) {
  return videoFileName.replace(/\.webm$/i, ".srt") || "videodrop-gravacao.srt";
}

function clearRecordingObjectUrl() {
  if (recordingObjectUrl) URL.revokeObjectURL(recordingObjectUrl);
  recordingObjectUrl = "";
}

function clearCaptionObjectUrl() {
  if (captionObjectUrl) URL.revokeObjectURL(captionObjectUrl);
  captionObjectUrl = "";
}

function clearRecordingResultState() {
  clearRecordingObjectUrl();
  clearCaptionObjectUrl();
  captionSegments = [];
  captionInterimText = "";
  captionLastSegmentEnd = 0;
  captionsRequestedForRecording = false;
  captionsSupportedForRecording = false;
  captionStatusMessage = "";
}

function stopStreamTracks(stream) {
  stream?.getTracks().forEach((track) => track.stop());
}

function speechRecognitionConstructor() {
  return window.SpeechRecognition || window.webkitSpeechRecognition;
}

function speechRecognitionSupported() {
  return Boolean(speechRecognitionConstructor());
}

function normalizeCaptionText(text) {
  return (text || "").replace(/\s+/g, " ").trim();
}

function captionElapsedSeconds() {
  return recordingStartedAt ? (Date.now() - recordingStartedAt) / 1000 : 0;
}

function estimateCaptionDurationSeconds(text) {
  const wordCount = normalizeCaptionText(text).split(" ").filter(Boolean).length;
  return Math.min(6, Math.max(1.2, wordCount * 0.42));
}

function appendCaptionSegment(text) {
  const cleanText = normalizeCaptionText(text);
  if (!cleanText) return;

  const end = Math.max(captionElapsedSeconds(), captionLastSegmentEnd + 0.4);
  const estimatedStart = Math.max(0, end - estimateCaptionDurationSeconds(cleanText));
  const start = Math.max(captionLastSegmentEnd, estimatedStart);
  captionSegments.push({ start, end, text: cleanText });
  captionLastSegmentEnd = end;
}

function formatSrtTimestamp(seconds) {
  const totalMilliseconds = Math.max(0, Math.floor(seconds * 1000));
  const milliseconds = (totalMilliseconds % 1000).toString().padStart(3, "0");
  const totalSeconds = Math.floor(totalMilliseconds / 1000);
  const hours = Math.floor(totalSeconds / 3600).toString().padStart(2, "0");
  const minutes = Math.floor((totalSeconds % 3600) / 60).toString().padStart(2, "0");
  const secs = (totalSeconds % 60).toString().padStart(2, "0");
  return `${hours}:${minutes}:${secs},${milliseconds}`;
}

function buildSrtContent(segments, durationSeconds) {
  return segments
    .map((segment, index) => {
      const start = Math.max(0, segment.start);
      const end = Math.max(start + 0.4, Math.min(durationSeconds || segment.end, segment.end));
      return [
        String(index + 1),
        `${formatSrtTimestamp(start)} --> ${formatSrtTimestamp(end)}`,
        segment.text
      ].join("\n");
    })
    .join("\n\n");
}

function buildCaptionFile(videoFileName, durationSeconds) {
  const finalSegments = captionSegments.filter((segment) => normalizeCaptionText(segment.text));
  if (!finalSegments.length) return null;

  const srtContent = buildSrtContent(finalSegments, durationSeconds);
  if (!srtContent.trim()) return null;

  return new File([srtContent], captionFileName(videoFileName), {
    type: "application/x-subrip;charset=utf-8"
  });
}

function updateCaptionLiveStatus(message) {
  captionStatusMessage = message;
  const status = document.querySelector("#captionStatus");
  if (status) status.textContent = message;
}

function resetCaptionCapture(wantsMicrophone) {
  stopCaptionRecognition();
  captionSegments = [];
  captionInterimText = "";
  captionLastSegmentEnd = 0;
  captionsRequestedForRecording = Boolean(wantsMicrophone);
  captionsSupportedForRecording = captionsRequestedForRecording && speechRecognitionSupported();
  captionStatusMessage = captionsRequestedForRecording
    ? (captionsSupportedForRecording ? "Legendas: aguardando fala do microfone." : "Legendas indisponíveis neste navegador.")
    : "";
}

function handleCaptionResult(event) {
  if (!captionsRequestedForRecording) return;

  const interimTexts = [];
  for (let index = event.resultIndex; index < event.results.length; index += 1) {
    const result = event.results[index];
    const alternative = result?.[0];
    const text = normalizeCaptionText(alternative?.transcript);
    if (!text) continue;

    if (result.isFinal) appendCaptionSegment(text);
    else interimTexts.push(text);
  }

  captionInterimText = normalizeCaptionText(interimTexts.join(" "));
  if (captionInterimText) {
    updateCaptionLiveStatus(`Legenda: ${captionInterimText}`);
  } else if (captionSegments.length) {
    updateCaptionLiveStatus("Legendas: texto reconhecido.");
  }
}

function startCaptionRecognition() {
  if (!captionsRequestedForRecording) return;

  const SpeechRecognition = speechRecognitionConstructor();
  if (!SpeechRecognition) {
    captionsSupportedForRecording = false;
    updateCaptionLiveStatus("Legendas indisponíveis neste navegador.");
    return;
  }

  const recognition = new SpeechRecognition();
  captionRecognition = recognition;
  captionRecognitionActive = true;
  recognition.lang = CAPTION_LANGUAGE;
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  recognition.addEventListener("start", () => {
    updateCaptionLiveStatus("Legendas: ouvindo microfone.");
  });
  recognition.addEventListener("result", handleCaptionResult);
  recognition.addEventListener("error", (event) => {
    if (event.error === "no-speech") {
      updateCaptionLiveStatus("Legendas: aguardando fala do microfone.");
      return;
    }
    captionRecognitionActive = false;
    captionsSupportedForRecording = false;
    updateCaptionLiveStatus("Legendas indisponíveis durante esta gravação.");
  });
  recognition.addEventListener("end", () => {
    if (captionRecognition !== recognition) return;
    if (!captionRecognitionActive || recordingStopping || mediaRecorder?.state !== "recording") return;

    captionRestartTimerId = window.setTimeout(() => {
      try {
        recognition.start();
      } catch {
        updateCaptionLiveStatus("Legendas pausadas pelo navegador.");
      }
    }, 250);
  });

  try {
    recognition.start();
  } catch {
    captionRecognitionActive = false;
    captionsSupportedForRecording = false;
    captionRecognition = null;
    updateCaptionLiveStatus("Legendas indisponíveis neste navegador.");
  }
}

function stopCaptionRecognition() {
  captionRecognitionActive = false;
  if (captionRestartTimerId) {
    window.clearTimeout(captionRestartTimerId);
    captionRestartTimerId = 0;
  }

  if (!captionRecognition) return;

  try {
    captionRecognition.stop();
  } catch {
    // SpeechRecognition may already be stopped by the browser.
  }
  captionRecognition = null;
  captionInterimText = "";
}

function cleanupRecordingSession() {
  window.clearInterval(recordingTimerId);
  recordingTimerId = 0;
  recordingDock.hidden = true;
  stopCaptionRecognition();

  stopStreamTracks(recordingStream);
  stopStreamTracks(screenStream);
  stopStreamTracks(microphoneStream);

  recordingAudioSources = [];
  recordingAudioContext?.close?.().catch(() => {});
  recordingAudioContext = null;
  recordingStream = null;
  screenStream = null;
  microphoneStream = null;
  mediaRecorder = null;
  recordingStopping = false;
  recordingWarningMessage = "";
  setRecorderButtonState(screenRecordingSupported() ? "idle" : "unsupported");
}

function addRecordingWarning(message) {
  if (!message) return;
  recordingWarningMessage = recordingWarningMessage
    ? `${recordingWarningMessage} ${message}`
    : message;
}

function renderLiveRecordingPreview() {
  previewFrame.innerHTML = '<video class="recording-preview-video" autoplay muted playsinline></video>';
  const video = previewFrame.querySelector("video");
  video.srcObject = screenStream;
  video.play().catch(() => {});

  statusPill.textContent = "Gravando";
  previewTitle.textContent = "Gravação de tela";
  updateRecordingTimer();
}

function renderRecordingStartingState() {
  statusPill.textContent = "Selecionando fonte";
  previewTitle.textContent = "Escolha o que gravar";
  previewMeta.textContent = "A gravação começa depois que você confirmar no seletor do navegador.";
  renderThumbnailLoading("Abrindo seletor");
  results.innerHTML = `
    <div class="loading-state recording-live-state">
      <img class="loading-brand" src="/videodrop_loader_animado.svg" alt="" aria-hidden="true" />
      <p>Selecione uma tela, janela ou aba no painel do navegador.</p>
    </div>
  `;
}

function renderRecordingLiveState() {
  const captionStatus = captionsRequestedForRecording
    ? `<p class="caption-status" id="captionStatus">${captionStatusMessage}</p>`
    : "";
  const warningStatus = recordingWarningMessage
    ? `<p class="caption-status recording-warning">${recordingWarningMessage}</p>`
    : "";

  results.innerHTML = `
    <div class="loading-state recording-live-state">
      <img class="loading-brand" src="/videodrop_loader_animado.svg" alt="" aria-hidden="true" />
      <p>Gravação em andamento. Use o controle flutuante para parar.</p>
      ${warningStatus}
      ${captionStatus}
    </div>
  `;
}

function updateRecordingTimer() {
  if (!recordingStartedAt) return;
  const elapsedSeconds = (Date.now() - recordingStartedAt) / 1000;
  const timeLabel = formatClock(elapsedSeconds);
  if (recordingTimer) recordingTimer.textContent = timeLabel;
  previewMeta.textContent = `${timeLabel} - ${recordingMetaSuffix}`;
}

function startRecordingTimer() {
  recordingStartedAt = Date.now();
  updateRecordingTimer();
  recordingTimerId = window.setInterval(updateRecordingTimer, 500);
}

function buildRecordingStream(displayStream, micStream, wantsSystemAudio) {
  const outputStream = new MediaStream();
  const videoTrack = displayStream.getVideoTracks()[0];
  if (!videoTrack) throw new Error("display video unavailable");
  outputStream.addTrack(videoTrack);

  const audioStreams = [];
  const displayAudioTracks = displayStream.getAudioTracks();
  if (displayAudioTracks.length) {
    audioStreams.push(new MediaStream(displayAudioTracks));
  } else if (wantsSystemAudio) {
    addRecordingWarning("O navegador não entregou áudio do sistema para essa fonte.");
    pasteHint.textContent = "O navegador não entregou áudio do sistema para essa fonte.";
    pasteHint.classList.add("flash");
    resetPasteHint(4200);
  }

  const microphoneTracks = micStream?.getAudioTracks() || [];
  if (microphoneTracks.length) audioStreams.push(new MediaStream(microphoneTracks));

  const AudioContextConstructor = window.AudioContext || window.webkitAudioContext;
  if (audioStreams.length > 1 && AudioContextConstructor) {
    recordingAudioContext = new AudioContextConstructor();
    const destination = recordingAudioContext.createMediaStreamDestination();
    recordingAudioSources = audioStreams.map((stream) => {
      const source = recordingAudioContext.createMediaStreamSource(stream);
      source.connect(destination);
      return source;
    });
    destination.stream.getAudioTracks().forEach((track) => outputStream.addTrack(track));
  } else {
    audioStreams.forEach((stream) => {
      stream.getAudioTracks().forEach((track) => outputStream.addTrack(track));
    });
  }

  return outputStream;
}

function screenRecordingErrorMessage(error) {
  if (error.name === "NotAllowedError") return "Permissão de gravação negada pelo navegador.";
  if (error.name === "NotFoundError") return "Nenhuma fonte de tela foi selecionada.";
  if (error.name === "NotReadableError") return "O sistema bloqueou a captura da fonte escolhida.";
  if (error.name === "TypeError") return "Este navegador não aceitou as opções de gravação solicitadas.";
  return "Não consegui iniciar a gravação de tela agora.";
}

function microphoneCaptureErrorMessage(error) {
  if (error.name === "NotAllowedError") {
    return "Microfone bloqueado pelo navegador ou pelo Windows. A gravação seguirá sem microfone.";
  }
  if (error.name === "NotFoundError") {
    return "Nenhum microfone foi encontrado. A gravação seguirá sem microfone.";
  }
  if (error.name === "NotReadableError") {
    return "O microfone está em uso ou bloqueado pelo sistema. A gravação seguirá sem microfone.";
  }
  return "Não consegui ativar o microfone. A gravação seguirá sem microfone.";
}

async function requestOptionalMicrophoneStream() {
  const microphoneRequest = navigator.mediaDevices.getUserMedia({ audio: true });
  let timeoutId = 0;

  try {
    const stream = await Promise.race([
      microphoneRequest,
      new Promise((resolve) => {
        timeoutId = window.setTimeout(() => resolve(null), MICROPHONE_REQUEST_TIMEOUT_MS);
      })
    ]);

    if (!stream) {
      const message = "O navegador não respondeu à permissão do microfone. A gravação seguirá sem microfone.";
      addRecordingWarning(message);
      pasteHint.textContent = message;
      pasteHint.classList.add("flash");
      resetPasteHint(6500);
      microphoneRequest.then(stopStreamTracks).catch(() => {});
      return null;
    }

    return stream;
  } catch (error) {
    const message = microphoneCaptureErrorMessage(error);
    addRecordingWarning(message);
    pasteHint.textContent = message;
    pasteHint.classList.add("flash");
    resetPasteHint(6500);
    return null;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function stopScreenRecording() {
  if (recordingStopping) return;
  recordingStopping = true;
  stopCaptionRecognition();

  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    try {
      mediaRecorder.requestData();
    } catch {
      // Some browsers reject requestData() when the recorder is already stopping.
    }
    mediaRecorder.stop();
    return;
  }

  cleanupRecordingSession();
}

function handleRecorderStop() {
  const mimeType = mediaRecorder?.mimeType || "video/webm";
  const durationSeconds = recordingStartedAt ? (Date.now() - recordingStartedAt) / 1000 : 0;
  const blob = new Blob(recordedChunks, { type: mimeType });
  const file = new File([blob], recordingFileName(), { type: blob.type || "video/webm" });
  const captionFile = captionsRequestedForRecording ? buildCaptionFile(file.name, durationSeconds) : null;

  recordedChunks = [];
  cleanupRecordingSession();

  if (!blob.size) {
    setError("A gravação terminou sem dados. Tente gravar novamente.");
    return;
  }

  clearRecordingObjectUrl();
  clearCaptionObjectUrl();
  recordingObjectUrl = URL.createObjectURL(blob);
  if (captionFile) captionObjectUrl = URL.createObjectURL(captionFile);
  renderRecordingResult(file, recordingObjectUrl, durationSeconds, captionFile, captionObjectUrl);
}

function handleRecorderError() {
  pasteHint.textContent = "A gravação foi interrompida pelo navegador.";
  pasteHint.classList.add("flash");
  resetPasteHint(4200);
  stopScreenRecording();
}

function renderRecordingResult(file, objectUrl, durationSeconds, captionFile = null, captionUrl = "") {
  statusPill.textContent = "Gravação pronta";
  previewTitle.textContent = "Gravação da tela";
  previewMeta.textContent = `${formatClock(durationSeconds)} - ${formatBytes(file.size)} - WebM`;
  previewFrame.innerHTML = '<video class="recording-playback-video" controls playsinline></video>';
  previewFrame.querySelector("video").src = objectUrl;
  const captionAction = captionFile && captionUrl
    ? '<a class="ghost-button caption-download-button">Baixar legenda</a>'
    : "";

  results.innerHTML = `
    <article class="recording-result">
      <div>
        <h3>Gravação pronta</h3>
        <p>${formatClock(durationSeconds)} - ${formatBytes(file.size)} - WebM local${captionFile ? " - legenda SRT" : ""}</p>
      </div>
      <div class="format-actions">
        <button class="ghost-button recording-share-button" type="button">Compartilhar</button>
        ${captionAction}
        <a class="download-button recording-download-button">Baixar</a>
      </div>
    </article>
  `;

  const download = results.querySelector(".recording-download-button");
  download.href = objectUrl;
  download.download = file.name;

  const captionDownload = results.querySelector(".caption-download-button");
  if (captionDownload && captionFile) {
    captionDownload.href = captionUrl;
    captionDownload.download = captionFile.name;
  }

  const share = results.querySelector(".recording-share-button");
  share.addEventListener("click", () => shareRecordedFile(file, share));
}

function recordingWhatsAppFileName(fileName) {
  return fileName.replace(/\.webm$/i, "-whatsapp.mp4") || "videodrop-gravacao-whatsapp.mp4";
}

async function convertRecordedFileForWhatsApp(file) {
  const response = await fetch("/api/recordings/whatsapp", {
    method: "POST",
    headers: { "Content-Type": file.type || "video/webm" },
    body: file
  });
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(error?.detail || "Não consegui converter a gravação para MP4.");
  }

  const blob = await response.blob();
  return new File([blob], recordingWhatsAppFileName(file.name), { type: "video/mp4" });
}

async function shareRecordedFile(file, triggerButton) {
  const originalText = triggerButton.textContent;
  triggerButton.disabled = true;
  triggerButton.classList.add("is-loading");
  triggerButton.textContent = "Convertendo...";
  pasteHint.textContent = "Convertendo gravação para MP4...";
  pasteHint.classList.add("flash");

  try {
    const mp4File = await convertRecordedFileForWhatsApp(file);
    const canNativeShare = showShareSheet(mp4File, "VideoDrop");
    pasteHint.textContent = canNativeShare
      ? "MP4 pronto para compartilhar."
      : "MP4 pronto. Se o Windows não compartilhar, baixe o arquivo pelo modal.";
    pasteHint.classList.add("flash");
    resetPasteHint();
  } catch (error) {
    if (error.name !== "AbortError") {
      pasteHint.textContent = "Não consegui preparar o MP4 para compartilhar. Baixe o vídeo e envie manualmente.";
      pasteHint.classList.add("flash");
      resetPasteHint(5200);
    }
  } finally {
    triggerButton.disabled = false;
    triggerButton.classList.remove("is-loading");
    triggerButton.textContent = originalText;
  }
}

async function startScreenRecording() {
  if (!screenRecordingSupported()) {
    setupScreenRecorderSupport();
    return;
  }
  if (mediaRecorder && mediaRecorder.state === "recording") return;

  const wantsSystemAudio = Boolean(systemAudioToggle?.checked);
  const wantsMicrophone = Boolean(microphoneToggle?.checked);
  const audioLabels = [
    wantsSystemAudio ? "áudio do sistema" : null,
    wantsMicrophone ? "microfone" : null
  ].filter(Boolean);
  recordingMetaSuffix = audioLabels.length ? `WebM local com ${audioLabels.join(" + ")}` : "WebM local sem áudio";
  closeShareSheet();
  setRecorderButtonState("starting");
  activeController?.abort();
  activeController = null;
  analyzeRunId += 1;
  currentData = null;
  recordingWarningMessage = "";
  clearRecordingResultState();
  resetCaptionCapture(false);
  renderRecordingStartingState();

  try {
    const displayOptions = {
      video: true,
      audio: wantsSystemAudio ? { suppressLocalAudioPlayback: false } : false,
      monitorTypeSurfaces: "include",
      selfBrowserSurface: "exclude",
      surfaceSwitching: "include"
    };
    if (wantsSystemAudio) {
      displayOptions.systemAudio = "include";
      displayOptions.windowAudio = "system";
    }

    screenStream = await navigator.mediaDevices.getDisplayMedia(displayOptions);
    if (wantsMicrophone) {
      microphoneStream = await requestOptionalMicrophoneStream();
    }

    const hasSystemAudio = screenStream.getAudioTracks().length > 0;
    const hasMicrophoneAudio = (microphoneStream?.getAudioTracks() || []).length > 0;
    const enabledAudioLabels = [
      hasSystemAudio ? "áudio do sistema" : null,
      hasMicrophoneAudio ? "microfone" : null
    ].filter(Boolean);
    recordingMetaSuffix = enabledAudioLabels.length
      ? `WebM local com ${enabledAudioLabels.join(" + ")}`
      : "WebM local sem áudio";
    resetCaptionCapture(hasMicrophoneAudio);

    recordingStream = buildRecordingStream(screenStream, microphoneStream, wantsSystemAudio);
    if (recordingAudioContext?.state === "suspended") {
      await recordingAudioContext.resume().catch(() => {});
    }
    const mimeType = selectRecorderMimeType();
    mediaRecorder = new MediaRecorder(recordingStream, mimeType ? { mimeType } : undefined);
    recordedChunks = [];
    recordingStopping = false;

    mediaRecorder.addEventListener("dataavailable", (event) => {
      if (event.data?.size) recordedChunks.push(event.data);
    });
    mediaRecorder.addEventListener("stop", handleRecorderStop, { once: true });
    mediaRecorder.addEventListener("error", handleRecorderError);
    screenStream.getVideoTracks()[0]?.addEventListener("ended", stopScreenRecording, { once: true });

    renderLiveRecordingPreview();
    renderRecordingLiveState();
    recordingDock.hidden = false;
    startRecordingTimer();
    mediaRecorder.start(1000);
    startCaptionRecognition();
    setRecorderButtonState("recording");
    pasteHint.textContent = "Gravação iniciada.";
    pasteHint.classList.add("flash");
    resetPasteHint();
  } catch (error) {
    cleanupRecordingSession();
    const message = screenRecordingErrorMessage(error);
    setRecorderStartError(message);
    pasteHint.textContent = message;
    pasteHint.classList.add("flash");
    resetPasteHint(5200);
  }
}

function clearPreparedShareFile() {
  preparedSharePayload = null;
  if (preparedShareObjectUrl) {
    URL.revokeObjectURL(preparedShareObjectUrl);
    preparedShareObjectUrl = "";
  }
  if (shareSheetDownload) {
    shareSheetDownload.hidden = true;
    shareSheetDownload.removeAttribute("href");
    shareSheetDownload.removeAttribute("download");
  }
}

function setShareSheetMessage(message) {
  if (shareSheetMeta) shareSheetMeta.textContent = message;
}

function canUseNativeShare(payload) {
  if (!navigator.share) return false;
  if (!navigator.canShare) return true;
  try {
    return navigator.canShare(payload);
  } catch (error) {
    return false;
  }
}

function setShareSheetDownload(file) {
  preparedShareObjectUrl = URL.createObjectURL(file);
  if (shareSheetDownload) {
    shareSheetDownload.href = preparedShareObjectUrl;
    shareSheetDownload.download = file.name;
    shareSheetDownload.hidden = false;
  }
}

// Chrome/Windows needs a fresh click to open the native share panel after the file is prepared.
function showShareSheet(file, title = currentData?.title || "VideoDrop") {
  clearPreparedShareFile();
  preparedSharePayload = { files: [file], title };
  setShareSheetDownload(file);

  const canNativeShare = canUseNativeShare(preparedSharePayload);
  if (shareNowButton) {
    shareNowButton.disabled = !canNativeShare;
  }

  setShareSheetMessage(
    canNativeShare
      ? `${file.name} está pronto. Tente compartilhar pelo Windows ou baixe o arquivo aqui.`
      : `${file.name} está pronto, mas o compartilhamento nativo não aceitou esse arquivo. Baixe por aqui.`
  );
  shareSheet.hidden = false;
  if (canNativeShare) {
    shareNowButton?.focus();
  } else {
    shareSheetDownload?.focus();
  }
  return canNativeShare;
}

function closeShareSheet() {
  clearPreparedShareFile();
  if (shareNowButton) shareNowButton.disabled = false;
  if (shareSheet) shareSheet.hidden = true;
}

async function sharePreparedFile() {
  if (!preparedSharePayload) return;

  try {
    if (!canUseNativeShare(preparedSharePayload)) {
      throw new Error("file share unavailable");
    }

    await navigator.share(preparedSharePayload);
    closeShareSheet();
    pasteHint.textContent = "Compartilhamento aberto pelo sistema.";
    pasteHint.classList.add("flash");
    resetPasteHint();
  } catch (error) {
    const message = error.name === "AbortError"
      ? "Compartilhamento cancelado. O arquivo continua pronto para baixar."
      : "O compartilhamento do Windows falhou. O arquivo pronto continua disponível para baixar.";
    setShareSheetMessage(message);
    shareSheetDownload?.focus();
    pasteHint.textContent = message;
    pasteHint.classList.add("flash");
    resetPasteHint(5200);
  }
}

// The first click prepares the file; the second click opens the native OS share UI.
async function shareToWhatsApp(format, triggerButton) {
  const url = downloadUrl(format.format_id);
  const fileName = shareFileName(format);
  const mimeType = shareMimeType(format);
  const originalText = triggerButton.textContent;
  let hintResetDelay = 1200;

  triggerButton.disabled = true;
  triggerButton.classList.add("is-loading");
  triggerButton.textContent = "Preparando...";
  pasteHint.textContent = "Preparando arquivo para compartilhar...";
  pasteHint.classList.add("flash");

  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error("download failed");

    const blob = await response.blob();
    const file = new File([blob], fileName, { type: mimeType });
    const canNativeShare = showShareSheet(file);
    pasteHint.textContent = canNativeShare
      ? "Arquivo pronto para compartilhar."
      : "Arquivo pronto. Se o Windows não compartilhar, baixe pelo modal.";
    pasteHint.classList.add("flash");
  } catch (error) {
    if (error.name !== "AbortError") {
      pasteHint.textContent = "Não consegui preparar esse arquivo para compartilhar.";
      pasteHint.classList.add("flash");
      hintResetDelay = 4200;
    }
  } finally {
    triggerButton.disabled = false;
    triggerButton.classList.remove("is-loading");
    triggerButton.textContent = originalText;
    resetPasteHint(hintResetDelay);
  }
}

function renderFormats(data) {
  results.innerHTML = "";
  data.formats.forEach((format) => {
    const node = formatTemplate.content.firstElementChild.cloneNode(true);
    const title = node.querySelector("h3");
    const description = node.querySelector("p");
    const download = node.querySelector(".download-button");
    const share = node.querySelector(".share-button");
    const isAudio = isAudioFormat(format);

    title.textContent = format.resolution;
    description.textContent = isAudio
      ? [
          formatBytes(format.size_bytes, format.size_estimated),
          format.bitrate ? `${Math.round(format.bitrate)} kbps` : null,
          "áudio em MP3"
        ].filter(Boolean).join(" - ")
      : [
          formatBytes(format.size_bytes, format.size_estimated),
          format.fps ? `${Math.round(format.fps)} fps` : null,
          format.needs_merge ? "vídeo + áudio em MP4" : "MP4 com áudio"
        ].filter(Boolean).join(" - ");

    download.href = downloadUrl(format.format_id);
    download.setAttribute("download", "");
    download.textContent = "Baixar";
    download.addEventListener("click", (event) => prepareDownload(format, download, event));
    share.addEventListener("click", () => shareToWhatsApp(format, share));
    results.appendChild(node);
  });
}

// URL analysis flow.
async function analyze(url) {
  const nextUrl = url.trim();
  if (primaryButton.disabled && nextUrl === currentUrl) return;

  activeController?.abort();
  const runId = ++analyzeRunId;
  currentUrl = nextUrl;
  closeShareSheet();
  clearRecordingResultState();
  input.value = currentUrl;
  setLoading(currentUrl);
  setAnalyzingState(true);
  await waitForPaint();

  const controller = new AbortController();
  activeController = controller;
  const timeoutId = window.setTimeout(() => controller.abort(), ANALYZE_TIMEOUT_MS);
  const cookieBrowser = activeCookieBrowser(currentUrl);
  const payload = { url: currentUrl };
  if (cookieBrowser) payload.cookie_browser = cookieBrowser;

  try {
    const response = await fetch("/api/probe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Não consegui analisar essa URL.");
    if (runId !== analyzeRunId) return;

    currentData = data;
    renderPreview(data);
    renderFormats(data);
  } catch (error) {
    if (runId !== analyzeRunId) return;
    if (error.name === "AbortError" && activeController !== controller) return;
    const message = error.name === "AbortError"
      ? "A análise demorou demais. Tente novamente em instantes."
      : error.message;
    setError(message);
  } finally {
    window.clearTimeout(timeoutId);
    if (activeController === controller) activeController = null;
    if (runId === analyzeRunId) setAnalyzingState(false);
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const value = input.value.trim();
  if (isProbablyUrl(value)) analyze(value);
});

// Event wiring.
themeToggle?.addEventListener("click", () => {
  const nextTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  setTheme(nextTheme);
});

shareNowButton?.addEventListener("click", sharePreparedFile);
shareSheetClose?.addEventListener("click", closeShareSheet);
shareSheetCancel?.addEventListener("click", closeShareSheet);
screenRecordButton?.addEventListener("click", startScreenRecording);
recordingStopButton?.addEventListener("click", stopScreenRecording);
shareSheet?.addEventListener("click", (event) => {
  if (event.target === shareSheet) closeShareSheet();
});

window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && shareSheet && !shareSheet.hidden) closeShareSheet();
});

window.addEventListener("paste", (event) => {
  const text = event.clipboardData?.getData("text")?.trim();
  if (!text || !isProbablyUrl(text)) return;
  event.preventDefault();
  pasteHint.textContent = "URL detectada. Carregando opções...";
  pasteHint.classList.add("flash");
  analyze(text);
  window.setTimeout(() => {
    pasteHint.textContent = "Ctrl + V em qualquer lugar detecta URLs automaticamente";
    pasteHint.classList.remove("flash");
  }, 2200);
});

window.addEventListener("beforeunload", () => {
  clearPreparedShareFile();
  clearRecordingObjectUrl();
  clearCaptionObjectUrl();
  stopStreamTracks(recordingStream);
  stopStreamTracks(screenStream);
  stopStreamTracks(microphoneStream);
});

setupTheme();
setupBrowserAuthControls();
setupScreenRecorderSupport();
if (copyrightYear) copyrightYear.textContent = String(new Date().getFullYear());
