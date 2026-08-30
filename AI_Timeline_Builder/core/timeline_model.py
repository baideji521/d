"""Timeline 模型层：GUI 与 JSON 的唯一中介。

所有 GUI 操作都必须经过本模型的方法，模型负责：
1. 修改前压入撤销快照
2. 修改 Timeline JSON
3. 发出信号让 Timeline / 预览 / JSON 面板 / 属性面板同步刷新

反向也成立：set_timeline() 可以直接吃一份外部 JSON（人工写的或未来 AI 生成的），
解析后驱动整个 GUI。这就是 GUI ↔ JSON 双向同步的实现点。
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from core import timeline as tl
from core.time_utils import snap_to_frame


class TimelineModel(QObject):
    """持有一份 Timeline JSON，并把它的变化广播给所有面板。"""

    # 结构性变化（增删元素、换轨道、加载新 JSON），面板需要整体重建
    timelineChanged = pyqtSignal()
    # 单个元素参数变化，面板可以做轻量刷新
    elementUpdated = pyqtSignal(str)
    # 当前选中元素变化（空字符串表示取消选中）
    selectionChanged = pyqtSignal(str)
    # 撤销栈变化，用于刷新菜单可用状态
    historyChanged = pyqtSignal()
    # 播放头位置变化（秒）
    playheadChanged = pyqtSignal(float)
    # 中文日志
    logMessage = pyqtSignal(str)

    def __init__(self, undo_manager, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._timeline: Dict[str, Any] = tl.empty_timeline()
        self._undo = undo_manager
        self._selected_id: str = ""
        self._selection: List[str] = []
        self._playhead: float = 0.0

    # ------------------------------------------------------------ 基本访问

    @property
    def timeline(self) -> Dict[str, Any]:
        """返回内部 JSON 的引用。只读用途；修改请走模型方法。"""
        return self._timeline

    @property
    def fps(self) -> float:
        return float(self._timeline.get("meta", {}).get("fps", 30))

    @property
    def width(self) -> int:
        return int(self._timeline.get("meta", {}).get("width", 1080))

    @property
    def height(self) -> int:
        return int(self._timeline.get("meta", {}).get("height", 1920))

    @property
    def duration(self) -> float:
        return tl.timeline_duration(self._timeline)

    @property
    def selected_id(self) -> str:
        return self._selected_id

    def selection(self) -> List[str]:
        """当前选中的所有元素 id。单选时就是一个元素的列表。"""
        return list(self._selection)


    @property
    def playhead(self) -> float:
        return self._playhead

    def to_json_text(self) -> str:
        """导出格式化 JSON 文本，供 JSON 面板显示与保存。"""
        self._timeline["meta"]["duration"] = tl.timeline_duration(self._timeline)
        return json.dumps(self._timeline, ensure_ascii=False, indent=2)

    def element(self, element_id: str) -> Optional[Dict[str, Any]]:
        return tl.get_element(self._timeline, element_id)

    def elements(self) -> List[Dict[str, Any]]:
        return self._timeline.get("elements", [])

    def tracks(self) -> List[Dict[str, Any]]:
        return self._timeline.get("tracks", [])

    def track(self, track_id: str) -> Optional[Dict[str, Any]]:
        return tl.get_track(self._timeline, track_id)

    # ------------------------------------------------------------ 撤销支持

    def _begin(self, description: str) -> None:
        """在任何修改前调用，记录快照。"""
        self._undo.push(description, self._timeline)

    def _commit(self, structural: bool = True, element_id: str = "") -> None:
        """修改完成后广播。structural=True 表示面板需要整体重建。"""
        self._timeline["meta"]["duration"] = tl.timeline_duration(self._timeline)
        if structural:
            self.timelineChanged.emit()
        elif element_id:
            self.elementUpdated.emit(element_id)
        else:
            self.timelineChanged.emit()
        self.historyChanged.emit()

    def undo(self) -> None:
        result = self._undo.undo(self._timeline)
        if result is None:
            self.logMessage.emit("没有可撤销的操作")
            return
        description, snapshot = result
        self._timeline = snapshot
        self._ensure_selection_valid()
        self.logMessage.emit(f"已撤销：{description}")
        self.timelineChanged.emit()
        self.historyChanged.emit()

    def redo(self) -> None:
        result = self._undo.redo(self._timeline)
        if result is None:
            self.logMessage.emit("没有可重做的操作")
            return
        description, snapshot = result
        self._timeline = snapshot
        self._ensure_selection_valid()
        self.logMessage.emit(f"已重做：{description}")
        self.timelineChanged.emit()
        self.historyChanged.emit()

    def can_undo(self) -> bool:
        return self._undo.can_undo()

    def can_redo(self) -> bool:
        return self._undo.can_redo()

    # ------------------------------------------------------------ 整体替换

    def set_timeline(self, data: Dict[str, Any], description: str = "加载 Timeline JSON") -> None:
        """用一份完整 JSON 替换当前时间线（JSON → GUI 方向的入口）。"""
        self._begin(description)
        self._timeline = copy.deepcopy(data)
        self._normalize()
        self._ensure_selection_valid()
        self.logMessage.emit(
            f"{description}：{len(self._timeline.get('elements', []))} 个元素，"
            f"{len(self._timeline.get('tracks', []))} 条轨道"
        )
        self.timelineChanged.emit()
        self.historyChanged.emit()

    def reset(self, name: str = "未命名项目") -> None:
        """新建空项目，同时清空撤销历史。"""
        self._timeline = tl.empty_timeline(name)
        self._selected_id = ""
        self._playhead = 0.0
        self._undo.clear()
        self.logMessage.emit(f"已新建空项目：{name}")
        self.timelineChanged.emit()
        self.selectionChanged.emit("")
        self.historyChanged.emit()

    def _normalize(self) -> None:
        """补齐外部 JSON 可能缺失的字段，保证 GUI 不会因为缺 key 崩溃。"""
        self._timeline.setdefault("version", tl.SCHEMA_VERSION)
        self._timeline.setdefault("time_unit", tl.TIME_UNIT)
        meta = self._timeline.setdefault("meta", {})
        meta.setdefault("name", "未命名项目")
        meta.setdefault("fps", 30)
        meta.setdefault("width", 1080)
        meta.setdefault("height", 1920)
        meta.setdefault("background", "#000000")
        if not self._timeline.get("tracks"):
            self._timeline["tracks"] = copy.deepcopy(tl.DEFAULT_TRACKS)
        self._timeline.setdefault("elements", [])
        for element in self._timeline["elements"]:
            element.setdefault("start", 0.0)
            if element.get("type") not in ("transition",):
                element.setdefault("duration", 1.0)
            if element.get("type") in ("video", "overlay", "text", "caption", "caption_group", "freeze"):
                element.setdefault("transform", tl.default_transform())
                element.setdefault("keyframes", {})
        meta["duration"] = tl.timeline_duration(self._timeline)

    def _ensure_selection_valid(self) -> None:
        """加载 / 撤销后如果选中的元素已不存在，就清空选中。"""
        self._selection = [
            eid for eid in self._selection if tl.get_element(self._timeline, eid) is not None
        ]
        if self._selected_id and tl.get_element(self._timeline, self._selected_id) is None:
            self._selected_id = self._selection[0] if self._selection else ""
            self.selectionChanged.emit(self._selected_id)


    # ------------------------------------------------------------ 选中与播放头

    def select(self, element_id: str) -> None:
        """单选。Timeline / JSON 面板 / 属性面板通过这个信号互相定位。"""
        target = element_id or ""
        if target == self._selected_id and self._selection == ([target] if target else []):
            return
        self._selected_id = target
        self._selection = [target] if target else []
        self.selectionChanged.emit(self._selected_id)

    def select_many(self, element_ids: List[str]) -> None:
        """多选。第一个作为「主选中」，属性面板仍然只显示主选中那一个。"""
        valid = [eid for eid in dict.fromkeys(element_ids) if tl.get_element(self._timeline, eid)]
        self._selection = valid
        self._selected_id = valid[0] if valid else ""
        self.selectionChanged.emit(self._selected_id)

    def toggle_select(self, element_id: str) -> None:
        """Ctrl+点击：加选 / 取消选中。"""
        if not element_id:
            return
        current = list(self._selection)
        if element_id in current:
            current.remove(element_id)
        else:
            current.append(element_id)
        self.select_many(current)

    def select_all(self) -> None:
        self.select_many([e.get("id", "") for e in self.elements()])


    def set_playhead(self, seconds: float) -> None:
        seconds = max(0.0, snap_to_frame(seconds, self.fps))
        if abs(seconds - self._playhead) < 1e-9:
            return
        self._playhead = seconds
        self.playheadChanged.emit(seconds)

    def set_meta(self, key: str, value: Any) -> None:
        """修改项目级参数（fps / 分辨率 / 名称）。"""
        self._begin(f"修改项目参数 {key}")
        self._timeline.setdefault("meta", {})[key] = value
        self.logMessage.emit(f"项目参数 {key} 改为 {value}")
        self._commit(structural=True)

    # ------------------------------------------------------------ 元素增删

    def new_element_id(self, type_name: str) -> str:
        return tl.next_element_id(self._timeline, type_name)

    def add_element(self, element: Dict[str, Any], description: str = "") -> str:
        """添加元素。若 id 冲突会自动换一个。"""
        element = copy.deepcopy(element)
        if not element.get("id") or tl.get_element(self._timeline, element["id"]):
            element["id"] = tl.next_element_id(self._timeline, element.get("type", "element"))
        label = description or f"添加{tl.ELEMENT_TYPE_LABELS.get(element.get('type'), '元素')}"
        self._begin(label)
        self._timeline["elements"].append(element)
        self.logMessage.emit(
            f"{label} {element['id']}："
            f"start={element.get('start')}s duration={element.get('duration')}s "
            f"track={element.get('track')}"
        )
        self._commit(structural=True)
        self.select(element["id"])
        return element["id"]

    def add_elements(self, elements: List[Dict[str, Any]], description: str) -> List[str]:
        """批量添加（模板展开专用），只产生一次撤销记录。"""
        self._begin(description)
        added: List[str] = []
        for raw in elements:
            element = copy.deepcopy(raw)
            if not element.get("id") or tl.get_element(self._timeline, element["id"]):
                element["id"] = tl.next_element_id(self._timeline, element.get("type", "element"))
            self._timeline["elements"].append(element)
            added.append(element["id"])
        self.logMessage.emit(f"{description}：展开 {len(added)} 个元素 {added}")
        self._commit(structural=True)
        if added:
            self.select(added[0])
        return added

    def remove_element(self, element_id: str) -> None:
        """删除元素，同时清理引用它的转场 / 特效 / 冻结帧。"""
        element = tl.get_element(self._timeline, element_id)
        if element is None:
            return
        type_label = tl.ELEMENT_TYPE_LABELS.get(element.get("type"), "元素")
        self._begin(f"删除{type_label}")
        removed = [element_id]
        keep: List[Dict[str, Any]] = []
        for item in self._timeline["elements"]:
            if item.get("id") == element_id:
                continue
            if item.get("type") == "transition" and element_id in (item.get("from"), item.get("to")):
                removed.append(item.get("id"))
                continue
            if item.get("type") in ("effect", "freeze") and item.get("target") == element_id:
                removed.append(item.get("id"))
                continue
            keep.append(item)
        self._timeline["elements"] = keep
        if self._selected_id in removed:
            self._selected_id = ""
            self.selectionChanged.emit("")
        self._selection = [eid for eid in self._selection if eid not in removed]
        self.logMessage.emit(f"删除{type_label} {element_id}，级联清理 {removed}")
        self._commit(structural=True)

    def remove_elements(self, element_ids: List[str]) -> List[str]:
        """批量删除（多选删除），只产生一次撤销记录，同样做级联清理。"""
        targets = {
            eid for eid in element_ids if tl.get_element(self._timeline, eid) is not None
        }
        if not targets:
            return []
        if len(targets) == 1:
            only = next(iter(targets))
            self.remove_element(only)
            return [only]

        self._begin(f"删除 {len(targets)} 个元素")
        removed = set(targets)
        keep: List[Dict[str, Any]] = []
        for item in self._timeline["elements"]:
            item_id = item.get("id")
            if item_id in targets:
                continue
            if item.get("type") == "transition" and (
                item.get("from") in targets or item.get("to") in targets
            ):
                removed.add(item_id)
                continue
            if item.get("type") in ("effect", "freeze") and item.get("target") in targets:
                removed.add(item_id)
                continue
            keep.append(item)
        self._timeline["elements"] = keep
        self._selection = [eid for eid in self._selection if eid not in removed]
        if self._selected_id in removed:
            self._selected_id = self._selection[0] if self._selection else ""
            self.selectionChanged.emit(self._selected_id)
        self.logMessage.emit(f"删除 {len(targets)} 个元素，级联清理后共 {len(removed)} 个：{sorted(removed)}")
        self._commit(structural=True)
        return sorted(removed)

    def duplicate_element(self, element_id: str) -> Optional[str]:
        """复制元素并紧接其后放置，做参数对照实验很方便。"""
        element = tl.get_element(self._timeline, element_id)
        if element is None:
            return None
        clone = copy.deepcopy(element)
        clone["id"] = tl.next_element_id(self._timeline, clone.get("type", "element"))
        clone["start"] = round(tl.element_end(element), 3)
        return self.add_element(clone, description="复制元素")

    def duplicate_in_place(self, element_id: str) -> Optional[str]:
        """原地复制一份（Alt+拖动用）：位置不变，随后由拖动决定去哪。"""
        element = tl.get_element(self._timeline, element_id)
        if element is None:
            return None
        clone = copy.deepcopy(element)
        clone["id"] = tl.next_element_id(self._timeline, clone.get("type", "element"))
        return self.add_element(clone, description="Alt 拖动复制元素")

    # ------------------------------------------------------------ 时间与轨道

    def move_element(self, element_id: str, new_start: float, new_track: Optional[str] = None) -> None:
        """拖动元素：改开始时间，可选换轨道。"""
        element = tl.get_element(self._timeline, element_id)
        if element is None:
            return
        new_start = max(0.0, snap_to_frame(new_start, self.fps))
        target_track = new_track or element.get("track")
        if abs(new_start - float(element.get("start", 0.0))) < 1e-9 and target_track == element.get("track"):
            return
        self._begin("移动元素")
        old_start = element.get("start")
        old_track = element.get("track")
        # caption_group 的 words 是绝对时间，整体平移时必须同步搬走
        if element.get("type") == "caption_group":
            delta = new_start - float(element.get("start", 0.0))
            for word in element.get("content", {}).get("words", []):
                word["start"] = round(float(word["start"]) + delta, 3)
                word["end"] = round(float(word["end"]) + delta, 3)
        element["start"] = new_start
        if new_track:
            element["track"] = new_track
        self.logMessage.emit(
            f"移动 {element_id}：start {old_start}s → {new_start}s，"
            f"track {old_track} → {element.get('track')}"
        )
        self._commit(structural=True)

    def resize_element(self, element_id: str, new_start: float, new_duration: float) -> None:
        """拖动元素左右边缘裁剪。视频 / 音频会同步调整 source 区间。"""
        element = tl.get_element(self._timeline, element_id)
        if element is None:
            return
        fps = self.fps
        new_start = max(0.0, snap_to_frame(new_start, fps))
        new_duration = max(1.0 / fps, snap_to_frame(new_duration, fps))
        self._begin("裁剪元素")
        old_start = float(element.get("start", 0.0))
        old_duration = float(element.get("duration", 0.0))
        source = element.get("source")
        if source and element.get("type") in ("video", "audio"):
            speed = float(element.get("speed", 1.0)) or 1.0
            # 左边缘移动 -> 源起点同步移动；右边缘 -> 源终点同步
            head_delta = (new_start - old_start) * speed
            src_start = max(0.0, float(source["start"]) + head_delta)
            src_end = src_start + new_duration * speed
            source["start"] = round(src_start, 3)
            source["end"] = round(src_end, 3)
        element["start"] = new_start
        element["duration"] = round(new_duration, 3)
        self.logMessage.emit(
            f"裁剪 {element_id}：start {old_start}s → {new_start}s，"
            f"duration {old_duration}s → {element['duration']}s，source={element.get('source')}"
        )
        self._commit(structural=True)

    def set_element_field(
        self,
        element_id: str,
        path: List[str],
        value: Any,
        description: str = "",
    ) -> None:
        """按路径修改元素字段，例如 ['transform', 'scale'] 或 ['style', 'stroke', 'width']。"""
        element = tl.get_element(self._timeline, element_id)
        if element is None:
            return
        label = description or f"修改 {'.'.join(path)}"
        self._begin(label)
        node: Any = element
        for key in path[:-1]:
            node = node.setdefault(key, {})
        old = node.get(path[-1])
        node[path[-1]] = value
        # 视频改速度或源区间后，时间线时长必须重新推导，否则 JSON 自相矛盾
        if element.get("type") in ("video", "audio") and path[0] in ("speed", "source"):
            source = element.get("source") or {}
            speed = float(element.get("speed", 1.0)) or 1.0
            span = float(source.get("end", 0.0)) - float(source.get("start", 0.0))
            if span > 0:
                element["duration"] = round(max(1.0 / self.fps, span / speed), 3)
        self.logMessage.emit(f"{element_id} {'.'.join(path)}：{old} → {value}")
        self._commit(structural=True)

    # ------------------------------------------------------------ 关键帧

    def add_keyframe(
        self,
        element_id: str,
        param: str,
        local_time: float,
        value: float,
        easing: str = "linear",
    ) -> None:
        """在元素相对时间 local_time 处打一个关键帧。同一时间点会被覆盖。"""
        element = tl.get_element(self._timeline, element_id)
        if element is None or param not in tl.KEYFRAME_PARAMS:
            return
        self._begin(f"添加关键帧 {param}")
        keyframes = element.setdefault("keyframes", {}).setdefault(param, [])
        local_time = round(max(0.0, local_time), 3)
        for kf in keyframes:
            if abs(float(kf.get("time", 0.0)) - local_time) < 1e-6:
                kf["value"] = value
                kf["easing"] = easing
                break
        else:
            keyframes.append({"time": local_time, "value": value, "easing": easing})
        keyframes.sort(key=lambda k: float(k.get("time", 0.0)))
        self.logMessage.emit(f"{element_id} 关键帧 {param} @ {local_time}s = {value}（{easing}）")
        self._commit(structural=True)

    def remove_keyframe(self, element_id: str, param: str, index: int) -> None:
        element = tl.get_element(self._timeline, element_id)
        if element is None:
            return
        keyframes = (element.get("keyframes") or {}).get(param) or []
        if not (0 <= index < len(keyframes)):
            return
        self._begin(f"删除关键帧 {param}")
        removed = keyframes.pop(index)
        if not keyframes:
            element["keyframes"].pop(param, None)
        self.logMessage.emit(f"{element_id} 删除关键帧 {param} @ {removed.get('time')}s")
        self._commit(structural=True)

    def update_keyframe(
        self,
        element_id: str,
        param: str,
        index: int,
        time_value: float,
        value: float,
        easing: str,
    ) -> None:
        element = tl.get_element(self._timeline, element_id)
        if element is None:
            return
        keyframes = (element.get("keyframes") or {}).get(param) or []
        if not (0 <= index < len(keyframes)):
            return
        self._begin(f"修改关键帧 {param}")
        keyframes[index] = {
            "time": round(max(0.0, time_value), 3),
            "value": value,
            "easing": easing,
        }
        keyframes.sort(key=lambda k: float(k.get("time", 0.0)))
        self.logMessage.emit(f"{element_id} 关键帧 {param}[{index}] 更新为 {keyframes[index]}")
        self._commit(structural=True)

    def apply_animation(self, element_id: str, animation: Dict[str, Any]) -> None:
        """把动画库里的关键帧模板套到元素上（会覆盖同名参数的既有关键帧）。"""
        element = tl.get_element(self._timeline, element_id)
        if element is None:
            return
        self._begin(f"应用动画 {animation.get('label', animation.get('id'))}")
        duration = float(animation.get("duration", 0.3))
        element.setdefault("keyframes", {})
        for param, points in (animation.get("keyframes") or {}).items():
            if param not in tl.KEYFRAME_PARAMS:
                continue
            element["keyframes"][param] = copy.deepcopy(points)
        element["animation"] = animation.get("id", "")
        self.logMessage.emit(
            f"{element_id} 应用动画 {animation.get('id')}，时长 {duration}s，"
            f"参数 {list((animation.get('keyframes') or {}).keys())}"
        )
        self._commit(structural=True)

    # ------------------------------------------------------------ 轨道操作

    def add_track(self, track_id: str, name: str, kind: str) -> bool:
        if tl.get_track(self._timeline, track_id):
            self.logMessage.emit(f"轨道 {track_id} 已存在，未添加")
            return False
        self._begin("新增轨道")
        self._timeline["tracks"].append(
            {"id": track_id, "name": name, "kind": kind, "locked": False, "hidden": False}
        )
        self.logMessage.emit(f"新增轨道 {track_id}（{name}，{kind}）")
        self._commit(structural=True)
        return True

    def remove_track(self, track_id: str) -> None:
        """删除轨道，同时删除其上所有元素。"""
        if not tl.get_track(self._timeline, track_id):
            return
        self._begin("删除轨道")
        doomed = {e.get("id") for e in self._timeline["elements"] if e.get("track") == track_id}
        self._timeline["tracks"] = [t for t in self._timeline["tracks"] if t.get("id") != track_id]
        self._timeline["elements"] = [
            e
            for e in self._timeline["elements"]
            if e.get("track") != track_id
            and e.get("from") not in doomed
            and e.get("to") not in doomed
        ]
        if self._selected_id in doomed:
            self._selected_id = ""
            self.selectionChanged.emit("")
        self.logMessage.emit(f"删除轨道 {track_id}，同时移除 {len(doomed)} 个元素")
        self._commit(structural=True)

    def rename_track(self, track_id: str, name: str) -> None:
        track = tl.get_track(self._timeline, track_id)
        if track is None:
            return
        self._begin("重命名轨道")
        track["name"] = name
        self.logMessage.emit(f"轨道 {track_id} 重命名为 {name}")
        self._commit(structural=True)

    def toggle_track_flag(self, track_id: str, flag: str) -> None:
        """切换 locked / hidden。"""
        track = tl.get_track(self._timeline, track_id)
        if track is None or flag not in ("locked", "hidden"):
            return
        self._begin("修改轨道状态")
        track[flag] = not bool(track.get(flag))
        label = "锁定" if flag == "locked" else "隐藏"
        self.logMessage.emit(f"轨道 {track_id} {label}：{track[flag]}")
        self._commit(structural=True)

    def move_track(self, track_id: str, offset: int) -> None:
        """调整轨道顺序，直接影响默认 Z-Index。"""
        tracks = self._timeline["tracks"]
        index = next((i for i, t in enumerate(tracks) if t.get("id") == track_id), -1)
        if index < 0:
            return
        target = index + offset
        if not (0 <= target < len(tracks)):
            return
        self._begin("调整轨道顺序")
        tracks[index], tracks[target] = tracks[target], tracks[index]
        self.logMessage.emit(
            f"轨道 {track_id} 顺序 {index} → {target}，Z-Index 变为 {tl.track_z_index(self._timeline, track_id)}"
        )
        self._commit(structural=True)

    def is_track_locked(self, track_id: str) -> bool:
        track = tl.get_track(self._timeline, track_id)
        return bool(track and track.get("locked"))
