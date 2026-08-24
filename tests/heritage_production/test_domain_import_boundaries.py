"""Cross-module import direction for the Production and Release domains.

Production stores Release-owned candidate/assessment values, while the pure
evaluator reads Production-owned gates and sign-offs. The two packages must
therefore import each other's submodules only, never each other's package API,
and must import cleanly in either order.
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

    def test_cross_package_imports_name_submodules_never_the_package_api(self) -> None:
        violations: list[str] = []
        pairs = (
            ("production", "heritage_production.domain.release"),
            ("release", "heritage_production.domain.production"),
        )

        for package, foreign_package in pairs:
            for source_file in (PACKAGE_ROOT / "domain" / package).rglob("*.py"):
                for name in imported_module_names(source_file):
                    if name == foreign_package:
                        violations.append(
                            f"{source_file.relative_to(PROJECT_ROOT)} -> {name}"
                        )

        self.assertEqual(
            violations,
            [],
            "importing the foreign package API would create an import cycle",
        )

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
