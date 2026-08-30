"""全局输出音量 meta.master_volume 的测试。

这是一条**兼容扩展**：缺省即 1，等于 1 时不落盘，v1 / v2 schema 都显式允许。
Remotion 侧由 `masterVolume()` / `resolveVolume()` 执行（见 remotion/src/lib/timeline.ts
与 lib/timeline.test.ts），这里只管 Python 侧的语义与稀疏性。

预览没有音频通路，所以这个字段影响的是**导出的 MP4**，不是预览。
"""

from __future__ import annotations

import pytest

from core import sparse
from core import timeline as tl
from core.migrations import migrate_to_v1, migrate_v1_to_v2


# ---------------------------------------------------------------- 取值语义


def test_缺省就是1():
    assert tl.effective_master_volume(tl.empty_timeline()) == 1.0
    assert tl.effective_master_volume({}) == 1.0


def test_越界夹到范围内():
    low, high = tl.MASTER_VOLUME_RANGE
    assert tl.effective_master_volume({"meta": {"master_volume": -3}}) == low
    assert tl.effective_master_volume({"meta": {"master_volume": 99}}) == high


def test_脏数据按默认值走():
    for bad in ("大声点", None, [], float("nan"), float("inf")):
        assert tl.effective_master_volume({"meta": {"master_volume": bad}}) == 1.0


def test_零表示静音而不是缺省():
    assert tl.effective_master_volume({"meta": {"master_volume": 0}}) == 0.0


# ---------------------------------------------------------------- 稀疏


def test_等于默认值时不落盘():
    data = tl.empty_timeline()
    data["meta"]["master_volume"] = 1.0
    assert "master_volume" not in sparse.sparse_timeline(data)["meta"]


def test_不等于默认值时保留():
    data = tl.empty_timeline()
    data["meta"]["master_volume"] = 0.35
    assert sparse.sparse_timeline(data)["meta"]["master_volume"] == 0.35


def test_静音要保留():
    data = tl.empty_timeline()
    data["meta"]["master_volume"] = 0
    assert sparse.sparse_timeline(data)["meta"]["master_volume"] == 0


def test_默认时间线里根本没有这个字段():
    assert "master_volume" not in sparse.sparse_timeline(tl.empty_timeline())["meta"]


# ---------------------------------------------------------------- 迁移


def test_v1_v2_往返不丢全局音量():
    data = tl.empty_timeline("音量项目")
    data["meta"]["master_volume"] = 0.5
    back = migrate_to_v1(migrate_v1_to_v2(data))
    assert back["meta"]["master_volume"] == 0.5


# ---------------------------------------------------------------- 模型


def test_模型改音量并可撤销(model):
    model.set_master_volume(0.4)
    assert model.master_volume == pytest.approx(0.4)
    model.undo()
    assert model.master_volume == 1.0


def test_改回默认值时字段消失(model):
    model.set_master_volume(0.4)
    model.set_master_volume(1.0)
    assert "master_volume" not in model.to_dict()["meta"]


def test_同值重复设置不产生撤销步骤(model):
    model.set_master_volume(1.0)
    assert model.to_dict()["meta"].get("master_volume") is None
    model.set_master_volume(0.4)
    model.set_master_volume(0.4)
    model.undo()
    assert model.master_volume == 1.0, "第二次同值设置不该多压一步撤销"


def test_非法值不改状态也不抛(model):
    model.set_master_volume("很大声")
    assert model.master_volume == 1.0


def test_模型也做范围夹取(model):
    model.set_master_volume(9.0)
    assert model.master_volume == tl.MASTER_VOLUME_RANGE[1]


# ---------------------------------------------------------------- 校验器


@pytest.mark.parametrize("value", [0, 0.5, 1, 2, 4])
def test_合法音量能过校验(validator, timeline, value):
    timeline["meta"]["master_volume"] = value
    errors = [i for i in validator.validate(timeline) if i.is_error()]
    assert errors == []


@pytest.mark.parametrize("value", [-1, 5, "大声"])
def test_非法音量被校验拦住(validator, timeline, value):
    timeline["meta"]["master_volume"] = value
    errors = [i for i in validator.validate(timeline) if i.is_error()]
    assert errors, "超范围 / 类型不对必须报错"
