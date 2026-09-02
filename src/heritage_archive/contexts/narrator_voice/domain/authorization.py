"""AuthorizationRecord aggregate: attestation, narrowing and withdrawal only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from heritage_archive.kernel import ActorId, ContentDigest, ValidationError, semantic_digest

from .errors import AuthorizationDenied, RevisionConflict
from .evidence import AuthoritySnapshot
from .ids import AuthorizationRecordId, AuthorityChangeId
from .values import AuthorityScope


def _utc(value: object, field: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValidationError(f"{field} must be an aware UTC datetime")
    return value


class AuthorizationStatus(str, Enum):
    NOT_YET_VALID = "not_yet_valid"
    ACTIVE = "active"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"


class AuthorityChangeKind(str, Enum):
    NARROWED = "narrowed"
    WITHDRAWN = "withdrawn"


@dataclass(frozen=True, slots=True)
class AuthorityChange:
    change_id: AuthorityChangeId
    kind: AuthorityChangeKind
    actor_id: ActorId
    prior_scope_digest: ContentDigest
    resulting_scope: AuthorityScope | None
    reason: str
    changed_at: datetime
    resulting_revision: int

    def __post_init__(self) -> None:
        from heritage_archive.kernel import require_canonical_text

        if type(self.change_id) is not AuthorityChangeId or type(self.kind) is not AuthorityChangeKind:
            raise ValidationError("authority change identity or kind is invalid")
        if type(self.actor_id) is not ActorId or type(self.prior_scope_digest) is not ContentDigest:
            raise ValidationError("authority change actor or prior scope digest is invalid")
        if self.kind is AuthorityChangeKind.NARROWED and type(self.resulting_scope) is not AuthorityScope:
            raise ValidationError("a narrowing requires its complete resulting scope")
        if self.kind is AuthorityChangeKind.WITHDRAWN and self.resulting_scope is not None:
            raise ValidationError("withdrawal has no resulting active scope")
        require_canonical_text(self.reason, field="authority change reason", nonempty=True)
        _utc(self.changed_at, "authority change time")
        if type(self.resulting_revision) is not int or self.resulting_revision < 2:
            raise ValidationError("authority change revision must be an integer >= 2")


@dataclass(frozen=True, slots=True)
class AuthorizationRecordSnapshot:
    record_id: AuthorizationRecordId
    revision: int
    steward_actor_id: ActorId
    initial_scope: AuthorityScope
    current_scope: AuthorityScope
    evidence_digest: ContentDigest
    attested_at: datetime
    changes: tuple[AuthorityChange, ...]
    withdrawn: bool


class AuthorizationRecord:
    """Small aggregate with a monotonic append-only authority history."""

    __slots__ = (
        "_record_id",
        "_revision",
        "_steward_actor_id",
        "_initial_scope",
        "_current_scope",
        "_evidence_digest",
        "_attested_at",
        "_changes",
        "_withdrawn",
    )

    def __init__(self, snapshot: AuthorizationRecordSnapshot) -> None:
        if type(snapshot) is not AuthorizationRecordSnapshot:
            raise ValidationError("authorization root requires an AuthorizationRecordSnapshot")
        if type(snapshot.record_id) is not AuthorizationRecordId or type(snapshot.steward_actor_id) is not ActorId:
            raise ValidationError("authorization record identity or steward is invalid")
        if type(snapshot.revision) is not int or snapshot.revision < 1:
            raise ValidationError("authorization record revision must be positive")
        if type(snapshot.initial_scope) is not AuthorityScope or type(snapshot.current_scope) is not AuthorityScope:
            raise ValidationError("authorization record scope is invalid")
        if type(snapshot.evidence_digest) is not ContentDigest:
            raise ValidationError("authorization evidence digest is invalid")
        _utc(snapshot.attested_at, "authorization attestation time")
        if type(snapshot.changes) is not tuple or any(type(change) is not AuthorityChange for change in snapshot.changes):
            raise ValidationError("authorization changes must be an immutable change tuple")
        if type(snapshot.withdrawn) is not bool:
            raise ValidationError("authorization withdrawal fact must be boolean")
        if snapshot.revision != 1 + len(snapshot.changes):
            raise ValidationError("authorization revision must match append-only history length")
        expected_revisions = tuple(range(2, snapshot.revision + 1))
        if tuple(change.resulting_revision for change in snapshot.changes) != expected_revisions:
            raise ValidationError("authority change revisions must be contiguous")
        scope = snapshot.initial_scope
        withdrawn = False
        previous_time = snapshot.attested_at
        for change in snapshot.changes:
            if change.actor_id != snapshot.steward_actor_id:
                raise ValidationError("historical authority change actor must equal bound steward")
            if change.changed_at < previous_time or change.prior_scope_digest != scope.digest:
                raise ValidationError("authority history order or prior-scope evidence is inconsistent")
            if withdrawn:
                raise ValidationError("authority history cannot continue after withdrawal")
            if change.kind is AuthorityChangeKind.NARROWED:
                assert change.resulting_scope is not None
                if not change.resulting_scope.is_narrowing_of(scope) or change.resulting_scope == scope:
                    raise ValidationError("historical scope change is not a semantic narrowing")
                scope = change.resulting_scope
            else:
                withdrawn = True
            previous_time = change.changed_at
        if scope != snapshot.current_scope or withdrawn != snapshot.withdrawn:
            raise ValidationError("authorization current state does not match append-only history")
        self._record_id = snapshot.record_id
        self._revision = snapshot.revision
        self._steward_actor_id = snapshot.steward_actor_id
        self._initial_scope = snapshot.initial_scope
        self._current_scope = snapshot.current_scope
        self._evidence_digest = snapshot.evidence_digest
        self._attested_at = snapshot.attested_at
        self._changes = snapshot.changes
        self._withdrawn = snapshot.withdrawn

    @classmethod
    def register(
        cls,
        record_id: AuthorizationRecordId,
        steward_actor_id: ActorId,
        scope: AuthorityScope,
        evidence_digest: ContentDigest,
        attested_at: datetime,
    ) -> AuthorizationRecord:
        # Initial registration is itself the active attestation; there is no draft state.
        return cls(
            AuthorizationRecordSnapshot(
                record_id,
                1,
                steward_actor_id,
                scope,
                scope,
                evidence_digest,
                attested_at,
                (),
                False,
            )
        )

    @classmethod
    def from_snapshot(cls, snapshot: AuthorizationRecordSnapshot) -> AuthorizationRecord:
        return cls(snapshot)

    @property
    def record_id(self) -> AuthorizationRecordId:
        return self._record_id

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def steward_actor_id(self) -> ActorId:
        return self._steward_actor_id

    @property
    def initial_scope(self) -> AuthorityScope:
        return self._initial_scope

    @property
    def current_scope(self) -> AuthorityScope:
        return self._current_scope

    @property
    def evidence_digest(self) -> ContentDigest:
        return self._evidence_digest

    @property
    def attested_at(self) -> datetime:
        return self._attested_at

    @property
    def changes(self) -> tuple[AuthorityChange, ...]:
        return self._changes

    @property
    def withdrawn(self) -> bool:
        return self._withdrawn

    @property
    def record_digest(self) -> ContentDigest:
        return semantic_digest(
            "narrator_voice.authorization_record.v1",
            {
                "record_id": self._record_id.value,
                "revision": self._revision,
                "steward_actor_id": self._steward_actor_id.value,
                "initial_scope_digest": self._initial_scope.digest.hex_digest,
                "current_scope_digest": self._current_scope.digest.hex_digest,
                "evidence_digest": self._evidence_digest.hex_digest,
                "attested_at": self._attested_at.isoformat(),
                "withdrawn": self._withdrawn,
                "changes": [
                    {
                        "change_id": change.change_id.value,
                        "kind": change.kind.value,
                        "actor_id": change.actor_id.value,
                        "prior_scope_digest": change.prior_scope_digest.hex_digest,
                        "resulting_scope_digest": None if change.resulting_scope is None else change.resulting_scope.digest.hex_digest,
                        "reason": change.reason,
                        "changed_at": change.changed_at.isoformat(),
                        "resulting_revision": change.resulting_revision,
                    }
                    for change in self._changes
                ],
            },
        )

    def to_snapshot(self) -> AuthorizationRecordSnapshot:
        return AuthorizationRecordSnapshot(
            self._record_id,
            self._revision,
            self._steward_actor_id,
            self._initial_scope,
            self._current_scope,
            self._evidence_digest,
            self._attested_at,
            self._changes,
            self._withdrawn,
        )

    def _check_mutation(self, actor_id: ActorId, expected_revision: int, changed_at: datetime) -> None:
        if type(expected_revision) is not int or expected_revision != self._revision:
            raise RevisionConflict(f"expected authorization revision {expected_revision!r}, current is {self._revision}")
        # INV-AR-2: only the bound server-resolved steward may append history.
        if type(actor_id) is not ActorId or actor_id != self._steward_actor_id:
            raise AuthorizationDenied("only the bound authorization steward may append a change")
        _utc(changed_at, "authority change time")
        last_time = self._changes[-1].changed_at if self._changes else self._attested_at
        if changed_at < last_time:
            raise ValidationError("authority changes must be chronological")
        if self._withdrawn:
            raise AuthorizationDenied("withdrawal is irreversible; this record cannot be reactivated")

    def narrow(
        self,
        change_id: AuthorityChangeId,
        actor_id: ActorId,
        resulting_scope: AuthorityScope,
        reason: str,
        changed_at: datetime,
        *,
        expected_revision: int,
    ) -> None:
        self._check_mutation(actor_id, expected_revision, changed_at)
        # INV-AR-3: identity is fixed; only operations/validity may become narrower.
        if type(resulting_scope) is not AuthorityScope or not resulting_scope.is_narrowing_of(self._current_scope) or resulting_scope == self._current_scope:
            raise ValidationError("authority change must semantically narrow operations and/or validity")
        change = AuthorityChange(
            change_id,
            AuthorityChangeKind.NARROWED,
            actor_id,
            self._current_scope.digest,
            resulting_scope,
            reason,
            changed_at,
            self._revision + 1,
        )
        self._changes = (*self._changes, change)
        self._current_scope = resulting_scope
        self._revision += 1

    def withdraw(
        self,
        change_id: AuthorityChangeId,
        actor_id: ActorId,
        reason: str,
        changed_at: datetime,
        *,
        expected_revision: int,
    ) -> None:
        self._check_mutation(actor_id, expected_revision, changed_at)
        change = AuthorityChange(
            change_id,
            AuthorityChangeKind.WITHDRAWN,
            actor_id,
            self._current_scope.digest,
            None,
            reason,
            changed_at,
            self._revision + 1,
        )
        self._changes = (*self._changes, change)
        self._withdrawn = True
        self._revision += 1

    def status_at(self, observed_at: datetime) -> AuthorizationStatus:
        _utc(observed_at, "authorization status observation time")
        if self._withdrawn:
            return AuthorizationStatus.WITHDRAWN
        if observed_at < self._current_scope.valid_from:
            return AuthorizationStatus.NOT_YET_VALID
        if observed_at >= self._current_scope.valid_until:
            return AuthorizationStatus.EXPIRED
        return AuthorizationStatus.ACTIVE

    def observe(self, observed_at: datetime) -> AuthoritySnapshot:
        return AuthoritySnapshot.create(
            self._record_id,
            self._revision,
            self._current_scope,
            self.record_digest,
            observed_at,
        )
