(function () {
  const slug = new URLSearchParams(location.search).get("l");
  const $ = id => document.getElementById(id);
  const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const clock = s => {
    s = Math.max(0, s);
    const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, sec = (s % 60).toFixed(1).padStart(4, "0");
    return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + sec;
  };
  const span = s => s >= 90 ? Math.round(s / 60) + " min" : Math.round(s) + " s";
  const store = {
    get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
  };

  if (!slug) { $("title").textContent = "No lecture chosen"; return; }
  const loader = document.createElement("script");
  loader.src = "lectures/" + encodeURIComponent(slug) + ".js";
  loader.onload = () => start(window.LECTURE);
  loader.onerror = () => { $("title").textContent = "This lecture has no read-along data."; };
  document.head.appendChild(loader);

  function statusHtml(L) {
    const v = L.verification, parts = [], c = L.word_check;
    if (c) {
      const pct = c.words_checked ? (100 * c.words_off / c.words_checked).toFixed(1) : "0";
      const share = Math.round(100 * c.words_checked / L.transcript_words);
      const where = c.regions.slice(0, 12).map(([a, b, n]) =>
        `<a href="#" class="jump" data-t="${a}">${clock(a)}</a> (${span(b - a)}, ${n} words)`).join(", ");
      parts.push(`<div class="status ${c.regions.length ? "failed" : "verified"}"><b>Checked word by word against ${esc(c.against)}.</b> ` +
        `${c.words_checked.toLocaleString()} words (${share}%) could be compared with where ${esc(c.against)} heard them; ` +
        `${pct}% sit more than ${c.agree_seconds} s away. ` +
        (c.regions.length
          ? `<b>${c.regions.length} stretch${c.regions.length > 1 ? "es" : ""} (${span(c.seconds_in_regions)}) disagree</b>, underlined in red and marked red on the timeline: ${where}${c.regions.length > 12 ? ", …" : ""}. Read on one lecture, the large ones (5 s or more) are real: words stretched over a chanted verse or over speech the transcript leaves out. Small ones (1–3 s) are often the speaker saying a phrase twice that the transcript writes once, so the highlight is on one of the two sayings.`
          : `No stretch disagrees. Words that do not sit in a run both systems agree on are unchecked, not confirmed.`) + `</div>`);
    }
    if (v.status === "verified") {
      const sys = Object.entries(v.systems).map(([n, s]) =>
        `${n} ${(s.span_error * 100).toFixed(1)}% inside against ${(s.whole_file_error * 100).toFixed(1)}% whole file`).join("; ");
      parts.push(`<div class="status verified"><b>Passed the placement check.</b> Two speech recognisers were scored inside the stretches where this transcript is trusted and over the whole file (${esc(sys)}). The worst inside-to-whole ratio is ×${v.worst_ratio}, under the ×${v.limit} limit. That rules out the transcript being laid against the wrong part of the recording. It <b>cannot</b> see a stretch shifted by seconds or minutes, which is what the word-by-word check below is for.</div>`);
    } else if (v.status === "failed") {
      parts.push(`<div class="status failed"><b>This alignment failed the placement check</b> (×${v.worst_ratio} against a limit of ×${v.limit}). Words are in the wrong places. It is shown so the fault can be watched and heard, not read along with.</div>`);
    } else {
      parts.push(`<div class="status unverified"><b>Unverified alignment.</b> Nobody has checked where these words landed. The highlighting may be right, or it may drift ahead of or behind the voice. If it does, press <kbd>M</kbd> to mark the moment.</div>`);
    }
    if (L.legacy) {
      parts.push(`<div class="status unverified"><b>Timed before the cleanup fix.</b> ${L.legacy.dropped.toLocaleString()} written words that nobody says aloud, such as his name written before each answer or a verse reference, were timed as if spoken. They are now shown as notes, but the highlight may run late after them until this lecture is re-timed.</div>`);
    }
    if (!L.exact_seek) {
      parts.push(`<div class="status unverified"><b>Jumping in this recording lands seconds early.</b> It is still the archive's original variable-bitrate MP3. Measured on one lecture, a jump landed 4 to 9 seconds before the time asked for while the player showed the right time, so after clicking a word or the timeline the highlight runs ahead of the voice. Whether playing straight through from the start stays in step has not been measured. A copy that jumps accurately is made by <code>scripts.read_along --encode</code>.</div>`);
    }
    if (L.problems.length) {
      parts.push(`<div class="status broken"><b>Broken timings:</b> ${esc(L.problems.join("; "))}. Highlighting near these words will be wrong.</div>`);
    }
    const notes = [`The transcript covers ${Math.round(L.share_of_audio * 100)}% of the recording. Hatched stretches have no transcript, and what they contain has not been checked.`];
    const unplaced = L.transcript_words - L.words_placed;
    if (unplaced) notes.push(`${unplaced.toLocaleString()} of ${L.transcript_words.toLocaleString()} words could not be placed and are shown faint.`);
    notes.push("These transcripts are edited for reading and often leave out questions from the floor, so a short question may pass with nothing highlighted.");
    if (L.duplicate_of) notes.push(`This is the same audio file as “${esc(L.duplicate_of)}”, published under a second page.`);
    parts.push(`<p class="sub sans">${notes.join(" ")}</p>`);
    return parts.join("");
  }

  function start(L) {
    document.title = L.title + " · Read-Along";
    $("title").textContent = L.title;
    $("status").innerHTML = statusHtml(L);
    const audio = $("audio");
    let requested = null, seekWarned = false;
    const seek = t => { requested = Math.max(0, t); audio.currentTime = requested; };
    audio.src = L.audio;
    audio.addEventListener("error", () => {
      $("status").insertAdjacentHTML("afterbegin", `<div class="status failed"><b>The audio file did not load</b> (${esc(L.audio)}). Audio is gitignored and lives only on this machine. Fetch it with <code>python scripts/taptajivanam_mirror.py fetch</code>.</div>`);
    });

    // --- the text, one element per spoken word, numbered as the aligner numbered it ---
    const els = new Array(L.timing.length);
    const text = $("text");
    const frag = document.createDocumentFragment();
    for (const para of L.paragraphs) {
      const p = document.createElement("p");
      for (const [word, index] of para) {
        const el = document.createElement("span");
        el.textContent = word;
        if (index === null) {
          el.className = "n";
        } else {
          const t = L.timing[index];
          // Only words inside a marked stretch: a lone disagreeing word is not evidence of a fault.
          const off = t && t[3] !== null && t[3] !== undefined && Math.abs(t[3]) > L.word_check.agree_seconds
            && L.word_check.regions.some(([a, b]) => t[0] >= a && t[1] <= b);
          el.className = "w" + (t ? (t[2] ? "" : " outside") : " unplaced") + (off ? " off" : "");
          if (off) el.title = `Placed ${Math.abs(t[3]).toFixed(1)} s ${t[3] < 0 ? "earlier" : "later"} than ${L.word_check.against} heard it.`;
          el.dataset.i = index;
          if (!t) el.title = "The aligner could not place this word, so it is never highlighted.";
          els[index] = el;
        }
        p.appendChild(el);
        p.appendChild(document.createTextNode(" "));
      }
      frag.appendChild(p);
    }
    text.appendChild(frag);

    // Placed words in time order. The invariants say index order and time order agree; sorting
    // by start keeps the search correct even when they do not.
    const order = [];
    L.timing.forEach((t, i) => { if (t) order.push(i); });
    order.sort((a, b) => L.timing[a][0] - L.timing[b][0]);
    const starts = order.map(i => L.timing[i][0]);
    const ends = order.map(i => L.timing[i][1]);

    // --- untranscribed stretches, in the text and on the timeline ---
    const gapEls = L.untranscribed.map(([a, b]) => {
      const el = document.createElement("span");
      el.className = "gap";
      el.textContent = `${clock(a)} – ${clock(b)} · ${span(b - a)} of audio with no transcript`;
      el.addEventListener("click", () => { seek(a); audio.play(); following = true; });
      const k = starts.findIndex(s => s >= b - 0.001);
      if (k === -1) text.appendChild(el);
      else els[order[k]].parentNode.insertBefore(el, els[order[k]]);
      return el;
    });
    const timeline = $("timeline");
    for (const [a, b] of L.spans) {
      const d = document.createElement("div");
      d.className = "span";
      d.style.left = (a / L.duration * 100) + "%";
      d.style.width = Math.max(0.1, (b - a) / L.duration * 100) + "%";
      timeline.appendChild(d);
    }
    for (const [a, b] of (L.word_check ? L.word_check.regions : [])) {
      const d = document.createElement("div");
      d.className = "fault";
      d.style.left = (a / L.duration * 100) + "%";
      d.style.width = Math.max(0.3, (b - a) / L.duration * 100) + "%";
      timeline.appendChild(d);
    }
    $("status").addEventListener("click", e => {
      const a = e.target.closest(".jump");
      if (!a) return;
      e.preventDefault();
      seek(+a.dataset.t); audio.play(); following = true;
    });
    timeline.addEventListener("click", e => {
      const r = timeline.getBoundingClientRect();
      seek((e.clientX - r.left) / r.width * (audio.duration || L.duration));
      following = true;
    });

    // --- following the voice ---
    let current = -1, currentGap = -1, following = true;
    const locate = t => {
      let lo = 0, hi = starts.length - 1, at = -1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (starts[mid] <= t) { at = mid; lo = mid + 1; } else hi = mid - 1;
      }
      return at;
    };
    function tick() {
      const t = audio.currentTime;
      const k = locate(t);
      let word = -1, waiting = false;
      if (k >= 0) {
        // The page follows the published text, which is edited: about once a minute he says
        // something it does not contain. Rather than vanish, the highlight waits on the last
        // written word - shown as waiting, so it does not claim he is still saying it - until
        // the next written word begins. A breath after a word still counts as the word.
        word = order[k];
        const next = k + 1 < starts.length ? starts[k + 1] : Infinity;
        waiting = t >= Math.max(ends[k], Math.min(next, ends[k] + 1.5));
      }
      if (word !== current) {
        if (current >= 0) els[current].classList.remove("on", "wait");
        current = word;
        if (current >= 0 && following) keepInView(els[current]);
      }
      if (current >= 0) {
        els[current].classList.toggle("on", !waiting);
        els[current].classList.toggle("wait", waiting);
      }
      const g = L.untranscribed.findIndex(([a, b]) => t >= a && t < b);
      if (g !== currentGap) {
        if (currentGap >= 0) gapEls[currentGap].classList.remove("on");
        currentGap = g;
        if (g >= 0) { gapEls[g].classList.add("on"); if (following) keepInView(gapEls[g]); }
      }
      const here = $("here");
      here.textContent = clock(t) + (g >= 0 ? " · no transcript here"
        : waiting ? " · waiting for the next written words" : "");
      here.classList.toggle("none", g >= 0);
      $("head").style.left = (t / (audio.duration || L.duration) * 100) + "%";
    }
    function keepInView(el) {
      const r = el.getBoundingClientRect(), top = $("audio").closest(".bar").getBoundingClientRect().bottom;
      if (r.top < top + 30 || r.bottom > innerHeight * 0.75) {
        programmatic = Date.now();
        el.scrollIntoView({block: "center", behavior: "smooth"});
      }
    }
    let programmatic = 0;
    const stopFollowing = () => {
      if (Date.now() - programmatic < 800) return;
      following = false;
      $("follow").hidden = false;
    };
    addEventListener("wheel", stopFollowing, {passive: true});
    addEventListener("touchmove", stopFollowing, {passive: true});
    $("follow").addEventListener("click", () => {
      following = true; $("follow").hidden = true;
      if (current >= 0) keepInView(els[current]);
    });

    let frame = 0;
    const loop = () => { tick(); frame = audio.paused ? 0 : requestAnimationFrame(loop); };
    audio.addEventListener("play", () => { if (!frame) frame = requestAnimationFrame(loop); });
    audio.addEventListener("seeked", () => {
      // A server without HTTP range support, or a file the browser cannot index, lands a seek
      // somewhere else - often at zero - and the highlight would follow it there silently.
      if (requested !== null && Math.abs(audio.currentTime - requested) > 1 && !seekWarned) {
        seekWarned = true;
        $("status").insertAdjacentHTML("afterbegin", `<div class="status failed"><b>Jumping did not land where asked</b> (asked for ${clock(requested)}, got ${clock(audio.currentTime)}). The highlight follows where the audio really is, but jumping is unreliable here. Open the page from disk, or serve it with a server that supports range requests.</div>`);
      }
      requested = null;
      tick();
    });
    audio.addEventListener("timeupdate", () => { if (!frame) tick(); });

    text.addEventListener("click", e => {
      const el = e.target.closest(".w");
      if (!el) return;
      const t = L.timing[+el.dataset.i];
      if (!t) return;
      seek(t[0]);
      following = true; $("follow").hidden = true;
      audio.play();
    });

    $("speed").addEventListener("change", e => { audio.playbackRate = +e.target.value; });

    // --- resume where the listener left off ---
    const posKey = "ra-pos:" + slug;
    const saved = store.get(posKey);
    if (saved > 10) {
      const b = $("resume");
      b.hidden = false;
      b.textContent = "Resume at " + clock(saved);
      b.addEventListener("click", () => { seek(saved); audio.play(); b.hidden = true; });
    }
    setInterval(() => { if (!audio.paused) store.set(posKey, audio.currentTime); }, 5000);

    // --- faults the listener notices ---
    const faultKey = "ra-faults:" + slug;
    let faults = store.get(faultKey) || [];
    function renderFaults() {
      $("faultlist").innerHTML = faults.map(f =>
        `<li>${clock(f.time)}: highlighted ${f.index === null ? "nothing" : `#${f.index} “${esc(f.word)}”`}</li>`).join("");
      $("faulttext").value = faults.length ? `${slug}\n` + faults.map(f =>
        `${f.time.toFixed(2)}\t${f.index === null ? "-" : f.index}\t${f.word || ""}`).join("\n") : "";
    }
    function mark() {
      faults.push({time: audio.currentTime, index: current >= 0 ? current : null,
                   word: current >= 0 ? els[current].textContent : null});
      store.set(faultKey, faults);
      renderFaults();
    }
    $("mark").addEventListener("click", mark);
    $("clearfaults").addEventListener("click", () => { faults = []; store.set(faultKey, faults); renderFaults(); });
    renderFaults();

    addEventListener("keydown", e => {
      if (e.target.closest("textarea, select, input") || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === " " && e.target === document.body) { e.preventDefault(); audio.paused ? audio.play() : audio.pause(); }
      else if (e.key === "ArrowLeft" && e.target === document.body) { seek(audio.currentTime - 5); }
      else if (e.key === "ArrowRight" && e.target === document.body) { seek(audio.currentTime + 5); }
      else if (e.key === "m" || e.key === "M") { mark(); }
    });
    tick();
  }
})();
