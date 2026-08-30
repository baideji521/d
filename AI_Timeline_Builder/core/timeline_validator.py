"""Timeline 规则引擎 / 校验器。

schemas/rules.json 声明规则，本模块实现规则。两者靠 rule id 对应。
校验结果统一为 Issue 列表，GUI 用它把非法元素标红，导出前也用它拦截。

结构分两层（指令第二十八条）：
1. Schema 层 —— jsonschema 跑 timeline_schema.json（v1）或 timeline_schema_v2.json（v2），
   管字段 / 类型 / required / enum / 数值范围 / 整体结构。
2. 语义层 —— 本模块自己实现，管引用是否存在、时间关系是否成立、素材长度够不够。

Schema 层是语义层的门禁：结构不对就直接返回，不再往下跑脏数据。
如果环境里没装 jsonschema，第 1 层会整体跳过（HAS_JSONSCHEMA=False），
此时「0 问题」只代表语义层通过，不代表结构合规 —— 所以 requirements.txt 把它列为必装。
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core import timeline as tl
from core.migrations import detect_version, migrate_to_v1

try:  # jsonschema 是可选依赖
    import jsonschema  # type: ignore

    HAS_JSONSCHEMA = True
except ImportError:  # pragma: no cover
    jsonschema = None  # type: ignore
    HAS_JSONSCHEMA = False


#: 单个元素的时间上界（秒）。24 小时以外的时长在这个工具里只可能是脏数据，
#: 放过去会让 Runtime 算出天文数字的帧数，渲染任务永远不结束。
MAX_TIMELINE_SECONDS = 86400.0


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
        self._schema_v2: Optional[Dict[str, Any]] = None
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
        """v1 与 v2 各一份 schema，按文档里的 version 选用。"""
        self._schema = self._read_schema("timeline_schema.json")
        self._schema_v2 = self._read_schema("timeline_schema_v2.json")

    def _read_schema(self, filename: str) -> Optional[Dict[str, Any]]:
        path = os.path.join(self._schemas_dir, filename)
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def schema_for(self, timeline: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self._schema_v2 if detect_version(timeline) >= 2 else self._schema


    def _level(self, rule_id: str) -> str:
        return self._rules.get(rule_id, {}).get("level", "error")

    def rule_description(self, rule_id: str) -> str:
        return self._rules.get(rule_id, {}).get("description", "")

    def all_rules(self) -> List[Dict[str, Any]]:
        return list(self._rules.values())

    # ------------------------------------------------------------ 主入口

    def validate(self, timeline: Dict[str, Any]) -> List[Issue]:
        """返回所有问题。空列表表示完全合规。

        两层结构（指令第二十八条）：

            Schema 层  字段 / 类型 / required / enum / 范围 / 结构
                ↓ 通过才继续
            语义层    引用是否存在、时间关系是否成立、素材长度够不够

        Schema 层是语义层的前置门禁。否则 start="十秒" 这类脏数据会让
        float() 抛 ValueError，JSON 面板里粘一段坏 JSON 就会崩，
        而不是给出可读的校验错误。

        v2 文档也走同一个入口：Schema 用 v2 那份，语义检查在降级成 v1 视图后进行，
        避免两套版本各写一遍规则。元素 id 在迁移中保持不变，所以错误定位不受影响。
        """
        # NaN / Infinity 能过 JSON Schema 的 "type": "number"，但 NaN 的任何比较都是
        # False，会让后面所有范围检查静默失效，最后在渲染时变成 NaN 帧数。
        # 放在 Schema 之前：-Infinity 会先撞上 minimum 而被报成普通的范围错误，
        # 真因（非有限数字）就被盖住了，修的人只会去改数值而不是去查数据来源。
        number_issues = self._validate_finite_numbers(timeline)
        if number_issues:
            return number_issues

        schema_issues = self._validate_schema(timeline)
        if schema_issues:
            return schema_issues


        if detect_version(timeline) >= 2:
            timeline = migrate_to_v1(timeline)

        issues: List[Issue] = []
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

    def validate_report(self, timeline: Dict[str, Any]) -> Dict[str, Any]:
        """结构化校验报告（指令第二十九条的形状）。

        任何输入都不会抛异常：脏 JSON 会被 Schema 层拦成 errors，
        连 dict 都不是的输入直接给一条 SCHEMA 错误。GUI 与未来的 AI
        都靠这个返回值决定"能不能渲染"。
        """
        if not isinstance(timeline, dict):
            return {
                "valid": False,
                "version": 0,
                "errors": [
                    {
                        "rule": "SCHEMA",
                        "element": "",
                        "path": [],
                        "message": f"Timeline 必须是 JSON 对象，收到 {type(timeline).__name__}",
                    }
                ],
                "warnings": [],
            }

        issues = self.validate(timeline)
        errors = [self._as_dict(i) for i in issues if i.is_error()]
        warnings = [self._as_dict(i) for i in issues if not i.is_error()]
        return {
            "valid": not errors,
            "version": detect_version(timeline),
            "errors": errors,
            "warnings": warnings,
        }

    @staticmethod
    def _as_dict(issue: Issue) -> Dict[str, Any]:
        return {
            "rule": issue.rule_id,
            "element": issue.element_id,
            "path": list(issue.path),
            "message": issue.message,
        }


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
        schema = self.schema_for(timeline)
        if not (HAS_JSONSCHEMA and schema):
            return []
        issues: List[Issue] = []
        validator = jsonschema.Draft7Validator(schema)  # type: ignore
        schema_name = "timeline_schema_v2.json" if detect_version(timeline) >= 2 else "timeline_schema.json"
        for error in validator.iter_errors(timeline):
            path = [str(p) for p in error.absolute_path]
            issues.append(
                Issue(
                    rule_id="SCHEMA",
                    level="error",
                    message=f"结构不符合 {schema_name}：{error.message}（位置 {'/'.join(path) or '根'}）",
                    element_id=self._element_id_at(timeline, error.absolute_path),
                    path=path,
                )
            )
        return issues


    @staticmethod
    def _element_id_at(timeline: Dict[str, Any], absolute_path) -> str:
        """从 jsonschema 的错误路径反查元素 id，让 Timeline 面板还能标红。

        路径形如 ['elements', 3, 'transform', 'scale']，取下标去 elements 里找。
        """
        parts = list(absolute_path)
        if len(parts) < 2 or parts[0] != "elements" or not isinstance(parts[1], int):
            return ""
        elements = timeline.get("elements", [])
        if 0 <= parts[1] < len(elements):
            return str(elements[parts[1]].get("id", ""))
        return ""


    def _validate_finite_numbers(self, timeline: Dict[str, Any]) -> List[Issue]:
        """整份文档不允许出现 NaN / Infinity。

        `json.loads` 会把 `NaN` / `Infinity` 解析成 Python 的 float 特殊值，
        JSON Schema 的 `"type": "number"` 也照收。但 NaN 参与的比较恒为 False，
        `duration > 0`、`start + duration <= total` 这类检查会全部静默通过，
        最后在 Runtime 里变成 NaN 帧数。所以必须单独拦。
        """
        issues: List[Issue] = []

        def walk(node: Any, path: List[str], element_id: str) -> None:
            if isinstance(node, dict):
                current_id = str(node.get("id", element_id)) if "type" in node else element_id
                for key, value in node.items():
                    walk(value, path + [str(key)], current_id)
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, path + [str(index)], element_id)
            elif isinstance(node, float) and not math.isfinite(node):
                issues.append(
                    Issue(
                        "RULE_NUMBER_001",
                        self._level("RULE_NUMBER_001"),
                        f"{'.'.join(path)} = {node} 不是有限数字，禁止 NaN / Infinity",
                        element_id,
                        path,
                    )
                )

        walk(timeline, [], "")
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
        # 上界同样要拦：duration=1e18 能过 Schema 的 minimum，也过 RULE_VIDEO_004 的
        # 「超出素材长度」警告，但送进 Runtime 会算出 3e19 帧 —— 渲染任务永远跑不完。
        for field, value in (("start", start), ("duration", duration)):
            if value > MAX_TIMELINE_SECONDS:
                issues.append(
                    Issue(
                        "RULE_TIME_003",
                        self._level("RULE_TIME_003"),
                        f"{field}={value} 超过上限 {MAX_TIMELINE_SECONDS} 秒（24 小时），"
                        "这种时长渲染不出来",
                        element_id,
                        [field],
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
        elif not track_id and element.get("type") in tl.TYPE_TRACK_KIND:
            # 需要落轨的元素没写 track：时间轴上画不出来、Z 序也没有依据，
            # 元素会在编辑器里「凭空消失」。Runtime 仍能渲染，所以只报警告。
            issues.append(
                Issue(
                    "RULE_TRACK_003",
                    self._level("RULE_TRACK_003"),
                    f"{tl.ELEMENT_TYPE_LABELS.get(element.get('type'), '元素')}"
                    "没有 track，时间轴上无法显示",
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
        """Effect 的语义校验，全部委托给 EffectRegistry。

        这里只做「把 Registry 的结构化结果翻译成 Issue」，
        不自己判断参数范围 —— 那份知识只应该存在于 Registry 一处。
        """
        issues: List[Issue] = []
        element_id = element.get("id", "")
        name = element.get("name", "")
        registry = self._libraries.get("effect")
        if registry is None:
            return issues

        definition = registry.get(name)
        if definition is None:
            issues.append(
                Issue(
                    "RULE_EFFECT_001",
                    self._level("RULE_EFFECT_001"),
                    f"特效 {name} 未在 EffectRegistry 注册（UNKNOWN_EFFECT）",
                    element_id,
                    ["name"],
                )
            )
            # 名字都不认识，后面的参数与 target 校验没有依据，直接停在这
            return issues

        if definition.element_type != "effect":
            issues.append(
                Issue(
                    "RULE_EFFECT_006",
                    self._level("RULE_EFFECT_006"),
                    f"{name} 是素材特效，必须写成 type=overlay 元素，不能作为 type=effect",
                    element_id,
                    ["name"],
                )
            )
            return issues

        target = element.get("target")
        if target:
            target_element = by_id.get(target)
            if target_element is None:
                issues.append(
                    Issue(
                        "RULE_EFFECT_002",
                        self._level("RULE_EFFECT_002"),
                        f"target {target} 指向的元素不存在",
                        element_id,
                        ["target"],
                    )
                )
            else:
                target_type = str(target_element.get("type", ""))
                report = registry.validate_target(name, target_type)
                for error in report["errors"]:
                    issues.append(
                        Issue(
                            "RULE_EFFECT_003",
                            self._level("RULE_EFFECT_003"),
                            error["message"],
                            element_id,
                            ["target"],
                        )
                    )

        params_report = registry.validate(name, element.get("params"))
        for error in params_report["errors"]:
            issues.append(
                Issue(
                    "RULE_EFFECT_004",
                    self._level("RULE_EFFECT_004"),
                    error["message"],
                    element_id,
                    ["params", error["parameter"]] if error["parameter"] else ["params"],
                )
            )
        for warning in params_report["warnings"]:
            # MISSING_PARAMETER 不上报：Runtime 会补默认值（指令第十七条），
            # 每个缺省参数都告警只会把真正的问题淹掉。
            if warning["code"] != "UNKNOWN_PARAMETER":
                continue
            issues.append(
                Issue(
                    "RULE_EFFECT_005",
                    self._level("RULE_EFFECT_005"),
                    warning["message"],
                    element_id,
                    ["params", warning["parameter"]],
                )
            )
        return issues

    def _validate_transition(self, element: Dict[str, Any], by_id: Dict[str, Any]) -> List[Issue]:
        """Transition 的语义校验。

        name / params / 两侧类型全部委托给 TransitionRegistry ——
        「哪些转场存在、参数什么范围、两侧能是什么类型」只应该有一处知识来源。
        from/to 的存在性与自环是 Timeline 结构问题，留在这里判断。
        """
        issues: List[Issue] = []
        element_id = element.get("id", "")
        name = element.get("name", "")
        from_id = element.get("from")
        to_id = element.get("to")
        registry = self._libraries.get("transition")
        definition = registry.get(name) if registry is not None else None

        if registry is not None and definition is None:
            issues.append(
                Issue(
                    "RULE_TRANSITION_004",
                    self._level("RULE_TRANSITION_004"),
                    f"转场 {name} 未在 TransitionRegistry 注册（UNKNOWN_TRANSITION）",
                    element_id,
                    ["name"],
                )
            )

        # from / to 必须都指向存在的元素。这一条与 name 是否认识无关，照常检查。
        for key, value in (("from", from_id), ("to", to_id)):
            if by_id.get(value) if value else None:
                continue
            issues.append(
                Issue(
                    "RULE_TRANSITION_001",
                    self._level("RULE_TRANSITION_001"),
                    f"{key}={value} 找不到对应元素",
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

        from_element = by_id.get(from_id or "")
        to_element = by_id.get(to_id or "")
        if definition is not None and from_element and to_element:
            report = registry.validate_pair(
                name,
                str(from_element.get("type", "")),
                str(to_element.get("type", "")),
            )
            for error in report["errors"]:
                issues.append(
                    Issue(
                        "RULE_TRANSITION_005",
                        self._level("RULE_TRANSITION_005"),
                        error["message"],
                        element_id,
                        [error["parameter"]],
                    )
                )

        # 转场太长会把整个片段吃掉，只作提示：有人就是要做长溶解
        duration = tl.as_seconds(element.get("duration"))
        for key in ("from", "to"):
            neighbour = by_id.get(element.get(key) or "")
            if neighbour and duration > tl.as_seconds(neighbour.get("duration")) / 2 + 1e-6:
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

        if definition is not None:
            params_report = registry.validate(name, element.get("params"))
            for error in params_report["errors"]:
                issues.append(
                    Issue(
                        "RULE_TRANSITION_006",
                        self._level("RULE_TRANSITION_006"),
                        error["message"],
                        element_id,
                        ["params", error["parameter"]] if error["parameter"] else ["params"],
                    )
                )
            for warning in params_report["warnings"]:
                # MISSING_PARAMETER 不上报：Runtime 会补默认值
                if warning["code"] != "UNKNOWN_PARAMETER":
                    continue
                issues.append(
                    Issue(
                        "RULE_TRANSITION_007",
                        self._level("RULE_TRANSITION_007"),
                        warning["message"],
                        element_id,
                        ["params", warning["parameter"]],
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
