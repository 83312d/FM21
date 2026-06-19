(function () {
  "use strict";

  const STORAGE_CITY = "fm21_city";
  const STORAGE_VOLUME = "fm21_volume";
  const GEO_TIMEOUT_MS = 5000;
  const METADATA_POLL_MS = 5000;
  const RETRY_BASE_MS = 1000;
  const RETRY_MAX_MS = 30000;
  const PROGRESS_TICK_MS = 250;

  const CONTENT_LABELS = {
    music: "Музыка",
    news: "Новости",
    ad: "Реклама",
  };

  const cities = JSON.parse(document.getElementById("fm21-cities").textContent);
  const cityByTag = new Map(cities.map((city) => [city.tag, city]));

  const audio = document.getElementById("stream");
  const playBtn = document.getElementById("play-btn");
  const stopBtn = document.getElementById("stop-btn");
  const playPrompt = document.getElementById("play-prompt");
  const citySelect = document.getElementById("city-select");
  const volumeInput = document.getElementById("volume");
  const statusEl = document.getElementById("status");
  const contentTypeEl = document.getElementById("content-type");
  const titleEl = document.getElementById("now-title");
  const artistEl = document.getElementById("now-artist");
  const listenersBadge = document.getElementById("live-indicator");
  const listenerCountEl = document.getElementById("listener-count");
  const progressFill = document.getElementById("progress-fill");
  const currentTimeEl = document.getElementById("current-time");
  const totalTimeEl = document.getElementById("total-time");
  const volumeIcon = document.querySelector(".volume-icon svg");

  const ICON_PLAY =
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><polygon points="5,3 19,12 5,21" /></svg>';
  const ICON_PAUSE =
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><rect x="6" y="4" width="4" height="16" rx="1" /><rect x="14" y="4" width="4" height="16" rx="1" /></svg>';

  let cityTag = "moscow";
  let cityName = cityByTag.get(cityTag)?.name ?? cityTag;
  let userStarted = false;
  let stopped = false;
  let metadataTimer = null;
  let lastMetadata = null;
  let retryTimer = null;
  let retryDelay = RETRY_BASE_MS;
  let progressTimer = null;
  let trackDurationSec = 0;
  let trackStartedAtMs = null;

  function isValidTag(tag) {
    return cityByTag.has(tag);
  }

  function streamUrl(tag) {
    return `/${tag}`;
  }

  function formatTime(seconds) {
    const safe = Math.max(0, Math.floor(seconds));
    const mins = Math.floor(safe / 60);
    const secs = safe % 60;
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  }

  function setStatus(message, isError) {
    statusEl.textContent = message || "";
    statusEl.classList.toggle("player__status--error", Boolean(isError));
  }

  function populateCitySelect(selected) {
    citySelect.replaceChildren();
    for (const city of cities) {
      const option = document.createElement("option");
      option.value = city.tag;
      option.textContent = city.name;
      citySelect.appendChild(option);
    }
    citySelect.value = selected;
  }

  function persistCity(tag) {
    try {
      localStorage.setItem(STORAGE_CITY, tag);
    } catch (_err) {
      /* ignore quota errors */
    }
  }

  function readStoredCity() {
    try {
      const stored = localStorage.getItem(STORAGE_CITY);
      return isValidTag(stored) ? stored : null;
    } catch (_err) {
      return null;
    }
  }

  function readStoredVolume() {
    try {
      const raw = localStorage.getItem(STORAGE_VOLUME);
      const value = Number(raw);
      if (Number.isFinite(value) && value >= 0 && value <= 100) {
        return value;
      }
    } catch (_err) {
      /* ignore */
    }
    return 80;
  }

  function persistVolume(value) {
    try {
      localStorage.setItem(STORAGE_VOLUME, String(value));
    } catch (_err) {
      /* ignore */
    }
  }

  function updateVolumeIcon(value) {
    if (!volumeIcon) {
      return;
    }
    volumeIcon.style.opacity = String(0.4 + (value / 100) * 0.6);
  }

  function resetProgressDisplay() {
    trackDurationSec = 0;
    trackStartedAtMs = null;
    progressFill.style.width = "0%";
    currentTimeEl.textContent = "0:00";
    totalTimeEl.textContent = "0:00";
  }

  function updateProgressFromClock() {
    if (!trackStartedAtMs || trackDurationSec <= 0) {
      progressFill.style.width = "0%";
      currentTimeEl.textContent = "0:00";
      totalTimeEl.textContent = formatTime(trackDurationSec);
      return;
    }
    const elapsed = Math.min(
      trackDurationSec,
      Math.max(0, (Date.now() - trackStartedAtMs) / 1000),
    );
    const percent = (elapsed / trackDurationSec) * 100;
    progressFill.style.width = `${Math.min(100, percent)}%`;
    currentTimeEl.textContent = formatTime(elapsed);
    totalTimeEl.textContent = formatTime(trackDurationSec);
  }

  function applyProgressFromPayload(payload) {
    if (!payload || stopped) {
      return;
    }
    const duration = Number(payload.duration_sec);
    if (!Number.isFinite(duration) || duration <= 0) {
      resetProgressDisplay();
      return;
    }
    trackDurationSec = duration;
    const parsed = payload.started_at ? Date.parse(payload.started_at) : NaN;
    trackStartedAtMs = Number.isFinite(parsed) ? parsed : null;
    updateProgressFromClock();
    if (!stopped && trackStartedAtMs) {
      startProgressTicker();
    }
  }

  function startProgressTicker() {
    stopProgressTicker();
    progressTimer = setInterval(() => {
      if (stopped || !trackStartedAtMs || trackDurationSec <= 0) {
        return;
      }
      updateProgressFromClock();
    }, PROGRESS_TICK_MS);
  }

  function stopProgressTicker() {
    if (progressTimer) {
      clearInterval(progressTimer);
      progressTimer = null;
    }
  }

  function hideListenersBadge() {
    if (listenersBadge) {
      listenersBadge.hidden = true;
    }
  }

  function showListenersBadge() {
    if (listenersBadge) {
      listenersBadge.hidden = false;
    }
  }

  function setListenerCount(count) {
    listenerCountEl.textContent = String(count);
    showListenersBadge();
  }

  function applyCity(tag, name) {
    cityTag = tag;
    cityName = name || cityByTag.get(tag)?.name || tag;
    citySelect.value = tag;
    persistCity(tag);
    setStatus("");
    connectStream(userStarted && !stopped);
    fetchNowPlaying();
    if (userStarted && !stopped) {
      fetchListeners();
      startMetadataPolling();
    }
  }

  function updatePlayUi() {
    const playing = userStarted && !audio.paused && !audio.ended && !stopped;
    playBtn.innerHTML = playing ? ICON_PAUSE : ICON_PLAY;
    playBtn.classList.toggle("is-playing", playing);
    playBtn.setAttribute("aria-label", playing ? "Приостановить" : "Воспроизвести");
    playPrompt.hidden = !(userStarted && !playing && audio.src);
  }

  function clearRetry() {
    if (retryTimer) {
      clearTimeout(retryTimer);
      retryTimer = null;
    }
  }

  function scheduleRetry() {
    clearRetry();
    setStatus(`Повтор подключения через ${Math.round(retryDelay / 1000)} с…`, true);
    retryTimer = setTimeout(() => {
      retryDelay = Math.min(retryDelay * 2, RETRY_MAX_MS);
      connectStream(userStarted && !stopped);
    }, retryDelay);
  }

  function connectStream(shouldPlay) {
    clearRetry();
    const wasPlaying = userStarted && shouldPlay;
    audio.pause();
    audio.removeAttribute("src");
    audio.load();

    const nextSrc = streamUrl(cityTag);
    audio.src = nextSrc;
    audio.load();
    updatePlayUi();

    if (wasPlaying) {
      const playPromise = audio.play();
      if (playPromise && typeof playPromise.then === "function") {
        playPromise
          .then(() => {
            retryDelay = RETRY_BASE_MS;
            setStatus("");
            playPrompt.hidden = true;
            updatePlayUi();
            startMetadataPolling();
            startProgressTicker();
            fetchListeners();
          })
          .catch(() => {
            playPrompt.hidden = false;
            updatePlayUi();
          });
      }
    }
  }

  async function fetchJson(path) {
    const response = await fetch(path, { credentials: "same-origin" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
  }

  function renderMetadata(payload) {
    if (!payload || stopped) {
      return;
    }
    lastMetadata = payload;
    contentTypeEl.textContent = CONTENT_LABELS[payload.content_type] || payload.content_type;
    titleEl.textContent = payload.title || "FM21";
    artistEl.textContent = payload.artist || "";
    applyProgressFromPayload(payload);
  }

  async function fetchNowPlaying() {
    try {
      const payload = await fetchJson(`/api/now-playing/${encodeURIComponent(cityTag)}`);
      renderMetadata(payload);
    } catch (_err) {
      if (lastMetadata && !stopped) {
        renderMetadata(lastMetadata);
      } else if (!stopped) {
        contentTypeEl.textContent = "—";
        titleEl.textContent = "Эфир";
        artistEl.textContent = "";
        resetProgressDisplay();
      }
    }
  }

  async function fetchListeners() {
    try {
      const payload = await fetchJson(`/api/listeners/${encodeURIComponent(cityTag)}`);
      setListenerCount(payload.listeners);
    } catch (_err) {
      hideListenersBadge();
    }
  }

  function metadataInterval() {
    return document.hidden ? METADATA_POLL_MS * 2 : METADATA_POLL_MS;
  }

  function startMetadataPolling() {
    stopMetadataPolling();
    const tick = async () => {
      if (!stopped) {
        await Promise.all([fetchNowPlaying(), fetchListeners()]);
      }
      metadataTimer = setTimeout(tick, metadataInterval());
    };
    metadataTimer = setTimeout(tick, metadataInterval());
  }

  function stopMetadataPolling() {
    if (metadataTimer) {
      clearTimeout(metadataTimer);
      metadataTimer = null;
    }
  }

  function requestGeolocation() {
    return new Promise((resolve) => {
      if (!navigator.geolocation) {
        resolve(null);
        return;
      }
      const timer = setTimeout(() => resolve(null), GEO_TIMEOUT_MS);
      navigator.geolocation.getCurrentPosition(
        (position) => {
          clearTimeout(timer);
          resolve(position.coords);
        },
        () => {
          clearTimeout(timer);
          resolve(null);
        },
        { timeout: GEO_TIMEOUT_MS, maximumAge: 0 },
      );
    });
  }

  async function detectCity() {
    const params = new URLSearchParams(window.location.search);
    const urlCity = params.get("city");
    if (isValidTag(urlCity)) {
      return { tag: urlCity, name: cityByTag.get(urlCity).name, source: "url" };
    }

    const stored = readStoredCity();
    if (stored) {
      return { tag: stored, name: cityByTag.get(stored).name, source: "storage" };
    }

    const coords = await requestGeolocation();
    if (coords) {
      try {
        const reverse = await fetchJson(
          `/api/geo/reverse?lat=${encodeURIComponent(coords.latitude)}&lon=${encodeURIComponent(coords.longitude)}`,
        );
        if (isValidTag(reverse.city_tag)) {
          return {
            tag: reverse.city_tag,
            name: reverse.city_name,
            source: reverse.source,
          };
        }
      } catch (_err) {
        /* fall through */
      }
    }

    const detected = await fetchJson("/api/geo/detect");
    return {
      tag: detected.city_tag,
      name: detected.city_name,
      source: detected.source,
    };
  }

  function resetStoppedUi() {
    stopped = false;
    resetProgressDisplay();
    hideListenersBadge();
    fetchNowPlaying();
  }

  function handleStop() {
    userStarted = false;
    stopped = true;
    audio.pause();
    stopMetadataPolling();
    stopProgressTicker();
    resetProgressDisplay();
    setListenerCount(0);
    titleEl.textContent = "Эфир остановлен";
    artistEl.textContent = "———";
    setStatus("");
    updatePlayUi();
  }

  async function init() {
    populateCitySelect(cityTag);
    const volume = readStoredVolume();
    volumeInput.value = String(volume);
    audio.volume = volume / 100;
    updateVolumeIcon(volume);
    resetProgressDisplay();
    hideListenersBadge();

    try {
      const resolved = await detectCity();
      if (isValidTag(resolved.tag)) {
        cityTag = resolved.tag;
        cityName = resolved.name;
      }
    } catch (_err) {
      cityTag = "moscow";
      cityName = cityByTag.get(cityTag).name;
    }

    citySelect.value = cityTag;
    persistCity(cityTag);
    audio.src = streamUrl(cityTag);
    updatePlayUi();
    await fetchNowPlaying();
    await fetchListeners();
    startMetadataPolling();
  }

  playBtn.addEventListener("click", async () => {
    if (stopped) {
      resetStoppedUi();
    }

    if (!audio.paused && !audio.ended) {
      audio.pause();
      userStarted = false;
      stopMetadataPolling();
      stopProgressTicker();
      updatePlayUi();
      return;
    }

    userStarted = true;
    stopped = false;
    playPrompt.hidden = true;
    try {
      await audio.play();
      retryDelay = RETRY_BASE_MS;
      setStatus("");
      startMetadataPolling();
      startProgressTicker();
      fetchListeners();
    } catch (_err) {
      playPrompt.hidden = false;
      setStatus("Нажмите Play для начала воспроизведения", true);
    }
    updatePlayUi();
  });

  stopBtn.addEventListener("click", () => {
    handleStop();
  });

  citySelect.addEventListener("change", () => {
    const nextTag = citySelect.value;
    if (!isValidTag(nextTag) || nextTag === cityTag) {
      return;
    }
    applyCity(nextTag, cityByTag.get(nextTag).name);
  });

  volumeInput.addEventListener("input", () => {
    const value = Number(volumeInput.value);
    audio.volume = value / 100;
    persistVolume(value);
    updateVolumeIcon(value);
  });

  audio.addEventListener("playing", () => {
    retryDelay = RETRY_BASE_MS;
    clearRetry();
    setStatus("");
    updatePlayUi();
  });

  audio.addEventListener("pause", () => {
    updatePlayUi();
  });

  audio.addEventListener("error", () => {
    if (!userStarted) {
      return;
    }
    scheduleRetry();
    updatePlayUi();
  });

  document.addEventListener("visibilitychange", () => {
    if (metadataTimer) {
      stopMetadataPolling();
      startMetadataPolling();
    }
  });

  init();
})();
