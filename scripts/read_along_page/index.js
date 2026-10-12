(function () {
  const C = window.CATALOGUE;
  const root = document.getElementById("lists");
  const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const mins = s => Math.round(s / 60) + " min";

  const group = l => l.verification.status === "failed" ? "failed"
    : l.word_check ? "checked" : l.verification.status;
  const groups = [
    ["checked", "Checked word by word", "A recogniser's word times exist, so stretches where the highlight is probably wrong are marked."],
    ["verified", "Verified alignment", "The placement check passed."],
    ["failed", "Failed the placement check", "Words are known to be in the wrong places."],
    ["unverified", "Unverified alignment", "Not yet checked. Watch for drift."],
  ];

  const badge = (l, status) => {
    if (status !== "checked") return `<span class="badge ${status}">${status}</span>`;
    const n = l.word_check.regions.length;
    return n ? `<span class="badge failed">${n} stretch${n > 1 ? "es" : ""} off</span>`
             : `<span class="badge verified">no stretch off</span>`;
  };
  for (const [status, heading, blurb] of groups) {
    const rows = C.lectures.filter(l => group(l) === status)
      .sort((a, b) => a.title.localeCompare(b.title));
    if (!rows.length) continue;
    let html = `<h2>${heading} <span class="sub">(${rows.length})</span></h2><p class="sub sans">${blurb}</p><ul class="list">`;
    for (const l of rows) {
      const notes = [];
      if (l.problems.length) notes.push("⚠ broken timings: " + l.problems.join("; "));
      if (!l.exact_seek) notes.push("original MP3: jumps land seconds early");
      if (l.legacy) notes.push(`timed before the cleanup fix (${l.legacy.dropped} written-only words timed as speech)`);
      if (l.duplicate_of) notes.push("same recording as " + l.duplicate_of);
      const unplaced = l.transcript_words - l.words_placed;
      if (unplaced > 0.05 * l.transcript_words) notes.push(`${unplaced.toLocaleString()} of ${l.transcript_words.toLocaleString()} words could not be placed`);
      if (l.verification.status === "verified" || l.verification.status === "failed") notes.push(`placement ratio ×${l.verification.worst_ratio} (limit ×${l.verification.limit})`);
      html += `<li><span class="t"><a href="player.html?l=${encodeURIComponent(l.slug)}">${esc(l.title)}</a>` +
        (notes.length ? `<span class="note">${esc(notes.join(" · "))}</span>` : "") +
        `</span><span class="m">${mins(l.duration)} · transcript covers ${Math.round(l.share_of_audio * 100)}%</span>` +
        badge(l, status) + `</li>`;
    }
    root.insertAdjacentHTML("beforeend", html + "</ul>");
  }

  if (C.refused.length) {
    let html = `<h2>Not shown <span class="sub">(${C.refused.length})</span></h2>` +
      `<p class="sub sans">The page and the aligner disagree about which word is which. Highlighting would be shifted, so these are withheld rather than shown wrongly.</p><ul class="list">`;
    for (const r of C.refused) {
      html += `<li><span class="t">${esc(r.slug)}<span class="note">${esc(r.reason)}</span></span><span class="badge refused">refused</span></li>`;
    }
    root.insertAdjacentHTML("beforeend", html + "</ul>");
  }
})();
