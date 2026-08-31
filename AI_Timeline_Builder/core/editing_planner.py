"""Editing Planner：把「剪辑意图」翻译成 Timeline 元素。

整条链路里 AI 只负责最上面一格：

    AI
     ↓  EditingDecision（做什么 / 什么时候 / 多久 / 为什么）
    Editing Planner（本模块）
     ↓  Timeline 元素（start / duration / track / asset / params）
    TimelineModel → Timeline JSON → Validator → Remotion → MP4

为什么必须夹这一层（指令第二十一、二十四条）：

- **AI 不许直接产出 TSX**，也不该知道 `V3` 轨道、`scale_to` 参数名、
  `source_time` 该填哪个数。它只说「24.0 秒这里要强调一下」。
- 「强调」是**复合意图**：冻帧 + 推镜 + 撞击音效 + 字幕强调。
  把这套展开规则写在 Planner 里，人工和 AI 才会得到同一个结果。
- Planner 会拒绝不存在的能力：特效 / 转场必须在 Registry 里注册过，
  音效必须在 AssetRegistry 里真的存在。**编造一律报错，不静默忽略**。

Planner 只生产元素，不做校验的活 —— 产出物照样要过
TimelineValidator（Schema + 语义 + Registry + Rule Engine）。
两者的关系是「先生成、再体检」，不是互相替代。

本模块不依赖 PyQt，也不碰 Remotion。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from core import safe_area as sa
from core import time_utils as tu
from core import timeline as tl

#: AI 可以表达的动作白名单（指令第二十三条）。不在表里的动作一律报错。
ACTIONS = (
    "cut",
    "trim",
    "highlight",
    "freeze",
    "zoom",
    "effect",
    "transition",
    "overlay",
    "caption",
    "sfx",
    "voice",
    "music",
)

ACTION_LABELS: Dict[str, str] = {
    "cut": "切一刀（把片段拆成两段）",
    "trim": "裁剪片段的头或尾",
    "highlight": "高光强调（冻帧 + 推镜 + 音效 + 字幕）",
    "freeze": "冻结帧",
    "zoom": "推拉镜头",
    "effect": "施加程序特效",
    "transition": "在两个片段之间加转场",
    "overlay": "叠加素材（图片 / 透明视频）",
    "caption": "加字幕",
    "sfx": "加音效",
    "voice": "加配音",
    "music": "加背景音乐",
}

#: highlight 展开成哪些动作。顺序即写入 Timeline 的顺序。
HIGHLIGHT_STEPS = ("freeze_frame", "zoom", "impact_sfx", "caption_emphasis")

#: 复合动作里各步骤的默认时长（秒）。都能被 decision.params 覆盖。
HIGHLIGHT_DEFAULTS: Dict[str, float] = {
    "freeze_duration": 1.0,
    "zoom_duration": 0.6,
    "sfx_duration": 0.6,
    "caption_duration": 1.0,
}

#: highlight 里推镜的目标缩放
HIGHLIGHT_SCALE_TO = 1.25

#: 挑音效时优先用哪些分类（AssetRegistry 里的 category）
IMPACT_CATEGORIES = ("impact", "boom", "whoosh")

#: voice marker → 剪辑动作的映射（指令第十七条）。
#:
#: VoiceDirector **不许**自己往时间线上加特效 —— 它只产出 voice_peak /
#: voice_pause 标记，说明「这里是重音 / 这里有停顿」。要不要因此推镜、
#: 加音效，是剪辑决策，必须走 EditingDecision → 白名单 → Planner → RuleEngine
#: 这条正路。映射表放在 Planner 这一侧，因为白名单归它管。
#:
#: voice_pause 故意**不映射任何动作**：停顿是节奏信息，不是「该加东西」的信号。
#: 它会被如实报成 VOICE_MARKER_NO_ACTION，而不是硬凑一个特效上去。
VOICE_MARKER_ACTIONS: Dict[str, Dict[str, Any]] = {
    "voice_peak": {
        "action": "zoom",
        "duration": 0.4,
        "params": {"scale_to": 1.12},
    },
}

#: 两个重音挨得太近时只保留第一个 —— 0.2 秒里连推三次镜头是抽搐不是强调
VOICE_PEAK_MIN_GAP = 0.35



@dataclass
class EditingDecision:
    """一条剪辑决策。这是 AI 与本工具之间的**唯一**协议对象。

    唯一一条契约（指令第三十三条）：**AI 的输出就是 EditingDecision 列表**，
    不是 Timeline JSON，不是 TSX，也不是 ffmpeg 命令行。
    JSON 形状见 `schemas/editing_decision_schema.json`。

    字段语义：

    - action：做什么，必须在 ACTIONS 里
    - target：作用在哪个元素上（cut / trim / freeze / zoom / effect 需要）
    - start：时间线绝对秒数
    - duration：持续秒数；省略时按能力的默认时长
    - params：动作参数（例如 zoom 的 scale_to、caption 的 text）。
      JSON 里的规范键名是 `parameters`，`params` 作为别名一样收。
    - reason：为什么这么剪。**不参与渲染**，Runtime 一个字都不读；
      它进决策溯源日志（core/provenance.py），让人能复核 AI 的判断而不是只看到结果。
    - confidence：AI 自报的置信度（0..1）。同样只进溯源日志 ——
      工具**不会**拿它自动丢决策，免得「低置信度就悄悄不执行」这种看不见的行为。
    - decision_id：省略时由 Planner 按顺序补（dec_001…），用来把产出元素与决策对上。
    """

    action: str
    target: str = ""
    start: float = 0.0
    duration: Optional[float] = None
    params: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    confidence: Optional[float] = None
    decision_id: str = ""

    @classmethod
    def from_dict(cls, raw: Any) -> "EditingDecision":
        """宽容地读一条决策。

        同时接受两种写法（指令里两处示例都要能用）：

            {"action": "zoom", "target": "clip_003", "start": 12.4, ...}
            {"decision": "highlight", "time": 24.0, "actions": [...]}

        脏输入不抛异常 —— 会被翻译成 action="" 的决策，
        由 Planner 报成 UNKNOWN_ACTION，错误信息里能看到原始内容。
        """
        if not isinstance(raw, dict):
            return cls(action="")
        action = str(raw.get("action") or raw.get("decision") or "")
        start = raw.get("start", raw.get("time", 0.0))
        duration = raw.get("duration")
        params = dict(raw.get("parameters") or raw.get("params") or {})
        # {"actions": [...]} 是 highlight 那种复合写法，收进 params 里统一处理
        if raw.get("actions"):
            params.setdefault("steps", list(raw["actions"]))
        for extra in ("text", "asset", "name", "from", "to", "source_time", "at"):
            if extra in raw and extra not in params:
                params[extra] = raw[extra]
        confidence = raw.get("confidence")
        return cls(
            action=action,
            target=str(raw.get("target") or ""),
            start=tl.as_seconds(start),
            duration=None if duration is None else tl.as_seconds(duration),
            params=params,
            reason=str(raw.get("reason") or ""),
            confidence=None if confidence is None else tl.as_seconds(confidence),
            decision_id=str(raw.get("decision_id") or ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"action": self.action, "start": self.start}
        if self.decision_id:
            payload["decision_id"] = self.decision_id
        if self.target:
            payload["target"] = self.target
        if self.duration is not None:
            payload["duration"] = self.duration
        if self.params:
            payload["parameters"] = copy.deepcopy(self.params)
        if self.reason:
            payload["reason"] = self.reason
        if self.confidence is not None:
            payload["confidence"] = self.confidence
        return payload


@dataclass
class PlanIssue:
    """Planner 拒绝或提醒的一条记录。"""

    code: str
    message: str
    action: str = ""
    target: str = ""
    #: 哪条决策引出的。Planner 会自动补，用于溯源（core/provenance.py）
    decision_id: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "action": self.action,
            "target": self.target,
            "decision_id": self.decision_id,
        }


@dataclass
class PlanResult:
    """一次 plan() 的完整结果。

    `elements` 是**新增**的元素；`timeline` 是应用后的新时间线（输入不被修改）。
    有 errors 时 timeline 仍然返回 —— 能做的那部分照做，做不了的如实报，
    这样 AI 拿到反馈可以只修那一条决策，而不是整批重来。

    `element_owner` 是「元素 id → 决策 id」的映射，决策溯源靠它，
    不靠事后按时间猜（猜出来的溯源比没有更害人）。
    """

    timeline: Dict[str, Any]
    elements: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[PlanIssue] = field(default_factory=list)
    warnings: List[PlanIssue] = field(default_factory=list)
    applied: List[Dict[str, Any]] = field(default_factory=list)
    element_owner: Dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def report(self) -> Dict[str, Any]:
        """结构化报告，GUI 与 AI 都读这个。"""
        return {
            "ok": self.ok,
            "element_count": len(self.elements),
            "elements": [e.get("id", "") for e in self.elements],
            "applied": [d for d in self.applied],
            "element_owner": dict(self.element_owner),
            "errors": [i.to_dict() for i in self.errors],
            "warnings": [i.to_dict() for i in self.warnings],
        }


class EditingPlanner:
    """决策 → 元素。

    构造参数都是可选的，缺了就退化成「不做那部分检查」，
    但**不会**因此放过编造：Registry 为 None 时特效名不校验这件事
    会以 warning 的形式写进结果，不会假装通过。
    """

    def __init__(
        self,
        effects: Any = None,
        transitions: Any = None,
        assets: Any = None,
        fps: float = tu.DEFAULT_FPS,
    ) -> None:
        self._effects = effects
        self._transitions = transitions
        self._assets = assets
        self._fps = float(fps) if fps else tu.DEFAULT_FPS

    # ------------------------------------------------------------ 主入口

    def plan(
        self,
        timeline: Dict[str, Any],
        decisions: Sequence[Any],
    ) -> PlanResult:
        """把一批决策应用到时间线上，返回新时间线与报告。输入不被修改。

        没带 `decision_id` 的决策会被按顺序补上（dec_001…）——
        传进来的 EditingDecision 对象会被就地补号，这样调用方拿完结果
        还能用同一批对象写溯源日志（core/provenance.record_plan）。
        """
        result = PlanResult(timeline=copy.deepcopy(timeline))
        fps = tl.as_seconds((result.timeline.get("meta") or {}).get("fps")) or self._fps
        for index, raw in enumerate(decisions or []):
            decision = (
                raw if isinstance(raw, EditingDecision) else EditingDecision.from_dict(raw)
            )
            if not decision.decision_id:
                decision.decision_id = f"dec_{index + 1:03d}"
            self._apply_one(result, decision, fps)
        result.timeline["meta"] = dict(result.timeline.get("meta") or {})
        result.timeline["meta"]["duration"] = tl.timeline_duration(result.timeline)
        return result

    # ------------------------------------------------------------ 单条分派

    def _apply_one(self, result: PlanResult, decision: EditingDecision, fps: float) -> None:
        action = decision.action
        before_errors, before_warnings = len(result.errors), len(result.warnings)
        if action not in ACTIONS:
            result.errors.append(
                PlanIssue(
                    "UNKNOWN_ACTION",
                    f"动作 {action or '(空)'} 不在白名单内，可用动作：{', '.join(ACTIONS)}",
                    action,
                    decision.target,
                )
            )
            self._tag_issues(result, decision, before_errors, before_warnings)
            return

        handler = getattr(self, f"_do_{action}")
        before = len(result.elements)
        handler(result, decision, fps)
        self._tag_issues(result, decision, before_errors, before_warnings)
        if len(result.elements) > before or action in ("cut", "trim"):
            result.applied.append(decision.to_dict())

    @staticmethod
    def _tag_issues(
        result: PlanResult,
        decision: EditingDecision,
        before_errors: int,
        before_warnings: int,
    ) -> None:
        """给这一轮新产生的问题补上决策号，溯源日志才能对上账。"""
        for issue in result.errors[before_errors:] + result.warnings[before_warnings:]:
            if not issue.decision_id:
                issue.decision_id = decision.decision_id

    # ------------------------------------------------------------ 各动作

    def _do_highlight(self, result: PlanResult, decision: EditingDecision, fps: float) -> None:
        """高光强调：冻帧 + 推镜 + 撞击音效 + 字幕强调。

        target 缺省时自动找「当前时间点在播的那个视频片段」——
        AI 只说时间，不必知道片段 id。
        """
        clip = self._resolve_clip(result, decision)
        if clip is None:
            return
        steps = [str(s) for s in decision.params.get("steps") or HIGHLIGHT_STEPS]
        at = self._snap(decision.start, fps)
        durations = {**HIGHLIGHT_DEFAULTS}
        for key in durations:
            if key in decision.params:
                durations[key] = tl.as_seconds(decision.params[key])
        if decision.duration is not None:
            durations["freeze_duration"] = decision.duration

        if "freeze_frame" in steps:
            self._do_freeze(
                result,
                EditingDecision(
                    "freeze",
                    clip.get("id", ""),
                    at,
                    durations["freeze_duration"],
                    {},
                    decision.reason,
                    decision.confidence,
                    decision.decision_id,
                ),
                fps,
            )
        if "zoom" in steps:
            self._do_zoom(
                result,
                EditingDecision(
                    "zoom",
                    clip.get("id", ""),
                    at,
                    durations["zoom_duration"],
                    {"scale_to": decision.params.get("scale_to", HIGHLIGHT_SCALE_TO)},
                    decision.reason,
                    decision.confidence,
                    decision.decision_id,
                ),
                fps,
            )
        if "impact_sfx" in steps:
            self._do_sfx(
                result,
                EditingDecision(
                    "sfx",
                    "",
                    at,
                    durations["sfx_duration"],
                    {"category": decision.params.get("sfx_category", "")},
                    decision.reason,
                    decision.confidence,
                    decision.decision_id,
                ),
                fps,
            )
        if "caption_emphasis" in steps:
            text = str(decision.params.get("text") or "")
            if text:
                self._do_caption(
                    result,
                    EditingDecision(
                        "caption",
                        "",
                        at,
                        durations["caption_duration"],
                        {"text": text, "emphasis": True, "safe_area": True},
                        decision.reason,
                        decision.confidence,
                        decision.decision_id,
                    ),
                    fps,
                )
            else:
                result.warnings.append(
                    PlanIssue(
                        "CAPTION_TEXT_MISSING",
                        "highlight 里要求了字幕强调，但没给 params.text，已跳过字幕",
                        "highlight",
                        clip.get("id", ""),
                    )
                )

    def _do_freeze(self, result: PlanResult, decision: EditingDecision, fps: float) -> None:
        clip = self._resolve_clip(result, decision)
        if clip is None:
            return
        at = self._snap(decision.start, fps)
        duration = self._snap(
            decision.duration if decision.duration is not None else HIGHLIGHT_DEFAULTS["freeze_duration"],
            fps,
        )
        source_time = decision.params.get("source_time")
        if source_time is None:
            source_time = self._source_time_at(clip, at)
        element = tl.make_freeze(
            self._new_id(result.timeline, "freeze"),
            str(clip.get("id", "")),
            tl.as_seconds(source_time),
            at,
            duration,
            str(clip.get("track") or "V1"),
        )
        self._add(result, element, decision)

    def _do_zoom(self, result: PlanResult, decision: EditingDecision, fps: float) -> None:
        params = {"scale_to": decision.params.get("scale_to", HIGHLIGHT_SCALE_TO)}
        if "scale_from" in decision.params:
            params["scale_from"] = decision.params["scale_from"]
        merged = dict(decision.params)
        merged.update(params)
        merged.pop("steps", None)
        self._do_effect(
            result,
            EditingDecision(
                "effect",
                decision.target,
                decision.start,
                decision.duration,
                {**merged, "name": "zoom"},
                decision.reason,
                decision.confidence,
                decision.decision_id,
            ),
            fps,
        )

    def _do_effect(self, result: PlanResult, decision: EditingDecision, fps: float) -> None:
        name = str(decision.params.get("name") or "")
        definition = self._effect_definition(result, decision, name)
        if definition is False:
            return
        clip = self._resolve_clip(result, decision, required=False)
        at = self._snap(decision.start, fps)
        default_duration = (
            float(definition.default_duration) if definition is not None else 0.6
        )
        duration = self._snap(
            decision.duration if decision.duration is not None else default_duration, fps
        )
        params = {
            k: v
            for k, v in decision.params.items()
            if k not in ("name", "steps", "text", "emphasis", "safe_area", "category")
        }
        if definition is not None:
            unknown = [k for k in params if definition.parameter(k) is None]
            for key in unknown:
                result.warnings.append(
                    PlanIssue(
                        "UNKNOWN_PARAMETER",
                        f"{name} 没有参数 {key}，渲染时会被忽略",
                        decision.action,
                        decision.target,
                    )
                )
        element = tl.make_effect(
            self._new_id(result.timeline, "effect"),
            name,
            params,
            str((clip or {}).get("track") or "V1"),
            at,
            duration,
            str(clip.get("id", "")) if clip else None,
        )
        self._add(result, element, decision)

    def _do_transition(self, result: PlanResult, decision: EditingDecision, fps: float) -> None:
        name = str(decision.params.get("name") or "")
        from_id = str(decision.params.get("from") or "")
        to_id = str(decision.params.get("to") or decision.target or "")
        if self._transitions is not None and self._transitions.get(name) is None:
            result.errors.append(
                PlanIssue(
                    "UNKNOWN_TRANSITION",
                    f"转场 {name or '(空)'} 未在 TransitionRegistry 注册，不许编造",
                    decision.action,
                    to_id,
                )
            )
            return
        if self._transitions is None:
            result.warnings.append(
                PlanIssue(
                    "REGISTRY_UNAVAILABLE",
                    f"没有 TransitionRegistry，转场 {name} 的名字未经校验",
                    decision.action,
                    to_id,
                )
            )
        elements = {str(e.get("id", "")): e for e in result.timeline.get("elements", [])}
        missing = [i for i in (from_id, to_id) if i not in elements]
        if missing:
            result.errors.append(
                PlanIssue(
                    "TARGET_NOT_FOUND",
                    f"转场两侧的元素 {', '.join(missing)} 不存在",
                    decision.action,
                    to_id,
                )
            )
            return
        definition = self._transitions.get(name) if self._transitions is not None else None
        default_duration = float(getattr(definition, "default_duration", 0.5) or 0.5)
        duration = self._snap(
            decision.duration if decision.duration is not None else default_duration, fps
        )
        start = decision.start
        if not start:
            # 没给时间就压在后一个片段的开头，这是转场最常见的位置
            start = tl.as_seconds(elements[to_id].get("start"))
        params = {
            k: v for k, v in decision.params.items() if k not in ("name", "from", "to", "steps")
        }
        element = tl.make_transition(
            self._new_id(result.timeline, "transition"),
            name,
            from_id,
            to_id,
            self._snap(start, fps),
            duration,
            params,
            str(elements[to_id].get("track") or "V1"),
        )
        self._add(result, element, decision)

    def _do_overlay(self, result: PlanResult, decision: EditingDecision, fps: float) -> None:
        asset_id = str(decision.params.get("asset") or "")
        if not self._asset_ok(result, decision, asset_id):
            return
        element = tl.make_overlay(
            self._new_id(result.timeline, "overlay"),
            asset_id,
            str(decision.params.get("track") or "V3"),
            self._snap(decision.start, fps),
            self._snap(decision.duration if decision.duration is not None else 1.0, fps),
        )
        self._add(result, element, decision)

    def _do_caption(self, result: PlanResult, decision: EditingDecision, fps: float) -> None:
        text = str(decision.params.get("text") or "")
        if not text.strip():
            result.errors.append(
                PlanIssue("CAPTION_TEXT_MISSING", "caption 必须给 params.text", decision.action)
            )
            return
        element = tl.make_caption(
            self._new_id(result.timeline, "caption"),
            text,
            str(decision.params.get("track") or "T1"),
            self._snap(decision.start, fps),
            self._snap(decision.duration if decision.duration is not None else 1.2, fps),
        )
        if decision.params.get("safe_area"):
            element["safe_area"] = True
            preset = sa.timeline_preset(result.timeline)
            sa.clamp_element(element, preset)
        self._add(result, element, decision)

    def _do_sfx(self, result: PlanResult, decision: EditingDecision, fps: float) -> None:
        asset_id = str(decision.params.get("asset") or "")
        if not asset_id:
            asset_id = self._pick_sfx(str(decision.params.get("category") or ""))
        if not asset_id:
            result.errors.append(
                PlanIssue(
                    "SFX_NOT_FOUND",
                    "素材库里找不到可用音效，AI 不许编造 asset id",
                    decision.action,
                )
            )
            return
        if not self._asset_ok(result, decision, asset_id):
            return
        self._add_audio(result, decision, asset_id, "A3", 0.6, fps)

    def _do_voice(self, result: PlanResult, decision: EditingDecision, fps: float) -> None:
        asset_id = str(decision.params.get("asset") or "")
        if not self._asset_ok(result, decision, asset_id):
            return
        self._add_audio(result, decision, asset_id, "A2", 1.0, fps)

    def _do_music(self, result: PlanResult, decision: EditingDecision, fps: float) -> None:
        asset_id = str(decision.params.get("asset") or "")
        if not self._asset_ok(result, decision, asset_id):
            return
        self._add_audio(result, decision, asset_id, "A1", 5.0, fps)

    def _do_cut(self, result: PlanResult, decision: EditingDecision, fps: float) -> None:
        """在 start 处把片段切成两段。源区间按比例分配，两段加起来等于原片段。"""
        clip = self._resolve_clip(result, decision)
        if clip is None:
            return
        start = tl.as_seconds(clip.get("start"))
        duration = tl.as_seconds(clip.get("duration"))
        at = self._snap(decision.start, fps)
        if not (start + 1e-6 < at < start + duration - 1e-6):
            result.errors.append(
                PlanIssue(
                    "CUT_OUT_OF_RANGE",
                    f"切点 {at}s 不在片段 [{start}, {round(start + duration, 3)}] 内部",
                    decision.action,
                    str(clip.get("id", "")),
                )
            )
            return
        source = clip.get("source") or {}
        src_start = tl.as_seconds(source.get("start"))
        src_end = tl.as_seconds(source.get("end"))
        speed = tl.effective_speed(clip)
        offset = (at - start) * speed
        tail = tl.make_video(
            self._new_id(result.timeline, "video"),
            str(clip.get("asset", "")),
            str(clip.get("track") or "V1"),
            at,
            src_start + offset,
            src_end,
            speed,
        )
        clip["duration"] = round(at - start, 3)
        clip["source"] = {"start": round(src_start, 3), "end": round(src_start + offset, 3)}
        self._add(result, tail, decision)

    def _do_trim(self, result: PlanResult, decision: EditingDecision, fps: float) -> None:
        """裁掉片段的头或尾。params.side = head / tail，params.seconds = 裁多少。"""
        clip = self._resolve_clip(result, decision)
        if clip is None:
            return
        side = str(decision.params.get("side") or "tail")
        amount = tl.as_seconds(decision.params.get("seconds", decision.duration or 0.0))
        duration = tl.as_seconds(clip.get("duration"))
        if amount <= 0 or amount >= duration:
            result.errors.append(
                PlanIssue(
                    "TRIM_OUT_OF_RANGE",
                    f"裁剪长度 {amount}s 必须大于 0 且小于片段时长 {duration}s",
                    decision.action,
                    str(clip.get("id", "")),
                )
            )
            return
        source = clip.get("source") or {}
        src_start = tl.as_seconds(source.get("start"))
        src_end = tl.as_seconds(source.get("end"))
        speed = tl.effective_speed(clip)
        shift = amount * speed
        if side == "head":
            clip["start"] = round(tl.as_seconds(clip.get("start")) + amount, 3)
            clip["source"] = {"start": round(src_start + shift, 3), "end": round(src_end, 3)}
        else:
            clip["source"] = {"start": round(src_start, 3), "end": round(src_end - shift, 3)}
        clip["duration"] = round(duration - amount, 3)

    # ------------------------------------------------------------ 工具

    def _add(self, result: PlanResult, element: Dict[str, Any], decision: EditingDecision) -> None:
        if decision.reason:
            # note 是 schema 里给「人工实验备注」留的字段，不影响渲染。
            # AI 的判断理由写在这里，复核的人能看到「为什么这一刀」。
            # 完整溯源（置信度 / 输入引用）另存 decisions.json，不塞进渲染数据。
            element["note"] = decision.reason
        result.timeline.setdefault("elements", []).append(element)
        result.elements.append(element)
        if decision.decision_id:
            result.element_owner[str(element.get("id", ""))] = decision.decision_id

    def _add_audio(
        self,
        result: PlanResult,
        decision: EditingDecision,
        asset_id: str,
        track: str,
        default_duration: float,
        fps: float,
    ) -> None:
        duration = decision.duration
        if duration is None:
            duration = self._asset_duration(asset_id) or default_duration
        element = tl.make_audio(
            self._new_id(result.timeline, "audio"),
            asset_id,
            str(decision.params.get("track") or track),
            self._snap(decision.start, fps),
            self._snap(duration, fps),
            tl.as_seconds(decision.params.get("source_start", 0.0)),
            tl.as_seconds(decision.params.get("volume", tl.DEFAULT_VOLUME)),
            tl.as_seconds(decision.params.get("fade_in", 0.0)),
            tl.as_seconds(decision.params.get("fade_out", 0.0)),
        )
        self._add(result, element, decision)

    def _resolve_clip(
        self,
        result: PlanResult,
        decision: EditingDecision,
        required: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """定位决策作用的视频片段：先按 target，再按时间点。"""
        elements = result.timeline.get("elements", [])
        if decision.target:
            for element in elements:
                if str(element.get("id", "")) == decision.target:
                    return element
            result.errors.append(
                PlanIssue(
                    "TARGET_NOT_FOUND",
                    f"target {decision.target} 在时间线上不存在",
                    decision.action,
                    decision.target,
                )
            )
            return None
        at = decision.start
        for element in elements:
            if element.get("type") != "video":
                continue
            start = tl.as_seconds(element.get("start"))
            if start - 1e-6 <= at < start + tl.as_seconds(element.get("duration")) + 1e-6:
                return element
        if required:
            result.errors.append(
                PlanIssue(
                    "TARGET_NOT_FOUND",
                    f"{at}s 处没有视频片段，无法定位 {decision.action} 的作用对象",
                    decision.action,
                )
            )
        return None

    def _effect_definition(self, result: PlanResult, decision: EditingDecision, name: str):
        """返回 EffectDefinition / None（没 Registry）/ False（名字不认识）。"""
        if self._effects is None:
            result.warnings.append(
                PlanIssue(
                    "REGISTRY_UNAVAILABLE",
                    f"没有 EffectRegistry，特效 {name} 的名字未经校验",
                    decision.action,
                    decision.target,
                )
            )
            return None
        definition = self._effects.get(name)
        if definition is None:
            result.errors.append(
                PlanIssue(
                    "UNKNOWN_EFFECT",
                    f"特效 {name or '(空)'} 未在 EffectRegistry 注册，不许编造",
                    decision.action,
                    decision.target,
                )
            )
            return False
        if getattr(definition, "element_type", "effect") != "effect":
            result.errors.append(
                PlanIssue(
                    "MATERIAL_EFFECT_AS_EFFECT",
                    f"{name} 是素材特效，必须用 overlay 动作，不能当程序特效",
                    decision.action,
                    decision.target,
                )
            )
            return False
        return definition

    def _asset_ok(self, result: PlanResult, decision: EditingDecision, asset_id: str) -> bool:
        if not asset_id:
            result.errors.append(
                PlanIssue(
                    "ASSET_MISSING",
                    f"{decision.action} 必须给 params.asset",
                    decision.action,
                    decision.target,
                )
            )
            return False
        if self._assets is None:
            result.warnings.append(
                PlanIssue(
                    "REGISTRY_UNAVAILABLE",
                    f"没有 AssetRegistry，素材 {asset_id} 是否存在未经校验",
                    decision.action,
                    decision.target,
                )
            )
            return True
        if not self._assets.has(asset_id):
            result.errors.append(
                PlanIssue(
                    "ASSET_NOT_FOUND",
                    f"素材 {asset_id} 不在素材库里，不许编造 asset id",
                    decision.action,
                    decision.target,
                )
            )
            return False
        return True

    def _pick_sfx(self, category: str) -> str:
        """从 AssetRegistry 里挑一个音效。挑不到就返回空串，由调用方报错。"""
        if self._assets is None:
            return ""
        wanted = [category] if category else list(IMPACT_CATEGORIES)
        for name in wanted:
            found = self._assets.first_of("sfx", category=name)
            if found:
                return str(found.get("id", ""))
        found = self._assets.first_of("sfx")
        return str(found.get("id", "")) if found else ""

    def _asset_duration(self, asset_id: str) -> float:
        if self._assets is None:
            return 0.0
        record = self._assets.get(asset_id) or {}
        return tl.as_seconds(record.get("duration"))

    @staticmethod
    def _source_time_at(clip: Dict[str, Any], at: float) -> float:
        """时间线时刻 → 该片段的源素材时刻（考虑变速）。"""
        start = tl.as_seconds(clip.get("start"))
        source = clip.get("source") or {}
        src_start = tl.as_seconds(source.get("start"))
        src_end = tl.as_seconds(source.get("end"))
        speed = tl.effective_speed(clip)
        raw = src_start + max(0.0, at - start) * speed
        if src_end > src_start:
            raw = min(raw, src_end)
        return round(raw, 3)

    def _snap(self, seconds: Any, fps: float) -> float:
        """所有时间都吸到整帧：AI 给的 12.31 会变成 12.3（30fps）。"""
        return tu.snap_to_frame(max(0.0, tl.as_seconds(seconds)), fps)

    @staticmethod
    def _new_id(timeline: Dict[str, Any], type_name: str) -> str:
        return tl.next_element_id(timeline, type_name)


# ---------------------------------------------------------------- AI 输出闸门
#
# 指令第三十三 / 四十二条：AI 的输出只能是 EditingDecision，且里面不许出现
# TSX、ffmpeg 命令、绝对路径。这两件事在**进 Planner 之前**就该拦住 ——
# 等到 Validator 才发现，中间已经生成了一堆基于胡话的元素。

#: 决策 Schema 文件名（放在 schemas/ 下，与时间线 Schema 同级）
DECISION_SCHEMA_FILE = "editing_decision_schema.json"

#: AI 输出里绝对不该出现的东西：code → (人话, 触发词)
FORBIDDEN_MARKERS: Dict[str, Any] = {
    "AI_OUTPUT_TSX": ("AI 不许写 TSX / React 组件，只能给 EditingDecision",
                      (".tsx", "import {", "<AbsoluteFill", "useCurrentFrame")),
    "AI_OUTPUT_FFMPEG": ("AI 不许直接调 ffmpeg / Remotion CLI",
                         ("ffmpeg", "ffprobe", "npx remotion", "remotion render")),
    "AI_OUTPUT_ABSOLUTE_PATH": ("AI 不许写绝对路径，素材只能用 asset id",
                                ("c:\\", "d:\\", "e:\\", "f:\\", "file://", "/users/", "/home/")),
}


def load_decision_schema(schemas_dir: str) -> Optional[Dict[str, Any]]:
    """读决策 Schema。文件缺失返回 None，由调用方报成「未校验」而不是「通过」。"""
    import json
    import os

    path = os.path.join(schemas_dir, DECISION_SCHEMA_FILE)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def forbidden_issues(payload: Any) -> List[PlanIssue]:
    """扫一遍 AI 输出里的字符串，看有没有越界的东西。

    只看**内容**，不看结构 —— 藏在 reason 里的 ffmpeg 命令行同样算越界，
    因为那说明模型以为自己能那么干。
    """
    texts: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            texts.append(node)
        elif isinstance(node, dict):
            for key, value in node.items():
                texts.append(str(key))
                walk(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)

    walk(payload)
    lowered = [t.lower() for t in texts]
    issues: List[PlanIssue] = []
    for code, (message, needles) in FORBIDDEN_MARKERS.items():
        # 触发词也要转小写再比：不然 "<AbsoluteFill" 这种驼峰永远命不中
        hit = next((n for n in (x.lower() for x in needles) for t in lowered if n in t), "")
        if hit:
            issues.append(PlanIssue(code, f"{message}（命中 {hit!r}）"))
    return issues


def decision_payload_issues(payload: Any, schemas_dir: str) -> List[PlanIssue]:
    """决策 JSON 的入口体检：Schema + 内容闸门。

    Schema 校验依赖 jsonschema；缺依赖或缺文件时报 `DECISION_SCHEMA_UNAVAILABLE`
    警告，**不**假装校验过了。内容闸门不依赖任何库，永远在跑。
    """
    issues = forbidden_issues(payload)
    schema = load_decision_schema(schemas_dir)
    if schema is None:
        issues.append(
            PlanIssue("DECISION_SCHEMA_UNAVAILABLE",
                      f"找不到 {DECISION_SCHEMA_FILE}，决策结构未经 Schema 校验")
        )
        return issues
    try:
        import jsonschema  # type: ignore
    except ImportError:
        issues.append(
            PlanIssue("DECISION_SCHEMA_UNAVAILABLE",
                      "没装 jsonschema，决策结构未经 Schema 校验")
        )
        return issues
    validator = jsonschema.Draft7Validator(schema)
    for error in sorted(validator.iter_errors(payload), key=lambda e: list(e.path)):
        where = "/".join(str(p) for p in error.path) or "(根)"
        issues.append(PlanIssue("DECISION_SCHEMA", f"{where}：{error.message}"))
    return issues


def decisions_from_payload(payload: Any) -> List[EditingDecision]:
    """`{"decisions": [...]}` → EditingDecision 列表。不做校验，只做翻译。"""
    rows = payload.get("decisions") if isinstance(payload, dict) else payload
    return [EditingDecision.from_dict(raw) for raw in (rows or [])]


# ---------------------------------------------------------------- 配音 → 决策



@dataclass
class VoiceDecisionBundle:
    """voice markers 翻译出来的决策 + 被跳过的说明（指令第十七条）。"""

    decisions: List[EditingDecision] = field(default_factory=list)
    notes: List[PlanIssue] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decisions": [d.to_dict() for d in self.decisions],
            "notes": [n.to_dict() for n in self.notes],
        }


def decisions_from_voice_markers(
    markers: Sequence[Dict[str, Any]],
    with_sfx: bool = False,
    min_gap: float = VOICE_PEAK_MIN_GAP,
    limit: Optional[int] = None,
) -> VoiceDecisionBundle:
    """voice markers → EditingDecision 列表（指令第十七条）。

    只做「翻译 + 去重」，不碰时间线、不校验素材 —— 那些是 Planner 与
    Validator 的活。产出的动作一定在 `ACTIONS` 白名单里（映射表里写死的），
    所以走这条路也绕不过白名单。

    - `with_sfx=True` 时每个重音额外配一条 `sfx` 决策（分类 impact）；
      音效到底存不存在由 Planner 查 AssetRegistry，这里不假设。
    - `min_gap` 秒内的相邻重音只保留第一个，被丢掉的记进 notes。
    - `limit` 限制最多产出多少个重音动作，免得一段长配音铺满特效。
    """
    bundle = VoiceDecisionBundle()
    last_peak: Optional[float] = None
    used = 0
    for marker in markers or []:
        if not isinstance(marker, dict):
            continue
        kind = str(marker.get("type") or "")
        at = tl.as_seconds(marker.get("time"))
        label = str(marker.get("label") or "")
        plan = VOICE_MARKER_ACTIONS.get(kind)
        if plan is None:
            bundle.notes.append(
                PlanIssue(
                    "VOICE_MARKER_NO_ACTION",
                    f"{kind or '(空)'} 标记（{at}s）不映射任何剪辑动作，只作为节奏信息保留",
                )
            )
            continue
        if last_peak is not None and at - last_peak < max(0.0, min_gap):
            bundle.notes.append(
                PlanIssue(
                    "VOICE_PEAK_TOO_CLOSE",
                    f"{at}s 的重音与上一个相隔 {round(at - last_peak, 3)}s"
                    f"（< {min_gap}s），已跳过，免得动作叠成抽搐",
                )
            )
            continue
        if limit is not None and used >= limit:
            bundle.notes.append(
                PlanIssue("VOICE_PEAK_LIMIT", f"{at}s 的重音超出上限 {limit} 条，已跳过")
            )
            continue
        reason = f"配音重音 @{at}s" + (f"：{label}" if label else "")
        bundle.decisions.append(
            EditingDecision(
                action=str(plan["action"]),
                start=at,
                duration=tl.as_seconds(plan.get("duration")),
                params=dict(plan.get("params") or {}),
                reason=reason,
            )
        )
        if with_sfx:
            bundle.decisions.append(
                EditingDecision(
                    action="sfx",
                    start=at,
                    duration=HIGHLIGHT_DEFAULTS["sfx_duration"],
                    params={"category": "impact"},
                    reason=reason,
                )
            )
        last_peak = at
        used += 1
    return bundle


# ---------------------------------------------------------------- 能力自述



def action_catalog() -> List[Dict[str, Any]]:
    """动作白名单的结构化描述，供 AI_CAPABILITIES / 文档生成器使用。"""
    rows: List[Dict[str, Any]] = []
    for action in ACTIONS:
        row: Dict[str, Any] = {
            "action": action,
            "label": ACTION_LABELS.get(action, action),
            "requires_target": action in ("cut", "trim", "freeze"),
        }
        if action == "highlight":
            row["expands_to"] = list(HIGHLIGHT_STEPS)
        if action in ("sfx", "voice", "music", "overlay"):
            row["requires_asset"] = action != "sfx"
        if action in ("effect", "transition"):
            row["requires_registry_name"] = True
        rows.append(row)
    return rows
