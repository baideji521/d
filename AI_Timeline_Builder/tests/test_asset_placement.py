"""素材落位策略的回归测试。

这里锁住的是「拖进来的东西默认去哪条轨道」这套规则本身。
规则以前散在 GUI 三处，现在只有一份，测试就守着这一份。
"""

import pytest

from gui import asset_placement as ap


def asset(**kwargs):
    base = {"id": "a1", "name": "a1", "type": "video", "path": "assets/video/a1.mp4"}
    base.update(kwargs)
    return base


def tracks(locked=()):
    from core import timeline as tl
    rows = []
    for track in tl.DEFAULT_TRACKS:
        row = dict(track)
        row["locked"] = row["id"] in locked
        rows.append(row)
    return rows


def clip(track="V1", start=0.0, duration=5.0, element_id="clip_001", element_type="video"):
    return {"id": element_id, "type": element_type, "track": track,
            "start": start, "duration": duration}


# ---------------------------------------------------------------- 角色判定


@pytest.mark.parametrize("kwargs, expected", [
    ({"type": "video"}, "video"),
    ({"type": "image", "path": "assets/image/arrow.png"}, "image"),
    ({"type": "overlay"}, "overlay"),
    # 图片但明显是叠加素材
    ({"type": "image", "category": "light_leak"}, "overlay"),
    ({"type": "video", "name": "dust_particles"}, "overlay"),
    # 音频按目录分角色
    ({"type": "audio", "category": "bgm"}, "music"),
    ({"type": "audio", "category": "voice"}, "voice"),
    ({"type": "audio", "category": "boom"}, "sfx"),
    ({"type": "audio", "category": "footstep"}, "sfx"),
    # 不认识的类型按视频兜底（最保守，kind 不会放错）
    ({"type": "font"}, "video"),
])
def test_素材角色判定(kwargs, expected):
    assert ap.classify(asset(**kwargs)) == expected


def test_脏数据不许崩():
    assert ap.classify({}) == "video"
    assert ap.classify(None) == "video"
    assert ap.classify({"type": 123, "tags": "不是列表"}) == "video"


@pytest.mark.parametrize("role, track, element_type", [
    ("video", "V1", "video"),
    ("image", "V3", "overlay"),
    ("overlay", "V4", "overlay"),
    ("music", "A1", "audio"),
    ("voice", "A2", "audio"),
    ("sfx", "A3", "audio"),
    ("caption", "T1", "caption"),
    ("text", "T2", "text"),
])
def test_每个角色的默认轨道(role, track, element_type):
    placement = ap.for_role(role)
    assert (placement.default_track, placement.element_type) == (track, element_type)


def test_轨道_kind_必须与元素类型匹配():
    assert ap.for_role("video").track_kind == "video"
    assert ap.for_role("sfx").track_kind == "audio"
    assert ap.for_role("caption").track_kind == "text"
    assert ap.for_role("text").track_kind == "text"


def test_库面板按元素类型也能问到策略():
    assert ap.for_element_type("caption").default_track == "T1"
    assert ap.for_element_type("caption_group").default_track == "T1"
    assert ap.for_element_type("text").default_track == "T2"
    assert ap.for_element_type("overlay").default_track == "V3"
    assert ap.for_element_type("不存在").default_track == "V1"


# ---------------------------------------------------------------- 选轨


def test_空时间线就落在默认轨():
    placement = ap.for_role("video")
    track, reason = ap.choose_track(placement, tracks(), [], 0.0, 5.0)
    assert track == "V1"
    assert "V1" in reason


def test_默认轨被占就顺延到下一条():
    placement = ap.for_role("video")
    track, reason = ap.choose_track(placement, tracks(), [clip("V1", 0.0, 10.0)], 2.0, 3.0)
    assert track == "V2"
    assert "顺延" in reason


def test_端点相接不算冲突():
    placement = ap.for_role("video")
    # 已有 0~10，新的从 10 开始，可以继续待在 V1
    track, _ = ap.choose_track(placement, tracks(), [clip("V1", 0.0, 10.0)], 10.0, 3.0)
    assert track == "V1"


def test_一路被占就一路往上让():
    placement = ap.for_role("video")
    busy = [clip("V1", 0.0, 10.0, "c1"), clip("V2", 0.0, 10.0, "c2"),
            clip("V3", 0.0, 10.0, "c3")]
    track, _ = ap.choose_track(placement, tracks(), busy, 1.0, 2.0)
    assert track == "V4"


def test_全被占也不能丢掉这次操作():
    placement = ap.for_role("video")
    busy = [clip(f"V{i}", 0.0, 10.0, f"c{i}") for i in range(1, 5)]
    track, reason = ap.choose_track(placement, tracks(), busy, 1.0, 2.0)
    assert track == "V1", "最后仍然回到默认轨，而不是静默失败"
    assert "重叠" in reason


def test_用户指着哪条轨就放哪条():
    placement = ap.for_role("video")
    # V2 上已经有东西，但用户的鼠标就悬在 V2
    track, reason = ap.choose_track(placement, tracks(), [clip("V2", 0.0, 10.0)],
                                    1.0, 2.0, requested_track="V2")
    assert track == "V2"
    assert "指定" in reason


def test_指定的轨道_kind_不对就忽略这个指定():
    placement = ap.for_role("video")
    track, _ = ap.choose_track(placement, tracks(), [], 0.0, 2.0, requested_track="A1")
    assert track == "V1"


def test_锁定的轨道不参与落位():
    placement = ap.for_role("video")
    track, _ = ap.choose_track(placement, tracks(locked=("V1",)), [], 0.0, 2.0)
    assert track == "V2"
    # 明确指定锁定轨也不行
    track, _ = ap.choose_track(placement, tracks(locked=("V1",)), [], 0.0, 2.0,
                               requested_track="V1")
    assert track == "V2"


def test_特效和转场不占位():
    placement = ap.for_role("video")
    attached = [clip("V1", 0.0, 10.0, "e1", "effect"), clip("V1", 0.0, 10.0, "t1", "transition")]
    track, _ = ap.choose_track(placement, tracks(), attached, 1.0, 2.0)
    assert track == "V1"


def test_字幕重叠也不换轨():
    # 字幕经常需要同轨紧挨着排，甚至短暂重叠，不该被自动挪到 T2
    placement = ap.for_role("caption")
    assert placement.avoid_overlap is False
    track, _ = ap.choose_track(placement, tracks(), [clip("T1", 0.0, 10.0, "cap", "caption")],
                               1.0, 2.0)
    assert track == "T1"


def test_音效按音频轨顺延():
    placement = ap.for_role("sfx")
    track, _ = ap.choose_track(placement, tracks(), [clip("A3", 0.0, 10.0, "s1", "audio")],
                               1.0, 0.5)
    assert track == "A2"


# ------------------------------------------------- 拖拽过程中的顺延（以鼠标轨道为起点）


def test_鼠标指的轨道空着就不动():
    placement = ap.for_role("video")
    track, note = ap.next_free_track(placement, tracks(), [], 0.0, 2.0, "V3")
    assert (track, note) == ("V3", "")


def test_鼠标指的轨道被占就从这条往后顺延():
    placement = ap.for_role("video")
    # 用户指着 V2，V2 被占，V3 空着 → 去 V3，而不是回到策略默认的 V1
    busy = [clip("V2", 0.0, 10.0, "c2")]
    track, note = ap.next_free_track(placement, tracks(), busy, 1.0, 2.0, "V2")
    assert track == "V3"
    assert "顺延" in note and "V2" in note


def test_顺延会绕回前面的轨道():
    placement = ap.for_role("video")
    busy = [clip("V2", 0.0, 10.0, "c2"), clip("V3", 0.0, 10.0, "c3"),
            clip("V4", 0.0, 10.0, "c4")]
    track, _ = ap.next_free_track(placement, tracks(), busy, 1.0, 2.0, "V2")
    assert track == "V1", "V3/V4 都满了就绕回 V1"


def test_全满时留在鼠标那条轨并说明会重叠():
    placement = ap.for_role("video")
    busy = [clip(f"V{i}", 0.0, 10.0, f"c{i}") for i in range(1, 5)]
    track, note = ap.next_free_track(placement, tracks(), busy, 1.0, 2.0, "V2")
    assert track == "V2"
    assert "重叠" in note


def test_不避让的类型永远不顺延():
    placement = ap.for_role("caption")
    track, note = ap.next_free_track(placement, tracks(),
                                     [clip("T1", 0.0, 10.0, "cap", "caption")],
                                     1.0, 2.0, "T1")
    assert (track, note) == ("T1", "")

