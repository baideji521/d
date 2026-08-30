"""新增轨道对话框。"""

from __future__ import annotations

from typing import Optional, Tuple

from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)


class TrackDialog(QDialog):
    """填轨道 id、名称、类型。"""

    def __init__(self, existing_ids, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("新增轨道")
        self.setMinimumWidth(320)
        self._existing = set(existing_ids)

        self._id_edit = QLineEdit()
        self._id_edit.setPlaceholderText("如 V5 / T3 / A4，只能用字母数字下划线")
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("如 V5 顶层贴纸")
        self._kind_box = QComboBox()
        self._kind_box.addItem("视频类（video）", "video")
        self._kind_box.addItem("文字类（text）", "text")
        self._kind_box.addItem("音频类（audio）", "audio")

        self._hint = QLabel("轨道顺序决定 Z-Index，新轨道会加在最上层，之后可以用轨道头的 ▲▼ 调整。")
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color:#7f8a99;")

        form = QFormLayout()
        form.addRow("轨道 id", self._id_edit)
        form.addRow("显示名称", self._name_edit)
        form.addRow("轨道类型", self._kind_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._hint)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        track_id = self._id_edit.text().strip()
        if not track_id or not track_id[0].isalpha() or not track_id.replace("_", "").isalnum():
            self._hint.setText("轨道 id 必须以字母开头，只能包含字母数字下划线。")
            self._hint.setStyleSheet("color:#ff6b61;")
            return
        if track_id in self._existing:
            self._hint.setText(f"轨道 {track_id} 已存在。")
            self._hint.setStyleSheet("color:#ff6b61;")
            return
        self.accept()

    def result_values(self) -> Tuple[str, str, str]:
        track_id = self._id_edit.text().strip()
        name = self._name_edit.text().strip() or track_id
        return track_id, name, self._kind_box.currentData()
