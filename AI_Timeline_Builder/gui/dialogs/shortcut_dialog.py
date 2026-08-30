"""快捷键速查面板（F1）。

内容全部从 gui/shortcuts.py 生成，改键位只需要改那一个文件，
面板不会和实际生效的键位对不上。
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from gui import shortcuts


class ShortcutDialog(QDialog):
    """按分组列出所有快捷键，另附鼠标操作说明。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("快捷键速查")
        self.resize(560, 640)

        tree = QTreeWidget()
        tree.setHeaderLabels(["操作", "键位"])
        tree.setColumnWidth(0, 320)
        tree.setRootIsDecorated(True)
        tree.setAlternatingRowColors(True)

        for group_name, action_keys in shortcuts.GROUPS:
            group = QTreeWidgetItem(tree, [group_name, ""])
            group.setFirstColumnSpanned(True)
            for action_key in action_keys:
                QTreeWidgetItem(
                    group,
                    [shortcuts.LABELS.get(action_key, action_key), shortcuts.display(action_key)],
                )
            group.setExpanded(True)

        mouse_group = QTreeWidgetItem(tree, ["鼠标操作", ""])
        mouse_group.setFirstColumnSpanned(True)
        for gesture, effect in shortcuts.MOUSE_TIPS:
            QTreeWidgetItem(mouse_group, [effect, gesture])
        mouse_group.setExpanded(True)

        hint = QLabel(
            "键位以剪映习惯为准。方向键 / 空格这类单键在时间线或预览有焦点时都能用；"
            "如果按了没反应，先点一下时间线空白处把焦点交回主窗口。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#7f8a99;")

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(tree, 1)
        layout.addWidget(hint)
        layout.addWidget(buttons)
