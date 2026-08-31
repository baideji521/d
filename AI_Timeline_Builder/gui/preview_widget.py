"""视频预览面板。

职责：
- 把当前播放头时刻的画面渲染出来（合成由 render/preview_renderer.py 负责）
- 支持播放 / 暂停 / 单帧步进
- 选中元素后可以直接在画面上拖动，实时改 transform.x / transform.y

渲染本身很快（QPainter 合成），慢的是 FFmpeg 抽帧，那部分在后台线程里，
帧就绪后 PreviewRenderer 发 frameReady，这里再重画一次。
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QElapsedTimer, QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,

    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core import safe_area as sa
from core import timeline as tl
from core.time_utils import format_timecode_long, frame_label

#: 安全区域比例（相对画布）。行业惯例：动作安全 93%，标题安全 90%。
ACTION_SAFE = 0.93
TITLE_SAFE = 0.90


class PreviewCanvas(QWidget):
    """画面显示区。负责等比居中，以及拖动改位置。

    画布尺寸完全由 meta.width / meta.height 决定 —— 项目设置里换成 9:16，
    这里的画面、安全区、鼠标归一化坐标会一起跟着变，不需要额外通知。
    """

    positionDragged = pyqtSignal(float, float)  # 归一化 x, y

    def __init__(self, model, renderer, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._renderer = renderer
        self._image: Optional[QImage] = None
        self._target_rect = QRect()
        self._render_size = QSize()
        self._render_scale = 1.0
        self._dragging = False
        self._show_safe_area = False
        self.setMinimumSize(240, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

    def set_safe_area_visible(self, visible: bool) -> None:
        self._show_safe_area = bool(visible)
        self.update()

    def safe_area_visible(self) -> bool:
        return self._show_safe_area


    def set_render_scale(self, scale: float) -> None:
        """渲染倍率。小于 1 时先按小尺寸合成再放大显示，播放时省很多时间。"""
        scale = max(0.2, min(1.0, float(scale)))
        if abs(scale - self._render_scale) < 0.001:
            return
        self._render_scale = scale
        self.invalidate()


    def invalidate(self) -> None:
        self._image = None
        self.update()

    def _compute_target(self) -> QRect:
        """在控件里按项目宽高比算出画面矩形。"""
        project_w = max(1, self._model.width)
        project_h = max(1, self._model.height)
        available_w = max(1, self.width() - 16)
        available_h = max(1, self.height() - 16)
        scale = min(available_w / project_w, available_h / project_h)
        width = max(1, int(project_w * scale))
        height = max(1, int(project_h * scale))
        return QRect(
            (self.width() - width) // 2,
            (self.height() - height) // 2,
            width,
            height,
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0b0e13"))
        self._target_rect = self._compute_target()
        render_size = QSize(
            max(16, int(self._target_rect.width() * self._render_scale)),
            max(16, int(self._target_rect.height() * self._render_scale)),
        )

        if self._image is None or self._render_size != render_size:
            self._render_size = render_size
            self._image = self._renderer.render(self._model.playhead, render_size)
        painter.drawImage(self._target_rect, self._image)

        painter.setPen(QPen(QColor("#2b3543")))
        painter.drawRect(self._target_rect.adjusted(0, 0, -1, -1))

        if self._show_safe_area:
            self._paint_safe_area(painter)


        # 选中元素画一个中心控制点，提示可以拖。
        # 按类型判断，不看 transform 字段在不在 —— 稀疏 JSON 里它常常不存在
        element = self._model.element(self._model.selected_id)
        if element and tl.supports_transform(element):
            transform = tl.effective_transform(element)
            cx = self._target_rect.left() + float(transform["x"]) * self._target_rect.width()
            cy = self._target_rect.top() + float(transform["y"]) * self._target_rect.height()
            painter.setPen(QPen(QColor("#ffe347"), 1, Qt.DashLine))
            painter.drawLine(int(cx) - 12, int(cy), int(cx) + 12, int(cy))
            painter.drawLine(int(cx), int(cy) - 12, int(cx), int(cy) + 12)
            painter.setPen(QPen(QColor("#ffe347"), 2))
            painter.drawEllipse(QPoint(int(cx), int(cy)), 5, 5)
        painter.end()

    def _paint_safe_area(self, painter: QPainter) -> None:
        """画三层参考框：

        1. 动作安全 93% / 标题安全 90% —— 广播行业惯例，与平台无关；
        2. **平台安全区** —— 按 `meta.safe_area.preset` 从 core/safe_area.py 取，
           抖音 / Shorts / Reels 各不相同，四边内缩也不对称
           （右侧按钮列比左侧宽得多），所以不能用「居中缩放」那种画法。

        比例都是相对**画布**的，所以换成 3:4 / 9:16 / 16:9 / 1:1 都自动适配。
        """
        rect = self._target_rect
        for ratio, color, label in (
            (ACTION_SAFE, QColor("#4fd1c5"), "动作安全 93%"),
            (TITLE_SAFE, QColor("#f6ad55"), "标题安全 90%"),
        ):
            width = int(rect.width() * ratio)
            height = int(rect.height() * ratio)
            box = QRect(
                rect.left() + (rect.width() - width) // 2,
                rect.top() + (rect.height() - height) // 2,
                width,
                height,
            )
            pen = QPen(color, 1, Qt.DashLine)
            painter.setPen(pen)
            painter.drawRect(box)
            painter.drawText(box.left() + 4, box.top() + 14, label)

        # 直接读模型内部 JSON 引用（只读），不走 to_dict()，避免每帧重建稀疏副本
        preset = sa.timeline_preset(self._model.timeline)
        left, top, right, bottom = sa.box(preset)
        platform_box = QRect(
            rect.left() + int(rect.width() * left),
            rect.top() + int(rect.height() * top),
            max(1, int(rect.width() * (right - left))),
            max(1, int(rect.height() * (bottom - top))),
        )
        painter.setPen(QPen(QColor("#f56565"), 2, Qt.DashDotLine))
        painter.drawRect(platform_box)
        painter.drawText(
            platform_box.left() + 4,
            platform_box.bottom() - 6,
            f"平台安全区 {sa.label_of(preset)}",
        )

        # 画面中心十字，方便判断元素有没有居中
        painter.setPen(QPen(QColor("#3b4657"), 1, Qt.DotLine))
        painter.drawLine(rect.center().x(), rect.top(), rect.center().x(), rect.bottom())
        painter.drawLine(rect.left(), rect.center().y(), rect.right(), rect.center().y())

    def mousePressEvent(self, event) -> None:  # noqa: N802
        element = self._model.element(self._model.selected_id)
        if event.button() == Qt.LeftButton and element and tl.supports_transform(element):
            self._dragging = True
            self._emit_position(event.pos())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._dragging:
            self._emit_position(event.pos())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._dragging = False

    def _emit_position(self, pos: QPoint) -> None:
        if self._target_rect.width() <= 0 or self._target_rect.height() <= 0:
            return
        x = (pos.x() - self._target_rect.left()) / self._target_rect.width()
        y = (pos.y() - self._target_rect.top()) / self._target_rect.height()
        self.positionDragged.emit(round(max(-0.5, min(1.5, x)), 3), round(max(-0.5, min(1.5, y)), 3))


class PreviewWidget(QWidget):
    """预览面板：画面 + 播放控制条 + **真实音频**。

    音频由 `render/preview_audio.PreviewAudio` 提供（预混一份 WAV + QMediaPlayer）。
    播放时**以音频时钟为准**推进播放头 —— 这样音视频不会越播越偏；
    没有可播音频时（整片无声、缺 QtMultimedia、缺 ffmpeg）自动退回挂钟驱动，
    行为与加音频之前完全一致。
    """

    def __init__(self, model, renderer, audio=None, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._renderer = renderer
        self._audio = audio
        #: 正在按音频时钟同步播放头，此时不要再把播放头写回音频（否则来回抖）
        self._syncing = False

        self.canvas = PreviewCanvas(model, renderer)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)   # 挂钟驱动：每次画完再排下一次，避免定时器排队堆积
        self._timer.timeout.connect(self._advance_frame)
        self._clock = QElapsedTimer()
        self._play_origin = 0.0


        self._info = QLabel("00:00:00.000 / 00:00:00.000")
        self._info.setStyleSheet("color:#9aa8bb; font-family: Consolas;")

        self._play_button = QPushButton("▶ 播放")
        self._play_button.setFixedWidth(74)
        self._play_button.clicked.connect(self.toggle_play)

        home_button = QPushButton("⏮")
        home_button.setFixedWidth(32)
        home_button.setToolTip("跳到开始")
        home_button.clicked.connect(self.go_start)

        end_button = QPushButton("⏭")
        end_button.setFixedWidth(32)
        end_button.setToolTip("跳到结束（最后一帧）")
        end_button.clicked.connect(self.go_end)

        prev_button = QPushButton("◀|")
        prev_button.setFixedWidth(36)
        prev_button.setToolTip("上一帧")
        prev_button.clicked.connect(lambda: self._step(-1))

        next_button = QPushButton("|▶")
        next_button.setFixedWidth(36)
        next_button.setToolTip("下一帧")
        next_button.clicked.connect(lambda: self._step(1))

        self._safe_area = QCheckBox("安全区")
        self._safe_area.setToolTip(
            "显示动作安全区 93% / 标题安全区 90%，以及 meta.safe_area.preset 指定的"
            "平台安全区（抖音 / YouTube Shorts / Instagram Reels / 通用），按当前画面比例适配"
        )
        self._safe_area.toggled.connect(self.canvas.set_safe_area_visible)

        # 预览有真实音频通路（预混 WAV + QMediaPlayer），这里的音量 / 静音
        # 写的是 **meta.master_volume** —— 它既进导出的 MP4，也进预览混音，
        # 两边走 Remotion `resolveVolume()` 的同一套语义，不会「听着是一个值、
        # 导出是另一个值」。
        self._mute_button = QPushButton("🔊")
        self._mute_button.setFixedWidth(32)
        self._mute_button.setToolTip("静音开关（meta.master_volume=0），预览与导出同时生效")
        self._mute_button.clicked.connect(self.toggle_mute)

        self._volume = QSlider(Qt.Horizontal)
        self._volume.setFixedWidth(90)
        self._volume.setRange(0, 200)
        self._volume.setValue(100)
        self._volume.setToolTip("音量 meta.master_volume（0~200%），预览与导出同时生效")
        self._volume.sliderReleased.connect(self._commit_volume)

        self._quality = QComboBox()
        self._quality.addItems(["预览质量 流畅", "预览质量 标准", "预览质量 高"])
        self._quality.setCurrentIndex(1)
        self._quality.setToolTip("流畅按更小尺寸合成再放大，卡的时候选它；高按面板实际尺寸渲染")
        self._quality.currentIndexChanged.connect(self._on_quality_changed)


        self._scrub = QSlider(Qt.Horizontal)
        self._scrub.setRange(0, 1000)
        self._scrub.sliderMoved.connect(self._on_scrub)

        controls = QHBoxLayout()
        controls.setContentsMargins(6, 4, 6, 4)
        controls.setSpacing(6)
        controls.addWidget(home_button)
        controls.addWidget(prev_button)
        controls.addWidget(self._play_button)
        controls.addWidget(next_button)
        controls.addWidget(end_button)
        controls.addWidget(self._scrub, 1)
        controls.addWidget(self._info)
        controls.addWidget(self._mute_button)
        controls.addWidget(self._volume)
        controls.addWidget(self._safe_area)
        controls.addWidget(self._quality)

        # 控件不接受键盘焦点，否则空格 / 方向键会被按钮和滑块吃掉，
        # 全局快捷键（空格播放、方向键帧步进）就失效了
        for widget in (home_button, prev_button, self._play_button, next_button, end_button,
                       self._scrub, self._quality, self._safe_area,
                       self._mute_button, self._volume):
            widget.setFocusPolicy(Qt.NoFocus)



        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.canvas, 1)
        layout.addLayout(controls)

        model.timelineChanged.connect(self._on_timeline_changed)
        model.elementUpdated.connect(lambda _id: self.canvas.invalidate())
        model.selectionChanged.connect(lambda _id: self.canvas.update())
        model.playheadChanged.connect(self._on_playhead_changed)
        renderer.frameReady.connect(self.canvas.invalidate)
        self.canvas.positionDragged.connect(self._on_position_dragged)

        self._volume_before_mute = 1.0
        self._sync_volume()

        self._update_info()

    # ------------------------------------------------------------ 播放控制

    def audio_available(self) -> bool:
        """当前有没有可播的预览音频。报告与用例用它区分「无声」和「坏了」。"""
        return bool(self._audio is not None and self._audio.available())

    def audio_status(self) -> str:
        if self._audio is None:
            return "未接预览音频通道"
        return self._audio.status_text()

    def toggle_play(self) -> None:
        if self._timer.isActive():
            self.stop()
        else:
            self._play_origin = self._model.playhead
            self._clock.restart()
            if self._audio is not None:
                self._audio.sync_volume()
                self._audio.play(self._play_origin)
            self._timer.start(0)
            self._apply_scale()
            self._play_button.setText("⏸ 暂停")

    def stop(self) -> None:
        self._timer.stop()
        if self._audio is not None:
            self._audio.pause()
        self._play_button.setText("▶ 播放")
        self._apply_scale()

    def is_playing(self) -> bool:
        return self._timer.isActive()

    def _advance_frame(self) -> None:
        """推进播放头。**有声音时以音频时钟为准**，没声音时用挂钟。

        为什么不一直用挂钟：挂钟和声卡时钟是两个独立时基，播一分钟就能差出
        几十毫秒，而且渲染丢帧会让画面进一步落后。音频播放器的 position()
        本身就是声卡消费到的位置，用它当时间源，音画偏差由构造保证。

        挂钟那一套仍然保留：整片无声、缺 QtMultimedia、缺 ffmpeg 时都走它。
        以前的行为（慢的时候跳帧而不是拖慢）也一样成立。
        """
        fps = max(1.0, self._model.fps)
        frame_ms = 1000.0 / fps
        elapsed = self._clock.elapsed() / 1000.0

        audio_playing = self._audio is not None and self._audio.is_playing()
        if audio_playing:
            next_time = self._audio.position_seconds()
        else:
            next_time = self._play_origin + elapsed
            # 音频刚混好还没开始播时，把它接上，别让这一段变成无声
            if self._audio is not None and self.audio_available():
                self._audio.play(next_time)

        if next_time >= self._model.duration:
            self.stop()
            self._model.set_playhead(0.0)
            return
        self._syncing = True
        try:
            self._model.set_playhead(next_time)
        finally:
            self._syncing = False
        self.canvas.repaint()   # 同步画完再计时，才能量出真实耗时并据此丢帧

        # 本帧实际耗时超过一帧间隔时，下一次立刻开始（丢掉中间那些帧）
        spent = self._clock.elapsed() / 1000.0 - elapsed
        delay = frame_ms - spent * 1000.0
        self._timer.start(max(0, int(delay)))

    def _on_quality_changed(self, _index: int) -> None:
        self._apply_scale()

    def _apply_scale(self) -> None:
        """质量档 + 是否在播放，共同决定渲染倍率。"""
        base = (0.5, 0.7, 1.0)[max(0, min(2, self._quality.currentIndex()))]
        if self._timer.isActive():
            base *= 0.8   # 播放时再降一档，停下来自动恢复清晰
        self.canvas.set_render_scale(base)

    def _step(self, frames: int) -> None:

        self.stop()
        fps = max(1.0, self._model.fps)
        self._model.set_playhead(max(0.0, self._model.playhead + frames / fps))

    def go_start(self) -> None:
        """跳到开始。"""
        self.stop()
        self._model.set_playhead(0.0)

    def go_end(self) -> None:
        """跳到结束：落在**最后一帧**，而不是超出末尾的那个时刻。

        时长 2.0s / 30fps 的片子共 60 帧，最后一帧在 1.966667s。
        直接跳到 2.0s 会落在片子之外，画面是空的。
        """
        self.stop()
        fps = max(1.0, self._model.fps)
        duration = max(0.0, self._model.duration)
        last = max(0.0, duration - 1.0 / fps)
        self._model.set_playhead(round(round(last * fps) / fps, 6))

    def safe_area_visible(self) -> bool:
        return self._safe_area.isChecked()

    def toggle_safe_area(self) -> None:
        self._safe_area.setChecked(not self._safe_area.isChecked())

    # ------------------------------------------------------------ 导出音量

    def toggle_mute(self) -> None:
        """导出静音开关。静音前记住原音量，取消静音时还原。"""
        current = self._model.master_volume
        if current > 0:
            self._volume_before_mute = current
            self._model.set_master_volume(0.0)
        else:
            self._model.set_master_volume(getattr(self, "_volume_before_mute", 1.0) or 1.0)
        self._sync_volume()

    def _commit_volume(self) -> None:
        """滑块松手才写模型 —— 拖动过程中每帧提交会把撤销栈冲爆。"""
        self._model.set_master_volume(self._volume.value() / 100.0)
        self._sync_volume()

    def _sync_volume(self) -> None:
        volume = self._model.master_volume
        if not self._volume.isSliderDown():
            self._volume.setValue(int(round(volume * 100)))
        self._mute_button.setText("🔇" if volume <= 0 else "🔊")

    def _on_scrub(self, value: int) -> None:
        duration = max(1e-6, self._model.duration)
        self._model.set_playhead(duration * value / 1000.0)

    # ------------------------------------------------------------ 同步

    def _on_timeline_changed(self) -> None:
        self.canvas.invalidate()
        self._update_info()
        self._sync_volume()

    def _on_playhead_changed(self, seconds: float) -> None:
        self.canvas.invalidate()
        self._update_info()
        # 播放头是被别人挪的（拖时间线 / 快捷键 / 帧步进 / 跳转）→ 音频跟着跳。
        # 自己按音频时钟推进的那一路要跳过，否则会不停 seek 自己，声音发抖。
        if self._audio is not None and not self._syncing:
            self._audio.seek(seconds)

    def _update_info(self) -> None:
        duration = self._model.duration
        fps = max(1.0, self._model.fps)
        self._info.setText(
            f"{format_timecode_long(self._model.playhead)} / {format_timecode_long(duration)}"
            f"  {frame_label(self._model.playhead, fps)}"
        )

        if duration > 0:
            ratio = int(self._model.playhead / duration * 1000)
            if not self._scrub.isSliderDown():
                self._scrub.setValue(max(0, min(1000, ratio)))

    def _on_position_dragged(self, x: float, y: float) -> None:
        element_id = self._model.selected_id
        if not element_id:
            return
        element = self._model.element(element_id)
        if element is None:
            return
        # 一次拖动会产生很多次移动，这里合并成一条撤销记录不现实，
        # 所以只在 transform 上直接写，撤销粒度是「每次微调」，够用
        self._model.set_element_field(element_id, ["transform", "x"], x, "拖动预览改位置 X")
        self._model.set_element_field(element_id, ["transform", "y"], y, "拖动预览改位置 Y")
