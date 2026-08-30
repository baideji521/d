"""Timeline 磁吸（Snap）。

阶段 7 之前的磁吸写在 `TrackCanvas` 里，只认三种目标（0 / 播放头 / 其它片段首尾），
容差固定 `8px / pps`，并且**拖放（drop）路径完全不经过它**。
本模块把磁吸拆成独立、无 Qt 依赖的引擎，负责三件事：

1. 收集吸附目标（第八条要求的全部类型）；
2. 在容差内选最近的目标；
3. 输出足够画 Snap Guide 的信息（时间、标签、来源）——第九条。

容差是"像素 + 时间上限"双闸：纯像素容差在极小缩放（10px/s）下等于 0.8s，
片段会被吸得乱跑；纯时间容差在极大缩放（800px/s）下等于 0px，又吸不上。
所以取 `min(pixels / pps, MAX_SNAP_SECONDS)`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: 默认磁吸容差（像素）。剪映的手感大约就是 8~10px。
SNAP_PIXELS = 10.0

#: 磁吸容差的时间上限（秒）。第二十四条的例子用 0.1s 阈值，这里取同一量级。
MAX_SNAP_SECONDS = 0.12

#: 目标类型的展示名，Snap Guide 上要写清"为什么吸到这里"。
KIND_LABELS = {
    "zero": "起点 0",
    "playhead": "播放头",
    "ruler": "刻度",
    "clip_start": "片段起点",
    "clip_end": "片段末尾",
    "clip_center": "片段中心",
    "marker": "标记",
    "transition_start": "转场起点",
    "transition_end": "转场终点",
}

#: 刻度吸附用的候选间隔（秒），第八条列的 0 / 0.5 / 1 / 2 / 5 / 10。
RULER_STEPS: Tuple[float, ...] = (0.5, 1.0, 2.0, 5.0, 10.0)


@dataclass(frozen=True)
class SnapTarget:
    time: float
    kind: str
    element_id: str = ""

    @property
    def label(self) -> str:
        name = KIND_LABELS.get(self.kind, self.kind)
        if self.element_id:
            return f"{name}（{self.element_id}）"
        return name


@dataclass(frozen=True)
class SnapResult:
    """磁吸结果。`snapped=False` 时 time 就是原值，guide 为 None。"""

    time: float
    snapped: bool = False
    target: Optional[SnapTarget] = None
    #: 被吸附的是片段的哪一边：start / end。移动时两边都参与竞争。
    edge: str = "start"

    @property
    def guide_time(self) -> Optional[float]:
        return self.target.time if self.target is not None else None

    @property
    def guide_label(self) -> str:
        return self.target.label if self.target is not None else ""


class SnapEngine:
    """磁吸引擎。

    用法：每次手势开始时用当前时间线数据 `collect()` 一次目标表，
    手势期间只做查找——避免每个 mouseMove 都遍历一遍元素列表。
    """

    def __init__(self, enabled: bool = True, pixels: float = SNAP_PIXELS) -> None:
        self.enabled = bool(enabled)
        self.pixels = float(pixels)
        self._targets: Tuple[SnapTarget, ...] = ()

    # ------------------------------------------------------------ 目标收集

    def collect(
        self,
        elements: Iterable[Dict[str, Any]],
        playhead: float = 0.0,
        exclude_ids: Sequence[str] = (),
        markers: Iterable[float] = (),
    ) -> Tuple[SnapTarget, ...]:
        excluded = set(exclude_ids or ())
        targets: List[SnapTarget] = [
            SnapTarget(0.0, "zero"),
            SnapTarget(round(float(playhead), 6), "playhead"),
        ]
        for element in elements:
            element_id = str(element.get("id", ""))
            if element_id in excluded:
                continue
            start = _number(element.get("start"))
            duration = _number(element.get("duration"))
            end = round(start + duration, 6)
            is_transition = element.get("type") == "transition"
            targets.append(
                SnapTarget(round(start, 6), "transition_start" if is_transition else "clip_start", element_id)
            )
            targets.append(
                SnapTarget(end, "transition_end" if is_transition else "clip_end", element_id)
            )
            if duration > 0:
                targets.append(SnapTarget(round(start + duration / 2.0, 6), "clip_center", element_id))
        for marker in markers or ():
            targets.append(SnapTarget(round(float(marker), 6), "marker"))
        self._targets = tuple(targets)
        return self._targets

    def targets(self) -> Tuple[SnapTarget, ...]:
        return self._targets

    # ------------------------------------------------------------ 查找

    def tolerance(self, pixels_per_second: float) -> float:
        return min(self.pixels / max(1e-6, float(pixels_per_second)), MAX_SNAP_SECONDS)

    def _ruler_candidate(self, seconds: float, tolerance: float) -> Optional[SnapTarget]:
        """刻度吸附：只吸"整齐"的间隔，且只在容差内。"""
        best: Optional[SnapTarget] = None
        best_gap = tolerance
        for step in RULER_STEPS:
            tick = round(round(seconds / step) * step, 6)
            gap = abs(tick - seconds)
            if gap < best_gap:
                best_gap = gap
                best = SnapTarget(tick, "ruler")
        return best

    def snap(self, seconds: float, pixels_per_second: float, use_ruler: bool = True) -> SnapResult:
        """把单个时间点吸到最近目标。"""
        seconds = float(seconds)
        if not self.enabled:
            return SnapResult(seconds)
        tolerance = self.tolerance(pixels_per_second)
        best: Optional[SnapTarget] = None
        best_gap = tolerance
        for target in self._targets:
            gap = abs(target.time - seconds)
            if gap < best_gap:
                best_gap = gap
                best = target
        if use_ruler:
            ruler = self._ruler_candidate(seconds, best_gap)
            if ruler is not None:
                best = ruler
        if best is None:
            return SnapResult(seconds)
        return SnapResult(best.time, True, best)

    def snap_span(
        self, start: float, duration: float, pixels_per_second: float, use_ruler: bool = True
    ) -> SnapResult:
        """移动片段：首尾都参与竞争，谁更近就用谁，返回的 time 始终是 **start**。"""
        start = float(start)
        duration = max(0.0, float(duration))
        if not self.enabled:
            return SnapResult(start)
        head = self.snap(start, pixels_per_second, use_ruler)
        tail = self.snap(start + duration, pixels_per_second, use_ruler)
        head_gap = abs(head.time - start) if head.snapped else float("inf")
        tail_gap = abs(tail.time - (start + duration)) if tail.snapped else float("inf")
        if head_gap == float("inf") and tail_gap == float("inf"):
            return SnapResult(start)
        if head_gap <= tail_gap:
            return SnapResult(head.time, True, head.target, "start")
        return SnapResult(max(0.0, tail.time - duration), True, tail.target, "end")


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback
