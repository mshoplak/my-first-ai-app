(() => {
  const searchForm = document.getElementById("search-form");
  const searchInput = document.getElementById("search-input");
  const searchBtn = document.getElementById("search-btn");
  const statusEl = document.getElementById("status");
  const playerEl = document.getElementById("player");
  const trackListSection = document.getElementById("track-list-section");
  const trackListHeading = document.getElementById("track-list-heading");
  const trackListEl = document.getElementById("track-list");
  const artworkImg = document.getElementById("artwork");
  const artworkPlaceholder = document.getElementById("artwork-placeholder");
  const trackTitle = document.getElementById("track-title");
  const trackArtist = document.getElementById("track-artist");
  const audio = document.getElementById("audio");
  const playPauseBtn = document.getElementById("play-pause-btn");
  const prevBtn = document.getElementById("prev-btn");
  const nextBtn = document.getElementById("next-btn");
  const iconPlay = document.getElementById("icon-play");
  const iconPause = document.getElementById("icon-pause");
  const progressBar = document.getElementById("progress-bar");
  const progressFill = document.getElementById("progress-fill");
  const progressThumb = document.getElementById("progress-thumb");
  const currentTimeEl = document.getElementById("current-time");
  const durationTimeEl = document.getElementById("duration-time");

  let isSeeking = false;
  let tracks = [];
  let currentIndex = -1;

  function formatTime(seconds) {
    if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  }

  function setStatus(message, type = "") {
    statusEl.textContent = message;
    statusEl.className = `status${type ? ` ${type}` : ""}`;
  }

  function setPlayingState(playing) {
    iconPlay.classList.toggle("hidden", playing);
    iconPause.classList.toggle("hidden", !playing);
    playPauseBtn.setAttribute("aria-label", playing ? "Pause" : "Play");
  }

  function updateProgress() {
    const duration = audio.duration || 0;
    const current = audio.currentTime || 0;
    const pct = duration > 0 ? (current / duration) * 100 : 0;

    progressFill.style.width = `${pct}%`;
    progressThumb.style.left = `${pct}%`;
    progressBar.setAttribute("aria-valuenow", Math.round(pct));
    currentTimeEl.textContent = formatTime(current);
    durationTimeEl.textContent = formatTime(duration);
  }

  function seekTo(clientX) {
    const rect = progressBar.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    if (audio.duration) {
      audio.currentTime = ratio * audio.duration;
    }
    updateProgress();
  }

  function updateNavButtons() {
    prevBtn.disabled = currentIndex <= 0;
    nextBtn.disabled = currentIndex < 0 || currentIndex >= tracks.length - 1;
  }

  function highlightActiveTrack() {
    trackListEl.querySelectorAll(".track-item").forEach((item, index) => {
      const isActive = index === currentIndex;
      item.classList.toggle("active", isActive);
      item.setAttribute("aria-selected", isActive ? "true" : "false");
    });

    const activeItem = trackListEl.querySelector(".track-item.active");
    if (activeItem) {
      activeItem.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }

  function renderTrackList() {
    trackListEl.innerHTML = "";

    tracks.forEach((track, index) => {
      const li = document.createElement("li");
      li.className = "track-item";
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", "false");
      li.dataset.index = String(index);

      const thumb = document.createElement("img");
      thumb.className = "track-item-thumb";
      thumb.src = track.thumbnail || "";
      thumb.alt = "";
      thumb.loading = "lazy";

      const info = document.createElement("div");
      info.className = "track-item-info";

      const title = document.createElement("div");
      title.className = "track-item-title";
      title.textContent = track.title;

      info.appendChild(title);

      const duration = document.createElement("span");
      duration.className = "track-item-duration";
      duration.textContent = formatTime(track.duration);

      li.appendChild(thumb);
      li.appendChild(info);
      li.appendChild(duration);

      li.addEventListener("click", () => playTrack(index, true));
      trackListEl.appendChild(li);
    });

    highlightActiveTrack();
    updateNavButtons();
  }

  function updatePlayerUI(track) {
    trackTitle.textContent = track.title;
    trackArtist.textContent = track.artist;
    durationTimeEl.textContent = formatTime(track.duration);

    if (track.thumbnail) {
      artworkImg.src = track.thumbnail;
      artworkImg.alt = `${track.title} artwork`;
      artworkImg.classList.add("visible");
      artworkPlaceholder.classList.add("hidden");
    } else {
      artworkImg.classList.remove("visible");
      artworkPlaceholder.classList.remove("hidden");
    }
  }

  function playTrack(index, autoPlay = true) {
    if (index < 0 || index >= tracks.length) return;

    const track = tracks[index];
    const switching = currentIndex !== index;
    currentIndex = index;

    updatePlayerUI(track);
    highlightActiveTrack();
    updateNavButtons();

    audio.src = track.audio_url;
    audio.load();
    playerEl.classList.remove("hidden");

    if (autoPlay) {
      audio.play().then(() => setPlayingState(true)).catch(() => {
        setStatus("Track loaded — press play to start.");
        setPlayingState(false);
      });
    } else {
      setPlayingState(false);
    }

    if (switching) {
      setStatus("");
    }
  }

  function playAdjacent(direction) {
    const nextIndex = currentIndex + direction;
    if (nextIndex >= 0 && nextIndex < tracks.length) {
      playTrack(nextIndex, true);
    }
  }

  searchForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = searchInput.value.trim();
    if (!query) return;

    searchBtn.disabled = true;
    setStatus("Searching…", "loading");
    audio.pause();
    setPlayingState(false);

    try {
      const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Search failed.");
      }

      tracks = data.tracks || [];
      if (!tracks.length) {
        throw new Error("No songs found for that artist.");
      }

      trackListHeading.textContent = `${data.artist} — Songs`;
      trackListSection.classList.remove("hidden");
      renderTrackList();

      const startIndex = Number.isInteger(data.start_index) ? data.start_index : 0;
      playTrack(startIndex, true);
      setStatus("");
    } catch (err) {
      setStatus(err.message, "error");
    } finally {
      searchBtn.disabled = false;
    }
  });

  playPauseBtn.addEventListener("click", () => {
    if (!audio.src) return;

    if (audio.paused) {
      audio.play().then(() => setPlayingState(true));
    } else {
      audio.pause();
      setPlayingState(false);
    }
  });

  prevBtn.addEventListener("click", () => playAdjacent(-1));
  nextBtn.addEventListener("click", () => playAdjacent(1));

  audio.addEventListener("timeupdate", () => {
    if (!isSeeking) updateProgress();
  });

  audio.addEventListener("loadedmetadata", updateProgress);

  audio.addEventListener("ended", () => {
    if (currentIndex < tracks.length - 1) {
      playTrack(currentIndex + 1, true);
    } else {
      setPlayingState(false);
      updateProgress();
    }
  });

  audio.addEventListener("play", () => setPlayingState(true));
  audio.addEventListener("pause", () => setPlayingState(false));

  progressBar.addEventListener("mousedown", (e) => {
    isSeeking = true;
    seekTo(e.clientX);
  });

  document.addEventListener("mousemove", (e) => {
    if (isSeeking) seekTo(e.clientX);
  });

  document.addEventListener("mouseup", () => {
    isSeeking = false;
  });

  progressBar.addEventListener("keydown", (e) => {
    if (!audio.duration) return;
    const step = 5;
    if (e.key === "ArrowRight") {
      audio.currentTime = Math.min(audio.duration, audio.currentTime + step);
      updateProgress();
    } else if (e.key === "ArrowLeft") {
      audio.currentTime = Math.max(0, audio.currentTime - step);
      updateProgress();
    }
  });
})();
