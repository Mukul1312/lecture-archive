"""The mutable `Production` aggregate root and its terminal approval invariant.

Production owns deliverable intent, exact source and selection references,
append-only gate sets, external sign-offs, candidate snapshots, and at most one
release approval. It never holds transcript text, proposal rows, review
findings, or policy rules.
"""

from __future__ import annotations

from heritage_production.domain.release.content import (
    ReleaseCandidateSnapshot,
    ReleaseContentBinding,
)
from heritage_production.domain.release.gates import ExternalGateSet
from heritage_production.domain.release.policy import ReleasePolicyVersion
from heritage_production.domain.release.signoffs import ExternalSignOff
from heritage_production.domain.shared import (
    ActorId,
    AggregateEventRecorder,
    DomainEvent,
    DomainEventId,
    EditionRef,
    ExternalGateSetRef,
    InvariantError,
    OperationId,
    PolicyRef,
    ProductionId,
    ReleaseCandidateRef,
    SignOffDecision,
    StaleReferenceError,
    ValidationError,
    assurance_satisfies,
)
from heritage_production.domain.shared.text import require_canonical_text

from .approval import ApprovalEvidence, ReleaseApproval
from .sources import AttachedSource, EditionSelection


def _require_exact(value: object, expected: type[object], field: str) -> None:
    if type(value) is not expected:
        raise ValidationError(f"{field} must be an exact {expected.__name__}")


def _sign_off_gate_key(sign_off: ExternalSignOff) -> tuple[str, ...]:
    """One actor's decision on one gate for one exact typed target."""
    return (
        sign_off.gate_code.value,
        sign_off.role.value,
        sign_off.credential.actor_id.value,
        sign_off.target.target_identity,
        sign_off.target.target_digest.hex_digest,
    )


def _gate_authorizes(requirement: object, sign_off: ExternalSignOff) -> bool:
    """Whether one gate requirement declares this sign-off's exact identity.

    This is the storable half of the check `record_external_sign_off` performs:
    gate code, role, pinned credential, typed target kind and member role, plus
    the assurance minimum for an approving decision. The manifest-member digest
    is deliberately excluded because it needs the release content, which the
    aggregate does not store.
    """
    if requirement.gate_code != sign_off.gate_code:
        return False
    if requirement.role != sign_off.role:
        return False
    if requirement.credential != sign_off.credential:
        return False
    rule = requirement.target_rule
    if rule.target_kind is not sign_off.target.target_kind:
        return False
    if (
        rule.required_member_role is not None
        and sign_off.target.member_role != rule.required_member_role
    ):
        return False
    if sign_off.decision is SignOffDecision.APPROVED and not assurance_satisfies(
        sign_off.assurance.assurance, requirement.minimum_assurance
    ):
        return False
    return True


def _require_event_inputs(event_id: object, event_occurred_at_us: object) -> None:
    _require_exact(event_id, DomainEventId, "event_id")
    if type(event_occurred_at_us) is not int or event_occurred_at_us <= 0:
        raise ValidationError("event_occurred_at_us must be a positive integer")


class Production(AggregateEventRecorder):
    """One intended deliverable with at most one terminal release approval."""

    __slots__ = (
        "production_id",
        "intended_deliverable",
        "steward_actor_id",
        "created_at_us",
        "sources",
        "edition_selection",
        "selected_policy_ref",
        "gate_sets",
        "active_gate_set_ref",
        "external_sign_offs",
        "candidates",
        "active_candidate_ref",
        "approval",
        "_sealed",
    )

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("Production state is behavior-only")
        object.__setattr__(self, name, value)

    def _write(self, name: str, value: object) -> None:
        object.__setattr__(self, name, value)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def _build(cls, **values: object) -> Production:
        production = object.__new__(cls)
        AggregateEventRecorder.__init__(production)
        for name, value in values.items():
            object.__setattr__(production, name, value)
        object.__setattr__(production, "_sealed", True)
        return production

    @classmethod
    def create(
        cls,
        *,
        production_id: ProductionId,
        intended_deliverable: str,
        steward_actor_id: ActorId,
        created_at_us: int,
        event_id: DomainEventId,
        event_occurred_at_us: int,
    ) -> Production:
        _require_exact(production_id, ProductionId, "production_id")
        _require_exact(steward_actor_id, ActorId, "steward_actor_id")
        require_canonical_text(
            intended_deliverable, field="intended_deliverable", nonempty=True
        )
        if type(created_at_us) is not int or created_at_us <= 0:
            raise ValidationError("created_at_us must be a positive integer")
        _require_event_inputs(event_id, event_occurred_at_us)

        production = cls._build(
            production_id=production_id,
            intended_deliverable=intended_deliverable,
            steward_actor_id=steward_actor_id,
            created_at_us=created_at_us,
            sources=(),
            edition_selection=None,
            selected_policy_ref=None,
            gate_sets=(),
            active_gate_set_ref=None,
            external_sign_offs=(),
            candidates=(),
            active_candidate_ref=None,
            approval=None,
        )
        production._record_event(
            DomainEvent(
                event_id,
                event_occurred_at_us,
                "ProductionCreated",
                {
                    "production_id": production_id.value,
                    "steward_actor_id": steward_actor_id.value,
                },
            )
        )
        return production

    @classmethod
    def reconstitute(
        cls,
        *,
        production_id: ProductionId,
        intended_deliverable: str,
        steward_actor_id: ActorId,
        created_at_us: int,
        sources: tuple[AttachedSource, ...],
        edition_selection: EditionSelection | None,
        selected_policy_ref: PolicyRef | None,
        gate_sets: tuple[ExternalGateSet, ...],
        active_gate_set_ref: ExternalGateSetRef | None,
        external_sign_offs: tuple[ExternalSignOff, ...],
        candidates: tuple[ReleaseCandidateSnapshot, ...],
        active_candidate_ref: ReleaseCandidateRef | None,
        approval: ReleaseApproval | None,
    ) -> Production:
        _require_exact(production_id, ProductionId, "production_id")
        _require_exact(steward_actor_id, ActorId, "steward_actor_id")
        require_canonical_text(
            intended_deliverable, field="intended_deliverable", nonempty=True
        )
        if type(created_at_us) is not int or created_at_us <= 0:
            raise ValidationError("created_at_us must be a positive integer")

        for field_name, values, expected in (
            ("sources", sources, AttachedSource),
            ("gate_sets", gate_sets, ExternalGateSet),
            ("external_sign_offs", external_sign_offs, ExternalSignOff),
            ("candidates", candidates, ReleaseCandidateSnapshot),
        ):
            if type(values) is not tuple or not all(
                type(value) is expected for value in values
            ):
                raise ValidationError(
                    f"{field_name} must be an immutable tuple of {expected.__name__}"
                )
        for field_name, value, expected in (
            ("edition_selection", edition_selection, EditionSelection),
            ("selected_policy_ref", selected_policy_ref, PolicyRef),
            ("active_gate_set_ref", active_gate_set_ref, ExternalGateSetRef),
            ("active_candidate_ref", active_candidate_ref, ReleaseCandidateRef),
            ("approval", approval, ReleaseApproval),
        ):
            if value is not None:
                _require_exact(value, expected, field_name)

        # Every reachable immutable child is reconstructed through its own
        # constructor, so a value forged behind a retained digest is rejected.
        for source in sources:
            if source.validated() != source:
                raise ValidationError("a stored source failed reconstruction")
        for gate_set in gate_sets:
            if gate_set.validated() != gate_set:
                raise ValidationError("a stored gate set failed reconstruction")
            if gate_set.production_id != production_id:
                raise ValidationError("a stored gate set names a different Production")
        for sign_off in external_sign_offs:
            if sign_off.validated() != sign_off:
                raise ValidationError("a stored sign-off failed reconstruction")
            if sign_off.production_id != production_id:
                raise ValidationError("a stored sign-off names a different Production")
            # The live path refuses a sign-off no gate declares; stored history
            # must obey the same rule, or an undeclared sign-off could discharge
            # a policy requirement that pins no credential of its own.
            if not any(
                _gate_authorizes(requirement, sign_off)
                for gate_set in gate_sets
                for requirement in gate_set.requirements
            ):
                raise ValidationError(
                    "a stored sign-off is authorized by no gate this Production declared"
                )
        for candidate in candidates:
            if candidate.validated() != candidate:
                raise ValidationError("a stored candidate failed reconstruction")
            if candidate.production_id != production_id:
                raise ValidationError("a stored candidate names a different Production")

        attached_versions = {value.source_version_ref for value in sources}
        selected_edition_ref = (
            edition_selection.edition_ref if edition_selection is not None else None
        )
        if edition_selection is not None:
            if edition_selection.validated() != edition_selection:
                raise ValidationError("the stored edition selection failed reconstruction")
            if edition_selection.production_id != production_id:
                raise ValidationError(
                    "the stored edition selection names a different Production"
                )
            if not all(
                value in attached_versions
                for value in edition_selection.source_version_refs
            ):
                raise ValidationError(
                    "the stored edition selection uses an unattached source version"
                )

        for label, keys in (
            ("source", tuple(value.identity for value in sources)),
            (
                "gate set",
                tuple(value.external_gate_set_id.value for value in gate_sets),
            ),
            (
                "sign-off",
                tuple(value.sign_off_digest.hex_digest for value in external_sign_offs),
            ),
            (
                "candidate",
                tuple(value.release_candidate_id.value for value in candidates),
            ),
        ):
            if len(set(keys)) != len(keys):
                raise ValidationError(f"{label} identities must be unique")

        if active_gate_set_ref is not None and not any(
            value.ref == active_gate_set_ref for value in gate_sets
        ):
            raise ValidationError("the active gate-set ref has no stored gate set")
        if active_candidate_ref is not None and not any(
            value.ref == active_candidate_ref for value in candidates
        ):
            raise ValidationError("the active candidate ref has no stored snapshot")
        if active_gate_set_ref is None and gate_sets:
            raise ValidationError("stored gate sets require an active selection")

        gate_keys = tuple(_sign_off_gate_key(value) for value in external_sign_offs)
        if len(set(gate_keys)) != len(gate_keys):
            raise ValidationError(
                "stored sign-offs repeat one actor's decision on one gate target"
            )
        recorded_sign_offs = {
            value.sign_off_digest: value for value in external_sign_offs
        }
        for candidate in candidates:
            for digest in candidate.included_sign_off_digests:
                sign_off = recorded_sign_offs.get(digest)
                if sign_off is None:
                    raise ValidationError(
                        "a stored candidate includes a sign-off this Production "
                        "never recorded"
                    )
                if sign_off.target.content_manifest_ref != (
                    candidate.content_manifest_ref
                ):
                    raise ValidationError(
                        "a stored candidate includes a sign-off for other release content"
                    )

        if approval is not None:
            if approval.validated() != approval:
                raise ValidationError("the stored approval failed reconstruction")
            if active_candidate_ref is None or approval.release_candidate_ref != (
                active_candidate_ref
            ):
                raise ValidationError("approval does not bind the active candidate")
            if approval.steward_actor_id != steward_actor_id:
                raise ValidationError("approval was not recorded by this Production's steward")
            if selected_edition_ref is None or approval.edition_ref != selected_edition_ref:
                raise ValidationError("approval does not bind the selected edition")
            if selected_policy_ref is None or approval.policy_ref != selected_policy_ref:
                raise ValidationError("approval does not bind the selected policy")
            if active_gate_set_ref is None or approval.external_gate_set_ref != (
                active_gate_set_ref
            ):
                raise ValidationError("approval does not bind the active gate set")
            approved_candidate = next(
                (
                    value
                    for value in candidates
                    if value.ref == approval.release_candidate_ref
                ),
                None,
            )
            if approved_candidate is None:
                raise ValidationError("approval names no stored candidate snapshot")
            if approval.content_manifest_ref != approved_candidate.content_manifest_ref:
                raise ValidationError(
                    "approval does not bind its candidate's release content manifest"
                )
            if tuple(approval.accepted_sign_off_digests) != (
                approved_candidate.included_sign_off_digests
            ):
                raise ValidationError(
                    "approval sign-offs do not match its candidate snapshot"
                )

        if active_candidate_ref is not None:
            if edition_selection is None:
                raise ValidationError("an active candidate requires a selected edition")
            if selected_policy_ref is None:
                raise ValidationError("an active candidate requires a selected policy")
            if active_gate_set_ref is None:
                raise ValidationError(
                    "an active candidate requires an explicit active gate set"
                )

        production = cls._build(
            production_id=production_id,
            intended_deliverable=intended_deliverable,
            steward_actor_id=steward_actor_id,
            created_at_us=created_at_us,
            sources=sources,
            edition_selection=edition_selection,
            selected_policy_ref=selected_policy_ref,
            gate_sets=gate_sets,
            active_gate_set_ref=active_gate_set_ref,
            external_sign_offs=external_sign_offs,
            candidates=candidates,
            active_candidate_ref=active_candidate_ref,
            approval=approval,
        )
        production.pull_events()
        return production

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def _require_open(self) -> None:
        if self.approval is not None:
            raise InvariantError("approval is terminal; this Production cannot change")

    # ------------------------------------------------------------------
    # Behaviour
    # ------------------------------------------------------------------

    def attach_source(
        self,
        *,
        attached_source: AttachedSource,
        event_id: DomainEventId,
        event_occurred_at_us: int,
    ) -> AttachedSource:
        self._require_open()
        _require_exact(attached_source, AttachedSource, "attached_source")
        _require_event_inputs(event_id, event_occurred_at_us)
        checked = attached_source.validated()
        if checked != attached_source:
            raise ValidationError("attached source failed reconstruction")

        for existing in self.sources:
            if existing.identity != checked.identity:
                continue
            if existing.content != checked.content:
                raise ValidationError(
                    "this source identity is already attached with different content"
                )
            return existing

        self._write("sources", (*self.sources, checked))
        self._record_event(
            DomainEvent(
                event_id,
                event_occurred_at_us,
                "SourceRecordingAttached",
                {
                    "production_id": self.production_id.value,
                    "source_recording_id": checked.source_recording_id.value,
                    "source_version_id": checked.source_version_id.value,
                    "artifact_digest": checked.artifact.content_digest.hex_digest,
                },
            )
        )
        return checked

    def select_candidate_edition(
        self,
        *,
        selection: EditionSelection,
        event_id: DomainEventId,
        event_occurred_at_us: int,
    ) -> EditionRef:
        self._require_open()
        _require_exact(selection, EditionSelection, "selection")
        _require_event_inputs(event_id, event_occurred_at_us)

        if selection.production_id != self.production_id:
            raise ValidationError("edition selection names a different Production")
        attached = {value.source_version_ref for value in self.sources}
        if not all(value in attached for value in selection.source_version_refs):
            raise ValidationError(
                "edition selection uses a source version this Production never attached"
            )

        checked_selection = selection.validated()
        if checked_selection != selection:
            raise ValidationError("edition selection failed reconstruction")

        current = self.selected_edition_ref
        if current is not None:
            if current == selection.edition_ref:
                if self.edition_selection != checked_selection:
                    raise ValidationError(
                        "this edition is already selected with a different source set"
                    )
                return current
            if (
                current.transcript_edition_id
                == selection.edition_ref.transcript_edition_id
            ):
                raise ValidationError(
                    "this edition ID is already selected with a different digest"
                )

        self._write("edition_selection", checked_selection)
        self._write("active_candidate_ref", None)
        self._record_event(
            DomainEvent(
                event_id,
                event_occurred_at_us,
                "CandidateEditionSelected",
                {
                    "production_id": self.production_id.value,
                    "transcript_edition_id": (
                        selection.edition_ref.transcript_edition_id.value
                    ),
                    "edition_digest": selection.edition_ref.content_digest.hex_digest,
                },
            )
        )
        return selection.edition_ref

    def select_release_policy(
        self,
        *,
        policy: ReleasePolicyVersion,
        event_id: DomainEventId,
        event_occurred_at_us: int,
    ) -> PolicyRef:
        self._require_open()
        _require_exact(policy, ReleasePolicyVersion, "policy")
        _require_event_inputs(event_id, event_occurred_at_us)
        checked = policy.validated()

        current = self.selected_policy_ref
        if current is not None:
            if current == checked.ref:
                return current
            if (
                current.release_policy_version_id
                == checked.ref.release_policy_version_id
            ):
                raise ValidationError(
                    "this policy ID is already selected with a different digest"
                )

        self._write("selected_policy_ref", checked.ref)
        self._write("active_candidate_ref", None)
        self._record_event(
            DomainEvent(
                event_id,
                event_occurred_at_us,
                "ReleasePolicyVersionSelected",
                {
                    "production_id": self.production_id.value,
                    "release_policy_version_id": (
                        checked.ref.release_policy_version_id.value
                    ),
                    "policy_digest": checked.ref.policy_digest.hex_digest,
                },
            )
        )
        return checked.ref

    def configure_external_gates(
        self,
        *,
        gate_set: ExternalGateSet,
        event_id: DomainEventId,
        event_occurred_at_us: int,
    ) -> ExternalGateSetRef:
        self._require_open()
        _require_exact(gate_set, ExternalGateSet, "gate_set")
        _require_event_inputs(event_id, event_occurred_at_us)
        checked = gate_set.validated()

        if checked.production_id != self.production_id:
            raise ValidationError("gate set names a different Production")
        for existing in self.gate_sets:
            if existing.external_gate_set_id != checked.external_gate_set_id:
                continue
            if existing.content_digest != checked.content_digest:
                raise ValidationError(
                    "this gate-set ID already exists with a different digest"
                )
            if self.active_gate_set_ref == existing.ref:
                return existing.ref
            self._write("active_gate_set_ref", existing.ref)
            self._write("active_candidate_ref", None)
            self._record_event(
                self._gate_event(event_id, event_occurred_at_us, existing)
            )
            return existing.ref

        self._write("gate_sets", (*self.gate_sets, checked))
        self._write("active_gate_set_ref", checked.ref)
        self._write("active_candidate_ref", None)
        self._record_event(self._gate_event(event_id, event_occurred_at_us, checked))
        return checked.ref

    def _gate_event(
        self,
        event_id: DomainEventId,
        event_occurred_at_us: int,
        gate_set: ExternalGateSet,
    ) -> DomainEvent:
        return DomainEvent(
            event_id,
            event_occurred_at_us,
            "ExternalGateSetConfigured",
            {
                "production_id": self.production_id.value,
                "external_gate_set_id": gate_set.external_gate_set_id.value,
                "gate_set_digest": gate_set.content_digest.hex_digest,
                "requirement_count": len(gate_set.requirements),
            },
        )

    def record_external_sign_off(
        self,
        *,
        sign_off: ExternalSignOff,
        content: ReleaseContentBinding,
        event_id: DomainEventId,
        event_occurred_at_us: int,
    ) -> ExternalSignOff:
        self._require_open()
        _require_exact(sign_off, ExternalSignOff, "sign_off")
        _require_exact(content, ReleaseContentBinding, "content")
        _require_event_inputs(event_id, event_occurred_at_us)
        checked = sign_off.validated()
        checked_content = content.validated()
        if checked_content != content:
            raise ValidationError("release content failed reconstruction")

        if checked.production_id != self.production_id:
            raise ValidationError("sign-off names a different Production")
        gate_set = self.active_gate_set
        if gate_set is None:
            raise InvariantError(
                "an explicit active gate set is required before recording sign-offs"
            )
        self._require_content_matches_selection(checked_content)
        if checked.target.content_manifest_ref != checked_content.content_manifest_ref:
            raise ValidationError(
                "sign-off does not target this exact sealed release content"
            )

        requirement = next(
            (
                value
                for value in gate_set.requirements
                if value.gate_code == checked.gate_code
            ),
            None,
        )
        if requirement is None:
            raise ValidationError(
                "sign-off names a gate the active gate set does not declare"
            )
        # The pinned credential is required for every decision: an unpinned
        # credential must never enter append-only history, even as a decline.
        if (
            requirement.role != checked.role
            or requirement.credential != checked.credential
            or requirement.target_rule.target_kind is not checked.target.target_kind
        ):
            raise ValidationError(
                "sign-off does not match the exact credential, role, and target its gate pins"
            )
        required_member = requirement.target_rule.required_member_role
        if required_member is not None:
            expected_digest = checked_content.member_digest(required_member)
            if (
                checked.target.member_role != required_member
                or expected_digest is None
                or checked.target.member_digest != expected_digest
            ):
                raise ValidationError(
                    "sign-off does not bind the exact manifest member its gate requires"
                )
        if checked.decision is SignOffDecision.APPROVED and not assurance_satisfies(
            checked.assurance.assurance, requirement.minimum_assurance
        ):
            raise ValidationError(
                "approving sign-off assurance is below its gate minimum"
            )

        for existing in self.external_sign_offs:
            if existing.sign_off_digest == checked.sign_off_digest:
                return existing
        # One actor decides one gate once, matching how ReviewRound keys a
        # sign-off by (role, actor, target). Re-signing the same gate and target
        # at a different time would otherwise pollute append-only history and
        # make "how many signers" ambiguous.
        if any(
            _sign_off_gate_key(existing) == _sign_off_gate_key(checked)
            for existing in self.external_sign_offs
        ):
            raise ValidationError(
                "this actor has already decided this gate for this exact target"
            )

        self._write("external_sign_offs", (*self.external_sign_offs, checked))
        self._record_event(
            DomainEvent(
                event_id,
                event_occurred_at_us,
                "ExternalSignOffRecorded",
                {
                    "production_id": self.production_id.value,
                    "gate_code": checked.gate_code.value,
                    "actor_id": checked.credential.actor_id.value,
                    "role": checked.role.value,
                    "decision": checked.decision.value,
                    "sign_off_digest": checked.sign_off_digest.hex_digest,
                },
            )
        )
        return checked

    def _require_content_matches_selection(
        self, content: ReleaseContentBinding
    ) -> None:
        if self.selected_edition_ref is None:
            raise InvariantError("no candidate edition is selected")
        if self.selected_policy_ref is None:
            raise InvariantError("no release policy is selected")
        if self.active_gate_set_ref is None:
            raise InvariantError("no explicit external gate set is selected")
        if content.production_id != self.production_id:
            raise ValidationError("release content names a different Production")
        if content.edition_ref != self.selected_edition_ref:
            raise StaleReferenceError(
                "release content does not bind the selected edition"
            )
        if content.policy_ref != self.selected_policy_ref:
            raise StaleReferenceError("release content does not bind the selected policy")
        if content.external_gate_set_ref != self.active_gate_set_ref:
            raise StaleReferenceError(
                "release content does not bind the active gate set"
            )

    def assemble_candidate(
        self,
        *,
        candidate: ReleaseCandidateSnapshot,
        content: ReleaseContentBinding,
        event_id: DomainEventId,
        event_occurred_at_us: int,
    ) -> ReleaseCandidateSnapshot:
        self._require_open()
        _require_exact(candidate, ReleaseCandidateSnapshot, "candidate")
        _require_exact(content, ReleaseContentBinding, "content")
        _require_event_inputs(event_id, event_occurred_at_us)
        checked = candidate.validated()
        checked_content = content.validated()
        if checked_content != content:
            raise ValidationError("release content failed reconstruction")

        if checked.production_id != self.production_id:
            raise ValidationError("candidate names a different Production")
        self._require_content_matches_selection(checked_content)
        checked.bind(checked_content)

        recorded = {value.sign_off_digest: value for value in self.external_sign_offs}
        for digest in checked.included_sign_off_digests:
            sign_off = recorded.get(digest)
            if sign_off is None:
                raise ValidationError(
                    "candidate includes a sign-off this Production never recorded"
                )
            if sign_off.target.content_manifest_ref != (
                checked_content.content_manifest_ref
            ):
                raise ValidationError(
                    "candidate includes a sign-off for other release content"
                )

        # An ID conflict is decided over the whole history before any
        # digest-reuse shortcut, so rejection cannot depend on iteration order.
        for existing in self.candidates:
            if (
                existing.release_candidate_id == checked.release_candidate_id
                and existing.semantic_digest != checked.semantic_digest
            ):
                raise ValidationError(
                    "this candidate ID already exists with a different digest"
                )

        replayed = next(
            (
                value
                for value in self.candidates
                if value.semantic_digest == checked.semantic_digest
            ),
            None,
        )
        selected = replayed if replayed is not None else checked
        if replayed is not None and self.active_candidate_ref == replayed.ref:
            return replayed

        event = DomainEvent(
            event_id,
            event_occurred_at_us,
            "ReleaseCandidateAssembled",
            {
                "production_id": self.production_id.value,
                "release_candidate_id": selected.release_candidate_id.value,
                "candidate_digest": selected.semantic_digest.hex_digest,
                "release_content_manifest_id": (
                    selected.content_manifest_ref.release_content_manifest_id.value
                ),
                "sign_off_count": len(selected.included_sign_off_digests),
                "replayed": replayed is not None,
            },
        )
        if replayed is None:
            self._write("candidates", (*self.candidates, checked))
        self._write("active_candidate_ref", selected.ref)
        self._record_event(event)
        return selected

    def approve_candidate(
        self,
        *,
        evidence: ApprovalEvidence,
        steward_actor_id: ActorId,
        approved_at_us: int,
        operation_id: OperationId,
        event_id: DomainEventId,
        event_occurred_at_us: int,
    ) -> ReleaseApproval:
        if self.approval is not None:
            raise InvariantError("this Production already has a release approval")
        _require_exact(evidence, ApprovalEvidence, "evidence")
        _require_exact(steward_actor_id, ActorId, "steward_actor_id")
        _require_exact(operation_id, OperationId, "operation_id")
        if type(approved_at_us) is not int or approved_at_us <= 0:
            raise ValidationError("approved_at_us must be a positive integer")
        _require_event_inputs(event_id, event_occurred_at_us)

        # Re-run the complete evidence check, including the pinned evaluator.
        evidence = evidence.validated()
        if evidence.snapshot.production_id != self.production_id:
            raise StaleReferenceError(
                "approval evidence was assembled for a different Production"
            )
        if steward_actor_id != self.steward_actor_id:
            raise ValidationError("only this Production's steward can approve a release")
        if self.active_candidate_ref is None:
            raise InvariantError("no active release candidate is selected")
        if evidence.candidate.ref != self.active_candidate_ref:
            raise StaleReferenceError(
                "approval evidence does not name the active candidate"
            )
        if not any(
            value.semantic_digest == evidence.candidate.semantic_digest
            for value in self.candidates
        ):
            raise StaleReferenceError("the approved candidate is not a stored snapshot")

        self._require_content_matches_selection(evidence.content)
        if evidence.policy.ref != self.selected_policy_ref:
            raise StaleReferenceError("approval policy is not the selected policy")
        if evidence.gate_set.ref != self.active_gate_set_ref:
            raise StaleReferenceError("approval gate set is not the active gate set")

        recorded = {value.sign_off_digest for value in self.external_sign_offs}
        if not all(
            value.sign_off_digest in recorded for value in evidence.accepted_sign_offs
        ):
            raise StaleReferenceError(
                "approval names a sign-off this Production never recorded"
            )

        if not evidence.eligible:
            raise InvariantError(
                "an ineligible candidate can never be approved"
            )

        approval = ReleaseApproval.seal(
            evidence=evidence,
            steward_actor_id=steward_actor_id,
            approved_at_us=approved_at_us,
            operation_id=operation_id,
        )
        self._write("approval", approval)
        self._record_event(
            DomainEvent(
                event_id,
                event_occurred_at_us,
                "ReleaseCandidateApproved",
                {
                    "production_id": self.production_id.value,
                    "release_candidate_id": (
                        approval.release_candidate_ref.release_candidate_id.value
                    ),
                    "candidate_digest": (
                        approval.release_candidate_ref.semantic_digest.hex_digest
                    ),
                    "release_content_manifest_id": (
                        approval.content_manifest_ref.release_content_manifest_id.value
                    ),
                    "release_content_digest": (
                        approval.content_manifest_ref.semantic_digest.hex_digest
                    ),
                    "eligibility_assessment_id": (
                        approval.assessment_ref.eligibility_assessment_id.value
                    ),
                    "eligibility_digest": (
                        approval.assessment_ref.semantic_digest.hex_digest
                    ),
                    "approval_digest": approval.approval_digest.hex_digest,
                    "steward_actor_id": steward_actor_id.value,
                },
            )
        )
        return approval

    # ------------------------------------------------------------------
    # Read-only projections
    # ------------------------------------------------------------------

    @property
    def selected_edition_ref(self) -> EditionRef | None:
        """The exact selected edition, derived from its verified selection."""
        if self.edition_selection is None:
            return None
        return self.edition_selection.edition_ref

    @property
    def active_gate_set(self) -> ExternalGateSet | None:
        if self.active_gate_set_ref is None:
            return None
        return next(
            value for value in self.gate_sets if value.ref == self.active_gate_set_ref
        )

    @property
    def active_candidate(self) -> ReleaseCandidateSnapshot | None:
        if self.active_candidate_ref is None:
            return None
        return next(
            value for value in self.candidates if value.ref == self.active_candidate_ref
        )

    @property
    def lifecycle_phase(self) -> str:
        """The display phase this aggregate alone can honestly derive.

        The cross-module read model adds `CONTENT_SEALED`, `REVIEWED`, and
        `IN_REVIEW`, which require review and release-content facts Production
        does not own. These labels are projections, never command guards.
        """
        if self.approval is not None:
            return "APPROVED"
        if self.active_candidate_ref is not None:
            return "CANDIDATE_ASSEMBLED"
        if self.selected_edition_ref is not None:
            return "TRANSCRIPT_SELECTED"
        if self.sources:
            return "SOURCED"
        return "DRAFT"
