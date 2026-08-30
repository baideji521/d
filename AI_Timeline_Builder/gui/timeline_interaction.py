"""Timeline 交互状态机（第三十一、三十二条）。

阶段 7 之前，press / move / release / drop 的状态散在 `TrackCanvas` 的
`_drag_mode` / `_drag_id` / `_drag_origin` / `_drag_start_time` / `_drag_copy_done` 里，
并且每一次 `mouseMoveEvent` 都直接调 `TimelineModel.move_element()` ——
一次拖动写几十次模型、压几十条撤销快照、触发几十次全量校验。

本模块把交互抽成**无 Qt 依赖的纯逻辑**：

    IDLE ─press→ HIT TEST ─┬─ body        → DRAG_ELEMENT
                           ├─ left/right  → RESIZE_LEFT / RESIZE_RIGHT
                           ├─ 空白         → RUBBER / PLAYHEAD
                           └─ 外部拖入     → DRAG_ASSET
      ─move→ 计算 preview（含 Snap）→ 控件只画 ghost，不写模型
      ─release→ commit() 返回一次「该怎么落库」的描述，由控件调既有 Model API

两条硬规则：
1. 手势期间捏着**按下那一刻的 TimelineCoordinate 快照**。视图之后被别的信号滚走
   也不影响 grab_offset —— 这是报障"鼠标在元素中间却按左边缘算"的直接修复。
2. 本模块**不碰 element 字典**，只输出 (element_id, start, duration, track)。
   写模型这件事永远由控件走 TimelineModel 的公开方法完成（第三十条）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core import timeline as tl
from gui import asset_placement as ap


from gui.timeline_coordinate import TimelineCoordinate
from gui.timeline_snap import SnapEngine, SnapResult


class InteractionMode:
    NONE = "none"
    DRAG_ELEMENT = "drag_element"
    RESIZE_LEFT = "resize_left"
    RESIZE_RIGHT = "resize_right"
    DRAG_ASSET = "drag_asset"
    RUBBER = "rubber"
    PLAYHEAD = "playhead"


@dataclass(frozen=True)
class Hit:
    """命中结果。zone 取 body / left / right / ""。"""

    element: Optional[Dict[str, Any]] = None
    zone: str = ""
    track_id: Optional[str] = None
    time: float = 0.0

    @property
    def element_id(self) -> str:
        return str(self.element.get("id", "")) if self.element else ""


@dataclass(frozen=True)
class Preview:
    """拖动过程中要画的 ghost + 反馈。控件只负责把它画出来。"""

    mode: str
    track_id: str
    start: float
    duration: float
    label: str = ""
    valid: bool = True
    reason: str = ""
    snap: Optional[SnapResult] = None
    element_id: str = ""
    #: 落位策略顺延了轨道时的说明（不是错误，只是提示）
    note: str = ""


    @property
    def end(self) -> float:
        return self.start + self.duration

    @property
    def snap_time(self) -> Optional[float]:
        return self.snap.guide_time if self.snap is not None else None

    @property
    def snap_label(self) -> str:
        return self.snap.guide_label if self.snap is not None else ""


@dataclass(frozen=True)
class MoveCommit:
    element_id: str
    start: float
    track_id: str
    #: 多选整体平移时，其它元素的 (id, start)
    followers: Tuple[Tuple[str, float], ...] = ()


@dataclass(frozen=True)
class ResizeCommit:
    element_id: str
    start: float
    duration: float
    edge: str


@dataclass(frozen=True)
class DropCommit:
    payload: Dict[str, Any]
    track_id: str
    start: float


@dataclass
class _Gesture:
    mode: str = InteractionMode.NONE
    coord: Optional[TimelineCoordinate] = None
    element_id: str = ""
    element_type: str = ""
    track_id: str = ""
    #: 按下点相对元素起点的时间偏移，move 全程保持不变
    grab_offset: float = 0.0
    origin_start: float = 0.0
    origin_duration: float = 0.0
    origin_x: float = 0.0
    origin_y: float = 0.0
    followers: Tuple[str, ...] = ()
    #: 多选整体平移用：按下那一刻其它选中元素的 (id, start)。
    #: 在按下时快照，避免拖动过程中反复回查模型。
    follower_starts: Tuple[Tuple[str, float], ...] = ()
    payload: Dict[str, Any] = field(default_factory=dict)
    moved: bool = False
    preview: Optional[Preview] = None


class TimelineInteraction:
    """交互控制器。一个 TrackCanvas 一个实例。

    控件负责喂进：坐标快照、元素列表、轨道表；控制器负责算出 preview 与 commit。
    """

    def __init__(self, snap: Optional[SnapEngine] = None) -> None:
        self.snap = snap or SnapEngine()
        self._gesture = _Gesture()

    # ------------------------------------------------------------ 查询

    @property
    def mode(self) -> str:
        return self._gesture.mode

    @property
    def active(self) -> bool:
        return self._gesture.mode != InteractionMode.NONE

    @property
    def preview(self) -> Optional[Preview]:
        return self._gesture.preview

    @property
    def dragging_element_id(self) -> str:
        return self._gesture.element_id

    def coordinate(self) -> Optional[TimelineCoordinate]:
        """手势期间的坐标快照（画 ghost 时必须用它，不能用最新的视图状态）。"""
        return self._gesture.coord

    # ------------------------------------------------------------ 命中测试

    @staticmethod
    def hit_test(
        coord: TimelineCoordinate,
        elements: Sequence[Dict[str, Any]],
        x: float,
        y: float,
    ) -> Hit:
        """从上层往下找，命中区用 hit rect（短片段也点得到）。"""
        track_id = coord.y_to_track(y)
        time = coord.clamp_time(coord.x_to_time(x))
        if track_id is None:
            return Hit(None, "", None, time)
        candidates = [e for e in elements if str(e.get("track", "")) == track_id]
        for element in reversed(candidates):
            rect = coord.element_to_hit_rect(element)
            if rect is None or not rect.contains(x, y):
                continue
            return Hit(element, coord.edge_zone(element, x) or "body", track_id, time)
        return Hit(None, "", track_id, time)

    # ------------------------------------------------------------ 轨道合法性

    @staticmethod
    def track_allows(element_type: str, track: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
        """元素类型能不能放进这条轨道。返回 (可以, 原因)。"""
        if not track:
            return (False, "这里没有轨道")
        expected = tl.TYPE_TRACK_KIND.get(element_type)
        kind = str(track.get("kind", ""))
        if expected and kind != expected:
            return (
                False,
                f"{tl.ELEMENT_TYPE_LABELS.get(element_type, element_type)}只能放到 "
                f"{expected} 轨，{track.get('id')} 是 {kind} 轨",
            )
        if track.get("locked"):
            return (False, f"{track.get('id')} 已锁定")
        return (True, "")

    # ------------------------------------------------------------ 手势：已有元素

    def begin_press(
        self,
        coord: TimelineCoordinate,
        elements: Sequence[Dict[str, Any]],
        x: float,
        y: float,
        selection: Sequence[str] = (),
        allow_edit: bool = True,
        markers: Sequence[float] = (),
    ) -> Hit:
        """左键按下。返回命中结果；控件据此决定选中谁。

        注意：**坐标快照在这里就固定**。之后视图被 selectionChanged 之类的信号
        滚走也不会影响 grab_offset 与 zone 判定。
        """
        hit = self.hit_test(coord, elements, x, y)
        self._gesture = _Gesture(coord=coord, origin_x=float(x), origin_y=float(y))
        if hit.element is None:
            self._gesture.mode = InteractionMode.RUBBER
            return hit
        if not allow_edit:
            self._gesture.mode = InteractionMode.NONE
            return hit

        element = hit.element
        start = _number(element.get("start"))
        duration = _number(element.get("duration"))
        mode = {
            "left": InteractionMode.RESIZE_LEFT,
            "right": InteractionMode.RESIZE_RIGHT,
        }.get(hit.zone, InteractionMode.DRAG_ELEMENT)

        self._gesture.mode = mode
        self._gesture.element_id = hit.element_id
        self._gesture.element_type = str(element.get("type", ""))
        self._gesture.track_id = str(element.get("track", ""))
        self._gesture.origin_start = start
        self._gesture.origin_duration = duration
        # 第七条：grab_offset = mouse_time - element.start，全程不变
        self._gesture.grab_offset = coord.x_to_time(x) - start
        self._gesture.followers = tuple(
            eid for eid in (selection or ()) if eid and eid != hit.element_id
        )
        by_id = {str(e.get("id", "")): e for e in elements}
        self._gesture.follower_starts = tuple(
            (eid, _number((by_id.get(eid) or {}).get("start")))
            for eid in self._gesture.followers
            if eid in by_id
        )
        self.snap.collect(
            elements,
            playhead=0.0,
            exclude_ids=[hit.element_id, *self._gesture.followers],
            markers=markers,
        )
        return hit

    def begin_asset_drag(
        self,
        coord: TimelineCoordinate,
        elements: Sequence[Dict[str, Any]],
        payload: Dict[str, Any],
        duration: float,
        element_type: str,
        label: str = "",
        playhead: float = 0.0,
        markers: Sequence[float] = (),
    ) -> None:
        """外部拖入（素材库 / 资源管理器）。第六条：左边缘对准鼠标落点。"""
        self._gesture = _Gesture(
            mode=InteractionMode.DRAG_ASSET,
            coord=coord,
            element_type=element_type,
            origin_duration=max(0.0, float(duration)),
            payload=dict(payload or {}),
        )
        self._gesture.payload["_label"] = label
        self._gesture.grab_offset = 0.0
        self.snap.collect(elements, playhead=playhead, markers=markers)

    def set_snap_targets(
        self,
        elements: Sequence[Dict[str, Any]],
        playhead: float,
        exclude_ids: Sequence[str] = (),
        markers: Sequence[float] = (),
    ) -> None:
        self.snap.collect(
            elements, playhead=playhead, exclude_ids=exclude_ids, markers=markers
        )

    # ------------------------------------------------------------ 手势：移动

    def update(
        self,
        x: float,
        y: float,
        tracks: Sequence[Dict[str, Any]],
        elements: Sequence[Dict[str, Any]] = (),
    ) -> Optional[Preview]:
        """鼠标移动 / 拖动移动。只算 preview，不写模型。"""
        gesture = self._gesture
        coord = gesture.coord
        if coord is None or gesture.mode in (InteractionMode.NONE, InteractionMode.RUBBER):
            return None

        gesture.moved = True
        mouse_time = coord.x_to_time(x)
        track_map = {str(t.get("id", "")): t for t in tracks}

        if gesture.mode in (InteractionMode.DRAG_ELEMENT, InteractionMode.DRAG_ASSET):
            duration = gesture.origin_duration
            raw_start = coord.clamp_time(mouse_time - gesture.grab_offset)
            snap = self.snap.snap_span(raw_start, duration, coord.pixels_per_second)
            start = coord.snap_time(coord.clamp_time(snap.time))

            target_track = coord.y_to_track(y) or gesture.track_id
            element_type = gesture.element_type
            ok, reason = self.track_allows(element_type, track_map.get(target_track))
            if not ok and gesture.mode == InteractionMode.DRAG_ELEMENT:
                # 移动已有元素：非法轨道就退回原轨道，但把原因带出去给状态栏
                fallback_ok, _ = self.track_allows(element_type, track_map.get(gesture.track_id))
                if fallback_ok:
                    target_track = gesture.track_id
                    ok = True
            note = ""
            if ok and target_track and gesture.mode == InteractionMode.DRAG_ASSET:
                # 第四条：从素材库拖进来时不要直接盖住已有元素。
                # 顺延是**拖动过程中**发生的，ghost 立刻跳到那条轨上，
                # 用户松手前就看得见落点，不是松手后被偷偷挪走。
                target_track, note = ap.next_free_track(
                    ap.for_element_type(element_type), tracks, elements,
                    start, duration, target_track,
                )
            preview = Preview(
                mode=gesture.mode,
                track_id=target_track or "",
                start=start,
                duration=duration,
                label=str(gesture.payload.get("_label") or gesture.element_id),
                valid=ok,
                reason="" if ok else reason,
                snap=snap if snap.snapped else None,
                element_id=gesture.element_id,
                note=note,
            )

            gesture.preview = preview
            return preview

        # Resize：左边缘动 start + duration，右边缘只动 duration
        frame = coord.frame_duration()
        origin_end = gesture.origin_start + gesture.origin_duration
        if gesture.mode == InteractionMode.RESIZE_LEFT:
            snap = self.snap.snap(mouse_time, coord.pixels_per_second)
            new_start = coord.snap_time(coord.clamp_time(snap.time))
            new_start = min(new_start, origin_end - frame)
            preview = Preview(
                mode=gesture.mode,
                track_id=gesture.track_id,
                start=new_start,
                duration=max(frame, origin_end - new_start),
                label=gesture.element_id,
                snap=snap if snap.snapped else None,
                element_id=gesture.element_id,
            )
        else:
            snap = self.snap.snap(mouse_time, coord.pixels_per_second)
            new_end = coord.snap_time(coord.clamp_time(snap.time))
            new_end = max(new_end, gesture.origin_start + frame)
            preview = Preview(
                mode=gesture.mode,
                track_id=gesture.track_id,
                start=gesture.origin_start,
                duration=max(frame, new_end - gesture.origin_start),
                label=gesture.element_id,
                snap=snap if snap.snapped else None,
                element_id=gesture.element_id,
            )
        gesture.preview = preview
        return preview

    # ------------------------------------------------------------ 落库

    def commit(self) -> Optional[Any]:
        """松手。返回 MoveCommit / ResizeCommit / DropCommit / None。

        一次手势只产出一条 commit，所以撤销栈里一次拖动就是一步 ——
        这同时修掉了"拖一次产生几十条撤销记录"。
        """
        gesture = self._gesture
        preview = gesture.preview
        if preview is None or not gesture.moved:
            return None
        if not preview.valid:
            return None

        if gesture.mode == InteractionMode.DRAG_ELEMENT:
            delta = preview.start - gesture.origin_start
            followers = tuple(
                (eid, max(0.0, start + delta)) for eid, start in gesture.follower_starts
            )
            return MoveCommit(gesture.element_id, preview.start, preview.track_id, followers)
        if gesture.mode in (InteractionMode.RESIZE_LEFT, InteractionMode.RESIZE_RIGHT):
            edge = "left" if gesture.mode == InteractionMode.RESIZE_LEFT else "right"
            return ResizeCommit(gesture.element_id, preview.start, preview.duration, edge)
        if gesture.mode == InteractionMode.DRAG_ASSET:
            payload = {k: v for k, v in gesture.payload.items() if k != "_label"}
            return DropCommit(payload, preview.track_id, preview.start)
        return None

    def follower_delta(self) -> float:
        """多选整体平移量。控件用它给其它选中元素算新 start。"""
        preview = self._gesture.preview
        if preview is None:
            return 0.0
        return preview.start - self._gesture.origin_start

    def followers(self) -> Tuple[str, ...]:
        return self._gesture.followers

    def drop_preview_time(self) -> Optional[float]:
        preview = self._gesture.preview
        return None if preview is None else preview.start

    def reset(self) -> None:
        self._gesture = _Gesture()

    # ------------------------------------------------------------ 框选

    def rubber_origin(self) -> Tuple[float, float]:
        return (self._gesture.origin_x, self._gesture.origin_y)

    def moved(self) -> bool:
        return self._gesture.moved


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback
