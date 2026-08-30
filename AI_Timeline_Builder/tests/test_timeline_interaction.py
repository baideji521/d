"""Timeline 交互状态机的测试（阶段 7 第三十一、三十二、三十三条）。

这些用例直接对着报障"把视频拖到 Timeline 轨道，很难拖准"写：

* grab_offset 在整段手势里不变 —— 抓片段中间就从中间拖，不会跳到左边缘
* 外部素材落下时**左边缘对准鼠标**，所见即所得
* 视觉矩形与命中矩形分离 —— 0.03 秒的片段照样点得到，而且整体算 body
* Resize 优先于 Move，但窄片段例外（否则永远没法移动）
* 一次手势只产出一条 commit —— 撤销栈里拖动就是一步

gui.timeline_interaction 不 import PyQt5，所以这些逻辑可以脱离 GUI 单测。
"""

from __future__ import annotations

import pytest

from gui.timeline_coordinate import EDGE_ZONE, MIN_HIT_WIDTH, TimelineCoordinate
from gui.timeline_interaction import (
    DropCommit,
    InteractionMode,
    MoveCommit,
    ResizeCommit,
    TimelineInteraction,
)

#: 自上而下的轨道显示顺序。row_pitch = 44 + 2 = 46
TRACK_ORDER = ("V1", "V2", "A1", "T1")

#: 每条轨道行内一个稳妥的 y（行高 44，取行内 20px 处）
Y = {"V1": 20.0, "V2": 66.0, "A1": 112.0, "T1": 158.0}


def coord(**kwargs) -> TimelineCoordinate:
    base = dict(pixels_per_second=80.0, fps=30.0, track_order=TRACK_ORDER)
    base.update(kwargs)
    return TimelineCoordinate(**base)


def tracks(locked=()):
    kinds = {"V1": "video", "V2": "video", "A1": "audio", "T1": "text"}
    return [
        {"id": tid, "name": tid, "kind": kinds[tid], "locked": tid in locked}
        for tid in TRACK_ORDER
    ]


def clip(element_id="clip_001", track="V1", start=10.0, duration=10.0, type_name="video"):
    return {
        "id": element_id,
        "type": type_name,
        "track": track,
        "asset": "video_001",
        "start": start,
        "duration": duration,
    }


# ------------------------------------------------------------ 命中测试


def test_点片段中间命中_body():
    c = coord()
    hit = TimelineInteraction.hit_test(c, [clip()], c.time_to_x(12.5), Y["V1"])
    assert hit.element_id == "clip_001"
    assert hit.zone == "body"
    assert hit.track_id == "V1"
    assert hit.time == pytest.approx(12.5)


@pytest.mark.parametrize(
    "seconds, zone",
    [
        (10.05, "left"),    # 距左边缘 4px
        (19.95, "right"),   # 距右边缘 4px
        (12.5, "body"),
    ],
)
def test_边缘区宽度是_EDGE_ZONE(seconds, zone):
    c = coord()
    hit = TimelineInteraction.hit_test(c, [clip()], c.time_to_x(seconds), Y["V1"])
    assert hit.zone == zone
    # 8px 的边缘区在 80px/s 下正好是 0.1 秒
    assert EDGE_ZONE / c.pixels_per_second == pytest.approx(0.1)


def test_极短片段也点得到而且整体算_body():
    """0.03s 在 80px/s 下只有 2.4px 宽，命中区被撑到 MIN_HIT_WIDTH。"""
    c = coord()
    tiny = clip(start=5.0, duration=0.03)
    visual = c.element_to_rect(tiny)
    hit_rect = c.element_to_hit_rect(tiny)
    assert visual.width < MIN_HIT_WIDTH
    assert hit_rect.width == MIN_HIT_WIDTH
    # 命中区变宽，但时间没变
    assert c.x_to_time(visual.x) == pytest.approx(5.0)

    hit = TimelineInteraction.hit_test(c, [tiny], hit_rect.left + 2.0, Y["V1"])
    assert hit.element_id == "clip_001"
    assert hit.zone == "body", "窄片段整体是 body，否则永远只能 resize 不能移动"


def test_点空白处没有命中但仍然知道时间与轨道():
    c = coord()
    hit = TimelineInteraction.hit_test(c, [clip()], c.time_to_x(50.0), Y["V2"])
    assert hit.element is None
    assert hit.track_id == "V2"
    assert hit.time == pytest.approx(50.0)


def test_同轨重叠时命中最上层():
    c = coord()
    lower = clip("clip_001", start=0.0, duration=20.0)
    upper = clip("clip_002", start=5.0, duration=5.0)
    hit = TimelineInteraction.hit_test(c, [lower, upper], c.time_to_x(7.0), Y["V1"])
    assert hit.element_id == "clip_002", "列表越靠后越上层"


def test_轨道区之外不命中任何元素():
    c = coord()
    hit = TimelineInteraction.hit_test(c, [clip()], c.time_to_x(12.5), 9999.0)
    assert hit.element is None and hit.track_id is None


# ------------------------------------------------------------ 移动已有元素


def test_抓住片段中间拖动_grab_offset_全程不变():
    """报障主场景：在 12.5s 处抓住 [10, 20] 的片段，落到 30s → start = 27.5。"""
    c = coord()
    it = TimelineInteraction()
    hit = it.begin_press(c, [clip()], c.time_to_x(12.5), Y["V1"])
    assert hit.zone == "body"
    assert it.mode == InteractionMode.DRAG_ELEMENT

    preview = it.update(c.time_to_x(30.0), Y["V1"], tracks(), [clip()])
    assert preview.start == pytest.approx(27.5)
    assert preview.duration == pytest.approx(10.0)

    commit = it.commit()
    assert isinstance(commit, MoveCommit)
    assert (commit.element_id, commit.start, commit.track_id) == ("clip_001", 27.5, "V1")


def test_按下之后视图滚动不影响手势():
    """press 时就把坐标快照捏住了 —— 这正是"点中间被算成点边缘"的直接修复。"""
    c = coord()
    it = TimelineInteraction()
    it.begin_press(c, [clip()], c.time_to_x(12.5), Y["V1"])
    assert it.coordinate() is c

    # 视图被别的信号滚走 1000px，控件仍然拿手势快照换算
    rolled = c.with_scroll(scroll_x=1000.0)
    assert rolled.time_to_x(12.5) != c.time_to_x(12.5)
    preview = it.update(c.time_to_x(20.0), Y["V1"], tracks(), [clip()])
    assert preview.start == pytest.approx(17.5), "grab_offset 仍是 2.5，没有被滚动污染"


def test_原地按下再松手不产生任何改动():
    c = coord()
    it = TimelineInteraction()
    it.begin_press(c, [clip()], c.time_to_x(12.5), Y["V1"])
    assert it.commit() is None, "没动过就不该写模型"


def test_一次手势只产出一条_commit():
    """拖动过程中 update 几十次，commit 仍然只有一条 —— 撤销栈里就是一步。"""
    c = coord()
    it = TimelineInteraction()
    it.begin_press(c, [clip()], c.time_to_x(12.5), Y["V1"])
    for x in range(1000, 2400, 40):
        it.update(float(x), Y["V1"], tracks(), [clip()])
    commit = it.commit()
    assert isinstance(commit, MoveCommit)
    it.reset()
    assert it.mode == InteractionMode.NONE and it.preview is None


def test_跨轨道移动到同类轨道():
    c = coord()
    it = TimelineInteraction()
    it.begin_press(c, [clip()], c.time_to_x(12.5), Y["V1"])
    preview = it.update(c.time_to_x(20.0), Y["V2"], tracks(), [clip()])
    assert preview.track_id == "V2" and preview.valid is True
    assert it.commit().track_id == "V2"


def test_拖到不兼容轨道时退回原轨道并给出原因():
    """视频拖到音频轨：位置照走，轨道退回 V1，状态栏能拿到原因。"""
    c = coord()
    it = TimelineInteraction()
    it.begin_press(c, [clip()], c.time_to_x(12.5), Y["V1"])
    preview = it.update(c.time_to_x(20.0), Y["A1"], tracks(), [clip()])
    assert preview.track_id == "V1"
    assert preview.valid is True
    assert it.commit().track_id == "V1"


def test_锁定轨道上的元素不进入拖动状态():
    c = coord()
    it = TimelineInteraction()
    hit = it.begin_press(c, [clip()], c.time_to_x(12.5), Y["V1"], allow_edit=False)
    assert hit.element_id == "clip_001", "仍然能选中"
    assert it.mode == InteractionMode.NONE
    assert it.update(c.time_to_x(20.0), Y["V1"], tracks(), [clip()]) is None


def test_点空白进入框选状态():
    c = coord()
    it = TimelineInteraction()
    it.begin_press(c, [clip()], c.time_to_x(50.0), Y["V1"])
    assert it.mode == InteractionMode.RUBBER
    assert it.rubber_origin() == (c.time_to_x(50.0), Y["V1"])
    assert it.update(c.time_to_x(60.0), Y["V1"], tracks(), [clip()]) is None
    assert it.commit() is None


def test_多选整体平移按同一位移搬走其它元素():
    c = coord()
    elements = [clip("clip_001"), clip("clip_002", start=30.0, duration=5.0)]
    it = TimelineInteraction()
    it.begin_press(
        c, elements, c.time_to_x(12.5), Y["V1"], selection=["clip_001", "clip_002"]
    )
    it.update(c.time_to_x(20.0), Y["V1"], tracks(), elements)
    commit = it.commit()
    assert commit.start == pytest.approx(17.5)
    assert commit.followers == (("clip_002", pytest.approx(37.5)),)


def test_多选平移不会把跟随元素推到负时间():
    c = coord()
    elements = [clip("clip_001"), clip("clip_002", start=1.0, duration=1.0)]
    it = TimelineInteraction()
    it.begin_press(
        c, elements, c.time_to_x(12.5), Y["V1"], selection=["clip_001", "clip_002"]
    )
    it.update(c.time_to_x(2.5), Y["V1"], tracks(), elements)
    commit = it.commit()
    assert commit.start >= 0.0
    assert all(start >= 0.0 for _, start in commit.followers)


def test_移动结果对齐到帧网格():
    c = coord(pixels_per_second=800.0)
    it = TimelineInteraction()
    it.begin_press(c, [clip()], c.time_to_x(12.5), Y["V1"])
    # 12.3457 不在帧网格上；关掉磁吸，只看帧对齐
    it.snap.enabled = False
    preview = it.update(c.time_to_x(12.3457), Y["V1"], tracks(), [clip()])
    assert preview.start == pytest.approx(c.snap_time(preview.start))


# ------------------------------------------------------------ 外部素材拖入


def test_素材落下时左边缘对准鼠标():
    """第六条：所见即所得 —— 鼠标在 20s，片段就从 20s 开始。"""
    c = coord()
    it = TimelineInteraction()
    it.begin_asset_drag(c, [], {"kind": "asset", "id": "video_001"}, 5.0, "video", "demo.mp4")
    preview = it.update(c.time_to_x(20.0), Y["V1"], tracks(), [])
    assert preview.mode == InteractionMode.DRAG_ASSET
    assert preview.start == pytest.approx(20.0)
    assert preview.duration == pytest.approx(5.0)
    assert preview.end == pytest.approx(25.0)
    assert preview.label == "demo.mp4"

    commit = it.commit()
    assert isinstance(commit, DropCommit)
    assert commit.start == pytest.approx(20.0)
    assert commit.track_id == "V1"
    assert commit.payload == {"kind": "asset", "id": "video_001"}, "内部标签不许漏进 payload"


def test_落点在零点左侧被钳到零():
    c = coord(scroll_x=0.0)
    it = TimelineInteraction()
    it.begin_asset_drag(c, [], {"kind": "asset", "id": "video_001"}, 5.0, "video")
    preview = it.update(-500.0, Y["V1"], tracks(), [])
    assert preview.start == 0.0


def test_素材落到不兼容轨道时被拒():
    c = coord()
    it = TimelineInteraction()
    it.begin_asset_drag(c, [], {"kind": "asset", "id": "audio_001"}, 4.0, "audio")
    preview = it.update(c.time_to_x(20.0), Y["V1"], tracks(), [])
    assert preview.valid is False
    assert "音频" in preview.reason and "V1" in preview.reason
    assert it.commit() is None, "非法落点绝不能落库"


def test_素材落到锁定轨道时被拒():
    c = coord()
    it = TimelineInteraction()
    it.begin_asset_drag(c, [], {"kind": "asset", "id": "video_001"}, 4.0, "video")
    preview = it.update(c.time_to_x(20.0), Y["V2"], tracks(locked=("V2",)), [])
    assert preview.valid is False and "已锁定" in preview.reason


def test_落到轨道区之外被拒():
    c = coord()
    it = TimelineInteraction()
    it.begin_asset_drag(c, [], {"kind": "asset", "id": "video_001"}, 4.0, "video")
    preview = it.update(c.time_to_x(20.0), 9999.0, tracks(), [])
    assert preview.valid is False and preview.reason == "这里没有轨道"


def test_未知类型不受轨道种类限制():
    """模板 / 转场这类不落轨的东西，type 传空串，不能被误拦。"""
    ok, reason = TimelineInteraction.track_allows("", {"id": "A1", "kind": "audio"})
    assert ok is True and reason == ""


def test_素材落下时会吸附到已有片段末尾():
    """9.9 不是任何整齐刻度，能吸上说明吸的是片段末尾而不是刻度。"""
    c = coord()
    existing = [clip("clip_001", start=0.0, duration=9.9)]
    it = TimelineInteraction()
    it.begin_asset_drag(c, existing, {"kind": "asset", "id": "video_001"}, 5.0, "video")
    preview = it.update(c.time_to_x(9.85), Y["V2"], tracks(), existing)
    assert preview.start == pytest.approx(9.9)
    assert preview.snap is not None
    assert "片段末尾" in preview.snap_label


def test_吸附之后仍然落在帧网格上():
    """磁吸目标不在帧网格上时，帧对齐是最后一道 —— 落库的时间必须是整帧。"""
    c = coord()
    existing = [clip("clip_001", start=0.0, duration=9.96)]
    it = TimelineInteraction()
    it.begin_asset_drag(c, existing, {"kind": "asset", "id": "video_001"}, 5.0, "video")
    preview = it.update(c.time_to_x(9.9), Y["V2"], tracks(), existing)
    assert preview.start == pytest.approx(c.snap_time(9.96))
    assert preview.start == pytest.approx(round(round(9.96 * 30) / 30, 6))


def test_拖动已有片段时标记也是磁吸目标():
    """标记点是「我想在这里切」的意图，拖片段时首尾都该能吸上去。

    时间点特意选在刻度线之外（20.23 不是 0.5s 的整数倍），
    否则刻度吸附会先把它抢走，测不出标记有没有生效。
    """
    c = coord()
    existing = [clip("clip_001", start=10.0, duration=10.0)]
    it = TimelineInteraction()
    it.begin_press(c, existing, c.time_to_x(15.0), Y["V1"], markers=[20.23])
    preview = it.update(c.time_to_x(15.3), Y["V1"], tracks(), existing)
    # grab_offset=5s → 原始 start 10.3、尾部 20.3；尾部离标记 0.07s，赢下竞争
    assert preview.start == pytest.approx(c.snap_time(20.23 - 10.0))


def test_没有标记时不会凭空多出磁吸点():
    c = coord()
    existing = [clip("clip_001", start=10.0, duration=10.0)]
    it = TimelineInteraction()
    it.begin_press(c, existing, c.time_to_x(15.0), Y["V1"])
    preview = it.update(c.time_to_x(15.3), Y["V1"], tracks(), existing)
    assert preview.start == pytest.approx(c.snap_time(10.3))


def test_素材拖入时标记同样参与磁吸():
    c = coord()
    it = TimelineInteraction()
    it.begin_asset_drag(
        c, [], {"kind": "asset", "id": "video_001"}, 5.0, "video", "demo.mp4", markers=[20.23]
    )
    preview = it.update(c.time_to_x(20.3), Y["V1"], tracks(), [])
    assert preview.start == pytest.approx(c.snap_time(20.23))


# ------------------------------------------------------------ 裁剪


def test_拖左边缘同时改_start_与_duration():
    c = coord()
    it = TimelineInteraction()
    it.begin_press(c, [clip()], c.time_to_x(10.05), Y["V1"])
    assert it.mode == InteractionMode.RESIZE_LEFT

    preview = it.update(c.time_to_x(12.0), Y["V1"], tracks(), [clip()])
    assert preview.start == pytest.approx(12.0)
    assert preview.duration == pytest.approx(8.0), "右端固定在 20s"

    commit = it.commit()
    assert isinstance(commit, ResizeCommit)
    assert (commit.start, commit.duration, commit.edge) == (12.0, 8.0, "left")


def test_拖右边缘只改_duration():
    c = coord()
    it = TimelineInteraction()
    it.begin_press(c, [clip()], c.time_to_x(19.95), Y["V1"])
    assert it.mode == InteractionMode.RESIZE_RIGHT

    preview = it.update(c.time_to_x(18.0), Y["V1"], tracks(), [clip()])
    assert preview.start == pytest.approx(10.0), "左端不动"
    assert preview.duration == pytest.approx(8.0)
    assert it.commit().edge == "right"


def test_裁剪不会短于一帧():
    c = coord()
    it = TimelineInteraction()
    it.begin_press(c, [clip()], c.time_to_x(19.95), Y["V1"])
    preview = it.update(c.time_to_x(5.0), Y["V1"], tracks(), [clip()])
    assert preview.duration == pytest.approx(1.0 / 30.0, abs=1e-6)


def test_左边缘越过右端也不会变成负时长():
    c = coord()
    it = TimelineInteraction()
    it.begin_press(c, [clip()], c.time_to_x(10.05), Y["V1"])
    preview = it.update(c.time_to_x(50.0), Y["V1"], tracks(), [clip()])
    assert preview.duration >= 1.0 / 30.0
    assert preview.start <= 20.0


def test_裁剪不会换轨道():
    c = coord()
    it = TimelineInteraction()
    it.begin_press(c, [clip()], c.time_to_x(10.05), Y["V1"])
    preview = it.update(c.time_to_x(12.0), Y["A1"], tracks(), [clip()])
    assert preview.track_id == "V1", "拖边缘就是裁剪，鼠标飘到别的轨也不换轨"


def test_窄片段优先移动而不是裁剪():
    """Resize 优先于 Move，但窄片段整体是 body —— 否则中间没有可移动区。"""
    c = coord()
    tiny = clip(start=5.0, duration=0.03)
    it = TimelineInteraction()
    hit_rect = c.element_to_hit_rect(tiny)
    it.begin_press(c, [tiny], hit_rect.left + 1.0, Y["V1"])
    assert it.mode == InteractionMode.DRAG_ELEMENT
