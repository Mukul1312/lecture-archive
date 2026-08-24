"""Cross-module import direction for the Production and Release domains.

Release *defines* the gate, candidate, and eligibility concepts; Production
*stores* them and is the only aggregate that mutates them. The dependency spine
is therefore strictly one-way:

    presentation -> production -> release -> (review, transcription) -> shared

Release must not import Production at all -- not its package API and not its
submodules -- so no semantic cycle can exist between the two modules.
"""

from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "heritage_production"


def imported_module_names(source_file: Path) -> list[str]:
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
    return names


def run_import(statement: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", statement],
        capture_output=True,
        text=True,
        env={
            "PYTHONPATH": str(PROJECT_ROOT / "src"),
            "PATH": "",
            "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
        },
        check=False,
    )


class DomainImportBoundaryTests(unittest.TestCase):
    def test_review_and_transcription_never_import_production_or_release(self) -> None:
        violations: list[str] = []

        for package in ("review", "transcription"):
            for source_file in (PACKAGE_ROOT / "domain" / package).rglob("*.py"):
                for name in imported_module_names(source_file):
                    if name.startswith(
                        ("heritage_production.domain.production", "heritage_production.domain.release")
                    ):
                        violations.append(
                            f"{source_file.relative_to(PROJECT_ROOT)} -> {name}"
                        )

        self.assertEqual(violations, [])

    def test_release_never_imports_production_in_any_form(self) -> None:
        """The spine is one-way: nothing under release may reach into production."""
        violations: list[str] = []

        for source_file in (PACKAGE_ROOT / "domain" / "release").rglob("*.py"):
            for name in imported_module_names(source_file):
                if name.startswith("heritage_production.domain.production"):
                    violations.append(
                        f"{source_file.relative_to(PROJECT_ROOT)} -> {name}"
                    )

        self.assertEqual(
            violations,
            [],
            "a release -> production import would reintroduce the module cycle",
        )

    def test_production_imports_release_submodules_never_its_package_api(self) -> None:
        violations: list[str] = []

        for source_file in (PACKAGE_ROOT / "domain" / "production").rglob("*.py"):
            for name in imported_module_names(source_file):
                if name == "heritage_production.domain.release":
                    violations.append(
                        f"{source_file.relative_to(PROJECT_ROOT)} -> {name}"
                    )

        self.assertEqual(
            violations,
            [],
            "production must name exact release submodules, not the package facade",
        )

    def test_no_import_cycle_exists_among_the_domain_modules(self) -> None:
        """Walk the real intra-domain import graph and prove it is acyclic."""
        graph: dict[str, set[str]] = {}
        for source_file in (PACKAGE_ROOT / "domain").rglob("*.py"):
            relative = source_file.relative_to(PACKAGE_ROOT).with_suffix("")
            parts = relative.parts
            module = "heritage_production.domain." + ".".join(
                parts[1:-1] if parts[-1] == "__init__" else parts[1:]
            )
            module = module.rstrip(".")
            targets = {
                name
                for name in imported_module_names(source_file)
                if name.startswith("heritage_production.domain")
            }
            graph.setdefault(module, set()).update(targets - {module})

        visiting: set[str] = set()
        done: set[str] = set()
        cycles: list[str] = []

        def walk(node: str, trail: tuple[str, ...]) -> None:
            if node in done:
                return
            if node in visiting:
                cycles.append(" -> ".join((*trail, node)))
                return
            visiting.add(node)
            for target in sorted(graph.get(node, ())):
                walk(target, (*trail, node))
            visiting.discard(node)
            done.add(node)

        for node in sorted(graph):
            walk(node, ())

        self.assertEqual(cycles, [])

    def test_both_domain_packages_import_cleanly_in_either_order(self) -> None:
        for first, second in (
            ("production", "release"),
            ("release", "production"),
        ):
            with self.subTest(order=f"{first} then {second}"):
                result = run_import(
                    f"import heritage_production.domain.{first} as a; "
                    f"import heritage_production.domain.{second} as b; "
                    "assert a.__all__ and b.__all__; print('ok')"
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    f"import order {first} then {second} failed: {result.stderr}",
                )
                self.assertIn("ok", result.stdout)

    def test_the_production_and_release_domains_stay_standard_library_only(self) -> None:
        standard_library = set(sys.stdlib_module_names)
        violations: list[str] = []

        for package in ("production", "release"):
            for source_file in (PACKAGE_ROOT / "domain" / package).rglob("*.py"):
                for name in imported_module_names(source_file):
                    root = name.split(".")[0]
                    if root in standard_library or root == "__future__":
                        continue
                    if name.startswith("heritage_production.domain"):
                        continue
                    violations.append(f"{source_file.relative_to(PROJECT_ROOT)} -> {name}")

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
