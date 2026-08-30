"""libraries/asset_registry.py 的测试。

Registry 是 AI 挑素材的唯一入口，所以两件事必须钉死：

1. 语义类型推断（bgm → music、tts → voice、transitions/ → transition_material）；
2. 探测不到的字段**不许填 0** —— 填 0 会让 AI 以为「这段素材长 0 秒」。
"""

from __future__ import annotations

import json
import os

import pytest

from libraries import asset_registry as ar

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "asset_manifest.json")


def asset(**overrides) -> dict:
    base = {
        "id": "sfx_impact_001",
        "name": "impact_01",
        "type": "audio",
        "path": "assets/audio/impact/impact_01.wav",
        "category": "impact",
        "tags": ["audio", "impact"],
        "duration": 1.2,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------- 语义类型

@pytest.mark.parametrize("path, category, physical, expected", [
    ("assets/audio/bgm/bgm_demo.wav", "bgm", "audio", "music"),
    ("assets/audio/tts/line_01.wav", "tts", "audio", "voice"),
    ("assets/audio/impact/impact_01.wav", "impact", "audio", "sfx"),
    ("assets/audio/whoosh/whoosh_01.wav", "whoosh", "audio", "sfx"),
    ("assets/transitions/dust/dust.webm", "dust", "overlay", "transition_material"),
    ("assets/effects/fire/fire.webm", "fire", "overlay", "effect_material"),
    ("assets/overlays/arrow/arrow_red.png", "arrow", "image", "sticker"),
    ("assets/videos/demo/demo.mp4", "demo", "video", "video"),
    ("assets/fonts/Inter.ttf", "", "font", "font"),
])
def test_语义类型按目录与分类推断(path, category, physical, expected):
    assert ar.semantic_type(asset(path=path, category=category, type=physical)) == expected


def test_overlays_下的透明视频仍算_overlay():
    """贴纸是静态图；overlays/ 下的 webm 是可播放的叠加素材，两者语义不同。"""
    record = asset(path="assets/overlays/smoke/smoke.webm", category="smoke", type="overlay")
    assert ar.semantic_type(record) == "overlay"


def test_认不出来也不许抛():
    assert ar.semantic_type({}) == "unknown"
    assert ar.semantic_type({"type": None, "path": None}) == "unknown"


def test_每个语义类型都有元素类型与建议轨道():
    for key in ar.SEMANTIC_KEYS:
        assert key in ar.ELEMENT_TYPE_OF
        assert key in ar.DEFAULT_TRACK_OF
        assert key in ar.SEMANTIC_LABELS
    # 字体不进时间线，所以它的元素类型与轨道是空的
    assert ar.ELEMENT_TYPE_OF["font"] == ""
    assert ar.DEFAULT_TRACK_OF["sfx"] == "A3"
    assert ar.DEFAULT_TRACK_OF["music"] == "A1"
    assert ar.DEFAULT_TRACK_OF["voice"] == "A2"


# ---------------------------------------------------------------- 记录形状

def test_记录带上标签与格式():
    record = ar.record_of(asset())
    assert record["type"] == "sfx"
    assert record["format"] == "wav"
    assert "impact" in record["tags"] and "sfx" in record["tags"] and "wav" in record["tags"]
    assert record["element_type"] == "audio"
    assert record["default_track"] == "A3"


def test_探测不到的字段直接省略而不是填零():
    record = ar.record_of(asset(duration=0, width=0, height=0))
    assert "duration" not in record
    assert "width" not in record
    assert "fps" not in record


# ---------------------------------------------------------------- 查询

@pytest.fixture
def registry() -> ar.AssetRegistry:
    return ar.AssetRegistry.from_manifest(MANIFEST)


def test_真实清单能读进来(registry):
    assert registry.total() > 100, "仓库里就有两百多个素材，读少了说明解析出错"
    counts = registry.count_by_type()
    assert counts["sfx"] > 100
    assert counts["music"] >= 1
    assert counts["video"] >= 2


def test_清单里的素材文件都真的存在(registry):
    """编造素材是明确禁止的，这条盯着「清单有、磁盘没有」。"""
    missing = registry.missing_files()
    assert missing == [], f"清单里有 {len(missing)} 个文件在磁盘上找不到"


def test_按类型与标签检索(registry):
    whoosh = registry.search(semantic="sfx", category="whoosh")
    assert whoosh, "音效库里应当有 whoosh 分类"
    assert all(r["type"] == "sfx" for r in whoosh)
    assert all("whoosh" in r["tags"] for r in whoosh)


def test_关键词检索命中_id_或名字(registry):
    hits = registry.search(keyword="bgm")
    assert any(r["type"] == "music" for r in hits)


def test_检索结果顺序稳定(registry):
    assert [r["id"] for r in registry.search(semantic="video")] == sorted(
        r["id"] for r in registry.search(semantic="video")
    )


def test_取不到就如实返回_None(registry):
    assert registry.get("不存在的素材") is None
    assert registry.first_of("sfx", category="不存在的分类") is None


def test_坏清单不许崩(tmp_path):
    bad = tmp_path / "broken.json"
    bad.write_text("{ 这不是 JSON", encoding="utf-8")
    assert ar.AssetRegistry.from_manifest(str(bad)).total() == 0
    assert ar.AssetRegistry.from_manifest(str(tmp_path / "nope.json")).total() == 0


def test_导出结构可直接落成_json(registry):
    payload = registry.export(semantic="music")
    assert payload["total"] == len(payload["assets"])
    json.dumps(payload, ensure_ascii=False)  # 不许出现不可序列化的值


def test_统计摘要覆盖全部语义类型(registry):
    summary = registry.summary()
    assert set(summary["by_type"]) == set(ar.SEMANTIC_KEYS)
    assert summary["total"] == registry.total()
    assert summary["missing"] == 0
