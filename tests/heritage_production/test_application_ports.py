"""The application's outbound port surface and its dependency direction."""

from __future__ import annotations

import ast
from pathlib import Path
import sys
import typing
import unittest

from heritage_production.application import ports


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PORTS_ROOT = PROJECT_ROOT / "src" / "heritage_production" / "application" / "ports"

# Design section 10.2 plus the operational ports named in master-plan Task 6.
# A port added or removed without amending the design is a design change, so it
# must break this test.
REPOSITORY_PORTS = {
    "ProductionRepository",
    "ASRProposalSetRepository",
    "TranscriptEditionRepository",
    "ReviewRoundRepository",
    "ReviewFindingRepository",
    "ReleasePolicyVersionRepository",
}
INFRASTRUCTURE_PORTS = {
    "UnitOfWork",
    "ArtifactStore",
    "ArtifactMetadataReader",
    "ArtifactDerivationVerifier",
    "OperationRecorder",
    "DomainEventOutbox",
    "Clock",
    "IdGenerator",
}
ADAPTER_PORTS = {
    "LegacyProposalTranslator",
    "ReviewPackageRenderer",
    "ReviewSubmissionParser",
    "ReleasePackageRenderer",
    "ApprovedReleaseExporter",
    "ActorAuthority",
    "ProcessRunner",
}
OPERATIONAL_PORTS = {
    "BackupService",
    "IntegrityService",
    "MigrationAuthorityRecorder",
    "ReadService",
}
ALL_PORTS = REPOSITORY_PORTS | INFRASTRUCTURE_PORTS | ADAPTER_PORTS | OPERATIONAL_PORTS


def declared_port_names() -> set[str]:
    """Every Protocol class declared under application/ports/."""
    names: set[str] = set()
    for source_file in PORTS_ROOT.rglob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {
                base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
                for base in node.bases
            }
            if "Protocol" in bases:
                names.add(node.name)
    return names


def protocol_members(port: type) -> set[str]:
    """The public members a Protocol declares, on Python 3.11.

    `typing` grew `__protocol_attrs__` in 3.12; the plan pins >=3.11, so the
    members are read off the class body instead.
    """
    return {
        name
        for name, value in vars(port).items()
        if not name.startswith("_") and callable(value)
    }


def imported_module_names(source_file: Path) -> list[str]:
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.append(node.module)
    return names


class PortSurfaceTests(unittest.TestCase):
    def test_exactly_the_approved_ports_are_declared(self) -> None:
        self.assertEqual(declared_port_names(), ALL_PORTS)

    def test_every_port_is_exported_from_the_package_api(self) -> None:
        self.assertEqual(set(ports.__all__), ALL_PORTS)
        for name in ALL_PORTS:
            self.assertTrue(hasattr(ports, name), f"{name} is not exported")

    def test_every_port_is_a_runtime_checkable_protocol(self) -> None:
        """Adapters are structural, so a fake must satisfy isinstance()."""
        for name in sorted(ALL_PORTS):
            with self.subTest(port=name):
                port = getattr(ports, name)
                self.assertTrue(
                    issubclass(type(port), type(typing.Protocol)) or hasattr(port, "_is_protocol"),
                    f"{name} must be a Protocol",
                )
                self.assertTrue(
                    getattr(port, "_is_runtime_protocol", False),
                    f"{name} must be @runtime_checkable",
                )

    def test_exactly_six_repository_ports_exist(self) -> None:
        declared = {name for name in declared_port_names() if name.endswith("Repository")}

        self.assertEqual(declared, REPOSITORY_PORTS)
        self.assertEqual(len(declared), 6)

    def test_sealed_root_repositories_expose_no_mutation_api(self) -> None:
        """Design 11.6: a sealed record has no repository update or delete."""
        sealed = (
            ports.ASRProposalSetRepository,
            ports.TranscriptEditionRepository,
            ports.ReleasePolicyVersionRepository,
        )
        for port in sealed:
            with self.subTest(port=port.__name__):
                self.assertEqual(protocol_members(port), {"add", "get"})

    def test_mutable_root_repositories_require_an_expected_version(self) -> None:
        """Design 9.3: mutable roots use optimistic versions."""
        import inspect

        for port in (ports.ProductionRepository, ports.ReviewRoundRepository):
            with self.subTest(port=port.__name__):
                signature = inspect.signature(port.save)
                self.assertIn("expected_version", signature.parameters)


class PortDependencyDirectionTests(unittest.TestCase):
    def test_ports_import_only_the_standard_library_and_the_domain(self) -> None:
        standard_library = set(sys.stdlib_module_names)
        violations: list[str] = []

        for source_file in PORTS_ROOT.rglob("*.py"):
            for name in imported_module_names(source_file):
                root = name.split(".")[0]
                if root in standard_library or root == "__future__":
                    continue
                if name.startswith("heritage_production.domain"):
                    continue
                if name.startswith("heritage_production.application"):
                    continue
                violations.append(f"{source_file.relative_to(PROJECT_ROOT)} -> {name}")

        self.assertEqual(violations, [])

    def test_ports_never_reach_infrastructure_or_presentation(self) -> None:
        violations: list[str] = []

        for source_file in PORTS_ROOT.rglob("*.py"):
            for name in imported_module_names(source_file):
                if name.startswith(
                    ("heritage_production.infrastructure", "heritage_production.presentation")
                ):
                    violations.append(f"{source_file.relative_to(PROJECT_ROOT)} -> {name}")

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
