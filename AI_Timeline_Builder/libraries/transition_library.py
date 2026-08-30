"""Transition Library：内置转场数据 + 加载入口。

转场在 Timeline JSON 里是 type="transition" 的元素，必须绑定 from / to 两个 Video Clip。
start 通常取 from 片段结束前 duration/2 的位置，GUI 拖动两个 Clip 交界处即可调整长度。

可以在 assets/transitions/*.json 里追加自定义转场。

结构化能力（分类 / supported_from / supported_to / renderer / 参数校验）全部在
libraries/transition_registry.py，本文件只提供数据与加载。
TransitionLibrary 就是一个预填了内置定义的 TransitionRegistry。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from libraries.transition_registry import TransitionDefinition, TransitionRegistry

_DIRECTIONS = ["left", "right", "up", "down"]

#: 转场两侧允许的元素 type。
#: 这不是凭空设的限制：remotion/src/effects/TransitionLayer.tsx 的 side()
#: 用 VideoLayer 渲染两侧，而 VideoLayer 只认 video（走 asset）和 freeze（走 target）。
#: 文字 / 字幕 / overlay 交给它会画不出东西，所以不列入。
SUPPORTED_SIDES: List[str] = ["video", "freeze"]

#: name → 标准分类。renderer 名一律等于 name，见 _decorate()。
_TRANSITION_CATEGORIES: Dict[str, str] = {
    "fade": "basic",
    "crossfade": "basic",
    "flash": "impact",
    "whip": "impact",
    "zoom": "impact",
    "wipe": "geometric",
    "slide": "geometric",
    "push": "geometric",
    "spin": "stylized",
    "blur": "stylized",
    "glitch": "stylized",
}


BUILTIN_TRANSITIONS: List[Dict[str, Any]] = [
    {
        "name": "fade",
        "label": "Fade 淡入淡出",
        "display_category": "基础",
        "default_duration": 0.5,
        "description": "经过纯色过渡，最稳的接法",
        "params": [
            {"key": "color", "label": "过渡颜色", "type": "color", "default": "#000000"},
        ],
    },
    {
        "name": "crossfade",
        "label": "Crossfade 交叉溶解",
        "display_category": "基础",
        "default_duration": 0.5,
        "description": "两个片段直接叠化，没有中间色",
        "params": [
            {"key": "easing", "label": "缓动", "type": "enum", "default": "easeInOut", "options": ["linear", "easeIn", "easeOut", "easeInOut"]},
        ],
    },
    {
        "name": "flash",
        "label": "Flash 闪白转场",
        "display_category": "冲击",
        "default_duration": 0.3,
        "description": "闪白过渡，节奏点上最常用",
        "params": [
            {"key": "color", "label": "闪光颜色", "type": "color", "default": "#FFFFFF"},
            {"key": "intensity", "label": "强度", "type": "number", "default": 0.9, "min": 0.0, "max": 1.0, "step": 0.05},
        ],
    },
    {
        "name": "whip",
        "label": "Whip 甩镜",
        "display_category": "冲击",
        "default_duration": 0.5,
        "description": "带模糊的快速横甩，短视频里出现频率最高",
        "params": [
            {"key": "direction", "label": "方向", "type": "enum", "default": "left", "options": _DIRECTIONS},
            {"key": "intensity", "label": "位移强度", "type": "number", "default": 0.8, "min": 0.0, "max": 2.0, "step": 0.05},
            {"key": "blur", "label": "模糊量", "type": "number", "default": 0.6, "min": 0.0, "max": 2.0, "step": 0.05},
        ],
    },
    {
        "name": "zoom",
        "label": "Zoom 缩放转场",
        "display_category": "冲击",
        "default_duration": 0.4,
        "description": "前一段推进、后一段拉出",
        "params": [
            {"key": "scale", "label": "缩放倍数", "type": "number", "default": 1.6, "min": 1.0, "max": 5.0, "step": 0.1},
            {"key": "blur", "label": "模糊量", "type": "number", "default": 0.3, "min": 0.0, "max": 2.0, "step": 0.05},
        ],
    },
    {
        "name": "wipe",
        "label": "Wipe 擦除",
        "display_category": "几何",
        "default_duration": 0.5,
        "description": "沿方向用硬边擦过",
        "params": [
            {"key": "direction", "label": "方向", "type": "enum", "default": "left", "options": _DIRECTIONS},
            {"key": "feather", "label": "边缘羽化 px", "type": "number", "default": 20.0, "min": 0.0, "max": 200.0, "step": 5.0},
        ],
    },
    {
        "name": "slide",
        "label": "Slide 滑入",
        "display_category": "几何",
        "default_duration": 0.5,
        "description": "新片段滑入，旧片段不动",
        "params": [
            {"key": "direction", "label": "方向", "type": "enum", "default": "left", "options": _DIRECTIONS},
        ],
    },
    {
        "name": "push",
        "label": "Push 推移",
        "display_category": "几何",
        "default_duration": 0.5,
        "description": "新片段把旧片段推出画面",
        "params": [
            {"key": "direction", "label": "方向", "type": "enum", "default": "left", "options": _DIRECTIONS},
        ],
    },
    {
        "name": "spin",
        "label": "Spin 旋转转场",
        "display_category": "风格",
        "default_duration": 0.5,
        "description": "旋转叠加缩放",
        "params": [
            {"key": "angle", "label": "旋转角度", "type": "number", "default": 90.0, "min": -720.0, "max": 720.0, "step": 15.0},
            {"key": "scale", "label": "缩放倍数", "type": "number", "default": 1.3, "min": 1.0, "max": 4.0, "step": 0.1},
        ],
    },
    {
        "name": "blur",
        "label": "Blur 模糊转场",
        "display_category": "风格",
        "default_duration": 0.5,
        "description": "两边都模糊到最大再恢复",
        "params": [
            {"key": "amount", "label": "最大模糊 px", "type": "number", "default": 24.0, "min": 0.0, "max": 120.0, "step": 2.0},
        ],
    },
    {
        "name": "glitch",
        "label": "Glitch 故障转场",
        "display_category": "风格",
        "default_duration": 0.35,
        "description": "条带错位切换",
        "params": [
            {"key": "intensity", "label": "强度", "type": "number", "default": 0.7, "min": 0.0, "max": 1.0, "step": 0.05},
            {"key": "slices", "label": "条带数量", "type": "int", "default": 14, "min": 2, "max": 60, "step": 1},
        ],
    },
]


def _decorate(item: Dict[str, Any]) -> Dict[str, Any]:
    """给内置转场补上标准分类 / renderer / supported_from / supported_to。

    renderer 名一律等于 name —— 两侧靠这个字符串对接，
    remotion/src/transitions/index.ts 注册的键必须与之一致。
    """
    item["category"] = _TRANSITION_CATEGORIES.get(item["name"], "basic")
    item["renderer"] = item["name"]
    item["supported_from"] = list(SUPPORTED_SIDES)
    item["supported_to"] = list(SUPPORTED_SIDES)
    return item


for _item in BUILTIN_TRANSITIONS:
    _decorate(_item)


class TransitionLibrary(TransitionRegistry):
    """转场库：内置定义 + assets/transitions 下的自定义 JSON。

    继承 TransitionRegistry，所以同时具备 register / unregister / validate /
    validate_pair / categories 等结构化能力。
    """

    def __init__(self, assets_dir: str = "") -> None:
        super().__init__(BUILTIN_TRANSITIONS)
        if assets_dir:
            self._load_custom(os.path.join(assets_dir, "transitions"))

    def _load_custom(self, directory: str) -> None:
        if not os.path.isdir(directory):
            return
        for entry in sorted(os.listdir(directory)):
            if not entry.endswith(".json"):
                continue
            try:
                with open(os.path.join(directory, entry), "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            for item in data.get("transitions", []):
                self.register(item)

    # ------------------------------------------------------------ 查询

    def label_of(self, name: str) -> str:
        item = self.get(name)
        return item.display_name if item else name

    def default_params(self, name: str) -> Dict[str, Any]:
        item = self.get(name)
        return item.default_params() if item else {}

    def default_duration(self, name: str) -> float:
        item = self.get(name)
        return item.default_duration if item else 0.5

    def param_spec(self, name: str, key: str) -> Optional[Dict[str, Any]]:
        item = self.get(name)
        return item.parameter(key) if item else None

    def display_categories(self) -> List[str]:
        """GUI 库面板用的中文分组。"""
        return sorted({t.display_category for t in self.all() if t.display_category})

