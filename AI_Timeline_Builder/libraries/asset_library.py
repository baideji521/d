"""Asset Library：素材库的展示层封装。

AssetManager 负责扫描与清单读写（数据），本模块负责「怎么把素材组织给面板看」（视图逻辑），
以及把所有库打包成一个容器，方便 GUI 与校验器统一取用。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from libraries.animation_library import AnimationLibrary
from libraries.caption_library import CaptionLibrary
from libraries.effect_library import EffectLibrary
from libraries.sound_library import SoundLibrary
from libraries.template_library import TemplateLibrary
from libraries.transition_library import TransitionLibrary

# 素材库面板左侧的分类树。kind 决定点开后展示哪种数据源。
LIBRARY_SECTIONS = [
    {"key": "video", "label": "视频 Video", "kind": "asset", "asset_type": "video"},
    {"key": "image", "label": "图片 Image", "kind": "asset", "asset_type": "image"},
    {"key": "audio", "label": "音频 Audio", "kind": "asset", "asset_type": "audio"},
    {"key": "overlay", "label": "叠加 Overlay", "kind": "asset", "asset_type": "overlay"},
    {"key": "font", "label": "字体 Font", "kind": "asset", "asset_type": "font"},
    {"key": "effect", "label": "特效 Effect", "kind": "effect"},
    {"key": "transition", "label": "转场 Transition", "kind": "transition"},
    {"key": "caption", "label": "字幕 Caption", "kind": "caption"},
    {"key": "animation", "label": "动画 Animation", "kind": "animation"},
    {"key": "template", "label": "模板 Template", "kind": "template"},
]


class AssetLibrary:
    """素材的分组视图。"""

    def __init__(self, asset_manager) -> None:
        self._assets = asset_manager

    def sections(self) -> List[Dict[str, Any]]:
        return list(LIBRARY_SECTIONS)

    def items_for(self, section_key: str, keyword: str = "", category: str = "") -> List[Dict[str, Any]]:
        """返回某个分类下的素材（仅 kind=asset 的分类有效）。"""
        section = next((s for s in LIBRARY_SECTIONS if s["key"] == section_key), None)
        if not section or section["kind"] != "asset":
            return []
        return self._assets.search(keyword=keyword, asset_type=section["asset_type"], category=category)

    def categories_for(self, section_key: str) -> List[str]:
        section = next((s for s in LIBRARY_SECTIONS if s["key"] == section_key), None)
        if not section or section["kind"] != "asset":
            return []
        return self._assets.categories_of(section["asset_type"])

    def describe(self, asset: Dict[str, Any]) -> str:
        """素材列表项的副标题：时长 / 分辨率 / 帧率 / 格式 / 大小。"""
        parts: List[str] = [asset.get("id", "")]
        if asset.get("duration"):
            parts.append(f"{float(asset['duration']):.2f}s")
        if asset.get("width") and asset.get("height"):
            parts.append(f"{asset['width']}×{asset['height']}")
        if asset.get("fps"):
            parts.append(f"{asset['fps']:g}fps")
        fmt = self.format_of(asset)
        if fmt:
            parts.append(fmt)
        size = asset.get("size_bytes") or 0
        if size:
            parts.append(self.format_size(size))
        if asset.get("has_alpha"):
            parts.append("含透明通道")
        return "  ".join(parts)

    @staticmethod
    def format_of(asset: Dict[str, Any]) -> str:
        """容器格式。直接取扩展名——不解码文件，列表刷新才不会卡。"""
        ext = os.path.splitext(str(asset.get("path") or ""))[1]
        return ext.lstrip(".").upper()

    @staticmethod
    def format_size(size_bytes: int) -> str:
        value = float(size_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
            value /= 1024
        return f"{value:.1f}GB"

    def first_of_category(self, asset_type: str, category_keyword: str = "") -> Optional[Dict[str, Any]]:
        """找第一个匹配的素材，Demo 生成器与模板展开用来自动挑素材。"""
        candidates = self._assets.search(asset_type=asset_type)
        if category_keyword:
            keyword = category_keyword.lower()
            for asset in candidates:
                haystack = f"{asset.get('id','')} {asset.get('name','')} {asset.get('category','')}".lower()
                if keyword in haystack:
                    return asset
        return candidates[0] if candidates else None


class Libraries:
    """把所有库打包在一起，避免到处传五六个参数。"""

    def __init__(self, assets_dir: str, asset_manager) -> None:
        self.asset = AssetLibrary(asset_manager)
        self.effect = EffectLibrary(assets_dir)
        self.transition = TransitionLibrary(assets_dir)
        self.caption = CaptionLibrary(assets_dir)
        self.animation = AnimationLibrary(assets_dir)
        self.template = TemplateLibrary(assets_dir)
        self._asset_manager = asset_manager

    @property
    def sound(self) -> SoundLibrary:
        """音效库。每次取都按当前素材清单重建 —— 重新扫描之后不该还拿着旧快照。"""
        return SoundLibrary(self._asset_manager.all(), self._asset_manager.root)

    def as_dict(self) -> Dict[str, Any]:
        """给校验器用的映射。"""
        return {
            "effect": self.effect,
            "transition": self.transition,
            "caption": self.caption,
            "animation": self.animation,
            "template": self.template,
        }
