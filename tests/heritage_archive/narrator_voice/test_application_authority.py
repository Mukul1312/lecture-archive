"""Application authority ports, actor resolution and CAS tests."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import sys
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ActorId
from heritage_archive.contexts.narrator_voice.application.commands import (
    RecordAuthorizationChangeCommand,
    RegisterAuthorizationCommand,
    ShowAuthorizationStatusCommand,
)
from heritage_archive.contexts.narrator_voice.application.handlers import (
    RecordAuthorizationChangeHandler,
    RegisterAuthorizationHandler,
    ShowAuthorizationStatusHandler,
)
from heritage_archive.contexts.narrator_voice.application.ports import PrincipalAuthority
from heritage_archive.contexts.narrator_voice.domain.authorization import AuthorizationStatus
from heritage_archive.contexts.narrator_voice.domain.errors import AuthorizationDenied, RevisionConflict
from heritage_archive.contexts.narrator_voice.domain.evidence import ReviewAuthority, TimingReviewStatus
from heritage_archive.contexts.narrator_voice.domain.ids import AuthorizationRecordId, AuthorityChangeId, CommandId
from heritage_archive.contexts.narrator_voice.domain.values import AuthorityOperation, AuthorityScope
from tests.heritage_archive.narrator_voice.fakes import (
    FakeActorResolver,
    FakeAuthorizationRepository,
    FakeAuthorizationStatusReader,
    FakeClock,
    FakeIdentifierSource,
)
from tests.heritage_archive.narrator_voice.fixtures import NOW, digest, uuid


class AuthorityApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.actor = ActorId(uuid(700))
        self.record_id = AuthorizationRecordId(uuid(701))
        self.change_id = AuthorityChangeId(uuid(702))
        self.repository = FakeAuthorizationRepository()
        self.clock = FakeClock(NOW)
        self.actor_resolver = FakeActorResolver({"fake-session": self.actor, "fake-other": ActorId(uuid(703))})
        self.ids = FakeIdentifierSource({AuthorityChangeId: [self.change_id]})
        self.reader = FakeAuthorizationStatusReader(self.repository)
        self.scope = AuthorityScope(
            "fake-speaker", "fake-voice", "or", "fake narration", None,
            frozenset(AuthorityOperation), NOW - timedelta(days=1), NOW + timedelta(days=2),
        )

    def register(self):
        return RegisterAuthorizationHandler(self.repository, self.actor_resolver, self.clock)(
            RegisterAuthorizationCommand(
                CommandId(uuid(704)), "fake-session", self.record_id, self.scope, digest("fake evidence")
            )
        )

    def test_register_persists_the_configured_record_id_without_requesting_an_authorization_id(self) -> None:
        result = self.register()
        stored = self.repository.load(self.record_id)
        self.assertEqual((result.record_id, result.revision, result.status), (self.record_id, 1, AuthorizationStatus.ACTIVE))
        self.assertEqual((stored.steward_actor_id, self.actor_resolver.calls), (self.actor, ["fake-session"]))
        self.assertEqual(self.ids.calls, [])
        self.assertFalse(hasattr(result, "evidence_digest"))

    def test_register_CAS_refusal_has_no_persisted_mutation(self) -> None:
        self.repository.reject_next_save = True
        with self.assertRaises(RevisionConflict):
            self.register()
        self.assertIsNone(self.repository.load(self.record_id))

    def test_authority_administration_requires_server_derived_steward_capability(self) -> None:
        resolver = FakeActorResolver(
            {"fake-review-only": ActorId(uuid(708))},
            profiles={
                "fake-review-only": PrincipalAuthority(
                    ActorId(uuid(708)),
                    False,
                    ReviewAuthority.QUALIFIED_ODIA,
                    TimingReviewStatus.HUMAN_REVIEWED,
                )
            },
        )
        with self.assertRaises(AuthorizationDenied):
            RegisterAuthorizationHandler(self.repository, resolver, self.clock)(
                RegisterAuthorizationCommand(
                    CommandId(uuid(709)), "fake-review-only", self.record_id, self.scope, digest("fake denied evidence"),
                )
            )
        self.assertIsNone(self.repository.load(self.record_id))

    def test_duplicate_registration_refuses_to_clobber_the_configured_record(self) -> None:
        self.register()
        with self.assertRaises(RevisionConflict):
            self.register()
        stored = self.repository.load(self.record_id)
        self.assertEqual((stored.record_id, stored.revision, stored.current_scope), (self.record_id, 1, self.scope))

    def test_change_uses_server_resolved_steward_expected_revision_and_status_history(self) -> None:
        self.register()
        narrower = AuthorityScope(
            self.scope.speaker_binding, self.scope.voice_binding, self.scope.language, self.scope.purpose, None,
            frozenset({AuthorityOperation.PREFLIGHT, AuthorityOperation.GENERATE}), NOW, NOW + timedelta(days=1),
        )
        result = RecordAuthorizationChangeHandler(self.repository, self.actor_resolver, self.clock, self.ids)(
            RecordAuthorizationChangeCommand(
                CommandId(uuid(705)), "fake-session", self.record_id, 1,
                narrower, False, "fake narrowed purpose",
            )
        )
        status = ShowAuthorizationStatusHandler(self.repository, self.clock)(
            ShowAuthorizationStatusCommand(CommandId(uuid(706)), self.record_id)
        )
        self.assertEqual((result.revision, status.status, status.revision), (2, AuthorizationStatus.ACTIVE, 2))
        self.assertEqual(tuple(change.resulting_revision for change in status.history), (1, 2))

    def test_stale_change_CAS_or_revision_conflict_preserves_history(self) -> None:
        self.register()
        with self.assertRaises(RevisionConflict):
            RecordAuthorizationChangeHandler(self.repository, self.actor_resolver, self.clock, self.ids)(
                RecordAuthorizationChangeCommand(
                    CommandId(uuid(707)), "fake-session", self.record_id, 99,
                    None, True, "fake stale withdrawal",
                )
            )
        self.assertEqual((self.repository.load(self.record_id).revision, self.repository.load(self.record_id).withdrawn), (1, False))


if __name__ == "__main__":
    unittest.main()
