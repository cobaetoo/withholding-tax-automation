"""로그 출력 패널 — 자동화 진행 로그를 스크롤 가능한 텍스트 영역에 표시"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QLabel,
)
from PySide6.QtCore import Qt, Slot, QTimer
from PySide6.QtGui import QTextCursor


class LogPanel(QWidget):
    """하단 도킹 로그 패널.

    자동화 모듈의 print() 출력을 캡처하여 표시.
    필터 입력으로 특정 키워드만 볼 수 있음.

    병렬 CLI 로그 폭주 시 매 줄 insertPlainText 가 이벤트 루프를 막지 않도록
    짧은 배치 플러시(기본 50ms)로 묶는다.
    """

    MAX_LINES = 5000
    FLUSH_MS = 50

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_text = ""
        self._all_lines: list[str] = []
        self._pending: list[str] = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(self.FLUSH_MS)
        self._flush_timer.timeout.connect(self._flush_pending)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)

        # 상단: 라벨 + 필터
        header = QHBoxLayout()
        header.addWidget(QLabel("로그"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("필터...")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setMaximumWidth(250)
        self.filter_edit.textChanged.connect(self._apply_filter)
        header.addStretch()
        header.addWidget(self.filter_edit)
        layout.addLayout(header)

        # 로그 텍스트
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setStyleSheet(
            "QTextEdit { font-family: 'Consolas', '맑은 고딕', monospace; "
            "font-size: 12px; background-color: #1e1e1e; color: #d4d4d4; }"
        )
        layout.addWidget(self.text_edit)

    @Slot(str)
    def append_log(self, message: str):
        """로그 메시지 추가 (LogCapture Signal에서 호출)"""
        self._all_lines.append(message)

        # 최대 줄 수 제한
        if len(self._all_lines) > self.MAX_LINES:
            self._all_lines = self._all_lines[-self.MAX_LINES:]

        # 필터 적용
        if self._filter_text and self._filter_text.lower() not in message.lower():
            return

        self._pending.append(message)
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush_pending(self):
        if not self._pending:
            return
        chunk = "\n".join(self._pending) + "\n"
        self._pending.clear()
        self.text_edit.moveCursor(QTextCursor.End)
        self.text_edit.insertPlainText(chunk)
        sb = self.text_edit.verticalScrollBar()
        if sb.value() >= sb.maximum() - 20:
            sb.setValue(sb.maximum())

    def _append_line(self, text: str):
        self.text_edit.moveCursor(QTextCursor.End)
        self.text_edit.insertPlainText(text + "\n")

        # 자동 스크롤 (스크롤바가 맨 아래에 있을 때만)
        sb = self.text_edit.verticalScrollBar()
        if sb.value() >= sb.maximum() - 20:
            sb.setValue(sb.maximum())

    def _apply_filter(self, text: str):
        self._flush_pending()
        self._filter_text = text.strip()
        self.text_edit.clear()
        for line in self._all_lines:
            if not self._filter_text or self._filter_text.lower() in line.lower():
                self._append_line(line)
