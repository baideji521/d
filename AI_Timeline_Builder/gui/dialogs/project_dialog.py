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

from core import resolution as res
from core import safe_area as sa

FPS_PRESETS = [24.0, 25.0, 30.0, 50.0, 60.0]

#: 自定义比例在下拉里的占位 id
CUSTOM_ASPECT = "custom"


class ProjectSettingsDialog(QDialog):
    """改项目名、fps、画面比例与分辨率。

    比例与分辨率**联动**：选 3:4 时分辨率下拉只出现 3:4 的档位。
    档位表来自 core/resolution.py，那是全项目唯一的一份，
    GUI / 导出 / 文档 / 验收脚本都读它，不在这里另写一套数字。

    fps 只影响帧对齐与渲染，JSON 里的时间永远是秒。
    """

    def __init__(self, meta: Dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("项目设置")
        self.setMinimumWidth(380)

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

        width = int(meta.get("width", res.DEFAULT_RESOLUTION[0]))
        height = int(meta.get("height", res.DEFAULT_RESOLUTION[1]))

        self._aspect = QComboBox()
        for aspect_id in res.aspect_ids():
            self._aspect.addItem(res.label_of(aspect_id), aspect_id)
        self._aspect.addItem("自定义比例", CUSTOM_ASPECT)
        self._aspect.currentIndexChanged.connect(self._on_aspect_changed)

        self._resolution = QComboBox()
        self._resolution.currentIndexChanged.connect(self._on_resolution_changed)

        self._width = QDoubleSpinBox()
        self._width.setDecimals(0)
        self._width.setRange(64, 7680)
        self._width.setValue(float(width))
        self._height = QDoubleSpinBox()
        self._height.setDecimals(0)
        self._height.setRange(64, 7680)
        self._height.setValue(float(height))

        detected = res.aspect_of(width, height)
        aspect_index = self._aspect.findData(detected or CUSTOM_ASPECT)
        self._aspect.setCurrentIndex(max(0, aspect_index))
        self._reload_resolutions(keep=(width, height))

        self._background = QComboBox()
        self._background.setEditable(True)
        for preset in ("#000000", "#FFFFFF", "#101318", "#1A1A2E"):
            self._background.addItem(preset)
        self._background.setEditText(str(meta.get("background", "#000000")))

        # 安全区档位：只影响**预览参考框**，不改画面、不进渲染。
        # 各平台四边内缩不一样（抖音右侧按钮列最宽），数值在 core/safe_area.py。
        self._safe_area = QComboBox()
        for preset in sa.catalog():
            self._safe_area.addItem(preset["label"], preset["id"])
        current_preset = sa.timeline_preset({"meta": meta})
        preset_index = self._safe_area.findData(current_preset)
        self._safe_area.setCurrentIndex(max(0, preset_index))

        hint = QLabel(
            "时间线里所有时间都以秒为单位；fps 只用于帧对齐与最终渲染。\n"
            "分辨率会写进 meta.width / meta.height，一路走到 Remotion 与最终 MP4。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#7f8a99;")

        form = QFormLayout()
        form.addRow("项目名称（meta.name）", self._name)
        form.addRow("帧率（meta.fps）", self._fps)
        form.addRow("画面比例", self._aspect)
        form.addRow("分辨率档位", self._resolution)
        form.addRow("宽度（meta.width）", self._width)
        form.addRow("高度（meta.height）", self._height)
        form.addRow("背景色（meta.background）", self._background)
        form.addRow("安全区档位（meta.safe_area）", self._safe_area)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    # ---------------------------------------------------------------- 联动

    def _current_aspect(self) -> str:
        return str(self._aspect.currentData() or CUSTOM_ASPECT)

    def _index_of_resolution(self, target: Optional[Tuple[int, int]]) -> int:
        """按**值**在分辨率下拉里找档位。

        不能用 QComboBox.findData：data 是 Python 元组时 Qt 只按对象同一性比，
        (1080, 1440) 这种等值但不同对象的元组一律找不到。
        那样打开一个 1080×1440 的项目时下拉会停在第一档 810×1080，
        用户什么都没改、只点了一下确定，分辨率就被悄悄换掉了。
        """
        if target is None:
            return -1
        try:
            wanted = (int(target[0]), int(target[1]))
        except (TypeError, ValueError, IndexError):
            return -1
        for index in range(self._resolution.count()):
            data = self._resolution.itemData(index)
            if data is not None and (int(data[0]), int(data[1])) == wanted:
                return index
        return -1

    def _reload_resolutions(self, keep: Optional[Tuple[int, int]] = None) -> None:
        """按当前比例重填分辨率下拉。"""
        aspect_id = self._current_aspect()
        self._resolution.blockSignals(True)
        self._resolution.clear()
        for width, height in res.resolutions_for(aspect_id):
            self._resolution.addItem(
                f"{width}×{height}（{res.tier_label(width, height)}）", (width, height)
            )
        self._resolution.addItem("自定义", None)
        matched = self._index_of_resolution(keep)
        self._resolution.setCurrentIndex(matched if matched >= 0 else 0)
        self._resolution.blockSignals(False)
        self._on_resolution_changed()


    def _on_aspect_changed(self) -> None:
        aspect_id = self._current_aspect()
        if aspect_id == CUSTOM_ASPECT:
            self._reload_resolutions()
            return
        # 换比例时默认落到该比例的常用档（1080 宽）
        self._reload_resolutions(keep=res.default_resolution(aspect_id))

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
            # 通用档也照实写进 meta；落盘时 core/sparse.py 会把默认值那一份删掉，
            # 所以「改成抖音再改回通用」不会留下残渣。
            "safe_area": {"preset": str(self._safe_area.currentData()
                                        or sa.DEFAULT_PRESET_ID)},
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
