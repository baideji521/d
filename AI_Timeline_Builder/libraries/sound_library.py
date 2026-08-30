"""Sound Library：音效库。

这里严格区分两件**完全不同**的事：

1. **系统支持的音效类型**（`SFX_CATEGORIES`）
   协议层面的分类表，决定音效库面板有哪些分组、SFX 元素的 `category` 允许写什么。
   跟本地有没有文件无关——一个类型下 0 个文件也照样列出来，数量写 0。

2. **本地实际存在的音效文件**
   只来自 asset manifest，而且**必须文件真的在磁盘上**（`os.path.exists`）。
   目录名不算文件；清单里指向已删除文件的条目算 `missing()`，不算可用素材。

不做任何"看起来应该有"的推断，也不编造文件名。这条是硬约束：
文档与 AI 目录都从本模块取数，一旦允许推断，AI 就会引用不存在的音效。

本模块刻意不依赖 Qt，`AssetManager` 是 QObject，测试里没法随便建；
这里只吃 `list[dict]`，所以能直接拿 manifest 做单元测试。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Optional

__all__ = [
    "SFX_CATEGORIES",
    "CATEGORY_KEYS",
    "CATEGORY_LABELS",
    "SoundLibrary",
]


#: 系统支持的音效类型。
#:
#: `track` 是建议轨道，与 `gui/asset_placement.py` 的落轨策略保持一致：
#: 背景音乐 → A1，人声 / TTS → A2，其余音效 → A3。
SFX_CATEGORIES: List[Dict[str, str]] = [
    {"key": "bgm", "label": "背景音乐 BGM", "track": "A1",
     "description": "整段铺底的音乐，通常需要 fade in / out 与较低音量"},
    {"key": "tts", "label": "语音 / 配音", "track": "A2",
     "description": "TTS 合成或录制的人声旁白"},
    {"key": "boom", "label": "低频冲击 Boom", "track": "A3",
     "description": "重低音砸落，配合镜头切换或强调"},
    {"key": "impact", "label": "撞击 Impact", "track": "A3",
     "description": "打击、爆点，最常用的卡点音效"},
    {"key": "whoosh", "label": "呼啸 Whoosh", "track": "A3",
     "description": "快速划过的风声，配合甩镜 / 位移转场"},
    {"key": "riser", "label": "上升 Riser", "track": "A3",
     "description": "情绪上扬的铺垫音，落点前使用"},
    {"key": "glass", "label": "玻璃 Glass", "track": "A3",
     "description": "玻璃碎裂 / 清脆质感"},
    {"key": "metal", "label": "金属 Metal", "track": "A3",
     "description": "金属碰撞、刀剑质感"},
    {"key": "wood", "label": "木质 Wood", "track": "A3",
     "description": "木头敲击、闷响质感"},
    {"key": "footstep", "label": "脚步 Footstep", "track": "A3",
     "description": "不同地面的脚步声，做拟音用"},
    {"key": "ui", "label": "界面 UI", "track": "A3",
     "description": "点击、切换、提示等短音，做转场点缀"},
    {"key": "soft", "label": "轻柔 Soft", "track": "A3",
     "description": "柔和的短音，适合字幕出现 / 轻提示"},
    {"key": "imported", "label": "导入 Imported", "track": "A3",
     "description": "用户从外部导入的音频，未归类"},
]

CATEGORY_KEYS = tuple(item["key"] for item in SFX_CATEGORIES)
CATEGORY_LABELS: Dict[str, str] = {item["key"]: item["label"] for item in SFX_CATEGORIES}

#: 未登记在分类表里的音频，统一归到这个建议轨道。
_FALLBACK_TRACK = "A3"


class SoundLibrary:
    """音效库：支持的类型 + 本地真实存在的文件。

    `assets` 是 asset manifest 里的素材列表（`AssetManager.all()` 或
    `asset_manifest.json` 的 `assets` 字段都行），非 audio 的条目会被忽略。
    `root` 是相对路径的基准目录（仓库根），空字符串表示按进程当前目录解析。
    """

    def __init__(self, assets: Iterable[Dict[str, Any]], root: str = "") -> None:
        self._root = root or ""
        self._audio: List[Dict[str, Any]] = [
            dict(a) for a in (assets or []) if isinstance(a, dict) and a.get("type") == "audio"
        ]

    # ------------------------------------------------------------ 构造

    @classmethod
    def from_manifest(cls, manifest_path: str) -> "SoundLibrary":
        """从 `asset_manifest.json` 读。清单读不出来就当成空库，不抛异常。"""
        root = os.path.dirname(os.path.abspath(manifest_path))
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            return cls([], root)
        assets = payload.get("assets") if isinstance(payload, dict) else payload
        if not isinstance(assets, list):
            assets = []
        return cls(assets, root)

    # ------------------------------------------------------------ 支持的类型

    def categories(self) -> List[Dict[str, str]]:
        """系统支持的音效类型（与本地文件无关）。"""
        return [dict(item) for item in SFX_CATEGORIES]

    def category(self, key: str) -> Optional[Dict[str, str]]:
        for item in SFX_CATEGORIES:
            if item["key"] == key:
                return dict(item)
        return None

    def label_of(self, key: str) -> str:
        return CATEGORY_LABELS.get(key, key)

    def track_for(self, key: str) -> str:
        """该类型的建议轨道。未登记的类型退回 A3。"""
        item = self.category(key)
        return item["track"] if item else _FALLBACK_TRACK

    def supports(self, key: str) -> bool:
        return key in CATEGORY_LABELS

    # ------------------------------------------------------------ 本地文件

    def _exists(self, asset: Dict[str, Any]) -> bool:
        path = str(asset.get("path") or "")
        if not path:
            return False
        if not os.path.isabs(path) and self._root:
            path = os.path.join(self._root, path)
        return os.path.exists(path)

    def files(self, category: str = "") -> List[Dict[str, Any]]:
        """本地真实存在的音频文件。`category` 为空表示全部。"""
        rows = [a for a in self._audio if self._exists(a)]
        if category:
            rows = [a for a in rows if a.get("category") == category]
        return sorted(rows, key=lambda a: str(a.get("id") or ""))

    def missing(self) -> List[Dict[str, Any]]:
        """清单里有、磁盘上没有的条目。必须显式暴露，不能静默当成可用。"""
        return sorted(
            (a for a in self._audio if not self._exists(a)),
            key=lambda a: str(a.get("id") or ""),
        )

    def count_by_category(self) -> Dict[str, int]:
        """每个**支持的类型**下的本地文件数，没有文件就是 0。"""
        counts = {key: 0 for key in CATEGORY_KEYS}
        for asset in self.files():
            key = str(asset.get("category") or "")
            counts[key] = counts.get(key, 0) + 1
        return counts

    def unknown_categories(self) -> List[str]:
        """本地文件用了、但分类表里没登记的 category。用来提醒分类表该补了。"""
        used = {str(a.get("category") or "") for a in self.files()}
        return sorted(k for k in used if k and k not in CATEGORY_LABELS)

    def total(self) -> int:
        return len(self.files())

    def first_of(self, category: str) -> Optional[Dict[str, Any]]:
        """挑该类型下第一个可用文件，Demo / 验收生成器用。没有就返回 None。"""
        rows = self.files(category)
        return rows[0] if rows else None

    # ------------------------------------------------------------ 汇总

    def describe(self, asset: Dict[str, Any]) -> str:
        """列表项副标题：时长 + 类型标签。"""
        parts = [str(asset.get("id") or "")]
        duration = asset.get("duration")
        if isinstance(duration, (int, float)) and duration > 0:
            parts.append(f"{float(duration):.3f}s")
        parts.append(self.label_of(str(asset.get("category") or "")))
        return "  ".join(p for p in parts if p)

    def summary(self) -> Dict[str, Any]:
        """给文档与 AI 目录用的结构化汇总。"""
        counts = self.count_by_category()
        return {
            "supported_categories": self.categories(),
            "local_file_count": self.total(),
            "count_by_category": counts,
            "categories_without_local_file": [k for k in CATEGORY_KEYS if not counts.get(k)],
            "unknown_categories": self.unknown_categories(),
            "missing_files": [str(a.get("path") or "") for a in self.missing()],
        }
