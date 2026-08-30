"""属性面板：当前选中元素的全部参数。

这是「参数实验模式」的主战场（开发指令第二十九条）：
每个控件都严格对应 Timeline JSON 里的一个字段，改控件 → 改 JSON → 预览刷新。
控件旁边直接标出 JSON 字段路径，所以看着界面就能知道 AI 该写什么。

面板按元素类型动态重建。为了避免「自己改字段 → 模型发信号 → 面板重建 → 输入框失焦」
的死循环，写入期间用 _suppress 计数器屏蔽重建。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core import timeline as tl
from core.time_utils import format_seconds
from libraries.caption_library import CAPTION_STYLES


class PropertyPanel(QScrollArea):
    """选中元素的参数编辑器。"""

    saveCaseRequested = pyqtSignal()
    logMessage = pyqtSignal(str)

    def __init__(self, model, asset_manager, libraries, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._assets = asset_manager
        self._libraries = libraries
        self._suppress = 0

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(8)
        self._layout.setAlignment(Qt.AlignTop)

        self.setWidget(self._container)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)

        model.selectionChanged.connect(lambda _id: self.rebuild())
        model.timelineChanged.connect(self._on_timeline_changed)
        model.elementUpdated.connect(lambda _id: self._on_timeline_changed())
        self.rebuild()

    # ------------------------------------------------------------ 重建控制

    def _on_timeline_changed(self) -> None:
        if self._suppress > 0:
            return
        self.rebuild()

    def _write(self, path: List[str], value: Any, description: str = "") -> None:
        """统一的写入口，带重建屏蔽。"""
        element_id = self._model.selected_id
        if not element_id:
            return
        self._suppress += 1
        try:
            self._model.set_element_field(element_id, path, value, description)
        finally:
            self._suppress -= 1
        self._refresh_derived()

    def _clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def rebuild(self) -> None:
        self._clear()
        element = self._model.element(self._model.selected_id)
        if element is None:
            hint = QLabel(
                "未选中元素。\n\n"
                "在 Timeline 里点一个元素，或从左侧素材/库面板拖一个进来。\n"
                "选中后这里会列出它在 Timeline JSON 里的全部字段。"
            )
            hint.setWordWrap(True)
            hint.setStyleSheet("color:#7f8a99;")
            self._layout.addWidget(hint)
            return

        self._layout.addWidget(self._build_identity(element))
        self._layout.addWidget(self._build_timing(element))

        etype = element.get("type")
        if etype == "video":
            self._layout.addWidget(self._build_video(element))
        elif etype == "overlay":
            self._layout.addWidget(self._build_overlay(element))
        elif etype == "text":
            self._layout.addWidget(self._build_text(element))
        elif etype in ("caption", "caption_group"):
            self._layout.addWidget(self._build_caption(element))
        elif etype == "audio":
            self._layout.addWidget(self._build_audio(element))
        elif etype == "effect":
            self._layout.addWidget(self._build_effect(element))
        elif etype == "transition":
            self._layout.addWidget(self._build_transition(element))
        elif etype == "freeze":
            self._layout.addWidget(self._build_freeze(element))

        # 按类型判断有没有 transform 语义 —— 稀疏 JSON 里没有 transform 字段是常态
        if tl.supports_transform(element):
            self._layout.addWidget(self._build_transform(element))
        if etype not in ("transition",):
            self._layout.addWidget(self._build_keyframes(element))
        self._layout.addWidget(self._build_case_box(element))

    # ------------------------------------------------------------ 控件工厂

    @staticmethod
    def _group(title: str) -> QGroupBox:
        box = QGroupBox(title)
        box.setStyleSheet(
            "QGroupBox{color:#c8d2df;border:1px solid #2f3846;border-radius:4px;margin-top:8px;padding-top:8px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}"
        )
        return box

    @staticmethod
    def _json_label(path: str) -> QLabel:
        label = QLabel(path)
        label.setStyleSheet("color:#5f6b7c;font-family:Consolas;font-size:10px;")
        return label

    def _row(self, form: QFormLayout, label: str, json_path: str, widget: QWidget) -> None:
        """一行 = 中文标签 + 控件 + JSON 路径提示。"""
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(1)
        box.addWidget(widget)
        box.addWidget(self._json_label(json_path))
        form.addRow(label, holder)

    def _number(
        self,
        value: float,
        on_change: Callable[[float], None],
        minimum: float = -100000.0,
        maximum: float = 100000.0,
        step: float = 0.01,
        decimals: int = 3,
        suffix: str = "",
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setDecimals(decimals)
        spin.setValue(float(value))
        if suffix:
            spin.setSuffix(suffix)
        spin.setKeyboardTracking(False)
        spin.valueChanged.connect(on_change)
        return spin

    def _integer(
        self,
        value: int,
        on_change: Callable[[int], None],
        minimum: int = -100000,
        maximum: int = 100000,
    ) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(int(value))
        spin.setKeyboardTracking(False)
        spin.valueChanged.connect(on_change)
        return spin

    def _combo(
        self,
        options: List[tuple],
        current: Any,
        on_change: Callable[[Any], None],
    ) -> QComboBox:
        combo = QComboBox()
        for value, label in options:
            combo.addItem(label, value)
        index = combo.findData(current)
        if index >= 0:
            combo.setCurrentIndex(index)
        combo.currentIndexChanged.connect(lambda _i: on_change(combo.currentData()))
        return combo

    def _color_button(self, value: str, on_change: Callable[[str], None]) -> QPushButton:
        button = QPushButton(value or "#FFFFFF")
        button.setStyleSheet(f"background-color:{value or '#FFFFFF'};color:#111;")

        def pick() -> None:
            color = QColorDialog.getColor(QColor(value or "#FFFFFF"), self, "选择颜色")
            if color.isValid():
                hex_value = color.name().upper()
                button.setText(hex_value)
                button.setStyleSheet(f"background-color:{hex_value};color:#111;")
                on_change(hex_value)

        button.clicked.connect(pick)
        return button

    def _asset_combo(self, asset_type: str, current: str, on_change: Callable[[str], None]) -> QComboBox:
        combo = QComboBox()
        combo.addItem("（未选择）", "")
        for asset in self._assets.search(asset_type=asset_type):
            combo.addItem(f"{asset['id']}  {asset.get('name','')}", asset["id"])
        # overlay 类型也允许选 image，素材目录归类不一定严格
        if asset_type == "overlay":
            for asset in self._assets.search(asset_type="image"):
                combo.addItem(f"{asset['id']}  {asset.get('name','')}", asset["id"])
        index = combo.findData(current)
        if index >= 0:
            combo.setCurrentIndex(index)
        combo.currentIndexChanged.connect(lambda _i: on_change(combo.currentData() or ""))
        return combo

    # ------------------------------------------------------------ 各分组

    def _build_identity(self, element: Dict[str, Any]) -> QWidget:
        box = self._group("身份")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignRight)

        id_label = QLabel(element.get("id", ""))
        id_label.setFont(QFont("Consolas"))
        id_label.setStyleSheet("color:#ffe347;")
        self._row(form, "元素 id", "id", id_label)

        type_label = QLabel(
            f"{tl.ELEMENT_TYPE_LABELS.get(element.get('type'), element.get('type'))}"
            f"（{element.get('type')}）"
        )
        self._row(form, "类型", "type", type_label)

        track_options = [
            (t["id"], f"{t['name']}（{t['kind']}）")
            for t in self._model.tracks()
            if t.get("kind") == tl.TYPE_TRACK_KIND.get(element.get("type", ""))
        ]
        if track_options:
            self._row(
                form,
                "轨道",
                "track",
                self._combo(
                    track_options,
                    element.get("track"),
                    lambda value: self._write(["track"], value, "修改轨道"),
                ),
            )

        note = QLineEdit(element.get("note", ""))
        note.setPlaceholderText("实验备注，不影响渲染")
        note.editingFinished.connect(lambda: self._write(["note"], note.text(), "修改备注"))
        self._row(form, "备注", "note", note)
        return box

    def _build_timing(self, element: Dict[str, Any]) -> QWidget:
        box = self._group("时间（单位：秒，禁止出现帧）")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignRight)

        self._row(
            form,
            "时间线开始",
            "start",
            self._number(
                element.get("start", 0.0),
                lambda value: self._write(["start"], round(value, 3), "修改开始时间"),
                minimum=0.0,
                step=0.1,
                suffix=" s",
            ),
        )
        self._row(
            form,
            "持续时间",
            "duration",
            self._number(
                element.get("duration", 0.0),
                lambda value: self._write(["duration"], round(value, 3), "修改持续时间"),
                minimum=0.01,
                step=0.1,
                suffix=" s",
            ),
        )

        self._end_label = QLabel(format_seconds(tl.element_end(element)))
        self._end_label.setFont(QFont("Consolas"))
        self._row(form, "时间线结束", "start + duration（派生值）", self._end_label)

        frames = int(round(float(element.get("duration", 0.0)) * self._model.fps))
        frame_label = QLabel(f"{frames} 帧 @ {self._model.fps:g}fps")
        frame_label.setStyleSheet("color:#7f8a99;")
        self._row(form, "换算参考", "渲染时 frame = round(秒 × fps)", frame_label)
        return box

    def _build_video(self, element: Dict[str, Any]) -> QWidget:
        box = self._group("视频片段")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignRight)

        self._row(
            form,
            "素材",
            "asset（只存 id，不存路径）",
            self._asset_combo(
                "video", element.get("asset", ""), lambda value: self._write(["asset"], value, "更换素材")
            ),
        )

        asset = self._assets.get(element.get("asset", ""))
        media_duration = float(asset.get("duration", 0.0)) if asset else 0.0
        info = QLabel(
            f"源素材总长 {media_duration:.2f}s"
            + (f"，{asset.get('width')}×{asset.get('height')} @ {asset.get('fps')}fps" if asset else "")
        )
        info.setStyleSheet("color:#7f8a99;")
        form.addRow("素材信息", info)

        # 面板只读，不往元素里写默认值（写回会污染稀疏 JSON）
        source = element.get("source") or {"start": 0.0, "end": 1.0}
        self._row(
            form,
            "原素材开始",
            "source.start",
            self._number(
                source.get("start", 0.0),
                lambda value: self._write(["source", "start"], round(value, 3), "修改源起点"),
                minimum=0.0,
                maximum=max(1.0, media_duration),
                step=0.1,
                suffix=" s",
            ),
        )
        self._row(
            form,
            "原素材结束",
            "source.end",
            self._number(
                source.get("end", 1.0),
                lambda value: self._write(["source", "end"], round(value, 3), "修改源终点"),
                minimum=0.0,
                maximum=max(1.0, media_duration) if media_duration else 100000.0,
                step=0.1,
                suffix=" s",
            ),
        )
        span = QLabel(f"{float(source.get('end', 0)) - float(source.get('start', 0)):.3f}s")
        span.setStyleSheet("color:#7f8a99;")
        form.addRow("源区间长度", span)

        self._row(
            form,
            "速度",
            "speed（duration = 源区间 / speed）",
            self._number(
                element.get("speed", 1.0),
                lambda value: self._write(["speed"], round(value, 3), "修改速度"),
                minimum=0.05,
                maximum=8.0,
                step=0.05,
                suffix=" ×",
            ),
        )

        # 阶段 6.5：只读取「生效值」，不能 setdefault 把默认值写回元素，
        # 否则光是打开属性面板就会往 JSON 里塞 audio 默认值
        audio = tl.effective_audio(element)
        enabled = QCheckBox("保留原声")
        enabled.setChecked(bool(audio["enabled"]))
        enabled.toggled.connect(lambda value: self._write(["audio", "enabled"], value, "切换原声"))
        self._row(form, "原声", "audio.enabled", enabled)
        self._row(
            form,
            "原声音量",
            "audio.volume",
            self._number(
                audio["volume"],
                lambda value: self._write(["audio", "volume"], round(value, 2), "修改原声音量"),
                minimum=0.0,
                maximum=4.0,
                step=0.05,
                decimals=2,
            ),
        )
        return box

    def _build_overlay(self, element: Dict[str, Any]) -> QWidget:
        box = self._group("图片 / Overlay")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignRight)
        self._row(
            form,
            "素材",
            "asset",
            self._asset_combo(
                "overlay", element.get("asset", ""), lambda value: self._write(["asset"], value, "更换素材")
            ),
        )
        asset = self._assets.get(element.get("asset", ""))
        if asset:
            info = QLabel(
                f"{asset.get('width')}×{asset.get('height')}"
                + ("，含透明通道" if asset.get("has_alpha") else "")
            )
            info.setStyleSheet("color:#7f8a99;")
            form.addRow("素材信息", info)
        return box

    def _build_text(self, element: Dict[str, Any]) -> QWidget:
        box = self._group("文字")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignRight)

        editor = QPlainTextEdit((element.get("content") or {}).get("text", ""))
        editor.setFixedHeight(60)
        editor.textChanged.connect(
            lambda: self._write(["content", "text"], editor.toPlainText(), "修改文字内容")
        )
        self._row(form, "内容", "content.text", editor)
        self._add_style_rows(form, element)
        return box

    def _build_caption(self, element: Dict[str, Any]) -> QWidget:
        box = self._group("字幕")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignRight)

        templates = [(t["name"], t["label"]) for t in self._libraries.caption.all()]
        self._row(
            form,
            "模板",
            "template",
            self._combo(
                templates,
                element.get("template", ""),
                self._apply_caption_template,
            ),
        )
        self._row(
            form,
            "表现形式",
            "caption_style",
            self._combo(
                list(CAPTION_STYLES),
                element.get("caption_style", "plain"),
                lambda value: self._write(["caption_style"], value, "修改字幕样式"),
            ),
        )

        content = element.get("content") or {}
        if element.get("type") == "caption_group" or content.get("words"):
            self._layout_words_editor(form, element)
        else:
            editor = QPlainTextEdit(content.get("text", ""))
            editor.setFixedHeight(56)
            editor.textChanged.connect(
                lambda: self._write(["content", "text"], editor.toPlainText(), "修改字幕文本")
            )
            self._row(form, "文本", "content.text", editor)

        highlight = element.get("highlight") or {
            "color": "#FFE347", "backgroundColor": "", "scale": 1.1
        }
        self._row(
            form,
            "高亮颜色",
            "highlight.color",
            self._color_button(
                highlight.get("color", "#FFE347"),
                lambda value: self._write(["highlight", "color"], value, "修改高亮色"),
            ),
        )
        self._row(
            form,
            "高亮放大",
            "highlight.scale",
            self._number(
                highlight.get("scale", 1.1),
                lambda value: self._write(["highlight", "scale"], round(value, 2), "修改高亮缩放"),
                minimum=0.5,
                maximum=3.0,
                step=0.01,
                decimals=2,
            ),
        )

        self._add_style_rows(form, element)

        save_button = QPushButton("把当前样式存成字幕模板")
        save_button.clicked.connect(lambda: self._save_caption_template(element))
        form.addRow("", save_button)
        return box

    def _layout_words_editor(self, form: QFormLayout, element: Dict[str, Any]) -> None:
        """逐词字幕的 words 编辑：一行一个词，格式 文本|开始|结束。"""
        words = (element.get("content") or {}).get("words") or []
        text = "\n".join(
            f"{w.get('text','')}|{w.get('start',0)}|{w.get('end',0)}" for w in words
        )
        editor = QPlainTextEdit(text)
        editor.setFixedHeight(110)
        editor.setFont(QFont("Consolas"))

        def commit() -> None:
            parsed: List[Dict[str, Any]] = []
            for line in editor.toPlainText().splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) != 3:
                    continue
                try:
                    parsed.append(
                        {
                            "text": parts[0].strip(),
                            "start": round(float(parts[1]), 3),
                            "end": round(float(parts[2]), 3),
                        }
                    )
                except ValueError:
                    continue
            if not parsed:
                return
            self._write(["content", "words"], parsed, "修改逐词字幕")
            start = min(w["start"] for w in parsed)
            end = max(w["end"] for w in parsed)
            self._write(["start"], round(start, 3), "同步字幕起点")
            self._write(["duration"], round(max(0.04, end - start), 3), "同步字幕时长")

        editor.focusOutEvent = self._wrap_focus_out(editor, commit)  # type: ignore[assignment]
        self._row(
            form,
            "逐词（文本|开始|结束）",
            "content.words[]（时间为绝对秒数）",
            editor,
        )

    @staticmethod
    def _wrap_focus_out(widget: QWidget, callback: Callable[[], None]):
        original = type(widget).focusOutEvent

        def handler(event):  # noqa: ANN001
            original(widget, event)
            callback()

        return handler

    def _add_style_rows(self, form: QFormLayout, element: Dict[str, Any]) -> None:
        style = element.get("style") or {}
        stroke = style.get("stroke") or {"width": 0, "color": "#000000"}

        font_edit = QLineEdit(style.get("fontFamily", "Arial"))
        font_edit.editingFinished.connect(
            lambda: self._write(["style", "fontFamily"], font_edit.text(), "修改字体")
        )
        self._row(form, "字体", "style.fontFamily", font_edit)

        self._row(
            form,
            "字号",
            "style.fontSize（按项目分辨率的像素值）",
            self._number(
                style.get("fontSize", 64),
                lambda value: self._write(["style", "fontSize"], round(value, 1), "修改字号"),
                minimum=4.0,
                maximum=600.0,
                step=2.0,
                decimals=1,
            ),
        )
        self._row(
            form,
            "字重",
            "style.fontWeight（100–900）",
            self._integer(
                style.get("fontWeight", 700),
                lambda value: self._write(["style", "fontWeight"], value, "修改字重"),
                minimum=100,
                maximum=900,
            ),
        )
        self._row(
            form,
            "颜色",
            "style.color",
            self._color_button(
                style.get("color", "#FFFFFF"),
                lambda value: self._write(["style", "color"], value, "修改文字颜色"),
            ),
        )
        self._row(
            form,
            "对齐",
            "style.align",
            self._combo(
                [("left", "左对齐"), ("center", "居中"), ("right", "右对齐")],
                style.get("align", "center"),
                lambda value: self._write(["style", "align"], value, "修改对齐"),
            ),
        )
        self._row(
            form,
            "描边宽度",
            "style.stroke.width",
            self._number(
                stroke.get("width", 0),
                lambda value: self._write(["style", "stroke", "width"], round(value, 1), "修改描边宽度"),
                minimum=0.0,
                maximum=40.0,
                step=1.0,
                decimals=1,
            ),
        )
        self._row(
            form,
            "描边颜色",
            "style.stroke.color",
            self._color_button(
                stroke.get("color", "#000000"),
                lambda value: self._write(["style", "stroke", "color"], value, "修改描边颜色"),
            ),
        )

    def _build_audio(self, element: Dict[str, Any]) -> QWidget:
        box = self._group("音频")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignRight)

        self._row(
            form,
            "素材",
            "asset",
            self._asset_combo(
                "audio", element.get("asset", ""), lambda value: self._write(["asset"], value, "更换音频")
            ),
        )
        source = element.get("source") or {"start": 0.0, "end": element.get("duration", 1.0)}
        self._row(
            form,
            "源裁剪开始",
            "source.start",
            self._number(
                source.get("start", 0.0),
                lambda value: self._write(["source", "start"], round(value, 3), "修改音频源起点"),
                minimum=0.0,
                step=0.05,
                suffix=" s",
            ),
        )
        self._row(
            form,
            "源裁剪结束",
            "source.end",
            self._number(
                source.get("end", 1.0),
                lambda value: self._write(["source", "end"], round(value, 3), "修改音频源终点"),
                minimum=0.0,
                step=0.05,
                suffix=" s",
            ),
        )
        self._row(
            form,
            "音量",
            "volume",
            self._number(
                element.get("volume", 1.0),
                lambda value: self._write(["volume"], round(value, 2), "修改音量"),
                minimum=0.0,
                maximum=4.0,
                step=0.05,
                decimals=2,
            ),
        )
        self._row(
            form,
            "速度",
            "speed",
            self._number(
                element.get("speed", 1.0),
                lambda value: self._write(["speed"], round(value, 3), "修改音频速度"),
                minimum=0.1,
                maximum=4.0,
                step=0.05,
            ),
        )
        fade = tl.effective_fade(element)
        self._row(
            form,
            "淡入",
            "fade.in",
            self._number(
                fade.get("in", 0.0),
                lambda value: self._write(["fade", "in"], round(value, 3), "修改淡入"),
                minimum=0.0,
                step=0.05,
                suffix=" s",
            ),
        )
        self._row(
            form,
            "淡出",
            "fade.out",
            self._number(
                fade.get("out", 0.0),
                lambda value: self._write(["fade", "out"], round(value, 3), "修改淡出"),
                minimum=0.0,
                step=0.05,
                suffix=" s",
            ),
        )
        return box

    def _build_effect(self, element: Dict[str, Any]) -> QWidget:
        name = element.get("name", "")
        definition = self._libraries.effect.get(name)
        box = self._group(f"特效 {definition['label'] if definition else name}")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignRight)

        name_label = QLabel(name)
        name_label.setFont(QFont("Consolas"))
        self._row(form, "特效名", "name", name_label)

        if definition and definition.get("description"):
            description = QLabel(definition["description"])
            description.setWordWrap(True)
            description.setStyleSheet("color:#7f8a99;")
            form.addRow("说明", description)

        targets = [("", "整个画面（视频类元素）")] + [
            (e["id"], f"{e['id']} {tl.ELEMENT_TYPE_LABELS.get(e.get('type'),'')}")
            for e in self._model.elements()
            if e.get("id") != element.get("id") and e.get("type") != "effect"
        ]
        self._row(
            form,
            "作用目标",
            "target（留空 = 作用于视频类元素）",
            self._combo(
                targets,
                element.get("target", ""),
                lambda value: self._write(["target"], value, "修改特效目标"),
            ),
        )
        self._row(
            form,
            "缓动",
            "easing",
            self._combo(
                [(k, tl.EASING_LABELS[k]) for k in tl.EASINGS],
                element.get("easing", "easeInOut"),
                lambda value: self._write(["easing"], value, "修改缓动"),
            ),
        )

        self._add_param_rows(form, element, definition)
        return box

    def _build_transition(self, element: Dict[str, Any]) -> QWidget:
        name = element.get("name", "")
        definition = self._libraries.transition.get(name)
        box = self._group(f"转场 {definition['label'] if definition else name}")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignRight)

        clips = [
            (e["id"], f"{e['id']} {(e.get('content') or {}).get('text','') or e.get('asset','')}")
            for e in self._model.elements()
            if e.get("type") in ("video", "freeze")
        ]
        self._row(
            form,
            "前一个片段",
            "from（必须是 Video Clip）",
            self._combo(clips, element.get("from", ""), lambda v: self._write(["from"], v, "修改转场 from")),
        )
        self._row(
            form,
            "后一个片段",
            "to（必须是 Video Clip）",
            self._combo(clips, element.get("to", ""), lambda v: self._write(["to"], v, "修改转场 to")),
        )
        if definition and definition.get("description"):
            description = QLabel(definition["description"])
            description.setWordWrap(True)
            description.setStyleSheet("color:#7f8a99;")
            form.addRow("说明", description)
        self._add_param_rows(form, element, definition)
        return box

    def _build_freeze(self, element: Dict[str, Any]) -> QWidget:
        box = self._group("冻结帧")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignRight)

        clips = [
            (e["id"], f"{e['id']} {self._assets.name_of(e.get('asset',''))}")
            for e in self._model.elements()
            if e.get("type") == "video"
        ]
        self._row(
            form,
            "目标片段",
            "target（必须是 Video Clip）",
            self._combo(
                clips, element.get("target", ""), lambda v: self._write(["target"], v, "修改冻结目标")
            ),
        )

        target = self._model.element(element.get("target", ""))
        source = (target or {}).get("source") or {}
        self._row(
            form,
            "冻结源时间",
            "source_time（源素材上的时间点）",
            self._number(
                element.get("source_time", 0.0),
                lambda value: self._write(["source_time"], round(value, 3), "修改冻结源时间"),
                minimum=0.0,
                step=0.05,
                suffix=" s",
            ),
        )
        if source:
            hint = QLabel(
                f"目标片段源区间 [{source.get('start')}, {source.get('end')}]，source_time 必须落在其中"
            )
            hint.setWordWrap(True)
            hint.setStyleSheet("color:#7f8a99;")
            form.addRow("约束", hint)
        return box

    def _add_param_rows(
        self,
        form: QFormLayout,
        element: Dict[str, Any],
        definition: Optional[Dict[str, Any]],
    ) -> None:
        """按库里的参数表自动生成控件。JSON 里的 params 字段与此一一对应。"""
        params = element.get("params") or {}
        if not definition:
            raw = QPlainTextEdit(json.dumps(params, ensure_ascii=False, indent=2))
            raw.setFixedHeight(90)
            raw.setFont(QFont("Consolas"))
            form.addRow("params（未知定义）", raw)
            return

        for spec in definition.get("params", []):
            key = spec["key"]
            current = params.get(key, spec["default"])
            path = ["params", key]
            label = spec["label"]
            json_path = f"params.{key}"

            if spec["type"] == "number":
                widget: QWidget = self._number(
                    float(current),
                    lambda value, p=path: self._write(p, round(value, 4), "修改特效参数"),
                    minimum=float(spec.get("min", -100000)),
                    maximum=float(spec.get("max", 100000)),
                    step=float(spec.get("step", 0.01)),
                )
            elif spec["type"] == "int":
                widget = self._integer(
                    int(current),
                    lambda value, p=path: self._write(p, value, "修改特效参数"),
                    minimum=int(spec.get("min", -100000)),
                    maximum=int(spec.get("max", 100000)),
                )
            elif spec["type"] == "bool":
                check = QCheckBox()
                check.setChecked(bool(current))
                check.toggled.connect(lambda value, p=path: self._write(p, value, "修改特效参数"))
                widget = check
            elif spec["type"] == "enum":
                widget = self._combo(
                    [(o, o) for o in spec.get("options", [])],
                    current,
                    lambda value, p=path: self._write(p, value, "修改特效参数"),
                )
            elif spec["type"] == "color":
                widget = self._color_button(
                    str(current), lambda value, p=path: self._write(p, value, "修改特效参数")
                )
            elif spec["type"] == "asset":
                widget = self._asset_combo(
                    spec.get("asset_type", "overlay"),
                    str(current),
                    lambda value, p=path: self._write(p, value, "修改特效素材"),
                )
            else:
                line = QLineEdit(str(current))
                line.editingFinished.connect(
                    lambda p=path, w=line: self._write(p, w.text(), "修改特效参数")
                )
                widget = line

            if spec.get("hint"):
                json_path += f"    {spec['hint']}"
            self._row(form, label, json_path, widget)

    # ------------------------------------------------------------ 关键帧

    def _build_keyframes(self, element: Dict[str, Any]) -> QWidget:
        box = self._group("关键帧 / 动画")
        outer = QVBoxLayout(box)
        outer.setSpacing(6)

        # 套用动画预设
        apply_row = QHBoxLayout()
        animation_combo = QComboBox()
        animation_combo.addItem("选择动画预设…", "")
        for animation in self._libraries.animation.all():
            animation_combo.addItem(f"{animation['label']}（{animation['duration']}s）", animation["id"])
        apply_button = QPushButton("套用")
        apply_button.setFixedWidth(56)

        def apply_animation() -> None:
            animation_id = animation_combo.currentData()
            if not animation_id:
                return
            animation = self._libraries.animation.get(animation_id)
            if not animation:
                return
            self._suppress += 1
            try:
                self._model.apply_animation(element["id"], animation)
            finally:
                self._suppress -= 1
            self.rebuild()

        apply_button.clicked.connect(apply_animation)
        apply_row.addWidget(animation_combo, 1)
        apply_row.addWidget(apply_button)
        outer.addLayout(apply_row)

        # 新增关键帧
        add_row = QGridLayout()
        param_combo = QComboBox()
        for param in tl.KEYFRAME_PARAMS:
            param_combo.addItem(tl.KEYFRAME_PARAM_LABELS[param], param)
        time_spin = QDoubleSpinBox()
        time_spin.setRange(0.0, 3600.0)
        time_spin.setDecimals(3)
        time_spin.setSingleStep(0.05)
        time_spin.setSuffix(" s")
        # 默认取播放头相对本元素的位置，正好是「我想在这里打一帧」
        time_spin.setValue(max(0.0, round(self._model.playhead - float(element.get("start", 0.0)), 3)))
        value_spin = QDoubleSpinBox()
        value_spin.setRange(-10000.0, 10000.0)
        value_spin.setDecimals(3)
        value_spin.setSingleStep(0.05)
        value_spin.setValue(1.0)
        easing_combo = QComboBox()
        for easing in tl.EASINGS:
            easing_combo.addItem(tl.EASING_LABELS[easing], easing)
        add_button = QPushButton("添加关键帧")

        def add_keyframe() -> None:
            self._suppress += 1
            try:
                self._model.add_keyframe(
                    element["id"],
                    param_combo.currentData(),
                    time_spin.value(),
                    value_spin.value(),
                    easing_combo.currentData(),
                )
            finally:
                self._suppress -= 1
            self.rebuild()

        add_button.clicked.connect(add_keyframe)

        add_row.addWidget(QLabel("参数"), 0, 0)
        add_row.addWidget(param_combo, 0, 1)
        add_row.addWidget(QLabel("时间"), 0, 2)
        add_row.addWidget(time_spin, 0, 3)
        add_row.addWidget(QLabel("数值"), 1, 0)
        add_row.addWidget(value_spin, 1, 1)
        add_row.addWidget(QLabel("Easing"), 1, 2)
        add_row.addWidget(easing_combo, 1, 3)
        add_row.addWidget(add_button, 2, 0, 1, 4)
        outer.addLayout(add_row)

        # 已有关键帧表格
        keyframes = element.get("keyframes") or {}
        rows: List[tuple] = []
        for param, points in keyframes.items():
            for index, point in enumerate(points):
                rows.append((param, index, point))

        table = QTableWidget(len(rows), 5)
        table.setHorizontalHeaderLabels(["参数", "时间 s", "数值", "Easing", ""])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.setFixedHeight(min(190, 30 + len(rows) * 26))

        for row, (param, index, point) in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(tl.KEYFRAME_PARAM_LABELS.get(param, param)))
            table.setItem(row, 1, QTableWidgetItem(f"{float(point.get('time', 0)):.3f}"))
            table.setItem(row, 2, QTableWidgetItem(f"{float(point.get('value', 0)):.3f}"))
            table.setItem(row, 3, QTableWidgetItem(str(point.get("easing", "linear"))))
            remove_button = QPushButton("删除")
            remove_button.clicked.connect(
                lambda _checked, p=param, i=index: self._remove_keyframe(element["id"], p, i)
            )
            table.setCellWidget(row, 4, remove_button)

        outer.addWidget(table)
        if not rows:
            empty = QLabel("当前没有关键帧。加了关键帧后，它会覆盖 transform 里的同名字段。")
            empty.setWordWrap(True)
            empty.setStyleSheet("color:#7f8a99;")
            outer.addWidget(empty)
        return box

    def _remove_keyframe(self, element_id: str, param: str, index: int) -> None:
        self._suppress += 1
        try:
            self._model.remove_keyframe(element_id, param, index)
        finally:
            self._suppress -= 1
        self.rebuild()

    def _build_transform(self, element: Dict[str, Any]) -> QWidget:
        box = self._group("变换 Transform")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignRight)
        # 显示的是「最终生效值」，不是「用户设置了什么」——
        # 面板读取默认值不等于把默认值写进 JSON（阶段 6.5 指令第六 / 二十条）
        transform = tl.effective_transform(element)

        hint = QLabel("X / Y 是归一化中心点坐标：0=左上，1=右下。可以直接在预览画面上拖。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#7f8a99;")
        form.addRow("", hint)

        for key, label, minimum, maximum, step in (
            ("x", "位置 X", -1.0, 2.0, 0.01),
            ("y", "位置 Y", -1.0, 2.0, 0.01),
            ("scale", "缩放", 0.01, 10.0, 0.01),
            ("rotation", "旋转（度）", -720.0, 720.0, 1.0),
            ("opacity", "不透明度", 0.0, 1.0, 0.05),
        ):
            self._row(
                form,
                label,
                f"transform.{key}",
                self._number(
                    transform[key],
                    lambda value, k=key: self._write(["transform", k], round(value, 3), "修改变换"),
                    minimum=minimum,
                    maximum=maximum,
                    step=step,
                ),
            )
        return box

    # ------------------------------------------------------------ 案例库

    def _build_case_box(self, element: Dict[str, Any]) -> QWidget:
        box = self._group("参数实验")
        layout = QVBoxLayout(box)
        hint = QLabel(
            "调好一组参数后存成案例，积累自己的剪辑规则库。\n"
            "案例保存在 projects/_cases/ 下，内容就是这个元素的完整 JSON。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#7f8a99;")
        layout.addWidget(hint)

        preview = QPlainTextEdit(json.dumps(element, ensure_ascii=False, indent=2))
        preview.setReadOnly(True)
        preview.setFixedHeight(130)
        preview.setFont(QFont("Consolas"))
        layout.addWidget(preview)

        save_button = QPushButton("保存为实验案例")
        save_button.clicked.connect(self.saveCaseRequested.emit)
        layout.addWidget(save_button)
        return box

    # ------------------------------------------------------------ 杂项

    def _apply_caption_template(self, name: str) -> None:
        element = self._model.element(self._model.selected_id)
        if element is None or not name:
            return
        template = self._libraries.caption.get(name)
        if not template:
            return
        self._suppress += 1
        try:
            self._model.set_element_field(
                self._model.selected_id, ["template"], name, f"套用字幕模板 {name}"
            )
            self._model.set_element_field(
                self._model.selected_id,
                ["caption_style"],
                template.get("caption_style", "plain"),
                "套用字幕模板",
            )
            self._model.set_element_field(
                self._model.selected_id,
                ["style"],
                json.loads(json.dumps(template.get("style", {}))),
                "套用字幕模板",
            )
            if template.get("highlight"):
                self._model.set_element_field(
                    self._model.selected_id,
                    ["highlight"],
                    json.loads(json.dumps(template["highlight"])),
                    "套用字幕模板",
                )
            if template.get("transform"):
                self._model.set_element_field(
                    self._model.selected_id,
                    ["transform"],
                    json.loads(json.dumps(template["transform"])),
                    "套用字幕模板",
                )
        finally:
            self._suppress -= 1
        self.rebuild()

    def _save_caption_template(self, element: Dict[str, Any]) -> None:
        name = f"custom_{element.get('id','caption')}"
        template = {
            "name": name,
            "label": f"自定义 {name}",
            "caption_style": element.get("caption_style", "plain"),
            "description": "由属性面板保存",
            "style": element.get("style", {}),
            "highlight": element.get("highlight", {}),
            "transform": element.get("transform", {}),
        }
        path = self._libraries.caption.save_template(template)
        self.logMessage.emit(f"字幕模板已保存：{path}")

    def _refresh_derived(self) -> None:
        """只更新派生显示，不重建整个面板（保住输入焦点）。"""
        element = self._model.element(self._model.selected_id)
        if element is None:
            return
        label = getattr(self, "_end_label", None)
        if label is not None:
            try:
                label.setText(format_seconds(tl.element_end(element)))
            except RuntimeError:
                # 控件已被 deleteLater 回收，忽略
                pass
