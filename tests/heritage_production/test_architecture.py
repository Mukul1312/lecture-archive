"""Architecture firewall checks based on parsed package imports."""

from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "heritage_production"
LAYERS = {
    "domain": 0,
    "application": 1,
    "infrastructure": 2,
    "presentation": 3,
}
REPOSITORY_PORTS = {
    "ProductionRepository",
    "ASRProposalSetRepository",
    "TranscriptEditionRepository",
    "ReviewRoundRepository",
    "ReviewFindingRepository",
    "ReleasePolicyVersionRepository",
}
FORBIDDEN_LEGACY_ROOTS = {"scripts", "voice_lab", "youtube_enhance"}


def python_modules() -> list[tuple[Path, tuple[str, ...]]]:
    modules: list[tuple[Path, tuple[str, ...]]] = []
    for source_file in PACKAGE_ROOT.rglob("*.py"):
        relative_parts = source_file.relative_to(PACKAGE_ROOT).with_suffix("").parts
        module_parts = relative_parts[:-1] if relative_parts[-1] == "__init__" else relative_parts
        modules.append((source_file, ("heritage_production", *module_parts)))
    return modules


def imported_modules(source_file: Path, module: tuple[str, ...]) -> list[tuple[str, ...]]:
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    imports: list[tuple[str, ...]] = []
    package = module[:-1] if source_file.name != "__init__.py" else module

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(tuple(alias.name.split(".")) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = tuple(node.module.split(".")) if node.module else ()
            if node.level:
                if node.level > len(package):
                    continue
                base = (*package[: len(package) - node.level + 1], *base)
            imports.append(base)
    return imports


def layer_for(module: tuple[str, ...]) -> str | None:
    if len(module) >= 2 and module[0] == "heritage_production":
        return module[1]
    return None


def repository_port_names() -> set[str]:
    repositories = PACKAGE_ROOT / "application" / "ports" / "repositories.py"
    if not repositories.exists():
        return set()
    tree = ast.parse(repositories.read_text(encoding="utf-8"), filename=str(repositories))
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name.endswith("Repository")
    }


def presentation_repository_imports(source_file: Path) -> list[str]:
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            violations.extend(
                alias.name for alias in node.names if "repository" in alias.name.lower()
            )
        elif isinstance(node, ast.ImportFrom):
            if node.module and "repository" in node.module.lower():
                violations.append(node.module)
            violations.extend(
                alias.name for alias in node.names if "repository" in alias.name.lower()
            )
    return violations


class ArchitectureFirewallTests(unittest.TestCase):
    def test_domain_uses_only_standard_library_imports(self) -> None:
        standard_library = set(sys.stdlib_module_names)
        violations: list[str] = []

        for source_file, module in python_modules():
            if layer_for(module) != "domain":
                continue
            for imported in imported_modules(source_file, module):
                if imported and imported[0] not in standard_library and imported[0] != "__future__":
                    violations.append(f"{source_file.relative_to(PROJECT_ROOT)} -> {'.'.join(imported)}")

        self.assertEqual(violations, [])

    def test_layers_do_not_import_outward(self) -> None:
        violations: list[str] = []

        for source_file, module in python_modules():
            source_layer = layer_for(module)
            if source_layer not in LAYERS:
                continue
            for imported in imported_modules(source_file, module):
                target_layer = layer_for(imported)
                if target_layer in LAYERS and LAYERS[target_layer] > LAYERS[source_layer]:
                    violations.append(
                        f"{source_file.relative_to(PROJECT_ROOT)} -> {'.'.join(imported)}"
                    )

        self.assertEqual(violations, [])

    def test_presentation_never_imports_repositories(self) -> None:
        violations: list[str] = []

        for source_file, module in python_modules():
            if layer_for(module) != "presentation":
                continue
            for imported in presentation_repository_imports(source_file):
                violations.append(f"{source_file.relative_to(PROJECT_ROOT)} -> {imported}")

        self.assertEqual(violations, [])

    def test_package_never_imports_legacy_or_enhancement_modules(self) -> None:
        violations: list[str] = []

        for source_file, module in python_modules():
            for imported in imported_modules(source_file, module):
                if imported and imported[0] in FORBIDDEN_LEGACY_ROOTS:
                    violations.append(f"{source_file.relative_to(PROJECT_ROOT)} -> {'.'.join(imported)}")

        self.assertEqual(violations, [])

    def test_repository_ports_are_empty_until_task_six_then_match_the_allowlist(self) -> None:
        actual_ports = repository_port_names()
        self.assertIn(actual_ports, (set(), REPOSITORY_PORTS))
