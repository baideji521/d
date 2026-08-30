"""插入转场对话框。

转场必须绑定 from clip / to clip 两个视频片段，这一点在 rules.json 的
RULE_TRANSITION_001 里也是硬要求，所以对话框里不允许只选一个。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
)

from core import timeline as tl


class TransitionDialog(QDialog):
    """选择转场类型、时长、绑定的两个片段，并填参数。"""

    def __init__(
        self,
        timeline: Dict[str, Any],
        transition_library,
        from_id: str = "",
        to_id: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("插入转场")
        self.setMinimumWidth(420)
        self._timeline = timeline
        self._lib = transition_library
        self._param_widgets: Dict[str, Any] = {}

        # 只有视频片段能当转场的两端
        self._clips: List[Dict[str, Any]] = sorted(
            [e for e in timeline.get("elements", []) if e.get("type") == "video"],
            key=lambda e: float(e.get("start", 0.0)),
        )

        self._name_box = QComboBox()
        for item in sorted(self._lib.all(), key=lambda t: (t.get("category", ""), t.get("label", ""))):
            self._name_box.addItem(f"[{item.get('category', '')}] {item.get('label')}", item.get("name"))
        self._name_box.currentIndexChanged.connect(self._on_name_changed)

        self._from_box = QComboBox()
        self._to_box = QComboBox()
        for box in (self._from_box, self._to_box):
            for clip in self._clips:
                box.addItem(self._clip_label(clip), clip.get("id"))

        self._duration = QDoubleSpinBox()
        self._duration.setDecimals(3)
        self._duration.setRange(0.04, 10.0)
        self._duration.setSingleStep(0.05)
        self._duration.setSuffix(" 秒")

        self._auto_place = QCheckBox("自动放在两个片段的衔接点上")
        self._auto_place.setChecked(True)
        self._start = QDoubleSpinBox()
        self._start.setDecimals(3)
        self._start.setRange(0.0, 3600.0)
        self._start.setSingleStep(0.1)
        self._start.setSuffix(" 秒")
        self._auto_place.toggled.connect(lambda on: self._start.setEnabled(not on))
        self._start.setEnabled(False)

        self._desc = QLabel()
        self._desc.setWordWrap(True)
        self._desc.setStyleSheet("color:#7f8a99;")

        self._param_group = QGroupBox("转场参数")
        self._param_form = QFormLayout(self._param_group)

        base_form = QFormLayout()
        base_form.addRow("转场类型", self._name_box)
        base_form.addRow("from clip（前一段）", self._from_box)
        base_form.addRow("to clip（后一段）", self._to_box)
        base_form.addRow("转场时长", self._duration)
        base_form.addRow("放置位置", self._auto_place)
        base_form.addRow("start", self._start)

        self._hint = QLabel("转场时长之后还可以在时间线上拖动边界继续调整。")
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color:#7f8a99;")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(base_form)
        layout.addWidget(self._desc)
        layout.addWidget(self._param_group)
        layout.addWidget(self._hint)
        layout.addWidget(buttons)

        self._preselect(from_id, to_id)
        self._on_name_changed()

    # ------------------------------------------------------------ 初始化辅助

    def _clip_label(self, clip: Dict[str, Any]) -> str:
        start = float(clip.get("start", 0.0))
        end = tl.element_end(clip)
        return f"{clip.get('id')}（{start:.2f}s → {end:.2f}s，{clip.get('track')}）"

    def _preselect(self, from_id: str, to_id: str) -> None:
        """优先用调用方给的两个 id；没给就猜相邻的两段。"""
        if from_id:
            index = self._from_box.findData(from_id)
            if index >= 0:
                self._from_box.setCurrentIndex(index)
        if to_id:
            index = self._to_box.findData(to_id)
            if index >= 0:
                self._to_box.setCurrentIndex(index)
        if not from_id and len(self._clips) >= 2:
            self._from_box.setCurrentIndex(0)
            self._to_box.setCurrentIndex(1)

    # ------------------------------------------------------------ 参数区

    def _on_name_changed(self) -> None:
        name = self._name_box.currentData()
        item = self._lib.get(name) or {}
        self._desc.setText(item.get("description", ""))
        self._duration.setValue(self._lib.default_duration(name))
        while self._param_form.rowCount():
            self._param_form.removeRow(0)
        self._param_widgets.clear()
        for spec in item.get("params", []):
            widget = self._make_param_widget(spec)
            if widget is None:
                continue
            self._param_widgets[spec["key"]] = widget
            self._param_form.addRow(f"{spec.get('label', spec['key'])}（params.{spec['key']}）", widget)
        self._param_group.setVisible(bool(self._param_widgets))

    def _make_param_widget(self, spec: Dict[str, Any]):
        kind = spec.get("type", "number")
        if kind == "number":
            box = QDoubleSpinBox()
            box.setDecimals(3)
            box.setRange(float(spec.get("min", -9999.0)), float(spec.get("max", 9999.0)))
            box.setSingleStep(float(spec.get("step", 0.05)))
            box.setValue(float(spec.get("default", 0.0)))
            return box
        if kind == "enum":
            box = QComboBox()
            for option in spec.get("options", []):
                box.addItem(str(option), option)
            index = box.findData(spec.get("default"))
            if index >= 0:
                box.setCurrentIndex(index)
            return box
        if kind == "color":
            box = QComboBox()
            box.setEditable(True)
            for preset in ("#000000", "#FFFFFF", "#FFE347", "#FF3B30", "#00E0FF"):
                box.addItem(preset)
            box.setEditText(str(spec.get("default", "#000000")))
            return box
        if kind == "bool":
            box = QCheckBox()
            box.setChecked(bool(spec.get("default", False)))
            return box
        box = QComboBox()
        box.setEditable(True)
        box.setEditText(str(spec.get("default", "")))
        return box

    def _read_param(self, widget) -> Any:
        if isinstance(widget, QDoubleSpinBox):
            return round(widget.value(), 3)
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QComboBox):
            if widget.isEditable():
                return widget.currentText().strip()
            return widget.currentData()
        return None

    # ------------------------------------------------------------ 确认

    def _on_accept(self) -> None:
        from_id = self._from_box.currentData()
        to_id = self._to_box.currentData()
        if not from_id or not to_id:
            self._hint.setText("时间线上至少需要两个视频片段才能插入转场。")
            self._hint.setStyleSheet("color:#ff6b61;")
            return
        if from_id == to_id:
            self._hint.setText("from clip 与 to clip 不能是同一个片段。")
            self._hint.setStyleSheet("color:#ff6b61;")
            return
        self.accept()

    def result_element(self, element_id: str) -> Optional[Dict[str, Any]]:
        """生成转场元素的 JSON。start 默认取 from clip 的结束点前推半个转场时长。"""
        from_id = self._from_box.currentData()
        to_id = self._to_box.currentData()
        from_clip = tl.get_element(self._timeline, from_id)
        to_clip = tl.get_element(self._timeline, to_id)
        if from_clip is None or to_clip is None:
            return None
        duration = round(self._duration.value(), 3)
        if self._auto_place.isChecked():
            boundary = tl.element_end(from_clip)
            start = max(0.0, round(boundary - duration / 2.0, 3))
        else:
            start = round(self._start.value(), 3)
        params = {key: self._read_param(widget) for key, widget in self._param_widgets.items()}
        return tl.make_transition(
            element_id,
            self._name_box.currentData(),
            from_id,
            to_id,
            start,
            duration,
            params,
            track=from_clip.get("track", "V1"),
        )
