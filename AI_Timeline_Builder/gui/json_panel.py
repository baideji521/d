"""JSON 面板：实时显示 Timeline JSON，并且能反过来驱动 GUI。

三条硬要求（开发指令第二十、二十一、三十条）：
1. 任何 GUI 操作后 JSON 立即更新
2. JSON 可以加载回来完整恢复 Timeline
3. 点 Timeline 元素 → JSON 自动定位高亮；点 JSON 里的元素 → Timeline 自动选中

校验结果显示在下方，错误红色、警告黄色，双击可以跳到对应元素。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class JsonPanel(QWidget):
    """JSON 显示 / 编辑 / 校验。"""

    loadRequested = pyqtSignal(dict)  # 用户加载了一份 JSON，交给主窗口套进模型
    exportRequested = pyqtSignal()
    elementPicked = pyqtSignal(str)  # 用户在 JSON 里点到某个元素
    logMessage = pyqtSignal(str)

    def __init__(self, model, validator, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._validator = validator
        self._element_lines: Dict[str, int] = {}
        self._syncing = False

        mono = QFont("Consolas")
        mono.setPointSize(9)

        self.editor = QPlainTextEdit()
        self.editor.setFont(mono)
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.cursorPositionChanged.connect(self._on_cursor_moved)

        self._edit_mode = QCheckBox("编辑模式")
        self._edit_mode.setToolTip("勾选后可以直接改 JSON，点「应用 JSON」生效")
        self._edit_mode.toggled.connect(self._on_edit_mode)

        self._apply_button = QPushButton("应用 JSON")
        self._apply_button.setEnabled(False)
        self._apply_button.clicked.connect(self._apply_editor_text)

        copy_button = QPushButton("复制 JSON")
        copy_button.clicked.connect(self._copy)

        save_button = QPushButton("保存 JSON")
        save_button.clicked.connect(self._save)

        load_button = QPushButton("加载 JSON")
        load_button.clicked.connect(self._load)

        validate_button = QPushButton("验证")
        validate_button.clicked.connect(lambda: self.validate(verbose=True))

        export_button = QPushButton("导出 Remotion")
        export_button.clicked.connect(self.exportRequested.emit)

        self._summary = QLabel("")
        self._summary.setStyleSheet("color:#7f8a99;")

        button_row = QHBoxLayout()
        button_row.setSpacing(4)
        button_row.addWidget(self._edit_mode)
        button_row.addWidget(self._apply_button)
        button_row.addWidget(copy_button)
        button_row.addWidget(save_button)
        button_row.addWidget(load_button)
        button_row.addWidget(validate_button)
        button_row.addWidget(export_button)
        button_row.addStretch(1)
        button_row.addWidget(self._summary)

        self.issue_list = QListWidget()
        self.issue_list.setFont(mono)
        self.issue_list.setMaximumHeight(120)
        self.issue_list.itemDoubleClicked.connect(self._on_issue_activated)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.editor)
        splitter.addWidget(self.issue_list)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(4)
        layout.addLayout(button_row)
        layout.addWidget(splitter, 1)

        model.timelineChanged.connect(self.refresh)
        model.elementUpdated.connect(lambda _id: self.refresh())
        model.selectionChanged.connect(self._locate_element)
        self.refresh()

    # ------------------------------------------------------------ 刷新

    def refresh(self) -> None:
        if self._edit_mode.isChecked():
            # 编辑模式下不覆盖用户正在改的文本
            return
        text = self._model.to_json_text()
        scroll = self.editor.verticalScrollBar().value()
        self._syncing = True
        self.editor.setPlainText(text)
        self._syncing = False
        self.editor.verticalScrollBar().setValue(scroll)
        self._index_elements(text)
        self.validate(verbose=False)
        self._locate_element(self._model.selected_id)

    def _index_elements(self, text: str) -> None:
        """记录每个元素 id 出现在第几行，供定位使用。"""
        self._element_lines.clear()
        for line_number, line in enumerate(text.splitlines()):
            stripped = line.strip()
            if stripped.startswith('"id":'):
                try:
                    value = json.loads("{" + stripped.rstrip(",") + "}")["id"]
                except (ValueError, KeyError):
                    continue
                # tracks 里的 id 也会命中，但元素 id 会覆盖它，且元素在后面，够用
                self._element_lines.setdefault(value, line_number)
                self._element_lines[value] = line_number

    # ------------------------------------------------------------ 双向定位

    def _locate_element(self, element_id: str) -> None:
        """Timeline → JSON：把元素所在的 JSON 块高亮并滚到可见处。"""
        self.editor.setExtraSelections([])
        if not element_id or element_id not in self._element_lines:
            return
        line = self._element_lines[element_id]
        document = self.editor.document()
        block = document.findBlockByNumber(line)
        if not block.isValid():
            return

        # 从 id 行向上找对象起始 {，向下找配对的 }
        start_line = line
        while start_line > 0:
            text = document.findBlockByNumber(start_line).text().strip()
            if text.startswith("{"):
                break
            start_line -= 1
        depth = 0
        end_line = start_line
        for probe in range(start_line, document.blockCount()):
            text = document.findBlockByNumber(probe).text()
            depth += text.count("{") - text.count("}")
            if depth <= 0:
                end_line = probe
                break

        highlight = QTextCharFormat()
        highlight.setBackground(QColor(70, 90, 130, 110))

        selections = []
        for probe in range(start_line, end_line + 1):
            probe_block = document.findBlockByNumber(probe)
            if not probe_block.isValid():
                continue
            cursor = QTextCursor(probe_block)
            cursor.select(QTextCursor.LineUnderCursor)
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format = highlight
            selections.append(selection)
        self.editor.setExtraSelections(selections)

        cursor = QTextCursor(document.findBlockByNumber(start_line))
        self._syncing = True
        self.editor.setTextCursor(cursor)
        self.editor.centerCursor()
        self._syncing = False

    def _on_cursor_moved(self) -> None:
        """JSON → Timeline：光标停在哪个元素块里，就选中那个元素。"""
        if self._syncing or self._edit_mode.isChecked():
            return
        line = self.editor.textCursor().blockNumber()
        document = self.editor.document()
        # 向上找最近的 "id"
        for probe in range(line, -1, -1):
            text = document.findBlockByNumber(probe).text().strip()
            if text.startswith('"id":'):
                try:
                    value = json.loads("{" + text.rstrip(",") + "}")["id"]
                except (ValueError, KeyError):
                    return
                if self._model.element(value) is not None:
                    self.elementPicked.emit(value)
                return
            if text.startswith('"elements"') or text.startswith('"tracks"'):
                return

    # ------------------------------------------------------------ 校验

    def validate(self, verbose: bool = False) -> List[Any]:
        issues = self._validator.validate(self._model.timeline)
        errors = [i for i in issues if i.is_error()]
        warnings = [i for i in issues if not i.is_error()]

        self.issue_list.clear()
        for issue in errors + warnings:
            item = QListWidgetItem(issue.display())
            item.setForeground(QColor("#ff6b61") if issue.is_error() else QColor("#ffc44d"))
            item.setData(Qt.UserRole, issue.element_id)
            item.setToolTip(self._validator.rule_description(issue.rule_id))
            self.issue_list.addItem(item)

        element_count = len(self._model.timeline.get("elements", []))
        self._summary.setText(
            f"元素 {element_count}  时长 {self._model.duration:.2f}s  "
            f"错误 {len(errors)}  警告 {len(warnings)}"
        )
        if verbose:
            if errors:
                QMessageBox.warning(
                    self,
                    "校验未通过",
                    f"发现 {len(errors)} 个错误、{len(warnings)} 个警告。\n\n"
                    + "\n".join(i.display() for i in errors[:12]),
                )
            else:
                QMessageBox.information(
                    self,
                    "校验通过",
                    f"没有错误。\n警告 {len(warnings)} 条（不阻塞导出）。",
                )
        return issues

    def issue_map(self) -> Dict[str, str]:
        return self._validator.invalid_element_ids(self._model.timeline)

    def _on_issue_activated(self, item: QListWidgetItem) -> None:
        element_id = item.data(Qt.UserRole)
        if element_id:
            self.elementPicked.emit(element_id)

    # ------------------------------------------------------------ 按钮

    def _copy(self) -> None:
        from PyQt5.QtWidgets import QApplication

        QApplication.clipboard().setText(self._model.to_json_text())
        self.logMessage.emit("Timeline JSON 已复制到剪贴板")

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "保存 Timeline JSON", "timeline.json", "JSON 文件 (*.json)"
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self._model.to_json_text())
        self.logMessage.emit(f"Timeline JSON 已保存：{path}")

    def _load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "加载 Timeline JSON", "", "JSON 文件 (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            QMessageBox.critical(self, "加载失败", f"无法解析 JSON：{exc}")
            return
        self.loadRequested.emit(data)
        self.logMessage.emit(f"已加载 Timeline JSON：{path}")

    def _on_edit_mode(self, enabled: bool) -> None:
        self.editor.setReadOnly(not enabled)
        self._apply_button.setEnabled(enabled)
        if not enabled:
            self.refresh()
        else:
            self.logMessage.emit("已进入 JSON 编辑模式，改完点「应用 JSON」")

    def _apply_editor_text(self) -> None:
        try:
            data = json.loads(self.editor.toPlainText())
        except json.JSONDecodeError as exc:
            QMessageBox.critical(self, "JSON 无效", f"第 {exc.lineno} 行：{exc.msg}")
            return
        self.loadRequested.emit(data)
        self._edit_mode.setChecked(False)
