"""项目相关对话框：项目设置、打开项目。"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

# 常见竖屏 / 横屏预设。分辨率与 fps 都会写进 timeline.meta，渲染端直接照用。
RESOLUTION_PRESETS = [
    ("竖屏 1080×1920（抖音/Reels）", 1080, 1920),
    ("竖屏 720×1280", 720, 1280),
    ("横屏 1920×1080", 1920, 1080),
    ("横屏 1280×720", 1280, 720),
    ("方形 1080×1080", 1080, 1080),
]

FPS_PRESETS = [24.0, 25.0, 30.0, 50.0, 60.0]


class ProjectSettingsDialog(QDialog):
    """改项目名、fps、分辨率。

    fps 只影响帧对齐与渲染，JSON 里的时间永远是秒。
    """

    def __init__(self, meta: Dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("项目设置")
        self.setMinimumWidth(360)

        self._name = QLineEdit(str(meta.get("name", "未命名项目")))

        self._fps = QComboBox()
        self._fps.setEditable(True)
        for value in FPS_PRESETS:
            self._fps.addItem(f"{value:g}", value)
        current_fps = float(meta.get("fps", 30))
        index = self._fps.findData(current_fps)
        if index >= 0:
            self._fps.setCurrentIndex(index)
        else:
            self._fps.setEditText(f"{current_fps:g}")

        self._resolution = QComboBox()
        for label, width, height in RESOLUTION_PRESETS:
            self._resolution.addItem(label, (width, height))
        self._resolution.addItem("自定义", None)
        self._resolution.currentIndexChanged.connect(self._on_resolution_changed)

        self._width = QDoubleSpinBox()
        self._width.setDecimals(0)
        self._width.setRange(64, 7680)
        self._width.setValue(float(meta.get("width", 1080)))
        self._height = QDoubleSpinBox()
        self._height.setDecimals(0)
        self._height.setRange(64, 7680)
        self._height.setValue(float(meta.get("height", 1920)))

        current = (int(meta.get("width", 1080)), int(meta.get("height", 1920)))
        matched = self._resolution.findData(current)
        self._resolution.setCurrentIndex(matched if matched >= 0 else self._resolution.count() - 1)
        self._on_resolution_changed()

        self._background = QComboBox()
        self._background.setEditable(True)
        for preset in ("#000000", "#FFFFFF", "#101318", "#1A1A2E"):
            self._background.addItem(preset)
        self._background.setEditText(str(meta.get("background", "#000000")))

        hint = QLabel("时间线里所有时间都以秒为单位；fps 只用于帧对齐与最终渲染。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#7f8a99;")

        form = QFormLayout()
        form.addRow("项目名称（meta.name）", self._name)
        form.addRow("帧率（meta.fps）", self._fps)
        form.addRow("分辨率预设", self._resolution)
        form.addRow("宽度（meta.width）", self._width)
        form.addRow("高度（meta.height）", self._height)
        form.addRow("背景色（meta.background）", self._background)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    def _on_resolution_changed(self) -> None:
        data = self._resolution.currentData()
        custom = data is None
        self._width.setEnabled(custom)
        self._height.setEnabled(custom)
        if not custom:
            self._width.setValue(float(data[0]))
            self._height.setValue(float(data[1]))

    def result_meta(self) -> Dict[str, Any]:
        try:
            fps = float(self._fps.currentText())
        except ValueError:
            fps = 30.0
        return {
            "name": self._name.text().strip() or "未命名项目",
            "fps": fps if fps > 0 else 30.0,
            "width": int(self._width.value()),
            "height": int(self._height.value()),
            "background": self._background.currentText().strip() or "#000000",
        }


class OpenProjectDialog(QDialog):
    """列出 projects/ 下的项目并选一个打开。"""

    def __init__(self, project_manager, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("打开项目")
        self.setMinimumSize(420, 320)
        self._pm = project_manager

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _: self.accept())
        for name in self._pm.list_projects():
            path = os.path.join(self._pm.projects_dir, name)
            info: Dict[str, Any] = {}
            info_path = os.path.join(path, "project.json")
            if os.path.isfile(info_path):
                try:
                    import json

                    with open(info_path, "r", encoding="utf-8") as handle:
                        info = json.load(handle)
                except (OSError, ValueError):
                    info = {}
            label = (
                f"{name}　{info.get('name', '')}　"
                f"{info.get('width', '?')}×{info.get('height', '?')} "
                f"{info.get('fps', '?')}fps　"
                f"时长 {info.get('duration', 0)}s　"
                f"保存于 {info.get('saved_at', '未知')}"
            )
            item = QListWidgetItem(label)
            item.setData(32, path)  # Qt.UserRole
            self._list.addItem(item)

        hint = QLabel(f"项目目录：{self._pm.projects_dir}")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#7f8a99;")
        if self._list.count() == 0:
            hint.setText("还没有保存过任何项目。先用「项目 → 保存项目」保存一次。")

        buttons = QDialogButtonBox(QDialogButtonBox.Open | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._list)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    def selected_dir(self) -> Optional[str]:
        item = self._list.currentItem()
        return item.data(32) if item else None
