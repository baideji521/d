"""参数实验案例库对话框。

案例 = 一份完整 Timeline JSON 快照 + 当时关注的元素 + 一句人话备注。
这就是开发指令里「参数实验模式」的落盘形式：
调参 → 预览 → 满意 → 存成案例 001 / 002 / 003，逐渐攒出自己的剪辑规则库。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
)

from PyQt5.QtCore import Qt


class SaveCaseDialog(QDialog):
    """填案例名称与备注。"""

    def __init__(self, default_name: str, summary: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("保存参数实验案例")
        self.setMinimumWidth(420)

        self._name = QLineEdit(default_name)
        self._note = QPlainTextEdit()
        self._note.setPlaceholderText(
            "记下这次实验的结论，例如：\nZoom scale_to 1.35 + Shake 0.4s，卡在鼓点上冲击感最好；1.6 就太夸张了。"
        )
        self._note.setFixedHeight(110)

        info = QLabel(summary or "将保存当前完整 Timeline JSON 作为案例快照。")
        info.setWordWrap(True)
        info.setStyleSheet("color:#7f8a99;")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("案例名称"))
        layout.addWidget(self._name)
        layout.addWidget(QLabel("实验结论 / 备注"))
        layout.addWidget(self._note)
        layout.addWidget(info)
        layout.addWidget(buttons)

    def case_name(self) -> str:
        return self._name.text().strip() or "案例"

    def case_note(self) -> str:
        return self._note.toPlainText().strip()


class CaseBrowserDialog(QDialog):
    """浏览、加载、删除案例。"""

    def __init__(self, project_manager, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("参数实验案例库")
        self.setMinimumSize(760, 480)
        self._pm = project_manager
        self._loaded: Optional[Dict[str, Any]] = None

        self._list = QListWidget()
        self._list.currentItemChanged.connect(lambda *_: self._show_detail())
        self._list.itemDoubleClicked.connect(lambda _: self._on_load())

        self._detail = QPlainTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setLineWrapMode(QPlainTextEdit.NoWrap)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._list)
        splitter.addWidget(self._detail)
        splitter.setSizes([260, 500])

        self._load_button = QPushButton("加载到时间线")
        self._load_button.clicked.connect(self._on_load)
        self._delete_button = QPushButton("删除案例")
        self._delete_button.clicked.connect(self._on_delete)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.reject)

        bar = QHBoxLayout()
        bar.addWidget(QLabel(f"案例目录：{self._pm.cases_dir()}"))
        bar.addStretch(1)
        bar.addWidget(self._load_button)
        bar.addWidget(self._delete_button)
        bar.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter)
        layout.addLayout(bar)

        self._reload()

    # ------------------------------------------------------------ 列表

    def _reload(self) -> None:
        self._list.clear()
        for case in self._pm.list_cases():
            label = f"{case.get('name', '未命名')}　{case.get('saved_at', '')}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, case)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)
        else:
            self._detail.setPlainText("还没有案例。在属性面板底部点「保存为实验案例」即可添加。")
        has_items = self._list.count() > 0
        self._load_button.setEnabled(has_items)
        self._delete_button.setEnabled(has_items)

    def _current_case(self) -> Optional[Dict[str, Any]]:
        item = self._list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _show_detail(self) -> None:
        case = self._current_case()
        if not case:
            return
        timeline = case.get("timeline") or {}
        meta = timeline.get("meta", {})
        lines = [
            f"案例名称：{case.get('name', '')}",
            f"保存时间：{case.get('saved_at', '')}",
            f"关注元素：{case.get('focus_element') or '（无）'}",
            f"项目：{meta.get('name', '')}　{meta.get('width')}×{meta.get('height')}　{meta.get('fps')}fps",
            f"时长：{meta.get('duration', 0)} 秒　元素数：{len(timeline.get('elements', []))}",
            f"文件：{case.get('_path', '')}",
            "",
            "备注：",
            case.get("note", "") or "（无）",
            "",
            "关注元素 JSON：",
        ]
        focus = case.get("focus_element")
        focus_json = "（无）"
        for element in timeline.get("elements", []):
            if element.get("id") == focus:
                focus_json = json.dumps(element, ensure_ascii=False, indent=2)
                break
        lines.append(focus_json)
        self._detail.setPlainText("\n".join(lines))

    # ------------------------------------------------------------ 操作

    def _on_load(self) -> None:
        case = self._current_case()
        if not case or not case.get("timeline"):
            return
        self._loaded = case
        self.accept()

    def _on_delete(self) -> None:
        case = self._current_case()
        if not case:
            return
        path = case.get("_path", "")
        if path and os.path.isfile(path):
            self._pm.delete_case(path)
        self._reload()

    def loaded_case(self) -> Optional[Dict[str, Any]]:
        return self._loaded
