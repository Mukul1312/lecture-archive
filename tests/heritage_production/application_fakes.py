"""Transactional fakes with teeth for the application layer.

These are contract instruments, not conveniences: they enforce the design
rules the real SQLite adapters must satisfy in Task 7 — one domain transaction
changes one aggregate root (design 9.3), optimistic versions live on the
mutable row (design 11.3), sealed roots take no update or delete (design
11.6), and an operation record becomes durable together with the state it
describes or not at all (design 9.4). A handler that violates a rule fails
here, before any real adapter exists.

`FakeDatabase` serializes writers the way SQLite `BEGIN IMMEDIATE` does: one
active transaction at a time. Commit runs in two phases — every staged entry
re-validates against durable state first, then every entry applies — so a
conflict discovered at commit time leaves nothing behind, exactly like a
rolled-back SQLite transaction.
"""

from __future__ import annotations

from heritage_production.application.errors import (
    OperationConflictError,
    TransactionRuleError,
)
from heritage_production.application.ports.infrastructure import OperationRecord
from heritage_production.application.ports.repositories import Versioned
from heritage_production.domain.production import Production
from heritage_production.domain.release import (
    SUPPORTED_EVALUATOR_REF,
    ReleasePolicyRules,
    ReleasePolicyVersion,
)
from heritage_production.domain.review import ReviewFinding, ReviewRound
from heritage_production.domain.shared import (
    DomainEventId,
    InvariantError,
    ProductionId,
    ReleasePolicyVersionId,
    StaleReferenceError,
    ValidationError,
)
from heritage_production.domain.transcription import ASRProposalSet, TranscriptEdition

from tests.heritage_production.heritage_release_fixtures import actor, uid


class FakeDatabase:
    """The writer gate: at most one transaction is active at a time."""

    def __init__(self) -> None:
        self.active: FakeUnitOfWork | None = None

    def begin(self, unit_of_work: FakeUnitOfWork) -> None:
        if self.active is not None:
            raise TransactionRuleError("another transaction is already active")
        self.active = unit_of_work

    def end(self, unit_of_work: FakeUnitOfWork) -> None:
        if self.active is unit_of_work:
            self.active = None

    def stage(self, *, root: tuple[str, object] | None, validate, apply) -> None:
        if self.active is None:
            raise TransactionRuleError("a write requires an active transaction")
        self.active.stage(root=root, validate=validate, apply=apply)


class FakeUnitOfWork:
    """Single-use transaction; explicit commit or nothing becomes durable."""

    def __init__(self, database: FakeDatabase) -> None:
        self._database = database
        self._staged: list[tuple[object, object]] = []
        self._root_writes: set[tuple[str, object]] = set()
        self._state = "new"
        self.commits = 0
        self.rollbacks = 0
        # Test hook: raise this instead of committing, modeling an I/O failure.
        self.commit_failure: Exception | None = None

    @property
    def entered(self) -> bool:
        return self._state != "new"

    def __enter__(self) -> FakeUnitOfWork:
        if self._state != "new":
            raise TransactionRuleError("a unit of work is single-use")
        self._database.begin(self)
        self._state = "active"
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if self._state == "active":
            self.rollback()
        return False

    def stage(self, *, root: tuple[str, object] | None, validate, apply) -> None:
        if self._state != "active":
            raise TransactionRuleError("no active transaction to write in")
        if root is not None:
            if any(existing != root for existing in self._root_writes):
                raise TransactionRuleError(
                    "one domain transaction changes one aggregate root"
                )
            self._root_writes.add(root)
        self._staged.append((validate, apply))

    def commit(self) -> None:
        if self._state != "active":
            raise TransactionRuleError("no active transaction to commit")
        if self.commit_failure is not None:
            failure = self.commit_failure
            self.rollback()
            raise failure
        try:
            for validate, _ in self._staged:
                validate()
        except BaseException:
            self.rollback()
            raise
        for _, apply in self._staged:
            apply()
        self._staged.clear()
        self._root_writes.clear()
        self._state = "committed"
        self.commits += 1
        self._database.end(self)

    def rollback(self) -> None:
        if self._state != "active":
            raise TransactionRuleError("no active transaction to roll back")
        self._staged.clear()
        self._root_writes.clear()
        self._state = "rolled-back"
        self.rollbacks += 1
        self._database.end(self)


class _MutableRootRepository:
    """Load with the row version; save against the version you expect."""

    root_type: type
    id_field: str

    def __init__(self, database: FakeDatabase) -> None:
        self._database = database
        self.rows: dict = {}

    def load(self, root_id):
        try:
            root, version = self.rows[root_id]
        except KeyError:
            raise StaleReferenceError(
                f"no stored {self.root_type.__name__} for {root_id!r}"
            ) from None
        return Versioned(root=root, version=version)

    def save(self, root, *, expected_version: int) -> int:
        if type(root) is not self.root_type:
            raise ValidationError(f"save takes exactly one {self.root_type.__name__}")
        if type(expected_version) is not int or expected_version < 0:
            raise ValidationError("expected_version must be a nonnegative integer")
        root_id = getattr(root, self.id_field)
        if self._current_version(root_id) != expected_version:
            raise StaleReferenceError("optimistic version conflict")
        new_version = expected_version + 1

        def validate() -> None:
            if self._current_version(root_id) != expected_version:
                raise StaleReferenceError("optimistic version conflict at commit")

        def apply() -> None:
            self.rows[root_id] = (root, new_version)

        self._database.stage(
            root=(self.root_type.__name__, root_id), validate=validate, apply=apply
        )
        return new_version

    def _current_version(self, root_id) -> int:
        row = self.rows.get(root_id)
        return 0 if row is None else row[1]


class _SealedRootRepository:
    """Sealed roots are added once and only ever read back (design 11.6)."""

    root_type: type
    id_field: str

    def __init__(self, database: FakeDatabase) -> None:
        self._database = database
        self.rows: dict = {}

    def add(self, root) -> None:
        if type(root) is not self.root_type:
            raise ValidationError(f"add takes exactly one {self.root_type.__name__}")
        root_id = getattr(root, self.id_field)
        if root_id in self.rows:
            raise InvariantError(f"{self.root_type.__name__} {root_id!r} already exists")

        def validate() -> None:
            if root_id in self.rows:
                raise InvariantError(
                    f"{self.root_type.__name__} {root_id!r} was added concurrently"
                )

        def apply() -> None:
            self.rows[root_id] = root

        self._database.stage(
            root=(self.root_type.__name__, root_id), validate=validate, apply=apply
        )

    def get(self, root_id):
        try:
            return self.rows[root_id]
        except KeyError:
            raise StaleReferenceError(
                f"no stored {self.root_type.__name__} for {root_id!r}"
            ) from None


class FakeProductionRepository(_MutableRootRepository):
    root_type = Production
    id_field = "production_id"


class FakeReviewRoundRepository(_MutableRootRepository):
    root_type = ReviewRound
    id_field = "review_round_id"


class FakeReviewFindingRepository(_MutableRootRepository):
    root_type = ReviewFinding
    id_field = "review_finding_id"

    def list_for_round(self, review_round_id) -> tuple:
        return tuple(
            root
            for root, _ in self.rows.values()
            if root.review_round_id == review_round_id
        )


class FakeASRProposalSetRepository(_SealedRootRepository):
    root_type = ASRProposalSet
    id_field = "proposal_set_id"


class FakeTranscriptEditionRepository(_SealedRootRepository):
    root_type = TranscriptEdition
    id_field = "transcript_edition_id"


class FakeReleasePolicyVersionRepository(_SealedRootRepository):
    root_type = ReleasePolicyVersion
    id_field = "release_policy_version_id"


class FakeOperationRecorder:
    """Duplicate operation IDs are refused when staged and again at commit."""

    def __init__(self, database: FakeDatabase) -> None:
        self._database = database
        self.records: dict = {}

    def find(self, operation_id):
        return self.records.get(operation_id)

    def record(self, record) -> None:
        if type(record) is not OperationRecord:
            raise ValidationError("record takes exactly one OperationRecord")
        if record.operation_id in self.records:
            raise OperationConflictError(
                "an operation record already exists for this operation id"
            )

        def validate() -> None:
            if record.operation_id in self.records:
                raise OperationConflictError(
                    "an operation record was written concurrently for this operation id"
                )

        def apply() -> None:
            self.records[record.operation_id] = record

        self._database.stage(root=None, validate=validate, apply=apply)


class FakeClock:
    """Deterministic microsecond clock; counts how often it is consulted."""

    def __init__(self, start_us: int = 1_700_000_000_500_000) -> None:
        self._next = start_us
        self.calls = 0

    def now_us(self) -> int:
        self.calls += 1
        value = self._next
        self._next += 1
        return value


def sample_production(suffix: int = 0) -> Production:
    production = Production.create(
        production_id=ProductionId(uid(700 + suffix)),
        intended_deliverable="August 21 listening transcript",
        steward_actor_id=actor(20),
        created_at_us=1_700_000_000_000_000,
        event_id=DomainEventId(uid(760 + suffix)),
        event_occurred_at_us=1_700_000_000_000_001,
    )
    production.pull_events()
    return production


def sample_policy(suffix: int = 0) -> ReleasePolicyVersion:
    return ReleasePolicyVersion.seal(
        release_policy_version_id=ReleasePolicyVersionId(uid(720 + suffix)),
        semantic_label="pilot-transcript-policy",
        policy_schema_version=1,
        policy_schema_code="heritage-transcript-policy-v1",
        evaluator_ref=SUPPORTED_EVALUATOR_REF,
        rules=ReleasePolicyRules(
            required_integrity_checks=(),
            uncertainty_allowances=(),
            blocking_finding_rules=(),
            review_coverage_requirements=(),
            review_signoff_requirements=(),
            external_signoff_requirements=(),
            required_release_members=(),
            maximum_unresolved_findings=0,
        ),
        author_actor_id=actor(21),
        created_at_us=1_700_000_000_000_000,
    )
