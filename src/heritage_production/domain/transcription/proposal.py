"""Sealed ASR proposal evidence bound to one exact source version."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from heritage_production.domain.shared import (
    ActorId,
    ArtifactRef,
    ContentDigest,
    ProposalItemId,
    ProposalSetId,
    SourceSpan,
    SourceVersionRef,
    TranscriptText,
    ValidationError,
    semantic_digest as calculate_semantic_digest,
)
from heritage_production.domain.shared.text import require_canonical_text


class EvidenceStatus(str, Enum):
    VERIFIED = "verified"
    OBSERVED = "observed"
    UNKNOWN = "unknown"


class ProvenanceStatus(str, Enum):
    COMPLETE = "complete"
    LEGACY_ATTESTED = "legacy_attested"


@dataclass(frozen=True, slots=True)
class IdentityEvidence:
    status: EvidenceStatus
    value: str | None

    def __post_init__(self) -> None:
        if type(self.status) is not EvidenceStatus:
            raise ValidationError("identity evidence status must be an EvidenceStatus")
        if self.status is EvidenceStatus.UNKNOWN:
            if self.value is not None:
                raise ValidationError("unknown identity evidence must not claim a value")
        else:
            require_canonical_text(self.value, field="identity evidence", nonempty=True)


@dataclass(frozen=True, slots=True)
class ConfigurationEvidence:
    status: EvidenceStatus
    content_digest: ContentDigest | None

    def __post_init__(self) -> None:
        if type(self.status) is not EvidenceStatus:
            raise ValidationError("configuration evidence status must be an EvidenceStatus")
        if self.status is EvidenceStatus.UNKNOWN:
            if self.content_digest is not None:
                raise ValidationError("unknown configuration evidence must not claim a digest")
        elif type(self.content_digest) is not ContentDigest:
            raise ValidationError("known configuration evidence requires a ContentDigest")


@dataclass(frozen=True, slots=True)
class ConfidenceEvidence:
    name: str
    value: str

    def __post_init__(self) -> None:
        require_canonical_text(self.name, field="confidence evidence name", nonempty=True)
        require_canonical_text(self.value, field="confidence evidence value", nonempty=True)


@dataclass(frozen=True, slots=True)
class RawRowLocator:
    stable_locator: str
    observed_absolute_path: str | None = None

    def __post_init__(self) -> None:
        require_canonical_text(
            self.stable_locator,
            field="stable raw row locator",
            nonempty=True,
        )
        if self.observed_absolute_path is not None:
            require_canonical_text(
                self.observed_absolute_path,
                field="observed absolute raw path",
                nonempty=True,
            )
            path = self.observed_absolute_path
            windows_drive = (
                len(path) >= 3
                and path[0].isalpha()
                and path[1] == ":"
                and path[2] in ("/", "\\")
            )
            if not (
                path.startswith("/")
                or path.startswith("\\\\")
                or windows_drive
            ):
                raise ValidationError(
                    "observed raw path must be lexically absolute"
                )


@dataclass(frozen=True, slots=True)
class StewardAttestation:
    actor_id: ActorId
    reason: str
    attested_at_us: int
    evidence_digest: ContentDigest

    def __post_init__(self) -> None:
        if type(self.actor_id) is not ActorId:
            raise ValidationError("attestation actor_id must be an ActorId")
        require_canonical_text(self.reason, field="attestation reason", nonempty=True)
        if type(self.attested_at_us) is not int or self.attested_at_us <= 0:
            raise ValidationError("attested_at_us must be a positive integer")
        if type(self.evidence_digest) is not ContentDigest:
            raise ValidationError("attestation evidence_digest must be a ContentDigest")


@dataclass(frozen=True, slots=True)
class ProposalItem:
    proposal_item_id: ProposalItemId
    source_span: SourceSpan
    proposed_text: TranscriptText
    language: str
    speaker_hypothesis: str | None
    confidence_evidence: tuple[ConfidenceEvidence, ...]
    raw_row_locator: RawRowLocator

    def __post_init__(self) -> None:
        if type(self.proposal_item_id) is not ProposalItemId:
            raise ValidationError("proposal_item_id must be a ProposalItemId")
        if type(self.source_span) is not SourceSpan:
            raise ValidationError("source_span must be an exact SourceSpan")
        if type(self.proposed_text) is not TranscriptText:
            raise ValidationError("proposed_text must be a TranscriptText")
        require_canonical_text(self.language, field="proposal language", nonempty=True)
        if self.speaker_hypothesis is not None:
            require_canonical_text(
                self.speaker_hypothesis,
                field="speaker hypothesis",
                nonempty=True,
            )
        if type(self.confidence_evidence) is not tuple or not all(
            type(value) is ConfidenceEvidence for value in self.confidence_evidence
        ):
            raise ValidationError("confidence_evidence must be a tuple of ConfidenceEvidence")
        if type(self.raw_row_locator) is not RawRowLocator:
            raise ValidationError("raw_row_locator must be a RawRowLocator")


@dataclass(frozen=True, slots=True)
class ProposalSetRef:
    proposal_set_id: ProposalSetId
    content_digest: ContentDigest

    def __post_init__(self) -> None:
        if type(self.proposal_set_id) is not ProposalSetId:
            raise ValidationError("proposal_set_id must be a ProposalSetId")
        if type(self.content_digest) is not ContentDigest:
            raise ValidationError("content_digest must be a ContentDigest")


def _digest_value(value: ContentDigest) -> dict[str, object]:
    return {"algorithm": value.algorithm, "hex_digest": value.hex_digest}


def _source_value(value: SourceVersionRef) -> dict[str, object]:
    return {
        "source_version_id": value.source_version_id.value,
        "source_recording_id": value.source_recording_id.value,
        "artifact_digest": _digest_value(value.artifact_digest),
        "duration_us": value.duration_us,
        "time_base_evidence": value.time_base_evidence,
    }


def _span_value(value: SourceSpan) -> dict[str, object]:
    return {
        "source_version": _source_value(value.source_version),
        "start_us": value.start_us,
        "end_us": value.end_us,
    }


def _identity_value(value: IdentityEvidence) -> dict[str, object]:
    return {"status": value.status.value, "value": value.value}


def _configuration_value(value: ConfigurationEvidence) -> dict[str, object]:
    return {
        "status": value.status.value,
        "content_digest": (
            _digest_value(value.content_digest) if value.content_digest is not None else None
        ),
    }


def _item_value(value: ProposalItem) -> dict[str, object]:
    return {
        "proposal_item_id": value.proposal_item_id.value,
        "source_span": _span_value(value.source_span),
        "proposed_text": value.proposed_text.value,
        "language": value.language,
        "speaker_hypothesis": value.speaker_hypothesis,
        "confidence_evidence": [
            {"name": evidence.name, "value": evidence.value}
            for evidence in value.confidence_evidence
        ],
        "raw_row_locator": value.raw_row_locator.stable_locator,
    }


@dataclass(frozen=True, slots=True, init=False)
class ASRProposalSet:
    proposal_set_id: ProposalSetId
    source_version: SourceVersionRef
    package_schema_version: int
    package_digest: ContentDigest
    importing_adapter: str
    importing_adapter_version: str
    tool_identity: IdentityEvidence
    model_name: IdentityEvidence
    model_revision: IdentityEvidence
    configuration: ConfigurationEvidence
    provenance_status: ProvenanceStatus
    missing_field_warnings: tuple[str, ...]
    steward_attestation: StewardAttestation | None
    imported_at_us: int
    raw_artifact: ArtifactRef
    items: tuple[ProposalItem, ...]
    semantic_digest: ContentDigest

    @classmethod
    def create(
        cls,
        *,
        proposal_set_id: ProposalSetId,
        source_version: SourceVersionRef,
        package_schema_version: int,
        package_digest: ContentDigest,
        importing_adapter: str,
        importing_adapter_version: str,
        tool_identity: IdentityEvidence,
        model_name: IdentityEvidence,
        model_revision: IdentityEvidence,
        configuration: ConfigurationEvidence,
        provenance_status: ProvenanceStatus,
        missing_field_warnings: tuple[str, ...],
        steward_attestation: StewardAttestation | None,
        imported_at_us: int,
        raw_artifact: ArtifactRef,
        items: tuple[ProposalItem, ...],
    ) -> ASRProposalSet:
        values = cls._validated_values(
            proposal_set_id=proposal_set_id,
            source_version=source_version,
            package_schema_version=package_schema_version,
            package_digest=package_digest,
            importing_adapter=importing_adapter,
            importing_adapter_version=importing_adapter_version,
            tool_identity=tool_identity,
            model_name=model_name,
            model_revision=model_revision,
            configuration=configuration,
            provenance_status=provenance_status,
            missing_field_warnings=missing_field_warnings,
            steward_attestation=steward_attestation,
            imported_at_us=imported_at_us,
            raw_artifact=raw_artifact,
            items=items,
        )
        digest = calculate_semantic_digest(
            "heritage-proposal-set-v1", cls._semantic_payload(**values)
        )
        return cls._build(**values, semantic_digest=digest)

    @classmethod
    def reconstitute(
        cls,
        *,
        semantic_digest: ContentDigest,
        **supplied_values: object,
    ) -> ASRProposalSet:
        if type(semantic_digest) is not ContentDigest:
            raise ValidationError("semantic_digest must be a ContentDigest")
        values = cls._validated_values(**supplied_values)
        calculated = calculate_semantic_digest(
            "heritage-proposal-set-v1", cls._semantic_payload(**values)
        )
        if calculated != semantic_digest:
            raise ValidationError("proposal-set semantic digest does not match its content")
        return cls._build(**values, semantic_digest=semantic_digest)

    @classmethod
    def _validated_values(cls, **values: object) -> dict[str, object]:
        if type(values["proposal_set_id"]) is not ProposalSetId:
            raise ValidationError("proposal_set_id must be a ProposalSetId")
        if type(values["source_version"]) is not SourceVersionRef:
            raise ValidationError("source_version must be an exact SourceVersionRef")
        if type(values["package_schema_version"]) is not int or values["package_schema_version"] <= 0:
            raise ValidationError("package_schema_version must be a positive integer")
        if type(values["package_digest"]) is not ContentDigest:
            raise ValidationError("package_digest must be a ContentDigest")
        require_canonical_text(values["importing_adapter"], field="importing_adapter", nonempty=True)
        require_canonical_text(
            values["importing_adapter_version"],
            field="importing_adapter_version",
            nonempty=True,
        )
        for field_name, expected in (
            ("tool_identity", IdentityEvidence),
            ("model_name", IdentityEvidence),
            ("model_revision", IdentityEvidence),
            ("configuration", ConfigurationEvidence),
        ):
            if type(values[field_name]) is not expected:
                raise ValidationError(f"{field_name} must be an exact {expected.__name__}")
        if type(values["provenance_status"]) is not ProvenanceStatus:
            raise ValidationError("provenance_status must be a ProvenanceStatus")
        warnings = values["missing_field_warnings"]
        if type(warnings) is not tuple or not all(type(value) is str for value in warnings):
            raise ValidationError("missing_field_warnings must be a tuple of strings")
        for warning in warnings:
            require_canonical_text(warning, field="missing field warning", nonempty=True)
        if values["steward_attestation"] is not None and type(values["steward_attestation"]) is not StewardAttestation:
            raise ValidationError("steward_attestation must be an exact StewardAttestation")
        if type(values["imported_at_us"]) is not int or values["imported_at_us"] <= 0:
            raise ValidationError("imported_at_us must be a positive integer")
        if type(values["raw_artifact"]) is not ArtifactRef:
            raise ValidationError("raw_artifact must be an exact ArtifactRef")
        items = values["items"]
        if type(items) is not tuple or not items or not all(type(item) is ProposalItem for item in items):
            raise ValidationError("items must be a nonempty tuple of ProposalItem")
        source_version = values["source_version"]
        proposal_ids: set[ProposalItemId] = set()
        for item in items:
            if item.source_span.source_version != source_version:
                raise ValidationError("every proposal item must bind the set's exact source version")
            if item.proposal_item_id in proposal_ids:
                raise ValidationError("proposal item identities must be unique within a set")
            proposal_ids.add(item.proposal_item_id)

        provenance_status = values["provenance_status"]
        if provenance_status is ProvenanceStatus.COMPLETE:
            if (
                values["tool_identity"].status is not EvidenceStatus.VERIFIED
                or values["model_revision"].status is not EvidenceStatus.VERIFIED
                or values["model_name"].status is EvidenceStatus.UNKNOWN
            ):
                raise ValidationError(
                    "complete provenance requires verified tool/revision and a known model name"
                )
            if values["configuration"].status is not EvidenceStatus.VERIFIED:
                raise ValidationError("complete provenance requires verified configuration identity")
        elif not warnings or values["steward_attestation"] is None:
            raise ValidationError(
                "legacy-attested provenance requires warnings and steward attestation"
            )
        return values

    @staticmethod
    def _semantic_payload(**values: object) -> dict[str, object]:
        attestation = values["steward_attestation"]
        return {
            "source_version": _source_value(values["source_version"]),
            "package_schema_version": values["package_schema_version"],
            "package_digest": _digest_value(values["package_digest"]),
            "importing_adapter": values["importing_adapter"],
            "importing_adapter_version": values["importing_adapter_version"],
            "tool_identity": _identity_value(values["tool_identity"]),
            "model_name": _identity_value(values["model_name"]),
            "model_revision": _identity_value(values["model_revision"]),
            "configuration": _configuration_value(values["configuration"]),
            "provenance_status": values["provenance_status"].value,
            "missing_field_warnings": list(values["missing_field_warnings"]),
            "steward_attestation": (
                {
                    "actor_id": attestation.actor_id.value,
                    "reason": attestation.reason,
                    "attested_at_us": attestation.attested_at_us,
                    "evidence_digest": _digest_value(attestation.evidence_digest),
                }
                if attestation is not None
                else None
            ),
            "raw_package_digest": _digest_value(values["raw_artifact"].content_digest),
            "items": [_item_value(item) for item in values["items"]],
        }

    @classmethod
    def _build(cls, **values: object) -> ASRProposalSet:
        instance = object.__new__(cls)
        for field_name, value in values.items():
            object.__setattr__(instance, field_name, value)
        return instance

    @property
    def ref(self) -> ProposalSetRef:
        return ProposalSetRef(self.proposal_set_id, self.semantic_digest)

    def pull_events(self) -> tuple[()]:
        """Proposal imports emit no domain fact in this slice."""

        return ()
