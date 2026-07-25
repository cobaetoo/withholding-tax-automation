"""TD-02 / TD-10 / TD-17: 배치 포털 스코프·크래시 표시·_reset_batch 정책."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.batch.db import BatchDB, BatchRepository, ClientRepository
from src.batch.models import BatchStatus, Client, make_batch_key
from src.ui.workers.automation_runner import AutomationRunner


def _fresh_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def _insert_batch(db: BatchDB, portal: str, year: int, month: int, status: str) -> int:
    key = make_batch_key(year, month, portal)
    now = "2026-07-25 12:00:00"
    cur = db.conn.execute(
        """INSERT INTO batches
           (batch_key, portal, target_year, target_month, status,
            started_at, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (key, portal, year, month, status, now, now, now),
    )
    return cur.lastrowid


def _call_reset(db_path: str, portal: str, phase_id: int) -> None:
    # _reset_batch 는 self 미사용 — QObject 인스턴스 없이 unbound 호출
    AutomationRunner._reset_batch(None, db_path, portal, phase_id)


def test_mark_crashed_scoped_to_portal():
    """TD-10: portal 지정 시 타 포털 running 배치는 건드리지 않음."""
    path = _fresh_db()
    try:
        with BatchDB(path) as db:
            repo = BatchRepository(db)
            id_w = _insert_batch(db, "wehago", 2026, 7, "running")
            id_n = _insert_batch(db, "nhis_edi", 2026, 7, "running")
            crashed = repo.mark_crashed_as_recoverable("wehago")
            assert len(crashed) == 1
            assert crashed[0].portal == "wehago"
            assert repo.get(id_w).status == BatchStatus.CRASHED
            assert repo.get(id_n).status == "running"
    finally:
        os.unlink(path)


def test_reset_batch_keeps_crashed_deletes_completed():
    """TD-02: completed 만 삭제, crashed 유지 → prepare 복구 가능."""
    path = _fresh_db()
    try:
        with BatchDB(path) as db:
            id_done = _insert_batch(db, "wehago", 2026, 6, "completed")
            id_crash = _insert_batch(db, "wehago", 2026, 7, "crashed")
            id_other = _insert_batch(db, "nhis_edi", 2026, 7, "completed")

        _call_reset(path, "wehago", phase_id=6)

        with BatchDB(path) as db:
            repo = BatchRepository(db)
            assert repo.get(id_done) is None, "completed wehago 배치 삭제"
            assert repo.get(id_crash) is not None, "crashed 유지"
            assert repo.get(id_crash).status == BatchStatus.CRASHED
            assert repo.get(id_other) is not None, "타 포털 completed 유지"
    finally:
        os.unlink(path)


def test_reset_batch_marks_running_as_crashed():
    path = _fresh_db()
    try:
        with BatchDB(path) as db:
            id_run = _insert_batch(db, "wehago", 2026, 7, "running")

        _call_reset(path, "wehago", phase_id=6)

        with BatchDB(path) as db:
            b = BatchRepository(db).get(id_run)
            assert b is not None
            assert b.status == BatchStatus.CRASHED
    finally:
        os.unlink(path)


def test_reset_batch_list_phase_does_not_wipe_clients():
    """TD-17: list phase _reset_batch 가 clients 를 지우지 않음."""
    import src.workflows.wehago_list_clients  # noqa: F401 — phase 1 등록

    path = _fresh_db()
    try:
        with BatchDB(path) as db:
            ClientRepository(db).upsert(Client(
                name="유지회사", portal="wehago",
                business_number="111-22-33333", enabled=True,
            ))
            _insert_batch(db, "wehago", 2026, 7, "completed")

        _call_reset(path, "wehago", phase_id=1)

        with BatchDB(path) as db:
            c = ClientRepository(db).get_by_name("유지회사", "wehago")
            assert c is not None
            # list phase 는 no-op — completed 배치도 유지
            assert BatchRepository(db).get_latest("wehago") is not None
    finally:
        os.unlink(path)
