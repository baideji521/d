"""Effect Library：特效定义。

分两类，type 严格区分（对应开发指令第十三条）：
- kind=program  程序特效，写入 Timeline 时 type="effect"，靠 name + params 描述
- kind=material 素材特效，写入 Timeline 时 type="overlay"，靠 asset 引用素材文件

每个特效都声明了完整的参数表（key / 类型 / 默认值 / 取值范围），
属性面板据此自动生成控件，JSON 里的 params 也严格按这张表来。
这样「什么效果对应什么参数」是被数据固定下来的，不靠记忆。

可以在 assets/effects/*.json 里放自定义特效，启动时会合并进来。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

# ------------------------------------------------------------------ 程序特效

PROGRAM_EFFECTS: List[Dict[str, Any]] = [
    {
        "name": "zoom",
        "label": "Zoom 推拉",
        "kind": "program",
        "category": "运动",
        "default_duration": 0.6,
        "description": "以指定中心点缩放画面，最常用的高光强调手法",
        "params": [
            {"key": "scale_from", "label": "起始 Scale", "type": "number", "default": 1.0, "min": 0.1, "max": 5.0, "step": 0.01},
            {"key": "scale_to", "label": "结束 Scale", "type": "number", "default": 1.35, "min": 0.1, "max": 5.0, "step": 0.01},
            {"key": "origin_x", "label": "中心 X", "type": "number", "default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01},
            {"key": "origin_y", "label": "中心 Y", "type": "number", "default": 0.45, "min": 0.0, "max": 1.0, "step": 0.01},
        ],
    },
    {
        "name": "shake",
        "label": "Shake 抖动",
        "kind": "program",
        "category": "运动",
        "default_duration": 0.4,
        "description": "按频率随机位移画面，制造冲击感",
        "params": [
            {"key": "amplitude", "label": "幅度（画面比例）", "type": "number", "default": 0.02, "min": 0.0, "max": 0.3, "step": 0.005},
            {"key": "frequency", "label": "频率（次/秒）", "type": "number", "default": 18.0, "min": 1.0, "max": 60.0, "step": 1.0},
            {"key": "rotation", "label": "附带旋转（度）", "type": "number", "default": 1.5, "min": 0.0, "max": 30.0, "step": 0.5},
        ],
    },
    {
        "name": "flash",
        "label": "Flash 闪白",
        "kind": "program",
        "category": "光效",
        "default_duration": 0.2,
        "description": "叠加一层纯色并快速衰减，常配合 Impact 音效",
        "params": [
            {"key": "color", "label": "颜色", "type": "color", "default": "#FFFFFF"},
            {"key": "intensity", "label": "强度", "type": "number", "default": 0.85, "min": 0.0, "max": 1.0, "step": 0.05},
            {"key": "decay", "label": "衰减曲线", "type": "enum", "default": "easeOut", "options": ["linear", "easeIn", "easeOut", "easeInOut"]},
        ],
    },
    {
        "name": "blur",
        "label": "Blur 模糊",
        "kind": "program",
        "category": "画质",
        "default_duration": 0.5,
        "description": "高斯模糊，从 from 值过渡到 to 值",
        "params": [
            {"key": "radius_from", "label": "起始半径 px", "type": "number", "default": 0.0, "min": 0.0, "max": 80.0, "step": 1.0},
            {"key": "radius_to", "label": "结束半径 px", "type": "number", "default": 12.0, "min": 0.0, "max": 80.0, "step": 1.0},
        ],
    },
    {
        "name": "glitch",
        "label": "Glitch 故障",
        "kind": "program",
        "category": "风格",
        "default_duration": 0.35,
        "description": "横向条带错位 + 颜色抖动",
        "params": [
            {"key": "intensity", "label": "强度", "type": "number", "default": 0.6, "min": 0.0, "max": 1.0, "step": 0.05},
            {"key": "slices", "label": "条带数量", "type": "int", "default": 12, "min": 2, "max": 60, "step": 1},
            {"key": "color_shift", "label": "颜色偏移 px", "type": "number", "default": 6.0, "min": 0.0, "max": 40.0, "step": 1.0},
        ],
    },
    {
        "name": "rgb_split",
        "label": "RGB Split 色差",
        "kind": "program",
        "category": "风格",
        "default_duration": 0.3,
        "description": "红蓝通道错开，制造强烈的冲击感",
        "params": [
            {"key": "offset", "label": "偏移 px", "type": "number", "default": 8.0, "min": 0.0, "max": 60.0, "step": 1.0},
            {"key": "angle", "label": "偏移角度", "type": "number", "default": 0.0, "min": 0.0, "max": 360.0, "step": 5.0},
        ],
    },
    {
        "name": "brightness",
        "label": "Brightness 亮度",
        "kind": "program",
        "category": "调色",
        "default_duration": 0.5,
        "description": "1.0 为原始亮度",
        "params": [
            {"key": "value_from", "label": "起始值", "type": "number", "default": 1.0, "min": 0.0, "max": 3.0, "step": 0.05},
            {"key": "value_to", "label": "结束值", "type": "number", "default": 1.4, "min": 0.0, "max": 3.0, "step": 0.05},
        ],
    },
    {
        "name": "contrast",
        "label": "Contrast 对比度",
        "kind": "program",
        "category": "调色",
        "default_duration": 0.5,
        "description": "1.0 为原始对比度",
        "params": [
            {"key": "value_from", "label": "起始值", "type": "number", "default": 1.0, "min": 0.0, "max": 3.0, "step": 0.05},
            {"key": "value_to", "label": "结束值", "type": "number", "default": 1.3, "min": 0.0, "max": 3.0, "step": 0.05},
        ],
    },
    {
        "name": "saturation",
        "label": "Saturation 饱和度",
        "kind": "program",
        "category": "调色",
        "default_duration": 0.5,
        "description": "0 为黑白，1.0 为原始饱和度",
        "params": [
            {"key": "value_from", "label": "起始值", "type": "number", "default": 1.0, "min": 0.0, "max": 3.0, "step": 0.05},
            {"key": "value_to", "label": "结束值", "type": "number", "default": 1.6, "min": 0.0, "max": 3.0, "step": 0.05},
        ],
    },
    {
        "name": "vignette",
        "label": "Vignette 暗角",
        "kind": "program",
        "category": "光效",
        "default_duration": 1.0,
        "description": "四周压暗，把注意力收到中心",
        "params": [
            {"key": "intensity", "label": "强度", "type": "number", "default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05},
            {"key": "radius", "label": "半径比例", "type": "number", "default": 0.75, "min": 0.1, "max": 1.5, "step": 0.05},
        ],
    },
    {
        "name": "motion_blur",
        "label": "Motion Blur 运动模糊",
        "kind": "program",
        "category": "画质",
        "default_duration": 0.3,
        "description": "沿指定方向拉伸模糊",
        "params": [
            {"key": "amount", "label": "强度 px", "type": "number", "default": 14.0, "min": 0.0, "max": 100.0, "step": 1.0},
            {"key": "angle", "label": "方向角度", "type": "number", "default": 0.0, "min": 0.0, "max": 360.0, "step": 5.0},
        ],
    },
    {
        "name": "spin",
        "label": "Spin 旋转",
        "kind": "program",
        "category": "运动",
        "default_duration": 0.5,
        "description": "画面整体旋转",
        "params": [
            {"key": "from", "label": "起始角度", "type": "number", "default": 0.0, "min": -720.0, "max": 720.0, "step": 5.0},
            {"key": "to", "label": "结束角度", "type": "number", "default": 15.0, "min": -720.0, "max": 720.0, "step": 5.0},
        ],
    },
    {
        "name": "bounce",
        "label": "Bounce 弹跳",
        "kind": "program",
        "category": "运动",
        "default_duration": 0.5,
        "description": "垂直方向弹跳衰减",
        "params": [
            {"key": "height", "label": "弹跳高度（画面比例）", "type": "number", "default": 0.08, "min": 0.0, "max": 0.5, "step": 0.01},
            {"key": "bounces", "label": "弹跳次数", "type": "int", "default": 2, "min": 1, "max": 8, "step": 1},
        ],
    },
    {
        "name": "pulse",
        "label": "Pulse 呼吸",
        "kind": "program",
        "category": "运动",
        "default_duration": 0.8,
        "description": "周期性缩放，适合持续强调",
        "params": [
            {"key": "scale_min", "label": "最小 Scale", "type": "number", "default": 1.0, "min": 0.1, "max": 3.0, "step": 0.01},
            {"key": "scale_max", "label": "最大 Scale", "type": "number", "default": 1.08, "min": 0.1, "max": 3.0, "step": 0.01},
            {"key": "cycles", "label": "周期数", "type": "int", "default": 2, "min": 1, "max": 10, "step": 1},
        ],
    },
]

# ------------------------------------------------------------------ 素材特效

_MATERIAL_PARAMS = [
    {"key": "asset", "label": "素材", "type": "asset", "default": "", "asset_type": "overlay", "hint": "从素材库选择叠加素材"},
    {"key": "scale", "label": "缩放", "type": "number", "default": 1.0, "min": 0.1, "max": 4.0, "step": 0.05},
    {"key": "opacity", "label": "不透明度", "type": "number", "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05},
    {"key": "blend", "label": "混合模式", "type": "enum", "default": "screen", "options": ["normal", "screen", "add"]},
]


def _material(name: str, label: str, duration: float, description: str) -> Dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "kind": "material",
        "category": "素材特效",
        "default_duration": duration,
        "blend": "screen",
        "description": description,
        "params": [dict(p) for p in _MATERIAL_PARAMS],
    }


MATERIAL_EFFECTS: List[Dict[str, Any]] = [
    _material("fire", "Fire 火焰", 1.2, "火焰素材叠加，建议放 V3/V4 轨"),
    _material("smoke", "Smoke 烟雾", 1.5, "烟雾素材叠加"),
    _material("explosion", "Explosion 爆炸", 0.8, "爆炸素材，常配 Impact 音效"),
    _material("spark", "Spark 火花", 0.6, "火花粒子"),
    _material("lightning", "Lightning 闪电", 0.5, "闪电，配合 Flash 效果更强"),
    _material("light_leak", "Light Leak 漏光", 1.0, "漏光素材，适合做转场衔接"),
    _material("particle", "Particle 粒子", 1.5, "通用粒子素材"),
    _material("speed_lines", "Speed Lines 速度线", 0.5, "速度线，强调运动方向"),
    _material("glow", "Glow 光晕", 0.8, "光晕素材"),
    _material("dust", "Dust 灰尘", 2.0, "空气尘埃，做氛围层"),
]


class EffectLibrary:
    """特效库。内置定义 + assets/effects 下的自定义 JSON。"""

    def __init__(self, assets_dir: str = "") -> None:
        self._effects: Dict[str, Dict[str, Any]] = {}
        for effect in PROGRAM_EFFECTS + MATERIAL_EFFECTS:
            self._effects[effect["name"]] = effect
        if assets_dir:
            self._load_custom(os.path.join(assets_dir, "effects"))

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
            for effect in data.get("effects", []):
                if effect.get("name"):
                    self._effects[effect["name"]] = effect

    # ------------------------------------------------------------ 查询

    def all(self) -> List[Dict[str, Any]]:
        return list(self._effects.values())

    def program_effects(self) -> List[Dict[str, Any]]:
        return [e for e in self._effects.values() if e.get("kind") == "program"]

    def material_effects(self) -> List[Dict[str, Any]]:
        return [e for e in self._effects.values() if e.get("kind") == "material"]

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        return self._effects.get(name)

    def has(self, name: str) -> bool:
        return name in self._effects

    def label_of(self, name: str) -> str:
        effect = self._effects.get(name)
        return effect.get("label", name) if effect else name

    def default_params(self, name: str) -> Dict[str, Any]:
        """按参数表生成一份默认 params，写进 Timeline JSON。"""
        effect = self._effects.get(name)
        if not effect:
            return {}
        return {p["key"]: p["default"] for p in effect.get("params", [])}

    def param_spec(self, name: str, key: str) -> Optional[Dict[str, Any]]:
        effect = self._effects.get(name)
        if not effect:
            return None
        for param in effect.get("params", []):
            if param.get("key") == key:
                return param
        return None

    def categories(self) -> List[str]:
        return sorted({e.get("category", "") for e in self._effects.values() if e.get("category")})

    def export_definitions(self) -> Dict[str, Any]:
        """导出给 Remotion 侧参考（渲染端按 name 分派，不依赖这份数据）。"""
        return {"version": 1, "effects": self.all()}
