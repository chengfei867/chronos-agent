"""Tests for the demo-manifest loader behind ``chronos quickstart`` (R118+R119).

R118 shipped four demos under ``examples/`` each with a ``manifest.json``
(``name`` / ``title`` / ``description`` / ``recommended_evaluators``). The
helpers in ``chronos.cli.quickstart`` parse those manifests with **fail-soft**
semantics — a corrupt or partial manifest must never crash the verb because
the envelopes.jsonl is the source of truth and the manifest is purely
cosmetic / hint surface (per the module docstring).

R119 carry-over from R118 (deferred work D-118-6): pin that fail-soft
contract with unit tests so future refactors can't silently drop it.

Covers:

* ``_load_manifest`` — happy path, missing file, malformed JSON,
  non-dict JSON, missing fields, malformed ``recommended_evaluators``.
* ``_list_available_demos`` — alphabetical sort order, demo dirs without
  ``envelopes.jsonl`` are skipped, missing root returns empty list.
* ``list_demos_command`` — renders without crashing on the empty case
  and on populated demos; surfaces evaluator hints (R118 acceptance row).

These tests touch only the helpers — they do NOT invoke the full Typer
verb (that surface is already covered by ``test_cli_quickstart.py``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rich.console import Console

from chronos.cli.quickstart import (
    _DEFAULT_EVALUATOR,
    DemoManifest,
    _list_available_demos,
    _load_manifest,
    list_demos_command,
)

# ---------------------------------------------------------------------------
# _load_manifest — happy path
# ---------------------------------------------------------------------------


def test_load_manifest_happy_path(tmp_path: Path) -> None:
    """Well-formed manifest → all fields parsed verbatim."""
    demo_dir = tmp_path / "demo-x"
    demo_dir.mkdir()
    payload = {
        "name": "demo-x",
        "title": "Demo X",
        "description": "A toy demo for tests.",
        "recommended_evaluators": ["evaluator_a", "evaluator_b"],
    }
    (demo_dir / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    manifest = _load_manifest(demo_dir, "demo-x")

    assert manifest.name == "demo-x"
    assert manifest.title == "Demo X"
    assert manifest.description == "A toy demo for tests."
    assert manifest.recommended_evaluators == ["evaluator_a", "evaluator_b"]


# ---------------------------------------------------------------------------
# _load_manifest — fail-soft cases
# ---------------------------------------------------------------------------


def test_load_manifest_missing_file_returns_empty(tmp_path: Path) -> None:
    """No manifest file → DemoManifest.empty, not an exception."""
    demo_dir = tmp_path / "demo-no-manifest"
    demo_dir.mkdir()
    # Do not create manifest.json.

    manifest = _load_manifest(demo_dir, "demo-no-manifest")

    assert manifest == DemoManifest.empty("demo-no-manifest")
    assert manifest.recommended_evaluators == [_DEFAULT_EVALUATOR], (
        "fallback evaluator must be the documented default"
    )


def test_load_manifest_malformed_json_returns_empty(tmp_path: Path) -> None:
    """Corrupt JSON → DemoManifest.empty (the verb stays usable)."""
    demo_dir = tmp_path / "demo-bad-json"
    demo_dir.mkdir()
    (demo_dir / "manifest.json").write_text("{not json,", encoding="utf-8")

    manifest = _load_manifest(demo_dir, "demo-bad-json")

    assert manifest == DemoManifest.empty("demo-bad-json")


def test_load_manifest_non_dict_returns_empty(tmp_path: Path) -> None:
    """Top-level JSON array (or any non-dict) → DemoManifest.empty."""
    demo_dir = tmp_path / "demo-non-dict"
    demo_dir.mkdir()
    (demo_dir / "manifest.json").write_text("[1, 2, 3]", encoding="utf-8")

    manifest = _load_manifest(demo_dir, "demo-non-dict")

    assert manifest == DemoManifest.empty("demo-non-dict")


def test_load_manifest_missing_optional_fields_uses_defaults(tmp_path: Path) -> None:
    """A bare-bones manifest still parses; missing fields fall back to sensible defaults."""
    demo_dir = tmp_path / "demo-bare"
    demo_dir.mkdir()
    (demo_dir / "manifest.json").write_text(json.dumps({}), encoding="utf-8")

    manifest = _load_manifest(demo_dir, "demo-bare")

    assert manifest.name == "demo-bare", "name falls back to the dir-name argument"
    assert manifest.title == "demo-bare", "title falls back to the dir-name argument"
    assert manifest.description == ""
    assert manifest.recommended_evaluators == [_DEFAULT_EVALUATOR]


def test_load_manifest_malformed_evaluators_falls_back(tmp_path: Path) -> None:
    """Non-list / non-string-list evaluators → fallback to default evaluator."""
    demo_dir = tmp_path / "demo-bad-evals"
    demo_dir.mkdir()
    payload = {
        "name": "demo-bad-evals",
        "title": "Demo Bad Evals",
        "description": "evaluators field is wrong type",
        "recommended_evaluators": {"not": "a list"},  # dict, not list
    }
    (demo_dir / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    manifest = _load_manifest(demo_dir, "demo-bad-evals")

    assert manifest.recommended_evaluators == [_DEFAULT_EVALUATOR]


def test_load_manifest_empty_evaluators_list_falls_back(tmp_path: Path) -> None:
    """Explicit empty evaluators list → fallback (so the eval-run hint is never blank)."""
    demo_dir = tmp_path / "demo-empty-evals"
    demo_dir.mkdir()
    payload = {
        "name": "demo-empty-evals",
        "title": "Demo Empty Evals",
        "description": "evaluators is []",
        "recommended_evaluators": [],
    }
    (demo_dir / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    manifest = _load_manifest(demo_dir, "demo-empty-evals")

    assert manifest.recommended_evaluators == [_DEFAULT_EVALUATOR]


def test_load_manifest_mixed_type_evaluators_falls_back(tmp_path: Path) -> None:
    """List with non-string elements → fallback (defensive against typos / API drift)."""
    demo_dir = tmp_path / "demo-mixed-evals"
    demo_dir.mkdir()
    payload = {
        "name": "demo-mixed",
        "title": "Demo Mixed",
        "description": "evaluators contains a non-string",
        "recommended_evaluators": ["good_eval", 42],
    }
    (demo_dir / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    manifest = _load_manifest(demo_dir, "demo-mixed-evals")

    assert manifest.recommended_evaluators == [_DEFAULT_EVALUATOR]


# ---------------------------------------------------------------------------
# _list_available_demos
# ---------------------------------------------------------------------------


def _seed_demo(root: Path, name: str, *, with_envelopes: bool = True) -> Path:
    d = root / name
    d.mkdir(parents=True)
    if with_envelopes:
        (d / "envelopes.jsonl").write_text("", encoding="utf-8")
    return d


def test_list_available_demos_alphabetical(tmp_path: Path) -> None:
    """Demos are returned in alphabetical order regardless of FS order."""
    _seed_demo(tmp_path, "zebra")
    _seed_demo(tmp_path, "alpha")
    _seed_demo(tmp_path, "mango")

    listing = _list_available_demos(tmp_path)
    names = [name for name, _ in listing]

    assert names == ["alpha", "mango", "zebra"]


def test_list_available_demos_skips_dirs_without_envelopes(tmp_path: Path) -> None:
    """A subdir without envelopes.jsonl is not a demo."""
    _seed_demo(tmp_path, "real-demo", with_envelopes=True)
    _seed_demo(tmp_path, "stray-dir", with_envelopes=False)

    listing = _list_available_demos(tmp_path)
    names = [name for name, _ in listing]

    assert names == ["real-demo"]


def test_list_available_demos_missing_root_is_empty(tmp_path: Path) -> None:
    """Non-existent examples root → empty list (no exception)."""
    missing = tmp_path / "does-not-exist"

    listing = _list_available_demos(missing)

    assert listing == []


def test_list_available_demos_empty_root_is_empty(tmp_path: Path) -> None:
    """Existing-but-empty root → empty list."""
    listing = _list_available_demos(tmp_path)

    assert listing == []


def test_list_available_demos_skips_files_at_root(tmp_path: Path) -> None:
    """Stray top-level files (e.g. README) are not mistaken for demos."""
    _seed_demo(tmp_path, "real-demo")
    (tmp_path / "README.md").write_text("# stray", encoding="utf-8")

    listing = _list_available_demos(tmp_path)
    names = [name for name, _ in listing]

    assert names == ["real-demo"]


def test_list_available_demos_loads_per_demo_manifest(tmp_path: Path) -> None:
    """Listing carries each demo's parsed manifest inline."""
    demo = _seed_demo(tmp_path, "demo-with-manifest")
    payload = {
        "name": "demo-with-manifest",
        "title": "Demo With Manifest",
        "description": "Has a manifest.",
        "recommended_evaluators": ["evaluator_x"],
    }
    (demo / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    listing = _list_available_demos(tmp_path)

    assert len(listing) == 1
    name, manifest = listing[0]
    assert name == "demo-with-manifest"
    assert manifest.title == "Demo With Manifest"
    assert manifest.recommended_evaluators == ["evaluator_x"]


# ---------------------------------------------------------------------------
# list_demos_command — rendering smoke
# ---------------------------------------------------------------------------


def _capture_console() -> tuple[Console, list[str]]:
    """Build a Console writing to an internal buffer + return both."""
    import io

    buf = io.StringIO()
    return Console(file=buf, width=120, force_terminal=False, no_color=True), buf  # type: ignore[return-value]


def test_list_demos_command_empty_root_friendly_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Empty examples root → friendly message, no exception."""
    from chronos.cli import quickstart as qs_mod

    monkeypatch.setattr(qs_mod, "_examples_root", lambda: tmp_path)
    console, buf = _capture_console()

    list_demos_command(console=console)

    out = buf.getvalue()
    assert "No demos found" in out


def test_list_demos_command_renders_populated_demos(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Populated demos → name + title + description + evaluators surface."""
    from chronos.cli import quickstart as qs_mod

    demo = _seed_demo(tmp_path, "demo-show")
    payload = {
        "name": "demo-show",
        "title": "Show Demo",
        "description": "A demo with a description for the listing.",
        "recommended_evaluators": ["evaluator_a", "evaluator_b"],
    }
    (demo / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(qs_mod, "_examples_root", lambda: tmp_path)
    console, buf = _capture_console()

    list_demos_command(console=console)

    out = buf.getvalue()
    assert "demo-show" in out
    assert "Show Demo" in out
    assert "A demo with a description" in out
    assert "evaluator_a" in out
    assert "evaluator_b" in out
    # Loader hint surfaces so users know what to do next.
    assert "chronos quickstart --demo" in out


def test_list_demos_command_handles_demo_without_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A demo dir without manifest.json still appears in the listing."""
    from chronos.cli import quickstart as qs_mod

    _seed_demo(tmp_path, "no-manifest-demo")
    monkeypatch.setattr(qs_mod, "_examples_root", lambda: tmp_path)
    console, buf = _capture_console()

    list_demos_command(console=console)

    out = buf.getvalue()
    assert "no-manifest-demo" in out
    # Default evaluator hint surfaces for fallback manifests.
    assert _DEFAULT_EVALUATOR in out


# ---------------------------------------------------------------------------
# Anti-bitrot — every shipped demo manifest is parseable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "demo_name",
    [
        "builtin-minimal",
        "langgraph-router",
        "crewai-research-team",
        "anthropic-agent-tools",
    ],
)
def test_shipped_demo_manifest_parses(demo_name: str) -> None:
    """Each R118-shipped demo's manifest.json must parse without falling back to empty."""
    repo_root = Path(__file__).resolve().parents[2]
    demo_dir = repo_root / "examples" / demo_name
    assert demo_dir.exists(), f"shipped demo {demo_name} missing: {demo_dir}"
    assert (demo_dir / "manifest.json").exists(), (
        f"shipped demo {demo_name} is missing manifest.json"
    )

    manifest = _load_manifest(demo_dir, demo_name)

    # If parsing fell back to empty, name/title would equal the dir name AND
    # description would be empty AND recommended_evaluators == [_DEFAULT_EVALUATOR].
    # A real manifest has at least one of: a description, multiple evaluators,
    # or a title that differs from the dir name. Assert that the manifest is
    # NOT a fallback.
    is_fallback = (
        manifest.title == demo_name
        and manifest.description == ""
        and manifest.recommended_evaluators == [_DEFAULT_EVALUATOR]
    )
    assert not is_fallback, (
        f"shipped manifest for {demo_name} parsed as the empty fallback — "
        "manifest.json is malformed or missing required fields"
    )

    # Specific contract: every shipped manifest declares ≥1 evaluator (used by
    # the quickstart Next-steps eval-run hint).
    assert manifest.recommended_evaluators, (
        f"shipped {demo_name} manifest has empty recommended_evaluators"
    )
