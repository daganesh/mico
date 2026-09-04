"""Layer-boundary enforcement (PRD §15.1, AD-14).

`mico/ui` may not import `mico/brain` directly, and `mico/brain` may not
import `mico/logic` or `mico/ui`. Runs as a CI required-status-check
("layer-check" in .github/workflows/ci.yml) so a violation fails the build
the same way a failing test would.

Rejected `import-linter` (AD-14: dev dependencies also require approval) in
favor of this ~50-line AST script.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

# layer prefix -> set of dotted-module prefixes it may not import
LAYER_RULES: dict[str, set[str]] = {
    "mico.ui": {"mico.brain"},
    "mico.brain": {"mico.logic", "mico.ui"},
    "mico.logic": {"mico.ui"},
}


@dataclass(frozen=True)
class Violation:
    file: Path
    line: int
    imported: str
    layer: str
    forbidden: str

    def __str__(self) -> str:
        return (
            f"{self.file}:{self.line}: {self.layer} imports {self.imported!r} "
            f"(forbidden: {self.forbidden})"
        )


def _module_path(file: Path, package_root: Path) -> str:
    rel = file.relative_to(package_root.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _layer_for(module_path: str) -> str | None:
    candidates = [layer for layer in LAYER_RULES if module_path.startswith(layer)]
    if not candidates:
        return None
    return max(candidates, key=len)


def _imported_names(node: ast.stmt) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        return [node.module]
    return []


def check_layers(package_root: Path) -> list[Violation]:
    """Scan every .py file under package_root for cross-layer imports."""
    violations: list[Violation] = []
    for file in sorted(package_root.rglob("*.py")):
        module_path = _module_path(file, package_root)
        layer = _layer_for(module_path)
        if layer is None:
            continue
        forbidden_prefixes = LAYER_RULES[layer]
        try:
            tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        except SyntaxError as exc:
            violations.append(Violation(file, exc.lineno or 0, "<unparseable>", layer, str(exc)))
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for imported in _imported_names(node):
                for forbidden in forbidden_prefixes:
                    if imported == forbidden or imported.startswith(forbidden + "."):
                        violations.append(Violation(file, node.lineno, imported, layer, forbidden))
    return violations


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    package_root = repo_root / "mico"
    violations = check_layers(package_root)
    if violations:
        print(f"Layer-boundary check failed: {len(violations)} violation(s)\n", file=sys.stderr)
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1
    print("Layer-boundary check passed: no cross-layer imports found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
