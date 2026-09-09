"""One durable, fixture-only web journey; no listener or provider transport."""

from dataclasses import replace
from hashlib import sha256
from html import escape
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from heritage_archive.contexts.narrator_voice.application import commands as c
from heritage_archive.contexts.narrator_voice.domain.evidence import ListeningOutcome, ReviewOutcome
from heritage_archive.contexts.narrator_voice.domain.ids import CommandId, DiaryEpisodeId, NarrationJobId
from heritage_archive.contexts.narrator_voice.infrastructure.local_root import LocalNarrationRoot
from heritage_archive.contexts.narrator_voice.infrastructure.operations import initialize_local_studio
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.security import ProcessSecurity
from heritage_archive.platform.web import WebRequest
from tests.heritage_archive.narrator_voice.test_cartesia_gateway import Identifiers
from tests.heritage_archive.narrator_voice.test_cartesia_generation_integration import initialization

from tests.heritage_archive.narrator_voice import workflow


class DurableWebWorkflowTests(unittest.TestCase):
    def post(self, fixture, path, body):
        response = fixture.request("POST", path, body)
        self.assertEqual(response.status, 200, (path, response.body))
        self.assertEqual(dict(response.headers)[b"cache-control"], b"no-store")
        return json.loads(response.body)["result"]

    def checked_audio(self, fixture, path, pcm):
        response = fixture.request("GET", path)
        self.assertEqual(response.status, 200, response.body)
        self.assertEqual(response.body[:4], b"RIFF")
        self.assertEqual(response.body[44:], pcm)
        headers = dict(response.headers)
        self.assertEqual(headers[b"content-type"], b"audio/wav")
        self.assertEqual(headers[b"content-length"], str(44 + len(pcm)).encode())
        self.assertEqual(headers[b"etag"], ('"' + sha256(response.body).hexdigest() + '"').encode())
        return response.body

    def test_intro_and_two_diary_passages_survive_restart(self):
        # Breaks caught: lost durable selections/listening, wrong PCM order/gaps,
        # replayed paid work, unchecked playback, or persistence bypass in routes.
        with workflow.forbid_web_external_io(), TemporaryDirectory(prefix="durable-web-fixture-") as directory:
            root = LocalNarrationRoot.open(Path(directory), (Path(__file__).resolve().parents[3],))
            config = initialization()
            config = replace(config, lane_c=replace(config.lane_c, initial_emotion="calm"))
            initialize_local_studio(root, config, Identifiers())
            first = workflow.DurableWebWorkflow(root, security=ProcessSecurity("a" * 64, "b" * 64), principal="fixture-first-process")
            audio = {}
            try:
                self.assertEqual(first.gateway.calls, [])
                self.assertTrue(first.handlers.readiness().healthy)
                fresh = first.request("GET", "/")
                self.assertEqual(fresh.status, 200)
                self.assertIn(b"backup history is not persisted", fresh.body)
                episode = self.post(first, "/api/v1/episode", {})
                episode_id, episode_revision = episode["episodeId"], episode["revision"]
                authority = {"evidenceDigest": "d" * 64, "validFrom": "2020-01-01T00:00:00Z", "validUntil": "2099-01-01T00:00:00Z"}
                for lane in ("lane_b", "lane_c"):
                    self.post(first, "/api/v1/authority/" + lane, authority)
                diary = self.post(first, "/api/v1/jobs/diary", {"passages": [{"text": "AB CD"}, {"text": "EF GH"}]})
                intro_text = '\u0b13\u0b21\u0b3c\u0b3f\u0b06 & "fixture"'
                intro = self.post(first, "/api/v1/jobs/intro", {"expectedEpisodeRevision": episode_revision, "passages": [{"text": intro_text}]})
                diary_id, intro_id = diary["jobId"], intro["jobId"]
                diary_passages = first.editor(diary_id).passages
                original_ids = [passage.passage_id.value for passage in diary_passages]
                revised = self.post(first, f"/api/v1/jobs/{diary_id}/passages/{original_ids[0]}/text",
                                    {"expectedRevision": diary["revision"], "text": "AB XY"})
                ordered = list(reversed(original_ids))
                changed = self.post(first, f"/api/v1/jobs/{diary_id}/order",
                                    {"expectedRevision": revised["revision"], "orderedPassageIds": ordered})
                self.assertEqual([p.passage_id.value for p in first.editor(diary_id).passages], ordered)
                self.assertIn(escape(intro_text).encode(), first.request("GET", "/").body)
                final_jobs, selections = {}, {}
                for job_id, revision, role, gaps in ((diary_id, changed["revision"], "diary", [3]),
                                                     (intro_id, intro["revision"], "intro", [])):
                    base = f"/api/v1/jobs/{job_id}"
                    passages = first.editor(job_id).passages
                    for index, passage in enumerate(passages):
                        passage_id = passage.passage_id.value
                        advanced = job_id == diary_id and index == 1
                        recipe = self.post(first, f"{base}/passages/{passage_id}/recipes/validate", {
                            "expectedRevision": revision, "mode": "advanced" if advanced else "structured",
                            "structuredControls": [] if advanced or role == "intro" else [{"kind": "break", "boundary": 2, "durationMs": 250}],
                            "advancedSource": '<speed ratio="0.90">AB</speed> XY' if advanced else None,
                        })
                        required = self.post(first, f"{base}/passages/{passage_id}/recipes/require",
                                             {"expectedRevision": recipe["revision"], "recipeId": recipe["recipeId"]})
                        estimate_body = {
                            "expectedRevision": required["revision"], "passageId": passage_id, "recipeId": recipe["recipeId"],
                            "speedMode": "inherit", "speed": None, "volumeMode": "inherit", "volume": None,
                            "emotionMode": "inherit", "emotion": None, "dictionaryMode": "inherit",
                        }
                        estimate = self.post(first, base + "/estimate", estimate_body)
                        preview = next(p for p in first.editor(job_id).passages if p.passage_id.value == passage_id).latest_preview
                        self.assertEqual((estimate["canonicalProjection"], estimate["billableCharacters"], estimate["estimatedUsage"]),
                                         (preview.canonical_projection, preview.billable_characters, preview.estimated_usage))
                        self.assertEqual(estimate["baseJobRevision"], required["revision"])
                        self.assertEqual(first.editor(job_id).revision, estimate["revision"])
                        token = estimate["confirmationToken"]
                        generated = self.post(first, base + "/generate", {"confirmationToken": token})
                        self.assertEqual((generated["state"], generated["budgetDisposition"]), ("completed", "settled"))
                        self.assertEqual(first.gateway.calls[-1].effective_input.canonical_projection, estimate["canonicalProjection"])
                        replay = first.request("POST", base + "/generate", {"confirmationToken": token})
                        self.assertEqual((replay.status, json.loads(replay.body)["error"]["code"]), (409, "confirmation_unavailable"))
                        take_id = generated["takeId"]
                        selections[passage_id] = take_id
                        path = f"/audio/jobs/{job_id}/takes/{take_id}.wav"
                        pcm = first.gateway.pcm_by_passage[passage_id]
                        audio[path] = (pcm, self.checked_audio(first, path, pcm))
                        review_revision = generated["revision"]
                        if role == "intro":
                            pending = self.post(first, base + "/estimate", {**estimate_body, "expectedRevision": review_revision})
                            pending_token = pending["confirmationToken"]
                            review_revision = pending["revision"]
                        reviewed = self.post(first, f"{base}/takes/{take_id}/review",
                                             {"expectedRevision": review_revision, "outcome": "accepted", "notes": "Fixture operational pass"})
                        selected = self.post(first, f"{base}/takes/{take_id}/select",
                                             {"expectedRevision": reviewed["revision"], "passageId": passage_id, "reason": "Fixture human selection"})
                        revision = selected["revision"]
                    assembled = self.post(first, base + "/narration-masters", {"expectedRevision": revision, "gapsSamples": gaps})
                    self.assertEqual(assembled["state"], "completed")
                    master_id = assembled["masterId"]
                    pcm = (b"\0\0" * 3).join(first.gateway.pcm_by_passage[p.passage_id.value] for p in passages)
                    path = f"/audio/jobs/{job_id}/masters/{master_id}.wav"
                    audio[path] = (pcm, self.checked_audio(first, path, pcm))
                    listened = self.post(first, f"{base}/narration-masters/{master_id}/listen",
                                         {"expectedRevision": assembled["revision"], "outcome": "passed", "notes": "Fixture complete master pass"})
                    attached = self.post(first, f"{base}/narration-masters/{master_id}/attach/{role}",
                                         {"sourceExpectedRevision": listened["revision"], "episodeId": episode_id, "episodeExpectedRevision": episode_revision})
                    episode_revision = attached["episodeRevision"]
                    final_jobs[job_id] = (attached["sourceRevision"], master_id, pcm)
                gap = self.post(first, f"/api/v1/episodes/{episode_id}/gap", {"expectedRevision": episode_revision, "gapSamples": 5})
                master = self.post(first, f"/api/v1/episodes/{episode_id}/speech-masters", {"expectedRevision": gap["revision"]})
                self.assertEqual(master["state"], "completed")
                episode_master_id = master["masterId"]
                episode_pcm = final_jobs[intro_id][2] + b"\0\0" * 5 + final_jobs[diary_id][2]
                episode_audio_path = f"/audio/episodes/{episode_id}/masters/{episode_master_id}.wav"
                audio[episode_audio_path] = (episode_pcm, self.checked_audio(first, episode_audio_path, episode_pcm))
                listened = self.post(first, f"/api/v1/episodes/{episode_id}/speech-masters/{episode_master_id}/listen",
                                     {"expectedRevision": master["revision"], "outcome": "passed", "notes": "Fixture episode pass"})
                episode_revision = listened["revision"]
                self.assertEqual(len(first.gateway.calls), 3)
                self.assertEqual(len({call.effective_input.passage_id for call in first.gateway.calls}), 3)
                self.assertEqual((final_jobs[diary_id][0], final_jobs[intro_id][0], episode_revision), (33, 21, 11))
            finally:
                first.close()

            second = workflow.DurableWebWorkflow(root, security=ProcessSecurity("c" * 64, "e" * 64), principal="fixture-restarted-process")
            try:
                self.assertEqual(second.gateway.calls, [])
                discovery = second.handlers.discover(c.DiscoverStudioCommand(second.ids.new_id(CommandId)))
                self.assertEqual(discovery.job_ids, tuple(sorted((NarrationJobId(diary_id), NarrationJobId(intro_id)), key=lambda value: value.value)))
                self.assertEqual(discovery.episode_ids, (DiaryEpisodeId(episode_id),))
                old_request = WebRequest("POST", f"/api/v1/jobs/{intro_id}/generate", first.headers(True), json.dumps({"confirmationToken": pending_token}).encode())
                self.assertEqual(second.app(old_request).status, 401)
                old_csrf_headers = tuple((key, first.security.csrf_token.encode() if key == b"x-narrator-csrf" else value)
                                         for key, value in second.headers(True))
                old_csrf = second.app(replace(old_request, headers=old_csrf_headers))
                self.assertEqual((old_csrf.status, json.loads(old_csrf.body)["error"]["code"]), (403, "invalid_csrf"))
                old_token = second.request("POST", f"/api/v1/jobs/{intro_id}/generate", {"confirmationToken": pending_token})
                self.assertEqual((old_token.status, json.loads(old_token.body)["error"]["code"]), (409, "confirmation_unavailable"))
                for job_id, (revision, master_id, _) in final_jobs.items():
                    editor = second.editor(job_id)
                    self.assertEqual(editor.revision, revision)
                    status = second.handlers.show_narration_status(c.ShowNarrationStatusCommand(second.ids.new_id(CommandId), NarrationJobId(job_id)))
                    self.assertEqual(status.revision, revision)
                    for passage in status.passages:
                        self.assertEqual(passage.selected_take_id.value, selections[passage.passage_id.value])
                        self.assertEqual(passage.takes[0].latest_operational_review, ReviewOutcome.ACCEPTED)
                    self.assertEqual(status.masters[0].master_id.value, master_id)
                    self.assertEqual(status.masters[0].latest_listening, ListeningOutcome.PASSED)
                    self.assertEqual(status.masters[0].issued_snapshot_count, 1)
                    self.assertTrue(status.masters[0].current)
                status = second.handlers.show_episode_status(c.ShowEpisodeStatusCommand(second.ids.new_id(CommandId), DiaryEpisodeId(episode_id)))
                self.assertEqual(status.revision, episode_revision)
                self.assertEqual(status.gap_samples, 5)
                self.assertEqual({component.source_job_id.value for component in status.components}, {intro_id, diary_id})
                self.assertTrue(all(component.attached and component.source_current for component in status.components))
                self.assertEqual(status.masters[0].master_id.value, episode_master_id)
                self.assertEqual(status.masters[0].latest_listening, ListeningOutcome.PASSED)
                self.assertEqual(status.listening[0].outcome, ListeningOutcome.PASSED)
                self.assertEqual([p.passage_id.value for p in second.editor(diary_id).passages], ordered)
                self.assertEqual([p.text for p in second.editor(diary_id).passages], ["EF GH", "AB XY"])
                page = second.request("GET", "/")
                self.assertEqual(page.status, 200)
                self.assertIn(escape(intro_text).encode(), page.body)
                for path, (pcm, original_bytes) in audio.items():
                    self.assertEqual(self.checked_audio(second, path, pcm), original_bytes)
                for path in (
                    f"/audio/jobs/{intro_id}/takes/{selections[ordered[0]]}.wav",
                    f"/audio/jobs/{intro_id}/masters/{final_jobs[diary_id][1]}.wav",
                ):
                    wrong_parent = second.request("GET", path)
                    self.assertEqual((wrong_parent.status, json.loads(wrong_parent.body)["error"]["code"]),
                                     (404, "not_found"))
                for path, expected in (*second.assets.items(), (episode_audio_path, audio[episode_audio_path][1])):
                    start, payload = second.raw_asgi_get(path)
                    self.assertEqual(start["status"], 200)
                    self.assertEqual(payload, expected)
                    self.assertEqual(dict(start["headers"])[b"etag"], ('"' + sha256(expected).hexdigest() + '"').encode())
                self.assertTrue(second.handlers.readiness().healthy)
                self.assertEqual(second.gateway.calls, [])
            finally:
                second.close()


if __name__ == "__main__":
    unittest.main()
