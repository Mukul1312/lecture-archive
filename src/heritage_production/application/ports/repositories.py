"""One repository port per approved aggregate root, and nothing else.

There are exactly six aggregate roots, so there are exactly six repository
ports (design section 8.3). A segment, revision, proposal row, sign-off,
eligibility result, release approval, and gate result are all reached through
their owning root.

Mutable and sealed roots get deliberately different shapes:

* A mutable root is loaded with its optimistic version and saved against an
  expected one. Design 11.3 puts the version on the aggregate *row*, so the
  aggregate itself never carries it and the port owns the concurrency contract.
* A sealed root has `add` and `get` only. Design 11.6 gives sealed records no
  update or delete API at all, so offering one here would be the first step
  toward violating it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar, runtime_checkable

from heritage_production.domain.production import Production
from heritage_production.domain.release import ReleasePolicyVersion
from heritage_production.domain.review import ReviewFinding, ReviewRound
from heritage_production.domain.shared import (
    ProductionId,
    ProposalSetId,
    ReleasePolicyVersionId,
    ReviewFindingId,
    ReviewRoundId,
    TranscriptEditionId,
)
from heritage_production.domain.transcription import ASRProposalSet, TranscriptEdition


RootT = TypeVar("RootT")


@dataclass(frozen=True, slots=True)
class Versioned(Generic[RootT]):
    """A mutable aggregate root together with the row version it was read at."""

    root: RootT
    version: int


@runtime_checkable
class ProductionRepository(Protocol):
    def load(self, production_id: ProductionId) -> Versioned[Production]: ...

    def save(self, production: Production, *, expected_version: int) -> int: ...


@runtime_checkable
class ReviewRoundRepository(Protocol):
    def load(self, review_round_id: ReviewRoundId) -> Versioned[ReviewRound]: ...

    def save(self, review_round: ReviewRound, *, expected_version: int) -> int: ...


@runtime_checkable
class ReviewFindingRepository(Protocol):
    """A finding body is immutable but takes one appended disposition."""

    def load(self, review_finding_id: ReviewFindingId) -> Versioned[ReviewFinding]: ...

    def save(self, review_finding: ReviewFinding, *, expected_version: int) -> int: ...

    def list_for_round(self, review_round_id: ReviewRoundId) -> tuple[ReviewFinding, ...]: ...


@runtime_checkable
class ASRProposalSetRepository(Protocol):
    def add(self, proposal_set: ASRProposalSet) -> None: ...

    def get(self, proposal_set_id: ProposalSetId) -> ASRProposalSet: ...


@runtime_checkable
class TranscriptEditionRepository(Protocol):
    def add(self, edition: TranscriptEdition) -> None: ...

    def get(self, transcript_edition_id: TranscriptEditionId) -> TranscriptEdition: ...


@runtime_checkable
class ReleasePolicyVersionRepository(Protocol):
    def add(self, policy: ReleasePolicyVersion) -> None: ...

    def get(self, release_policy_version_id: ReleasePolicyVersionId) -> ReleasePolicyVersion: ...
