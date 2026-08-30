"""特效 / 转场 / 字幕 / 动画 / 模板 库面板。

与素材面板分开：这些不是磁盘文件，而是「参数定义」。
每一项都能拖到 Timeline 上，拖过去时主窗口会按定义生成带完整默认参数的元素。

树形结构按分类分组，选中后下方显示该项的说明与完整参数表 —— 
这张参数表就是「什么效果对应什么参数」的答案，也是 JSON 里 params 的来源。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QDrag, QFont
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core import timeline as tl
from gui.timeline_widget import make_drag_payload

SECTIONS = [
    ("effect_program", "程序特效"),
    ("effect_material", "素材特效"),
    ("transition", "转场"),
    ("caption", "字幕模板"),
    ("animation", "动画（关键帧模板）"),
    ("template", "组合模板"),
]


class LibraryTree(QTreeWidget):
    """支持拖出的库列表。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setRootIsDecorated(True)
        self.setIndentation(12)

    def startDrag(self, supported_actions) -> None:  # noqa: N802
        item = self.currentItem()
        if item is None:
            return
        payload = item.data(0, Qt.UserRole)
        if not payload:
            return
        drag = QDrag(self)
        drag.setMimeData(make_drag_payload(payload["kind"], payload["id"], payload.get("extra")))
        drag.exec_(Qt.CopyAction)


class LibraryPanel(QWidget):
    """库面板。"""

    itemActivated = pyqtSignal(dict)  # 双击直接加到时间线
    logMessage = pyqtSignal(str)

    def __init__(self, libraries, parent=None) -> None:
        super().__init__(parent)
        self._libraries = libraries

        self._section_box = QComboBox()
        for key, label in SECTIONS:
            self._section_box.addItem(label, key)
        self._section_box.currentIndexChanged.connect(lambda _i: self.refresh())

        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索名称 / 说明")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(lambda _t: self.refresh())

        self.tree = LibraryTree()
        self.tree.currentItemChanged.connect(self._on_current_changed)
        self.tree.itemDoubleClicked.connect(self._on_double_clicked)

        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setFixedHeight(150)
        font = QFont("Consolas")
        font.setPointSize(8)
        self._detail.setFont(font)

        hint = QLabel("拖到 Timeline 或双击加入。参数表即 JSON 里 params 的字段。")
        hint.setStyleSheet("color:#7f8a99;")
        hint.setWordWrap(True)

        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(self._section_box, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.addLayout(top)
        layout.addWidget(self._search)
        layout.addWidget(self.tree, 1)
        layout.addWidget(hint)
        layout.addWidget(self._detail)

        self.refresh()

    # ------------------------------------------------------------ 数据装填

    def _current_section(self) -> str:
        return self._section_box.currentData() or "effect_program"

    def _items_for_section(self, section: str) -> List[Dict[str, Any]]:
        if section == "effect_program":
            return [
                {"kind": "effect", "id": e["name"], "label": e["label"], "category": e.get("category", ""), "raw": e}
                for e in self._libraries.effect.program_effects()
            ]
        if section == "effect_material":
            return [
                {"kind": "effect_material", "id": e["name"], "label": e["label"], "category": e.get("category", ""), "raw": e}
                for e in self._libraries.effect.material_effects()
            ]
        if section == "transition":
            return [
                {"kind": "transition", "id": t["name"], "label": t["label"], "category": t.get("category", ""), "raw": t}
                for t in self._libraries.transition.all()
            ]
        if section == "caption":
            return [
                {
                    "kind": "caption",
                    "id": c["name"],
                    "label": c["label"],
                    "category": c.get("caption_style", ""),
                    "raw": c,
                }
                for c in self._libraries.caption.all()
            ]
        if section == "animation":
            return [
                {"kind": "animation", "id": a["id"], "label": a["label"], "category": a.get("category", ""), "raw": a}
                for a in self._libraries.animation.all()
            ]
        return [
            {"kind": "template", "id": t["id"], "label": t["name"], "category": "模板", "raw": t}
            for t in self._libraries.template.all()
        ]

    def refresh(self) -> None:
        section = self._current_section()
        keyword = self._search.text().strip().lower()
        items = self._items_for_section(section)

        groups: Dict[str, List[Dict[str, Any]]] = {}
        for item in items:
            raw = item["raw"]
            haystack = " ".join(
                [item["id"], item["label"], str(raw.get("description", "")), item.get("category", "")]
            ).lower()
            if keyword and keyword not in haystack:
                continue
            groups.setdefault(item.get("category") or "其他", []).append(item)

        self.tree.clear()
        for category in sorted(groups):
            parent = QTreeWidgetItem([category])
            parent.setForeground(0, QColor("#7f8a99"))
            parent.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(parent)
            for item in sorted(groups[category], key=lambda i: i["label"]):
                child = QTreeWidgetItem([item["label"]])
                child.setData(0, Qt.UserRole, {"kind": item["kind"], "id": item["id"]})
                child.setToolTip(0, item["raw"].get("description", ""))
                parent.addChild(child)
            parent.setExpanded(True)

    # ------------------------------------------------------------ 详情

    def _on_current_changed(self, current: Optional[QTreeWidgetItem], _previous) -> None:
        if current is None:
            self._detail.clear()
            return
        payload = current.data(0, Qt.UserRole)
        if not payload:
            self._detail.clear()
            return
        self._detail.setPlainText(self._describe(payload["kind"], payload["id"]))

    def _describe(self, kind: str, item_id: str) -> str:
        lines: List[str] = []
        if kind in ("effect", "effect_material"):
            effect = self._libraries.effect.get(item_id)
            if not effect:
                return ""
            element_type = "effect" if effect.get("kind") == "program" else "overlay"
            lines.append(f"name: {effect['name']}    写入 JSON 的 type: {element_type}")
            lines.append(f"默认时长: {effect['default_duration']}s")
            lines.append(f"说明: {effect.get('description', '')}")
            lines.append("")
            lines.append("参数表：")
            for param in effect.get("params", []):
                lines.append(self._describe_param(param))
        elif kind == "transition":
            transition = self._libraries.transition.get(item_id)
            if not transition:
                return ""
            lines.append(f"name: {transition['name']}    type: transition")
            lines.append(f"默认时长: {transition['default_duration']}s")
            lines.append(f"说明: {transition.get('description', '')}")
            lines.append("必须绑定 from / to 两个 Video Clip")
            lines.append("")
            lines.append("参数表：")
            for param in transition.get("params", []):
                lines.append(self._describe_param(param))
        elif kind == "caption":
            template = self._libraries.caption.get(item_id)
            if not template:
                return ""
            lines.append(f"template: {template['name']}    caption_style: {template['caption_style']}")
            lines.append(f"说明: {template.get('description', '')}")
            lines.append("")
            lines.append("style 字段：")
            for key, value in (template.get("style") or {}).items():
                lines.append(f"  {key} = {value}")
            if template.get("highlight"):
                lines.append("highlight 字段：")
                for key, value in template["highlight"].items():
                    lines.append(f"  {key} = {value}")
        elif kind == "animation":
            animation = self._libraries.animation.get(item_id)
            if not animation:
                return ""
            lines.append(f"id: {animation['id']}    时长: {animation['duration']}s")
            lines.append(f"说明: {animation.get('description', '')}")
            lines.append("这是关键帧模板，套用后写进元素的 keyframes 字段")
            lines.append("")
            for param, points in (animation.get("keyframes") or {}).items():
                label = tl.KEYFRAME_PARAM_LABELS.get(param, param)
                lines.append(f"{label}（{param}）：")
                for point in points:
                    lines.append(
                        f"  time={point.get('time')}s  value={point.get('value')}  easing={point.get('easing', 'linear')}"
                    )
        else:
            template = self._libraries.template.get(item_id)
            if not template:
                return ""
            lines.append(f"id: {template['id']}    总时长: {template.get('duration')}s")
            lines.append(f"说明: {template.get('description', '')}")
            lines.append("拖入后会展开成下列独立元素（offset 相对落点）：")
            lines.append("")
            for spec in template.get("elements", []):
                detail = f"  {spec.get('type')}"
                if spec.get("name"):
                    detail += f" / {spec['name']}"
                if spec.get("template"):
                    detail += f" / 模板 {spec['template']}"
                detail += f"  offset={spec.get('offset')}s  duration={spec.get('duration')}s  track={spec.get('track')}"
                lines.append(detail)
                for key, value in (spec.get("params") or {}).items():
                    lines.append(f"      {key} = {value}")
        return "\n".join(lines)

    @staticmethod
    def _describe_param(param: Dict[str, Any]) -> str:
        text = f"  {param['key']}（{param['label']}）  类型={param['type']}  默认={param['default']}"
        if "min" in param or "max" in param:
            text += f"  范围=[{param.get('min')}, {param.get('max')}]"
        if param.get("options"):
            text += f"  可选={param['options']}"
        if param.get("hint"):
            text += f"  说明={param['hint']}"
        return text

    def _on_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        payload = item.data(0, Qt.UserRole)
        if payload:
            self.itemActivated.emit(payload)
