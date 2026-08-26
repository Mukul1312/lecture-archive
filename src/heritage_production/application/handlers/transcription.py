"""Handlers for the Transcription module's sealed roots.

`ImportProposalPackage` is where the anti-corruption boundary of design 10.4
actually runs. Everything the legacy package claims about itself is evidence;
nothing it claims is authority. The adapter translates, and this handler
decides whether what came back may become a sealed `ASRProposalSet`.

Three refusals matter more than the happy path:

* a quarantined translation creates nothing. Design 10.4 quarantines an import
  whose source cannot be independently bound, and there is no
  `ProvenanceStatus` that records "quarantined", so there is no honest sealed
  object to write.
* an adapter whose identity differs from the one the command declared is
  refused, because that identity is in the idempotency key (design 9.4) and a
  declaration nothing checks is not a key.
* a translation bound to a source other than the one the operator supplied is
  refused. Design 10.4 exists precisely because a legacy package's own idea of
  its audio is not authority.
"""

from __future__ import annotations

from heritage_production.domain.shared import (
    DomainEventId,
    PolicyRefusalError,
    StaleReferenceError,
    ValidationError,
)
from heritage_production.domain.review import FindingDecision
from heritage_production.domain.transcription import (
    ASRProposalSet,
    ParentEditionManifest,
    TranscriptEdition,
)

from ..commands.transcription import (
    CreateInitialTranscriptEdition,
    CreateSuccessorTranscriptEdition,
    ImportProposalPackage,
)
from ..execution import CompletedOperation, OperationResult, run_operation


def _proposal_payload(proposal_set: ASRProposalSet) -> dict:
    """A sealed root, so the semantic digest is what a replay pins."""
    return {
        "proposal_set_id": proposal_set.proposal_set_id.value,
        "content_digest": proposal_set.semantic_digest.hex_digest,
        "provenance_status": proposal_set.provenance_status.value,
        "item_count": len(proposal_set.items),
        "warning_count": len(proposal_set.missing_field_warnings),
    }


def _edition_payload(edition: TranscriptEdition) -> dict:
    """A sealed root, so the semantic digest is what a replay pins."""
    return {
        "transcript_edition_id": edition.transcript_edition_id.value,
        "production_id": edition.production_id.value,
        "content_digest": edition.semantic_digest.hex_digest,
        "revision_count": len(edition.revisions),
        "gap_count": len(edition.gaps),
    }


class TranscriptionCommandHandlers:
    def __init__(
        self,
        *,
        proposals,
        editions,
        productions,
        findings,
        artifacts,
        translator,
        transactions,
        recorder,
        events,
        clock,
        ids,
    ) -> None:
        self._proposals = proposals
        self._editions = editions
        self._productions = productions
        self._findings = findings
        self._artifacts = artifacts
        self._translator = translator
        self._transactions = transactions
        self._recorder = recorder
        self._events = events
        self._clock = clock
        self._ids = ids

    def _publish(self, root) -> None:
        for event in root.pull_events():
            self._events.enqueue(event)

    def _resolve_proposal_sets(self, command) -> None:
        """Read every declared proposal set by exact ID and digest.

        Design 9.3 reads immutable inputs from other aggregates that way, and
        a sealed edition cannot be deleted afterwards, so a reference that is
        wrong here is wrong permanently.
        """
        declared_sources = set(command.source_versions)
        for ref in command.proposal_set_refs:
            stored = self._proposals.get(ref.proposal_set_id)
            if stored.ref != ref:
                raise StaleReferenceError(
                    "the stored proposal set does not match the digest this edition pins"
                )
            # The application owns this check because neither aggregate can
            # see the other: an edition built from proposals for a recording
            # it does not declare has incoherent provenance.
            if stored.source_version not in declared_sources:
                raise ValidationError(
                    "a proposal set was imported for a source this edition does not declare"
                )

    def create_initial_transcript_edition(
        self, command: CreateInitialTranscriptEdition
    ) -> CompletedOperation:
        def execute() -> OperationResult:
            # A sealed edition has no delete path, so an edition for a
            # Production that does not exist would be permanent orphan
            # evidence rather than a recoverable mistake.
            self._productions.load(command.production_id)
            self._resolve_proposal_sets(command)
            edition = TranscriptEdition.seal_initial(
                transcript_edition_id=command.transcript_edition_id,
                production_id=command.production_id,
                source_versions=command.source_versions,
                transcript_scope=command.transcript_scope,
                proposal_set_refs=command.proposal_set_refs,
                revisions=command.revisions,
                gaps=command.gaps,
                change_manifest=command.change_manifest,
                creation_actor_id=command.actor.actor_id,
                created_at_us=self._clock.now_us(),
                event_id=DomainEventId(self._ids.new_id()),
                event_occurred_at_us=self._clock.now_us(),
            )
            self._editions.add(edition)
            # Sealed, but not silent: design 9.6 lists TranscriptEditionCreated,
            # so this root has events to drain even though it can never change.
            self._publish(edition)
            return OperationResult(value=edition, payload=_edition_payload(edition))

        def rederive(record) -> OperationResult:
            stored = self._editions.get(command.transcript_edition_id)
            return OperationResult(value=stored, payload=_edition_payload(stored))

        return run_operation(
            command,
            recorder=self._recorder,
            unit_of_work=self._transactions(),
            clock=self._clock,
            execute=execute,
            rederive=rederive,
        )

    def _resolve_parent(self, command):
        """Bind the parent manifest to the parent that is actually stored.

        `ParentEditionManifest` self-verifies: it recomputes its content
        digest and refuses to exist unless that equals its own `EditionRef`.
        So the manifest cannot misdescribe *some* edition -- but nothing in
        the domain says which edition, and a manifest describing an edition
        that was never sealed is perfectly well-formed. Checking the ref
        against storage is what ties it to this Production's history.

        The rebuilt comparison covers the one field that digest cannot:
        `ancestor_edition_refs`. The domain pins its first element to the
        parent's own parent, so a lie needs a chain three deep -- beyond that
        first step the ancestry is asserted by the caller, and this walks it.
        """
        stored = self._editions.get(command.parent.edition_ref.transcript_edition_id)
        if stored.ref != command.parent.edition_ref:
            raise StaleReferenceError(
                "the stored parent edition does not match the digest this successor pins"
            )
        if stored.production_id != command.production_id:
            raise StaleReferenceError(
                "the parent edition belongs to a different Production"
            )
        rebuilt = ParentEditionManifest.from_edition(stored, self._ancestors_of(stored))
        if rebuilt != command.parent:
            raise ValidationError(
                "the supplied parent manifest does not describe the stored parent"
            )
        return stored

    def _ancestors_of(self, edition) -> tuple:
        """Walk the stored lineage, nearest first, verifying each digest.

        The ancestry is derived rather than accepted: a caller free to assert
        its own lineage could hide an edition from the record.
        """
        chain: list = []
        current = edition.parent_edition_ref
        while current is not None:
            ancestor = self._editions.get(current.transcript_edition_id)
            if ancestor.ref != current:
                raise StaleReferenceError(
                    "a stored ancestor edition does not match its recorded digest"
                )
            chain.append(ancestor.ref)
            current = ancestor.parent_edition_ref
        return tuple(chain)

    def _require_accepted_findings(self, command, parent) -> tuple:
        """Design 9.2 step 9: an accepted correction is what justifies a successor.

        The domain checks these refs against the change manifest's keys. It
        cannot check that the findings exist, that they were accepted rather
        than rejected, or that they were raised against *this* parent -- only
        something holding both aggregates can. Step 10 is explicit that review
        of another edition is historical evidence, never authority here.
        """
        refs = tuple(
            mapping.finding for mapping in command.change_manifest.finding_mappings
        )
        for ref in refs:
            finding = self._findings.load(ref.review_finding_id).root
            if finding.finding_payload_digest != ref.finding_payload_digest:
                raise StaleReferenceError(
                    "the stored finding does not match the payload digest this change pins"
                )
            if finding.edition_ref != parent.ref:
                raise PolicyRefusalError(
                    "a finding raised against another edition cannot authorize this successor"
                )
            disposition = finding.disposition
            if disposition is None:
                raise PolicyRefusalError(
                    "an undecided finding cannot authorize a successor edition"
                )
            if disposition.decision is not FindingDecision.ACCEPTED:
                raise PolicyRefusalError(
                    "only an accepted finding can authorize a successor edition"
                )
            if disposition.disposition_digest != ref.disposition_digest:
                raise StaleReferenceError(
                    "the stored disposition does not match the digest this change pins"
                )
        return refs

    def create_successor_transcript_edition(
        self, command: CreateSuccessorTranscriptEdition
    ) -> CompletedOperation:
        def execute() -> OperationResult:
            # No separate Production existence check here: the parent edition
            # names a Production that exists by construction, so a command
            # naming a different one is refused by the comparison in
            # `_resolve_parent` whether or not that other one exists. The
            # initial-edition handler has no parent, so there the load is the
            # only check and stays.
            parent = self._resolve_parent(command)
            self._resolve_proposal_sets(command)
            accepted = self._require_accepted_findings(command, parent)
            edition = TranscriptEdition.seal_successor(
                transcript_edition_id=command.transcript_edition_id,
                production_id=command.production_id,
                source_versions=command.source_versions,
                transcript_scope=command.transcript_scope,
                proposal_set_refs=command.proposal_set_refs,
                parent_edition_ref=command.parent.edition_ref,
                revisions=command.revisions,
                gaps=command.gaps,
                change_manifest=command.change_manifest,
                creation_actor_id=command.actor.actor_id,
                created_at_us=self._clock.now_us(),
                parent_manifest=command.parent,
                accepted_findings=accepted,
                event_id=DomainEventId(self._ids.new_id()),
                event_occurred_at_us=self._clock.now_us(),
            )
            self._editions.add(edition)
            self._publish(edition)
            return OperationResult(value=edition, payload=_edition_payload(edition))

        def rederive(record) -> OperationResult:
            stored = self._editions.get(command.transcript_edition_id)
            return OperationResult(value=stored, payload=_edition_payload(stored))

        return run_operation(
            command,
            recorder=self._recorder,
            unit_of_work=self._transactions(),
            clock=self._clock,
            execute=execute,
            rederive=rederive,
        )

    def import_proposal_package(
        self, command: ImportProposalPackage
    ) -> CompletedOperation:
        translated = None

        def prepare() -> None:
            nonlocal translated
            # Outside the transaction: this reads bytes and runs an adapter,
            # and a rejected package must never open one.
            if not self._artifacts.verify(command.raw_package):
                raise StaleReferenceError(
                    "raw package does not match stored content-addressed bytes"
                )
            identity = self._translator.identity()
            if (
                identity.name != command.importing_adapter
                or identity.version != command.importing_adapter_version
            ):
                raise StaleReferenceError(
                    "the translating adapter is not the one this command declares"
                )
            result = self._translator.translate(
                raw_package=command.raw_package,
                import_root=command.import_root,
                bound_source=command.source_version,
            )
            if result.quarantined:
                raise PolicyRefusalError(
                    result.quarantine_reason or "the imported package was quarantined"
                )
            if result.raw_package != command.raw_package:
                raise ValidationError(
                    "the translation is not of the package this command names"
                )
            translated = result

        def execute() -> OperationResult:
            if translated is None:  # pragma: no cover - prepare always runs first
                raise ValidationError("the package was never translated")
            proposal_set = ASRProposalSet.create(
                proposal_set_id=command.proposal_set_id,
                source_version=command.source_version,
                package_schema_version=translated.package_schema_version,
                package_digest=command.raw_package.content_digest,
                importing_adapter=command.importing_adapter,
                importing_adapter_version=command.importing_adapter_version,
                tool_identity=translated.tool_identity,
                model_name=translated.model_name,
                model_revision=translated.model_revision,
                configuration=translated.configuration,
                provenance_status=translated.provenance_status,
                missing_field_warnings=translated.missing_field_warnings,
                steward_attestation=command.steward_attestation,
                imported_at_us=self._clock.now_us(),
                raw_artifact=command.raw_package,
                items=translated.items,
            )
            self._proposals.add(proposal_set)
            return OperationResult(
                value=proposal_set, payload=_proposal_payload(proposal_set)
            )

        def rederive(record) -> OperationResult:
            stored = self._proposals.get(command.proposal_set_id)
            return OperationResult(value=stored, payload=_proposal_payload(stored))

        return run_operation(
            command,
            recorder=self._recorder,
            unit_of_work=self._transactions(),
            clock=self._clock,
            execute=execute,
            rederive=rederive,
            prepare=prepare,
        )


__all__ = ["TranscriptionCommandHandlers"]
