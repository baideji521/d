"""验收分析器自身的回归测试（阶段 6.5 TEST_HARNESS_CORRECTION）。

验收器一旦误判，后果比产品 Bug 更糟：真 Bug 会被「已 PASS」盖住，
或者正确行为被当成 Bug 去改产品代码。所以判据本身也要有测试守着。

这里只测纯函数（不需要 MP4 / ffmpeg）：
- effect_is_noop：按 remotion/src/effects/*.ts 的数学判断参数是否等价于不生效
- effect_blanks_canvas：按同样的数学判断参数是否**本来就该**把画面清成纯背景
- unexpected_black：区分「设计上的纯色窗口」与真正的异常黑帧
- sparse_change：稀疏改动度量，用于「灰尘 / 火花」这类低平均差、高局部差的素材
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCEPTANCE = os.path.join(ROOT, "out", "acceptance")
if ACCEPTANCE not in sys.path:
    sys.path.insert(0, ACCEPTANCE)

analyze = pytest.importorskip("analyze", reason="验收工具未就绪")


def effect(name, params):
    return {"type": "effect", "name": name, "params": params}


# ---------------------------------------------------------------- 空操作判定


@pytest.mark.parametrize("element", [
    # shake：amplitude 与 rotation 都是 0 → x/y/rotation 全不变（shake.ts）
    effect("shake", {"amplitude": 0.0, "frequency": 1.0, "rotation": 0.0}),
    # spin：from == to 且是整圈 → 旋转 720° 与不旋转画面一致（spin.ts）
    effect("spin", {"from": -720.0, "to": -720.0}),
    effect("spin", {"from": 720.0, "to": 720.0}),
    # bounce：height=0 → offset 恒为 0（bounce.ts）
    effect("bounce", {"height": 0.0, "bounces": 1}),
    # glitch / vignette / rgb_split：低于阈值时 Component 直接返回 null
    effect("glitch", {"intensity": 0.0, "slices": 2, "color_shift": 0.0}),
    effect("vignette", {"intensity": 0.0, "radius": 0.1}),
    effect("rgb_split", {"offset": 0.0, "angle": 0.0}),
    effect("zoom", {"scale_from": 1.0, "scale_to": 1.0}),
    effect("pulse", {"scale_min": 1.0, "scale_max": 1.0}),
    effect("blur", {"radius_from": 0.0, "radius_to": 0.0}),
    effect("motion_blur", {"amount": 0.0}),
    effect("brightness", {"value_from": 1.0, "value_to": 1.0}),
])
def test_数学上不改变画面的参数必须判成空操作(element):
    assert analyze.effect_is_noop(element) is True


@pytest.mark.parametrize("element", [
    effect("shake", {"amplitude": 0.05, "frequency": 18.0, "rotation": 0.0}),
    effect("spin", {"from": 0.0, "to": 180.0}),
    effect("spin", {"from": 90.0, "to": 90.0}),      # 90° 不是整圈，画面是斜的
    effect("bounce", {"height": 0.08, "bounces": 2}),
    effect("glitch", {"intensity": 0.6, "slices": 12}),
    effect("vignette", {"intensity": 0.5, "radius": 0.75}),
    # 旧实现的坑：offset=8 曾经画不出东西，但参数本身不是空操作，必须判成「应当生效」
    effect("rgb_split", {"offset": 8.0, "angle": 0.0}),
    effect("rgb_split", {"offset": 60.0, "angle": 360.0}),
    effect("zoom", {"scale_from": 1.0, "scale_to": 1.3}),
    effect("brightness", {"value_from": 1.0, "value_to": 1.6}),
])
def test_会改变画面的参数不许被当成空操作(element):
    assert analyze.effect_is_noop(element) is False


def test_参数类型不对时按_renderer_默认值判断():
    # num() 遇到非数字退回默认值，判据必须跟着退回，不能崩
    assert analyze.effect_is_noop(effect("zoom", {"scale_from": "一倍"})) is False
    assert analyze.effect_is_noop(effect("shake", {"amplitude": None})) is False


# ---------------------------------------------------------------- 稀疏改动度量


def frame(pixels):
    out = bytearray()
    for r, g, b in pixels:
        out += bytes((r, g, b))
    return bytes(out)


def test_稀疏改动度量抓得住少数像素的剧烈变化():
    base = frame([(10, 10, 10)] * 100)
    # 只改 2 个像素，但改得很狠：平均差会被摊薄到 ~4，峰值必须留下来
    changed = [(10, 10, 10)] * 100
    changed[7] = (255, 255, 255)
    changed[42] = (255, 255, 255)
    result = analyze.sparse_change(base, frame(changed))
    assert result["max"] >= 200
    assert result["ratio"] == pytest.approx(0.02)
    assert result["mean"] < 6  # 平均差确实很小 —— 这正是需要换指标的原因


def test_完全一样的两帧稀疏改动为零():
    same = frame([(30, 60, 90)] * 50)
    result = analyze.sparse_change(same, same)
    assert result == {"mean": 0.0, "max": 0.0, "ratio": 0.0}


def test_整屏轻微变化不会被当成稀疏改动():
    base = frame([(100, 100, 100)] * 100)
    drift = frame([(104, 104, 104)] * 100)  # 每个像素只差 4，低于阈值 12
    result = analyze.sparse_change(base, drift)
    assert result["ratio"] == 0.0
    assert result["max"] == pytest.approx(4.0, abs=1.0)


# ---------------------------------------------------------------- 帧对齐


def test_采样时间必须落到真实帧时刻():
    # 30fps：0.05s 落在第 1 帧（1/30 = 0.033333s）覆盖的区间里，
    # 但 ffmpeg -ss 0.05 会取到第 2 帧，所以必须先落回第 1 帧
    assert analyze.snap_to_frame(0.05, 2.048) == 0.033333
    assert analyze.snap_to_frame(0.0, 2.048) == 0.0
    assert analyze.snap_to_frame(1.0, 2.048) == 1.0


def test_对齐后的时间再对齐一次结果不变():
    # JSON 里的时间常常是截断值（1/30 写成 0.033333 甚至 0.033），
    # 严格 floor 会把它算成上一帧 —— 一帧长的特效就是这样被量丢的
    for stamp in (0.033, 0.033333, 1 / 30):
        assert analyze.snap_to_frame(stamp, 2.048) == 0.033333
    once = analyze.snap_to_frame(0.05, 2.048)
    assert analyze.snap_to_frame(once, 2.048) == once


def test_采样时间不许超过最后一帧():
    # 60 帧 / 30fps 的片子，最后一帧在 59/30 = 1.966666s；
    # 容器时长会报 2.048s（带尾部余量），所以帧数要按 ffprobe 数出来的传进去
    assert analyze.snap_to_frame(1.984, 2.048, total_frames=60) == 1.966666
    assert analyze.snap_to_frame(99.0, 2.048, total_frames=60) == 1.966666


def test_没有帧数时按时长兜底不许崩():
    value = analyze.snap_to_frame(99.0, 2.048)
    assert 1.9 <= value <= 2.1


def test_窗口覆盖的帧可以精确算出来():
    fps = 30.0
    # 只持续一帧：[1/30, 2/30) 只盖住第 1 帧
    assert analyze.frames_in_window(1 / fps, 2 / fps, fps) == [0.033333]
    # JSON 里写的是截断值，结果必须一样
    assert analyze.frames_in_window(0.033333, 0.066666, fps) == [0.033333]
    # 半帧：[1.0, 1.0+1/60) 仍然盖住正好落在 1.0s 的第 30 帧
    assert analyze.frames_in_window(1.0, 1.0 + 1 / 60, fps) == [1.0]
    # 整段落在两帧之间：一帧都盖不到，Runtime 不画才是对的
    assert analyze.frames_in_window(1.005, 1.02, fps) == []
    # 1 秒窗口盖住 30 帧
    assert len(analyze.frames_in_window(0.5, 1.5, fps)) == 30


def test_窗口判定不许比_runtime_宽容():
    # 60 帧的片子（0..59），末帧在 1.966666s。
    # JSON 里 start 被截成 1.967 时，Runtime 的 now >= start 对末帧不成立 → 一帧都不画。
    # 验收器要是加容差把末帧算进去，就会把正确行为报成 Bug。
    assert analyze.frames_in_window(1.967, 2.0, 30.0, total_frames=60) == []


def test_窗口不许超出实际帧数():
    # [1.9, 2.5) 按公式能算到第 74 帧，但片子只有 60 帧
    covered = analyze.frames_in_window(1.9, 2.5, 30.0, total_frames=60)
    assert covered[-1] == 1.966666


# ------------------------------------------------------- 设计上就该清空画面的参数


@pytest.mark.parametrize("element", [
    # effect_zoom_min：scale 0.1 → 可见面积 1%，其余全是合成背景（黑）
    effect("zoom", {"scale_from": 0.1, "scale_to": 0.1, "origin_x": 0.0, "origin_y": 0.0}),
    # 只要区间里有一端缩到极小就会经过「几乎全黑」的那一段
    effect("zoom", {"scale_from": 0.1, "scale_to": 1.3}),
    # effect_pulse_min：scale 0.1
    effect("pulse", {"scale_min": 0.1, "scale_max": 0.1, "cycles": 1}),
    # effect_brightness_min：整帧乘 0
    effect("brightness", {"value_from": 0.0, "value_to": 0.0}),
])
def test_数学上会把画面清空的参数必须登记成设计黑帧(element):
    assert analyze.effect_blanks_canvas(element) is True


@pytest.mark.parametrize("element", [
    # 0.2² = 4% > 2%，画面还剩得下东西，黑帧就是异常
    effect("zoom", {"scale_from": 0.2, "scale_to": 0.2}),
    effect("zoom", {"scale_from": 1.0, "scale_to": 1.3}),
    effect("pulse", {"scale_min": 1.0, "scale_max": 1.08}),
    # 只有一端为 0 时画面会亮回来，不是全程纯黑
    effect("brightness", {"value_from": 0.0, "value_to": 1.0}),
    effect("brightness", {"value_from": 1.0, "value_to": 1.6}),
    # blur 半径再大也不会把画面变成纯背景
    effect("blur", {"radius_from": 0.0, "radius_to": 40.0}),
    effect("shake", {"amplitude": 0.0}),
])
def test_不会清空画面的参数不许登记成设计黑帧(element):
    assert analyze.effect_blanks_canvas(element) is False


def test_清空判定遇到脏参数按_renderer_默认值走():
    # num() 退回默认值：scale 默认 1 / 1.3 → 不清空，且不许抛异常
    assert analyze.effect_blanks_canvas(effect("zoom", {"scale_from": "一倍"})) is False
    assert analyze.effect_blanks_canvas(effect("pulse", {"scale_min": None})) is False
    # bool 不算数字（True 会被 float() 变成 1.0，容易误判）
    assert analyze.effect_blanks_canvas(effect("brightness", {"value_from": False,
                                                             "value_to": False})) is False
    assert analyze.effect_blanks_canvas({"type": "effect"}) is False


# ------------------------------------------------------------ 异常黑帧的甄别


def hit(start, end):
    return {"start": start, "end": end, "duration": round(end - start, 3)}


def test_落在设计区间里的黑帧不算异常():
    verdict = {"evidence": {"designed_dark_windows": [[0.5, 1.5]]}}
    # blackdetect 报的区间天然比设计窗口宽一点，±0.08 容差要吃得下
    assert analyze.unexpected_black([hit(0.45, 1.55)], verdict) == []


def test_设计区间之外的黑帧必须报出来():
    verdict = {"evidence": {"designed_dark_windows": [[0.5, 1.5]]}}
    hits = [hit(0.45, 1.55), hit(3.0, 3.4)]
    assert analyze.unexpected_black(hits, verdict) == [hit(3.0, 3.4)]
    # 只有半截落在窗口里也算异常（渲染真的漏了一段）
    assert analyze.unexpected_black([hit(1.0, 2.5)], verdict) == [hit(1.0, 2.5)]


def test_单帧登记方式同样有效():
    # opacity=0 这类用例登记的是时刻列表，不是区间
    verdict = {"evidence": {"dark_by_design": [0.0, 1.0, 1.9]}}
    assert analyze.unexpected_black([hit(0.0, 1.95)], verdict) == []


def test_没有登记任何设计黑帧时全部算异常():
    assert analyze.unexpected_black([hit(0.5, 1.5)], {}) == [hit(0.5, 1.5)]
    assert analyze.unexpected_black([hit(0.5, 1.5)], {"evidence": {}}) == [hit(0.5, 1.5)]


def test_只避开当前窗口不够_要避开所有特征窗口():
    timeline = {"elements": [
        {"type": "video", "start": 0.0, "duration": 2.0},
        {"type": "effect", "start": 0.4, "duration": 1.0},
        {"type": "text", "start": 0.2, "duration": 1.5},
    ]}
    free = analyze.feature_free_stamps(timeline, 2.0)
    assert free, "应当还能找到既没有特效也没有文字的时间点"
    for stamp in free:
        assert not (0.35 <= stamp <= 1.45), f"{stamp} 落在特效窗口里"
        assert not (0.15 <= stamp <= 1.75), f"{stamp} 落在文字窗口里"

