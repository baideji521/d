"""Rule Engine：把「能不能这么剪」从校验器里独立出来。

分工（指令第二十二条）：

    Schema      字段 / 类型 / 结构        jsonschema
        ↓
    Semantic    引用是否存在、时间关系     core/timeline_validator.py
        ↓
    Registry    特效 / 转场是否注册、参数   libraries/*_registry.py
        ↓
    Rule Engine 剪辑规则（本模块）         规则声明 + 规则实现在一起

为什么再拆一层：`schemas/rules.json` 一直只是**声明**（id + level + 说明），
真正的判断散在 `timeline_validator.py` 里。声明和实现分居两地，
就会出现「rules.json 写了一条规则，其实没人在跑」这种最难发现的假合规。
本模块做两件事：

1. 提供剪辑级规则的**实现**（片段长度、安全区），返回结构化 finding；
2. 提供**一致性检查**：声明了的规则必须有地方实现，实现了的必须先声明。
   `tests/test_rule_engine.py` 用它把两边钉在一起。

本模块不碰 Schema、不碰 Registry、不做时间计算之外的事，也不依赖 PyQt。
level（error / warning）永远从 rules.json 读，不在代码里第二次写。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from core import safe_area as sa
from core import timeline as tl

#: 普通片段的时长上界（秒）。超过这个长度的片段在短视频里几乎必然是忘了剪。
#: 只报 warning：真有人要放一段 30 秒长镜头，工具不该拦。
MAX_CLIP_SECONDS = 15.0

#: 收尾片段豁免（RULE_CLIP_002）：每条视频轨上**最后一个**片段允许超长，
#: 片尾留白 / 结尾长镜头是常见剪法。
CLOSING_CLIP_EXEMPT = True


@dataclass
class RuleDefinition:
    """一条规则的声明（来自 schemas/rules.json）。"""

    id: str
    level: str
    description: str
    #: check = 有对应实现会真的跑；exemption = 只描述豁免条件，本身不产出问题
    kind: str = "check"

    @property
    def category(self) -> str:
        """规则族：去掉 `RULE_` 前缀与结尾的三位编号。

        RULE_CLIP_001 → CLIP，RULE_SAFE_AREA_001 → SAFE_AREA
        （族名本身可以带下划线，所以不能简单按 `_` 取第二段）。
        """
        match = re.fullmatch(r"RULE_(.+)_\d{3}", self.id)
        return match.group(1) if match else self.id

    def is_exemption(self) -> bool:
        return self.kind == "exemption"


@dataclass
class Finding:
    """一条规则命中。level 由调用方按 rules.json 补，这里只说「是哪条规则、哪里」。"""

    rule_id: str
    message: str
    element_id: str = ""
    path: List[str] = field(default_factory=list)


def load_rule_definitions(rules_path: str) -> Dict[str, RuleDefinition]:
    """读 rules.json 的声明部分。文件缺失返回空表，不抛异常。"""
    if not os.path.isfile(rules_path):
        return {}
    with open(rules_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    table: Dict[str, RuleDefinition] = {}
    for raw in data.get("rules", []):
        rule_id = str(raw.get("id", ""))
        if not rule_id:
            continue
        table[rule_id] = RuleDefinition(
            id=rule_id,
            level=str(raw.get("level", "error")),
            description=str(raw.get("description", "")),
            kind=str(raw.get("kind", "check")),
        )
    return table


class RuleEngine:
    """剪辑级规则的实现。

    每个 `_check_*` 方法只负责一族规则，返回 Finding 列表；
    `RULES_IMPLEMENTED_HERE` 声明本模块会产出哪些 rule id ——
    一致性测试靠它，而不是靠人去数。
    """

    #: 本模块负责实现的规则 id
    RULES_IMPLEMENTED_HERE = ("RULE_CLIP_001", "RULE_SAFE_AREA_001", "RULE_SAFE_AREA_002")

    def __init__(self, definitions: Optional[Dict[str, RuleDefinition]] = None) -> None:
        self._definitions = dict(definitions or {})

    # ------------------------------------------------------------ 声明查询

    def definition(self, rule_id: str) -> Optional[RuleDefinition]:
        return self._definitions.get(rule_id)

    def level_of(self, rule_id: str) -> str:
        rule = self._definitions.get(rule_id)
        return rule.level if rule else "error"

    def declared_ids(self) -> List[str]:
        return sorted(self._definitions)

    # ------------------------------------------------------------ 主入口

    def check(self, timeline: Dict[str, Any]) -> List[Finding]:
        """跑本模块负责的全部规则。输入脏数据也不许抛异常。"""
        if not isinstance(timeline, dict):
            return []
        findings: List[Finding] = []
        findings.extend(self._check_clip_length(timeline))
        findings.extend(self._check_safe_area(timeline))
        findings.extend(self._check_safe_area_layout(timeline))
        return findings

    # ------------------------------------------------------------ 各族规则

    def _check_clip_length(self, timeline: Dict[str, Any]) -> List[Finding]:
        """RULE_CLIP_001 / RULE_CLIP_002：普通片段别超过 15 秒，收尾片段豁免。"""
        findings: List[Finding] = []
        elements = [
            e for e in timeline.get("elements", [])
            if isinstance(e, dict) and e.get("type") == "video"
        ]
        if not elements:
            return findings

        # 每条轨道各自算「最后一个片段」：多轨剪辑里 V1 与 V2 的收尾是分开的
        last_on_track: Dict[str, str] = {}
        for element in elements:
            track = str(element.get("track", "") or "")
            current = last_on_track.get(track)
            if current is None:
                last_on_track[track] = str(element.get("id", ""))
                continue
            previous = next(
                (e for e in elements if str(e.get("id", "")) == current), None
            )
            if previous is None or tl.element_end(element) >= tl.element_end(previous):
                last_on_track[track] = str(element.get("id", ""))

        for element in elements:
            duration = tl.as_seconds(element.get("duration"))
            if duration <= MAX_CLIP_SECONDS:
                continue
            element_id = str(element.get("id", ""))
            track = str(element.get("track", "") or "")
            if CLOSING_CLIP_EXEMPT and last_on_track.get(track) == element_id:
                continue  # RULE_CLIP_002 豁免
            findings.append(
                Finding(
                    "RULE_CLIP_001",
                    f"片段时长 {duration:.3f}s 超过 {MAX_CLIP_SECONDS:g}s，"
                    "短视频里这通常是忘了剪（轨道上的收尾片段不受此限）",
                    element_id,
                    ["duration"],
                )
            )
        return findings

    def _check_safe_area(self, timeline: Dict[str, Any]) -> List[Finding]:
        """RULE_SAFE_AREA_001：声明了 safe_area 的元素必须真的落在安全区内。

        只查显式声明 `safe_area: true` 的元素 —— 没声明就是用户要满屏放，
        工具不该替他改主意。
        """
        findings: List[Finding] = []
        preset = sa.timeline_preset(timeline)
        for element in timeline.get("elements", []):
            if not isinstance(element, dict) or not sa.element_locked(element):
                continue
            if not tl.supports_transform(element):
                findings.append(
                    Finding(
                        "RULE_SAFE_AREA_001",
                        f"{tl.ELEMENT_TYPE_LABELS.get(element.get('type'), '元素')}"
                        "没有位置语义，safe_area 对它无效",
                        str(element.get("id", "")),
                        ["safe_area"],
                    )
                )
                continue
            transform = tl.effective_transform(element)
            x, y = float(transform["x"]), float(transform["y"])
            if sa.contains(x, y, preset):
                continue
            left, top, right, bottom = sa.box(preset)
            findings.append(
                Finding(
                    "RULE_SAFE_AREA_001",
                    f"声明了 safe_area 但位置 ({x:.3f}, {y:.3f}) 在安全区外"
                    f"（{sa.label_of(preset)}：x ∈ [{left:.2f}, {right:.2f}]，"
                    f"y ∈ [{top:.2f}, {bottom:.2f}]）",
                    str(element.get("id", "")),
                    ["transform"],
                )
            )
        return findings

    def _check_safe_area_layout(self, timeline: Dict[str, Any]) -> List[Finding]:
        """RULE_SAFE_AREA_002：字幕 / 文字 / 叠加素材越界，即使没声明也提示。

        为什么要有这一条（指令第二十一条）：只查 `safe_area: true` 的元素，
        安全区就只是个自愿贴的标签 —— 大多数人根本不会贴，字幕照样被 UI 压住。
        排版约束该对所有排版元素生效。

        但它只报 warning，不拦渲染：满屏贴纸、故意压边的花字都是正当做法，
        工具的职责是「提醒你这里会被 UI 盖住」，不是替你决定构图。
        已经声明 `safe_area: true` 的元素由 001 以 error 报，这里跳过，不重复。
        """
        findings: List[Finding] = []
        for row in sa.violations(timeline):
            if row["locked"]:
                continue  # 归 RULE_SAFE_AREA_001，那边是 error
            bounds = row["box"]
            findings.append(
                Finding(
                    "RULE_SAFE_AREA_002",
                    f"{tl.ELEMENT_TYPE_LABELS.get(row['type'], row['type'])}"
                    f"位置 ({row['x']:.3f}, {row['y']:.3f}) 在安全区外，"
                    f"发布后可能被平台 UI 压住"
                    f"（{sa.label_of(row['preset'])}："
                    f"x ∈ [{bounds['left']:.2f}, {bounds['right']:.2f}]，"
                    f"y ∈ [{bounds['top']:.2f}, {bounds['bottom']:.2f}]）",
                    row["id"],
                    ["transform"],
                )
            )
        return findings


# ---------------------------------------------------------------- 一致性检查
#
# 「声明了却没人实现」是最危险的一种假合规：rules.json 看着有 40 条，
# 实际在跑的只有 38 条，而报告会照抄声明数。所以这里用源码扫描把两边对上。

_RULE_ID_PATTERN = re.compile(r"RULE_[A-Z]+(?:_[A-Z]+)*_\d{3}")

#: 会产出 rule id 的实现文件。新增实现文件必须加进来，否则一致性测试会把它当「未实现」。
IMPLEMENTATION_FILES = (
    os.path.join("core", "timeline_validator.py"),
    os.path.join("core", "rule_engine.py"),
)


def implemented_rule_ids(root: str) -> Dict[str, List[str]]:
    """扫描实现文件，返回 {rule_id: [出现的文件, ...]}。

    这是静态扫描，只能证明「代码里提到了这条规则」，
    不能证明「这条规则在某个输入下真的会命中」—— 后者由各自的用例测试负责。
    """
    found: Dict[str, List[str]] = {}
    for relative in IMPLEMENTATION_FILES:
        path = os.path.join(root, relative)
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        for rule_id in sorted(set(_RULE_ID_PATTERN.findall(text))):
            found.setdefault(rule_id, []).append(relative.replace("\\", "/"))
    return found


def consistency_report(root: str, rules_path: str) -> Dict[str, Any]:
    """声明 ↔ 实现的一致性报告。

    - declared_not_implemented：rules.json 写了但没人实现（假合规，必须为空）
    - implemented_not_declared：代码里在报但 rules.json 没声明（level 无来源，必须为空）
    - exemptions：只描述豁免条件、本身不产出问题的条目（允许没有实现）
    """
    definitions = load_rule_definitions(rules_path)
    implemented = implemented_rule_ids(root)
    exemptions = sorted(r.id for r in definitions.values() if r.is_exemption())
    declared = {r.id for r in definitions.values() if not r.is_exemption()}
    return {
        "declared": sorted(declared),
        "implemented": sorted(implemented),
        "exemptions": exemptions,
        "declared_not_implemented": sorted(declared - set(implemented)),
        "implemented_not_declared": sorted(set(implemented) - declared - set(exemptions)),
        "by_file": implemented,
    }


def rule_catalog(rules_path: str) -> List[Dict[str, Any]]:
    """给文档 / 能力目录用的规则全表，按 id 排序。"""
    definitions = load_rule_definitions(rules_path)
    rows: List[Dict[str, Any]] = []
    for rule_id in sorted(definitions):
        rule = definitions[rule_id]
        rows.append(
            {
                "id": rule.id,
                "category": rule.category,
                "level": rule.level,
                "kind": rule.kind,
                "description": rule.description,
            }
        )
    return rows


def group_by_category(rows: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """按规则族分组，文档里一族一节。"""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("category", "")), []).append(dict(row))
    return grouped
