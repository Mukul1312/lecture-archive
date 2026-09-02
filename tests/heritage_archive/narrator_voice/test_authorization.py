"""AuthorizationRecord invariant catalogue tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ActorId, ContentDigest, ValidationError
from heritage_archive.contexts.narrator_voice.application.schema_v1 import decode_schema_v1, encode_schema_v1
from heritage_archive.contexts.narrator_voice.domain.authorization import (
    AuthorizationRecord,
    AuthorizationRecordSnapshot,
    AuthorizationStatus,
)
from heritage_archive.contexts.narrator_voice.domain.errors import AuthorizationDenied, RevisionConflict
from heritage_archive.contexts.narrator_voice.domain.ids import AuthorizationRecordId, AuthorityChangeId, DiaryEpisodeId
from heritage_archive.contexts.narrator_voice.domain.values import AuthorityOperation, AuthorityScope


UUIDS = [f"123e4567-e89b-42d3-a456-42661418{n:04d}" for n in range(30)]
NOW = datetime(2026, 9, 2, 12, tzinfo=timezone.utc)


def scope(*, operations: frozenset[AuthorityOperation] | None = None, start: datetime = NOW, end: datetime | None = None, voice: str = "fake-voice") -> AuthorityScope:
    return AuthorityScope(
        "fake-speaker",
        voice,
        "or",
        "reviewed-odia-diary-intro",
        DiaryEpisodeId(UUIDS[3]),
        operations or frozenset({AuthorityOperation.PREFLIGHT, AuthorityOperation.GENERATE, AuthorityOperation.ASSEMBLE, AuthorityOperation.ATTACH, AuthorityOperation.DELIVER}),
        start,
        end or NOW + timedelta(days=365),
    )


class AuthorizationRecordInvariantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.steward = ActorId(UUIDS[1])
        self.record = AuthorizationRecord.register(
            AuthorizationRecordId(UUIDS[0]),
            self.steward,
            scope(),
            ContentDigest.from_bytes(b"obviously-fake-attestation"),
            NOW,
        )

    def test_INV_AR_1_grant_identity_evidence_and_history_are_immutable(self) -> None:
        original = self.record.to_snapshot()
        self.record.narrow(
            AuthorityChangeId(UUIDS[4]),
            self.steward,
            scope(operations=frozenset({AuthorityOperation.GENERATE, AuthorityOperation.ASSEMBLE})),
            "fake narrowing",
            NOW + timedelta(hours=1),
            expected_revision=1,
        )
        self.assertEqual((self.record.record_id, self.record.evidence_digest, self.record.steward_actor_id), (original.record_id, original.evidence_digest, original.steward_actor_id))
        self.assertEqual(self.record.changes[0].prior_scope_digest, original.current_scope.digest)
        with self.assertRaises(FrozenInstanceError):
            self.record.changes[0].reason = "rewrite"  # type: ignore[misc]

    def test_INV_AR_2_only_bound_server_resolved_steward_can_append_change(self) -> None:
        with self.assertRaises(AuthorizationDenied):
            self.record.narrow(
                AuthorityChangeId(UUIDS[4]),
                ActorId(UUIDS[2]),
                scope(operations=frozenset({AuthorityOperation.GENERATE})),
                "fake narrowing",
                NOW + timedelta(hours=1),
                expected_revision=1,
            )
        self.assertEqual((self.record.revision, self.record.changes), (1, ()))
        with self.assertRaises(RevisionConflict):
            self.record.withdraw(
                AuthorityChangeId(UUIDS[5]), self.steward, "fake withdrawal",
                NOW + timedelta(hours=2), expected_revision=0,
            )

    def test_INV_AR_3_narrowing_cannot_widen_rebind_or_remove_lane_c_episode_binding(self) -> None:
        invalid = (
            scope(operations=frozenset(set(scope().operations) | {AuthorityOperation.PREFLIGHT}), start=NOW - timedelta(seconds=1)),
            scope(voice="another-fake-voice"),
            replace(scope(), intended_episode_id=DiaryEpisodeId(UUIDS[6])),
            scope(end=NOW + timedelta(days=366)),
        )
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValidationError):
                    self.record.narrow(
                        AuthorityChangeId(UUIDS[4]), self.steward, candidate,
                        "invalid widening", NOW + timedelta(hours=1), expected_revision=1,
                    )
        narrowed = scope(operations=frozenset({AuthorityOperation.GENERATE}), start=NOW + timedelta(minutes=1), end=NOW + timedelta(days=30))
        self.record.narrow(AuthorityChangeId(UUIDS[4]), self.steward, narrowed, "valid narrowing", NOW + timedelta(hours=1), expected_revision=1)
        self.record.withdraw(AuthorityChangeId(UUIDS[5]), self.steward, "irreversible withdrawal", NOW + timedelta(hours=2), expected_revision=2)
        self.assertEqual(self.record.status_at(NOW + timedelta(hours=3)), AuthorizationStatus.WITHDRAWN)
        with self.assertRaises(AuthorizationDenied):
            self.record.narrow(AuthorityChangeId(UUIDS[6]), self.steward, narrowed, "cannot reactivate", NOW + timedelta(hours=3), expected_revision=3)

    def test_expiry_is_derived_and_historical_snapshots_never_become_current_truth(self) -> None:
        active = self.record.observe(NOW + timedelta(hours=1))
        self.assertEqual(self.record.status_at(NOW + timedelta(hours=1)), AuthorizationStatus.ACTIVE)
        self.assertEqual(self.record.status_at(NOW + timedelta(days=366)), AuthorizationStatus.EXPIRED)
        self.record.withdraw(AuthorityChangeId(UUIDS[5]), self.steward, "withdrawn after observation", NOW + timedelta(hours=2), expected_revision=1)
        self.assertNotEqual(active.record_revision, self.record.revision)
        self.assertEqual(active.scope, scope())
        self.assertEqual(self.record.status_at(NOW + timedelta(hours=3)), AuthorizationStatus.WITHDRAWN)

    def test_schema_v1_round_trip_preserves_aggregate_snapshot_and_append_only_history(self) -> None:
        self.record.narrow(
            AuthorityChangeId(UUIDS[4]), self.steward,
            scope(operations=frozenset({AuthorityOperation.GENERATE, AuthorityOperation.ASSEMBLE})),
            "fake narrowing", NOW + timedelta(hours=1), expected_revision=1,
        )
        snapshot = self.record.to_snapshot()
        raw = encode_schema_v1(snapshot)
        restored_snapshot = decode_schema_v1(raw, AuthorizationRecordSnapshot)
        restored = AuthorizationRecord.from_snapshot(restored_snapshot)
        self.assertEqual(restored.to_snapshot(), snapshot)
        self.assertEqual(encode_schema_v1(restored.to_snapshot()), raw)


if __name__ == "__main__":
    unittest.main()
