"""Asset Registry：素材的**语义分类**层。

已有两层：

    core/asset_manager.py   扫磁盘、探时长/分辨率、写 asset_manifest.json（数据）
    libraries/asset_library.py  面板怎么分组、怎么显示副标题（视图）

这一层解决的是第三个问题：**AI 与规则引擎需要的语义类型**。

清单里的 `type` 只有 video / image / audio / overlay / font 五种，
但「一段 BGM」「一声 whoosh 音效」「一句配音」在剪辑语义上完全不同 ——
它们该落到不同轨道、时长约束不同、AI 挑素材时的意图也不同。
所以这里在物理类型之上再推一层语义类型：

    audio + category=bgm           → music
    audio + category=tts/voice     → voice
    audio + 其它                    → sfx
    overlay + 目录在 transitions/   → transition_material
    overlay + 目录在 effects/       → effect_material
    image  + 目录在 overlays/       → sticker

推断只看清单里已有的 `type` / `path` / `category`，**不去猜文件内容**，
也不写回清单 —— 清单仍然由 AssetManager 独占。

本模块不依赖 PyQt，纯函数 + 一个查询类，测试与文档生成器都能直接用。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Optional

#: 语义类型全表。顺序即文档 / GUI 里的展示顺序。
SEMANTIC_TYPES: List[Dict[str, str]] = [
    {"key": "video", "label": "视频 Video", "element_type": "video", "track": "V1"},
    {"key": "image", "label": "图片 Image", "element_type": "overlay", "track": "V3"},
    {"key": "sticker", "label": "贴纸 Sticker", "element_type": "overlay", "track": "V3"},
    {"key": "overlay", "label": "叠加素材 Overlay", "element_type": "overlay", "track": "V3"},
    {
        "key": "transition_material",
        "label": "转场素材 Transition Material",
        "element_type": "overlay",
        "track": "V4",
    },
    {
        "key": "effect_material",
        "label": "特效素材 Effect Material",
        "element_type": "overlay",
        "track": "V4",
    },
    {"key": "music", "label": "音乐 BGM", "element_type": "audio", "track": "A1"},
    {"key": "voice", "label": "人声 Voice", "element_type": "audio", "track": "A2"},
    {"key": "sfx", "label": "音效 SFX", "element_type": "audio", "track": "A3"},
    {"key": "font", "label": "字体 Font", "element_type": "", "track": ""},
]

SEMANTIC_KEYS = tuple(item["key"] for item in SEMANTIC_TYPES)
SEMANTIC_LABELS: Dict[str, str] = {item["key"]: item["label"] for item in SEMANTIC_TYPES}
#: 语义类型 → 写进 Timeline 时的元素 type（font 不进时间线，为空）
ELEMENT_TYPE_OF: Dict[str, str] = {item["key"]: item["element_type"] for item in SEMANTIC_TYPES}
#: 语义类型 → 建议落轨
DEFAULT_TRACK_OF: Dict[str, str] = {item["key"]: item["track"] for item in SEMANTIC_TYPES}

#: category 命中这些词就算音乐 / 人声，其余音频一律算音效
MUSIC_CATEGORIES = ("bgm", "music")
VOICE_CATEGORIES = ("tts", "voice", "vo", "narration")

#: 目录名 → overlay / image 的语义类型
DIR_SEMANTICS = {
    "transitions": "transition_material",
    "effects": "effect_material",
    "overlays": "sticker",
}


def _relative_parts(path: str) -> List[str]:
    return [part for part in str(path or "").replace("\\", "/").split("/") if part]


def semantic_type(asset: Dict[str, Any]) -> str:
    """推断素材的语义类型。认不出来就退回物理 type，绝不抛异常。"""
    physical = str(asset.get("type", "") or "")
    category = str(asset.get("category", "") or "").lower()
    parts = _relative_parts(asset.get("path"))
    # parts 形如 ["assets", "audio", "bgm", "bgm_demo.wav"]
    top = parts[1].lower() if len(parts) >= 2 else ""

    if physical == "audio":
        if any(word in category for word in MUSIC_CATEGORIES) or top == "bgm":
            return "music"
        if any(word in category for word in VOICE_CATEGORIES) or top == "tts":
            return "voice"
        return "sfx"
    if physical in ("overlay", "image"):
        mapped = DIR_SEMANTICS.get(top)
        if mapped:
            # overlays/ 下的透明视频仍是 overlay，只有静态图才算贴纸
            if mapped == "sticker" and physical == "overlay":
                return "overlay"
            return mapped
        return physical
    if physical in SEMANTIC_KEYS:
        return physical
    return physical or "unknown"


def format_of(asset: Dict[str, Any]) -> str:
    """容器格式，取扩展名（不解码文件）。"""
    ext = os.path.splitext(str(asset.get("path") or ""))[1]
    return ext.lstrip(".").lower()


def tags_of(asset: Dict[str, Any]) -> List[str]:
    """标签：清单里的 tags + 语义类型 + 格式，去重后排序。

    AI 只能从能力列表里挑素材，标签是它唯一的检索维度，所以要把
    「这是什么类型 / 什么格式」也变成可检索的标签。
    """
    tags = {str(tag).lower() for tag in asset.get("tags", []) if str(tag).strip()}
    tags.add(semantic_type(asset))
    fmt = format_of(asset)
    if fmt:
        tags.add(fmt)
    category = str(asset.get("category", "") or "").lower()
    if category:
        tags.add(category)
    return sorted(tags)


def record_of(asset: Dict[str, Any], root: str = "") -> Dict[str, Any]:
    """把清单条目整理成 Registry 记录（指令第七条的形状）。

    只做「有什么就写什么」：探测不到的字段（图片没有 duration、
    音频没有分辨率）一律省略，不填 0 —— 填 0 会让 AI 以为「时长是 0 秒」。
    """
    kind = semantic_type(asset)
    record: Dict[str, Any] = {
        "id": str(asset.get("id", "")),
        "type": kind,
        "physical_type": str(asset.get("type", "") or ""),
        "path": str(asset.get("path", "") or ""),
        "name": str(asset.get("name", "") or ""),
        "category": str(asset.get("category", "") or ""),
        "tags": tags_of(asset),
        "format": format_of(asset),
        "element_type": ELEMENT_TYPE_OF.get(kind, ""),
        "default_track": DEFAULT_TRACK_OF.get(kind, ""),
    }
    for key in ("duration", "width", "height", "fps", "sample_rate", "channels", "size_bytes"):
        value = asset.get(key)
        if value:
            record[key] = value
    if asset.get("has_alpha"):
        record["has_alpha"] = True
    if asset.get("has_audio"):
        record["has_audio"] = True
    if root and record["path"]:
        record["exists"] = os.path.isfile(os.path.join(root, record["path"]))
    return record


class AssetRegistry:
    """素材注册表：按语义类型 / 分类 / 标签查素材。

    数据来源是 AssetManager 已经扫好的清单，本类**只读**。
    """

    def __init__(self, assets: Iterable[Dict[str, Any]], root: str = "") -> None:
        self._root = root
        self._records: Dict[str, Dict[str, Any]] = {}
        for asset in assets or []:
            if not isinstance(asset, dict):
                continue
            record = record_of(asset, root)
            if record["id"]:
                self._records[record["id"]] = record

    # ------------------------------------------------------------ 构造

    @classmethod
    def from_manifest(cls, manifest_path: str) -> "AssetRegistry":
        """从 asset_manifest.json 读。文件缺失 / 坏 JSON 都返回空注册表。"""
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return cls([], "")
        return cls(data.get("assets", []), os.path.dirname(os.path.abspath(manifest_path)))

    # ------------------------------------------------------------ 查询

    def get(self, asset_id: str) -> Optional[Dict[str, Any]]:
        return self._records.get(asset_id)

    def has(self, asset_id: str) -> bool:
        return asset_id in self._records

    def all(self) -> List[Dict[str, Any]]:
        return list(self._records.values())

    def ids(self) -> List[str]:
        return list(self._records)

    def total(self) -> int:
        return len(self._records)

    def by_type(self, semantic: str) -> List[Dict[str, Any]]:
        return [r for r in self._records.values() if r["type"] == semantic]

    def by_category(self, category: str) -> List[Dict[str, Any]]:
        return [r for r in self._records.values() if r["category"] == category]

    def by_tag(self, tag: str) -> List[Dict[str, Any]]:
        needle = str(tag).lower()
        return [r for r in self._records.values() if needle in r["tags"]]

    def categories_of(self, semantic: str) -> List[str]:
        return sorted({r["category"] for r in self.by_type(semantic) if r["category"]})

    def count_by_type(self) -> Dict[str, int]:
        counts = {key: 0 for key in SEMANTIC_KEYS}
        for record in self._records.values():
            counts[record["type"]] = counts.get(record["type"], 0) + 1
        return counts

    def search(
        self,
        keyword: str = "",
        semantic: str = "",
        category: str = "",
        tag: str = "",
    ) -> List[Dict[str, Any]]:
        """多条件检索。全部为空即返回全部，按 id 排序保证结果稳定。"""
        needle = keyword.strip().lower()
        results: List[Dict[str, Any]] = []
        for record in self._records.values():
            if semantic and record["type"] != semantic:
                continue
            if category and record["category"] != category:
                continue
            if tag and tag.lower() not in record["tags"]:
                continue
            if needle:
                haystack = " ".join(
                    [record["id"], record["name"], record["category"], " ".join(record["tags"])]
                ).lower()
                if needle not in haystack:
                    continue
            results.append(record)
        return sorted(results, key=lambda r: r["id"])

    def first_of(self, semantic: str, category: str = "") -> Optional[Dict[str, Any]]:
        """挑第一个可用素材（Demo 生成器 / 模板展开用）。"""
        candidates = self.search(semantic=semantic, category=category)
        return candidates[0] if candidates else None

    def missing_files(self) -> List[Dict[str, Any]]:
        """清单里有、磁盘上没有的素材。root 为空时无法判断，返回空列表。"""
        if not self._root:
            return []
        return [r for r in self._records.values() if r.get("exists") is False]

    # ------------------------------------------------------------ 导出

    def summary(self) -> Dict[str, Any]:
        """给报告 / 文档用的统计。"""
        return {
            "total": self.total(),
            "by_type": self.count_by_type(),
            "missing": len(self.missing_files()),
            "types": [dict(item) for item in SEMANTIC_TYPES],
        }

    def export(self, semantic: str = "") -> Dict[str, Any]:
        """导出结构化目录，供 docs/*.json 生成器使用。"""
        records = self.search(semantic=semantic)
        return {
            "version": 1,
            "total": len(records),
            "assets": [dict(record) for record in records],
        }
