"""Timeline 的唯一坐标真相源。

阶段 7 之前，时间↔像素的换算写在 `gui/timeline_widget.py` 的 `ViewState` 里，
并且 `seconds * pixels_per_second` 这一形式在缩放锚点、播放头跟随、滚动定位、
内容宽度四处被手写复制（见 docs/GUI_TIMELINE_INTERACTION_AUDIT.md 第 13 问）。
本模块把这些换算收成一个**不可变值对象**，规则很硬：

    GUI 里任何地方都不许再出现 `seconds * pps` 或 `x / pps`，
    一律走 TimelineCoordinate。

不可变的理由：拖动手势必须在**同一个坐标快照**下完成。阶段 7 之前的真因之一，
就是按下瞬间 `selectionChanged → scroll_to_time` 把 `scroll_x` 改了，
而 `_drag_origin` 还是旧坐标下的值，于是"点中间"被算成"点边缘"。
值对象让手势可以捏着一份 `TimelineCoordinate` 走完全程，视图后来怎么滚都不影响它。

本模块**不 import PyQt5**：坐标是纯数学，可以脱离 GUI 单测（tests/test_timeline_coordinate.py）。
矩形用本模块的 `Rect`，由控件层再转成 QRectF。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from core.time_utils import DEFAULT_FPS, snap_to_frame

#: 轨道行高与行距。行高从阶段 6 的 38 提到 44：38px 行高里再扣掉 4px 内缩，
#: 片段实际只有 34px 高，在 125% 缩放的 Windows 上点起来偏细。
ROW_HEIGHT = 44.0
ROW_GAP = 2.0

#: 片段左右边缘的 Resize 命中宽度（像素）。
EDGE_ZONE = 8.0

#: 片段的最小命中宽度（像素）。视觉宽度可以只有 1px（0.03s 的片段），
#: 但命中区不能跟着缩到点不中——这里只放大 hit rect，绝不改时间。
MIN_HIT_WIDTH = 16.0

#: 缩放档位（百分比）。100% 定义为 PPS_AT_100 像素/秒。
#: 8 档从极缩小到极放大，和 GUI 下拉 / 快捷键一一对应。
PERCENT_STEPS: Tuple[float, ...] = (25.0, 50.0, 75.0, 100.0, 150.0, 200.0, 400.0, 800.0)

#: 100% 对应多少像素/秒。80px/s 时 0.1s 有 8 像素，肉眼能分辨，
#: 也是阶段 1~7 一直在用的默认视图，保持不变。
PPS_AT_100 = 80.0

#: 档位换算成像素/秒：(20, 40, 60, 80, 120, 160, 320, 640)
ZOOM_STEPS: Tuple[float, ...] = tuple(PPS_AT_100 * p / 100.0 for p in PERCENT_STEPS)

#: 允许的缩放上下限。**比档位更宽**：
#: 「整条时间线塞进视口」在 95 秒的素材上会落到 25% 以下，
#: 那不是档位，是自由缩放，不该被档位卡住。
MIN_PPS = 2.0
MAX_PPS = 1200.0

#: 默认缩放 = 100%
DEFAULT_PPS = PPS_AT_100



@dataclass(frozen=True)
class Rect:
    """轻量矩形。用浮点存，避免早取整带来的 1px 漂移。"""

    x: float
    y: float
    width: float
    height: float

    @property
    def left(self) -> float:
        return self.x

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def top(self) -> float:
        return self.y

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def contains(self, px: float, py: float) -> bool:
        return self.left <= px <= self.right and self.top <= py <= self.bottom

    def intersects(self, other: "Rect") -> bool:
        return not (
            other.left > self.right
            or other.right < self.left
            or other.top > self.bottom
            or other.bottom < self.top
        )

    def inflated(self, dx: float, dy: float) -> "Rect":
        return Rect(self.x - dx, self.y - dy, self.width + 2 * dx, self.height + 2 * dy)

    def as_tuple(self) -> Tuple[float, float, float, float]:
        return (self.x, self.y, self.width, self.height)


class TimelineZoom:
    """缩放档位管理。把"当前多少像素每秒"这件事从各个控件里收回来。

    档位是**建议值**而不是限制：滚轮缩放、fit 都可能落在两档之间，
    `zoom_in()` / `zoom_out()` 会跳到下一个/上一个档位，所以手动缩放过的视图
    也能靠按钮回到整齐的档位上。
    """

    def __init__(self, pixels_per_second: float = DEFAULT_PPS) -> None:
        self._pps = self._clamp(pixels_per_second)

    @staticmethod
    def _clamp(pps: float) -> float:
        return max(MIN_PPS, min(MAX_PPS, float(pps)))

    @property
    def pixels_per_second(self) -> float:
        return self._pps

    def set_zoom(self, pixels_per_second: float) -> float:
        self._pps = self._clamp(pixels_per_second)
        return self._pps

    def zoom_in(self) -> float:
        for step in ZOOM_STEPS:
            if step > self._pps * 1.001:
                return self.set_zoom(step)
        return self.set_zoom(MAX_PPS)

    def zoom_out(self) -> float:
        for step in reversed(ZOOM_STEPS):
            if step < self._pps * 0.999:
                return self.set_zoom(step)
        return self.set_zoom(MIN_PPS)

    def step_index(self) -> int:
        """当前 pps 最接近第几档，给滑块 / 状态显示用。"""
        best = 0
        best_gap = float("inf")
        for index, step in enumerate(ZOOM_STEPS):
            gap = abs(math.log(step) - math.log(max(1e-6, self._pps)))
            if gap < best_gap:
                best_gap = gap
                best = index
        return best

    # ------------------------------------------------------------ 百分比档位

    def percent(self) -> float:
        """当前缩放的百分比。100% = PPS_AT_100 像素/秒。"""
        return round(self._pps / PPS_AT_100 * 100.0, 2)

    def set_percent(self, percent: float) -> float:
        """按百分比设缩放。GUI 下拉 / 菜单只认百分比，不认像素每秒。"""
        return self.set_zoom(PPS_AT_100 * max(1e-6, float(percent)) / 100.0)

    def nearest_percent(self) -> float:
        """当前缩放最接近哪个档位（用于下拉框回显）。"""
        return PERCENT_STEPS[self.step_index()]

    @staticmethod
    def percent_label(percent: float) -> str:
        text = f"{float(percent):g}"
        return f"{text}%"


    def fit_project(self, duration_seconds: float, viewport_width: float) -> float:
        """整条时间线塞进视口。"""
        duration = max(1e-6, float(duration_seconds))
        width = max(1.0, float(viewport_width))
        return self.set_zoom(width / duration)

    def fit_selection(self, start: float, end: float, viewport_width: float) -> float:
        """选中区间塞进视口。区间退化成一个点时按 1 秒算，避免除零后顶到最大档。"""
        span = max(1e-6, float(end) - float(start))
        if span < 1e-3:
            span = 1.0
        return self.set_zoom(max(1.0, float(viewport_width)) / span)

    def slider_ratio(self) -> float:
        """对数刻度下的滑块比例 0..1。"""
        lo, hi = math.log(MIN_PPS), math.log(MAX_PPS)
        return max(0.0, min(1.0, (math.log(self._pps) - lo) / (hi - lo)))

    @staticmethod
    def ratio_to_zoom(ratio: float) -> float:
        lo, hi = math.log(MIN_PPS), math.log(MAX_PPS)
        return math.exp(lo + max(0.0, min(1.0, float(ratio))) * (hi - lo))


@dataclass(frozen=True)
class TimelineCoordinate:
    """一次绘制 / 一次手势期间的坐标快照。

    参数含义：
    - pixels_per_second：缩放。
    - timeline_origin_x：时间 0 在画布里的 x（当前恒为 0；留给以后左侧留白，
      这样"左边缘在哪里"是一个显式参数而不是散落的 +offset）。
    - scroll_x / scroll_y：横向 / 纵向滚动量（像素）。
    - fps：帧率，`snap_time` 用它对齐帧网格。
    - track_order：**自上而下**的轨道 id。模型里 tracks 越靠后越上层，
      所以控件层传进来的是 reversed(model.tracks())，反转只做这一次。
    """

    pixels_per_second: float = DEFAULT_PPS
    timeline_origin_x: float = 0.0
    scroll_x: float = 0.0
    fps: float = DEFAULT_FPS
    scroll_y: float = 0.0
    row_height: float = ROW_HEIGHT
    row_gap: float = ROW_GAP
    track_order: Tuple[str, ...] = ()

    # ------------------------------------------------------------ 派生

    @property
    def row_pitch(self) -> float:
        return self.row_height + self.row_gap

    def with_zoom(self, pixels_per_second: float) -> "TimelineCoordinate":
        return replace(self, pixels_per_second=max(1e-6, float(pixels_per_second)))

    def with_scroll(self, scroll_x: Optional[float] = None, scroll_y: Optional[float] = None) -> "TimelineCoordinate":
        return replace(
            self,
            scroll_x=self.scroll_x if scroll_x is None else float(scroll_x),
            scroll_y=self.scroll_y if scroll_y is None else float(scroll_y),
        )

    def with_tracks(self, track_ids: Iterable[str]) -> "TimelineCoordinate":
        return replace(self, track_order=tuple(str(t) for t in track_ids))

    def with_fps(self, fps: float) -> "TimelineCoordinate":
        return replace(self, fps=float(fps) or DEFAULT_FPS)

    # ------------------------------------------------------------ 时间 ↔ 像素

    def time_to_x(self, seconds: float) -> float:
        return self.timeline_origin_x + float(seconds) * self.pixels_per_second - self.scroll_x

    def x_to_time(self, x: float) -> float:
        """像素 → 秒。**不钳到 0**，否则 x_to_time(time_to_x(t)) 在负半轴不可逆，
        property 往返测试就没法写了。需要非负时由调用方显式 clamp_time()。"""
        return (float(x) - self.timeline_origin_x + self.scroll_x) / self.pixels_per_second

    def duration_to_width(self, seconds: float) -> float:
        return float(seconds) * self.pixels_per_second

    def width_to_duration(self, width: float) -> float:
        return float(width) / self.pixels_per_second

    @staticmethod
    def clamp_time(seconds: float) -> float:
        return max(0.0, float(seconds))

    def scroll_for_anchor(self, seconds: float, x: float) -> float:
        """要让时间 seconds 出现在像素 x 上，scroll_x 该是多少。

        缩放锚定、滚动定位都用它，避免在控件里手写 `seconds * pps - x`
        （审计第 13 问里那四处复制粘贴就是这么来的）。
        """
        return max(0.0, float(seconds) * self.pixels_per_second + self.timeline_origin_x - float(x))

    # ------------------------------------------------------------ 帧对齐

    def snap_time(self, seconds: float) -> float:
        """吸附到帧网格。直接复用 core.time_utils.snap_to_frame，
        不在 GUI 里另写一套取整规则（模型落库时用的就是它）。"""
        return snap_to_frame(float(seconds), self.fps)

    def snap_x(self, x: float) -> float:
        return self.time_to_x(self.snap_time(self.x_to_time(x)))

    def frame_duration(self) -> float:
        return 1.0 / float(self.fps or DEFAULT_FPS)

    # ------------------------------------------------------------ 轨道 ↔ Y

    def track_index_at(self, y: float) -> int:
        """返回行号（可能越界，负数表示在内容上方）。"""
        return int(math.floor((float(y) + self.scroll_y) / self.row_pitch))

    def y_to_track(self, y: float) -> Optional[str]:
        index = self.track_index_at(y)
        if 0 <= index < len(self.track_order):
            return self.track_order[index]
        return None

    def track_to_y(self, track_id: str) -> Optional[float]:
        """轨道行的顶部 y（视口坐标）。轨道不在显示序列里时返回 None。"""
        for index, tid in enumerate(self.track_order):
            if tid == track_id:
                return index * self.row_pitch - self.scroll_y
        return None

    def row_rect(self, track_id: str, viewport_width: float) -> Optional[Rect]:
        top = self.track_to_y(track_id)
        if top is None:
            return None
        return Rect(0.0, top, max(0.0, float(viewport_width)), self.row_height)

    def content_height(self) -> float:
        return len(self.track_order) * self.row_pitch

    # ------------------------------------------------------------ 元素 ↔ 矩形

    def element_to_rect(self, element: Dict[str, Any]) -> Optional[Rect]:
        """视觉矩形。宽度不设下限，真实时长有多短就画多窄（保真）。"""
        top = self.track_to_y(str(element.get("track", "")))
        if top is None:
            return None
        x = self.time_to_x(_number(element.get("start")))
        width = self.duration_to_width(_number(element.get("duration")))
        return Rect(x, top + 2.0, width, self.row_height - 4.0)

    def element_to_hit_rect(self, element: Dict[str, Any]) -> Optional[Rect]:
        """命中矩形：至少 MIN_HIT_WIDTH 宽，围绕视觉矩形中心扩展。
        只影响"点得到"，绝不回写时间——第十三条要求的 visual / hit 分离。"""
        rect = self.element_to_rect(element)
        if rect is None:
            return None
        if rect.width >= MIN_HIT_WIDTH:
            return rect
        pad = (MIN_HIT_WIDTH - rect.width) / 2.0
        return Rect(rect.x - pad, rect.y, MIN_HIT_WIDTH, rect.height)

    def rect_to_time(self, rect: Rect) -> Tuple[float, float]:
        """矩形 → (start, duration)。start 会被钳成非负，duration 至少一帧。"""
        start = self.clamp_time(self.x_to_time(rect.left))
        duration = max(self.frame_duration(), self.width_to_duration(rect.width))
        return (start, duration)

    def edge_zone(self, element: Dict[str, Any], x: float) -> str:
        """判断 x 落在片段的哪个区域：left / right / body / ""（没中）。

        窄片段（宽度 < 3*EDGE_ZONE）**整体判成 body**：否则左右各 8px 一夹，
        中间没有可移动区，用户想拖动却永远在 resize——这正是报障里
        "鼠标在元素中间，拖动却从左边缘算" 的一种表现。
        """
        rect = self.element_to_hit_rect(element)
        if rect is None or not rect.contains(x, rect.top + 1.0):
            return ""
        if rect.width < EDGE_ZONE * 3.0:
            return "body"
        if x - rect.left <= EDGE_ZONE:
            return "left"
        if rect.right - x <= EDGE_ZONE:
            return "right"
        return "body"

    # ------------------------------------------------------------ 刻度

    def tick_step(self, min_label_pixels: float = 62.0) -> float:
        """按缩放挑一个人能看懂的刻度间隔（秒）。刻度尺与网格线共用它，
        避免"片段变宽了、刻度没变"这类不同步。"""
        for step in (0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 300.0):
            if step * self.pixels_per_second >= min_label_pixels:
                return step
        return 300.0

    def visible_time_range(self, viewport_width: float) -> Tuple[float, float]:
        return (self.x_to_time(0.0), self.x_to_time(float(viewport_width)))

    def visible_ticks(self, viewport_width: float, min_label_pixels: float = 62.0) -> Sequence[float]:
        step = self.tick_step(min_label_pixels)
        start, end = self.visible_time_range(viewport_width)
        first = int(math.floor(max(0.0, start) / step))
        ticks = []
        index = first
        while index * step <= end + step:
            ticks.append(round(index * step, 6))
            index += 1
        return ticks

    def content_width(self, duration_seconds: float, tail_seconds: float = 4.0) -> float:
        """内容总宽度。tail_seconds 是尾部留白，显式命名而不是散落的 +4.0。"""
        duration = max(float(duration_seconds), 10.0)
        return (duration + float(tail_seconds)) * self.pixels_per_second


def _number(value: Any, fallback: float = 0.0) -> float:
    """脏值兜底：模型层已经净化过，这里只防 None / 字符串混进绘制路径。"""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return fallback
    if math.isnan(result) or math.isinf(result):
        return fallback
    return result
