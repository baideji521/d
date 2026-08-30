"""Template Library：模板 = 多个元素 + 参数 + 时间关系的组合。

模板不是素材，拖进 Timeline 后会展开成若干真实元素。
每个子元素用 offset 表示「相对模板落点的秒数」，展开时 start = 落点 + offset。

展开产物必须是完全普通的 Timeline 元素 —— 展开之后模板就不存在了，
JSON 里看不到任何「模板」的痕迹。这样保证 Schema 只有一套。

自定义模板放 assets/templates/*.json。
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any, Callable, Dict, List, Optional

BUILTIN_TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "template_high_point",
        "name": "高光冲击",
        "description": "Freeze + Zoom + Impact 音效 + Caption + Flash，短视频高光点标准组合",
        "duration": 1.5,
        "elements": [
            {"type": "freeze", "offset": 0.0, "duration": 1.2, "track": "V1"},
            {
                "type": "effect",
                "name": "zoom",
                "offset": 0.0,
                "duration": 0.6,
                "track": "V1",
                "params": {"scale_from": 1.0, "scale_to": 1.35, "origin_x": 0.5, "origin_y": 0.45},
            },
            {
                "type": "effect",
                "name": "flash",
                "offset": 0.0,
                "duration": 0.2,
                "track": "V1",
                "params": {"color": "#FFFFFF", "intensity": 0.85, "decay": "easeOut"},
            },
            {"type": "audio", "asset_role": "impact", "offset": 0.0, "duration": 0.8, "track": "A3", "volume": 0.9},
            {
                "type": "caption",
                "template": "bounce_big",
                "offset": 0.1,
                "duration": 1.0,
                "track": "T1",
                "text": "就是这里",
            },
        ],
    },
    {
        "id": "template_shock_cut",
        "name": "震撼切点",
        "description": "Shake + RGB Split + 速度线素材 + 短促文字",
        "duration": 0.8,
        "elements": [
            {
                "type": "effect",
                "name": "shake",
                "offset": 0.0,
                "duration": 0.4,
                "track": "V1",
                "params": {"amplitude": 0.025, "frequency": 22.0, "rotation": 2.0},
            },
            {
                "type": "effect",
                "name": "rgb_split",
                "offset": 0.0,
                "duration": 0.3,
                "track": "V1",
                "params": {"offset": 10.0, "angle": 0.0},
            },
            {
                "type": "text",
                "offset": 0.05,
                "duration": 0.6,
                "track": "T2",
                "text": "WHAT?!",
                "animation": "anim_punch_in",
            },
        ],
    },
    {
        "id": "template_intro_title",
        "name": "开场标题",
        "description": "Punch In 标题 + Vignette + 逐词字幕",
        "duration": 2.5,
        "elements": [
            {
                "type": "text",
                "offset": 0.0,
                "duration": 2.0,
                "track": "T2",
                "text": "标题在这里",
                "animation": "anim_punch_in",
            },
            {
                "type": "effect",
                "name": "vignette",
                "offset": 0.0,
                "duration": 2.5,
                "track": "V1",
                "params": {"intensity": 0.45, "radius": 0.8},
            },
            {
                "type": "caption",
                "template": "bold_white",
                "offset": 1.0,
                "duration": 1.5,
                "track": "T1",
                "text": "副标题说明",
            },
        ],
    },
    {
        "id": "template_slow_emphasis",
        "name": "慢放强调",
        "description": "Pulse 呼吸 + 光晕素材 + 黑底字幕",
        "duration": 2.0,
        "elements": [
            {
                "type": "effect",
                "name": "pulse",
                "offset": 0.0,
                "duration": 1.6,
                "track": "V1",
                "params": {"scale_min": 1.0, "scale_max": 1.06, "cycles": 2},
            },
            {
                "type": "effect",
                "name": "brightness",
                "offset": 0.0,
                "duration": 1.6,
                "track": "V1",
                "params": {"value_from": 1.0, "value_to": 1.2},
            },
            {
                "type": "caption",
                "template": "box_black",
                "offset": 0.2,
                "duration": 1.6,
                "track": "T1",
                "text": "注意这个细节",
            },
        ],
    },
]


class TemplateLibrary:
    """模板库。展开逻辑集中在 expand()。"""

    def __init__(self, assets_dir: str = "") -> None:
        self._dir = os.path.join(assets_dir, "templates") if assets_dir else ""
        self._items: Dict[str, Dict[str, Any]] = {t["id"]: t for t in BUILTIN_TEMPLATES}
        self._load_custom()

    def _load_custom(self) -> None:
        if not self._dir or not os.path.isdir(self._dir):
            return
        for entry in sorted(os.listdir(self._dir)):
            if not entry.endswith(".json"):
                continue
            try:
                with open(os.path.join(self._dir, entry), "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            items = data.get("templates") or ([data] if data.get("id") else [])
            for item in items:
                if item.get("id"):
                    self._items[item["id"]] = item

    # ------------------------------------------------------------ 查询

    def all(self) -> List[Dict[str, Any]]:
        return list(self._items.values())

    def get(self, template_id: str) -> Optional[Dict[str, Any]]:
        return self._items.get(template_id)

    def has(self, template_id: str) -> bool:
        return template_id in self._items

    def label_of(self, template_id: str) -> str:
        item = self._items.get(template_id)
        return item.get("name", template_id) if item else template_id

    # ------------------------------------------------------------ 展开

    def expand(
        self,
        template_id: str,
        at_time: float,
        context: Dict[str, Any],
        make_id: Callable[[str], str],
    ) -> List[Dict[str, Any]]:
        """把模板展开成 Timeline 元素列表。

        context 需要提供：
        - base_clip_id  落点所在的视频片段 id（Freeze / Effect target 用）
        - base_source_time  该片段在落点处对应的源素材时间（Freeze 用）
        - impact_asset  Impact 类音效的 asset id（可为空，为空则跳过音频元素）
        - caption_library / animation_library  用于套用样式与关键帧
        make_id 由调用方提供，保证 id 不与现有元素冲突。
        """
        template = self._items.get(template_id)
        if not template:
            return []

        from core import timeline as tl  # 延迟导入避免循环依赖

        caption_library = context.get("caption_library")
        animation_library = context.get("animation_library")
        base_clip_id = context.get("base_clip_id", "")
        base_source_time = float(context.get("base_source_time", 0.0))
        impact_asset = context.get("impact_asset", "")

        result: List[Dict[str, Any]] = []
        for spec in template.get("elements", []):
            etype = spec.get("type")
            offset = float(spec.get("offset", 0.0))
            start = round(at_time + offset, 3)
            duration = float(spec.get("duration", 1.0))
            track = spec.get("track") or "V1"

            if etype == "freeze":
                if not base_clip_id:
                    continue
                element = tl.make_freeze(
                    make_id("freeze"), base_clip_id, base_source_time, start, duration, track
                )
            elif etype == "effect":
                element = tl.make_effect(
                    make_id("effect"),
                    spec.get("name", ""),
                    spec.get("params", {}),
                    track,
                    start,
                    duration,
                    target=base_clip_id or None,
                )
            elif etype == "audio":
                asset_id = spec.get("asset") or impact_asset
                if not asset_id:
                    continue
                element = tl.make_audio(
                    make_id("audio"), asset_id, track, start, duration, 0.0, float(spec.get("volume", 1.0))
                )
            elif etype == "caption":
                element = tl.make_caption(
                    make_id("caption"),
                    spec.get("text", ""),
                    track,
                    start,
                    duration,
                    template=spec.get("template", "bold_white"),
                )
                if caption_library is not None:
                    caption_library.apply_to_element(element, element["template"])
            elif etype == "text":
                element = tl.make_text(make_id("text"), spec.get("text", ""), track, start, duration)
            elif etype == "overlay":
                asset_id = spec.get("asset", "")
                if not asset_id:
                    continue
                element = tl.make_overlay(make_id("overlay"), asset_id, track, start, duration)
            else:
                continue

            # 模板可以直接指定一个动画预设
            animation_id = spec.get("animation")
            if animation_id and animation_library is not None and animation_library.has(animation_id):
                element["keyframes"] = animation_library.scaled_keyframes(
                    animation_id, min(duration, float(animation_library.get(animation_id)["duration"]))
                )
                element["animation"] = animation_id

            element["label"] = f"{template.get('name', template_id)}·{spec.get('type')}"
            result.append(element)

        return result

    # ------------------------------------------------------------ 保存

    def save_template(self, template: Dict[str, Any]) -> str:
        """把当前选中的若干元素存成模板。"""
        if not self._dir:
            return ""
        os.makedirs(self._dir, exist_ok=True)
        template_id = template.get("id") or "template_custom"
        template = copy.deepcopy(template)
        template["id"] = template_id
        path = os.path.join(self._dir, f"{template_id}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "templates": [template]}, handle, ensure_ascii=False, indent=2)
        self._items[template_id] = template
        return path

    @staticmethod
    def build_from_elements(
        template_id: str,
        name: str,
        elements: List[Dict[str, Any]],
        description: str = "",
    ) -> Dict[str, Any]:
        """把一批 Timeline 元素反向抽成模板定义（offset 相对最早元素）。"""
        if not elements:
            return {}
        base = min(float(e.get("start", 0.0)) for e in elements)
        end = max(float(e.get("start", 0.0)) + float(e.get("duration", 0.0)) for e in elements)
        specs: List[Dict[str, Any]] = []
        for element in sorted(elements, key=lambda e: float(e.get("start", 0.0))):
            spec: Dict[str, Any] = {
                "type": element.get("type"),
                "offset": round(float(element.get("start", 0.0)) - base, 3),
                "duration": round(float(element.get("duration", 0.0)), 3),
                "track": element.get("track"),
            }
            if element.get("name"):
                spec["name"] = element["name"]
            if element.get("params"):
                spec["params"] = copy.deepcopy(element["params"])
            if element.get("template"):
                spec["template"] = element["template"]
            if element.get("animation"):
                spec["animation"] = element["animation"]
            text = (element.get("content") or {}).get("text")
            if text:
                spec["text"] = text
            if element.get("type") == "audio":
                spec["asset_role"] = "impact"
                spec["volume"] = element.get("volume", 1.0)
            specs.append(spec)
        return {
            "id": template_id,
            "name": name,
            "description": description,
            "duration": round(end - base, 3),
            "elements": specs,
        }
