"""ImportProposalPackage — the anti-corruption boundary of design 10.4.

The happy path is the least interesting part. What matters is that a legacy
package's claims about itself are treated as evidence and never as authority:
a quarantined import creates nothing, an adapter that is not the declared one
is refused, and a translation of some other package is refused. Each of those
is a way a real legacy export can be wrong.
"""

from __future__ import annotations

import dataclasses
import unittest

from heritage_production.application import commands
from heritage_production.application.errors import (
    OperationConflictError,
    ReplayIntegrityError,
)
from heritage_production.application.idempotency import command_result_digest
from heritage_production.application.ports.adapters import TranslatedProposal
from heritage_production.domain.shared import (
    ActorId,
    ArtifactId,
    ContentDigest,
    PolicyRefusalError,
    OperationId,
    ProposalItemId,
    ProposalSetId,
    SourceSpan,
    TranscriptText,
    StaleReferenceError,
    ValidationError,
)
from heritage_production.domain.transcription import (
    ConfigurationEvidence,
    ConfidenceEvidence,
    EvidenceStatus,
    IdentityEvidence,
    ProposalItem,
    ProvenanceStatus,
    RawRowLocator,
    StewardAttestation,
)

from tests.heritage_production.application_harness import ApplicationHarness
from tests.heritage_production.heritage_release_fixtures import uid
from tests.heritage_production.test_transcription_proposals import SOURCE


PACKAGE_BYTES = b'{"segments":[{"start":0,"end":10000,"text":"Namaste"}]}'
CONFIG_DIGEST = ContentDigest("sha256", "c" * 64)


def proposal_item(identifier: int = 800) -> ProposalItem:
    return ProposalItem(
        proposal_item_id=ProposalItemId(uid(identifier)),
        source_span=SourceSpan(SOURCE, 0, 10_000),
        proposed_text=TranscriptText("Namaste"),
        language="sa",
        speaker_hypothesis="speaker-1",
        confidence_evidence=(ConfidenceEvidence("posterior", "0.98"),),
        raw_row_locator=RawRowLocator("segments.jsonl#row=1"),
    )


def complete_translation(raw_package, **overrides) -> TranslatedProposal:
    values = dict(
        raw_package=raw_package,
        package_schema_version=1,
        tool_identity=IdentityEvidence(EvidenceStatus.VERIFIED, "whisper.cpp"),
        model_name=IdentityEvidence(EvidenceStatus.VERIFIED, "large-v3"),
        model_revision=IdentityEvidence(EvidenceStatus.VERIFIED, "model-sha-1"),
        configuration=ConfigurationEvidence(EvidenceStatus.VERIFIED, CONFIG_DIGEST),
        provenance_status=ProvenanceStatus.COMPLETE,
        missing_field_warnings=(),
        items=(proposal_item(),),
        quarantined=False,
        quarantine_reason=None,
    )
    values.update(overrides)
    return TranslatedProposal(**values)  # type: ignore[arg-type]


def legacy_translation(raw_package, **overrides) -> TranslatedProposal:
    """The pilot's shape: observed model name, no pinned revision, warnings.

    Design 10.4 is explicit that the observed model name `small` must not
    become a pinned revision, so this keeps the distinction the evidence
    statuses exist to carry.
    """
    return complete_translation(
        raw_package,
        model_name=IdentityEvidence(EvidenceStatus.OBSERVED, "small"),
        model_revision=IdentityEvidence(EvidenceStatus.UNKNOWN, None),
        configuration=ConfigurationEvidence(EvidenceStatus.UNKNOWN, None),
        provenance_status=ProvenanceStatus.LEGACY_ATTESTED,
        missing_field_warnings=(
            "asr-full.metadata.json declares an absolute audio locator",
            "no pinned model revision is recorded",
        ),
        **overrides,
    )


def attestation() -> StewardAttestation:
    return StewardAttestation(
        ActorId(uid(20)),
        "Legacy export predates model pinning; source bound by the steward",
        1_700_000_000_000_000,
        ContentDigest("sha256", "d" * 64),
    )


class Fixture:
    def __init__(self) -> None:
        self.harness = ApplicationHarness()
        self.package = self.harness.artifacts.seed(
            ArtifactId(uid(310)), PACKAGE_BYTES
        )
        self.harness.translator.result = complete_translation(self.package)

    def legacy(self) -> None:
        self.harness.translator.result = legacy_translation(self.package)


class ImportProposalPackageTests(unittest.TestCase):
    def test_it_seals_a_proposal_set_bound_to_the_supplied_source(self) -> None:
        fixture = Fixture()

        outcome = fixture.harness.import_package(fixture.package, SOURCE)

        stored = fixture.harness.proposals.get(ProposalSetId(uid(760)))
        self.assertIs(outcome.result, stored)
        self.assertEqual(stored.source_version, SOURCE)
        self.assertEqual(stored.raw_artifact, fixture.package)
        self.assertEqual(stored.package_digest, fixture.package.content_digest)

    def test_the_declared_adapter_is_recorded_on_the_sealed_set(self) -> None:
        fixture = Fixture()

        outcome = fixture.harness.import_package(fixture.package, SOURCE)

        self.assertEqual(outcome.result.importing_adapter, "whisper-package")
        self.assertEqual(outcome.result.importing_adapter_version, "1.0.0")

    def test_the_translator_is_given_the_operator_supplied_source(self) -> None:
        """Design 10.4: the package's own idea of its audio is not authority."""
        fixture = Fixture()

        fixture.harness.import_package(fixture.package, SOURCE)

        (raw_package, import_root, bound_source) = fixture.harness.translator.calls[0]
        self.assertEqual(raw_package, fixture.package)
        self.assertEqual(import_root, "data/imports/1985-08-21")
        self.assertEqual(bound_source, SOURCE)

    def test_a_sealed_root_publishes_no_events(self) -> None:
        fixture = Fixture()

        fixture.harness.import_package(fixture.package, SOURCE)

        self.assertEqual(fixture.harness.events.events, [])

    def test_the_payload_pins_the_content_digest(self) -> None:
        fixture = Fixture()

        outcome = fixture.harness.import_package(fixture.package, SOURCE)

        self.assertEqual(
            outcome.record.result_payload,
            {
                "proposal_set_id": uid(760),
                "content_digest": outcome.result.semantic_digest.hex_digest,
                "provenance_status": "complete",
                "item_count": 1,
                "warning_count": 0,
            },
        )

    def test_a_replay_returns_the_original_sealed_set(self) -> None:
        fixture = Fixture()
        first = fixture.harness.import_package(fixture.package, SOURCE)

        again = fixture.harness.import_package(fixture.package, SOURCE)

        self.assertTrue(again.replayed)
        self.assertIs(again.result, first.result)
        self.assertEqual(len(fixture.harness.proposals.rows), 1)

    def test_a_replay_retranslates_nothing(self) -> None:
        fixture = Fixture()
        fixture.harness.import_package(fixture.package, SOURCE)

        fixture.harness.import_package(fixture.package, SOURCE)

        self.assertEqual(len(fixture.harness.translator.calls), 1)

    def test_a_changed_import_root_under_one_operation_id_conflicts(self) -> None:
        fixture = Fixture()
        fixture.harness.import_package(fixture.package, SOURCE)

        with self.assertRaises(OperationConflictError):
            fixture.harness.import_package(
                fixture.package, SOURCE, import_root="data/imports/elsewhere"
            )

    def test_a_changed_adapter_version_under_one_operation_id_conflicts(self) -> None:
        """Design 9.4 puts adapter version in the key, so this is not a replay."""
        fixture = Fixture()
        fixture.harness.import_package(fixture.package, SOURCE)
        fixture.harness.translator._identity = type(
            fixture.harness.translator.identity()
        )("whisper-package", "2.0.0")

        with self.assertRaises(OperationConflictError):
            fixture.harness.import_package(
                fixture.package, SOURCE, importing_adapter_version="2.0.0"
            )


class ImportRefusalTests(unittest.TestCase):
    def test_a_quarantined_package_creates_nothing(self) -> None:
        """Design 10.4 has no ProvenanceStatus for quarantined, so nothing is sealed."""
        fixture = Fixture()
        fixture.harness.translator.result = complete_translation(
            fixture.package,
            quarantined=True,
            quarantine_reason="no independently bound source was supplied",
        )

        with self.assertRaises(PolicyRefusalError):
            fixture.harness.import_package(fixture.package, SOURCE)

        self.assertEqual(fixture.harness.proposals.rows, {})
        self.assertEqual(fixture.harness.recorder.records, {})
        self.assertEqual([u for u in fixture.harness.units if u.entered], [])

    def test_an_undeclared_adapter_is_refused(self) -> None:
        fixture = Fixture()

        with self.assertRaises(StaleReferenceError):
            fixture.harness.import_package(
                fixture.package, SOURCE, importing_adapter="some-other-tool"
            )

        self.assertEqual(fixture.harness.proposals.rows, {})
        self.assertEqual(fixture.harness.translator.calls, [])

    def test_an_undeclared_adapter_version_is_refused(self) -> None:
        fixture = Fixture()

        with self.assertRaises(StaleReferenceError):
            fixture.harness.import_package(
                fixture.package, SOURCE, importing_adapter_version="9.9.9"
            )

        self.assertEqual(fixture.harness.translator.calls, [])

    def test_a_translation_of_another_package_is_refused(self) -> None:
        fixture = Fixture()
        other = fixture.harness.artifacts.seed(ArtifactId(uid(311)), b"other bytes")
        fixture.harness.translator.result = complete_translation(other)

        with self.assertRaises(ValidationError):
            fixture.harness.import_package(fixture.package, SOURCE)

        self.assertEqual(fixture.harness.proposals.rows, {})
        self.assertEqual(fixture.harness.recorder.records, {})

    def test_a_package_absent_from_the_store_is_refused(self) -> None:
        fixture = Fixture()
        unstored = type(fixture.package)(
            ArtifactId(uid(399)),
            ContentDigest.from_bytes(b"never stored"),
            12,
            "application/json",
        )

        with self.assertRaises(StaleReferenceError):
            fixture.harness.import_package(unstored, SOURCE)

        self.assertEqual(fixture.harness.translator.calls, [])

    def test_bytes_that_no_longer_match_the_package_digest_are_refused(self) -> None:
        fixture = Fixture()
        fixture.harness.artifacts.corrupt(fixture.package, b"tampered")

        with self.assertRaises(StaleReferenceError):
            fixture.harness.import_package(fixture.package, SOURCE)

        self.assertEqual(fixture.harness.proposals.rows, {})


class LegacyProvenanceTests(unittest.TestCase):
    """The pilot's actual shape: attested, not complete."""

    def test_a_legacy_import_keeps_its_unknowns_and_warnings(self) -> None:
        fixture = Fixture()
        fixture.legacy()

        outcome = fixture.harness.import_package(
            fixture.package, SOURCE, steward_attestation=attestation()
        )

        self.assertEqual(
            outcome.result.provenance_status, ProvenanceStatus.LEGACY_ATTESTED
        )
        self.assertEqual(outcome.result.model_name.status, EvidenceStatus.OBSERVED)
        self.assertEqual(outcome.result.model_name.value, "small")
        self.assertEqual(outcome.result.model_revision.status, EvidenceStatus.UNKNOWN)
        self.assertEqual(len(outcome.result.missing_field_warnings), 2)

    def test_an_observed_model_name_never_becomes_a_pinned_revision(self) -> None:
        """Design 10.4 names this exact inference as forbidden."""
        fixture = Fixture()
        fixture.legacy()

        outcome = fixture.harness.import_package(
            fixture.package, SOURCE, steward_attestation=attestation()
        )

        self.assertIsNone(outcome.result.model_revision.value)

    def test_a_legacy_import_without_a_steward_attestation_is_refused(self) -> None:
        """The domain requires the steward's evidence for an attested import."""
        fixture = Fixture()
        fixture.legacy()

        with self.assertRaises(ValidationError):
            fixture.harness.import_package(fixture.package, SOURCE)

        self.assertEqual(fixture.harness.proposals.rows, {})
        self.assertEqual(fixture.harness.recorder.records, {})

    def test_the_payload_reports_attested_provenance(self) -> None:
        fixture = Fixture()
        fixture.legacy()

        outcome = fixture.harness.import_package(
            fixture.package, SOURCE, steward_attestation=attestation()
        )

        self.assertEqual(
            outcome.record.result_payload["provenance_status"], "legacy_attested"
        )
        self.assertEqual(outcome.record.result_payload["warning_count"], 2)


class ReplaySteeringTests(unittest.TestCase):
    """A stored payload must not choose which root a replay loads.

    Re-digesting a rewritten payload keeps the record self-consistent, so the
    earlier guards pass. Loading by the identity the *command* declares -- a
    value the verified input digest already covers -- is what stops a payload
    with storage access from choosing the answer.
    """

    def test_a_tampered_payload_cannot_redirect_the_reload(self) -> None:
        fixture = Fixture()
        first = fixture.harness.import_package(fixture.package, SOURCE)
        other_package = fixture.harness.artifacts.seed(
            ArtifactId(uid(313)), b"a second package"
        )
        fixture.harness.translator.result = complete_translation(other_package)
        other = fixture.harness.import_package(
            other_package, SOURCE, proposal_suffix=762, suffix=24
        ).result
        fixture.harness.translator.result = complete_translation(fixture.package)

        command = commands.ImportProposalPackage(
            operation_id=OperationId(uid(20)),
            actor=fixture.harness.context(),
            proposal_set_id=ProposalSetId(uid(760)),
            source_version=SOURCE,
            raw_package=fixture.package,
            import_root="data/imports/1985-08-21",
            importing_adapter="whisper-package",
            importing_adapter_version="1.0.0",
        )
        forged = dict(first.record.result_payload)
        forged["proposal_set_id"] = other.proposal_set_id.value
        forged["content_digest"] = other.semantic_digest.hex_digest
        fixture.harness.recorder.records[command.operation_id] = dataclasses.replace(
            first.record,
            result_payload=forged,
            result_digest=command_result_digest(command, forged),
        )

        with self.assertRaises(ReplayIntegrityError):
            fixture.harness.import_package(fixture.package, SOURCE)


class ImportProposalPackageCommandTests(unittest.TestCase):
    """The declared adapter is part of the idempotency key (design 9.4).

    A key field that accepts empty text is not a key, so the DTO refuses one
    rather than leaving the handler's comparison to carry the whole weight.

    Whitespace-only text is *not* refused: `require_canonical_text` treats it
    as nonempty, and that is a shared rule used across Tasks 2-5. Asserting
    otherwise here would assert a rule the codebase does not have.
    """

    def fields(self, harness: ApplicationHarness, package) -> dict:
        return {
            "operation_id": OperationId(uid(20)),
            "actor": harness.context(),
            "proposal_set_id": ProposalSetId(uid(760)),
            "source_version": SOURCE,
            "raw_package": package,
            "import_root": "data/imports/1985-08-21",
            "importing_adapter": "whisper-package",
            "importing_adapter_version": "1.0.0",
        }

    def test_the_declared_adapter_must_be_canonical_nonempty_text(self) -> None:
        fixture = Fixture()
        base = self.fields(fixture.harness, fixture.package)

        for field in ("importing_adapter", "importing_adapter_version"):
            for bad in ("", "with\rreturn", None, 7):
                with self.subTest(field=field, value=bad):
                    with self.assertRaises(ValidationError):
                        commands.ImportProposalPackage(**{**base, field: bad})

    def test_a_steward_attestation_must_be_exact_when_present(self) -> None:
        fixture = Fixture()
        base = self.fields(fixture.harness, fixture.package)

        for bad in ("attested", ActorId(uid(20)), 7):
            with self.subTest(attestation=bad):
                with self.assertRaises(ValidationError):
                    commands.ImportProposalPackage(
                        **base, steward_attestation=bad
                    )

    def test_omitting_the_attestation_is_allowed(self) -> None:
        """A complete-provenance import needs no steward evidence."""
        fixture = Fixture()

        command = commands.ImportProposalPackage(
            **self.fields(fixture.harness, fixture.package)
        )

        self.assertIsNone(command.steward_attestation)


if __name__ == "__main__":
    unittest.main()
