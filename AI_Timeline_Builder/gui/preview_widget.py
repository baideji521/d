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
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.time_utils import format_timecode


class PreviewCanvas(QWidget):
    """画面显示区。负责等比居中，以及拖动改位置。"""

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
        self.setMinimumSize(240, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

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

        # 选中元素画一个中心控制点，提示可以拖
        element = self._model.element(self._model.selected_id)
        if element and isinstance(element.get("transform"), dict):
            transform = element["transform"]
            cx = self._target_rect.left() + float(transform.get("x", 0.5)) * self._target_rect.width()
            cy = self._target_rect.top() + float(transform.get("y", 0.5)) * self._target_rect.height()
            painter.setPen(QPen(QColor("#ffe347"), 1, Qt.DashLine))
            painter.drawLine(int(cx) - 12, int(cy), int(cx) + 12, int(cy))
            painter.drawLine(int(cx), int(cy) - 12, int(cx), int(cy) + 12)
            painter.setPen(QPen(QColor("#ffe347"), 2))
            painter.drawEllipse(QPoint(int(cx), int(cy)), 5, 5)
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        element = self._model.element(self._model.selected_id)
        if event.button() == Qt.LeftButton and element and isinstance(element.get("transform"), dict):
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
    """预览面板：画面 + 播放控制条。"""

    def __init__(self, model, renderer, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._renderer = renderer

        self.canvas = PreviewCanvas(model, renderer)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)   # 挂钟驱动：每次画完再排下一次，避免定时器排队堆积
        self._timer.timeout.connect(self._advance_frame)
        self._clock = QElapsedTimer()
        self._play_origin = 0.0


        self._info = QLabel("00:00.00 / 00:00.00")
        self._info.setStyleSheet("color:#9aa8bb; font-family: Consolas;")

        self._play_button = QPushButton("▶ 播放")
        self._play_button.setFixedWidth(74)
        self._play_button.clicked.connect(self.toggle_play)

        prev_button = QPushButton("◀|")
        prev_button.setFixedWidth(36)
        prev_button.setToolTip("上一帧")
        prev_button.clicked.connect(lambda: self._step(-1))

        next_button = QPushButton("|▶")
        next_button.setFixedWidth(36)
        next_button.setToolTip("下一帧")
        next_button.clicked.connect(lambda: self._step(1))

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
        controls.addWidget(prev_button)
        controls.addWidget(self._play_button)
        controls.addWidget(next_button)
        controls.addWidget(self._scrub, 1)
        controls.addWidget(self._info)
        controls.addWidget(self._quality)

        # 控件不接受键盘焦点，否则空格 / 方向键会被按钮和滑块吃掉，
        # 全局快捷键（空格播放、方向键帧步进）就失效了
        for widget in (prev_button, self._play_button, next_button, self._scrub, self._quality):
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

        self._update_info()

    # ------------------------------------------------------------ 播放控制

    def toggle_play(self) -> None:
        if self._timer.isActive():
            self.stop()
        else:
            self._play_origin = self._model.playhead
            self._clock.restart()
            self._timer.start(0)
            self._apply_scale()
            self._play_button.setText("⏸ 暂停")

    def stop(self) -> None:
        self._timer.stop()
        self._play_button.setText("▶ 播放")
        self._apply_scale()

    def is_playing(self) -> bool:
        return self._timer.isActive()

    def _advance_frame(self) -> None:
        """按挂钟时间推进播放头，渲染跟不上就直接丢帧。

        以前是固定 QTimer.start(1000/fps) 每次加 1/fps，一帧画得比间隔久的时候
        定时器事件就会堆起来，越播越慢、越播越卡；现在时间只由挂钟决定，
        慢的时候表现为跳帧而不是拖慢。
        """
        fps = max(1.0, self._model.fps)
        frame_ms = 1000.0 / fps
        elapsed = self._clock.elapsed() / 1000.0
        next_time = self._play_origin + elapsed
        if next_time >= self._model.duration:
            self.stop()
            self._model.set_playhead(0.0)
            return
        self._model.set_playhead(next_time)
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

    def _on_scrub(self, value: int) -> None:
        duration = max(1e-6, self._model.duration)
        self._model.set_playhead(duration * value / 1000.0)

    # ------------------------------------------------------------ 同步

    def _on_timeline_changed(self) -> None:
        self.canvas.invalidate()
        self._update_info()

    def _on_playhead_changed(self, _seconds: float) -> None:
        self.canvas.invalidate()
        self._update_info()

    def _update_info(self) -> None:
        duration = self._model.duration
        self._info.setText(
            f"{format_timecode(self._model.playhead)} / {format_timecode(duration)}"
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
