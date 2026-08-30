"""Transition Library：转场定义。

转场在 Timeline JSON 里是 type="transition" 的元素，必须绑定 from / to 两个 Video Clip。
start 通常取 from 片段结束前 duration 的位置，GUI 拖动两个 Clip 交界处即可调整长度。

可以在 assets/transitions/*.json 里追加自定义转场。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

_DIRECTIONS = ["left", "right", "up", "down"]

BUILTIN_TRANSITIONS: List[Dict[str, Any]] = [
    {
        "name": "fade",
        "label": "Fade 淡入淡出",
        "category": "基础",
        "default_duration": 0.5,
        "description": "经过纯色过渡，最稳的接法",
        "params": [
            {"key": "color", "label": "过渡颜色", "type": "color", "default": "#000000"},
        ],
    },
    {
        "name": "crossfade",
        "label": "Crossfade 交叉溶解",
        "category": "基础",
        "default_duration": 0.5,
        "description": "两个片段直接叠化，没有中间色",
        "params": [
            {"key": "easing", "label": "缓动", "type": "enum", "default": "easeInOut", "options": ["linear", "easeIn", "easeOut", "easeInOut"]},
        ],
    },
    {
        "name": "flash",
        "label": "Flash 闪白转场",
        "category": "冲击",
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
        "category": "冲击",
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
        "category": "冲击",
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
        "category": "几何",
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
        "category": "几何",
        "default_duration": 0.5,
        "description": "新片段滑入，旧片段不动",
        "params": [
            {"key": "direction", "label": "方向", "type": "enum", "default": "left", "options": _DIRECTIONS},
        ],
    },
    {
        "name": "push",
        "label": "Push 推移",
        "category": "几何",
        "default_duration": 0.5,
        "description": "新片段把旧片段推出画面",
        "params": [
            {"key": "direction", "label": "方向", "type": "enum", "default": "left", "options": _DIRECTIONS},
        ],
    },
    {
        "name": "spin",
        "label": "Spin 旋转转场",
        "category": "风格",
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
        "category": "风格",
        "default_duration": 0.5,
        "description": "两边都模糊到最大再恢复",
        "params": [
            {"key": "amount", "label": "最大模糊 px", "type": "number", "default": 24.0, "min": 0.0, "max": 120.0, "step": 2.0},
        ],
    },
    {
        "name": "glitch",
        "label": "Glitch 故障转场",
        "category": "风格",
        "default_duration": 0.35,
        "description": "条带错位切换",
        "params": [
            {"key": "intensity", "label": "强度", "type": "number", "default": 0.7, "min": 0.0, "max": 1.0, "step": 0.05},
            {"key": "slices", "label": "条带数量", "type": "int", "default": 14, "min": 2, "max": 60, "step": 1},
        ],
    },
]


class TransitionLibrary:
    """转场库。"""

    def __init__(self, assets_dir: str = "") -> None:
        self._items: Dict[str, Dict[str, Any]] = {t["name"]: t for t in BUILTIN_TRANSITIONS}
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
                if item.get("name"):
                    self._items[item["name"]] = item

    def all(self) -> List[Dict[str, Any]]:
        return list(self._items.values())

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        return self._items.get(name)

    def has(self, name: str) -> bool:
        return name in self._items

    def label_of(self, name: str) -> str:
        item = self._items.get(name)
        return item.get("label", name) if item else name

    def default_params(self, name: str) -> Dict[str, Any]:
        item = self._items.get(name)
        if not item:
            return {}
        return {p["key"]: p["default"] for p in item.get("params", [])}

    def default_duration(self, name: str) -> float:
        item = self._items.get(name)
        return float(item.get("default_duration", 0.5)) if item else 0.5

    def param_spec(self, name: str, key: str) -> Optional[Dict[str, Any]]:
        item = self._items.get(name)
        if not item:
            return None
        for param in item.get("params", []):
            if param.get("key") == key:
                return param
        return None

    def categories(self) -> List[str]:
        return sorted({t.get("category", "") for t in self._items.values() if t.get("category")})
