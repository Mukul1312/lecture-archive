"""One wired application for the handler tests.

Every handler checkpoint needs the same assembly -- repositories, recorder,
outbox, clock, ids -- so it lives here rather than being rebuilt per module.
`durable()` is the snapshot the "nothing changed" assertions compare, and it
covers all three durable stores, because a handler that leaves an orphan
event or an orphan record has still broken design 9.4.
"""

from __future__ import annotations

from heritage_production.application import commands
from heritage_production.application.handlers import (
    ProductionCommandHandlers,
    RegistrationCommandHandlers,
    TranscriptionCommandHandlers,
)
from heritage_production.domain.production import AttachedSource, EditionSelection
from heritage_production.domain.release import ReleasePolicyRules
from heritage_production.domain.shared import (
    ArtifactId,
    ArtifactRef,
    ExternalGateSetId,
    OperationId,
    ProductionId,
    ProposalSetId,
    ReleasePolicyVersionId,
    RubricId,
    SourceRecordingRef,
    SourceVersionRef,
    TranscriptEditionId,
)

from tests.heritage_production.application_fakes import (
    FakeASRProposalSetRepository,
    FakeArtifactStore,
    FakeClock,
    FakeDatabase,
    FakeDomainEventOutbox,
    FakeIdGenerator,
    FakeLegacyProposalTranslator,
    FakeOperationRecorder,
    FakeProductionRepository,
    FakeReleasePolicyVersionRepository,
    FakeTranscriptEditionRepository,
    FakeUnitOfWork,
)
from tests.heritage_production.heritage_release_fixtures import actor, uid


STEWARD = actor(20)


def empty_rules() -> ReleasePolicyRules:
    """The explicitly empty rule set design 9.2 calls a valid configuration."""
    return ReleasePolicyRules(
        required_integrity_checks=(),
        uncertainty_allowances=(),
        blocking_finding_rules=(),
        review_coverage_requirements=(),
        review_signoff_requirements=(),
        external_signoff_requirements=(),
        required_release_members=(),
        maximum_unresolved_findings=0,
    )


def attached_for(version: SourceVersionRef, *, artifact_suffix: int = 200) -> AttachedSource:
    """An attachment whose artifact matches the version's declared digest.

    `AttachedSource` requires the two to agree, so the artifact is built from
    the version rather than chosen independently.
    """
    return AttachedSource(
        SourceRecordingRef(version.source_recording_id, {"title": "SSGGSM 1985-08-21"}),
        version,
        ArtifactRef(
            ArtifactId(uid(artifact_suffix)), version.artifact_digest, 4096, "audio/mpeg"
        ),
        STEWARD,
        1_700_000_000_000_000,
    )


class ApplicationHarness:
    def __init__(self) -> None:
        self.database = FakeDatabase()
        self.productions = FakeProductionRepository(self.database)
        self.editions = FakeTranscriptEditionRepository(self.database)
        self.policies = FakeReleasePolicyVersionRepository(self.database)
        self.recorder = FakeOperationRecorder(self.database)
        self.artifacts = FakeArtifactStore()
        self.proposals = FakeASRProposalSetRepository(self.database)
        self.translator = FakeLegacyProposalTranslator()
        self.events = FakeDomainEventOutbox(self.database)
        self.clock = FakeClock()
        self.ids = FakeIdGenerator()
        self.units: list = []
        # Raised instead of committing, to model an I/O failure at commit.
        self.commit_failure: Exception | None = None
        self.handlers = ProductionCommandHandlers(
            productions=self.productions,
            editions=self.editions,
            policies=self.policies,
            transactions=lambda: self.begin(),
            recorder=self.recorder,
            events=self.events,
            clock=self.clock,
            ids=self.ids,
        )
        self.transcription = TranscriptionCommandHandlers(
            proposals=self.proposals,
            editions=self.editions,
            productions=self.productions,
            artifacts=self.artifacts,
            translator=self.translator,
            transactions=lambda: self.begin(),
            recorder=self.recorder,
            events=self.events,
            clock=self.clock,
            ids=self.ids,
        )
        self.registrations = RegistrationCommandHandlers(
            artifacts=self.artifacts,
            transactions=lambda: self.begin(),
            recorder=self.recorder,
            clock=self.clock,
        )

    def begin(self) -> FakeUnitOfWork:
        unit = FakeUnitOfWork(self.database)
        unit.commit_failure = self.commit_failure
        self.units.append(unit)
        return unit

    def durable(self) -> tuple:
        return (
            dict(self.productions.rows),
            dict(self.recorder.records),
            list(self.events.events),
        )

    def context(self) -> commands.ActorContext:
        return commands.ActorContext(STEWARD)

    # --- seeding, outside any command ------------------------------------

    def store_edition(self, edition) -> None:
        """Place a sealed edition in storage without going through a command."""
        with self.begin() as unit:
            self.editions.add(edition)
            unit.commit()

    def store_policy(self, policy) -> None:
        with self.begin() as unit:
            self.policies.add(policy)
            unit.commit()

    # --- commands ---------------------------------------------------------

    def create(self, suffix: int = 1, deliverable: str = "August 21 listening transcript"):
        return self.handlers.create_production(
            commands.CreateProduction(
                operation_id=OperationId(uid(suffix)),
                actor=self.context(),
                intended_deliverable=deliverable,
            )
        )

    def attach(
        self,
        production_id: ProductionId,
        version: SourceVersionRef,
        *,
        suffix: int = 2,
        expected_version: int = 1,
        attached_source: AttachedSource | None = None,
    ):
        return self.handlers.attach_source_recording(
            commands.AttachSourceRecording(
                operation_id=OperationId(uid(suffix)),
                actor=self.context(),
                production_id=production_id,
                attached_source=attached_source or attached_for(version),
                expected_version=expected_version,
            )
        )

    def select_edition(
        self,
        production_id: ProductionId,
        selection: EditionSelection,
        *,
        suffix: int = 4,
        expected_version: int = 2,
    ):
        return self.handlers.select_candidate_edition(
            commands.SelectCandidateEdition(
                operation_id=OperationId(uid(suffix)),
                actor=self.context(),
                production_id=production_id,
                edition_selection=selection,
                expected_version=expected_version,
            )
        )

    def configure_gates(
        self,
        production_id: ProductionId,
        requirements: tuple,
        *,
        gate_set_suffix: int = 700,
        suffix: int = 6,
        expected_version: int = 3,
    ):
        return self.handlers.configure_external_gates(
            commands.ConfigureExternalGates(
                operation_id=OperationId(uid(suffix)),
                actor=self.context(),
                production_id=production_id,
                external_gate_set_id=ExternalGateSetId(uid(gate_set_suffix)),
                requirements=requirements,
                expected_version=expected_version,
            )
        )

    def create_policy(
        self,
        *,
        policy_suffix: int = 720,
        suffix: int = 7,
        rules=None,
        semantic_label: str = "pilot-transcript-policy",
    ):
        from heritage_production.domain.release import SUPPORTED_EVALUATOR_REF

        return self.handlers.create_release_policy_version(
            commands.CreateReleasePolicyVersion(
                operation_id=OperationId(uid(suffix)),
                actor=self.context(),
                release_policy_version_id=ReleasePolicyVersionId(uid(policy_suffix)),
                semantic_label=semantic_label,
                policy_schema_version=1,
                policy_schema_code="heritage-transcript-policy-v1",
                evaluator_ref=SUPPORTED_EVALUATOR_REF,
                rules=rules if rules is not None else empty_rules(),
            )
        )

    def register_rubric(
        self,
        content: ArtifactRef,
        *,
        rubric_suffix: int = 740,
        schema_version: int = 1,
        suffix: int = 12,
    ):
        return self.registrations.register_rubric(
            commands.RegisterRubric(
                operation_id=OperationId(uid(suffix)),
                actor=self.context(),
                rubric_id=RubricId(uid(rubric_suffix)),
                schema_version=schema_version,
                content=content,
            )
        )

    def register_credential(self, credential, *, suffix: int = 13):
        return self.registrations.register_actor_credential(
            commands.RegisterActorCredential(
                operation_id=OperationId(uid(suffix)),
                actor=self.context(),
                credential=credential,
            )
        )

    def import_package(
        self,
        raw_package,
        source_version,
        *,
        proposal_suffix: int = 760,
        suffix: int = 20,
        import_root: str = "data/imports/1985-08-21",
        importing_adapter: str = "whisper-package",
        importing_adapter_version: str = "1.0.0",
        steward_attestation=None,
    ):
        return self.transcription.import_proposal_package(
            commands.ImportProposalPackage(
                operation_id=OperationId(uid(suffix)),
                actor=self.context(),
                proposal_set_id=ProposalSetId(uid(proposal_suffix)),
                source_version=source_version,
                raw_package=raw_package,
                import_root=import_root,
                importing_adapter=importing_adapter,
                importing_adapter_version=importing_adapter_version,
                steward_attestation=steward_attestation,
            )
        )

    def create_initial_edition(
        self,
        production_id: ProductionId,
        *,
        edition_suffix: int = 780,
        suffix: int = 21,
        source_versions=(),
        transcript_scope=None,
        proposal_set_refs=(),
        revisions=(),
        gaps=(),
        change_manifest=None,
    ):
        return self.transcription.create_initial_transcript_edition(
            commands.CreateInitialTranscriptEdition(
                operation_id=OperationId(uid(suffix)),
                actor=self.context(),
                production_id=production_id,
                transcript_edition_id=TranscriptEditionId(uid(edition_suffix)),
                source_versions=source_versions,
                transcript_scope=transcript_scope,
                proposal_set_refs=proposal_set_refs,
                revisions=revisions,
                gaps=gaps,
                change_manifest=change_manifest,
            )
        )

    def select_policy(
        self,
        production_id: ProductionId,
        policy_ref,
        *,
        suffix: int = 5,
        expected_version: int = 3,
    ):
        return self.handlers.select_release_policy_version(
            commands.SelectReleasePolicyVersion(
                operation_id=OperationId(uid(suffix)),
                actor=self.context(),
                production_id=production_id,
                policy_ref=policy_ref,
                expected_version=expected_version,
            )
        )
