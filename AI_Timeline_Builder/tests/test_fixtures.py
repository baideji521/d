"""tests/fixtures/*.json 的守门测试。

fixture 不是「示例文件」，它是**协议的活样本**：

1. 每份都必须过 Validator（Schema + 语义 + Registry + Rule Engine）；
2. `basic_video.json` 是稀疏原则的基准 —— 刚导入一个视频、什么都没改，
   JSON 里就不许出现 transform / speed / audio / keyframes / params / fade；
3. 磁盘上的文件必须与 `tools/build_fixtures.py` 的生成结果一致
   （谁手改了 fixture 却没改生成器，这里会红）；
4. `demo_timeline.json` 必须真的覆盖指令第五十条列的那一串能力，
   不许「文件在就算覆盖」。
"""

from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
for path in (ROOT, TOOLS):
    if path not in sys.path:
        sys.path.insert(0, path)

import build_fixtures as bf  # noqa: E402

FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures")


def load(name: str) -> dict:
    with open(os.path.join(FIXTURE_DIR, f"{name}.json"), "r", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def manifest() -> dict:
    return bf.build_manifest()


@pytest.fixture(scope="module")
def fixture_validator(manifest):
    return bf.make_validator(manifest)


@pytest.mark.parametrize("name", list(bf.FIXTURES))
def test_每份_fixture_都在磁盘上(name):
    assert os.path.isfile(os.path.join(FIXTURE_DIR, f"{name}.json")), (
        f"缺少 {name}.json，请跑 python tools/build_fixtures.py build"
    )


@pytest.mark.parametrize("name", list(bf.FIXTURES))
def test_每份_fixture_都过校验(name, fixture_validator):
    report = fixture_validator.validate_report(load(name))
    assert report["valid"], json.dumps(report["errors"], ensure_ascii=False, indent=2)


@pytest.mark.parametrize("name", list(bf.FIXTURES))
def test_磁盘文件与生成器一致(name):
    assert load(name) == bf.FIXTURES[name](), (
        f"{name}.json 与 tools/build_fixtures.py 的生成结果不一致；"
        "改 fixture 请改生成器再重新 build"
    )


#: 稀疏原则要盯的字段（指令第二十九条）
DEFAULT_LEAK_KEYS = ("transform", "speed", "audio", "keyframes", "params", "fade")


def test_刚导入的视频不许有任何默认字段():
    data = load("basic_video")
    assert len(data["elements"]) == 1
    element = data["elements"][0]
    for key in DEFAULT_LEAK_KEYS:
        assert key not in element, f"basic_video 里泄漏了默认字段 {key}"
    assert set(element) == {"id", "type", "track", "asset", "start", "duration", "source"}


def test_没人设置的全局字段也不许出现():
    data = load("basic_video")
    for key in ("master_volume", "markers", "safe_area"):
        assert key not in data["meta"], f"basic_video 的 meta 里泄漏了 {key}"


@pytest.mark.parametrize("name, expected", [
    ("res_3x4", (1080, 1440)),
    ("res_9x16", (1080, 1920)),
    ("res_16x9", (1920, 1080)),
    ("res_1x1", (1080, 1080)),
])
def test_比例用例写着真实分辨率(name, expected):
    meta = load(name)["meta"]
    assert (meta["width"], meta["height"]) == expected


def test_比例用例覆盖四个档位():
    from core import resolution as res

    got = set()
    for name in ("res_3x4", "res_9x16", "res_16x9", "res_1x1"):
        meta = load(name)["meta"]
        got.add(res.aspect_of(meta["width"], meta["height"]))
    assert got == {"3:4", "9:16", "16:9", "1:1"}


# ---------------------------------------------------------------- 综合 Demo


def test_综合_demo_覆盖指令要求的能力():
    data = load("demo_timeline")
    elements = data["elements"]
    types = [e["type"] for e in elements]

    assert types.count("video") == 2, "需要 2 个视频片段"
    assert types.count("caption") >= 1 and types.count("caption_group") >= 1
    assert types.count("freeze") >= 1
    assert types.count("transition") >= 1
    assert types.count("text") >= 1
    # 图片 + 叠加素材
    assert types.count("overlay") >= 2

    effects = {e["name"] for e in elements if e["type"] == "effect"}
    assert {"zoom", "shake", "blur", "flash"} <= effects

    tracks = {e.get("track") for e in elements if e["type"] == "audio"}
    assert {"A1", "A2", "A3"} <= tracks, "BGM / 配音 / 音效三条音轨都要有"
    assert sum(1 for e in elements if e.get("track") == "A3") >= 2, "至少两个音效"

    assert any(e.get("keyframes") for e in elements), "需要关键帧"
    assert any(e.get("transform") for e in elements), "需要 transform"
    assert data["meta"]["markers"], "需要标记"
    assert data["meta"]["master_volume"] == 0.9


def test_综合_demo_的标记与安全区是兼容扩展():
    data = load("demo_timeline")
    assert data["meta"]["safe_area"]["preset"] == "youtube_shorts"
    caption = next(e for e in data["elements"] if e["type"] == "caption")
    assert caption["safe_area"] is True
    # 声明了安全区就必须真的在区内，否则 RULE_SAFE_AREA_001 会报错
    from core import safe_area as sa

    assert sa.contains(
        caption["transform"].get("x", 0.5), caption["transform"]["y"], "youtube_shorts"
    )


# ---------------------------------------------------------------- 探针判据


def test_黑帧豁免只认_fade_flash_转场():
    """crossfade 两侧都是画面，不该被当成「允许黑」的窗口。"""
    reasons = [w["reason"] for w in bf._veil_windows(load("transition"))]
    assert not any("转场经过纯色" in r for r in reasons), \
        "crossfade 被当成纯色过渡豁免了，真黑帧就会被放过"


def test_没有画面主体的尾巴算预期黑():
    """complex_timeline 的视频到 4.0s，字幕盖到 4.4s，BGM 到 5.0s。

    4.0 之后没有画面主体，只剩字幕与声音 —— 那一段黑是设计结果。
    字幕不算主体：它只占一小块，底下没画面时整帧本来就是黑底。
    """
    gaps = bf._uncovered_ranges(load("complex_timeline"))
    assert len(gaps) == 1
    assert abs(gaps[0]["start"] - 4.0) < 1e-6
    assert abs(gaps[0]["end"] - 5.0) < 1e-6


def test_画面铺满时没有豁免窗口():
    assert bf._uncovered_ranges(load("basic_video")) == []


def test_音量为零的音频不算声源():
    """0 是有意义的设置，不能当成「没设置」。"""
    data = load("audio")
    assert bf._expects_sound(data) is True
    muted = json.loads(json.dumps(data))
    for element in muted["elements"]:
        if element["type"] == "audio":
            element["volume"] = 0.0
        else:
            element["audio"] = {"enabled": False}
    assert bf._expects_sound(muted) is False

