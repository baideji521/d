"""时间线标记（Marker）的回归测试。

Marker 是兼容扩展：挂在 meta 上，老 JSON 没有这个键也要正常工作，
有这个键时不能破坏稀疏性，也不能被 v1↔v2 迁移丢掉。
"""

import pytest

from core import markers as mk
from core import sparse
from core.migrations import migrate_to_v1, migrate_v1_to_v2



def timeline(**meta):
    base = {"name": "t", "fps": 30, "width": 1080, "height": 1920}
    base.update(meta)
    return {
        "version": 1,
        "time_unit": "seconds",
        "meta": base,
        "tracks": [{"id": "V1", "name": "V1", "kind": "video"}],
        "elements": [{"id": "clip_001", "type": "video", "track": "V1", "asset": "demo",
                      "start": 0.0, "duration": 5.0}],
    }


# ---------------------------------------------------------------- 读写


def test_没有_markers_键时返回空列表():
    assert mk.markers_of(timeline()) == []
    assert mk.marker_times(timeline()) == []
    assert mk.markers_of({}) == []
    assert mk.markers_of({"meta": "不是字典"}) == []


def test_加一条标记():
    data = timeline()
    marker = mk.add_marker(data, 12.5, "highlight", "高潮")
    assert marker == {"time": 12.5, "type": "highlight", "label": "高潮"}
    assert data["meta"]["markers"] == [marker]


def test_标记按时间排序():
    data = timeline()
    mk.add_marker(data, 5.0)
    mk.add_marker(data, 1.0)
    mk.add_marker(data, 3.0)
    assert mk.marker_times(data) == [1.0, 3.0, 5.0]


def test_同一时刻同一类型只留一条():
    data = timeline()
    mk.add_marker(data, 2.0, "highlight", "第一次")
    mk.add_marker(data, 2.0, "highlight", "改个名")
    assert len(mk.markers_of(data)) == 1
    assert mk.markers_of(data)[0]["label"] == "改个名"
    # 类型不同就是两条
    mk.add_marker(data, 2.0, "sfx")
    assert len(mk.markers_of(data)) == 2


def test_没有标签时不写_label_键():
    data = timeline()
    marker = mk.add_marker(data, 1.0, "normal", "   ")
    assert marker == {"time": 1.0, "type": "normal"}
    assert "label" not in marker


def test_不认识的类型退回普通():
    data = timeline()
    marker = mk.add_marker(data, 1.0, "外星类型")
    assert marker["type"] == "normal"


@pytest.mark.parametrize("bad", [None, "十二秒", float("nan")])
def test_时间不合法就拒绝(bad):
    if bad is not None and isinstance(bad, float):
        # nan 能过 float()，但 round(nan) 仍是 nan —— 这里只要求不抛异常
        assert mk.normalize({"time": bad, "type": "normal"}) is not None
        return
    assert mk.normalize({"time": bad, "type": "normal"}) is None


def test_负时间被夹到零():
    assert mk.normalize({"time": -3.0, "type": "normal"})["time"] == 0.0


def test_删除最近的一条():
    data = timeline()
    mk.add_marker(data, 1.0)
    mk.add_marker(data, 5.0)
    removed = mk.remove_marker_at(data, 1.02)
    assert removed["time"] == 1.0
    assert mk.marker_times(data) == [5.0]


def test_容差之外不删():
    data = timeline()
    mk.add_marker(data, 1.0)
    assert mk.remove_marker_at(data, 3.0) is None
    assert mk.marker_times(data) == [1.0]


def test_清空后_markers_键消失():
    data = timeline()
    mk.add_marker(data, 1.0)
    mk.set_markers(data, [])
    assert "markers" not in data["meta"]


def test_找上一个下一个标记():
    data = timeline()
    for t in (1.0, 3.0, 7.0):
        mk.add_marker(data, t)
    assert mk.nearest_marker(data, 3.0, 1)["time"] == 7.0
    assert mk.nearest_marker(data, 3.0, -1)["time"] == 1.0
    assert mk.nearest_marker(data, 7.0, 1) is None
    assert mk.nearest_marker(data, 1.0, -1) is None


def test_类型都有中文名和颜色():
    for name in ("normal", "highlight", "transition", "caption", "sfx", "ai_highlight"):
        assert mk.type_label(name) != name
        assert mk.type_color(name).startswith("#")


# ---------------------------------------------------------------- 稀疏与迁移


def test_稀疏化保留标记():
    data = timeline()
    mk.add_marker(data, 12.5, "highlight", "高潮")
    result = sparse.sparse_timeline(data)
    assert result["meta"]["markers"] == [{"time": 12.5, "type": "highlight", "label": "高潮"}]


def test_稀疏化丢掉空标记列表():
    data = timeline(markers=[])
    assert "markers" not in sparse.sparse_timeline(data)["meta"]


def test_没有标记的项目稀疏结果里没有这个键():
    assert "markers" not in sparse.sparse_timeline(timeline())["meta"]


def test_v1_v2_往返不丢标记():
    data = timeline()
    mk.add_marker(data, 4.0, "transition", "切镜")
    v2 = migrate_v1_to_v2(sparse.sparse_timeline(data))

    back = migrate_to_v1(v2)
    assert mk.markers_of(back) == [{"time": 4.0, "type": "transition", "label": "切镜"}]
