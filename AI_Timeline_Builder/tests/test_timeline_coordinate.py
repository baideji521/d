"""坐标系统测试：往返、缩放、滚动、轨道映射、命中区。

第四十条要求的 property 思维测试放在 `test_往返_*` 里：
随机（这里用固定种子，保证失败可复现）生成时间 / 缩放 / 滚动，验证往返误差。
"""

from __future__ import annotations

import random

import pytest

from gui.timeline_coordinate import (
    DEFAULT_PPS,
    EDGE_ZONE,
    MAX_PPS,
    MIN_HIT_WIDTH,
    MIN_PPS,
    PERCENT_STEPS,
    PPS_AT_100,

    ROW_GAP,
    ROW_HEIGHT,
    ZOOM_STEPS,
    Rect,
    TimelineCoordinate,
    TimelineZoom,
)

TRACKS = ("T2", "T1", "V4", "V3", "V2", "V1", "A3", "A2", "A1")


def coord(pps: float = DEFAULT_PPS, scroll_x: float = 0.0, scroll_y: float = 0.0) -> TimelineCoordinate:
    return TimelineCoordinate(
        pixels_per_second=pps, scroll_x=scroll_x, scroll_y=scroll_y, fps=30.0, track_order=TRACKS
    )


# ------------------------------------------------------------ 基本换算


@pytest.mark.parametrize("seconds", [0.0, 0.1, 0.25, 0.5, 1.0, 2.37, 10.125, 100.001, 285.1])
def test_时间往返不掉精度(seconds):
    c = coord(100.0, scroll_x=1234.5)
    assert c.x_to_time(c.time_to_x(seconds)) == pytest.approx(seconds, abs=1e-9)


def test_时间到像素是线性的():
    c = coord(100.0)
    assert c.time_to_x(0.0) == 0.0
    assert c.time_to_x(1.0) == 100.0
    assert c.time_to_x(12.37) == pytest.approx(1237.0)


def test_滚动后同一时间对应不同像素但换算仍然可逆():
    a = coord(100.0, scroll_x=0.0)
    b = coord(100.0, scroll_x=1000.0)
    assert a.time_to_x(30.0) == 3000.0
    assert b.time_to_x(30.0) == 2000.0
    for c in (a, b):
        assert c.x_to_time(c.time_to_x(30.0)) == pytest.approx(30.0)


def test_x_to_time_不钳零否则往返不可逆():
    c = coord(100.0)
    assert c.x_to_time(-250.0) == pytest.approx(-2.5)
    assert c.clamp_time(c.x_to_time(-250.0)) == 0.0


def test_时长与宽度互逆():
    c = coord(40.0)
    assert c.duration_to_width(8.5) == pytest.approx(340.0)
    assert c.width_to_duration(340.0) == pytest.approx(8.5)


# ------------------------------------------------------------ property 往返


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_往返_时间_像素_时间(seed):
    rng = random.Random(seed)
    for _ in range(200):
        t = rng.uniform(0.0, 300.0)
        pps = rng.uniform(10.0, 800.0)
        scroll = rng.uniform(0.0, 10000.0)
        c = coord(pps, scroll_x=scroll)
        assert abs(c.x_to_time(c.time_to_x(t)) - t) < 1e-6


@pytest.mark.parametrize("seed", [7, 8])
def test_往返_像素_时间_像素(seed):
    rng = random.Random(seed)
    for _ in range(200):
        x = rng.uniform(-2000.0, 20000.0)
        c = coord(rng.uniform(10.0, 800.0), scroll_x=rng.uniform(0.0, 10000.0))
        assert abs(c.time_to_x(c.x_to_time(x)) - x) < 1e-6


@pytest.mark.parametrize("seed", [11, 12])
def test_往返_轨道_y_轨道(seed):
    rng = random.Random(seed)
    for _ in range(200):
        scroll_y = rng.uniform(0.0, 400.0)
        c = coord(scroll_y=scroll_y)
        track = TRACKS[rng.randrange(len(TRACKS))]
        top = c.track_to_y(track)
        assert top is not None
        # 行内任意一点都必须映射回同一条轨道
        offset = rng.uniform(0.0, ROW_HEIGHT - 0.01)
        assert c.y_to_track(top + offset) == track


# ------------------------------------------------------------ 轨道映射


def test_轨道自上而下按显示序():
    c = coord()
    assert c.track_to_y("T2") == 0.0
    assert c.track_to_y("T1") == ROW_HEIGHT + ROW_GAP
    assert c.y_to_track(1.0) == "T2"
    assert c.y_to_track(ROW_HEIGHT + ROW_GAP + 1.0) == "T1"


def test_轨道越界返回None():
    c = coord()
    assert c.y_to_track(-5.0) is None
    assert c.y_to_track(len(TRACKS) * (ROW_HEIGHT + ROW_GAP) + 10.0) is None
    assert c.track_to_y("不存在") is None


def test_纵向滚动参与轨道映射():
    pitch = ROW_HEIGHT + ROW_GAP
    c = coord(scroll_y=pitch * 2)
    assert c.y_to_track(1.0) == "V4"
    assert c.track_to_y("V4") == 0.0


# ------------------------------------------------------------ 元素矩形与命中


def element(start=1.0, duration=2.0, track="V1"):
    return {"id": "clip_001", "type": "video", "track": track, "start": start, "duration": duration}


def test_元素矩形按时间算():
    c = coord(100.0)
    rect = c.element_to_rect(element(1.0, 2.0))
    assert rect is not None
    assert rect.left == pytest.approx(100.0)
    assert rect.width == pytest.approx(200.0)


def test_短片段的命中区被放宽但时间不变():
    c = coord(20.0)
    el = element(1.0, 0.2)  # 视觉宽度 4px
    visual = c.element_to_rect(el)
    hit = c.element_to_hit_rect(el)
    assert visual.width == pytest.approx(4.0)
    assert hit.width == MIN_HIT_WIDTH
    # 命中区居中扩展，时间信息不受影响
    assert (hit.left + hit.right) / 2 == pytest.approx((visual.left + visual.right) / 2)
    assert c.rect_to_time(visual)[1] == pytest.approx(0.2)


def test_窄片段整体算body否则永远只能resize():
    c = coord(20.0)
    el = element(1.0, 0.2)
    rect = c.element_to_hit_rect(el)
    assert c.edge_zone(el, rect.left + 1.0) == "body"
    assert c.edge_zone(el, rect.right - 1.0) == "body"


def test_宽片段的左右边缘是resize中间是move():
    c = coord(200.0)
    el = element(1.0, 2.0)  # 400px 宽
    rect = c.element_to_rect(el)
    assert c.edge_zone(el, rect.left + 1.0) == "left"
    assert c.edge_zone(el, rect.right - 1.0) == "right"
    assert c.edge_zone(el, rect.left + rect.width / 2) == "body"
    assert c.edge_zone(el, rect.left + EDGE_ZONE + 1.0) == "body"


def test_矩形转时间钳非负且至少一帧():
    c = coord(100.0)
    start, duration = c.rect_to_time(Rect(-500.0, 0.0, 0.0, 10.0))
    assert start == 0.0
    assert duration == pytest.approx(1.0 / 30.0)


# ------------------------------------------------------------ 帧对齐


def test_帧对齐与模型使用同一规则():
    from core.time_utils import snap_to_frame

    c = coord()
    for value in (0.0, 0.011, 0.049, 1.2345, 12.37):
        assert c.snap_time(value) == snap_to_frame(value, 30.0)


def test_帧对齐不改变整帧时间():
    c = coord()
    assert c.snap_time(1.0) == pytest.approx(1.0)
    assert c.snap_time(2.0 / 30.0) == pytest.approx(round(2.0 / 30.0, 6))


# ------------------------------------------------------------ 刻度与内容宽度


def test_刻度密度随缩放变化():
    assert coord(10.0).tick_step() > coord(800.0).tick_step()
    assert coord(800.0).tick_step() == 0.1


def test_可见刻度覆盖视口():
    c = coord(100.0, scroll_x=500.0)
    ticks = c.visible_ticks(400.0)
    assert ticks[0] <= 5.0
    assert ticks[-1] >= 9.0


def test_内容宽度带尾部留白且随缩放变化():
    c = coord(100.0)
    assert c.content_width(20.0) == pytest.approx((20.0 + 4.0) * 100.0)
    assert c.content_width(1.0) == pytest.approx((10.0 + 4.0) * 100.0)


def test_锚点滚动能把时间钉在指定像素():
    c = coord(100.0)
    scroll = c.scroll_for_anchor(30.0, 200.0)
    moved = c.with_scroll(scroll_x=scroll)
    assert moved.time_to_x(30.0) == pytest.approx(200.0)


# ------------------------------------------------------------ 缩放档位


def test_缩放档位覆盖极缩小到极放大():
    # 档位以百分比定义（100% = 80px/s），换算出来是 20..640px/s
    assert PERCENT_STEPS == (25.0, 50.0, 75.0, 100.0, 150.0, 200.0, 400.0, 800.0)
    assert ZOOM_STEPS[0] == 20.0
    assert ZOOM_STEPS[-1] == 640.0
    # 自由缩放范围比档位更宽：fit 整条时间线可能落到 25% 以下
    assert MIN_PPS < ZOOM_STEPS[0]
    assert MAX_PPS > ZOOM_STEPS[-1]


def test_百分比与像素每秒互相换算():
    zoom = TimelineZoom(PPS_AT_100)
    assert zoom.percent() == 100.0
    assert zoom.set_percent(25.0) == 20.0
    assert zoom.percent() == 25.0
    assert zoom.set_percent(800.0) == 640.0
    assert zoom.percent() == 800.0
    # 落在两档之间时，下拉框回显最近的档位
    zoom.set_zoom(100.0)
    assert zoom.nearest_percent() in (100.0, 150.0)
    assert TimelineZoom.percent_label(25.0) == "25%"


def test_每个百分比档位都能设进去():
    zoom = TimelineZoom()
    for percent in PERCENT_STEPS:
        assert zoom.set_percent(percent) == pytest.approx(PPS_AT_100 * percent / 100.0)
        assert zoom.percent() == pytest.approx(percent)



def test_zoom_in_out_走档位():
    zoom = TimelineZoom(80.0)
    assert zoom.zoom_in() == 120.0
    assert zoom.zoom_out() == 80.0
    zoom.set_zoom(95.0)
    assert zoom.zoom_in() == 120.0
    assert zoom.zoom_out() == 80.0


def test_缩放被钳在范围内():
    """越界的缩放值被夹回档位区间，两端继续按按钮不会跑出去。"""
    zoom = TimelineZoom()
    assert zoom.set_zoom(1.0) == MIN_PPS
    assert zoom.zoom_out() == MIN_PPS, "已经最小了，再缩小仍停在最小档"
    assert zoom.set_zoom(99999.0) == MAX_PPS
    assert zoom.zoom_in() == MAX_PPS, "已经最大了，再放大仍停在最大档"


def test_fit_project_把整条时间线塞进视口():
    zoom = TimelineZoom()
    zoom.fit_project(60.0, 1200.0)
    assert zoom.pixels_per_second == pytest.approx(20.0)


def test_fit_selection_区间退化时不顶到最大():
    zoom = TimelineZoom()
    zoom.fit_selection(5.0, 5.0, 800.0)
    assert zoom.pixels_per_second == pytest.approx(800.0)


def test_滑块比例与缩放互逆():
    zoom = TimelineZoom(200.0)
    ratio = zoom.slider_ratio()
    assert TimelineZoom.ratio_to_zoom(ratio) == pytest.approx(200.0)


# ------------------------------------------------------------ DPI


@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 1.75])
def test_坐标换算与设备像素比无关(dpr):
    """开启 AA_EnableHighDpiScaling 后鼠标事件与绘制都在逻辑像素里，
    坐标换算只吃逻辑像素，所以 DPR 变化不该影响任何结果。
    这里用"把像素值整体按 dpr 缩放"模拟不同 DPI 下的**物理**像素，
    验证只要单位一致，时间就一致。"""
    logical = coord(100.0, scroll_x=300.0)
    physical = coord(100.0 * dpr, scroll_x=300.0 * dpr)
    for t in (0.0, 1.0, 12.37, 100.001):
        assert physical.x_to_time(logical.time_to_x(t) * dpr) == pytest.approx(t, abs=1e-9)
