"""find_jitax_encrypted_file — 확장자 필터·mtime 선택 (FS only, 브라우저 없음)."""
from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

from src.automation.wetax._form import find_jitax_encrypted_file


def _touch(path: Path, mtime: float | None = None) -> None:
    path.write_bytes(b"x")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_empty_dir_returns_none(tmp_path):
    with patch(
        "src.automation.wetax._form.make_save_dir",
        return_value=str(tmp_path),
    ):
        assert find_jitax_encrypted_file("수임A", year=2026, month=7) is None


def test_missing_dir_returns_none(tmp_path):
    missing = tmp_path / "nope"
    with patch(
        "src.automation.wetax._form.make_save_dir",
        return_value=str(missing),
    ):
        assert find_jitax_encrypted_file("수임A", year=2026, month=7) is None


def test_wrong_extension_skipped(tmp_path):
    _touch(tmp_path / "notes.txt")
    _touch(tmp_path / "report.xlsx")
    _touch(tmp_path / "readme.md")
    with patch(
        "src.automation.wetax._form.make_save_dir",
        return_value=str(tmp_path),
    ):
        assert find_jitax_encrypted_file("수임A", year=2026, month=7) is None


def test_dot2_chosen_by_mtime(tmp_path):
    base = time.time()
    older = tmp_path / "old.2"
    newer = tmp_path / "new.2"
    _touch(older, base - 100)
    _touch(newer, base)
    # 잘못된 확장자는 무시
    _touch(tmp_path / "noise.pdf", base + 50)
    with patch(
        "src.automation.wetax._form.make_save_dir",
        return_value=str(tmp_path),
    ):
        got = find_jitax_encrypted_file("수임A", year=2026, month=7)
    assert got is not None
    assert os.path.basename(got) == "new.2"


def test_dot1_accepted(tmp_path):
    _touch(tmp_path / "efile.1")
    with patch(
        "src.automation.wetax._form.make_save_dir",
        return_value=str(tmp_path),
    ):
        got = find_jitax_encrypted_file("수임A", year=2026, month=7)
    assert got is not None
    assert got.endswith(".1")


def test_extension_case_insensitive(tmp_path):
    _touch(tmp_path / "FILE.2")
    with patch(
        "src.automation.wetax._form.make_save_dir",
        return_value=str(tmp_path),
    ):
        got = find_jitax_encrypted_file("수임A", year=2026, month=7)
    assert got is not None
    assert os.path.basename(got).upper().endswith(".2")
