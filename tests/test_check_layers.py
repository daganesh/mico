"""Tests for tools/check_layers.py (the CI layer-boundary gate)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.check_layers import check_layers  # noqa: E402


def _write(root: Path, relpath: str, content: str) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_real_tree_has_no_violations() -> None:
    assert check_layers(REPO_ROOT / "mico") == []


def test_ui_importing_brain_directly_is_flagged(tmp_path: Path) -> None:
    package_root = tmp_path / "mico"
    _write(package_root, "__init__.py", "")
    _write(package_root, "brain/__init__.py", "")
    _write(package_root, "brain/storage.py", "class MetadataStore: ...\n")
    _write(package_root, "ui/__init__.py", "")
    _write(package_root, "ui/cli/__init__.py", "")
    _write(package_root, "ui/cli/bad.py", "from mico.brain.storage import MetadataStore\n")

    violations = check_layers(package_root)

    assert len(violations) == 1
    assert violations[0].imported == "mico.brain.storage"
    assert violations[0].layer == "mico.ui"


def test_ui_importing_logic_is_allowed(tmp_path: Path) -> None:
    package_root = tmp_path / "mico"
    _write(package_root, "__init__.py", "")
    _write(package_root, "logic/__init__.py", "")
    _write(package_root, "logic/tracks.py", "class TrackService: ...\n")
    _write(package_root, "ui/__init__.py", "")
    _write(package_root, "ui/cli/__init__.py", "")
    _write(package_root, "ui/cli/good.py", "from mico.logic.tracks import TrackService\n")

    assert check_layers(package_root) == []


def test_brain_importing_logic_is_flagged(tmp_path: Path) -> None:
    package_root = tmp_path / "mico"
    _write(package_root, "__init__.py", "")
    _write(package_root, "logic/__init__.py", "")
    _write(package_root, "logic/tracks.py", "class TrackService: ...\n")
    _write(package_root, "brain/__init__.py", "")
    _write(package_root, "brain/bad.py", "import mico.logic.tracks\n")

    violations = check_layers(package_root)

    assert len(violations) == 1
    assert violations[0].layer == "mico.brain"
    assert violations[0].forbidden == "mico.logic"
