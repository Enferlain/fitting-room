import json

import pytest

from fitting_room import harness_store
from fitting_room.store import StoreError


def test_harness_provision_reuses_verified_install(tmp_path, monkeypatch):
    calls = []

    def provision(path, command, *, verify=False):
        calls.append((command, verify))
        if verify:
            assert not (path / "harness.json").exists()
            return "codex-cli 0.163.0"
        binary = path / "bin" / "codex"
        binary.parent.mkdir()
        binary.touch(mode=0o755)

    monkeypatch.setattr(harness_store, "provision_in_base", provision)
    path = harness_store.ensure_harness("codex", "0.163.0", tmp_path)
    assert json.loads((path / "harness.json").read_text()) == {
        "harness": "codex",
        "version": "0.163.0",
        "recipe": harness_store.RECIPES["codex"],
    }
    assert harness_store.ensure_harness("codex", "0.163.0", tmp_path) == path
    assert [verify for _, verify in calls] == [False, True]


def test_failed_version_check_does_not_leave_install(tmp_path, monkeypatch):
    monkeypatch.setattr(harness_store, "provision_in_base", lambda *_a, **_kw: "2.2.60")
    with pytest.raises(StoreError, match="expected 2.2.6"):
        harness_store.ensure_harness("opencode", "2.2.6", tmp_path)
    assert not (tmp_path / "harness/opencode/2.2.6").exists()


def test_hermes_requires_version_output_and_full_matching_sha():
    sha = "f97608f178d1ffeca59860195ab7da295f7c8e5f"
    version = "Hermes Agent v0.21.5 (2026.9.24)"
    assert harness_store.version_matches("hermes", sha, f"{version}\n{sha}")
    assert harness_store.version_matches(
        "hermes", sha, f"{version} · upstream {sha[:8]}\n{sha}\n\n"
    )
    assert not harness_store.version_matches("hermes", sha, f"{version}\n{sha[:8]}")
    assert not harness_store.version_matches("hermes", sha, sha)


def test_existing_harness_with_bad_manifest_is_not_replaced(tmp_path):
    path = tmp_path / "harness/codex/0.163.0"
    path.mkdir(parents=True)
    manifest = path / "harness.json"
    manifest.write_text("{")
    with pytest.raises(StoreError, match="Invalid harness manifest"):
        harness_store.ensure_harness("codex", "0.163.0", tmp_path)
    assert manifest.read_text() == "{"


def test_recipe_bump_invalidates_existing_harness(tmp_path, monkeypatch):
    def provision(path, command, *, verify=False):
        if verify:
            return "opencode v2.2.6"
        binary = path / "bin" / "opencode"
        binary.parent.mkdir()
        binary.touch(mode=0o755)

    monkeypatch.setattr(harness_store, "provision_in_base", provision)
    path = harness_store.ensure_harness("opencode", "2.2.6", tmp_path)
    monkeypatch.setitem(harness_store.RECIPES, "opencode", harness_store.RECIPES["opencode"] + 1)
    with pytest.raises(StoreError, match="installer recipe"):
        harness_store.ensure_harness("opencode", "2.2.6", tmp_path)
    assert path.is_dir()  # never replaced underneath a running campaign
