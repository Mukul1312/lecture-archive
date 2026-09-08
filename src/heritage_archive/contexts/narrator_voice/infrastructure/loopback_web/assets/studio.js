"use strict";

(() => {
  if (document.body.hasAttribute("data-narrator-bootstrap")) {
    // Navigation timing survives this reload without storing private browser state.
    const navigation = performance.getEntriesByType("navigation")[0];
    if (navigation && navigation.type !== "reload") window.location.reload();
    return;
  }

  const message = document.getElementById("result");
  const csrf = document.querySelector('meta[name="narrator-csrf"]').content;
  const text = value => value.replace(/\r\n?/g, "\n").normalize("NFC");
  const integer = value => {
    if (!/^(0|[1-9][0-9]*)$/.test(value)) throw new Error();
    const number = Number(value);
    if (!Number.isSafeInteger(number)) throw new Error();
    return number;
  };
  const controls = source => {
    const values = JSON.parse(source);
    if (!Array.isArray(values)) throw new Error();
    return values.map(value => {
      if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error();
      switch (value.kind) {
        case "break":
          return {kind: "break", boundary: value.boundary, durationMs: value.durationMs};
        case "speed":
        case "volume":
          return {kind: value.kind, start: value.start, end: value.end, value: value.value};
        case "spelling":
          return {kind: "spelling", start: value.start, end: value.end, spelling: text(value.spelling)};
        default: throw new Error();
      }
    });
  };
  const bodyFor = form => {
    const value = name => form.elements.namedItem(name).value;
    const expected = () => integer(value("expectedRevision"));
    const passages = () => text(value("passages")).split(/\n\n+/).map(passage => ({text: passage}));
    const overrideValue = (modeName, valueName) => value(modeName) === "set" ? value(valueName) : null;
    switch (form.dataset.kind) {
      case "episode": return {};
      case "authority": return {evidenceDigest: value("evidenceDigest"), validFrom: value("validFrom"), validUntil: value("validUntil")};
      case "diary": return {passages: passages()};
      case "intro": return {expectedEpisodeRevision: integer(value("expectedEpisodeRevision")), passages: passages()};
      case "text": return {expectedRevision: expected(), text: text(value("text"))};
      case "order": return {expectedRevision: expected(), orderedPassageIds: value("orderedPassageIds").split(/\r?\n/)};
      case "defaults": return {expectedRevision: expected(), speed: value("speed"), volume: value("volume"), emotion: value("emotion") || null};
      case "recipe": {
        const mode = value("mode");
        return {expectedRevision: expected(), mode,
          structuredControls: mode === "structured" ? controls(value("structuredControls")) : [],
          advancedSource: mode === "advanced" ? text(value("advancedSource")) : null};
      }
      case "require-recipe": return {expectedRevision: expected(), recipeId: value("recipeId")};
      case "dictionary": return {expectedRevision: expected()};
      case "estimate": return {expectedRevision: expected(), passageId: value("passageId"), recipeId: value("recipeId"),
        speedMode: value("speedMode"), speed: overrideValue("speedMode", "speed"),
        volumeMode: value("volumeMode"), volume: overrideValue("volumeMode", "volume"),
        emotionMode: value("emotionMode"), emotion: overrideValue("emotionMode", "emotion"),
        dictionaryMode: value("dictionaryMode")};
      case "generate": return {confirmationToken: value("confirmationToken")};
      case "reconcile": return {expectedRevision: expected()};
      default: throw new Error();
    }
  };
  const guidance = {
    stale_revision: "State changed. Reload and reapply your changes.",
    authority_exists: "The configured authority is already registered. Reload the page.",
    episode_exists: "The episode already exists. Reload the page.",
    studio_busy: "The studio is busy. Review the current state before submitting again.",
    already_required: "This recipe is already required. Reload the page.",
    unsupported_state: "Studio state is unsupported. Check the local store with CLI doctor.",
    dictionary_unavailable: "No configured dictionary is available for this lane.",
    authority_denied: "Current authority does not permit this operation.",
    validation_failed: "The change could not be validated. Review the current text, controls and state.",
    invalid_input: "Check the field formats and values.",
    invalid_json: "Check the field formats and values.",
    session_required: "The studio session changed. Reload the page.",
    not_found: "The requested resource is unavailable. Reload the page.",
    generation_busy: "Generation or reconciliation is already active. Try this confirmation again after it finishes.",
    confirmation_capacity: "Confirmation capacity is full after saving the estimate. Reload before estimating again.",
    confirmation_unavailable: "This confirmation is unavailable. Reload and create a fresh estimate.",
    reconciliation_unavailable: "This generation attempt is not eligible for reconciliation. Reload the page."
  };

  document.querySelectorAll("form[data-kind]").forEach(form => {
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const buttons = Array.from(form.querySelectorAll('button[type="submit"]'));
      if (buttons.some(button => button.disabled)) return;
      let body;
      try { body = bodyFor(form); }
      catch { message.textContent = "Check the field formats and values."; return; }
      buttons.forEach(button => { button.disabled = true; });
      message.textContent = "Saving…";
      try {
        const response = await fetch(form.getAttribute("action"), {
          method: "POST", credentials: "same-origin", cache: "no-store", redirect: "error",
          headers: {"Content-Type": "application/json", "X-Narrator-CSRF": csrf},
          body: JSON.stringify(body)
        });
        const result = await response.json();
        if (response.ok && result.ok === true) {
          if (form.dataset.kind === "estimate") {
            const panel = form.closest("[data-generation-panel]");
            const estimateResult = panel.querySelector("[data-estimate-result]");
            estimateResult.querySelector("[data-estimate-projection]").textContent = result.result.canonicalProjection;
            estimateResult.querySelector("[data-estimate-billable]").textContent = String(result.result.billableCharacters);
            estimateResult.querySelector("[data-estimate-usage]").textContent = result.result.estimatedUsage;
            estimateResult.hidden = false;
            const generate = panel.querySelector('form[data-kind="generate"]');
            generate.elements.namedItem("confirmationToken").value = result.result.confirmationToken;
            generate.hidden = false;
            message.textContent = "Estimate saved. Review it, then confirm this take once.";
            buttons.forEach(button => { button.disabled = false; });
            return;
          }
          window.location.reload();
          return;
        }
        message.textContent = guidance[result.error?.code] || "The request could not be completed. Check the studio state before submitting again.";
      } catch {
        message.textContent = "The response was lost. Reload and inspect the current state before submitting again.";
      }
      buttons.forEach(button => { button.disabled = false; });
    });
  });
})();
