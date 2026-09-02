"""AST architecture guard for the package layout accepted by ADR-0005."""

from __future__ import annotations

import ast
from collections import defaultdict
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


PACKAGE = "heritage_archive"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "src" / PACKAGE
CONTEXT_LAYERS = {"domain": 0, "application": 1, "infrastructure": 2}


class ArchitectureViolation(AssertionError):
    """Raised when a source layout violates the accepted import rulebook."""


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def modules_under(package_root: Path, package_name: str) -> dict[tuple[str, ...], Path]:
    found: dict[tuple[str, ...], Path] = {}
    if _is_reparse_point(package_root) or not package_root.is_dir():
        return found
    for directory, names, files in os.walk(package_root, followlinks=False):
        current = Path(directory)
        names[:] = [
            name
            for name in names
            if name not in {"__pycache__", ".venv", ".venv-narrator"}
            and not _is_reparse_point(current / name)
        ]
        for name in files:
            if not name.endswith(".py"):
                continue
            source = current / name
            if _is_reparse_point(source):
                continue
            parts = source.relative_to(package_root).with_suffix("").parts
            module = (package_name, *(parts[:-1] if parts[-1] == "__init__" else parts))
            found[module] = source
    return found


def imports_from(source: Path, module: tuple[str, ...]) -> set[tuple[str, ...]]:
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    package = module if source.name == "__init__.py" else module[:-1]
    imports: set[tuple[str, ...]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(tuple(alias.name.split(".")) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = tuple(node.module.split(".")) if node.module else ()
            if node.level:
                base = (*package[: len(package) - node.level + 1], *base)
            imports.add(base)
            imports.update((*base, alias.name) for alias in node.names)
    return imports


def context_layer(module: tuple[str, ...], package_name: str) -> tuple[str, str] | None:
    if len(module) >= 4 and module[:2] == (package_name, "contexts") and module[3] in CONTEXT_LAYERS:
        return module[2], module[3]
    return None


def guard(package_root: Path, package_name: str = PACKAGE) -> int:
    modules = modules_under(package_root, package_name)
    edges: dict[tuple[str, ...], set[tuple[str, ...]]] = defaultdict(set)
    violations: list[str] = []
    standard_library = set(sys.stdlib_module_names) | {"__future__"}
    for module, source in modules.items():
        source_context_layer = context_layer(module, package_name)
        for imported in imports_from(source, module):
            if not imported:
                continue
            if imported[:1] == ("heritage_production",):
                violations.append(f"legacy import: {module} -> {imported}")
            if module[:2] == (package_name, "kernel") and (
                imported[0] not in standard_library
                and imported[:2] != (package_name, "kernel")
            ):
                violations.append(f"kernel impurity: {module} -> {imported}")
            if imported in modules:
                edges[module].add(imported)
            if source_context_layer is not None:
                source_context, source_layer = source_context_layer
                target_context_layer = context_layer(imported, package_name)
                if target_context_layer is not None:
                    target_context, target_layer = target_context_layer
                    if target_context != source_context:
                        violations.append(f"context crossing: {module} -> {imported}")
                    elif CONTEXT_LAYERS[target_layer] > CONTEXT_LAYERS[source_layer]:
                        violations.append(f"outward import: {module} -> {imported}")
                if source_layer == "domain" and imported[0] not in standard_library:
                    allowed = (
                        imported[:2] == (package_name, "kernel")
                        or context_layer(imported, package_name) == (source_context, "domain")
                    )
                    if not allowed:
                        violations.append(f"domain impurity: {module} -> {imported}")
                if (
                    source_layer == "application"
                    and imported[:2] == (package_name, "platform")
                ):
                    violations.append(f"application-to-platform import: {module} -> {imported}")
                if source_layer in {"application", "infrastructure"} and imported[0] not in standard_library:
                    allowed = imported[:2] == (package_name, "kernel")
                    if target_context_layer is not None:
                        target_context, target_layer = target_context_layer
                        allowed = target_context == source_context and (
                            CONTEXT_LAYERS[target_layer] <= CONTEXT_LAYERS[source_layer]
                        )
                    if source_layer == "infrastructure" and imported[:2] == (package_name, "platform"):
                        allowed = True
                    if not allowed:
                        violations.append(f"context layer impurity: {module} -> {imported}")
            if module[:2] == (package_name, "platform") and imported[:2] == (package_name, "contexts"):
                violations.append(f"platform-to-context import: {module} -> {imported}")
            if module[:2] != (package_name, "composition_root") and imported[:2] == (package_name, "composition_root"):
                violations.append(f"composition root is not a sink: {module} -> {imported}")
    visiting: set[tuple[str, ...]] = set()
    visited: set[tuple[str, ...]] = set()

    def visit(module: tuple[str, ...]) -> None:
        if module in visiting:
            violations.append(f"import cycle: {module}")
            return
        if module in visited:
            return
        visiting.add(module)
        for target in edges[module]:
            visit(target)
        visiting.remove(module)
        visited.add(module)

    for module in modules:
        visit(module)
    if violations:
        raise ArchitectureViolation("\n".join(violations))
    return len(modules)


class ArchitectureGuardTests(unittest.TestCase):
    def test_real_kernel_is_scanned_and_is_stdlib_pure(self) -> None:
        self.assertGreaterEqual(guard(PACKAGE_ROOT, PACKAGE), 8)

    def assert_guard_rejects(self, relative: str, contents: str, expected: str) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / PACKAGE
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(contents, encoding="utf-8")
            with self.assertRaisesRegex(ArchitectureViolation, expected):
                guard(root, PACKAGE)

    def test_rejects_domain_outward_import(self) -> None:
        self.assert_guard_rejects(
            "contexts/a/domain/outward.py",
            "from heritage_archive.contexts.a.infrastructure import adapter\n",
            "outward import",
        )

    def test_rejects_domain_third_party_import(self) -> None:
        self.assert_guard_rejects(
            "contexts/a/domain/third_party.py", "import requests\n", "domain impurity"
        )

    def test_rejects_cross_context_import(self) -> None:
        self.assert_guard_rejects(
            "contexts/a/application/cross.py",
            "from heritage_archive.contexts.b.domain import model\n",
            "context crossing",
        )

    def test_rejects_application_platform_import(self) -> None:
        self.assert_guard_rejects(
            "contexts/a/application/platform.py",
            "from heritage_archive.platform.audio import engine\n",
            "application-to-platform import",
        )

    def test_rejects_application_third_party_import(self) -> None:
        self.assert_guard_rejects(
            "contexts/a/application/third_party.py",
            "import requests\n",
            "context layer impurity",
        )

    def test_rejects_infrastructure_third_party_import(self) -> None:
        self.assert_guard_rejects(
            "contexts/a/infrastructure/third_party.py",
            "import requests\n",
            "context layer impurity",
        )

    def test_rejects_platform_context_import(self) -> None:
        self.assert_guard_rejects(
            "platform/audio/forbidden.py",
            "from heritage_archive.contexts.a.domain import model\n",
            "platform-to-context import",
        )

    def test_rejects_non_root_composition_import(self) -> None:
        self.assert_guard_rejects(
            "contexts/a/domain/composition.py",
            "from heritage_archive.composition_root import wire\n",
            "composition root is not a sink",
        )

    def test_rejects_kernel_third_party_import(self) -> None:
        self.assert_guard_rejects("kernel/third_party.py", "import requests\n", "kernel impurity")

    def test_rejects_kernel_platform_import(self) -> None:
        self.assert_guard_rejects(
            "kernel/platform.py",
            "from heritage_archive.platform.audio import engine\n",
            "kernel impurity",
        )

    def test_rejects_kernel_context_import(self) -> None:
        self.assert_guard_rejects(
            "kernel/context.py",
            "from heritage_archive.contexts.a.domain import model\n",
            "kernel impurity",
        )

    def test_rejects_relative_import_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / PACKAGE
            (root / "kernel").mkdir(parents=True)
            (root / "kernel" / "first.py").write_text(
                "from . import second\n", encoding="utf-8"
            )
            (root / "kernel" / "second.py").write_text(
                "from . import first\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ArchitectureViolation, "import cycle"):
                guard(root, PACKAGE)

    def test_rejects_absolute_package_import_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / PACKAGE
            (root / "kernel").mkdir(parents=True)
            (root / "kernel" / "first.py").write_text(
                "from heritage_archive.kernel import second\n", encoding="utf-8"
            )
            (root / "kernel" / "second.py").write_text(
                "from heritage_archive.kernel import first\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ArchitectureViolation, "import cycle"):
                guard(root, PACKAGE)

    def test_rejects_platform_root_package_context_import(self) -> None:
        self.assert_guard_rejects(
            "platform/audio/forbidden.py",
            "from heritage_archive import contexts\n",
            "platform-to-context import",
        )

    def test_rejects_non_root_root_package_composition_import(self) -> None:
        self.assert_guard_rejects(
            "contexts/a/domain/composition.py",
            "from heritage_archive import composition_root\n",
            "composition root is not a sink",
        )

    def test_relative_import_resolver_preserves_bare_alias_edge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "probe.py"
            source.write_text("from . import errors\n", encoding="utf-8")
            imports = imports_from(source, (PACKAGE, "kernel", "probe"))
        self.assertEqual(
            imports,
            {(PACKAGE, "kernel"), (PACKAGE, "kernel", "errors")},
        )

    def test_scanner_skips_ignored_and_reparse_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / PACKAGE
            (root / "kernel").mkdir(parents=True)
            (root / "kernel" / "safe.py").write_text("", encoding="utf-8")
            (root / ".venv").mkdir()
            (root / ".venv" / "ignored.py").write_text("import requests\n", encoding="utf-8")
            (root / "reparse").mkdir()
            (root / "reparse" / "ignored.py").write_text("import requests\n", encoding="utf-8")
            original = _is_reparse_point
            with patch(
                f"{__name__}._is_reparse_point",
                side_effect=lambda path: path.name == "reparse" or original(path),
            ):
                modules = modules_under(root, PACKAGE)
        self.assertEqual(set(modules), {(PACKAGE, "kernel", "safe")})

    def test_scanner_excludes_real_reparse_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / PACKAGE
            target = Path(temporary_directory) / "reparse-target"
            link = root / "linked"
            (root / "kernel").mkdir(parents=True)
            (root / "kernel" / "safe.py").write_text("", encoding="utf-8")
            target.mkdir()
            (target / "decoy.py").write_text("import requests\n", encoding="utf-8")
            try:
                if os.name == "nt":
                    result = subprocess.run(
                        ["cmd.exe", "/d", "/s", "/c", "mklink", "/J", str(link), str(target)],
                        capture_output=True,
                        check=False,
                        text=True,
                    )
                    if result.returncode != 0:
                        self.skipTest(f"Windows refused a temporary junction: {result.stderr}")
                else:
                    link.symlink_to(target, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"OS refused a temporary directory link: {error}")
            self.assertTrue(_is_reparse_point(link))
            self.assertEqual(set(modules_under(root, PACKAGE)), {(PACKAGE, "kernel", "safe")})


class NarratorVoiceArchitectureTests(unittest.TestCase):
    NARRATOR_ROOT = PACKAGE_ROOT / "contexts" / "narrator_voice"

    @staticmethod
    def _classes(path: Path, suffix: str = "") -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        return {
            node.name for node in tree.body
            if isinstance(node, ast.ClassDef) and (not suffix or node.name.endswith(suffix))
        }

    def test_narrator_voice_is_nonvacuous_with_exactly_three_roots_and_repository_ports(self) -> None:
        domain = self.NARRATOR_ROOT / "domain"
        application = self.NARRATOR_ROOT / "application"
        roots = {
            name
            for filename in ("authorization.py", "narration_job.py", "diary_episode.py")
            for name in self._classes(domain / filename)
            if name in {"AuthorizationRecord", "NarrationJob", "DiaryEpisode"}
        }
        repositories = self._classes(application / "ports.py", "Repository")
        self.assertEqual(roots, {"AuthorizationRecord", "NarrationJob", "DiaryEpisode"})
        self.assertEqual(
            repositories,
            {"AuthorizationRecordRepository", "NarrationJobRepository", "DiaryEpisodeRepository"},
        )
        self.assertGreaterEqual(len(list(domain.glob("*.py"))), 8)
        self.assertGreaterEqual(len(list(application.glob("*.py"))), 5)

    def test_lane_b_and_lane_c_use_distinct_narrow_policy_factories_and_handlers(self) -> None:
        narration_source = (self.NARRATOR_ROOT / "domain" / "narration_job.py").read_text(encoding="utf-8")
        handler_source = (self.NARRATOR_ROOT / "application" / "handlers.py").read_text(encoding="utf-8")
        self.assertIn("def prepare_lane_b_diary_job(", narration_source)
        self.assertIn("def prepare_lane_c_intro_job(", narration_source)
        self.assertIn("class PrepareDiaryNarrationHandler", handler_source)
        self.assertIn("class PrepareIntroNarrationHandler", handler_source)
        self.assertNotIn("prepare_job_for_lane", narration_source)

    def test_narrator_domain_and_application_have_no_legacy_provider_web_filesystem_or_ffmpeg_import(self) -> None:
        forbidden_roots = {
            "heritage_production", "requests", "httpx", "urllib", "socket", "aiohttp",
            "fastapi", "flask", "django", "cartesia", "ffmpeg", "subprocess", "pathlib", "os",
        }
        violations = []
        for layer in ("domain", "application"):
            for source in (self.NARRATOR_ROOT / layer).glob("*.py"):
                module = (PACKAGE, "contexts", "narrator_voice", layer, source.stem)
                for imported in imports_from(source, module):
                    if imported and imported[0].lower() in forbidden_roots:
                        violations.append(f"{source.name}: {'.'.join(imported)}")
        self.assertEqual(violations, [])

    def test_complete_public_use_case_surface_has_frozen_commands_results_and_explicit_handlers(self) -> None:
        handlers = self._classes(self.NARRATOR_ROOT / "application" / "handlers.py", "Handler")
        expected = {
            "RegisterAuthorizationHandler", "RecordAuthorizationChangeHandler", "ShowAuthorizationStatusHandler",
            "PrepareDiaryNarrationHandler", "PrepareIntroNarrationHandler", "RevisePassageTextHandler",
            "ReorderPassagesHandler", "ReviseDeliveryDefaultsHandler", "ValidateRenderRecipeHandler",
            "RequireRenderRecipeHandler", "RequireDictionaryHandler", "EstimateGenerationHandler",
            "GenerateTakeHandler", "GeneratePendingPassagesHandler", "RecordReviewDecisionHandler",
            "SelectWorkingTakeHandler", "AssembleNarrationMasterHandler",
            "RecordNarrationMasterListeningHandler", "IssueNarrationMasterSnapshotHandler",
            "ShowNarrationStatusHandler", "ReconcileGenerationAttemptHandler",
            "ReconcileNarrationAssemblyAttemptHandler", "PrepareDiaryEpisodeHandler",
            "AttachIntroMasterHandler", "AttachDiaryMasterHandler", "SetIntroDiaryGapHandler",
            "AssembleEpisodeSpeechMasterHandler", "RecordEpisodeListeningHandler",
            "BuildTimedNarrationPackageHandler", "RecordTimingCorrectionHandler",
            "ShowEpisodeStatusHandler", "ExportPresentationHandoffHandler",
            "ReconcileEpisodeAssemblyAttemptHandler",
        }
        self.assertEqual(handlers, expected)
        command_source = (self.NARRATOR_ROOT / "application" / "commands.py").read_text(encoding="utf-8")
        result_source = (self.NARRATOR_ROOT / "application" / "results.py").read_text(encoding="utf-8")
        command_tree = ast.parse(command_source)
        result_tree = ast.parse(result_source)
        command_classes = {node.name: node for node in command_tree.body if isinstance(node, ast.ClassDef)}
        result_classes = {node.name: node for node in result_tree.body if isinstance(node, ast.ClassDef)}
        self.assertTrue(all(name.removesuffix("Handler") + "Command" in command_classes for name in expected))
        for collection in (command_classes.values(), result_classes.values()):
            for node in collection:
                decorator_text = {ast.unparse(value) for value in node.decorator_list}
                self.assertTrue(
                    any("dataclass" in value and "frozen=True" in value and "slots=True" in value for value in decorator_text),
                    node.name,
                )
