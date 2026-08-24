"""Behavioural tests for package metadata and the thin CLI seam."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))
loaded_test_package = sys.modules.get("heritage_production")
if loaded_test_package is not None:
    loaded_test_package.__path__.append(str(SOURCE_ROOT / "heritage_production"))
COMMAND_GROUPS = {
    "production",
    "source",
    "proposal",
    "edition",
    "actor",
    "rubric",
    "policy",
    "gates",
    "review",
    "finding",
    "release",
    "authority",
    "operation",
    "integrity",
    "quarantine",
    "outbox",
    "backup",
    "restore",
}


class PackagingTests(unittest.TestCase):
    def test_project_metadata_declares_the_isolated_package_contract(self) -> None:
        with (PROJECT_ROOT / "pyproject.toml").open("rb") as project_file:
            project = tomllib.load(project_file)

        metadata = project["project"]
        self.assertEqual(metadata["name"], "heritage-production")
        self.assertEqual(metadata["requires-python"], ">=3.11")
        self.assertEqual(metadata["dependencies"], ["cryptography==50.0.0"])
        self.assertEqual(
            metadata["optional-dependencies"]["dev"],
            ["hypothesis==6.165.10", "rfc8785==0.1.4", "build==1.5.0"],
        )
        self.assertEqual(
            metadata["scripts"]["heritage-production"],
            "heritage_production.presentation.cli.main:main",
        )

    def test_heritage_lock_contains_exact_direct_and_transitive_dependencies(self) -> None:
        lock_lines = (PROJECT_ROOT / "requirements-heritage.lock.txt").read_text(
            encoding="utf-8"
        ).splitlines()
        pins = {line for line in lock_lines if line and not line.startswith("#")}

        self.assertTrue(
            {
                "cryptography==50.0.0",
                "hypothesis==6.165.10",
                "rfc8785==0.1.4",
                "build==1.5.0",
            }.issubset(pins)
        )
        self.assertTrue(all("==" in pin for pin in pins))

    def test_package_layers_are_importable(self) -> None:
        import heritage_production.application  # noqa: F401
        import heritage_production.domain  # noqa: F401
        import heritage_production.infrastructure  # noqa: F401
        import heritage_production.presentation  # noqa: F401


class CliTests(unittest.TestCase):
    def test_cli_parser_exposes_the_global_options_and_command_groups(self) -> None:
        from heritage_production.presentation.cli.main import build_parser

        parser = build_parser()
        arguments = parser.parse_args(
            [
                "--store",
                "custom-store",
                "--operation-id",
                "operation-123",
                "--json",
                "production",
            ]
        )

        self.assertEqual(arguments.store, "custom-store")
        self.assertEqual(arguments.operation_id, "operation-123")
        self.assertTrue(arguments.json)
        self.assertEqual(arguments.command, "production")
        self.assertEqual(
            set(parser._subparsers._group_actions[0].choices),  # type: ignore[attr-defined]
            COMMAND_GROUPS,
        )

    def test_module_help_requires_no_store_initialization(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(SOURCE_ROOT)

        with tempfile.TemporaryDirectory() as temporary_directory:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "heritage_production.presentation.cli.main",
                    "--help",
                ],
                cwd=temporary_directory,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--store", result.stdout)
            self.assertIn("--operation-id", result.stdout)
            self.assertIn("--json", result.stdout)
            self.assertTrue(all(command in result.stdout for command in COMMAND_GROUPS))
            self.assertFalse((Path(temporary_directory) / ".heritage-production").exists())
