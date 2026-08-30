"""画面比例 / 分辨率档位的回归测试。

这些数字会一路走到 ffprobe，所以档位表本身必须锁死：
比例与分辨率联动错了，用户看到的预览和导出的 MP4 就不是一个形状。

档位表在指令第十四条被扩到四个比例（9:16 / 3:4 / 16:9 / 1:1）
与四档画质（720 / 1080 / 1440 / 2160），本文件的断言随之更新；
3:4 的 810×1080 是历史工程档位，必须继续留在表里。
"""

import pytest

from core import resolution as res


def test_四个比例都在且顺序固定():
    assert res.aspect_ids() == ["3:4", "9:16", "16:9", "1:1"]


@pytest.mark.parametrize("aspect_id, expected", [
    ("3:4", [(720, 960), (810, 1080), (1080, 1440), (1440, 1920), (2160, 2880)]),
    ("9:16", [(720, 1280), (1080, 1920), (1440, 2560), (2160, 3840)]),
    ("16:9", [(1280, 720), (1920, 1080), (2560, 1440), (3840, 2160)]),
    ("1:1", [(720, 720), (1080, 1080), (1440, 1440), (2160, 2160)]),
])
def test_每个比例的分辨率档位固定(aspect_id, expected):
    assert res.resolutions_for(aspect_id) == expected


def test_历史档位_810x1080_不许消失():
    """既有工程与验收用例全在这一档，删掉它等于让老项目变成「自定义比例」。"""
    assert (810, 1080) in res.resolutions_for("3:4")
    assert res.aspect_of(810, 1080) == "3:4"


def test_档位本身必须真的符合比例():
    for aspect_id in res.aspect_ids():
        target = res.ratio_value(aspect_id)
        for width, height in res.resolutions_for(aspect_id):
            assert abs(width / height - target) < 1e-6, f"{width}×{height} 不是 {aspect_id}"


def test_不认识的比例不许崩():
    assert res.resolutions_for("21:9") == []
    assert res.get_aspect("21:9") is None
    assert res.ratio_value("21:9") is None
    assert res.label_of("21:9") == "21:9"
    assert res.default_resolution("21:9") == res.DEFAULT_RESOLUTION


@pytest.mark.parametrize("aspect_id, expected", [
    ("3:4", (1080, 1440)),
    ("9:16", (1080, 1920)),
    ("16:9", (1920, 1080)),
    ("1:1", (1080, 1080)),
])
def test_默认分辨率就是指令给的那一组(aspect_id, expected):
    """横版的 1080 档宽度是 1920，所以默认档不能靠 width==1080 去猜。"""
    assert res.default_resolution(aspect_id) == expected


@pytest.mark.parametrize("aspect_id, tier, expected", [
    ("9:16", 720, (720, 1280)),
    ("9:16", 2160, (2160, 3840)),
    ("16:9", 720, (1280, 720)),
    ("16:9", 2160, (3840, 2160)),
    ("1:1", 1440, (1440, 1440)),
])
def test_按画质档位取分辨率(aspect_id, tier, expected):
    assert res.resolution_for_tier(aspect_id, tier) == expected


def test_画质档位按短边判定():
    assert res.tier_of(1920, 1080) == 1080
    assert res.tier_of(1080, 1920) == 1080
    assert res.tier_of(2160, 3840) == 2160
    assert "1080" in res.tier_label(1920, 1080)


def test_没有这一档就如实返回_None():
    assert res.resolution_for_tier("16:9", 810) is None


@pytest.mark.parametrize("width, height, expected", [
    (810, 1080, "3:4"),
    (1080, 1440, "3:4"),
    (1440, 1920, "3:4"),
    (720, 1280, "9:16"),
    (1080, 1920, "9:16"),
    (1440, 2560, "9:16"),
    (1920, 1080, "16:9"),
    (1280, 720, "16:9"),
    (3840, 2160, "16:9"),
    (1080, 1080, "1:1"),
    (2160, 2160, "1:1"),
    # 手改过 JSON 的近似值也要认出来
    (1082, 1920, "9:16"),
    (540, 960, "9:16"),
    (1000, 1000, "1:1"),
])
def test_能从宽高反查比例(width, height, expected):
    assert res.aspect_of(width, height) == expected


@pytest.mark.parametrize("width, height", [
    (2560, 1080), (1000, 300), (0, 100), (-10, 20), ("宽", 100), (None, None),
])
def test_不属于任何档位就如实返回_None(width, height):
    assert res.aspect_of(width, height) is None


def test_描述里带比例或明说自定义():
    assert res.describe(1080, 1920) == "1080×1920（9:16）"
    assert res.describe(1920, 1080) == "1920×1080（16:9）"
    assert "自定义" in res.describe(2560, 1080)


def test_区分预置与自定义分辨率():
    assert res.is_preset(1080, 1440) is True
    assert res.is_preset(1920, 1080) is True
    # 540×960 比例对，但不是预置档位
    assert res.is_preset(540, 960) is False


def test_全表覆盖十七个档位():
    rows = res.all_resolutions()
    assert len(rows) == 17
    assert ("3:4", 810, 1080) in rows
    assert ("9:16", 1440, 2560) in rows
    assert ("16:9", 1920, 1080) in rows
    assert ("1:1", 1080, 1080) in rows
