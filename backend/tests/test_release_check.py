import importlib.util
from pathlib import Path
import subprocess

import pytest


spec = importlib.util.spec_from_file_location("release_check", Path(__file__).resolve().parents[2] / "scripts/check_release.py")
release_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_check)


@pytest.fixture
def repository(tmp_path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    return tmp_path


def test_source_candidates_exclude_ignored_user_data(repository):
    (repository / ".gitignore").write_text("storage/\n")
    (repository / "app.py").write_text("print('local studio')\n")
    (repository / "storage").mkdir()
    (repository / "storage" / "voices.wav").write_bytes(b"private fixture")
    count, findings = release_check.scan(repository)
    assert count == 2
    assert findings == []


def test_real_token_pattern_reports_location_without_exposing_value(repository):
    token = "nvapi-" + "x" * 48
    (repository / "settings.py").write_text("API_KEY = '" + token + "'\n")
    _, findings = release_check.scan(repository)
    assert findings == ["settings.py:1: AI API token"]
    assert token not in str(findings)


def test_force_added_runtime_data_is_blocked(repository):
    (repository / ".gitignore").write_text("storage/\n")
    (repository / "storage").mkdir()
    (repository / "storage" / "voices.wav").write_bytes(b"private fixture")
    subprocess.run(["git", "-C", str(repository), "add", "--force", "storage/voices.wav"], check=True)
    _, findings = release_check.scan(repository, staged=True)
    assert findings == ["storage/voices.wav: runtime/media/credential file"]


def test_index_scan_detects_a_secret_even_after_working_copy_is_cleaned(repository):
    (repository / "app.py").write_text("token = '" + "sk-" + "x" * 48 + "'\n")
    subprocess.run(["git", "-C", str(repository), "add", "app.py"], check=True)
    (repository / "app.py").write_text("print('clean')\n")
    assert release_check.scan(repository)[1] == []
    assert release_check.scan(repository, staged=True)[1] == ["app.py:1: AI API token"]


def test_external_symlinks_are_not_read(repository, tmp_path_factory):
    external = tmp_path_factory.mktemp("outside") / "private.txt"
    external.write_text("do not read")
    (repository / "linked.txt").symlink_to(external)
    assert release_check.scan(repository)[1] == ["linked.txt: symlink or unsupported file"]
