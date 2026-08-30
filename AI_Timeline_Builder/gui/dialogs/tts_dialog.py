"""文本转语音对话框：填文本 → 选音色/语速/音量 → 生成配音。

生成走 core.tts 的后台线程，对话框只负责收参数与试听，
真正的「入库 + 落到轨道」由主窗口在拿到 WAV 后完成。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
)
from PyQt5.QtCore import Qt

from core import tts


# 语速滑块显示用的档位说明
def _rate_hint(value: int) -> str:
    if value <= -4:
        return "很慢"
    if value < 0:
        return "偏慢"
    if value == 0:
        return "正常"
    if value <= 4:
        return "偏快"
    return "很快"


class TtsDialog(QDialog):
    """收集 TTS 参数。文本可以从选中的字幕元素带过来。"""

    def __init__(
        self,
        tracks: List[Dict[str, Any]],
        default_text: str = "",
        default_start: float = 0.0,
        default_track: str = "A2",
        root: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("文本转语音（生成配音）")
        self.setMinimumWidth(520)

        self._root = root or os.getcwd()
        self._voices = tts.list_voices()

        self._text_edit = QPlainTextEdit()
        self._text_edit.setPlaceholderText("在这里输入要读出来的文字，支持多行。")
        self._text_edit.setPlainText(default_text)
        self._text_edit.setMinimumHeight(120)

        self._voice_box = QComboBox()
        for voice in self._voices:
            label = f"{voice['name']}（{voice['culture']}　{voice['gender']}）"
            self._voice_box.addItem(label, voice["name"])
        if not self._voices:
            self._voice_box.addItem("系统未安装可用音色", "")
            self._voice_box.setEnabled(False)
        else:
            default_name = tts.default_voice()
            index = self._voice_box.findData(default_name)
            if index >= 0:
                self._voice_box.setCurrentIndex(index)

        self._rate = QSlider(Qt.Horizontal)
        self._rate.setRange(tts.RATE_MIN, tts.RATE_MAX)
        self._rate.setValue(0)
        self._rate_label = QLabel("0（正常）")
        self._rate.valueChanged.connect(
            lambda v: self._rate_label.setText(f"{v}（{_rate_hint(v)}）")
        )
        rate_row = QHBoxLayout()
        rate_row.addWidget(self._rate, 1)
        rate_row.addWidget(self._rate_label)

        self._volume = QSlider(Qt.Horizontal)
        self._volume.setRange(tts.VOLUME_MIN, tts.VOLUME_MAX)
        self._volume.setValue(100)
        self._volume_label = QLabel("100")
        self._volume.valueChanged.connect(lambda v: self._volume_label.setText(str(v)))
        volume_row = QHBoxLayout()
        volume_row.addWidget(self._volume, 1)
        volume_row.addWidget(self._volume_label)

        self._track_box = QComboBox()
        for track in tracks:
            if track.get("kind") != "audio":
                continue
            self._track_box.addItem(f"{track.get('id')}　{track.get('name')}", track.get("id"))
        if self._track_box.count() == 0:
            self._track_box.addItem("A2", "A2")
        preferred = self._track_box.findData(default_track)
        if preferred >= 0:
            self._track_box.setCurrentIndex(preferred)

        self._start = QDoubleSpinBox()
        self._start.setRange(0.0, 36000.0)
        self._start.setDecimals(3)
        self._start.setSingleStep(0.1)
        self._start.setSuffix(" 秒")
        self._start.setValue(max(0.0, round(float(default_start), 3)))

        self._place = QCheckBox("生成后直接放到时间线上（取消勾选则只入素材库）")
        self._place.setChecked(True)

        self._preview_button = QPushButton("试听（不写入素材库）")
        self._preview_button.clicked.connect(self._on_preview)
        self._preview_button.setEnabled(bool(self._voices))

        self._hint = QLabel(
            "用的是 Windows 自带的离线语音合成，不联网、不需要 API Key。\n"
            "音色由系统语音包决定；想要更多音色请在「设置 → 时间和语言 → 语音」里安装。\n"
            "配音时长由文本长度和语速决定，生成后会按实际时长放到轨道上。"
        )
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color:#7f8a99;")

        form = QFormLayout()
        form.addRow("配音文本", self._text_edit)
        form.addRow("音色", self._voice_box)
        form.addRow("语速", rate_row)
        form.addRow("音量", volume_row)
        form.addRow("落到轨道", self._track_box)
        form.addRow("开始时间", self._start)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("生成配音")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        bottom = QHBoxLayout()
        bottom.addWidget(self._preview_button)
        bottom.addStretch(1)
        bottom.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._place)
        layout.addWidget(self._hint)
        layout.addLayout(bottom)

    # ------------------------------------------------------------ 交互

    def _on_accept(self) -> None:
        if not self._text_edit.toPlainText().strip():
            self._show_error("配音文本不能为空。")
            return
        if not self._voice_box.currentData():
            self._show_error("系统里没有可用音色，先在系统设置里装一个语音包。")
            return
        self.accept()

    def _show_error(self, message: str) -> None:
        self._hint.setText(message)
        self._hint.setStyleSheet("color:#ff6b61;")

    def _on_preview(self) -> None:
        """试听：合成到临时目录并用系统播放器打开，不入素材库。

        试听是同步的（一般 1 秒内），但为了不让对话框假死，
        按钮先禁用并给出提示。
        """
        text = self._text_edit.toPlainText().strip()
        if not text:
            self._show_error("先写点文本再试听。")
            return
        self._preview_button.setEnabled(False)
        self._preview_button.setText("正在合成试听…")
        self._preview_button.repaint()

        cache_dir = os.path.join(self._root, ".cache", "tts")
        os.makedirs(cache_dir, exist_ok=True)
        target = os.path.join(cache_dir, "preview.wav")
        error = tts.synthesize(
            text,
            target,
            voice=self._voice_box.currentData(),
            rate=self._rate.value(),
            volume=self._volume.value(),
            cache_dir=cache_dir,
        )
        self._preview_button.setEnabled(True)
        self._preview_button.setText("试听（不写入素材库）")
        if error:
            self._show_error(error)
            return
        self._hint.setText(f"试听文件已生成：{target}")
        self._hint.setStyleSheet("color:#7f8a99;")
        try:
            os.startfile(target)  # noqa: S606  仅本机播放试听文件
        except OSError as exc:
            self._show_error(f"无法调用系统播放器：{exc}")

    # ------------------------------------------------------------ 结果

    def result_values(self) -> Dict[str, Any]:
        return {
            "text": self._text_edit.toPlainText().strip(),
            "voice": self._voice_box.currentData() or "",
            "rate": int(self._rate.value()),
            "volume": int(self._volume.value()),
            "track": self._track_box.currentData() or "A2",
            "start": round(float(self._start.value()), 3),
            "place": self._place.isChecked(),
        }


def element_text(element: Optional[Dict[str, Any]]) -> str:
    """从字幕 / 逐词字幕 / 文字元素里取出可朗读的文本。"""
    if not element:
        return ""
    content = element.get("content") or {}
    if isinstance(content.get("text"), str):
        return content["text"]
    words = content.get("words")
    if isinstance(words, list):
        return "".join(str(w.get("text", "")) for w in words)
    return ""
