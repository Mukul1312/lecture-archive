"""Registration handlers, which write no aggregate at all.

Design 9.1 gives both of these "Artifact/operation records only" as their
write set. That makes them the first handlers with nothing to reload on a
replay: there is no root to fetch and compare, so the operation record's
stored payload *is* the durable result, and `rederive` rebuilds the reference
from it rather than from aggregate state.

Because nothing here writes a root, one transaction stages only the operation
record. The one-root rule is not being spent, and design 9.3 is satisfied
trivially rather than by care -- which is worth stating, because a later
change that quietly adds an aggregate write here would be the interesting
event.
"""

from __future__ import annotations

from heritage_production.domain.shared import (
    ActorCredentialRef,
    ActorId,
    ArtifactRef,
    AssuranceLevel,
    ContentDigest,
    CredentialVerificationMethod,
    RubricId,
    RubricRef,
    StaleReferenceError,
    ValidationError,
)

from ..commands.release import RegisterActorCredential, RegisterRubric
from ..execution import CompletedOperation, OperationResult, run_operation


def _rubric_payload(rubric: RubricRef) -> dict:
    return {
        "rubric_id": rubric.rubric_id.value,
        "schema_version": rubric.schema_version,
        "content_digest": rubric.content_digest.hex_digest,
        "artifact_id": rubric.artifact.artifact_id.value,
    }


def _credential_payload(credential: ActorCredentialRef) -> dict:
    """Public verification evidence only; a private key never reaches here.

    `ActorCredentialRef` already refuses key evidence on a noncryptographic
    claim, so the payload can mirror the reference without deciding for itself
    what is safe to record (design 15.1).
    """
    fingerprint = credential.credential_fingerprint
    artifact = credential.public_key_artifact
    return {
        "actor_id": credential.actor_id.value,
        "verification_method": credential.verification_method.value,
        "assurance": credential.assurance.value,
        "credential_fingerprint": None if fingerprint is None else fingerprint.hex_digest,
        "public_key_artifact_id": None if artifact is None else artifact.artifact_id.value,
    }


class RegistrationCommandHandlers:
    def __init__(self, *, artifacts, transactions, recorder, clock) -> None:
        self._artifacts = artifacts
        self._transactions = transactions
        self._recorder = recorder
        self._clock = clock

    def _require_stored(self, artifact: ArtifactRef, *, field: str) -> None:
        """The store is asked, never the caller.

        A reference is a claim about bytes. `verify` re-hashes what is stored,
        so a reference naming absent bytes, or bytes that no longer hash to
        the digest claimed, is refused rather than registered.
        """
        if not self._artifacts.verify(artifact):
            raise StaleReferenceError(
                f"{field} does not match stored content-addressed bytes"
            )

    def _run(self, command, *, execute, rederive, prepare) -> CompletedOperation:
        return run_operation(
            command,
            recorder=self._recorder,
            unit_of_work=self._transactions(),
            clock=self._clock,
            execute=execute,
            rederive=rederive,
            prepare=prepare,
        )

    def register_rubric(self, command: RegisterRubric) -> CompletedOperation:
        rubric = RubricRef(
            rubric_id=command.rubric_id,
            schema_version=command.schema_version,
            content_digest=command.content.content_digest,
            artifact=command.content,
        )

        def prepare() -> None:
            self._require_stored(command.content, field="rubric content")

        def execute() -> OperationResult:
            return OperationResult(value=rubric, payload=_rubric_payload(rubric))

        def rederive(record) -> OperationResult:
            stored = record.result_payload
            # Rebuilt from the record, not from the command: a replay must
            # return what the first run registered, and comparing the rebuilt
            # reference against the command is what proves they agree.
            rebuilt = RubricRef(
                rubric_id=RubricId(stored["rubric_id"]),
                schema_version=stored["schema_version"],
                content_digest=ContentDigest("sha256", stored["content_digest"]),
                artifact=command.content,
            )
            if rebuilt != rubric:
                raise ValidationError(
                    "the recorded rubric does not match the one this command names"
                )
            return OperationResult(value=rebuilt, payload=_rubric_payload(rebuilt))

        return self._run(command, execute=execute, rederive=rederive, prepare=prepare)

    def register_actor_credential(
        self, command: RegisterActorCredential
    ) -> CompletedOperation:
        credential = command.credential

        def prepare() -> None:
            # Only a cryptographic credential carries key material to check;
            # the reference type already refuses it on the other two methods.
            if credential.public_key_artifact is not None:
                self._require_stored(
                    credential.public_key_artifact, field="public key artifact"
                )

        def execute() -> OperationResult:
            return OperationResult(
                value=credential, payload=_credential_payload(credential)
            )

        def rederive(record) -> OperationResult:
            stored = record.result_payload
            if stored != _credential_payload(credential):
                raise ValidationError(
                    "the recorded credential does not match the one this command names"
                )
            return OperationResult(value=credential, payload=stored)

        return self._run(command, execute=execute, rederive=rederive, prepare=prepare)


__all__ = ["RegistrationCommandHandlers"]
