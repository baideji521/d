"""时间换算工具。

本项目的铁律：JSON 里只出现「秒」，帧只在渲染层内部存在。
GUI 与 AI 都不应该看到 frame，唯一的换算入口就是这个模块。
"""

from __future__ import annotations

DEFAULT_FPS = 30


def seconds_to_frames(seconds: float, fps: float = DEFAULT_FPS) -> int:
    """秒 -> 帧。与 Remotion 侧 render.mjs 使用完全相同的四舍五入规则。"""
    return int(round(float(seconds) * float(fps)))


def frames_to_seconds(frames: int, fps: float = DEFAULT_FPS) -> float:
    """帧 -> 秒。仅供 GUI 内部对齐网格使用，不写入 JSON。"""
    return float(frames) / float(fps)


def snap_to_frame(seconds: float, fps: float = DEFAULT_FPS) -> float:
    """把任意秒数吸附到最近的整帧边界，避免拖动产生 12.333333333 这类脏数据。"""
    return round(seconds_to_frames(seconds, fps) / float(fps), 6)


def clamp(value: float, low: float, high: float) -> float:
    """把数值限制在闭区间内。"""
    if value < low:
        return low
    if value > high:
        return high
    return value


def format_timecode(seconds: float, fps: float = DEFAULT_FPS) -> str:
    """格式化为 mm:ss.cc（百分秒），Timeline 刻度与属性面板共用。"""
    seconds = max(0.0, float(seconds))
    minutes = int(seconds // 60)
    rest = seconds - minutes * 60
    return f"{minutes:02d}:{rest:05.2f}"


def format_seconds(seconds: float) -> str:
    """属性面板展示用：保留两位小数并带单位。"""
    return f"{float(seconds):.2f}s"


def ranges_overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
    """判断两个时间区间是否重叠（端点相接不算重叠）。"""
    return a_start < b_end and b_start < a_end
