"""多轨 Timeline 控件。

结构上分三块画布，共享同一个视图状态（缩放、滚动）：
    ┌──────────┬──────────────────────────────┐
    │ 角落      │ 时间刻度 RulerCanvas          │
    ├──────────┼──────────────────────────────┤
    │ 轨道头    │ 轨道内容 TrackCanvas          │
    │ HeaderCanvas（锁定/隐藏/上下移）         │
    └──────────┴──────────────────────────────┘
轨道头固定在左侧不随横向滚动跑掉，纵向滚动与内容联动。

交互：
- 左键点击选中，拖动本体移动（可跨轨道），拖动左右边缘裁剪
- 刻度区按下拖动 = 拖播放头
- Ctrl + 滚轮缩放，Shift + 滚轮横向滚动
- 从素材/库面板拖拽进来 = 添加元素（通过 itemDropped 信号交给主窗口处理）
- 右键弹出上下文菜单（由主窗口填充）
- 校验不通过的元素描红边/黄边

显示顺序：tracks 列表越靠后越上层，所以画布自上而下用 reversed(tracks)。

阶段 7 的三条结构性约束（细节见 docs/GUI_TIMELINE_INTERACTION_AUDIT.md）：

1. **坐标只有一个真相源**：所有时间↔像素↔轨道换算走 `gui/timeline_coordinate.TimelineCoordinate`，
   本文件里不允许再出现 `seconds * pps` 或 `x / pps`。
2. **手势期间捏坐标快照**：`TimelineInteraction` 在按下那一刻拿到一份 TimelineCoordinate，
   之后视图被任何信号滚走都不影响 grab_offset —— 修掉"点中间被当成点边缘"。
3. **一次手势只落库一次**：拖动过程只画 ghost，松手才调 `TimelineModel.move_element /
   resize_element`。这样撤销栈一次拖动一步，也不会每个 mouseMove 触发全量校验。
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt5.QtCore import QMimeData, QPoint, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPen,
)
from PyQt5.QtWidgets import (
    QAbstractScrollArea,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QToolButton,
    QWidget,
)

from core import markers as marker_utils
from core import timeline as tl
from core.time_utils import DEFAULT_FPS, format_timecode
from gui import shortcuts
from gui.timeline_coordinate import (
    DEFAULT_PPS,
    EDGE_ZONE,
    PERCENT_STEPS,
    ROW_GAP,
    ROW_HEIGHT,
    Rect,

    TimelineCoordinate,
    TimelineZoom,
)
from gui.timeline_interaction import (
    DropCommit,
    InteractionMode,
    MoveCommit,
    ResizeCommit,
    TimelineInteraction,
)
from gui.timeline_snap import SnapEngine

MIME_TYPE = "application/x-ai-timeline-item"

HEADER_WIDTH = 176
RULER_HEIGHT = 30

#: 外部文件拖进来时还不知道时长，ghost 先按这个秒数画（落库时由主窗口按真实素材算）。
UNKNOWN_DROP_SECONDS = 3.0

# 元素类型 -> (填充色, 边框色)
TYPE_COLORS = {
    "video": ("#2f6f9f", "#8fc6ef"),
    "overlay": ("#7a5aa8", "#c9aef0"),
    "text": ("#a8762f", "#f0cf8f"),
    "caption": ("#2f8f6a", "#8fefc9"),
    "caption_group": ("#2f8f8f", "#8fefef"),
    "audio": ("#3f7a3f", "#a8e0a8"),
    "effect": ("#a83f5a", "#f0a8bd"),
    "transition": ("#8f6f2f", "#efd18f"),
    "freeze": ("#5a5a8f", "#aeaee0"),
}

TRACK_KIND_COLORS = {
    "video": "#232a36",
    "text": "#2a2632",
    "audio": "#1f2b26",
}


def make_drag_payload(kind: str, item_id: str, extra: Optional[Dict[str, Any]] = None) -> QMimeData:
    """构造拖拽数据。kind 取 asset / effect / transition / caption / animation / template。"""
    payload = {"kind": kind, "id": item_id}
    if extra:
        payload.update(extra)
    mime = QMimeData()
    mime.setData(MIME_TYPE, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    mime.setText(f"{kind}:{item_id}")
    return mime


def read_drag_payload(mime: QMimeData) -> Optional[Dict[str, Any]]:
    if not mime.hasFormat(MIME_TYPE):
        return None
    try:
        return json.loads(bytes(mime.data(MIME_TYPE)).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def _to_qrect(rect: Rect) -> QRectF:
    return QRectF(rect.x, rect.y, rect.width, rect.height)


class ViewState:
    """视图状态：缩放 + 滚动 + 轨道显示序。

    它自己**不做换算**，唯一职责是产出 `TimelineCoordinate` 快照。
    这样"当前视图"与"手势用的坐标"可以是两份，互不干扰。
    """

    def __init__(self, model) -> None:
        self._model = model
        self.zoom = TimelineZoom(DEFAULT_PPS)
        self.scroll_x = 0.0
        self.scroll_y = 0.0

    # 兼容旧调用点：读写 pixels_per_second 等价于操作 TimelineZoom
    @property
    def pixels_per_second(self) -> float:
        return self.zoom.pixels_per_second

    @pixels_per_second.setter
    def pixels_per_second(self, value: float) -> None:
        self.zoom.set_zoom(value)

    def display_tracks(self) -> List[Dict[str, Any]]:
        return list(reversed(self._model.tracks()))

    def coord(self) -> TimelineCoordinate:
        return TimelineCoordinate(
            pixels_per_second=self.zoom.pixels_per_second,
            timeline_origin_x=0.0,
            scroll_x=self.scroll_x,
            scroll_y=self.scroll_y,
            fps=float(getattr(self._model, "fps", DEFAULT_FPS) or DEFAULT_FPS),
            row_height=ROW_HEIGHT,
            row_gap=ROW_GAP,
            track_order=tuple(str(t.get("id", "")) for t in self.display_tracks()),
        )


class RulerCanvas(QWidget):
    """时间刻度 + 播放头拖动区。"""

    playheadRequested = pyqtSignal(float)

    def __init__(self, model, view: ViewState, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._view = view
        self.setFixedHeight(RULER_HEIGHT)
        self.setCursor(Qt.SizeHorCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#171b24"))
        painter.setPen(QPen(QColor("#39424f")))
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)

        coord = self._view.coord()
        step = coord.tick_step()

        font = QFont("Consolas")
        font.setPointSize(7)
        painter.setFont(font)

        for seconds in coord.visible_ticks(self.width()):
            x = coord.time_to_x(seconds)
            painter.setPen(QPen(QColor("#5b687a")))
            painter.drawLine(int(x), self.height() - 9, int(x), self.height())
            painter.setPen(QPen(QColor("#9aa8bb")))
            painter.drawText(int(x) + 3, 13, format_timecode(seconds))
            # 中间再补一条细分线
            mid_x = coord.time_to_x(seconds + step / 2)
            painter.setPen(QPen(QColor("#3c4552")))
            painter.drawLine(int(mid_x), self.height() - 5, int(mid_x), self.height())

        self._paint_markers(painter, coord)

        playhead_x = coord.time_to_x(self._model.playhead)
        painter.setPen(QPen(QColor("#ff5f56"), 2))
        painter.drawLine(int(playhead_x), 0, int(playhead_x), self.height())
        painter.setBrush(QBrush(QColor("#ff5f56")))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(
            QPoint(int(playhead_x) - 6, 0),
            QPoint(int(playhead_x) + 6, 0),
            QPoint(int(playhead_x), 9),
        )
        painter.end()

    def _paint_markers(self, painter: QPainter, coord: TimelineCoordinate) -> None:
        """标记旗标。颜色按标记类型走 core/markers.py，不在这里另起一套配色。"""
        for marker in self._model.markers():
            x = coord.time_to_x(float(marker.get("time", 0.0)))
            if x < -12 or x > self.width() + 12:
                continue
            color = QColor(marker_utils.type_color(str(marker.get("type", ""))))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            # 旗杆在左、旗面朝右：旗杆正好压在标记时间上，不会让人误判 ±几像素
            painter.drawRect(int(x), 2, 2, self.height() - 4)
            painter.drawPolygon(
                QPoint(int(x) + 2, 2),
                QPoint(int(x) + 12, 6),
                QPoint(int(x) + 2, 10),
            )
            label = str(marker.get("label") or "")
            if label:
                painter.setPen(QPen(color))
                painter.drawText(int(x) + 15, 10, label)

    def _time_at(self, x: int) -> float:
        coord = self._view.coord()
        return coord.snap_time(coord.clamp_time(coord.x_to_time(x)))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.playheadRequested.emit(self._time_at(event.pos().x()))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() & Qt.LeftButton:
            self.playheadRequested.emit(self._time_at(event.pos().x()))


class HeaderCanvas(QWidget):
    """轨道头：名称、锁定、隐藏、上下移。"""

    trackFlagToggled = pyqtSignal(str, str)
    trackMoveRequested = pyqtSignal(str, int)
    trackContextRequested = pyqtSignal(str, QPoint)

    def __init__(self, model, view: ViewState, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._view = view
        self.setFixedWidth(HEADER_WIDTH)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._buttons: List[Tuple[QRect, str, str]] = []  # (区域, 轨道 id, 动作)
        self._drop_track = ""

    def set_drop_track(self, track_id: str) -> None:
        """拖放期间高亮目标轨道（第十一条）。"""
        if track_id == self._drop_track:
            return
        self._drop_track = track_id or ""
        self.update()

    def display_tracks(self) -> List[Dict[str, Any]]:
        return self._view.display_tracks()

    def content_height(self) -> int:
        return int(self._view.coord().content_height())

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(HEADER_WIDTH, self.content_height())

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#141821"))
        self._buttons.clear()
        coord = self._view.coord()

        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        metrics = QFontMetrics(font)

        for track in self.display_tracks():
            track_id = str(track.get("id", ""))
            top_f = coord.track_to_y(track_id)
            if top_f is None:
                continue
            top = int(top_f)
            if top + ROW_HEIGHT < 0 or top > self.height():
                continue
            row = QRect(0, top, HEADER_WIDTH - 1, int(ROW_HEIGHT))
            painter.fillRect(row, QColor(TRACK_KIND_COLORS.get(track.get("kind"), "#232a36")))
            if track_id == self._drop_track:
                painter.fillRect(row, QColor(127, 178, 255, 46))
                painter.setPen(QPen(QColor("#7fb2ff"), 2))
            else:
                painter.setPen(QPen(QColor("#2f3846")))
            painter.drawRect(row)

            name = track.get("name", track_id)
            painter.setPen(QPen(QColor("#7f8a99") if track.get("hidden") else QColor("#dfe6ef")))
            painter.drawText(
                QRect(8, top, HEADER_WIDTH - 74, int(ROW_HEIGHT)),
                Qt.AlignVCenter | Qt.AlignLeft,
                metrics.elidedText(name, Qt.ElideRight, HEADER_WIDTH - 78),
            )

            # Z 序提示：数字越大越上层
            painter.setPen(QPen(QColor("#5f6b7c")))
            painter.drawText(
                QRect(8, top + int(ROW_HEIGHT) - 15, 90, 13),
                Qt.AlignLeft,
                f"Z {tl.track_z_index(self._model.timeline, track_id)}"
                + ("　← 可放入" if track_id == self._drop_track else ""),
            )

            self._draw_button(painter, row, 0, "🔒" if track.get("locked") else "🔓", track_id, "locked")
            self._draw_button(painter, row, 1, "🙈" if track.get("hidden") else "👁", track_id, "hidden")
            self._draw_button(painter, row, 2, "▲", track_id, "up")
            self._draw_button(painter, row, 3, "▼", track_id, "down")
        painter.end()

    def _draw_button(
        self,
        painter: QPainter,
        row: QRect,
        slot: int,
        label: str,
        track_id: str,
        action: str,
    ) -> None:
        size = 18
        x = HEADER_WIDTH - 8 - (4 - slot) * (size + 2)
        y = row.top() + (int(ROW_HEIGHT) - size) // 2
        rect = QRect(x, y, size, size)
        painter.setPen(QPen(QColor("#4a5566")))
        painter.setBrush(QBrush(QColor("#1c222c")))
        painter.drawRoundedRect(rect, 3, 3)
        painter.setPen(QPen(QColor("#c8d2df")))
        painter.drawText(rect, Qt.AlignCenter, label)
        self._buttons.append((rect, track_id, action))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.RightButton:
            track_id = self._view.coord().y_to_track(event.pos().y())
            if track_id:
                self.trackContextRequested.emit(track_id, event.globalPos())
            return
        for rect, track_id, action in self._buttons:
            if rect.contains(event.pos()):
                if action in ("locked", "hidden"):
                    self.trackFlagToggled.emit(track_id, action)
                elif action == "up":
                    self.trackMoveRequested.emit(track_id, 1)
                else:
                    self.trackMoveRequested.emit(track_id, -1)
                return


class TrackCanvas(QWidget):
    """轨道内容：元素块的绘制与全部鼠标交互。"""

    elementClicked = pyqtSignal(str)
    elementDoubleClicked = pyqtSignal(str)
    elementContextRequested = pyqtSignal(str, QPoint)
    emptyContextRequested = pyqtSignal(str, float, QPoint)
    itemDropped = pyqtSignal(dict, str, float)
    filesDropped = pyqtSignal(list, str, float)
    playheadRequested = pyqtSignal(float)
    zoomChanged = pyqtSignal()
    dropTrackChanged = pyqtSignal(str)
    statusMessage = pyqtSignal(str)

    def __init__(self, model, view: ViewState, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._view = view
        self._issues: Dict[str, str] = {}
        self._interaction = TimelineInteraction(SnapEngine(enabled=True))
        self._hover_id = ""
        self._rubber = QRect()  # 框选矩形
        self._rubber_active = False
        self._alt_copy = False
        self._drop_info: Optional[Callable[[Dict[str, Any]], Tuple[str, float, str]]] = None
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    # ------------------------------------------------------------ 外部接线

    def set_drop_info_provider(
        self, provider: Optional[Callable[[Dict[str, Any]], Tuple[str, float, str]]]
    ) -> None:
        """主窗口注入"这个 payload 会变成什么元素、多长、叫什么"，
        ghost 才能按真实时长画。控件本身不认识素材库。"""
        self._drop_info = provider

    def set_snap_enabled(self, enabled: bool) -> None:
        self._interaction.snap.enabled = bool(enabled)
        self.update()

    def snap_enabled(self) -> bool:
        return self._interaction.snap.enabled

    def set_issues(self, issues: Dict[str, str]) -> None:
        self._issues = issues
        self.update()

    def gesture_active(self) -> bool:
        return self._interaction.active

    # ------------------------------------------------------------ 布局计算

    def coord(self) -> TimelineCoordinate:
        return self._view.coord()

    def display_tracks(self) -> List[Dict[str, Any]]:
        return self._view.display_tracks()

    def content_height(self) -> int:
        return int(self.coord().content_height())

    def content_width(self) -> float:
        return self.coord().content_width(self._model.duration)

    # ------------------------------------------------------------ 绘制

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0f131a"))
        coord = self.coord()

        self._paint_rows(painter, coord)
        self._paint_grid(painter, coord)
        self._paint_elements(painter, coord)
        self._paint_ghost(painter)
        self._paint_playhead(painter, coord)
        self._paint_snap_guide(painter)
        self._paint_rubber(painter)
        painter.end()

    def _preview_track(self) -> str:
        preview = self._interaction.preview
        return preview.track_id if preview is not None else ""

    def _paint_rows(self, painter: QPainter, coord: TimelineCoordinate) -> None:
        drop_track = self._preview_track()
        for track in self.display_tracks():
            track_id = str(track.get("id", ""))
            top_f = coord.track_to_y(track_id)
            if top_f is None:
                continue
            top = int(top_f)
            if top + ROW_HEIGHT < 0 or top > self.height():
                continue
            color = QColor(TRACK_KIND_COLORS.get(track.get("kind"), "#232a36"))
            color.setAlpha(90 if not track.get("hidden") else 40)
            painter.fillRect(QRect(0, top, self.width(), int(ROW_HEIGHT)), color)
            if track_id and track_id == drop_track:
                # Drop Zone：目标轨道整行高亮 + 蓝框，别让用户靠猜
                painter.fillRect(QRect(0, top, self.width(), int(ROW_HEIGHT)), QColor(127, 178, 255, 34))
                painter.setPen(QPen(QColor("#7fb2ff"), 1, Qt.DashLine))
                painter.drawRect(QRect(0, top, self.width() - 1, int(ROW_HEIGHT) - 1))
            if track.get("locked"):
                painter.setPen(QPen(QColor("#3a4454"), 1, Qt.DotLine))
                painter.drawRect(QRect(0, top, self.width() - 1, int(ROW_HEIGHT)))

    def _paint_grid(self, painter: QPainter, coord: TimelineCoordinate) -> None:
        painter.setPen(QPen(QColor("#1c222c")))
        for seconds in coord.visible_ticks(self.width()):
            x = int(coord.time_to_x(seconds))
            painter.drawLine(x, 0, x, self.height())

    def _paint_elements(self, painter: QPainter, coord: TimelineCoordinate) -> None:
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        selected = set(self._model.selection())
        primary = self._model.selected_id
        dragging = self._interaction.dragging_element_id

        for element in self._model.elements():
            box = coord.element_to_rect(element)
            if box is None or box.right < 0 or box.left > self.width():
                continue
            rect = _to_qrect(box)
            etype = str(element.get("type", ""))
            element_id = str(element.get("id", ""))
            fill_hex, edge_hex = TYPE_COLORS.get(etype, ("#3f4a5a", "#8f9aab"))

            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            base = QColor(fill_hex)
            if element_id == dragging:
                # 正在拖的原件画淡一点，ghost 才是主角
                base = base.darker(150)
            gradient.setColorAt(0.0, base.lighter(118))
            gradient.setColorAt(1.0, base.darker(112))
            painter.setBrush(QBrush(gradient))

            issue = self._issues.get(element_id)
            if issue == "error":
                painter.setPen(QPen(QColor("#ff5f56"), 2))
            elif issue == "warning":
                painter.setPen(QPen(QColor("#ffbd2e"), 2))
            elif element_id == primary:
                painter.setPen(QPen(QColor("#ffffff"), 2))
            elif element_id in selected:
                # 多选里的非主选中，用偏蓝的粗边区分
                painter.setPen(QPen(QColor("#7fb2ff"), 2))
            elif element_id == self._hover_id:
                painter.setPen(QPen(QColor(edge_hex).lighter(130), 2))
            else:
                painter.setPen(QPen(QColor(edge_hex), 1))
            painter.drawRoundedRect(rect, 4, 4)

            # 转场块画成对角条纹，和普通片段区分开
            if etype == "transition":
                painter.save()
                painter.setClipRect(rect)
                painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
                stripe = int(rect.left()) - int(ROW_HEIGHT)
                while stripe < rect.right():
                    painter.drawLine(stripe, int(rect.bottom()), stripe + int(ROW_HEIGHT), int(rect.top()))
                    stripe += 7
                painter.restore()

            # 有关键帧的元素在底部画标记点
            keyframes = element.get("keyframes") or {}
            if keyframes:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor("#ffe347")))
                duration = max(1e-6, float(element.get("duration", 0.0) or 0.0))
                for points in keyframes.values():
                    for point in points:
                        ratio = min(1.0, max(0.0, float(point.get("time", 0.0)) / duration))
                        kx = rect.left() + rect.width() * ratio
                        painter.drawEllipse(QRectF(kx - 2, rect.bottom() - 5, 4, 4))

            if rect.width() > 26:
                inner = QRectF(rect.left() + 6, rect.top(), rect.width() - 12, rect.height())
                painter.setPen(QPen(QColor("#f2f6fb")))
                painter.drawText(
                    QRectF(inner.left(), inner.top() + 1, inner.width(), inner.height() / 2),
                    Qt.AlignVCenter | Qt.AlignLeft,
                    metrics.elidedText(self._element_label(element), Qt.ElideRight, int(inner.width())),
                )
                # 第三十五条：片段上要能直接看到时长
                painter.setPen(QPen(QColor("#c2cfdf")))
                painter.drawText(
                    QRectF(inner.left(), inner.top() + inner.height() / 2, inner.width(), inner.height() / 2),
                    Qt.AlignVCenter | Qt.AlignLeft,
                    f"{float(element.get('duration', 0.0) or 0.0):.2f}s",
                )

            # Resize 手柄：选中或悬停时画出来，告诉用户这里能拉
            if (element_id in selected or element_id == self._hover_id) and rect.width() >= EDGE_ZONE * 3:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(255, 255, 255, 120)))
                for hx in (rect.left() + 2, rect.right() - 4):
                    painter.drawRect(QRectF(hx, rect.top() + 4, 2, rect.height() - 8))

    def _paint_ghost(self, painter: QPainter) -> None:
        """拖动 / 拖入过程中的 Ghost Clip（第十二条）。"""
        preview = self._interaction.preview
        coord = self._interaction.coordinate()
        if preview is None or coord is None or not preview.track_id:
            return
        top = coord.track_to_y(preview.track_id)
        if top is None:
            return
        x = coord.time_to_x(preview.start)
        width = max(2.0, coord.duration_to_width(preview.duration))
        rect = QRectF(x, top + 2.0, width, ROW_HEIGHT - 4.0)

        edge = QColor("#7fb2ff") if preview.valid else QColor("#ff5f56")
        painter.setBrush(QBrush(QColor(127, 178, 255, 60) if preview.valid else QColor(255, 95, 86, 60)))
        painter.setPen(QPen(edge, 2, Qt.DashLine))
        painter.drawRoundedRect(rect, 4, 4)

        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QPen(QColor("#f2f6fb")))
        text = f"{preview.label}　{preview.start:.2f}s → {preview.end:.2f}s（{preview.duration:.2f}s）"
        if not preview.valid and preview.reason:
            text = f"✕ {preview.reason}"
        painter.drawText(
            QRectF(rect.left() + 6, rect.top(), max(120.0, rect.width() - 12), rect.height()),
            Qt.AlignVCenter | Qt.AlignLeft,
            text,
        )

    def _paint_snap_guide(self, painter: QPainter) -> None:
        """吸附提示线 + 标签：让用户知道"为什么突然吸到这里"（第九条）。"""
        preview = self._interaction.preview
        coord = self._interaction.coordinate()
        if preview is None or coord is None or preview.snap_time is None:
            return
        x = int(coord.time_to_x(preview.snap_time))
        painter.setPen(QPen(QColor("#ffe347"), 1, Qt.DashLine))
        painter.drawLine(x, 0, x, self.height())
        painter.setPen(QPen(QColor("#ffe347")))
        font = QFont()
        font.setPointSize(7)
        painter.setFont(font)
        painter.drawText(
            QRectF(x + 4, 2, 220, 14),
            Qt.AlignVCenter | Qt.AlignLeft,
            f"{preview.snap_time:.2f}s　{preview.snap_label}",
        )

    def _paint_rubber(self, painter: QPainter) -> None:
        if self._rubber.isNull() or not self._rubber_active:
            return
        painter.setPen(QPen(QColor("#7fb2ff"), 1, Qt.DashLine))
        painter.setBrush(QBrush(QColor(127, 178, 255, 40)))
        painter.drawRect(self._rubber)

    def _element_label(self, element: Dict[str, Any]) -> str:
        etype = element.get("type", "")
        if etype in ("video", "overlay", "audio"):
            return f"{element.get('id')} {self._model_asset_name(element.get('asset'))}"
        if etype in ("text", "caption"):
            return f"{element.get('id')} {(element.get('content') or {}).get('text', '')}"
        if etype == "caption_group":
            words = (element.get("content") or {}).get("words") or []
            preview = " ".join(str(w.get("text", "")) for w in words[:4])
            return f"{element.get('id')} {preview}"
        if etype in ("effect", "transition"):
            return f"{element.get('id')} {element.get('name', '')}"
        if etype == "freeze":
            return f"{element.get('id')} 冻结 @{element.get('source_time')}s"
        return str(element.get("id", ""))

    def _model_asset_name(self, asset_id: Optional[str]) -> str:
        if not asset_id:
            return ""
        manager = getattr(self._model, "asset_manager", None)
        if manager is not None:
            return manager.name_of(asset_id)
        return asset_id

    def _paint_playhead(self, painter: QPainter, coord: TimelineCoordinate) -> None:
        x = int(coord.time_to_x(self._model.playhead))
        painter.setPen(QPen(QColor("#ff5f56"), 1))
        painter.drawLine(x, 0, x, self.height())

    # ------------------------------------------------------------ 鼠标

    def _element_at(self, pos: QPoint) -> Optional[Dict[str, Any]]:
        hit = TimelineInteraction.hit_test(self.coord(), self._model.elements(), pos.x(), pos.y())
        return hit.element

    def mousePressEvent(self, event) -> None:  # noqa: N802
        coord = self.coord()
        elements = self._model.elements()
        hit = TimelineInteraction.hit_test(coord, elements, event.pos().x(), event.pos().y())

        if event.button() == Qt.RightButton:
            if hit.element:
                # 右键点在已选中的多个元素之一上时，保持多选，方便批量操作
                if hit.element_id not in self._model.selection():
                    self._model.select(hit.element_id)
                self.elementContextRequested.emit(hit.element_id, event.globalPos())
            else:
                self.emptyContextRequested.emit(hit.track_id or "", hit.time, event.globalPos())
            return

        if event.button() != Qt.LeftButton:
            return

        if hit.element is None:
            # 空白处按下：先记下起点，移动了就是框选，没移动就是挪播放头
            self._interaction.begin_press(coord, elements, event.pos().x(), event.pos().y())
            self._rubber_active = True
            self._rubber = QRect(event.pos(), event.pos())
            return

        if event.modifiers() & Qt.ControlModifier:
            # Ctrl + 点击：加选 / 取消选中，不进入拖动
            self._model.toggle_select(hit.element_id)
            return

        locked = self._model.is_track_locked(str(hit.element.get("track", "")))
        # 关键顺序：**先按坐标快照建立手势**，再动选中状态。
        # 选中会触发 selectionChanged → 主窗口可能横向滚动视图，
        # 阶段 7 之前先 select 再算 rect，于是"点中间"被算成"点边缘"。
        self._interaction.begin_press(
            coord,
            elements,
            event.pos().x(),
            event.pos().y(),
            selection=self._model.selection(),
            allow_edit=not locked,
            markers=self._model.marker_times(),
        )
        self._alt_copy = bool(event.modifiers() & Qt.AltModifier) and not locked

        self.elementClicked.emit(hit.element_id)
        if not (hit.element_id in self._model.selection() and len(self._model.selection()) > 1):
            self._model.select(hit.element_id)
        self._interaction.set_snap_targets(
            elements,
            playhead=float(self._model.playhead),
            exclude_ids=[hit.element_id, *self._interaction.followers()],
            markers=self._model.marker_times(),
        )

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._rubber_active:
            self._rubber = QRect(
                QPoint(*(int(v) for v in self._interaction.rubber_origin())), event.pos()
            ).normalized()
            self.update()
            return

        if not self._interaction.active:
            self._update_hover(event.pos())
            return

        preview = self._interaction.update(
            event.pos().x(), event.pos().y(), self._model.tracks(), self._model.elements()
        )
        if preview is not None:
            self.dropTrackChanged.emit(preview.track_id)
            if not preview.valid and preview.reason:
                self.statusMessage.emit(preview.reason)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._rubber_active:
            moved = self._rubber.width() > 3 or self._rubber.height() > 3
            if moved:
                self._select_in_rect(self._rubber)
            else:
                coord = self.coord()
                self.playheadRequested.emit(
                    coord.snap_time(coord.clamp_time(coord.x_to_time(event.pos().x())))
                )
                self._model.select("")
            self._rubber = QRect()
            self._rubber_active = False
            self._interaction.reset()
            self.update()
            return

        self._commit_gesture()
        self._interaction.reset()
        self.dropTrackChanged.emit("")
        self.update()

    def _commit_gesture(self) -> None:
        """一次手势 → 一次落库。GUI 只调 TimelineModel 的公开方法。"""
        commit = self._interaction.commit()
        if commit is None:
            return
        if isinstance(commit, MoveCommit):
            element_id = commit.element_id
            if self._alt_copy:
                clone_id = self._model.duplicate_in_place(element_id)
                if clone_id:
                    element_id = clone_id
                    self._model.select(clone_id)
            self._model.move_element(element_id, commit.start, commit.track_id)
            for follower_id, start in commit.followers:
                if self._model.is_track_locked(
                    str((self._model.element(follower_id) or {}).get("track", ""))
                ):
                    continue
                self._model.move_element(follower_id, start, None)
        elif isinstance(commit, ResizeCommit):
            self._model.resize_element(commit.element_id, commit.start, commit.duration)
        self._alt_copy = False

    def _select_in_rect(self, rect: QRect) -> None:
        """框选：和矩形有交集的元素全部选中。"""
        coord = self.coord()
        box = Rect(rect.x(), rect.y(), rect.width(), rect.height())
        hits: List[str] = []
        for element in self._model.elements():
            element_rect = coord.element_to_hit_rect(element)
            if element_rect is not None and element_rect.intersects(box):
                hits.append(str(element.get("id", "")))
        self._model.select_many(hits)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        element = self._element_at(event.pos())
        if element:
            self.elementDoubleClicked.emit(str(element.get("id", "")))

    def _update_hover(self, pos: QPoint) -> None:
        coord = self.coord()
        hit = TimelineInteraction.hit_test(coord, self._model.elements(), pos.x(), pos.y())
        hover_id = hit.element_id
        if hover_id != self._hover_id:
            self._hover_id = hover_id
            self.update()
        if hit.element is None:
            self.setCursor(Qt.ArrowCursor)
            return
        self.setCursor(Qt.SizeHorCursor if hit.zone in ("left", "right") else Qt.OpenHandCursor)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._hover_id:
            self._hover_id = ""
            self.update()

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.ControlModifier:
            # 以鼠标位置为锚点缩放，手感和专业剪辑软件一致
            coord = self.coord()
            anchor_time = coord.x_to_time(event.pos().x())
            factor = 1.25 if event.angleDelta().y() > 0 else 0.8
            new_pps = self._view.zoom.set_zoom(coord.pixels_per_second * factor)
            self._view.scroll_x = coord.with_zoom(new_pps).scroll_for_anchor(
                anchor_time, event.pos().x()
            )
            self.zoomChanged.emit()
            event.accept()
            return
        event.ignore()

    # ------------------------------------------------------------ 拖放

    @staticmethod
    def _local_files(mime) -> List[str]:
        """从系统拖放里取本地文件路径（从资源管理器直接拖素材进来）。"""
        if not mime.hasUrls():
            return []
        return [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]

    def _begin_external_drag(self, mime) -> bool:
        """把一次外部拖入变成 DRAG_ASSET 手势，这样 ghost / 磁吸 / 轨道校验全都走同一条路。"""
        payload = read_drag_payload(mime)
        files = self._local_files(mime)
        if payload is None and not files:
            return False
        if payload is None:
            payload = {"kind": "files", "files": files}
            element_type = "video"
            duration = UNKNOWN_DROP_SECONDS
            label = os.path.basename(files[0]) + (f" 等 {len(files)} 个" if len(files) > 1 else "")
        else:
            element_type, duration, label = self._resolve_drop_info(payload)
        self._interaction.begin_asset_drag(
            self.coord(),
            self._model.elements(),
            payload,
            duration,
            element_type,
            label,
            playhead=float(self._model.playhead),
            markers=self._model.marker_times(),
        )
        return True

    def _resolve_drop_info(self, payload: Dict[str, Any]) -> Tuple[str, float, str]:
        if self._drop_info is not None:
            try:
                return self._drop_info(payload)
            except Exception:  # pragma: no cover - 提供方异常不能让拖放崩掉
                pass
        kind = str(payload.get("kind", ""))
        default_type = {
            "effect": "effect",
            "effect_material": "overlay",
            "transition": "transition",
            "caption": "caption",
        }.get(kind, "video")
        return (default_type, UNKNOWN_DROP_SECONDS, str(payload.get("id", kind)))

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._begin_external_drag(event.mimeData()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._interaction.mode != InteractionMode.DRAG_ASSET and not self._begin_external_drag(
            event.mimeData()
        ):
            return
        preview = self._interaction.update(
            event.pos().x(), event.pos().y(), self._model.tracks(), self._model.elements()
        )
        if preview is not None:
            self.dropTrackChanged.emit(preview.track_id)
            if preview.valid:
                event.acceptProposedAction()
                if preview.note:
                    # 落位策略换了轨道：ghost 已经跳过去了，状态栏说明为什么
                    self.statusMessage.emit(preview.note)
            else:
                # 明确拒绝而不是静默失败（第二十六条）
                event.ignore()
                self.statusMessage.emit(preview.reason)
        self.update()


    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._interaction.reset()
        self.dropTrackChanged.emit("")
        self.update()

    def dropEvent(self, event) -> None:  # noqa: N802
        preview = self._interaction.update(
            event.pos().x(), event.pos().y(), self._model.tracks(), self._model.elements()
        )
        commit = self._interaction.commit() if preview is not None else None
        self._interaction.reset()
        self.dropTrackChanged.emit("")
        self.update()

        if preview is not None and not preview.valid:
            self.statusMessage.emit(preview.reason)
            return
        if not isinstance(commit, DropCommit):
            return

        files = commit.payload.get("files")
        if files:
            self.filesDropped.emit(list(files), commit.track_id, commit.start)
        else:
            self.itemDropped.emit(commit.payload, commit.track_id, commit.start)
        event.acceptProposedAction()


class TimelineWidget(QAbstractScrollArea):
    """把三块画布 + 底部工具条拼起来，并负责滚动条与刷新。"""

    elementDoubleClicked = pyqtSignal(str)
    elementContextRequested = pyqtSignal(str, QPoint)
    emptyContextRequested = pyqtSignal(str, float, QPoint)
    trackContextRequested = pyqtSignal(str, QPoint)
    itemDropped = pyqtSignal(dict, str, float)
    filesDropped = pyqtSignal(list, str, float)
    statusMessage = pyqtSignal(str)
    # 工具条按钮：由主窗口接到具体动作上，和快捷键走同一套实现
    splitRequested = pyqtSignal()
    deleteRequested = pyqtSignal()
    freezeRequested = pyqtSignal()
    duplicateRequested = pyqtSignal()

    def __init__(self, model, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._view = ViewState(model)

        container = QWidget()
        layout = QGridLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        corner = QWidget()
        corner.setFixedSize(HEADER_WIDTH, RULER_HEIGHT)
        corner.setStyleSheet("background-color: #171b24;")

        self.ruler = RulerCanvas(model, self._view)
        self.header = HeaderCanvas(model, self._view)
        self.canvas = TrackCanvas(model, self._view)
        self._toolbar = self._build_toolbar()

        layout.addWidget(corner, 0, 0)
        layout.addWidget(self.ruler, 0, 1)
        layout.addWidget(self.header, 1, 0)
        layout.addWidget(self.canvas, 1, 1)
        layout.addWidget(self._toolbar, 2, 0, 1, 2)
        layout.setRowStretch(1, 1)
        layout.setColumnStretch(1, 1)

        self.setViewport(container)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFrameShape(QAbstractScrollArea.NoFrame)

        self.ruler.playheadRequested.connect(model.set_playhead)
        self.canvas.playheadRequested.connect(model.set_playhead)
        self.canvas.elementClicked.connect(self._on_element_clicked)
        self.canvas.elementDoubleClicked.connect(self.elementDoubleClicked)
        self.canvas.elementContextRequested.connect(self.elementContextRequested)
        self.canvas.emptyContextRequested.connect(self.emptyContextRequested)
        self.canvas.itemDropped.connect(self.itemDropped)
        self.canvas.filesDropped.connect(self.filesDropped)
        self.canvas.zoomChanged.connect(self._on_zoom_changed)
        self.canvas.dropTrackChanged.connect(self.header.set_drop_track)
        self.canvas.statusMessage.connect(self.statusMessage)
        self.header.trackFlagToggled.connect(model.toggle_track_flag)
        self.header.trackMoveRequested.connect(model.move_track)
        self.header.trackContextRequested.connect(self.trackContextRequested)

        self.horizontalScrollBar().valueChanged.connect(self._on_h_scroll)
        self.verticalScrollBar().valueChanged.connect(self._on_v_scroll)

        model.timelineChanged.connect(self.refresh)
        model.elementUpdated.connect(lambda _id: self.refresh())
        model.selectionChanged.connect(lambda _id: self._repaint_all())
        model.playheadChanged.connect(self._on_playhead_changed)

    # ------------------------------------------------------------ 工具条

    def _build_toolbar(self) -> QWidget:
        """底部工具条：常用剪辑动作 + 磁吸 / 跟随 / 缩放，不用翻菜单。"""
        bar = QWidget()
        bar.setFixedHeight(30)
        bar.setStyleSheet("background-color:#141922;")
        row = QHBoxLayout(bar)
        row.setContentsMargins(6, 2, 6, 2)
        row.setSpacing(4)

        def add_button(text: str, tip: str, slot) -> QToolButton:
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tip)
            button.setFocusPolicy(Qt.NoFocus)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(slot)
            row.addWidget(button)
            return button

        add_button("✂ 分割", f"在播放头处分割选中片段（{shortcuts.primary('split')}）", self.splitRequested)
        add_button("🗑 删除", f"删除选中元素（{shortcuts.primary('delete')}）", self.deleteRequested)
        add_button("❚❚ 定格", f"在播放头处加冻结帧（{shortcuts.primary('freeze')}）", self.freezeRequested)
        add_button("⧉ 复制", f"原地复制一份（{shortcuts.primary('duplicate')}）", self.duplicateRequested)

        row.addSpacing(8)
        self._snap_button = QToolButton()
        self._snap_button.setText("🧲 磁吸")
        self._snap_button.setCheckable(True)
        self._snap_button.setChecked(True)
        self._snap_button.setFocusPolicy(Qt.NoFocus)
        self._snap_button.setToolTip(
            f"拖动时吸附到刻度、播放头、相邻片段的首尾与中心（{shortcuts.primary('toggle_snap')}）"
        )
        self._snap_button.toggled.connect(self.canvas.set_snap_enabled)
        row.addWidget(self._snap_button)

        self._follow_button = QToolButton()
        self._follow_button.setText("⇥ 跟随播放头")
        self._follow_button.setCheckable(True)
        self._follow_button.setChecked(True)
        self._follow_button.setFocusPolicy(Qt.NoFocus)
        self._follow_button.setToolTip("播放时时间线自动横向滚动，让播放头始终可见")
        row.addWidget(self._follow_button)

        row.addStretch(1)

        self._time_label = QLabel("00:00.00 / 00:00.00")
        self._time_label.setStyleSheet("color:#9aa8bb; font-family: Consolas;")
        row.addWidget(self._time_label)

        row.addSpacing(8)
        self._zoom_label = QLabel("100% · 80 px/s")
        self._zoom_label.setStyleSheet("color:#6f7b8c; font-family: Consolas;")
        row.addWidget(self._zoom_label)
        add_button("－", f"缩小一档（{shortcuts.primary('zoom_out')}）", self.zoom_out)
        self._zoom_combo = QComboBox()
        self._zoom_combo.setFixedWidth(78)
        self._zoom_combo.setFocusPolicy(Qt.NoFocus)
        self._zoom_combo.setToolTip("缩放档位（100% = 80 px/s）")
        for percent in PERCENT_STEPS:
            self._zoom_combo.addItem(TimelineZoom.percent_label(percent), percent)
        self._zoom_combo.setCurrentIndex(self._view.zoom.step_index())
        self._zoom_combo.activated.connect(self._on_zoom_combo)
        row.addWidget(self._zoom_combo)
        self._zoom_slider = QSlider(Qt.Horizontal)
        self._zoom_slider.setFixedWidth(120)
        self._zoom_slider.setRange(0, 100)
        self._zoom_slider.setValue(int(self._view.zoom.slider_ratio() * 100))
        self._zoom_slider.setFocusPolicy(Qt.NoFocus)
        self._zoom_slider.setToolTip("时间线缩放（自由拖动，档位见左侧下拉）")
        self._zoom_slider.valueChanged.connect(self._on_zoom_slider)
        row.addWidget(self._zoom_slider)

        add_button("＋", f"放大一档（{shortcuts.primary('zoom_in')}）", self.zoom_in)
        add_button("⤢ 适配", f"缩放到整条时间线（{shortcuts.primary('zoom_fit')}）", self.zoom_to_fit)
        return bar

    # ------------------------------------------------------------ 缩放

    def _on_zoom_slider(self, value: int) -> None:
        self._view.zoom.set_zoom(TimelineZoom.ratio_to_zoom(value / 100.0))
        self._sync_scrollbars()
        self._update_zoom_label()
        self._repaint_all()

    def _on_zoom_combo(self, index: int) -> None:
        """下拉选档：以视口中心的时间为锚点，缩放前后中心不跑。"""
        percent = self._zoom_combo.itemData(index)
        if percent is None:
            return
        coord = self.coord()
        center_x = max(1.0, self.canvas.width() / 2.0)
        anchor_time = coord.x_to_time(center_x)
        new_pps = self._view.zoom.set_percent(float(percent))
        self._view.scroll_x = coord.with_zoom(new_pps).scroll_for_anchor(anchor_time, center_x)
        self._sync_zoom_slider()
        self.refresh()


    def _on_zoom_changed(self) -> None:
        """Ctrl+滚轮缩放后，把滑块同步过来。"""
        self._sync_zoom_slider()
        self._sync_scrollbars()

    def zoom(self, factor: float) -> None:
        """按倍数缩放（保留旧接口，菜单与快捷键在用）。"""
        self._view.zoom.set_zoom(self._view.zoom.pixels_per_second * float(factor))
        self._sync_zoom_slider()
        self.refresh()

    def zoom_in(self) -> None:
        self._view.zoom.zoom_in()
        self._sync_zoom_slider()
        self.refresh()

    def zoom_out(self) -> None:
        self._view.zoom.zoom_out()
        self._sync_zoom_slider()
        self.refresh()

    def zoom_to_fit(self) -> None:
        self._view.zoom.fit_project(max(self._model.duration, 1.0), max(120, self.canvas.width() - 20))
        self._view.scroll_x = 0.0
        self._sync_zoom_slider()
        self.refresh()

    def zoom_to_selection(self) -> None:
        element = self._model.element(self._model.selected_id)
        if element is None:
            self.zoom_to_fit()
            return
        start = float(element.get("start", 0.0) or 0.0)
        end = start + float(element.get("duration", 0.0) or 0.0)
        self._view.zoom.fit_selection(start, end, max(120, self.canvas.width() - 20))
        self._view.scroll_x = self._view.coord().scroll_for_anchor(start, 20.0)
        self._sync_zoom_slider()
        self.refresh()

    def pixels_per_second(self) -> float:
        return self._view.zoom.pixels_per_second

    def coordinate(self) -> TimelineCoordinate:
        """给测试与外部工具用的坐标快照。"""
        return self._view.coord()

    def _sync_zoom_slider(self) -> None:
        self._zoom_slider.blockSignals(True)
        self._zoom_slider.setValue(int(self._view.zoom.slider_ratio() * 100))
        self._zoom_slider.blockSignals(False)
        self._zoom_combo.blockSignals(True)
        self._zoom_combo.setCurrentIndex(self._view.zoom.step_index())
        self._zoom_combo.blockSignals(False)
        self._update_zoom_label()

    def _update_zoom_label(self) -> None:
        zoom = self._view.zoom
        self._zoom_label.setText(
            f"{zoom.percent():g}% · {zoom.pixels_per_second:.0f} px/s"
        )


    # ------------------------------------------------------------ 磁吸 / 选中

    def toggle_snap(self) -> None:
        self._snap_button.setChecked(not self._snap_button.isChecked())

    def snap_enabled(self) -> bool:
        return self._snap_button.isChecked()

    def set_drop_info_provider(self, provider) -> None:
        self.canvas.set_drop_info_provider(provider)

    def _on_element_clicked(self, element_id: str) -> None:
        """画布点击已经处理过选中逻辑（含 Ctrl 加选），这里只做转发。"""
        if element_id and element_id not in self._model.selection():
            self._model.select(element_id)

    # ------------------------------------------------------------ 播放头跟随

    def _on_playhead_changed(self, seconds: float) -> None:
        if self._follow_button.isChecked():
            self._ensure_playhead_visible(seconds)
        self._update_time_label()
        # 播放头只影响标尺和轨道区；左侧轨道头没有播放头，播放时不用跟着重画
        self.ruler.update()
        self.canvas.update()

    def _ensure_playhead_visible(self, seconds: float) -> None:
        """播放头快出画面时把视图推过去，播放时看起来就像剪映那样自动跑。"""
        if self.canvas.gesture_active():
            return
        coord = self._view.coord()
        width = max(1, self.canvas.width())
        x = coord.time_to_x(seconds)
        left_margin = width * 0.1
        if left_margin <= x <= width * 0.85:
            return
        target = coord.scroll_for_anchor(seconds, left_margin)
        bar = self.horizontalScrollBar()
        if int(target) != bar.value():
            bar.setValue(int(target))

    def _update_time_label(self) -> None:
        self._time_label.setText(
            f"{format_timecode(self._model.playhead)} / {format_timecode(self._model.duration)}"
        )

    # ------------------------------------------------------------ 刷新

    def refresh(self) -> None:
        self._sync_scrollbars()
        self._update_time_label()
        self._update_zoom_label()
        self._repaint_all()

    def set_issues(self, issues: Dict[str, str]) -> None:
        self.canvas.set_issues(issues)

    def scroll_to_time(self, seconds: float) -> None:
        """把某个时间点滚到可见区域，JSON 面板反选元素时用。

        只在目标**不可见**时才滚，而且手势期间绝不滚：
        阶段 7 之前这里无条件把选中元素居中，于是在 mousePressEvent 里
        选中 → 视图横移 → 后续边缘判定全错（审计第 17 问）。
        """
        if self.canvas.gesture_active():
            return
        coord = self._view.coord()
        x = coord.time_to_x(seconds)
        width = max(1, self.canvas.width())
        if 0.0 <= x <= width - 1:
            return
        target = coord.scroll_for_anchor(seconds, width * 0.25)
        self.horizontalScrollBar().setValue(int(target))

    def _repaint_all(self) -> None:
        self.ruler.update()
        self.header.update()
        self.canvas.update()

    def _sync_scrollbars(self) -> None:
        coord = self._view.coord()
        h_bar = self.horizontalScrollBar()
        page = max(1, self.canvas.width())
        h_bar.setPageStep(page)
        h_bar.setSingleStep(40)
        h_bar.setRange(0, max(0, int(coord.content_width(self._model.duration) - page)))

        v_bar = self.verticalScrollBar()
        v_page = max(1, self.canvas.height())
        v_bar.setPageStep(v_page)
        v_bar.setSingleStep(int(ROW_HEIGHT))
        v_bar.setRange(0, max(0, int(coord.content_height()) - v_page))

    def _on_h_scroll(self, value: int) -> None:
        self._view.scroll_x = float(value)
        self._repaint_all()

    def _on_v_scroll(self, value: int) -> None:
        self._view.scroll_y = float(value)
        self._repaint_all()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_scrollbars()

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # noqa: N802
        # 滚动完全由 valueChanged 处理，这里不做默认的像素搬移
        self._repaint_all()
