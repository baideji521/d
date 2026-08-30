"""Timeline 磁吸引擎的测试（阶段 7 第八、九、四十条）。

覆盖：目标类型是否齐全、容差的"像素 + 时间上限"双闸、
`9.96 → 10.0` 会吸而 `9.7` 不吸、首尾竞争、Snap Guide 的展示信息。

本模块与 gui.timeline_snap 一样**不需要 Qt**：磁吸是纯数学。
"""

from __future__ import annotations

import pytest

from gui.timeline_snap import (
    MAX_SNAP_SECONDS,
    SNAP_PIXELS,
    SnapEngine,
    SnapTarget,
)


def clips():
    """两个相邻片段 + 一个转场，覆盖 clip_* 与 transition_* 两组目标。"""
    return [
        {"id": "clip_001", "type": "video", "track": "V1", "start": 0.0, "duration": 10.0},
        {"id": "clip_002", "type": "video", "track": "V1", "start": 10.0, "duration": 5.0},
        {"id": "tr_001", "type": "transition", "track": "V1", "start": 9.75, "duration": 0.5},
    ]


# ------------------------------------------------------------ 目标收集


def test_收集到第八条要求的全部目标类型():
    engine = SnapEngine()
    kinds = {t.kind for t in engine.collect(clips(), playhead=3.5, markers=[7.25])}
    assert kinds == {
        "zero",
        "playhead",
        "clip_start",
        "clip_end",
        "clip_center",
        "transition_start",
        "transition_end",
        "marker",
    }


def test_零点与播放头总在目标里():
    engine = SnapEngine()
    targets = engine.collect([], playhead=2.5)
    assert SnapTarget(0.0, "zero") in targets
    assert SnapTarget(2.5, "playhead") in targets


def test_被拖动的元素自己不参与吸附():
    """否则片段会被自己的起点黏住，一点都推不动。"""
    engine = SnapEngine()
    targets = engine.collect(clips(), exclude_ids=["clip_001"])
    assert all(t.element_id != "clip_001" for t in targets)


def test_零时长元素不产生中心点():
    engine = SnapEngine()
    targets = engine.collect(
        [{"id": "x", "type": "effect", "track": "V1", "start": 2.0, "duration": 0.0}]
    )
    assert [t for t in targets if t.kind == "clip_center"] == []


def test_脏数值不会让收集抛异常():
    engine = SnapEngine()
    targets = engine.collect(
        [{"id": "x", "type": "video", "track": "V1", "start": None, "duration": "五秒"}]
    )
    assert [t.time for t in targets if t.element_id == "x"] == [0.0, 0.0]


# ------------------------------------------------------------ 容差双闸


@pytest.mark.parametrize(
    "pps, expected",
    [
        (10.0, MAX_SNAP_SECONDS),       # 极缩小：纯像素容差会变成 1.0s，必须被时间上限压住
        (80.0, MAX_SNAP_SECONDS),       # 10/80 = 0.125 > 0.12
        (200.0, SNAP_PIXELS / 200.0),   # 放大后由像素容差决定
        (800.0, SNAP_PIXELS / 800.0),
    ],
)
def test_容差取像素与时间上限的较小值(pps, expected):
    assert SnapEngine().tolerance(pps) == pytest.approx(expected)


def test_容差不会因为_pps_为零而除零():
    assert SnapEngine().tolerance(0.0) == MAX_SNAP_SECONDS


# ------------------------------------------------------------ 单点吸附


def test_九点九六吸到十秒():
    """第四十条点名的用例：9.96 在容差内，应该吸到整秒刻度。"""
    engine = SnapEngine()
    engine.collect([], playhead=0.0)
    result = engine.snap(9.96, 80.0)
    assert result.snapped is True
    assert result.time == pytest.approx(10.0)
    assert result.target.kind == "ruler"


def test_九点七不吸():
    """差 0.3s 远超容差，硬吸过去等于篡改用户意图。"""
    engine = SnapEngine()
    engine.collect([], playhead=0.0)
    result = engine.snap(9.7, 80.0)
    assert result.snapped is False
    assert result.time == pytest.approx(9.7)
    assert result.guide_time is None


def test_关掉磁吸后原值直接返回():
    engine = SnapEngine(enabled=False)
    engine.collect(clips(), playhead=0.0)
    result = engine.snap(9.96, 80.0)
    assert result.snapped is False and result.time == pytest.approx(9.96)


def test_片段中心也是吸附目标():
    """clip_001 是 [0, 10]，中心 5.0。容差 10/200=0.05s，4.98 落在里面。

    刻度 0.5 的最近点同样是 5.0，但 ruler 只在**严格更近**时才顶掉元素目标，
    所以这里报出来的原因是"片段中心"——Snap Guide 上写的就是用户真正对齐到的东西。
    """
    engine = SnapEngine()
    engine.collect(clips(), playhead=0.0)
    result = engine.snap(4.98, 200.0)
    assert result.snapped is True
    assert result.time == pytest.approx(5.0)
    assert result.target.kind == "clip_center"
    assert result.target.element_id == "clip_001"


def test_只有片段边界能解释的位置也能吸():
    """9.75 是转场起点，不是任何整齐刻度（0.5 的倍数是 9.5 / 10.0）。"""
    engine = SnapEngine()
    engine.collect(clips(), playhead=0.0)
    result = engine.snap(9.74, 800.0)
    assert result.snapped is True
    assert result.time == pytest.approx(9.75)
    assert result.target.kind == "transition_start"


def test_不用刻度时只吸元素与播放头():
    engine = SnapEngine()
    engine.collect(clips(), playhead=0.0)
    assert engine.snap(9.96, 80.0, use_ruler=False).time == pytest.approx(10.0)
    # 3.02 附近没有任何元素目标，关掉刻度就不该吸
    assert engine.snap(3.02, 800.0, use_ruler=False).snapped is False


# ------------------------------------------------------------ 首尾竞争


def test_移动片段时尾部更近就按尾部吸():
    """片段 [4.9, 5.02]，尾部 9.92 离 10.0 只差 0.08，比头部离 5.0 的 0.1 更近。"""
    engine = SnapEngine()
    engine.collect([], playhead=0.0)
    result = engine.snap_span(4.9, 5.02, 80.0)
    assert result.snapped is True
    assert result.edge == "end"
    assert result.time == pytest.approx(10.0 - 5.02)


def test_移动片段时头部更近就按头部吸():
    engine = SnapEngine()
    engine.collect([], playhead=0.0)
    result = engine.snap_span(9.96, 3.0, 80.0)
    assert result.snapped is True
    assert result.edge == "start"
    assert result.time == pytest.approx(10.0)


def test_首尾都吸不上就返回原值():
    """9.7 与 13.03 都离最近刻度 0.03s，超过 800px/s 下的 0.0125s 容差。"""
    engine = SnapEngine()
    engine.collect([], playhead=0.0)
    result = engine.snap_span(9.7, 3.33, 800.0)
    assert result.snapped is False and result.time == pytest.approx(9.7)


def test_尾部吸附不会把片段推到负时间():
    engine = SnapEngine()
    engine.collect([], playhead=0.0)
    result = engine.snap_span(0.02, 0.5, 80.0)
    assert result.time >= 0.0


def test_snap_span_返回的时间始终是起点():
    """调用方拿到的就能直接当 start 用，不需要再减一次 duration。"""
    engine = SnapEngine()
    engine.collect([], playhead=0.0)
    duration = 5.02
    result = engine.snap_span(4.9, duration, 80.0)
    assert result.time + duration == pytest.approx(10.0)


# ------------------------------------------------------------ Snap Guide


def test_guide_能说清吸到了什么():
    engine = SnapEngine()
    engine.collect(clips(), playhead=0.0)
    result = engine.snap(9.74, 800.0)
    assert result.guide_time == pytest.approx(9.75)
    assert "转场起点" in result.guide_label
    assert "tr_001" in result.guide_label


def test_没有元素_id_的目标标签不带括号():
    assert SnapTarget(0.0, "zero").label == "起点 0"
    assert SnapTarget(1.0, "playhead").label == "播放头"


def test_未知类型的标签退化成类型名():
    assert SnapTarget(0.0, "某种新目标").label == "某种新目标"
