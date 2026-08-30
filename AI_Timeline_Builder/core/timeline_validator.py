"""Timeline 规则引擎 / 校验器。

schemas/rules.json 声明规则，本模块实现规则。两者靠 rule id 对应。
校验结果统一为 Issue 列表，GUI 用它把非法元素标红，导出前也用它拦截。

如果环境里装了 jsonschema，会额外跑一遍 timeline_schema.json 的结构校验；
没装也不影响，业务规则完全由本模块自己实现。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core import timeline as tl

try:  # jsonschema 是可选依赖
    import jsonschema  # type: ignore

    HAS_JSONSCHEMA = True
except ImportError:  # pragma: no cover
    jsonschema = None  # type: ignore
    HAS_JSONSCHEMA = False


@dataclass
class Issue:
    """一条校验问题。"""

    rule_id: str
    level: str  # error / warning
    message: str
    element_id: str = ""
    path: List[str] = field(default_factory=list)

    def is_error(self) -> bool:
        return self.level == "error"

    def display(self) -> str:
        where = f"[{self.element_id}] " if self.element_id else ""
        tag = "错误" if self.is_error() else "警告"
        return f"{tag} {self.rule_id} {where}{self.message}"


class TimelineValidator:
    """按 rules.json 校验 Timeline JSON。"""

    def __init__(self, schemas_dir: str, asset_manager=None, libraries=None) -> None:
        self._schemas_dir = schemas_dir
        self._assets = asset_manager
        self._libraries = libraries or {}
        self._rules: Dict[str, Dict[str, Any]] = {}
        self._keyframe_params: List[str] = list(tl.KEYFRAME_PARAMS)
        self._easings: List[str] = list(tl.EASINGS)
        self._schema: Optional[Dict[str, Any]] = None
        self._load_rules()
        self._load_schema()

    # ------------------------------------------------------------ 加载配置

    def _load_rules(self) -> None:
        path = os.path.join(self._schemas_dir, "rules.json")
        if not os.path.isfile(path):
            return
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        for rule in data.get("rules", []):
            self._rules[rule["id"]] = rule
        self._keyframe_params = data.get("keyframe_params", self._keyframe_params)
        self._easings = data.get("easings", self._easings)

    def _load_schema(self) -> None:
        path = os.path.join(self._schemas_dir, "timeline_schema.json")
        if not os.path.isfile(path):
            return
        with open(path, "r", encoding="utf-8") as handle:
            self._schema = json.load(handle)

    def _level(self, rule_id: str) -> str:
        return self._rules.get(rule_id, {}).get("level", "error")

    def rule_description(self, rule_id: str) -> str:
        return self._rules.get(rule_id, {}).get("description", "")

    def all_rules(self) -> List[Dict[str, Any]]:
        return list(self._rules.values())

    # ------------------------------------------------------------ 主入口

    def validate(self, timeline: Dict[str, Any]) -> List[Issue]:
        """返回所有问题。空列表表示完全合规。"""
        issues: List[Issue] = []
        issues.extend(self._validate_schema(timeline))
        issues.extend(self._validate_global(timeline))

        track_ids = {t.get("id") for t in timeline.get("tracks", [])}
        elements = timeline.get("elements", [])
        by_id = {e.get("id"): e for e in elements}

        issues.extend(self._validate_unique_ids(elements))

        for element in elements:
            issues.extend(self._validate_common(element, track_ids, timeline))
            etype = element.get("type")
            if etype == "video":
                issues.extend(self._validate_video(element))
            elif etype == "overlay":
                issues.extend(self._validate_asset_ref(element))
            elif etype == "audio":
                issues.extend(self._validate_audio(element))
            elif etype == "text":
                issues.extend(self._validate_text(element))
            elif etype in ("caption", "caption_group"):
                issues.extend(self._validate_caption(element))
            elif etype == "effect":
                issues.extend(self._validate_effect(element, by_id))
            elif etype == "transition":
                issues.extend(self._validate_transition(element, by_id))
            elif etype == "freeze":
                issues.extend(self._validate_freeze(element, by_id))
            issues.extend(self._validate_keyframes(element))
            issues.extend(self._validate_transform(element))

        return issues

    def errors_only(self, timeline: Dict[str, Any]) -> List[Issue]:
        return [i for i in self.validate(timeline) if i.is_error()]

    def invalid_element_ids(self, timeline: Dict[str, Any]) -> Dict[str, str]:
        """返回 {元素 id: 最高严重级别}，供 Timeline 标红 / 标黄。"""
        result: Dict[str, str] = {}
        for issue in self.validate(timeline):
            if not issue.element_id:
                continue
            if result.get(issue.element_id) == "error":
                continue
            result[issue.element_id] = issue.level
        return result

    # ------------------------------------------------------------ 各类规则

    def _validate_schema(self, timeline: Dict[str, Any]) -> List[Issue]:
        if not (HAS_JSONSCHEMA and self._schema):
            return []
        issues: List[Issue] = []
        validator = jsonschema.Draft7Validator(self._schema)  # type: ignore
        for error in validator.iter_errors(timeline):
            path = [str(p) for p in error.absolute_path]
            issues.append(
                Issue(
                    rule_id="SCHEMA",
                    level="error",
                    message=f"结构不符合 timeline_schema.json：{error.message}（位置 {'/'.join(path) or '根'}）",
                    path=path,
                )
            )
        return issues

    def _validate_global(self, timeline: Dict[str, Any]) -> List[Issue]:
        issues: List[Issue] = []
        if timeline.get("time_unit") != "seconds":
            issues.append(
                Issue("RULE_TIME_001", self._level("RULE_TIME_001"), "time_unit 必须为 seconds")
            )
        for element in timeline.get("elements", []):
            for key in element.keys():
                # keyframes 是关键帧容器，里面的 time 依旧是秒，不算帧字段
                if key == "keyframes":
                    continue
                if "frame" in key.lower():
                    issues.append(
                        Issue(
                            "RULE_TIME_001",
                            self._level("RULE_TIME_001"),
                            f"禁止出现帧字段 {key}，所有时间必须用秒",
                            element.get("id", ""),
                            [key],
                        )
                    )
        return issues

    def _validate_unique_ids(self, elements: List[Dict[str, Any]]) -> List[Issue]:
        seen: Dict[str, int] = {}
        issues: List[Issue] = []
        for element in elements:
            element_id = element.get("id", "")
            seen[element_id] = seen.get(element_id, 0) + 1
        for element_id, count in seen.items():
            if count > 1:
                issues.append(
                    Issue(
                        "RULE_ID_001",
                        self._level("RULE_ID_001"),
                        f"元素 id 重复出现 {count} 次",
                        element_id,
                        ["id"],
                    )
                )
        return issues

    def _validate_common(
        self,
        element: Dict[str, Any],
        track_ids: set,
        timeline: Dict[str, Any],
    ) -> List[Issue]:
        issues: List[Issue] = []
        element_id = element.get("id", "")
        start = float(element.get("start", 0.0))
        duration = float(element.get("duration", 0.0))

        if start < 0:
            issues.append(
                Issue("RULE_TIME_002", self._level("RULE_TIME_002"), f"start={start} 不得小于 0", element_id, ["start"])
            )
        if duration <= 0:
            issues.append(
                Issue(
                    "RULE_VIDEO_002",
                    self._level("RULE_VIDEO_002"),
                    f"duration={duration} 必须大于 0",
                    element_id,
                    ["duration"],
                )
            )

        track_id = element.get("track")
        if track_id and track_id not in track_ids:
            issues.append(
                Issue(
                    "RULE_TRACK_001",
                    self._level("RULE_TRACK_001"),
                    f"引用了不存在的轨道 {track_id}",
                    element_id,
                    ["track"],
                )
            )
        else:
            expected = tl.TYPE_TRACK_KIND.get(element.get("type", ""))
            track = tl.get_track(timeline, track_id) if track_id else None
            if expected and track and track.get("kind") != expected:
                issues.append(
                    Issue(
                        "RULE_TRACK_002",
                        self._level("RULE_TRACK_002"),
                        f"{tl.ELEMENT_TYPE_LABELS.get(element.get('type'), '元素')}"
                        f"应放在 {expected} 类轨道，当前轨道 {track_id} 是 {track.get('kind')}",
                        element_id,
                        ["track"],
                    )
                )
        return issues

    def _validate_asset_ref(self, element: Dict[str, Any]) -> List[Issue]:
        issues: List[Issue] = []
        asset_id = element.get("asset")
        element_id = element.get("id", "")
        if not asset_id:
            issues.append(
                Issue("RULE_ASSET_001", self._level("RULE_ASSET_001"), "缺少 asset 引用", element_id, ["asset"])
            )
            return issues
        if self._assets is None:
            return issues
        asset = self._assets.get(asset_id)
        if asset is None:
            issues.append(
                Issue(
                    "RULE_ASSET_001",
                    self._level("RULE_ASSET_001"),
                    f"asset {asset_id} 不存在于素材库",
                    element_id,
                    ["asset"],
                )
            )
        elif not self._assets.file_exists(asset_id):
            issues.append(
                Issue(
                    "RULE_ASSET_002",
                    self._level("RULE_ASSET_002"),
                    f"asset {asset_id} 指向的文件在磁盘上找不到：{asset.get('path')}",
                    element_id,
                    ["asset"],
                )
            )
        return issues

    def _validate_video(self, element: Dict[str, Any]) -> List[Issue]:
        issues = self._validate_asset_ref(element)
        element_id = element.get("id", "")
        source = element.get("source") or {}
        src_start = float(source.get("start", 0.0))
        src_end = float(source.get("end", 0.0))

        if src_start >= src_end:
            issues.append(
                Issue(
                    "RULE_VIDEO_003",
                    self._level("RULE_VIDEO_003"),
                    f"source.start={src_start} 必须小于 source.end={src_end}",
                    element_id,
                    ["source"],
                )
            )

        if self._assets is not None:
            asset = self._assets.get(element.get("asset", ""))
            if asset and asset.get("duration"):
                media_duration = float(asset["duration"])
                if src_end > media_duration + 0.05:
                    issues.append(
                        Issue(
                            "RULE_VIDEO_001",
                            self._level("RULE_VIDEO_001"),
                            f"source.end={src_end}s 超过源视频长度 {media_duration}s",
                            element_id,
                            ["source", "end"],
                        )
                    )

        speed = float(element.get("speed", 1.0) or 1.0)
        duration = float(element.get("duration", 0.0))
        expected = (src_end - src_start) / speed if speed else 0.0
        if expected > 0 and abs(expected - duration) > 0.05:
            issues.append(
                Issue(
                    "RULE_VIDEO_004",
                    self._level("RULE_VIDEO_004"),
                    f"duration={duration}s 与 (source 区间 {src_end - src_start:.3f}s / speed {speed}) "
                    f"= {expected:.3f}s 不一致",
                    element_id,
                    ["duration"],
                )
            )
        return issues

    def _validate_audio(self, element: Dict[str, Any]) -> List[Issue]:
        issues = self._validate_asset_ref(element)
        element_id = element.get("id", "")
        volume = float(element.get("volume", 1.0))
        if not 0 <= volume <= 4:
            issues.append(
                Issue(
                    "RULE_AUDIO_001",
                    self._level("RULE_AUDIO_001"),
                    f"volume={volume} 必须在 0 到 4 之间",
                    element_id,
                    ["volume"],
                )
            )
        fade = element.get("fade") or {}
        fade_in = float(fade.get("in", 0.0))
        fade_out = float(fade.get("out", 0.0))
        if fade_in < 0 or fade_out < 0:
            issues.append(
                Issue(
                    "RULE_AUDIO_001",
                    self._level("RULE_AUDIO_001"),
                    f"fade 不得为负：in={fade_in} out={fade_out}",
                    element_id,
                    ["fade"],
                )
            )
        duration = float(element.get("duration", 0.0))
        if duration > 0 and fade_in + fade_out > duration + 1e-6:
            issues.append(
                Issue(
                    "RULE_AUDIO_002",
                    self._level("RULE_AUDIO_002"),
                    f"fade.in + fade.out = {fade_in + fade_out}s 超过 duration {duration}s",
                    element_id,
                    ["fade"],
                )
            )
        return issues

    def _validate_text(self, element: Dict[str, Any]) -> List[Issue]:
        text = (element.get("content") or {}).get("text", "")
        if not str(text).strip():
            return [
                Issue(
                    "RULE_TEXT_001",
                    self._level("RULE_TEXT_001"),
                    "Text 的 content.text 不得为空",
                    element.get("id", ""),
                    ["content", "text"],
                )
            ]
        return []

    def _validate_caption(self, element: Dict[str, Any]) -> List[Issue]:
        issues: List[Issue] = []
        element_id = element.get("id", "")
        content = element.get("content") or {}
        text = str(content.get("text", "")).strip()
        words = content.get("words") or []
        if not text and not words:
            issues.append(
                Issue(
                    "RULE_CAPTION_001",
                    self._level("RULE_CAPTION_001"),
                    "Caption 必须存在 text 或 words",
                    element_id,
                    ["content"],
                )
            )
        previous_end: Optional[float] = None
        for index, word in enumerate(words):
            start = float(word.get("start", 0.0))
            end = float(word.get("end", 0.0))
            if start >= end:
                issues.append(
                    Issue(
                        "RULE_CAPTION_002",
                        self._level("RULE_CAPTION_002"),
                        f"第 {index + 1} 个词「{word.get('text')}」的 start={start} 不小于 end={end}",
                        element_id,
                        ["content", "words", str(index)],
                    )
                )
            if previous_end is not None and start < previous_end - 1e-6:
                issues.append(
                    Issue(
                        "RULE_CAPTION_002",
                        self._level("RULE_CAPTION_002"),
                        f"第 {index + 1} 个词「{word.get('text')}」start={start} 与前一个词 end={previous_end} 重叠",
                        element_id,
                        ["content", "words", str(index)],
                    )
                )
            previous_end = end
        return issues

    def _validate_effect(self, element: Dict[str, Any], by_id: Dict[str, Any]) -> List[Issue]:
        issues: List[Issue] = []
        element_id = element.get("id", "")
        name = element.get("name", "")
        library = self._libraries.get("effect")
        if library is not None and not library.has(name):
            issues.append(
                Issue(
                    "RULE_EFFECT_001",
                    self._level("RULE_EFFECT_001"),
                    f"特效 {name} 不在 Effect Library 中",
                    element_id,
                    ["name"],
                )
            )
        target = element.get("target")
        if target and target not in by_id:
            issues.append(
                Issue(
                    "RULE_EFFECT_002",
                    self._level("RULE_EFFECT_002"),
                    f"target {target} 指向的元素不存在",
                    element_id,
                    ["target"],
                )
            )
        return issues

    def _validate_transition(self, element: Dict[str, Any], by_id: Dict[str, Any]) -> List[Issue]:
        issues: List[Issue] = []
        element_id = element.get("id", "")
        from_id = element.get("from")
        to_id = element.get("to")

        for key, value in (("from", from_id), ("to", to_id)):
            target = by_id.get(value) if value else None
            if target is None:
                issues.append(
                    Issue(
                        "RULE_TRANSITION_001",
                        self._level("RULE_TRANSITION_001"),
                        f"{key}={value} 找不到对应元素",
                        element_id,
                        [key],
                    )
                )
            elif target.get("type") not in ("video", "freeze"):
                issues.append(
                    Issue(
                        "RULE_TRANSITION_001",
                        self._level("RULE_TRANSITION_001"),
                        f"{key}={value} 不是 Video Clip（实际类型 {target.get('type')}）",
                        element_id,
                        [key],
                    )
                )

        if from_id and from_id == to_id:
            issues.append(
                Issue(
                    "RULE_TRANSITION_002",
                    self._level("RULE_TRANSITION_002"),
                    "from 与 to 不得为同一个 Clip",
                    element_id,
                    ["to"],
                )
            )

        duration = float(element.get("duration", 0.0))
        for key in ("from", "to"):
            neighbour = by_id.get(element.get(key) or "")
            if neighbour and duration > float(neighbour.get("duration", 0.0)) / 2 + 1e-6:
                issues.append(
                    Issue(
                        "RULE_TRANSITION_003",
                        self._level("RULE_TRANSITION_003"),
                        f"转场时长 {duration}s 超过 {key} 片段 {neighbour.get('id')} "
                        f"时长 {neighbour.get('duration')}s 的一半",
                        element_id,
                        ["duration"],
                    )
                )
        return issues

    def _validate_freeze(self, element: Dict[str, Any], by_id: Dict[str, Any]) -> List[Issue]:
        issues: List[Issue] = []
        element_id = element.get("id", "")
        target_id = element.get("target")
        target = by_id.get(target_id) if target_id else None
        if target is None or target.get("type") != "video":
            issues.append(
                Issue(
                    "RULE_FREEZE_001",
                    self._level("RULE_FREEZE_001"),
                    f"target={target_id} 必须指向一个已存在的 Video Clip",
                    element_id,
                    ["target"],
                )
            )
            return issues
        source = target.get("source") or {}
        src_start = float(source.get("start", 0.0))
        src_end = float(source.get("end", 0.0))
        source_time = float(element.get("source_time", 0.0))
        if not (src_start - 1e-6 <= source_time <= src_end + 1e-6):
            issues.append(
                Issue(
                    "RULE_FREEZE_002",
                    self._level("RULE_FREEZE_002"),
                    f"source_time={source_time}s 不在目标片段源区间 [{src_start}, {src_end}] 内",
                    element_id,
                    ["source_time"],
                )
            )
        return issues

    def _validate_keyframes(self, element: Dict[str, Any]) -> List[Issue]:
        issues: List[Issue] = []
        element_id = element.get("id", "")
        duration = float(element.get("duration", 0.0))
        for param, points in (element.get("keyframes") or {}).items():
            if param not in self._keyframe_params:
                issues.append(
                    Issue(
                        "RULE_KEYFRAME_002",
                        self._level("RULE_KEYFRAME_002"),
                        f"关键帧参数 {param} 不在允许列表 {self._keyframe_params} 内",
                        element_id,
                        ["keyframes", param],
                    )
                )
                continue
            previous: Optional[float] = None
            for index, point in enumerate(points):
                time_value = float(point.get("time", 0.0))
                if previous is not None and time_value < previous - 1e-6:
                    issues.append(
                        Issue(
                            "RULE_KEYFRAME_001",
                            self._level("RULE_KEYFRAME_001"),
                            f"{param} 第 {index + 1} 个关键帧时间 {time_value}s 小于前一个 {previous}s",
                            element_id,
                            ["keyframes", param, str(index)],
                        )
                    )
                if duration > 0 and time_value > duration + 1e-6:
                    issues.append(
                        Issue(
                            "RULE_KEYFRAME_001",
                            self._level("RULE_KEYFRAME_001"),
                            f"{param} 关键帧时间 {time_value}s 超出元素 duration {duration}s",
                            element_id,
                            ["keyframes", param, str(index)],
                        )
                    )
                easing = point.get("easing", "linear")
                if easing not in self._easings:
                    issues.append(
                        Issue(
                            "RULE_KEYFRAME_002",
                            self._level("RULE_KEYFRAME_002"),
                            f"{param} 关键帧 easing={easing} 不在 {self._easings} 内",
                            element_id,
                            ["keyframes", param, str(index)],
                        )
                    )
                previous = time_value
        return issues

    def _validate_transform(self, element: Dict[str, Any]) -> List[Issue]:
        transform = element.get("transform")
        if not transform:
            return []
        issues: List[Issue] = []
        element_id = element.get("id", "")
        opacity = float(transform.get("opacity", 1.0))
        scale = float(transform.get("scale", 1.0))
        if not 0 <= opacity <= 1:
            issues.append(
                Issue(
                    "RULE_TRANSFORM_001",
                    self._level("RULE_TRANSFORM_001"),
                    f"opacity={opacity} 必须在 0 到 1 之间",
                    element_id,
                    ["transform", "opacity"],
                )
            )
        if scale <= 0:
            issues.append(
                Issue(
                    "RULE_TRANSFORM_001",
                    self._level("RULE_TRANSFORM_001"),
                    f"scale={scale} 必须大于 0",
                    element_id,
                    ["transform", "scale"],
                )
            )
        return issues
