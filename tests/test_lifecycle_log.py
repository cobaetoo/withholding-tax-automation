"""lifecycle_log smoke tests."""
import os

from src.utils import lifecycle_log as ll


def test_log_event_writes_line(tmp_path, monkeypatch):
    monkeypatch.setattr(ll, "_log_path", lambda: str(tmp_path / "lifecycle.log"))
    ll.log_event("test.event", foo="bar")
    text = (tmp_path / "lifecycle.log").read_text(encoding="utf-8")
    assert "event=test.event" in text
    assert "foo=bar" in text
    assert "pid=" in text


def test_log_event_never_raises(monkeypatch):
    def boom():
        raise OSError("no disk")

    monkeypatch.setattr(ll, "_log_path", boom)
    ll.log_event("should_not_raise")  # must not raise
