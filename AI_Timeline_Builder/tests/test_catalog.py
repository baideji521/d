"""目录生成器测试。

生成器是「文档不会漂移」的唯一保证，所以这里盯三件事：

1. 产物齐全、AI 目录是合法 JSON；
2. 目录里的能力条目与真实注册表逐一对齐（不多不少）；
3. 音效清单里的每个文件都真的存在（防编造），renderer 探测失败时如实写"未探测"。
"""

from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import build_catalog as bc  # noqa: E402

from core import resolution as res  # noqa: E402
from libraries.asset_registry import AssetRegistry  # noqa: E402
from libraries.effect_library import EffectLibrary  # noqa: E402
from libraries.sound_library import SoundLibrary  # noqa: E402
from libraries.transition_library import TransitionLibrary  # noqa: E402

EXPECTED_FILES = {
    "EFFECT_CATALOG.md",
    "EFFECT_CATALOG.json",
    "TRANSITION_CATALOG.md",
    "TRANSITION_CATALOG.json",
    "SOUND_EFFECT_CATALOG.md",
    "SFX_CATALOG.md",
    "SFX_CATALOG.json",
    "RESOLUTION_GUIDE.md",
    "TIMELINE_GUI_GUIDE.md",
    "TIMELINE_JSON_EXAMPLES.md",
    "AI_MEDIA_CATALOG.json",
    "AI_CAPABILITIES.md",
    "AI_CAPABILITIES.json",
    "AI_SYSTEM_PROMPT.md",
}


@pytest.fixture(scope="module")
def effects():
    return EffectLibrary(bc.ASSETS_DIR)


@pytest.fixture(scope="module")
def transitions():
    return TransitionLibrary(bc.ASSETS_DIR)


@pytest.fixture(scope="module")
def sounds():
    return SoundLibrary.from_manifest(bc.MANIFEST)


@pytest.fixture(scope="module")
def registry():
    return AssetRegistry.from_manifest(bc.MANIFEST)


@pytest.fixture(scope="module")
def catalog(effects, transitions, sounds):
    """不跑 node：renderer 探测置为未知，正好覆盖"未探测"分支。"""
    return bc.build_ai_catalog(effects, transitions, sounds, None, "未探测（测试固定）")


# ---------------------------------------------------------------- AI 目录


def test_ai目录覆盖注册表全部特效与转场(catalog, effects, transitions):
    assert {e["name"] for e in catalog["effects"]} == set(effects.names())
    assert {t["name"] for t in catalog["transitions"]} == set(transitions.names())


def test_ai目录能被json序列化(catalog):
    assert json.loads(json.dumps(catalog, ensure_ascii=False))["version"] == 1


def test_未探测时不给覆盖结论(catalog):
    assert catalog["renderer_discovery"]["runtime_effects"] is None
    assert catalog["renderer_discovery"]["runtime_transitions"] is None
    assert "未探测" in catalog["renderer_discovery"]["note"]


def test_ai目录声明ai只产json(catalog):
    assert catalog["contract"]["ai_outputs"] == "Timeline JSON only"
    assert "TSX" in catalog["contract"]["ai_never_outputs"]


def test_ai目录里的音效文件全都真实存在(catalog):
    for row in catalog["sound_effects"]["local_files"]:
        assert os.path.exists(os.path.join(ROOT, row["path"])), row["path"]


def test_ai目录的音效元素样例是稀疏的(catalog):
    shape = catalog["sound_effects"]["element_shape"]
    assert shape["type"] == "audio"
    assert shape["fade"] == {"in": 0.05, "out": 0.1}
    assert "speed" not in shape


def test_ai目录带上分辨率与标记(catalog):
    """比例档位不在这里另写一份，直接与 core/resolution.py 对齐。

    写死集合的坏处在阶段十四暴露过一次：档位表加了 16:9 / 1:1 之后，
    这条断言红的原因不是能力错了，而是断言自己成了第二份真相。
    """
    aspects = {a["id"] for a in catalog["resolutions"]["aspects"]}
    assert aspects == set(res.aspect_ids())
    assert {"3:4", "9:16", "16:9", "1:1"} <= aspects
    assert catalog["markers"]["location"] == "meta.markers"


def test_落轨策略写进ai目录(catalog):
    assert catalog["placement_policy"]["video"]["default_track"] == "V1"
    assert catalog["placement_policy"]["caption"]["avoid_overlap"] is False


# ---------------------------------------------------------------- Markdown


def test_未探测时转场文档不下覆盖结论(transitions):
    text = bc.build_transition_catalog(transitions, None, "未探测（测试固定）")
    assert "未探测" in text
    assert "Python 有、Remotion 缺 renderer" not in text


def test_转场文档列出全部转场(transitions):
    text = bc.build_transition_catalog(transitions, None, "未探测（测试固定）")
    for name in transitions.names():
        assert f"### `{name}`" in text


def test_特效文档列出全部特效(effects, registry):
    text = bc.build_effect_catalog(effects, None, "未探测（测试固定）", registry)
    for name in effects.names():
        assert f"### `{name}`" in text


def test_素材特效缺素材时文档写MISSING而不是可用(effects, registry):
    """素材特效没素材就渲染不出东西。文档必须写 MISSING，
    不能因为「注册表里有」就标成可用 —— 否则 AI 会照着编时间线。"""
    text = bc.build_effect_catalog(effects, None, "未探测（测试固定）", registry)
    for definition in effects.material_effects():
        hits = bc._material_assets(registry, definition.name)
        section = text.split(f"### `{definition.name}`")[1].split("### ")[0]
        if hits:
            assert "AVAILABLE" in section, definition.name
            for asset_id in hits:
                assert asset_id in section
        else:
            assert "MISSING" in section, definition.name
            assert "AVAILABLE" not in section, definition.name



def test_音效文档把支持的类型与本地文件分开写(sounds):
    text = bc.build_sound_catalog(sounds)
    assert "## 支持的类型" in text
    assert "## 本地文件清单" in text
    for path in (a["path"] for a in sounds.files()):
        assert path in text


def test_json示例全部通过校验器(sounds):
    text = bc.build_json_examples(sounds)
    assert "校验有 error" not in text
    assert text.count("校验通过（0 error）") >= 5


def test_gui说明书的键位来自快捷键表():
    from gui import shortcuts as sc

    text = bc.build_gui_guide()
    assert sc.display("undo") in text
    assert sc.display("toggle_snap") in text


# ---------------------------------------------------------------- 产物


def test_产物文件名齐全():
    payloads = bc.build_all()
    assert set(payloads) == EXPECTED_FILES
    for name, content in payloads.items():
        assert content.endswith("\n")
        assert content.strip()


def test_docs下的文件与当前仓库状态一致():
    """`--check` 必须过：谁改了注册表却没重新生成文档，这里就会红。"""
    runtime, _ = bc.discover_renderers()
    if runtime is None:
        pytest.skip("node 不可用，无法与已生成文档逐字节比对")
    assert bc.main(["--check"]) == 0
