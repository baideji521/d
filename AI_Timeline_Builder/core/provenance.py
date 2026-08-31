"""Decision Provenance：把「为什么这么剪」与「渲染需要什么」彻底分开。

指令第三十五、三十六条要求的两件事，本模块各占一半：

1. **Runtime 不读 reason / confidence**。Timeline JSON 是渲染输入，
   里面只该有 start / duration / asset / 参数这些 Remotion 真的会用的东西。
   AI 的理由、置信度、输入引用属于「决策记录」，另存一份。
2. **决策可追溯**。每条决策有 decision_id，产出的元素 id 记在决策上，
   反过来也能从元素查回决策。人复核时问的是「这个推镜是谁加的、为什么」，
   没有这层映射就只能靠猜。

存哪里：与工程文件同级的 `decisions.json`（`DecisionLog.save()`），
**不进** timeline.json。删掉它渲染结果一模一样 —— 这正是它该有的性质。

本模块不依赖 PyQt，不碰 Remotion，也不做任何时间计算。
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

#: 决策来源。写死成枚举，免得日志里出现 "ai?" / "gpt" / "手动" 三种写法。
SOURCES = ("ai", "human", "voice_marker", "template", "unknown")

#: 日志文件名（与 timeline.json 同目录）
LOG_FILENAME = "decisions.json"

#: 日志格式版本。字段结构变了就 +1，读旧文件时能看出差异。
LOG_VERSION = 1


@dataclass
class DecisionRecord:
    """一条决策的溯源记录。

    与 EditingDecision 的区别：EditingDecision 是**输入**（要做什么），
    本记录是**发生过什么**（做成了哪些元素、被拒了没有、理由是什么）。
    """

    decision_id: str
    source: str
    action: str
    start: float = 0.0
    duration: Optional[float] = None
    target: str = ""
    reason: str = ""
    confidence: Optional[float] = None
    #: 这条决策产出的元素 id（可能多个：highlight 会展开成四个）
    elements: List[str] = field(default_factory=list)
    #: 输入引用：这条决策是看着什么做出来的（marker 时间、素材 id、片段 id…）
    input_ref: Dict[str, Any] = field(default_factory=dict)
    #: Planner 的拒绝 / 提醒（code 列表），空表示照做了
    issues: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "decision_id": self.decision_id,
            "source": self.source,
            "action": self.action,
            "start": self.start,
        }
        if self.duration is not None:
            payload["duration"] = self.duration
        if self.target:
            payload["target"] = self.target
        if self.reason:
            payload["reason"] = self.reason
        if self.confidence is not None:
            payload["confidence"] = self.confidence
        if self.elements:
            payload["elements"] = list(self.elements)
        if self.input_ref:
            payload["input_ref"] = copy.deepcopy(self.input_ref)
        if self.issues:
            payload["issues"] = list(self.issues)
        return payload

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "DecisionRecord":
        return cls(
            decision_id=str(raw.get("decision_id", "")),
            source=normalize_source(raw.get("source")),
            action=str(raw.get("action", "")),
            start=float(raw.get("start", 0.0) or 0.0),
            duration=None if raw.get("duration") is None else float(raw["duration"]),
            target=str(raw.get("target", "")),
            reason=str(raw.get("reason", "")),
            confidence=None if raw.get("confidence") is None else float(raw["confidence"]),
            elements=[str(e) for e in raw.get("elements", [])],
            input_ref=dict(raw.get("input_ref") or {}),
            issues=[str(i) for i in raw.get("issues", [])],
        )


def normalize_source(source: Any) -> str:
    """不认识的来源退成 unknown，而不是原样写进日志。

    「原样写」看着更诚实，其实更糟：后面统计「AI 加了多少个特效」时，
    `ai` / `AI` / `openai` 会被算成三种来源。
    """
    value = str(source or "").strip().lower()
    return value if value in SOURCES else "unknown"


def next_decision_id(existing: Sequence[str]) -> str:
    """dec_001、dec_002…… 与元素 id 一样的顺序编号，方便肉眼对照。"""
    used = set()
    for item in existing:
        text = str(item)
        if text.startswith("dec_"):
            try:
                used.add(int(text[4:]))
            except ValueError:
                continue
    index = 1
    while index in used:
        index += 1
    return f"dec_{index:03d}"


class DecisionLog:
    """一批决策的溯源日志。

    只做记录与查询，不做判断 —— 它不该有「置信度低于 0.5 就丢掉」这种逻辑，
    那属于人的决定，不该藏在日志层。
    """

    def __init__(self, records: Optional[Sequence[DecisionRecord]] = None) -> None:
        self._records: List[DecisionRecord] = list(records or [])

    def __len__(self) -> int:
        return len(self._records)

    def records(self) -> List[DecisionRecord]:
        return list(self._records)

    def add(
        self,
        action: str,
        source: str = "ai",
        start: float = 0.0,
        duration: Optional[float] = None,
        target: str = "",
        reason: str = "",
        confidence: Optional[float] = None,
        elements: Optional[Sequence[str]] = None,
        input_ref: Optional[Dict[str, Any]] = None,
        issues: Optional[Sequence[str]] = None,
        decision_id: str = "",
    ) -> DecisionRecord:
        record = DecisionRecord(
            decision_id=decision_id or next_decision_id([r.decision_id for r in self._records]),
            source=normalize_source(source),
            action=str(action),
            start=float(start or 0.0),
            duration=duration,
            target=str(target or ""),
            reason=str(reason or ""),
            confidence=confidence,
            elements=[str(e) for e in (elements or [])],
            input_ref=dict(input_ref or {}),
            issues=[str(i) for i in (issues or [])],
        )
        self._records.append(record)
        return record

    def of_element(self, element_id: str) -> Optional[DecisionRecord]:
        """这个元素是哪条决策产出的。找不到返回 None（人手加的元素就没有）。"""
        for record in self._records:
            if element_id in record.elements:
                return record
        return None

    def by_source(self, source: str) -> List[DecisionRecord]:
        wanted = normalize_source(source)
        return [r for r in self._records if r.source == wanted]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": LOG_VERSION,
            "count": len(self._records),
            "decisions": [r.to_dict() for r in self._records],
        }

    def save(self, path: str) -> str:
        """写决策日志。**不写进 timeline.json**，删掉它不影响渲染。"""
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        return path

    @classmethod
    def load(cls, path: str) -> "DecisionLog":
        """读决策日志。文件不存在就是空日志 —— 老工程没这个文件是正常的。"""
        if not os.path.isfile(path):
            return cls()
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        rows = data.get("decisions", []) if isinstance(data, dict) else []
        return cls([DecisionRecord.from_dict(r) for r in rows if isinstance(r, dict)])


def log_path(project_dir: str) -> str:
    return os.path.join(project_dir, LOG_FILENAME)


def record_plan(
    log: DecisionLog,
    result: Any,
    decisions: Sequence[Any],
    source: str = "ai",
    input_ref: Optional[Dict[str, Any]] = None,
) -> List[DecisionRecord]:
    """把一次 `EditingPlanner.plan()` 的结果记进日志。

    元素归属按 `PlanResult.element_owner`（Planner 在生成时就标好了），
    不是事后按时间猜 —— 猜出来的溯源比没有溯源更害人。
    """
    owner: Dict[str, str] = dict(getattr(result, "element_owner", {}) or {})
    issues_by_id: Dict[str, List[str]] = {}
    for issue in list(getattr(result, "errors", [])) + list(getattr(result, "warnings", [])):
        key = getattr(issue, "decision_id", "") or ""
        issues_by_id.setdefault(key, []).append(getattr(issue, "code", ""))

    written: List[DecisionRecord] = []
    for decision in decisions or []:
        decision_id = str(getattr(decision, "decision_id", "") or "")
        elements = [eid for eid, did in owner.items() if did == decision_id]
        written.append(
            log.add(
                action=str(getattr(decision, "action", "")),
                source=source,
                start=float(getattr(decision, "start", 0.0) or 0.0),
                duration=getattr(decision, "duration", None),
                target=str(getattr(decision, "target", "") or ""),
                reason=str(getattr(decision, "reason", "") or ""),
                confidence=getattr(decision, "confidence", None),
                elements=elements,
                input_ref=dict(input_ref or {}),
                issues=issues_by_id.get(decision_id, []),
                decision_id=decision_id,
            )
        )
    return written
