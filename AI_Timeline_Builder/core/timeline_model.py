"""Timeline 模型层：GUI 与 JSON 的唯一中介。

所有 GUI 操作都必须经过本模型的方法，模型负责：
1. 修改前压入撤销快照
2. 修改 Timeline JSON
3. 发出信号让 Timeline / 预览 / JSON 面板 / 属性面板同步刷新

反向也成立：set_timeline() / from_dict() 可以直接吃一份外部 JSON（人工写的、
剪映导入的、或未来 AI 生成的），解析后驱动整个 GUI。这就是 GUI ↔ JSON
双向同步的实现点。

三层边界（阶段 6.5 第三条），本文件是中间那一层：

    Timeline JSON        只保存显式编辑意图      ← to_dict() / to_json_text()
    TimelineModel        提供 effective value    ← get_effective_*()
    Remotion Runtime     渲染时补默认值          ← `element.speed ?? 1`

因此：

* **to_dict() 是稀疏的**（core/sparse.py 负责 default elision），
  GUI 的保存 / 导出 / JSON 面板全部走它，绝不会把默认值写进用户的项目文件。
* **_normalize() 不补 transform / keyframes 默认值**，只把脏标量压成真数字。
  界面在 paintEvent 里对元素做算术不能抛异常 —— PyQt 槽里抛异常会直接把
  进程带走（0xC0000409），用户连校验错误都看不到。
* 需要「最终生效值」的地方一律读 get_effective_*()，不回写元素。
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from core import markers as marker_utils
from core import sparse


from core import timeline as tl
from core.migrations import detect_version, migrate_to_v1, migrate_v1_to_v2
from core.time_utils import snap_to_frame

#: 需要在 _normalize() 里被压成数字的顶层标量字段
_SCALAR_NUMBER_FIELDS = ("start", "duration", "source_time", "speed", "volume")

#: 需要逐键压成数字的嵌套对象字段
_NESTED_NUMBER_FIELDS = ("source", "transform", "fade")


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
        self._validator: Any = None

    # ------------------------------------------------------------ 基本访问

    @property
    def timeline(self) -> Dict[str, Any]:
        """返回内部 JSON 的引用。只读用途；修改请走模型方法。"""
        return self._timeline

    @property
    def fps(self) -> float:
        return float(self._timeline.get("meta", {}).get("fps", 30) or 30)

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

    def element(self, element_id: str) -> Optional[Dict[str, Any]]:
        return tl.get_element(self._timeline, element_id)

    def get_element(self, element_id: str) -> Optional[Dict[str, Any]]:
        """element() 的同义方法，与 get_effective_* 一族的命名保持一致。"""
        return tl.get_element(self._timeline, element_id)

    def elements(self) -> List[Dict[str, Any]]:
        return self._timeline.get("elements", [])

    def tracks(self) -> List[Dict[str, Any]]:
        return self._timeline.get("tracks", [])

    def track(self, track_id: str) -> Optional[Dict[str, Any]]:
        return tl.get_track(self._timeline, track_id)

    def active_track_ids(self) -> List[str]:
        """真正被元素引用的轨道 id，按元素出现顺序去重。

        编辑器里永远有 9 条预设轨（sparse.merge_editor_tracks），导出的 JSON
        只留活跃轨道 —— 两者是不同的概念，这个方法回答后者。
        """
        result: List[str] = []
        for element in self._timeline.get("elements", []):
            if not isinstance(element, dict):
                continue
            track_id = element.get("track")
            if isinstance(track_id, str) and track_id and track_id not in result:
                result.append(track_id)
        return result

    # ------------------------------------------------------------ 生效值
    #
    # element.get("transform") 回答「用户设置了什么」，
    # get_effective_transform() 回答「最终生效值是什么」。
    # 面板显示与预览一律读后者，且绝不回写元素（否则稀疏化立刻失效）。

    def get_effective_transform(self, element: Dict[str, Any]) -> Dict[str, float]:
        return tl.effective_transform(element or {})

    def get_effective_speed(self, element: Dict[str, Any]) -> float:
        return tl.effective_speed(element or {})

    def get_effective_audio(self, element: Dict[str, Any]) -> Dict[str, Any]:
        return tl.effective_audio(element or {})

    def get_effective_volume(self, element: Dict[str, Any]) -> float:
        return tl.effective_volume(element or {})

    def get_effective_fade(self, element: Dict[str, Any]) -> Dict[str, float]:
        return tl.effective_fade(element or {})

    def get_effective_keyframes(self, element: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        return tl.effective_keyframes(element or {})

    # ------------------------------------------------------------ 序列化

    def to_dict(self) -> Dict[str, Any]:
        """导出 Canonical Sparse JSON —— 保存 / 导出 / 渲染都用这一份。

        返回的是新对象，改它不会影响模型（core/sparse.py 内部深拷贝）。
        """
        return sparse.sparse_timeline(self._timeline)

    def to_effective_dict(self) -> Dict[str, Any]:
        """补齐全部默认值的完整快照。调试 / 对照用，不要拿去保存。"""
        return sparse.effective_timeline(self._timeline)

    def to_v2_dict(self) -> Dict[str, Any]:
        """v2 协议视图。运行时仍然是 v1，这里只做导出侧的格式转换。"""
        return migrate_v1_to_v2(self.to_dict())

    def to_json_text(self) -> str:
        """导出格式化 JSON 文本，供 JSON 面板显示与保存。"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def from_dict(
        self,
        data: Dict[str, Any],
        description: str = "加载 Timeline JSON",
    ) -> Dict[str, Any]:
        """set_timeline() 的同义方法，语义上与 to_dict() 成对。"""
        return self.set_timeline(data, description)

    # ------------------------------------------------------------ 校验

    def set_validator(self, validator: Any) -> None:
        """注入 TimelineValidator。GUI → Model → Schema 校验这条链的接线点。"""
        self._validator = validator

    def validate(self, timeline: Optional[Dict[str, Any]] = None) -> List[Any]:
        """返回 Issue 列表。没注入校验器时返回空列表，不抛异常。"""
        if self._validator is None:
            return []
        return self._validator.validate(self.to_dict() if timeline is None else timeline)

    def validate_report(self, timeline: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """结构化校验报告。任何输入都不抛异常，GUI 靠它决定能不能渲染。

        默认校验 to_dict() —— 那才是真正会被保存与渲染的文档。
        """
        target = self.to_dict() if timeline is None else timeline
        if self._validator is None:
            return {
                "valid": True,
                "version": detect_version(target) if isinstance(target, dict) else 0,
                "errors": [],
                "warnings": [],
            }
        return self._validator.validate_report(target)

    # ------------------------------------------------------------ 撤销支持

    def _begin(self, description: str) -> None:
        """在任何修改前调用，记录快照。"""
        self._undo.push(description, self._timeline)

    def _commit(self, structural: bool = True, element_id: str = "") -> None:
        """修改完成后广播。structural=True 表示面板需要整体重建。"""
        self._timeline.setdefault("meta", {})["duration"] = tl.timeline_duration(self._timeline)
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

    def set_timeline(
        self,
        data: Dict[str, Any],
        description: str = "加载 Timeline JSON",
    ) -> Dict[str, Any]:
        """用一份完整 JSON 替换当前时间线（JSON → GUI 方向的入口）。

        返回**对原始输入**的结构化校验报告：先校验、后净化。顺序不能反 ——
        _normalize() 会把 duration="五秒" 压成 0.0，净化之后再校验就什么都
        报不出来了，用户只会看到一个莫名变短的片段。
        """
        self._begin(description)
        incoming = copy.deepcopy(data) if isinstance(data, dict) else {}
        # v2 文档也能直接灌进来：运行时统一降级成 v1
        if isinstance(data, dict) and detect_version(data) >= 2:
            incoming = migrate_to_v1(incoming)
        report = self.validate_report(incoming)

        self._timeline = incoming
        self._normalize()
        self._ensure_selection_valid()

        self.logMessage.emit(
            f"{description}：{len(self._timeline.get('elements', []))} 个元素，"
            f"{len(self._timeline.get('tracks', []))} 条轨道"
        )
        for error in report.get("errors", []):
            self.logMessage.emit(f"　校验错误 {error.get('rule')}：{error.get('message')}")
        for warning in report.get("warnings", []):
            self.logMessage.emit(f"　校验警告 {warning.get('rule')}：{warning.get('message')}")

        self.timelineChanged.emit()
        self.historyChanged.emit()
        return report

    def reset(self, name: str = "未命名项目") -> None:
        """新建空项目，同时清空撤销历史。"""
        self._timeline = tl.empty_timeline(name)
        self._selected_id = ""
        self._selection = []
        self._playhead = 0.0
        self._undo.clear()
        self.logMessage.emit(f"已新建空项目：{name}")
        self.timelineChanged.emit()
        self.selectionChanged.emit("")
        self.historyChanged.emit()

    def _normalize(self) -> None:
        """把外部 JSON 整理成 GUI 能安全消费的形状。

        阶段 6.5：这里**不再补 transform / keyframes 默认值**。补默认值会让
        「打开一个项目再保存」凭空长出一堆字段，稀疏化就白做了。
        本方法只做两件事：

        1. 结构兜底 —— 缺 meta / tracks / elements 时给出合法的空壳
        2. 脏标量压平 —— duration="五秒" → 0.0，界面做算术不会抛异常

        真正的报错由 TimelineValidator 负责，它在本方法**之前**跑
        （见 set_timeline 的注释）。
        """
        if not isinstance(self._timeline, dict):
            self._timeline = tl.empty_timeline()

        self._timeline.setdefault("version", tl.SCHEMA_VERSION)
        self._timeline.setdefault("time_unit", tl.TIME_UNIT)

        meta = self._timeline.get("meta")
        if not isinstance(meta, dict):
            meta = {}
            self._timeline["meta"] = meta
        meta.setdefault("name", "未命名项目")
        meta["fps"] = tl.as_seconds(meta.get("fps")) or 30
        meta["width"] = int(tl.as_seconds(meta.get("width")) or 1080)
        meta["height"] = int(tl.as_seconds(meta.get("height")) or 1920)

        tracks = self._timeline.get("tracks")
        if not isinstance(tracks, list) or not tracks:
            tracks = copy.deepcopy(tl.DEFAULT_TRACKS)
        # 编辑器始终显示 9 条预设轨；导出时 sparse_tracks() 再收敛回活跃轨道
        self._timeline["tracks"] = sparse.merge_editor_tracks(tracks)

        elements = self._timeline.get("elements")
        if not isinstance(elements, list):
            elements = []
        self._timeline["elements"] = [e for e in elements if isinstance(e, dict)]

        for element in self._timeline["elements"]:
            self._normalize_element(element)

        meta["duration"] = tl.timeline_duration(self._timeline)

    def _normalize_element(self, element: Dict[str, Any]) -> None:
        """单个元素的脏值压平。只动已存在的键，不凭空添加字段。"""
        element.setdefault("start", 0.0)
        if element.get("type") not in ("transition",):
            element.setdefault("duration", 1.0)

        for key in _SCALAR_NUMBER_FIELDS:
            if key in element:
                element[key] = tl.as_seconds(element[key])

        for group in _NESTED_NUMBER_FIELDS:
            node = element.get(group)
            if isinstance(node, dict):
                for key, value in list(node.items()):
                    node[key] = tl.as_seconds(value)

        # audio.enabled 是布尔开关，不能被 as_seconds 压成数字（第二十八条）
        audio = element.get("audio")
        if isinstance(audio, dict) and "volume" in audio:
            audio["volume"] = tl.as_seconds(audio["volume"])

        keyframes = element.get("keyframes")
        if isinstance(keyframes, dict):
            for param, points in list(keyframes.items()):
                if not isinstance(points, list):
                    keyframes[param] = []
                    continue
                for point in points:
                    if not isinstance(point, dict):
                        continue
                    for key in ("time", "value"):
                        if key in point:
                            point[key] = tl.as_seconds(point[key])

        # caption_group 的逐词时间是绝对时间，同样可能是脏的
        content = element.get("content")
        words = content.get("words") if isinstance(content, dict) else None
        if isinstance(words, list):
            for word in words:
                if not isinstance(word, dict):
                    continue
                for key in ("start", "end"):
                    if key in word:
                        word[key] = tl.as_seconds(word[key])

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

    def set_canvas(self, width: int, height: int) -> None:
        """一次改画布宽高，只留一条撤销记录。

        宽高必须一起改：分开改会在中间态出现 810×1920 这种不存在的比例，
        预览会闪一下，撤销也要按两次。
        """
        self._begin("修改画布尺寸")
        meta = self._timeline.setdefault("meta", {})
        meta["width"] = int(width)
        meta["height"] = int(height)
        self.logMessage.emit(f"画布改为 {int(width)}×{int(height)}")
        self._commit(structural=True)

    # ------------------------------------------------------------ 全局音量

    @property
    def master_volume(self) -> float:
        """全局输出音量。缺省 1；这是**导出音量**，预览没有音频通路。"""
        return tl.effective_master_volume(self._timeline)

    def set_master_volume(self, value: float) -> None:
        """改全局输出音量。等于默认值时把字段删掉，保持稀疏。"""
        low, high = tl.MASTER_VOLUME_RANGE
        try:
            target = max(low, min(high, float(value)))
        except (TypeError, ValueError):
            self.logMessage.emit(f"音量不合法：{value}")
            return
        if abs(target - self.master_volume) < 1e-6:
            return
        self._begin("修改全局音量")
        meta = self._timeline.setdefault("meta", {})
        if abs(target - tl.DEFAULT_MASTER_VOLUME) < 1e-6:
            meta.pop("master_volume", None)
        else:
            meta["master_volume"] = round(target, 3)
        self.logMessage.emit(
            "整片静音（导出）" if target <= 0 else f"全局音量 {target:g}（仅影响导出，预览无声）"
        )
        self._commit(structural=True)


    # ------------------------------------------------------------ 标记

    def markers(self) -> List[Dict[str, Any]]:
        """时间线标记（按时间排序）。纯标注，不参与渲染。"""
        return marker_utils.markers_of(self._timeline)

    def marker_times(self) -> List[float]:
        return marker_utils.marker_times(self._timeline)

    def add_marker(self, time: float, marker_type: str = marker_utils.DEFAULT_TYPE,
                   label: str = "") -> Optional[Dict[str, Any]]:
        # 先判合法再压撤销快照：不合法就什么都没发生，撤销栈里不该多一步空操作
        if marker_utils.normalize({"time": time, "type": marker_type, "label": label}) is None:
            self.logMessage.emit(f"标记时间不合法：{time}")
            return None
        self._begin("添加标记")
        marker = marker_utils.add_marker(self._timeline, time, marker_type, label)
        self.logMessage.emit(
            f"标记 {marker_utils.type_label(marker['type'])} @ {marker['time']}s"
            + (f"（{marker.get('label')}）" if marker.get("label") else "")
        )
        self._commit(structural=True)
        return marker

    def remove_marker_at(self, time: float) -> Optional[Dict[str, Any]]:
        probe = copy.deepcopy(self._timeline)
        if marker_utils.remove_marker_at(probe, time) is None:
            self.logMessage.emit(f"{round(float(time), 3)}s 附近没有标记")
            return None
        self._begin("删除标记")
        removed = marker_utils.remove_marker_at(self._timeline, time)
        self.logMessage.emit(f"删除标记 @ {removed['time']}s")
        self._commit(structural=True)
        return removed

    def clear_markers(self) -> None:
        self._begin("清空标记")
        marker_utils.set_markers(self._timeline, [])
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
        self.logMessage.emit(
            f"删除 {len(targets)} 个元素，级联清理后共 {len(removed)} 个：{sorted(removed)}"
        )
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

    def move_element(
        self,
        element_id: str,
        new_start: float,
        new_track: Optional[str] = None,
    ) -> None:
        """拖动元素：改开始时间，可选换轨道。"""
        element = tl.get_element(self._timeline, element_id)
        if element is None:
            return
        new_start = max(0.0, snap_to_frame(new_start, self.fps))
        target_track = new_track or element.get("track")
        old_seconds = tl.as_seconds(element.get("start"))
        if abs(new_start - old_seconds) < 1e-9 and target_track == element.get("track"):
            return
        self._begin("移动元素")
        old_start = element.get("start")
        old_track = element.get("track")
        # caption_group 的 words 是绝对时间，整体平移时必须同步搬走
        if element.get("type") == "caption_group":
            delta = new_start - old_seconds
            for word in (element.get("content") or {}).get("words", []):
                word["start"] = round(tl.as_seconds(word.get("start")) + delta, 3)
                word["end"] = round(tl.as_seconds(word.get("end")) + delta, 3)
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
        old_start = tl.as_seconds(element.get("start"))
        old_duration = tl.as_seconds(element.get("duration"))
        source = element.get("source")
        if isinstance(source, dict) and element.get("type") in ("video", "audio"):
            speed = tl.effective_speed(element)
            # 左边缘移动 -> 源起点同步移动；右边缘 -> 源终点同步
            head_delta = (new_start - old_start) * speed
            src_start = max(0.0, tl.as_seconds(source.get("start")) + head_delta)
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
        self._resync_media_duration(element, path[0] if path else "")
        self.logMessage.emit(f"{element_id} {'.'.join(path)}：{old} → {value}")
        self._commit(structural=True)

    def update_element(
        self,
        element_id: str,
        fields: Dict[str, Any],
        description: str = "",
    ) -> bool:
        """一次改多个顶层字段，只压一次撤销记录。元素不存在时返回 False。"""
        element = tl.get_element(self._timeline, element_id)
        if element is None or not isinstance(fields, dict):
            return False
        self._begin(description or f"修改元素 {element_id}")
        for key, value in fields.items():
            element[key] = value
            self._resync_media_duration(element, key)
        self.logMessage.emit(f"{element_id} 批量修改 {sorted(fields)}")
        self._commit(structural=True)
        return True

    def _resync_media_duration(self, element: Dict[str, Any], changed_key: str) -> None:
        """视频 / 音频改速度或源区间后重算成片时长，否则 JSON 自相矛盾。"""
        if element.get("type") not in ("video", "audio"):
            return
        if changed_key not in ("speed", "source"):
            return
        source = element.get("source")
        if not isinstance(source, dict):
            return
        speed = tl.effective_speed(element)
        span = tl.as_seconds(source.get("end")) - tl.as_seconds(source.get("start"))
        if span > 0:
            element["duration"] = round(max(1.0 / self.fps, span / speed), 3)

    # ------------------------------------------------------------ 特效

    def add_effect(
        self,
        name: str,
        params: Optional[Dict[str, Any]] = None,
        start: float = 0.0,
        duration: float = 0.6,
        target: Optional[str] = None,
        easing: str = "easeInOut",
        track: str = "V1",
    ) -> str:
        """添加程序特效。素材特效走 make_overlay（type=overlay），两者 type 不同。"""
        host = tl.get_element(self._timeline, target or "") or {}
        element = tl.make_effect(
            tl.next_element_id(self._timeline, "effect"),
            name,
            params or {},
            track=host.get("track") or track,
            start=start,
            duration=duration,
            target=target,
            easing=easing,
        )
        return self.add_element(element, f"添加特效 {name}")

    def effects(self, target: Optional[str] = None) -> List[Dict[str, Any]]:
        """所有程序特效；给了 target 就只返回作用在它身上的。"""
        result = [e for e in self.elements() if e.get("type") == "effect"]
        if target is None:
            return result
        return [e for e in result if e.get("target") == target]

    def remove_effect(self, element_id: str) -> bool:
        """按 id 删特效。id 指向的不是特效时什么都不做并返回 False。"""
        element = tl.get_element(self._timeline, element_id)
        if element is None or element.get("type") != "effect":
            return False
        self.remove_element(element_id)
        return True

    # ------------------------------------------------------------ 转场

    def add_transition(
        self,
        name: str,
        from_id: str,
        to_id: str,
        start: float,
        duration: float,
        params: Optional[Dict[str, Any]] = None,
        track: str = "V1",
    ) -> str:
        """添加转场。必须绑定 from / to 两个 Video Clip。"""
        host = tl.get_element(self._timeline, from_id) or {}
        element = tl.make_transition(
            tl.next_element_id(self._timeline, "transition"),
            name,
            from_id,
            to_id,
            start,
            duration,
            params or {},
            track=host.get("track") or track,
        )
        return self.add_element(element, f"插入转场 {name}")

    def transitions(self) -> List[Dict[str, Any]]:
        return [e for e in self.elements() if e.get("type") == "transition"]

    def remove_transition(self, element_id: str) -> bool:
        """按 id 删转场。id 指向的不是转场时什么都不做并返回 False。"""
        element = tl.get_element(self._timeline, element_id)
        if element is None or element.get("type") != "transition":
            return False
        self.remove_element(element_id)
        return True

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
            if abs(tl.as_seconds(kf.get("time")) - local_time) < 1e-6:
                kf["value"] = value
                kf["easing"] = easing
                break
        else:
            keyframes.append({"time": local_time, "value": value, "easing": easing})
        keyframes.sort(key=lambda k: tl.as_seconds(k.get("time")))
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
        # 最后一条曲线也删完了，keyframes 字段就没有存在意义（稀疏化第六条）
        if not element.get("keyframes"):
            element.pop("keyframes", None)
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
        keyframes.sort(key=lambda k: tl.as_seconds(k.get("time")))
        self.logMessage.emit(f"{element_id} 关键帧 {param}[{index}] 更新为 {keyframes[index]}")
        self._commit(structural=True)

    def apply_animation(self, element_id: str, animation: Dict[str, Any]) -> None:
        """把动画库里的关键帧模板套到元素上（会覆盖同名参数的既有关键帧）。"""
        element = tl.get_element(self._timeline, element_id)
        if element is None:
            return
        self._begin(f"应用动画 {animation.get('label', animation.get('id'))}")
        duration = tl.as_seconds(animation.get("duration")) or 0.3
        element.setdefault("keyframes", {})
        for param, points in (animation.get("keyframes") or {}).items():
            if param not in tl.KEYFRAME_PARAMS:
                continue
            element["keyframes"][param] = copy.deepcopy(points)
        if not element.get("keyframes"):
            element.pop("keyframes", None)
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
            f"轨道 {track_id} 顺序 {index} → {target}，"
            f"Z-Index 变为 {tl.track_z_index(self._timeline, track_id)}"
        )
        self._commit(structural=True)

    def is_track_locked(self, track_id: str) -> bool:
        track = tl.get_track(self._timeline, track_id)
        return bool(track and track.get("locked"))
