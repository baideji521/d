"""导入剪映文本对话框：选文件 → 预览解析结果 → 生成字幕 / 批量转配音。

只负责收集参数和展示解析结果，真正的合成与落轨由主窗口驱动。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from core import jianying_import as jy
from core import tts


class JianyingImportDialog(QDialog):
    """导入剪映字幕，可选同时生成字幕元素和逐行配音。"""

    def __init__(self, tracks: List[Dict[str, Any]], playhead: float = 0.0, root: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("导入剪映文本 / 字幕（可批量转配音）")
        self.resize(760, 620)

        self._root = root or os.getcwd()
        self._rows: List[Dict[str, Any]] = []

        # ---- 文件选择
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText(
            "选 draft_content.json（剪映草稿）、剪映导出的 .srt，或一行一句的 .txt"
        )
        self._path_edit.setReadOnly(True)
        browse = QPushButton("选择文件…")
        browse.clicked.connect(self._on_browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self._path_edit, 1)
        path_row.addWidget(browse)

        # ---- 解析结果预览
        self._table = QTreeWidget()
        self._table.setHeaderLabels(["#", "开始", "结束", "文本"])
        self._table.setRootIsDecorated(False)
        self._table.setColumnWidth(0, 44)
        self._table.setColumnWidth(1, 80)
        self._table.setColumnWidth(2, 80)
        self._table.setMinimumHeight(220)

        self._summary = QLabel("还没有选文件")
        self._summary.setStyleSheet("color:#7f8a99;")
        self._summary.setWordWrap(True)

        # ---- 生成选项
        self._make_caption = QCheckBox("生成字幕元素（放到文字轨）")
        self._make_caption.setChecked(True)
        self._make_voice = QCheckBox("逐行生成配音（放到音频轨）")
        self._make_voice.setChecked(True)
        self._make_voice.setEnabled(tts.available())
        if not tts.available():
            self._make_voice.setChecked(False)
            self._make_voice.setText("逐行生成配音（系统里没有可用音色，不可用）")

        self._time_mode = QComboBox()
        self._time_mode.addItem("用文件里的时间（推荐）", "source")
        self._time_mode.addItem("从下面的偏移开始依次排布", "sequential")

        self._offset = QDoubleSpinBox()
        self._offset.setRange(0.0, 36000.0)
        self._offset.setDecimals(3)
        self._offset.setSingleStep(0.1)
        self._offset.setSuffix(" 秒")
        self._offset.setValue(max(0.0, round(float(playhead), 3)))

        self._avoid_overlap = QCheckBox("配音比字幕长时自动往后顺延，避免互相压住")
        self._avoid_overlap.setChecked(True)

        self._caption_track = QComboBox()
        self._audio_track = QComboBox()
        for track in tracks:
            label = f"{track.get('id')}　{track.get('name')}"
            if track.get("kind") == "text":
                self._caption_track.addItem(label, track.get("id"))
            elif track.get("kind") == "audio":
                self._audio_track.addItem(label, track.get("id"))
        if self._caption_track.count() == 0:
            self._caption_track.addItem("T1", "T1")
        if self._audio_track.count() == 0:
            self._audio_track.addItem("A2", "A2")
        preferred_audio = self._audio_track.findData("A2")
        if preferred_audio >= 0:
            self._audio_track.setCurrentIndex(preferred_audio)

        # ---- 配音参数
        self._voice_box = QComboBox()
        for voice in tts.list_voices():
            self._voice_box.addItem(
                f"{voice['name']}（{voice['culture']}　{voice['gender']}）", voice["name"]
            )
        if self._voice_box.count() == 0:
            self._voice_box.addItem("系统未安装可用音色", "")
            self._voice_box.setEnabled(False)
        else:
            index = self._voice_box.findData(tts.default_voice())
            if index >= 0:
                self._voice_box.setCurrentIndex(index)

        self._rate = QSlider(Qt.Horizontal)
        self._rate.setRange(tts.RATE_MIN, tts.RATE_MAX)
        self._rate.setValue(0)
        self._rate_label = QLabel("0")
        self._rate.valueChanged.connect(lambda v: self._rate_label.setText(str(v)))
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

        form = QFormLayout()
        form.addRow("字幕轨", self._caption_track)
        form.addRow("配音轨", self._audio_track)
        form.addRow("时间基准", self._time_mode)
        form.addRow("起始偏移", self._offset)
        form.addRow("音色", self._voice_box)
        form.addRow("语速", rate_row)
        form.addRow("音量", volume_row)

        self._hint = QLabel(
            "剪映草稿默认在 C:\\Users\\你的用户名\\AppData\\Local\\JianyingPro\\User Data\\"
            "Projects\\com.lveditor.draft\\项目名\\draft_content.json。\n"
            "新版剪映的草稿文件常常不是明文 JSON，那种情况请在剪映里「导出 → 字幕文件（SRT）」再导入。\n"
            "配音用的是 Windows 自带离线语音合成，逐行串行合成，行数多会花些时间。"
        )
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color:#7f8a99;")

        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.button(QDialogButtonBox.Ok).setText("开始导入")
        self._buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(path_row)
        layout.addWidget(self._table, 1)
        layout.addWidget(self._summary)
        layout.addLayout(form)
        layout.addWidget(self._make_caption)
        layout.addWidget(self._make_voice)
        layout.addWidget(self._avoid_overlap)
        layout.addWidget(self._hint)
        layout.addWidget(self._buttons)

    # ------------------------------------------------------------ 交互

    def _on_browse(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "选择剪映草稿 / 字幕文件", "", jy.SUPPORTED_FILTER
        )
        if not path:
            return
        self._path_edit.setText(path)
        self._load(path)

    def _load(self, path: str) -> None:
        rows, message = jy.parse_file(path)
        self._rows = rows
        self._table.clear()
        for row in rows:
            QTreeWidgetItem(
                self._table,
                [str(row["index"]), f"{row['start']:.2f}", f"{row['end']:.2f}", row["text"]],
            )
        if rows:
            self._summary.setText(jy.summarize(rows))
            self._summary.setStyleSheet("color:#7f8a99;")
        else:
            self._summary.setText(message or "没解析到内容")
            self._summary.setStyleSheet("color:#ff6b61;")
        self._buttons.button(QDialogButtonBox.Ok).setEnabled(bool(rows))

    def _on_accept(self) -> None:
        if not self._rows:
            return
        if not self._make_caption.isChecked() and not self._make_voice.isChecked():
            self._summary.setText("字幕和配音至少要勾一个，否则导入没有任何效果。")
            self._summary.setStyleSheet("color:#ff6b61;")
            return
        self.accept()

    # ------------------------------------------------------------ 结果

    def result_values(self) -> Dict[str, Any]:
        rows = [dict(row) for row in self._rows]
        if self._time_mode.currentData() == "sequential":
            cursor = float(self._offset.value())
            for row in rows:
                length = max(0.4, float(row["end"]) - float(row["start"]))
                row["start"] = round(cursor, 3)
                row["end"] = round(cursor + length, 3)
                cursor += length + jy.DEFAULT_LINE_GAP
        elif self._offset.value() > 0:
            shift = float(self._offset.value())
            for row in rows:
                row["start"] = round(float(row["start"]) + shift, 3)
                row["end"] = round(float(row["end"]) + shift, 3)

        return {
            "lines": rows,
            "make_caption": self._make_caption.isChecked(),
            "make_voice": self._make_voice.isChecked(),
            "caption_track": self._caption_track.currentData() or "T1",
            "audio_track": self._audio_track.currentData() or "A2",
            "avoid_overlap": self._avoid_overlap.isChecked(),
            "voice": self._voice_box.currentData() or "",
            "rate": int(self._rate.value()),
            "volume": int(self._volume.value()),
            "source": self._path_edit.text(),
        }
