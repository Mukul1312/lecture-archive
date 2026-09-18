"use strict";

(() => {
  const SAVE_DELAY_MS = 700;
  const RETRY_MS = 5000;
  const POSITION_SAVE_MS = 15000;
  const SEEK_STEP_S = 3;
  const DELAY_STEP_MS = 500;
  const MAX_DELAY_MS = 60000;
  const SPEEDS = [0.75, 0.9, 1, 1.1, 1.25];
  const STATUS_LABEL = { unchecked: "not checked", ok: "checked", fixed: "corrected", unsure: "unsure" };

  const $ = (id) => document.getElementById(id);
  const player = $("player");
  const list = $("cues");

  let review = null;
  let rows = [];
  let current = -1;
  let dirty = false;
  let saving = false;
  let saveTimer = null;
  let lastPositionSave = 0;

  function clock(ms) {
    const total = Math.max(0, Math.floor(ms / 1000));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  function makeButton(label, title, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.title = title;
    button.addEventListener("click", onClick);
    return button;
  }

  // Checked cues are "ok" when the words are unchanged and "fixed" when corrected.
  function checkedStatus(cue) {
    return cue.text !== cue.original ? "fixed" : "ok";
  }

  function isChecked(cue) {
    return cue.status === "ok" || cue.status === "fixed";
  }

  function renderRow(cue, index) {
    const row = document.createElement("section");
    row.className = "cue";
    row.dataset.index = String(index);

    const head = document.createElement("div");
    head.className = "cue-head";
    const number = document.createElement("span");
    number.className = "num";
    number.textContent = `#${cue.n}`;
    const time = makeButton(clock(cue.start_ms), "Play from this cue", () => {
      seekToCue(index);
      player.play();
    });
    time.className = "time";
    const state = document.createElement("span");
    state.className = "state";
    const check = makeButton("✓ Checked", "Mark this cue checked (Ctrl+Enter)", () => {
      cue.status = isChecked(cue) ? "unchecked" : checkedStatus(cue);
      changed(index);
    });
    const unsure = makeButton("? Unsure", "Mark this cue as unsure", () => {
      cue.status = cue.status === "unsure" ? "unchecked" : "unsure";
      changed(index);
    });
    const revert = makeButton("↺ Revert", "Restore the subtitle's original words", () => {
      cue.text = cue.original;
      text.value = cue.text;
      if (isChecked(cue)) cue.status = checkedStatus(cue);
      changed(index);
    });
    head.append(number, time, state, check, unsure, revert);

    const text = document.createElement("textarea");
    text.className = "text";
    text.value = cue.text;
    text.rows = Math.max(2, cue.text.split("\n").length);
    text.spellcheck = false;
    text.setAttribute("aria-label", `Cue ${cue.n} words`);
    text.addEventListener("input", () => {
      cue.text = text.value;
      if (cue.text !== cue.original) cue.status = "fixed";
      else if (cue.status === "fixed") cue.status = "ok";
      changed(index);
    });

    const original = document.createElement("div");
    original.className = "original";
    original.textContent = `Subtitle said: ${cue.original}`;

    const note = document.createElement("input");
    note.type = "text";
    note.className = "note";
    note.placeholder = "Note (optional)";
    note.value = cue.note;
    note.setAttribute("aria-label", `Cue ${cue.n} note`);
    note.addEventListener("input", () => {
      cue.note = note.value;
      changed(index);
    });

    row.append(head, text, original, note);
    return { row, text, state, original, check, unsure, revert };
  }

  function paint(index) {
    const cue = review.cues[index];
    const view = rows[index];
    view.row.classList.remove("status-unchecked", "status-ok", "status-fixed", "status-unsure");
    view.row.classList.add(`status-${cue.status}`);
    view.row.classList.toggle("edited", cue.text !== cue.original);
    view.state.textContent = STATUS_LABEL[cue.status];
    view.check.setAttribute("aria-pressed", String(isChecked(cue)));
    view.unsure.setAttribute("aria-pressed", String(cue.status === "unsure"));
    view.revert.disabled = cue.text === cue.original;
  }

  function changed(index) {
    paint(index);
    markDirty();
  }

  function progress() {
    const tally = { unchecked: 0, ok: 0, fixed: 0, unsure: 0 };
    for (const cue of review.cues) tally[cue.status] += 1;
    const checked = tally.ok + tally.fixed;
    $("progress").textContent =
      `Checked ${checked} / ${review.cues.length} · corrected ${tally.fixed} · unsure ${tally.unsure}`;
  }

  function cueAt(ms) {
    let low = 0;
    let high = review.cues.length - 1;
    let found = -1;
    while (low <= high) {
      const mid = (low + high) >> 1;
      if (review.cues[mid].start_ms <= ms) {
        found = mid;
        low = mid + 1;
      } else {
        high = mid - 1;
      }
    }
    return found;
  }

  function typingInList() {
    const element = document.activeElement;
    return Boolean(element && list.contains(element) && (element.tagName === "TEXTAREA" || element.tagName === "INPUT"));
  }

  function followAudio() {
    const index = cueAt(player.currentTime * 1000 - review.offset_ms);
    if (index !== current) {
      if (current >= 0) rows[current].row.classList.remove("current");
      current = index;
      if (index >= 0) {
        rows[index].row.classList.add("current");
        if ($("follow").checked && !typingInList()) {
          rows[index].row.scrollIntoView({ block: "center", behavior: "smooth" });
        }
      }
    }
    const now = Date.now();
    if (!player.paused && now - lastPositionSave > POSITION_SAVE_MS) {
      lastPositionSave = now;
      review.last_position_s = player.currentTime;
      markDirty();
    }
  }

  function seekToCue(index) {
    player.currentTime = Math.max(0, (review.cues[index].start_ms + review.offset_ms) / 1000);
  }

  function focusCue(index, { seek } = { seek: false }) {
    if (index < 0 || index >= rows.length) return;
    rows[index].row.scrollIntoView({ block: "center" });
    rows[index].text.focus({ preventScroll: true });
    if (seek) seekToCue(index);
  }

  function focusedIndex() {
    const row = document.activeElement && document.activeElement.closest(".cue");
    return row ? Number(row.dataset.index) : null;
  }

  function showState(message, kind) {
    const element = $("save-state");
    element.textContent = message;
    element.className = `save-${kind}`;
  }

  function payload() {
    return JSON.stringify({
      schema: review.schema,
      source_srt: review.source_srt,
      source_srt_sha256: review.source_srt_sha256,
      audio: review.audio,
      offset_ms: review.offset_ms,
      last_position_s: review.last_position_s,
      session_notes: review.session_notes,
      cues: review.cues,
    });
  }

  function markDirty() {
    dirty = true;
    showState("Unsaved changes…", "pending");
    progress();
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, SAVE_DELAY_MS);
  }

  async function save() {
    clearTimeout(saveTimer);
    if (saving) {
      saveTimer = setTimeout(save, SAVE_DELAY_MS);
      return;
    }
    saving = true;
    dirty = false;
    showState("Saving…", "pending");
    try {
      const response = await fetch("/api/review", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Reference-Editor": "1" },
        body: payload(),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
      showState(`Saved ${new Date().toLocaleTimeString()}`, "ok");
    } catch (error) {
      dirty = true;
      showState(`NOT SAVED: ${error.message}. Retrying…`, "error");
      saveTimer = setTimeout(save, RETRY_MS);
    } finally {
      saving = false;
    }
  }

  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  // Exports read the saved file, so flush pending edits first; stay put if saving fails.
  async function flushThenOpen(href) {
    while (saving) await wait(100);
    if (dirty) await save();
    while (saving) await wait(100);
    if (!dirty) window.location.href = href;
  }

  function setDelay(ms) {
    review.offset_ms = Math.max(-MAX_DELAY_MS, Math.min(MAX_DELAY_MS, ms));
    const seconds = review.offset_ms / 1000;
    $("delay").textContent = `${seconds >= 0 ? "+" : ""}${seconds.toFixed(1)} s`;
    if (current >= 0) rows[current].row.classList.remove("current");
    current = -1;
    followAudio();
  }

  function buildControls() {
    const speeds = $("speeds");
    for (const rate of SPEEDS) {
      const button = makeButton(`${rate}×`, `Play at ${rate}× speed`, () => {
        player.playbackRate = rate;
        for (const other of speeds.children) other.setAttribute("aria-pressed", String(other === button));
      });
      button.setAttribute("aria-pressed", String(rate === 1));
      speeds.append(button);
    }
    $("delay-minus").addEventListener("click", () => { setDelay(review.offset_ms - DELAY_STEP_MS); markDirty(); });
    $("delay-plus").addEventListener("click", () => { setDelay(review.offset_ms + DELAY_STEP_MS); markDirty(); });
    $("delay-reset").addEventListener("click", () => { setDelay(0); markDirty(); });
    $("next-unchecked").addEventListener("click", () => {
      const from = Math.max(0, focusedIndex() ?? current);
      for (let step = 1; step <= review.cues.length; step += 1) {
        const index = (from + step) % review.cues.length;
        if (review.cues[index].status === "unchecked") {
          focusCue(index, { seek: true });
          return;
        }
      }
    });
    const notes = $("session-notes");
    notes.value = review.session_notes;
    notes.addEventListener("input", () => {
      review.session_notes = notes.value;
      markDirty();
    });
    for (const id of ["export-srt", "export-log"]) {
      const link = $(id);
      link.addEventListener("click", (event) => {
        event.preventDefault();
        flushThenOpen(link.href);
      });
    }
  }

  function bindKeys() {
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        if (player.paused) player.play(); else player.pause();
      } else if (event.key === "F2") {
        event.preventDefault();
        player.currentTime = Math.max(0, player.currentTime - SEEK_STEP_S);
      } else if (event.key === "F4") {
        event.preventDefault();
        player.currentTime = Math.min(player.duration || Number.MAX_VALUE, player.currentTime + SEEK_STEP_S);
      } else if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        const index = focusedIndex() ?? current;
        if (index === null || index < 0) return;
        const cue = review.cues[index];
        cue.status = checkedStatus(cue);
        changed(index);
        focusCue(index + 1);
      }
    });
    window.addEventListener("beforeunload", (event) => {
      if (dirty || saving) {
        event.preventDefault();
        event.returnValue = "";
      }
    });
  }

  async function start() {
    try {
      const response = await fetch("/api/review", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      review = await response.json();
    } catch (error) {
      const message = $("load-error");
      message.textContent = `Could not load the review: ${error.message}. Is the editor still running?`;
      message.hidden = false;
      return;
    }
    const fragment = document.createDocumentFragment();
    rows = review.cues.map((cue, index) => {
      const view = renderRow(cue, index);
      fragment.append(view.row);
      return view;
    });
    list.append(fragment);
    rows.forEach((_, index) => paint(index));
    buildControls();
    bindKeys();
    setDelay(review.offset_ms);
    progress();
    showState("All changes saved", "ok");
    player.src = review.audio_src;
    player.addEventListener("timeupdate", followAudio);
    player.addEventListener("seeked", followAudio);
    player.addEventListener("loadedmetadata", () => {
      if (review.last_position_s > 0) player.currentTime = review.last_position_s;
      followAudio();
    }, { once: true });
    player.addEventListener("error", () => {
      showState("Audio could not be loaded. Check the network or pass a local file with --audio.", "error");
    });
  }

  start();
})();
