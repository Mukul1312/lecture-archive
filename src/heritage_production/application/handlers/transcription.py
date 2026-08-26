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
    PolicyRefusalError,
    ProposalSetId,
    StaleReferenceError,
    ValidationError,
)
from heritage_production.domain.transcription import ASRProposalSet

from ..commands.transcription import ImportProposalPackage
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


class TranscriptionCommandHandlers:
    def __init__(
        self,
        *,
        proposals,
        artifacts,
        translator,
        transactions,
        recorder,
        clock,
    ) -> None:
        self._proposals = proposals
        self._artifacts = artifacts
        self._translator = translator
        self._transactions = transactions
        self._recorder = recorder
        self._clock = clock

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
            stored = self._proposals.get(
                ProposalSetId(record.result_payload["proposal_set_id"])
            )
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
