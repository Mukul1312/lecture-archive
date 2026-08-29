"""Layering guards for `heritage_archive`, written before the code they guard.

ADR-0001 decision 2(a) and ADR-0004 decision 2: these go in **first**, before any
domain code, because the shelved `heritage_production` shows what happens without
them — 34,679 lines with a firewall that only ever verified itself.

These are the *layering* guards only. Named-invariant guards (`INV-<ID>`, ADR-0001
decision 2(b), ADR-0005 §6) arrive with their invariants, one test per invariant,
each citing the ADR that mandated it.

Two properties this module has that the `heritage_production` original did not:

* It never asserts that a folder exists. ADR-0005 §5 forbids scaffolding — "empty
  folders rot" — so the guards discover whatever is present and check that, rather
  than pinning a shape. A layout that has not graduated yet must not be forced into
  existence by its own test suite.
* It cannot pass vacuously without saying so. `test_the_guards_are_not_vacuous`
  skips loudly while the package is absent and fails if the package exists but the
  scanner finds nothing — which would mean the scanner, not the code, is broken.

Run explicitly (the shelved suite is excluded from default discovery per ADR-0001
decision 5):

    python -m unittest discover -s tests/heritage_archive -t .
"""

from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]

# The one line to change if the package is renamed. Matches pyproject.toml's
# `name = "heritage-archive"`, and is deliberately distinct from the shelved
# `heritage_production` sitting beside it in src/.
PACKAGE_NAME = "heritage_archive"
PACKAGE_ROOT = PROJECT_ROOT / "src" / PACKAGE_NAME

# ADR-0005 §3. Lower may not import higher.
LAYER_RANK = {"domain": 0, "application": 1, "infrastructure": 2}

# ADR-0005 §5: the composition root is the ONE named exemption to the dependency
# rule — it may import across contexts, because it is the main partition, nothing
# depends on it, and construction is not orchestration. Named here so the carve-out
# is a decision on the record rather than a wildcard someone widens later.
COMPOSITION_ROOT_PARTS = (PACKAGE_NAME, "composition_root")

# Until composition_root/ graduates (ADR-0005 §5: 3+ repositories, or wiring past
# ~50 lines, or cross-context wiring), inline wiring lives in the inbound CLI
# adapter. That file is infrastructure, so it is already allowed to import both
# application and domain; it gets no cross-context exemption, which is the point.


def python_modules() -> list[tuple[Path, tuple[str, ...]]]:
    """Every module in the package, as (path, dotted-parts). Empty if absent."""
    if not PACKAGE_ROOT.is_dir():
        return []
    modules: list[tuple[Path, tuple[str, ...]]] = []
    for source_file in sorted(PACKAGE_ROOT.rglob("*.py")):
        if "__pycache__" in source_file.parts:
            continue
        relative = source_file.relative_to(PACKAGE_ROOT).with_suffix("").parts
        if relative and relative[-1] == "__init__":
            relative = relative[:-1]
        modules.append((source_file, (PACKAGE_NAME, *relative)))
    return modules


def imported_modules(source_file: Path, module: tuple[str, ...]) -> list[tuple[str, ...]]:
    """Every module this file imports, with relative imports resolved.

    Resolving relative imports is not optional: without it the cycle and boundary
    walks are blind to exactly the intra-package edges they exist to find. The
    `heritage_production` suite learned this the hard way and kept a dedicated test
    for it (`test_domain_import_boundaries.py`).
    """
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    # A package __init__ is its own package; a plain module lives inside its parent.
    package = module if source_file.name == "__init__.py" else module[:-1]

    imports: list[tuple[str, ...]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(tuple(alias.name.split(".")) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = tuple(node.module.split(".")) if node.module else ()
            if node.level:
                if node.level > len(package):
                    continue
                base = (*package[: len(package) - node.level + 1], *base)
            if node.module is None:
                # A bare `from . import errors`: the aliases ARE module names, so
                # the edge is to `<package>.errors`, not to `<package>`. Stopping at
                # the package loses intra-package edges and blinds the cycle walk --
                # which is precisely how `heritage_production`'s resolver behaves,
                # and this module's own resolver test caught it.
                # When `node.module` is set (`from .errors import Foo`) the aliases
                # may be plain symbols, so the edge correctly stops at the module.
                imports.extend((*base, alias.name) for alias in node.names)
            else:
                imports.append(base)
    return imports


def context_of(module: tuple[str, ...]) -> str | None:
    """`heritage_archive.contexts.<name>....` -> `<name>`, else None."""
    if len(module) >= 3 and module[1] == "contexts":
        return module[2]
    return None


def layer_of(module: tuple[str, ...]) -> str | None:
    """The layer segment inside a context, or None for kernel/platform/root."""
    if context_of(module) is None or len(module) < 4:
        return None
    return module[3] if module[3] in LAYER_RANK else None


def is_composition_root(module: tuple[str, ...]) -> bool:
    return module[: len(COMPOSITION_ROOT_PARTS)] == COMPOSITION_ROOT_PARTS


def is_internal(imported: tuple[str, ...]) -> bool:
    return bool(imported) and imported[0] == PACKAGE_NAME


def where(source_file: Path) -> str:
    return str(source_file.relative_to(PROJECT_ROOT))


class GuardsAreLive(unittest.TestCase):
    """The guards must not pass by having nothing to check."""

    def test_the_guards_are_not_vacuous(self) -> None:
        if not PACKAGE_ROOT.is_dir():
            self.skipTest(
                f"{PACKAGE_NAME} does not exist yet. These guards are deliberately "
                "in place before the code they guard (ADR-0004 decision 2). ADR-0004 "
                "§5 sets the start gate for that first commit: 2026-09-05."
            )
        modules = python_modules()
        self.assertNotEqual(
            modules,
            [],
            f"{PACKAGE_ROOT} exists but the scanner found no modules in it. "
            "The scanner is broken, not the code — every guard below is passing "
            "vacuously until this is fixed.",
        )


class DependencyRule(unittest.TestCase):
    """ADR-0005 §3: dependencies point inward, toward the domain."""

    def test_layers_do_not_import_outward(self) -> None:
        violations: list[str] = []
        for source_file, module in python_modules():
            rank = LAYER_RANK.get(layer_of(module) or "")
            if rank is None:
                continue
            for imported in imported_modules(source_file, module):
                if not is_internal(imported):
                    continue
                target = LAYER_RANK.get(layer_of(imported) or "")
                if target is not None and target > rank:
                    violations.append(
                        f"{where(source_file)} ({layer_of(module)}) -> "
                        f"{'.'.join(imported)} ({layer_of(imported)})"
                    )
        self.assertEqual(violations, [], f"inward dependency rule broken: {violations}")

    def test_domain_imports_only_stdlib_and_the_kernel(self) -> None:
        """ADR-0005 §3: domain may import stdlib, the kernel, and its own siblings.

        This is the check that walks the real tree. Keeping the predicate and its
        enforcement in one test is deliberate — the `heritage_production` original
        split them, and an audit found the split test at `test_architecture.py:133`
        would have passed unchanged if every domain module imported numpy.
        """
        standard_library = set(sys.stdlib_module_names)
        violations: list[str] = []
        for source_file, module in python_modules():
            if layer_of(module) != "domain":
                continue
            for imported in imported_modules(source_file, module):
                root = imported[0] if imported else ""
                if root in standard_library or root == "__future__":
                    continue
                if is_internal(imported) and (
                    imported[:2] == (PACKAGE_NAME, "kernel")
                    or context_of(imported) == context_of(module)
                ):
                    continue
                violations.append(f"{where(source_file)} -> {'.'.join(imported)}")
        self.assertEqual(
            violations,
            [],
            f"domain must be stdlib + kernel + own-context only: {violations}",
        )

    def test_platform_is_reachable_only_from_infrastructure(self) -> None:
        """ADR-0005 §4: platform is the only place third-party SDKs are imported.

        Letting domain or application reach it would route a third-party dependency
        into an inner layer through a folder the domain rule does not name.
        """
        violations: list[str] = []
        for source_file, module in python_modules():
            layer = layer_of(module)
            if layer not in {"domain", "application"}:
                continue
            for imported in imported_modules(source_file, module):
                if is_internal(imported) and imported[:2] == (PACKAGE_NAME, "platform"):
                    violations.append(f"{where(source_file)} ({layer}) -> {'.'.join(imported)}")
        self.assertEqual(violations, [], f"platform reached from an inner layer: {violations}")


class ContextBoundaries(unittest.TestCase):
    """ADR-0005 §4: each context is a mini-hexagon."""

    def test_no_context_imports_another_except_the_composition_root(self) -> None:
        violations: list[str] = []
        for source_file, module in python_modules():
            if is_composition_root(module):
                continue
            own = context_of(module)
            if own is None:
                continue
            for imported in imported_modules(source_file, module):
                other = context_of(imported) if is_internal(imported) else None
                if other is not None and other != own:
                    violations.append(f"{where(source_file)} ({own}) -> {'.'.join(imported)} ({other})")
        self.assertEqual(
            violations,
            [],
            "cross-context imports are forbidden outside the composition root "
            f"(ADR-0005 §5): {violations}",
        )

    def test_the_kernel_never_imports_a_context(self) -> None:
        """The kernel is shared by definition; a context import would invert that."""
        violations: list[str] = []
        for source_file, module in python_modules():
            if module[:2] != (PACKAGE_NAME, "kernel"):
                continue
            for imported in imported_modules(source_file, module):
                if is_internal(imported) and context_of(imported) is not None:
                    violations.append(f"{where(source_file)} -> {'.'.join(imported)}")
        self.assertEqual(violations, [], f"kernel depends on a context: {violations}")

    def test_the_kernel_uses_only_the_standard_library(self) -> None:
        """ADR-0001: the lifted kernel is stdlib-only, and stays that way."""
        standard_library = set(sys.stdlib_module_names)
        violations: list[str] = []
        for source_file, module in python_modules():
            if module[:2] != (PACKAGE_NAME, "kernel"):
                continue
            for imported in imported_modules(source_file, module):
                root = imported[0] if imported else ""
                if root in standard_library or root == "__future__" or is_internal(imported):
                    continue
                violations.append(f"{where(source_file)} -> {'.'.join(imported)}")
        self.assertEqual(violations, [], f"third-party import in the kernel: {violations}")

    def test_nothing_imports_the_composition_root(self) -> None:
        """ADR-0005 §5: 'It's a sink, not a source. Pollution flows in, nothing out.'

        This is the property that makes the cross-context exemption safe. If anything
        imports the composition root, the exemption stops being contained.
        """
        violations: list[str] = []
        for source_file, module in python_modules():
            if is_composition_root(module):
                continue
            for imported in imported_modules(source_file, module):
                if is_internal(imported) and is_composition_root(imported):
                    violations.append(f"{where(source_file)} -> {'.'.join(imported)}")
        self.assertEqual(violations, [], f"the composition root is imported by: {violations}")


class NoCycles(unittest.TestCase):
    """A cycle means two modules are one module wearing two names.

    `heritage_production` carries a real example: `review.findings` and
    `review.rounds` import each other, and `rounds.py` defers four imports into
    function bodies to hide it. ADR-0001 §4 cites that as a reason not to mine the
    review model. No cycle is grandfathered here — the allowlist starts empty and
    should stay empty.
    """

    def test_the_package_import_graph_is_acyclic(self) -> None:
        graph: dict[str, set[str]] = {}
        for source_file, module in python_modules():
            name = ".".join(module)
            targets = {
                ".".join(imported)
                for imported in imported_modules(source_file, module)
                if is_internal(imported)
            }
            graph.setdefault(name, set()).update(targets - {name})

        visiting: set[str] = set()
        done: set[str] = set()
        cycles: list[str] = []

        def walk(node: str, trail: tuple[str, ...]) -> None:
            if node in done:
                return
            if node in visiting:
                # Report the cycle itself, not the path that reached it.
                cycles.append(" -> ".join((*trail[trail.index(node):], node)))
                return
            visiting.add(node)
            for target in sorted(graph.get(node, ())):
                walk(target, (*trail, node))
            visiting.discard(node)
            done.add(node)

        for node in sorted(graph):
            walk(node, ())

        self.assertEqual(cycles, [], f"import cycle(s): {cycles}")

    def test_the_relative_import_resolver_sees_intra_package_edges(self) -> None:
        """The cycle walk is worthless if relative imports are dropped.

        Synthetic rather than pinned to a real file, so it keeps working before any
        code exists and does not break when files move.
        """
        import tempfile

        source_text = (
            "from . import errors\n"
            "from ..application import handlers\n"
            "from .value_objects import Digest\n"
        )
        module = (PACKAGE_NAME, "contexts", "archive", "domain", "probe")

        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / "probe.py"
            probe.write_text(source_text, encoding="utf-8")
            resolved = imported_modules(probe, module)

        # `from . import errors` must reach the SUBMODULE. Stopping at the package
        # would make this a self-edge, which the cycle walk filters out -- so the
        # edge would vanish entirely. This is the case that matters.
        self.assertIn((PACKAGE_NAME, "contexts", "archive", "domain", "errors"), resolved)

        # When `node.module` is set the alias may be a submodule OR a symbol
        # re-exported from that package's `__init__`, and nothing in the AST
        # distinguishes them. The resolver stops at the named module, which is the
        # conservative choice: it is still a real edge, it still carries the layer
        # and context, and it cannot invent a module that does not exist.
        self.assertIn((PACKAGE_NAME, "contexts", "archive", "application"), resolved)
        self.assertIn(
            (PACKAGE_NAME, "contexts", "archive", "domain", "value_objects"), resolved
        )
        self.assertNotIn(
            (PACKAGE_NAME, "contexts", "archive", "domain", "value_objects", "Digest"),
            resolved,
        )


if __name__ == "__main__":
    unittest.main()
