"""音效库测试。

重点只有一个：**支持的类型** 和 **本地实际存在的文件** 必须分得开，
而且后者绝不能凭清单就算数——文件不在磁盘上就不算可用。
"""

from __future__ import annotations

import json
import os

import pytest

from libraries.sound_library import CATEGORY_KEYS, SFX_CATEGORIES, SoundLibrary


def _asset(asset_id, category, path, duration=1.0, asset_type="audio"):
    return {"id": asset_id, "type": asset_type, "category": category,
            "path": path, "duration": duration, "name": asset_id}


@pytest.fixture()
def sound_root(tmp_path):
    """造两个真文件 + 一个清单里有但磁盘上没有的条目。"""
    (tmp_path / "assets" / "audio" / "impact").mkdir(parents=True)
    (tmp_path / "assets" / "audio" / "bgm").mkdir(parents=True)
    real_impact = tmp_path / "assets" / "audio" / "impact" / "hit.wav"
    real_impact.write_bytes(b"RIFF")
    real_bgm = tmp_path / "assets" / "audio" / "bgm" / "loop.wav"
    real_bgm.write_bytes(b"RIFF")
    return tmp_path


@pytest.fixture()
def library(sound_root):
    assets = [
        _asset("sfx_impact_001", "impact", "assets/audio/impact/hit.wav", 0.6),
        _asset("sfx_bgm_001", "bgm", "assets/audio/bgm/loop.wav", 16.0),
        _asset("sfx_impact_002", "impact", "assets/audio/impact/gone.wav", 0.5),
        _asset("video_001", "imported", "assets/videos/a.mp4", 3.0, asset_type="video"),
    ]
    return SoundLibrary(assets, str(sound_root))


# ---------------------------------------------------------------- 支持的类型


def test_支持的类型表每项都完整():
    for item in SFX_CATEGORIES:
        assert item["key"]
        assert item["label"]
        assert item["track"]
        assert item["description"]


def test_支持的类型key不重复():
    assert len(CATEGORY_KEYS) == len(set(CATEGORY_KEYS))


def test_建议轨道与落轨策略一致(library):
    assert library.track_for("bgm") == "A1"
    assert library.track_for("tts") == "A2"
    assert library.track_for("impact") == "A3"


def test_未登记的类型建议轨道退回A3(library):
    assert library.track_for("不存在的类型") == "A3"
    assert library.supports("不存在的类型") is False


def test_类型表与本地文件无关(library):
    """imported 本地一个文件都没有，但仍然是被支持的类型。"""
    assert library.supports("imported") is True
    assert library.count_by_category()["imported"] == 0


# ---------------------------------------------------------------- 本地文件


def test_只有磁盘上真实存在的文件才算可用(library):
    ids = [a["id"] for a in library.files()]
    assert ids == ["sfx_bgm_001", "sfx_impact_001"]
    assert "sfx_impact_002" not in ids


def test_清单里指向不存在文件的条目要单独暴露(library):
    assert [a["id"] for a in library.missing()] == ["sfx_impact_002"]


def test_非音频条目被忽略(library):
    assert all(a["type"] == "audio" for a in library.files())
    assert all(a["id"] != "video_001" for a in library.missing())


def test_按类型筛选(library):
    assert [a["id"] for a in library.files("impact")] == ["sfx_impact_001"]
    assert library.files("footstep") == []


def test_计数覆盖所有支持的类型(library):
    counts = library.count_by_category()
    assert set(counts) >= set(CATEGORY_KEYS)
    assert counts["impact"] == 1
    assert counts["bgm"] == 1
    assert counts["footstep"] == 0


def test_没登记的category要报出来(sound_root):
    (sound_root / "assets" / "audio" / "weird").mkdir(parents=True)
    path = sound_root / "assets" / "audio" / "weird" / "x.wav"
    path.write_bytes(b"RIFF")
    library = SoundLibrary(
        [_asset("sfx_weird_001", "外星音效", "assets/audio/weird/x.wav")], str(sound_root)
    )
    assert library.unknown_categories() == ["外星音效"]


def test_first_of只挑真实存在的(library):
    assert library.first_of("impact")["id"] == "sfx_impact_001"
    assert library.first_of("footstep") is None


def test_副标题带时长和类型名(library):
    text = library.describe(library.first_of("bgm"))
    assert "sfx_bgm_001" in text
    assert "16.000s" in text
    assert "背景音乐" in text


# ---------------------------------------------------------------- 清单读取


def test_从清单文件读(sound_root):
    manifest = sound_root / "asset_manifest.json"
    manifest.write_text(json.dumps({
        "version": 1,
        "assets": [_asset("sfx_bgm_001", "bgm", "assets/audio/bgm/loop.wav", 16.0)],
    }, ensure_ascii=False), encoding="utf-8")
    library = SoundLibrary.from_manifest(str(manifest))
    assert library.total() == 1


def test_清单不存在时是空库而不是崩(tmp_path):
    library = SoundLibrary.from_manifest(str(tmp_path / "没有这个文件.json"))
    assert library.total() == 0
    assert library.categories()  # 类型表照旧


def test_清单是坏json时也是空库(tmp_path):
    broken = tmp_path / "asset_manifest.json"
    broken.write_text("{ 这不是 json", encoding="utf-8")
    assert SoundLibrary.from_manifest(str(broken)).total() == 0


def test_汇总里同时给出支持的类型和缺素材的类型(library):
    summary = library.summary()
    assert len(summary["supported_categories"]) == len(SFX_CATEGORIES)
    assert summary["local_file_count"] == 2
    assert "footstep" in summary["categories_without_local_file"]
    assert summary["missing_files"] == ["assets/audio/impact/gone.wav"]


# ---------------------------------------------------------------- 真实仓库


def test_真实仓库里的音效文件全都存在():
    """防编造：仓库清单里列出的每个音效文件都必须真的在磁盘上。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    library = SoundLibrary.from_manifest(os.path.join(root, "asset_manifest.json"))
    for asset in library.files():
        assert os.path.exists(os.path.join(root, asset["path"])), asset["path"]
