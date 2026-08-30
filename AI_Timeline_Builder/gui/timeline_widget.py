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
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Tuple

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
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollBar,
    QSizePolicy,
    QSlider,
    QToolButton,
    QWidget,
)

from core import timeline as tl
from core.time_utils import format_timecode
from gui import shortcuts

MIME_TYPE = "application/x-ai-timeline-item"

HEADER_WIDTH = 168
RULER_HEIGHT = 26
ROW_HEIGHT = 38
ROW_GAP = 2
MIN_PPS = 8.0
MAX_PPS = 600.0
EDGE_GRAB = 6
# 磁吸容差（像素）。按像素算，缩放后手感一致
SNAP_PIXELS = 8

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


class ViewState:
    """缩放与滚动的共享状态。"""

    def __init__(self) -> None:
        self.pixels_per_second = 60.0
        self.scroll_x = 0.0
        self.scroll_y = 0.0

    def x_for_time(self, seconds: float) -> float:
        return seconds * self.pixels_per_second - self.scroll_x

    def time_for_x(self, x: float) -> float:
        return max(0.0, (x + self.scroll_x) / self.pixels_per_second)

    def width_for_duration(self, seconds: float) -> float:
        return max(1.0, seconds * self.pixels_per_second)


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

        pps = self._view.pixels_per_second
        # 根据缩放挑一个人能看懂的刻度间隔
        for step in (0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0):
            if step * pps >= 62:
                break
        start_time = self._view.time_for_x(0)
        end_time = self._view.time_for_x(self.width())

        font = QFont("Consolas")
        font.setPointSize(7)
        painter.setFont(font)

        index = int(start_time / step)
        while True:
            seconds = index * step
            if seconds > end_time + step:
                break
            x = self._view.x_for_time(seconds)
            painter.setPen(QPen(QColor("#5b687a")))
            painter.drawLine(int(x), self.height() - 8, int(x), self.height())
            painter.setPen(QPen(QColor("#9aa8bb")))
            painter.drawText(int(x) + 3, 12, format_timecode(seconds))
            # 中间再补一条细分线
            mid_x = self._view.x_for_time(seconds + step / 2)
            painter.setPen(QPen(QColor("#3c4552")))
            painter.drawLine(int(mid_x), self.height() - 4, int(mid_x), self.height())
            index += 1

        playhead_x = self._view.x_for_time(self._model.playhead)
        painter.setPen(QPen(QColor("#ff5f56"), 2))
        painter.drawLine(int(playhead_x), 0, int(playhead_x), self.height())
        painter.setBrush(QBrush(QColor("#ff5f56")))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(
            QPoint(int(playhead_x) - 5, 0),
            QPoint(int(playhead_x) + 5, 0),
            QPoint(int(playhead_x), 8),
        )
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.playheadRequested.emit(self._view.time_for_x(event.pos().x()))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() & Qt.LeftButton:
            self.playheadRequested.emit(self._view.time_for_x(event.pos().x()))


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

    def display_tracks(self) -> List[Dict[str, Any]]:
        return list(reversed(self._model.tracks()))

    def content_height(self) -> int:
        return len(self._model.tracks()) * (ROW_HEIGHT + ROW_GAP)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(HEADER_WIDTH, self.content_height())

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#141821"))
        self._buttons.clear()

        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        metrics = QFontMetrics(font)

        for index, track in enumerate(self.display_tracks()):
            top = index * (ROW_HEIGHT + ROW_GAP) - int(self._view.scroll_y)
            if top + ROW_HEIGHT < 0 or top > self.height():
                continue
            row = QRect(0, top, HEADER_WIDTH - 1, ROW_HEIGHT)
            painter.fillRect(row, QColor(TRACK_KIND_COLORS.get(track.get("kind"), "#232a36")))
            painter.setPen(QPen(QColor("#2f3846")))
            painter.drawRect(row)

            name = track.get("name", track.get("id", ""))
            painter.setPen(QPen(QColor("#7f8a99") if track.get("hidden") else QColor("#dfe6ef")))
            painter.drawText(
                QRect(8, top, HEADER_WIDTH - 74, ROW_HEIGHT),
                Qt.AlignVCenter | Qt.AlignLeft,
                metrics.elidedText(name, Qt.ElideRight, HEADER_WIDTH - 78),
            )

            # Z 序提示：数字越大越上层
            painter.setPen(QPen(QColor("#5f6b7c")))
            painter.drawText(
                QRect(8, top + ROW_HEIGHT - 14, 60, 12),
                Qt.AlignLeft,
                f"Z {tl.track_z_index(self._model.timeline, track.get('id'))}",
            )

            self._draw_button(painter, row, 0, "🔒" if track.get("locked") else "🔓", track["id"], "locked")
            self._draw_button(painter, row, 1, "🙈" if track.get("hidden") else "👁", track["id"], "hidden")
            self._draw_button(painter, row, 2, "▲", track["id"], "up")
            self._draw_button(painter, row, 3, "▼", track["id"], "down")
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
        size = 16
        x = HEADER_WIDTH - 8 - (4 - slot) * (size + 2)
        y = row.top() + (ROW_HEIGHT - size) // 2
        rect = QRect(x, y, size, size)
        painter.setPen(QPen(QColor("#4a5566")))
        painter.setBrush(QBrush(QColor("#1c222c")))
        painter.drawRoundedRect(rect, 3, 3)
        painter.setPen(QPen(QColor("#c8d2df")))
        painter.drawText(rect, Qt.AlignCenter, label)
        self._buttons.append((rect, track_id, action))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.RightButton:
            track_id = self._track_at(event.pos().y())
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

    def _track_at(self, y: int) -> str:
        index = int((y + self._view.scroll_y) // (ROW_HEIGHT + ROW_GAP))
        tracks = self.display_tracks()
        if 0 <= index < len(tracks):
            return tracks[index].get("id", "")
        return ""


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


    def __init__(self, model, view: ViewState, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._view = view
        self._issues: Dict[str, str] = {}
        self._drag_mode = ""  # move / trim_left / trim_right / rubber
        self._drag_id = ""
        self._drag_origin = QPoint()
        self._drag_start_time = 0.0
        self._drag_start_duration = 0.0
        self._drag_track = ""
        self._drag_copy_done = False  # Alt 拖动只在第一次移动时复制
        self._hover_id = ""
        self._rubber = QRect()  # 框选矩形
        self._snap_enabled = True
        self._snap_line: Optional[float] = None  # 正在吸附的时间点，用来画提示线
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    # ------------------------------------------------------------ 磁吸

    def set_snap_enabled(self, enabled: bool) -> None:
        self._snap_enabled = bool(enabled)
        self.update()

    def snap_enabled(self) -> bool:
        return self._snap_enabled

    def _snap_targets(self, exclude_ids: List[str]) -> List[float]:
        """可以吸附的时间点：0、播放头、其它元素的首尾。"""
        targets = [0.0, float(self._model.playhead)]
        for element in self._model.elements():
            if element.get("id") in exclude_ids:
                continue
            start = float(element.get("start", 0.0))
            targets.append(start)
            targets.append(round(start + float(element.get("duration", 0.0)), 6))
        return targets

    def _snap_time(self, seconds: float, exclude_ids: List[str]) -> float:
        """把时间吸到最近的目标点上。容差按像素算，缩放后手感一致。"""
        self._snap_line = None
        if not self._snap_enabled:
            return seconds
        tolerance = SNAP_PIXELS / max(1e-6, self._view.pixels_per_second)
        best = seconds
        best_gap = tolerance
        for target in self._snap_targets(exclude_ids):
            gap = abs(target - seconds)
            if gap < best_gap:
                best_gap = gap
                best = target
        if best != seconds:
            self._snap_line = best
        return best

    def _snap_move(self, new_start: float, duration: float, exclude_ids: List[str]) -> float:
        """移动时首尾都参与吸附，取更近的一边。"""
        if not self._snap_enabled:
            return new_start
        snapped_start = self._snap_time(new_start, exclude_ids)
        line_for_start = self._snap_line
        snapped_end = self._snap_time(new_start + duration, exclude_ids)
        line_for_end = self._snap_line
        gap_start = abs(snapped_start - new_start)
        gap_end = abs(snapped_end - (new_start + duration))
        if line_for_start is not None and (line_for_end is None or gap_start <= gap_end):
            self._snap_line = line_for_start
            return snapped_start
        if line_for_end is not None:
            self._snap_line = line_for_end
            return max(0.0, snapped_end - duration)
        self._snap_line = None
        return new_start


    # ------------------------------------------------------------ 布局计算

    def set_issues(self, issues: Dict[str, str]) -> None:
        self._issues = issues
        self.update()

    def display_tracks(self) -> List[Dict[str, Any]]:
        return list(reversed(self._model.tracks()))

    def content_height(self) -> int:
        return len(self._model.tracks()) * (ROW_HEIGHT + ROW_GAP)

    def content_width(self) -> float:
        duration = max(self._model.duration, 10.0)
        return (duration + 4.0) * self._view.pixels_per_second

    def _row_top(self, track_id: str) -> Optional[int]:
        for index, track in enumerate(self.display_tracks()):
            if track.get("id") == track_id:
                return index * (ROW_HEIGHT + ROW_GAP) - int(self._view.scroll_y)
        return None

    def _track_at_y(self, y: int) -> str:
        index = int((y + self._view.scroll_y) // (ROW_HEIGHT + ROW_GAP))
        tracks = self.display_tracks()
        if 0 <= index < len(tracks):
            return tracks[index].get("id", "")
        return ""

    def _element_rect(self, element: Dict[str, Any]) -> Optional[QRectF]:
        top = self._row_top(element.get("track", ""))
        if top is None:
            return None
        x = self._view.x_for_time(float(element.get("start", 0.0)))
        width = self._view.width_for_duration(float(element.get("duration", 0.0)))
        return QRectF(x, top + 2, width, ROW_HEIGHT - 4)

    def _element_at(self, pos: QPoint) -> Optional[Dict[str, Any]]:
        """从上层往下找，保证重叠时选到视觉上在前面的那个。"""
        track_id = self._track_at_y(pos.y())
        if not track_id:
            return None
        candidates = [e for e in self._model.elements() if e.get("track") == track_id]
        for element in reversed(candidates):
            rect = self._element_rect(element)
            if rect and rect.contains(pos.x(), pos.y()):
                return element
        return None

    # ------------------------------------------------------------ 绘制

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0f131a"))

        self._paint_rows(painter)
        self._paint_grid(painter)
        self._paint_elements(painter)
        self._paint_playhead(painter)
        self._paint_snap_line(painter)
        self._paint_rubber(painter)
        painter.end()

    def _paint_snap_line(self, painter: QPainter) -> None:
        """吸附提示线：让用户知道刚才是「吸上去了」而不是自己拖准了。"""
        if self._snap_line is None:
            return
        x = int(self._view.x_for_time(self._snap_line))
        painter.setPen(QPen(QColor("#ffe347"), 1, Qt.DashLine))
        painter.drawLine(x, 0, x, self.height())

    def _paint_rubber(self, painter: QPainter) -> None:
        if self._rubber.isNull() or self._drag_mode != "rubber":
            return
        painter.setPen(QPen(QColor("#7fb2ff"), 1, Qt.DashLine))
        painter.setBrush(QBrush(QColor(127, 178, 255, 40)))
        painter.drawRect(self._rubber)


    def _paint_rows(self, painter: QPainter) -> None:
        for index, track in enumerate(self.display_tracks()):
            top = index * (ROW_HEIGHT + ROW_GAP) - int(self._view.scroll_y)
            if top + ROW_HEIGHT < 0 or top > self.height():
                continue
            color = QColor(TRACK_KIND_COLORS.get(track.get("kind"), "#232a36"))
            color.setAlpha(90 if not track.get("hidden") else 40)
            painter.fillRect(QRect(0, top, self.width(), ROW_HEIGHT), color)
            if track.get("locked"):
                painter.setPen(QPen(QColor("#3a4454"), 1, Qt.DotLine))
                painter.drawRect(QRect(0, top, self.width() - 1, ROW_HEIGHT))

    def _paint_grid(self, painter: QPainter) -> None:
        pps = self._view.pixels_per_second
        for step in (0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0):
            if step * pps >= 62:
                break
        start_time = self._view.time_for_x(0)
        end_time = self._view.time_for_x(self.width())
        painter.setPen(QPen(QColor("#1c222c")))
        index = int(start_time / step)
        while index * step <= end_time + step:
            x = int(self._view.x_for_time(index * step))
            painter.drawLine(x, 0, x, self.height())
            index += 1

    def _paint_elements(self, painter: QPainter) -> None:
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        selected = set(self._model.selection())
        primary = self._model.selected_id

        for element in self._model.elements():
            rect = self._element_rect(element)
            if rect is None or rect.right() < 0 or rect.left() > self.width():
                continue
            etype = element.get("type", "")
            fill_hex, edge_hex = TYPE_COLORS.get(etype, ("#3f4a5a", "#8f9aab"))

            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            base = QColor(fill_hex)
            gradient.setColorAt(0.0, base.lighter(118))
            gradient.setColorAt(1.0, base.darker(112))
            painter.setBrush(QBrush(gradient))

            issue = self._issues.get(element.get("id", ""))
            if issue == "error":
                painter.setPen(QPen(QColor("#ff5f56"), 2))
            elif issue == "warning":
                painter.setPen(QPen(QColor("#ffbd2e"), 2))
            elif element.get("id") == primary:
                painter.setPen(QPen(QColor("#ffffff"), 2))
            elif element.get("id") in selected:
                # 多选里的非主选中，用偏蓝的粗边区分
                painter.setPen(QPen(QColor("#7fb2ff"), 2))
            else:
                painter.setPen(QPen(QColor(edge_hex), 1))
            painter.drawRoundedRect(rect, 4, 4)

            # 转场块画成对角条纹，和普通片段区分开
            if etype == "transition":
                painter.save()
                painter.setClipRect(rect)
                painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
                stripe = int(rect.left()) - ROW_HEIGHT
                while stripe < rect.right():
                    painter.drawLine(stripe, int(rect.bottom()), stripe + ROW_HEIGHT, int(rect.top()))
                    stripe += 7
                painter.restore()

            # 有关键帧的元素在底部画标记点
            keyframes = element.get("keyframes") or {}
            if keyframes:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor("#ffe347")))
                duration = max(1e-6, float(element.get("duration", 0.0)))
                for points in keyframes.values():
                    for point in points:
                        ratio = min(1.0, max(0.0, float(point.get("time", 0.0)) / duration))
                        kx = rect.left() + rect.width() * ratio
                        painter.drawEllipse(QRectF(kx - 2, rect.bottom() - 5, 4, 4))

            if rect.width() > 26:
                painter.setPen(QPen(QColor("#f2f6fb")))
                label = self._element_label(element)
                painter.drawText(
                    QRectF(rect.left() + 6, rect.top(), rect.width() - 12, rect.height()),
                    Qt.AlignVCenter | Qt.AlignLeft,
                    metrics.elidedText(label, Qt.ElideRight, int(rect.width()) - 12),
                )

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

    def _paint_playhead(self, painter: QPainter) -> None:
        x = int(self._view.x_for_time(self._model.playhead))
        painter.setPen(QPen(QColor("#ff5f56"), 1))
        painter.drawLine(x, 0, x, self.height())

    # ------------------------------------------------------------ 鼠标

    def mousePressEvent(self, event) -> None:  # noqa: N802
        element = self._element_at(event.pos())
        if event.button() == Qt.RightButton:
            if element:
                # 右键点在已选中的多个元素之一上时，保持多选，方便批量操作
                if element["id"] not in self._model.selection():
                    self._model.select(element["id"])
                self.elementContextRequested.emit(element["id"], event.globalPos())
            else:
                track_id = self._track_at_y(event.pos().y())
                self.emptyContextRequested.emit(
                    track_id, self._view.time_for_x(event.pos().x()), event.globalPos()
                )
            return

        if event.button() != Qt.LeftButton:
            return

        if element is None:
            # 空白处按下：先记下起点，移动了就是框选，没移动就是挪播放头
            self._drag_mode = "rubber"
            self._drag_origin = event.pos()
            self._rubber = QRect(event.pos(), event.pos())
            return

        if event.modifiers() & Qt.ControlModifier:
            # Ctrl + 点击：加选 / 取消选中，不进入拖动
            self._model.toggle_select(element["id"])
            return

        if element["id"] in self._model.selection() and len(self._model.selection()) > 1:
            # 多选状态下点其中一个：保持多选，整组一起拖
            self.elementClicked.emit(element["id"])
        else:
            self.elementClicked.emit(element["id"])
            self._model.select(element["id"])

        if self._model.is_track_locked(element.get("track", "")):
            return

        rect = self._element_rect(element)
        if rect is None:
            return
        self._drag_id = element["id"]
        self._drag_origin = event.pos()
        self._drag_start_time = float(element.get("start", 0.0))
        self._drag_start_duration = float(element.get("duration", 0.0))
        self._drag_track = element.get("track", "")
        self._drag_copy_done = not bool(event.modifiers() & Qt.AltModifier)

        if abs(event.pos().x() - rect.left()) <= EDGE_GRAB:
            self._drag_mode = "trim_left"
        elif abs(event.pos().x() - rect.right()) <= EDGE_GRAB:
            self._drag_mode = "trim_right"
        else:
            self._drag_mode = "move"

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._drag_mode:
            self._update_cursor(event.pos())
            return

        if self._drag_mode == "rubber":
            self._rubber = QRect(self._drag_origin, event.pos()).normalized()
            self.update()
            return

        delta_seconds = (event.pos().x() - self._drag_origin.x()) / self._view.pixels_per_second

        if self._drag_mode == "move":
            self._handle_move_drag(event, delta_seconds)
        elif self._drag_mode == "trim_left":
            new_start = max(0.0, self._drag_start_time + delta_seconds)
            new_start = self._snap_time(new_start, [self._drag_id])
            new_duration = self._drag_start_duration - (new_start - self._drag_start_time)
            if new_duration > 0.02:
                self._model.resize_element(self._drag_id, new_start, new_duration)
        else:
            new_end = self._snap_time(
                self._drag_start_time + self._drag_start_duration + delta_seconds, [self._drag_id]
            )
            new_duration = new_end - self._drag_start_time
            if new_duration > 0.02:
                self._model.resize_element(self._drag_id, self._drag_start_time, new_duration)
        self.update()

    def _handle_move_drag(self, event, delta_seconds: float) -> None:
        """拖动移动。Alt 按住时先复制一份再拖，多选时整组一起动。"""
        if not self._drag_copy_done:
            clone_id = self._model.duplicate_in_place(self._drag_id)
            self._drag_copy_done = True
            if clone_id:
                self._drag_id = clone_id
                self._model.select(clone_id)

        group = [eid for eid in self._model.selection() if eid != self._drag_id]
        new_start = max(0.0, self._drag_start_time + delta_seconds)
        new_start = self._snap_move(new_start, self._drag_start_duration, self._model.selection())

        target_track = self._track_at_y(event.pos().y()) or self._drag_track
        element = self._model.element(self._drag_id)
        if element is not None:
            # 只允许放到 kind 匹配的轨道，避免把音频丢到视频轨
            expected = tl.TYPE_TRACK_KIND.get(element.get("type", ""))
            track = self._model.track(target_track)
            if expected and track and track.get("kind") != expected:
                target_track = self._drag_track
            if self._model.is_track_locked(target_track):
                target_track = self._drag_track

        if group:
            # 多选拖动：只沿时间轴整体平移，不跨轨道，避免轨道错位
            offset = new_start - float(
                (self._model.element(self._drag_id) or {}).get("start", new_start)
            )
            self._model.move_element(self._drag_id, new_start, None)
            for other_id in group:
                other = self._model.element(other_id)
                if other is None or self._model.is_track_locked(other.get("track", "")):
                    continue
                self._model.move_element(
                    other_id, max(0.0, float(other.get("start", 0.0)) + offset), None
                )
            return
        self._model.move_element(self._drag_id, new_start, target_track)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_mode == "rubber":
            moved = self._rubber.width() > 3 or self._rubber.height() > 3
            if moved:
                self._select_in_rect(self._rubber)
            else:
                self.playheadRequested.emit(self._view.time_for_x(event.pos().x()))
                self._model.select("")
            self._rubber = QRect()
        self._drag_mode = ""
        self._drag_id = ""
        self._snap_line = None
        self.update()

    def _select_in_rect(self, rect: QRect) -> None:
        """框选：和矩形有交集的元素全部选中。"""
        hits: List[str] = []
        for element in self._model.elements():
            element_rect = self._element_rect(element)
            if element_rect is None:
                continue
            if rect.intersects(element_rect.toRect()):
                hits.append(element.get("id", ""))
        self._model.select_many(hits)


    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        element = self._element_at(event.pos())
        if element:
            self.elementDoubleClicked.emit(element["id"])

    def _update_cursor(self, pos: QPoint) -> None:
        element = self._element_at(pos)
        if element is None:
            self.setCursor(Qt.ArrowCursor)
            return
        rect = self._element_rect(element)
        if rect is None:
            return
        if abs(pos.x() - rect.left()) <= EDGE_GRAB or abs(pos.x() - rect.right()) <= EDGE_GRAB:
            self.setCursor(Qt.SizeHorCursor)
        else:
            self.setCursor(Qt.OpenHandCursor)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.ControlModifier:
            # 以鼠标位置为锚点缩放，手感和专业剪辑软件一致
            anchor_time = self._view.time_for_x(event.pos().x())
            factor = 1.25 if event.angleDelta().y() > 0 else 0.8
            self._view.pixels_per_second = max(
                MIN_PPS, min(MAX_PPS, self._view.pixels_per_second * factor)
            )
            self._view.scroll_x = max(
                0.0, anchor_time * self._view.pixels_per_second - event.pos().x()
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

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if read_drag_payload(event.mimeData()) is not None or self._local_files(event.mimeData()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if read_drag_payload(event.mimeData()) is not None or self._local_files(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        track_id = self._track_at_y(event.pos().y())
        drop_time = self._view.time_for_x(event.pos().x())

        files = self._local_files(event.mimeData())
        if files:
            self.filesDropped.emit(files, track_id, drop_time)
            event.acceptProposedAction()
            return

        payload = read_drag_payload(event.mimeData())
        if payload is None:
            return
        self.itemDropped.emit(payload, track_id, drop_time)
        event.acceptProposedAction()



class TimelineWidget(QAbstractScrollArea):
    """把三块画布 + 底部工具条拼起来，并负责滚动条与刷新。"""

    elementDoubleClicked = pyqtSignal(str)
    elementContextRequested = pyqtSignal(str, QPoint)
    emptyContextRequested = pyqtSignal(str, float, QPoint)
    trackContextRequested = pyqtSignal(str, QPoint)
    itemDropped = pyqtSignal(dict, str, float)
    filesDropped = pyqtSignal(list, str, float)
    # 工具条按钮：由主窗口接到具体动作上，和快捷键走同一套实现
    splitRequested = pyqtSignal()
    deleteRequested = pyqtSignal()
    freezeRequested = pyqtSignal()
    duplicateRequested = pyqtSignal()


    def __init__(self, model, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._view = ViewState()

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
            f"拖动时吸附到播放头和相邻片段边缘（{shortcuts.primary('toggle_snap')}）"
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
        add_button("－", f"缩小（{shortcuts.primary('zoom_out')}）", lambda: self.zoom(0.8))
        self._zoom_slider = QSlider(Qt.Horizontal)
        self._zoom_slider.setFixedWidth(120)
        self._zoom_slider.setRange(0, 100)
        self._zoom_slider.setValue(self._zoom_to_slider(self._view.pixels_per_second))
        self._zoom_slider.setFocusPolicy(Qt.NoFocus)
        self._zoom_slider.setToolTip("时间线缩放")
        self._zoom_slider.valueChanged.connect(self._on_zoom_slider)
        row.addWidget(self._zoom_slider)
        add_button("＋", f"放大（{shortcuts.primary('zoom_in')}）", lambda: self.zoom(1.25))
        add_button("⤢ 适配", f"缩放到整条时间线（{shortcuts.primary('zoom_fit')}）", self.zoom_to_fit)
        return bar

    @staticmethod
    def _zoom_to_slider(pps: float) -> int:
        """像素/秒 映射到滑块位置，用对数刻度，手感更均匀。"""
        ratio = (math.log(max(MIN_PPS, pps)) - math.log(MIN_PPS)) / (
            math.log(MAX_PPS) - math.log(MIN_PPS)
        )
        return int(max(0.0, min(1.0, ratio)) * 100)

    @staticmethod
    def _slider_to_zoom(value: int) -> float:
        ratio = max(0, min(100, value)) / 100.0
        return math.exp(math.log(MIN_PPS) + ratio * (math.log(MAX_PPS) - math.log(MIN_PPS)))

    def _on_zoom_slider(self, value: int) -> None:
        self._view.pixels_per_second = self._slider_to_zoom(value)
        self._sync_scrollbars()
        self._repaint_all()

    def _on_zoom_changed(self) -> None:
        """Ctrl+滚轮缩放后，把滑块同步过来。"""
        self._sync_zoom_slider()
        self._sync_scrollbars()

    def toggle_snap(self) -> None:
        self._snap_button.setChecked(not self._snap_button.isChecked())

    def snap_enabled(self) -> bool:
        return self._snap_button.isChecked()

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
        width = max(1, self.canvas.width())
        x = self._view.x_for_time(seconds)
        left_margin = width * 0.1
        right_margin = width * 0.85
        if left_margin <= x <= right_margin:
            return
        target = max(0.0, seconds * self._view.pixels_per_second - left_margin)
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
        self._repaint_all()

    def set_issues(self, issues: Dict[str, str]) -> None:
        self.canvas.set_issues(issues)

    def zoom(self, factor: float) -> None:
        self._view.pixels_per_second = max(
            MIN_PPS, min(MAX_PPS, self._view.pixels_per_second * factor)
        )
        self._sync_zoom_slider()
        self.refresh()

    def zoom_to_fit(self) -> None:
        duration = max(self._model.duration, 1.0)
        available = max(120, self.canvas.width() - 20)
        self._view.pixels_per_second = max(MIN_PPS, min(MAX_PPS, available / duration))
        self._view.scroll_x = 0.0
        self._sync_zoom_slider()
        self.refresh()

    def _sync_zoom_slider(self) -> None:
        self._zoom_slider.blockSignals(True)
        self._zoom_slider.setValue(self._zoom_to_slider(self._view.pixels_per_second))
        self._zoom_slider.blockSignals(False)

    def scroll_to_time(self, seconds: float) -> None:
        """把某个时间点滚到可见区域中间，JSON 面板反选元素时用。"""
        target = max(0.0, seconds * self._view.pixels_per_second - self.canvas.width() / 2)
        self.horizontalScrollBar().setValue(int(target))

    def _repaint_all(self) -> None:
        self.ruler.update()
        self.header.update()
        self.canvas.update()

    def _sync_scrollbars(self) -> None:
        h_bar = self.horizontalScrollBar()
        page = max(1, self.canvas.width())
        h_bar.setPageStep(page)
        h_bar.setSingleStep(40)
        h_bar.setRange(0, max(0, int(self.canvas.content_width() - page)))

        v_bar = self.verticalScrollBar()
        v_page = max(1, self.canvas.height())
        v_bar.setPageStep(v_page)
        v_bar.setSingleStep(ROW_HEIGHT)
        v_bar.setRange(0, max(0, self.canvas.content_height() - v_page))

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
