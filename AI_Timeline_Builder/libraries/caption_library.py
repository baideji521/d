"""Caption Library：字幕模板。

Caption 与 Text 是两个独立概念，模板不共用（对应开发指令第十一条）。
caption_style 决定渲染行为，style 决定外观：

- plain             整句显示
- word_by_word      逐词出现，出现后保留
- highlight_current 全句常显，当前词高亮
- karaoke           当前词从左到右填色
- char_by_char      逐字出现
- bounce            整句弹跳入场
- pop               整句缩放弹出
- two_line          上下双行滚动

用户在 GUI 里存的自定义模板会写到 assets/captions/*.json，启动时自动合并。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

CAPTION_STYLES = [
    ("plain", "普通字幕"),
    ("word_by_word", "逐词出现"),
    ("highlight_current", "当前词高亮"),
    ("karaoke", "卡拉OK 填色"),
    ("char_by_char", "逐字出现"),
    ("bounce", "弹跳入场"),
    ("pop", "Pop 缩放弹出"),
    ("two_line", "上下双行"),
]

CAPTION_STYLE_LABELS = dict(CAPTION_STYLES)

BUILTIN_TEMPLATES: List[Dict[str, Any]] = [
    {
        "name": "bold_white",
        "label": "白底黑边 粗体",
        "caption_style": "plain",
        "description": "最通用的字幕样式，黑边保证任何画面上都看得清",
        "style": {
            "fontFamily": "Arial",
            "fontSize": 64,
            "fontWeight": 900,
            "color": "#FFFFFF",
            "align": "center",
            "lineHeight": 1.2,
            "stroke": {"width": 8, "color": "#000000"},
            "shadow": {"x": 0, "y": 4, "blur": 8, "color": "rgba(0,0,0,0.6)"},
        },
        "transform": {"x": 0.5, "y": 0.82, "scale": 1.0, "rotation": 0, "opacity": 1},
    },
    {
        "name": "highlight_yellow",
        "label": "黄色高亮 当前词",
        "caption_style": "highlight_current",
        "description": "整句常显，当前词变黄放大，短视频标配",
        "style": {
            "fontFamily": "Arial",
            "fontSize": 64,
            "fontWeight": 900,
            "color": "#FFFFFF",
            "align": "center",
            "lineHeight": 1.2,
            "stroke": {"width": 8, "color": "#000000"},
        },
        "highlight": {"color": "#FFE347", "backgroundColor": "", "scale": 1.15},
        "transform": {"x": 0.5, "y": 0.8, "scale": 1.0, "rotation": 0, "opacity": 1},
    },
    {
        "name": "karaoke_green",
        "label": "卡拉OK 绿色填色",
        "caption_style": "karaoke",
        "description": "当前词从左到右填色，节奏感最强",
        "style": {
            "fontFamily": "Arial",
            "fontSize": 60,
            "fontWeight": 900,
            "color": "#FFFFFF",
            "align": "center",
            "stroke": {"width": 7, "color": "#000000"},
        },
        "highlight": {"color": "#3BE07C", "backgroundColor": "", "scale": 1.0},
        "transform": {"x": 0.5, "y": 0.8, "scale": 1.0, "rotation": 0, "opacity": 1},
    },
    {
        "name": "box_black",
        "label": "黑底色块",
        "caption_style": "plain",
        "description": "半透明黑底色块，适合信息量大的解说",
        "style": {
            "fontFamily": "Arial",
            "fontSize": 52,
            "fontWeight": 700,
            "color": "#FFFFFF",
            "backgroundColor": "rgba(0,0,0,0.65)",
            "align": "center",
            "letterSpacing": 1,
        },
        "transform": {"x": 0.5, "y": 0.85, "scale": 1.0, "rotation": 0, "opacity": 1},
    },
    {
        "name": "word_pop",
        "label": "逐词弹出",
        "caption_style": "word_by_word",
        "description": "词一个个蹦出来，配合鼓点",
        "style": {
            "fontFamily": "Arial",
            "fontSize": 72,
            "fontWeight": 900,
            "color": "#FFFFFF",
            "align": "center",
            "stroke": {"width": 9, "color": "#000000"},
        },
        "transform": {"x": 0.5, "y": 0.78, "scale": 1.0, "rotation": 0, "opacity": 1},
    },
    {
        "name": "char_typing",
        "label": "逐字打字机",
        "caption_style": "char_by_char",
        "description": "逐字出现，适合悬念铺垫",
        "style": {
            "fontFamily": "Consolas",
            "fontSize": 56,
            "fontWeight": 700,
            "color": "#E8FF59",
            "align": "center",
            "stroke": {"width": 5, "color": "#000000"},
        },
        "transform": {"x": 0.5, "y": 0.8, "scale": 1.0, "rotation": 0, "opacity": 1},
    },
    {
        "name": "bounce_big",
        "label": "大字弹跳",
        "caption_style": "bounce",
        "description": "整句弹跳入场，用在情绪最高点",
        "style": {
            "fontFamily": "Arial",
            "fontSize": 88,
            "fontWeight": 900,
            "color": "#FFFFFF",
            "align": "center",
            "stroke": {"width": 10, "color": "#FF3B3B"},
        },
        "transform": {"x": 0.5, "y": 0.5, "scale": 1.0, "rotation": 0, "opacity": 1},
    },
    {
        "name": "two_line_split",
        "label": "上下双行",
        "caption_style": "two_line",
        "description": "长句自动拆成两行显示",
        "style": {
            "fontFamily": "Arial",
            "fontSize": 54,
            "fontWeight": 800,
            "color": "#FFFFFF",
            "align": "center",
            "lineHeight": 1.35,
            "stroke": {"width": 7, "color": "#000000"},
        },
        "transform": {"x": 0.5, "y": 0.8, "scale": 1.0, "rotation": 0, "opacity": 1},
    },
]


class CaptionLibrary:
    """字幕模板库，支持把 GUI 里调好的样式存回 assets/captions/。"""

    def __init__(self, assets_dir: str = "") -> None:
        self._dir = os.path.join(assets_dir, "captions") if assets_dir else ""
        self._items: Dict[str, Dict[str, Any]] = {t["name"]: t for t in BUILTIN_TEMPLATES}
        self._builtin_names = set(self._items.keys())
        self.reload()

    def reload(self) -> None:
        """重新读取自定义模板。"""
        self._items = {t["name"]: t for t in BUILTIN_TEMPLATES}
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
            items = data.get("templates") or ([data] if data.get("name") else [])
            for item in items:
                if item.get("name"):
                    self._items[item["name"]] = item

    # ------------------------------------------------------------ 查询

    def all(self) -> List[Dict[str, Any]]:
        return list(self._items.values())

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        return self._items.get(name)

    def has(self, name: str) -> bool:
        return name in self._items

    def label_of(self, name: str) -> str:
        item = self._items.get(name)
        return item.get("label", name) if item else name

    def is_builtin(self, name: str) -> bool:
        return name in self._builtin_names

    # ------------------------------------------------------------ 保存

    def save_template(self, template: Dict[str, Any]) -> str:
        """把模板写到 assets/captions/<name>.json，返回文件路径。"""
        if not self._dir:
            return ""
        os.makedirs(self._dir, exist_ok=True)
        name = template.get("name") or f"caption_{int(time.time())}"
        template = dict(template)
        template["name"] = name
        path = os.path.join(self._dir, f"{name}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "templates": [template]}, handle, ensure_ascii=False, indent=2)
        self._items[name] = template
        return path

    def apply_to_element(self, element: Dict[str, Any], name: str) -> None:
        """把模板套到字幕元素上（就地修改 style / highlight / transform / caption_style）。"""
        template = self._items.get(name)
        if not template:
            return
        element["template"] = name
        element["caption_style"] = template.get("caption_style", "plain")
        element["style"] = json.loads(json.dumps(template.get("style", {})))
        if template.get("highlight"):
            element["highlight"] = json.loads(json.dumps(template["highlight"]))
        if template.get("transform"):
            element["transform"] = json.loads(json.dumps(template["transform"]))
