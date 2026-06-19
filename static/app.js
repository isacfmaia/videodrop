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
const shareSheetClose = document.querySelector("#shareSheetClose");
const shareSheetCancel = document.querySelector("#shareSheetCancel");
const ANALYZE_TIMEOUT_MS = 120000;

let currentUrl = "";
let currentData = null;
let activeController = null;
let analyzeRunId = 0;
let preparedSharePayload = null;

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

function downloadUrl(formatId) {
  const params = new URLSearchParams({ url: currentUrl, format_id: formatId });
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

function showShareSheet(file) {
  preparedSharePayload = { files: [file], title: currentData?.title || "VideoDrop" };
  if (shareSheetMeta) {
    shareSheetMeta.textContent = `${file.name} está pronto. Clique para abrir a tela de compartilhamento do Windows.`;
  }
  shareSheet.hidden = false;
  shareNowButton?.focus();
}

function closeShareSheet() {
  preparedSharePayload = null;
  if (shareSheet) shareSheet.hidden = true;
}

async function sharePreparedFile() {
  if (!preparedSharePayload) return;

  try {
    if (!navigator.share) {
      throw new Error("native share unavailable");
    }

    if (navigator.canShare && !navigator.canShare(preparedSharePayload)) {
      throw new Error("file share unavailable");
    }

    await navigator.share(preparedSharePayload);
    closeShareSheet();
    pasteHint.textContent = "Compartilhamento aberto pelo sistema.";
    pasteHint.classList.add("flash");
    resetPasteHint();
  } catch (error) {
    if (error.name !== "AbortError") {
      pasteHint.textContent = "O Chrome/Windows não aceitou compartilhar esse arquivo. Tente baixar e anexar no WhatsApp.";
      pasteHint.classList.add("flash");
      resetPasteHint(5200);
    }
  }
}

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
    if (!navigator.share) {
      throw new Error("native share unavailable");
    }

    const response = await fetch(url);
    if (!response.ok) throw new Error("download failed");

    const blob = await response.blob();
    const file = new File([blob], fileName, { type: mimeType });
    const sharePayload = { files: [file] };

    if (navigator.canShare && !navigator.canShare(sharePayload)) {
      throw new Error("file share unavailable");
    }

    showShareSheet(file);
    pasteHint.textContent = "Arquivo pronto para compartilhar.";
    pasteHint.classList.add("flash");
  } catch (error) {
    if (error.name !== "AbortError") {
      pasteHint.textContent = "Não consegui abrir o compartilhamento do sistema para esse arquivo.";
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
    share.addEventListener("click", () => shareToWhatsApp(format, share));
    results.appendChild(node);
  });
}

async function analyze(url) {
  const nextUrl = url.trim();
  if (primaryButton.disabled && nextUrl === currentUrl) return;

  activeController?.abort();
  const runId = ++analyzeRunId;
  currentUrl = nextUrl;
  input.value = currentUrl;
  setLoading(currentUrl);
  setAnalyzingState(true);
  await waitForPaint();

  const controller = new AbortController();
  activeController = controller;
  const timeoutId = window.setTimeout(() => controller.abort(), ANALYZE_TIMEOUT_MS);

  try {
    const response = await fetch("/api/probe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: currentUrl }),
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

themeToggle?.addEventListener("click", () => {
  const nextTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  setTheme(nextTheme);
});

shareNowButton?.addEventListener("click", sharePreparedFile);
shareSheetClose?.addEventListener("click", closeShareSheet);
shareSheetCancel?.addEventListener("click", closeShareSheet);
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

setupTheme();
if (copyrightYear) copyrightYear.textContent = String(new Date().getFullYear());
