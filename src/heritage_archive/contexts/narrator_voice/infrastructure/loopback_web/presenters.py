"""Explicit browser allowlists and escaped semantic local HTML."""
from html import escape
import json

from ...domain.values import BreakControl, SpeedControl, VolumeControl, SpellingControl

BACKUP_GUIDANCE = "backup history is not persisted; use CLI backup and verify-backup"
_ISSUE_CODES = frozenset({"layout_missing", "path_reparse", "path_nonregular", "path_unreadable",
    "config_missing", "config_invalid", "staging_nonempty", "json_noncanonical", "json_invalid",
    "revision_name_invalid", "revision_gap"})


def readiness(value):
    return {"healthy": value.healthy, "checkedFileCount": value.checked_file_count,
            "issueCodes": [code if code in _ISSUE_CODES else "storage_issue" for code in value.issue_codes],
            "backupGuidance": BACKUP_GUIDANCE}


def authority(lane, value):
    return {"lane": lane.value, "present": value is not None,
            "revision": None if value is None else value.revision,
            "status": None if value is None else value.status.value,
            "withdrawn": False if value is None else value.withdrawn,
            "validFrom": None if value is None else value.valid_from.isoformat(),
            "validUntil": None if value is None else value.valid_until.isoformat(),
            "coveredOperations": [] if value is None else [op.value for op in value.covered_operations]}


def episode(value):
    return {"episodeId": value.episode_id.value, "revision": value.revision,
            "status": value.status.value, "assemblyReady": value.assembly_ready}


def editor(value):
    return {"jobId": value.job_id.value, "revision": value.revision, "lane": value.lane.value,
            "defaults": {"speed": value.defaults.speed, "volume": value.defaults.volume,
                         "emotion": value.defaults.emotion, "dictionaryConfigured": value.defaults.dictionary_configured},
            "passages": [{"passageId": passage.passage_id.value, "order": passage.order,
                "text": passage.text, "textRevision": passage.text_revision,
                "recipes": [{"recipeId": recipe.recipe_id.value, "revision": recipe.revision,
                             "textRevision": recipe.text_revision, "controls": [control(item) for item in recipe.controls],
                             "current": recipe.current, "required": recipe.required} for recipe in passage.recipes],
                "recipeRequired": passage.recipe_required, "dictionaryRequired": passage.dictionary_required,
                "latestPreview": preview(passage.latest_preview)} for passage in value.passages]}


def control(value):
    if type(value) is BreakControl:
        return {"kind": "break", "boundary": value.boundary, "durationMs": value.duration_ms}
    if type(value) in (SpeedControl, VolumeControl):
        return {"kind": "speed" if type(value) is SpeedControl else "volume",
                "start": value.span.start, "end": value.span.end, "value": value.value.value}
    if type(value) is SpellingControl:
        return {"kind": "spelling", "start": value.span.start, "end": value.span.end, "spelling": value.spelling}
    raise ValueError("unsupported public control")


def preview(value):
    if value is None:
        return None
    return {"previewId": value.preview_id.value, "baseJobRevision": value.base_job_revision,
            "canonicalProjection": value.canonical_projection, "billableCharacters": value.billable_characters,
            "estimatedUsage": value.estimated_usage, "issuedAt": value.issued_at.isoformat()}


def e(value):
    return escape(str(value), quote=True)


def document(csrf_token, content):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta name="narrator-csrf" content="' + e(csrf_token) + '">'
            '<title>Narration studio</title><link rel="stylesheet" href="/assets/studio.css">'
            '<script src="/assets/studio.js" defer></script></head><body><main>'
            '<h1>Narration studio</h1><p id="result" role="status" aria-live="polite"></p>'
            + content + '</main></body></html>').encode("utf-8")


def form(path, kind, content, label):
    return '<form method="post" action="' + e(path) + '" data-kind="' + e(kind) + '">' + content + '<button type="submit">' + e(label) + '</button></form>'


def field(name, label, value="", *, textarea=False):
    control = ('<textarea name="' + e(name) + '">' + e(value) + '</textarea>') if textarea else (
        '<input name="' + e(name) + '" value="' + e(value) + '" required>')
    return '<label>' + e(label) + control + '</label>'


def revision(value):
    return '<input type="hidden" name="expectedRevision" value="' + e(value) + '">'


def unavailable_page(csrf_token):
    return document(csrf_token, '<p>Studio unavailable. Authoring is disabled; check the local store with CLI doctor.</p><p>' + BACKUP_GUIDANCE + '</p>')


def page(csrf_token, health, current_episode, authorities, jobs):
    parts = ['<section><h2>Storage readiness</h2><p>' + ('Healthy' if health['healthy'] else 'Needs attention')
             + '; checked files: ' + e(health['checkedFileCount']) + '</p><p>' + e(', '.join(health['issueCodes']))
             + '</p><p>' + BACKUP_GUIDANCE + '</p></section><section><h2>Episode</h2>']
    if current_episode is None:
        parts.append(form('/api/v1/episode', 'episode', '', 'Create episode'))
    else:
        parts.append('<p>' + e(current_episode['episodeId']) + ' revision ' + e(current_episode['revision']) + ': ' + e(current_episode['status']) + '</p>')
    parts.append('</section><section><h2>Authority registration and validity</h2><p>Record validity does not establish generation readiness.</p>')
    for record in authorities:
        parts.append('<h3>' + ('Lane B — diary' if record['lane'] == 'lane_b' else 'Lane C — intro') + '</h3><p>' + e(record['status'] or 'not registered') + '</p>')
        if record['present']:
            parts.append('<p>Revision ' + e(record['revision']) + '; ' + e(record['validFrom']) + ' to ' + e(record['validUntil']) + '; operations: ' + e(', '.join(record['coveredOperations'])) + '</p>')
        elif record['lane'] == 'lane_b' or current_episode is not None:
            parts.append(form('/api/v1/authority/' + record['lane'], 'authority',
                field('evidenceDigest', 'Evidence SHA-256') + field('validFrom', 'Valid from (UTC, with seconds)') + field('validUntil', 'Valid until (UTC, with seconds)'), 'Register configured authority'))
        else:
            parts.append('<p>Create the episode before registering intro authority.</p>')
    parts.append('</section><section><h2>Prepare narration</h2>')
    parts.append(form('/api/v1/jobs/diary', 'diary', field('passages', 'Passages (separate with a blank line)', textarea=True), 'Prepare diary'))
    if current_episode is not None:
        parts.append(form('/api/v1/jobs/intro', 'intro', '<input type="hidden" name="expectedEpisodeRevision" value="' + e(current_episode['revision']) + '">' + field('passages', 'Intro passages (separate with a blank line)', textarea=True), 'Prepare intro'))
    parts.append('</section>')
    for job in jobs:
        parts.append('<section><h2>' + e(job['lane']) + ' job ' + e(job['jobId']) + '</h2><p>Revision ' + e(job['revision']) + '</p>')
        base = '/api/v1/jobs/' + job['jobId']
        expected = revision(job['revision'])
        defaults = job['defaults']
        parts.append(form(base + '/defaults', 'defaults', expected + field('speed', 'Speed (0.60–1.50)', defaults['speed'])
                          + field('volume', 'Volume (0.50–2.00)', defaults['volume'])
                          + '<label>Emotion<select name="emotion"><option value=""' + (' selected' if defaults['emotion'] is None else '')
                          + '>None</option><option value="calm"' + (' selected' if defaults['emotion'] == 'calm' else '') + '>Calm</option></select></label>', 'Save defaults'))
        parts.append('<p>Dictionary configured: ' + e(defaults['dictionaryConfigured']) + '</p>')
        parts.append(form(base + '/order', 'order', expected + field('orderedPassageIds', 'Passage IDs in order, one per line',
                          '\n'.join(passage['passageId'] for passage in job['passages']), textarea=True), 'Save order'))
        for passage in job['passages']:
            path = base + '/passages/' + passage['passageId']
            parts.append('<article><h3>Passage ' + e(passage['order'] + 1) + '</h3><p>' + e(passage['passageId']) + '; text revision ' + e(passage['textRevision']) + '</p>')
            parts.append(form(path + '/text', 'text', expected + field('text', 'Canonical passage text', passage['text'], textarea=True), 'Save text'))
            parts.append('<p>Recipe required: ' + e(passage['recipeRequired']) + '; dictionary required: ' + e(passage['dictionaryRequired']) + '</p>')
            parts.append(form(path + '/recipes/validate', 'recipe', expected
                + '<label>Authoring mode<select name="mode"><option value="structured">Structured controls</option><option value="advanced">Advanced markup</option></select></label>'
                + field('structuredControls', 'Structured controls (JSON array; scalar offsets)', '[]', textarea=True)
                + field('advancedSource', 'Advanced source (exact canonical text with allowed markup)', '', textarea=True), 'Validate recipe'))
            for recipe in passage['recipes']:
                parts.append('<p>Recipe ' + e(recipe['recipeId']) + '; revision ' + e(recipe['revision']) + '; text revision '
                    + e(recipe['textRevision']) + '; current: ' + e(recipe['current']) + '; required: ' + e(recipe['required'])
                    + '</p><pre>' + e(json.dumps(recipe['controls'], ensure_ascii=False)) + '</pre>')
                if recipe['current'] and not recipe['required']:
                    parts.append(form(path + '/recipes/require', 'require-recipe', expected
                        + '<input type="hidden" name="recipeId" value="' + e(recipe['recipeId']) + '">', 'Require this recipe'))
            parts.append(form(path + '/dictionary/require', 'dictionary', expected,
                              'Require configured dictionary') if defaults['dictionaryConfigured'] else '<p>Configured dictionary unavailable.</p>')
            latest = passage['latestPreview']
            if latest is not None:
                parts.append('<p>Historical preview ' + e(latest['previewId']) + '; base revision ' + e(latest['baseJobRevision'])
                    + '; billable characters ' + e(latest['billableCharacters']) + '; estimated usage ' + e(latest['estimatedUsage'])
                    + '; issued ' + e(latest['issuedAt']) + '. A fresh estimate is required before generation.</p><pre>' + e(latest['canonicalProjection']) + '</pre>')
            parts.append('</article>')
        parts.append('</section>')
    return document(csrf_token, ''.join(parts))
