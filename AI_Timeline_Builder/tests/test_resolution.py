"""画面比例 / 分辨率档位的回归测试。

这些数字会一路走到 ffprobe，所以档位表本身必须锁死：
比例与分辨率联动错了，用户看到的预览和导出的 MP4 就不是一个形状。
"""

import pytest

from core import resolution as res


def test_两个必须保留的比例都在():
    assert res.aspect_ids() == ["3:4", "9:16"]


@pytest.mark.parametrize("aspect_id, expected", [
    ("3:4", [(810, 1080), (1080, 1440), (1440, 1920)]),
    ("9:16", [(720, 1280), (1080, 1920), (1440, 2560)]),
])
def test_每个比例的分辨率档位固定(aspect_id, expected):
    assert res.resolutions_for(aspect_id) == expected


def test_档位本身必须真的符合比例():
    for aspect_id in res.aspect_ids():
        target = res.ratio_value(aspect_id)
        for width, height in res.resolutions_for(aspect_id):
            assert abs(width / height - target) < 1e-6, f"{width}×{height} 不是 {aspect_id}"


def test_不认识的比例不许崩():
    assert res.resolutions_for("1:1") == []
    assert res.get_aspect("1:1") is None
    assert res.ratio_value("1:1") is None
    assert res.label_of("1:1") == "1:1"
    assert res.default_resolution("1:1") == res.DEFAULT_RESOLUTION


def test_默认分辨率取_1080_宽那一档():
    assert res.default_resolution("3:4") == (1080, 1440)
    assert res.default_resolution("9:16") == (1080, 1920)


@pytest.mark.parametrize("width, height, expected", [
    (810, 1080, "3:4"),
    (1080, 1440, "3:4"),
    (1440, 1920, "3:4"),
    (720, 1280, "9:16"),
    (1080, 1920, "9:16"),
    (1440, 2560, "9:16"),
    # 手改过 JSON 的近似值也要认出来
    (1082, 1920, "9:16"),
    (540, 960, "9:16"),
])
def test_能从宽高反查比例(width, height, expected):
    assert res.aspect_of(width, height) == expected


@pytest.mark.parametrize("width, height", [
    (1920, 1080), (1000, 1000), (0, 100), (-10, 20), ("宽", 100), (None, None),
])
def test_不属于任何档位就如实返回_None(width, height):
    assert res.aspect_of(width, height) is None


def test_描述里带比例或明说自定义():
    assert res.describe(1080, 1920) == "1080×1920（9:16）"
    assert "自定义" in res.describe(1920, 1080)


def test_区分预置与自定义分辨率():
    assert res.is_preset(1080, 1440) is True
    # 540×960 比例对，但不是预置档位
    assert res.is_preset(540, 960) is False


def test_全表覆盖六个档位():
    rows = res.all_resolutions()
    assert len(rows) == 6
    assert ("3:4", 810, 1080) in rows
    assert ("9:16", 1440, 2560) in rows
