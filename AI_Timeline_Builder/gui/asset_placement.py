"""素材落位策略（AssetPlacementPolicy）。

以前「视频默认放 V1、图片放 V3、音乐放 A1」这类规则散在 GUI 各处：
素材面板一处、库面板一处、拖放回调再一处，改一个地方另外两个就不一致。
这里把规则收成一份，GUI 只问三件事：

    这个素材该建成什么元素？   → element_type
    默认放哪条轨道？           → default_track
    默认那条被占了往哪让？     → fallback_tracks

模块**不依赖 Qt**，可以直接单测；也不写 JSON，只回答「应该放哪」，
真正落库仍然走 TimelineModel。

轨道语义沿用 core/timeline.py 的 DEFAULT_TRACKS：
    V1 主视频 / V2 视频叠加 / V3 图片·Overlay / V4 高层 Overlay
    A1 背景音乐 / A2 人声 / A3 音效
    T1 字幕 / T2 普通文字
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from core import timeline as tl

#: 音乐类音频的目录 / 分类名（来自 assets 子目录名或 tags）
MUSIC_HINTS = ("bgm", "music", "背景音乐", "音乐")
#: 人声类音频（tts 目录里的合成配音也算人声，与 libraries/sound_library.py 的建议轨道一致）
VOICE_HINTS = ("voice", "vo", "narration", "speech", "tts", "人声", "配音", "旁白")
#: 明确当作高层叠加素材的提示词
OVERLAY_HINTS = ("overlay", "light_leak", "film_burn", "dust", "flash", "glitch",
                 "speed_lines", "leak", "particle")


@dataclass(frozen=True)
class Placement:
    """一条落位建议。所有字段都是「建议」，最终仍由校验器把关。"""

    role: str                       # music / voice / sfx / video / image / overlay / caption / text
    element_type: str               # 要建成的 Timeline 元素类型
    default_track: str              # 首选轨道
    fallback_tracks: Tuple[str, ...]  # 首选被占用时依次尝试
    avoid_overlap: bool             # True 时会为了不覆盖已有元素而换轨
    label: str                      # 中文说明，用于状态栏 / 日志

    @property
    def track_kind(self) -> str:
        """这个元素类型要求的轨道 kind。"""
        return tl.TYPE_TRACK_KIND.get(self.element_type, "video")

    def candidates(self) -> Tuple[str, ...]:
        return (self.default_track,) + tuple(self.fallback_tracks)


#: 角色 → 落位规则。这是全项目唯一的一份。
POLICIES: Dict[str, Placement] = {
    "video": Placement("video", "video", "V1", ("V2", "V3", "V4"), True, "视频"),
    "image": Placement("image", "overlay", "V3", ("V4", "V2", "V1"), True, "图片"),
    "overlay": Placement("overlay", "overlay", "V4", ("V3", "V2"), True, "叠加素材"),
    "music": Placement("music", "audio", "A1", ("A2", "A3"), True, "背景音乐"),
    "voice": Placement("voice", "audio", "A2", ("A3", "A1"), True, "人声"),
    "sfx": Placement("sfx", "audio", "A3", ("A2", "A1"), True, "音效"),
    "caption": Placement("caption", "caption", "T1", ("T2",), False, "字幕"),
    "text": Placement("text", "text", "T2", ("T1",), False, "文字"),
    "freeze": Placement("freeze", "freeze", "V1", ("V2", "V3", "V4"), True, "冻结帧"),
}


def _text_bag(asset: Dict[str, Any]) -> str:
    """把素材上所有可能带线索的字段拼成一个小写字符串，用于关键词判定。"""
    parts: List[str] = []
    for key in ("category", "id", "name", "path"):
        value = asset.get(key)
        if isinstance(value, str):
            parts.append(value)
    tags = asset.get("tags")
    if isinstance(tags, (list, tuple)):
        parts.extend(str(tag) for tag in tags)
    return " ".join(parts).lower()


def classify(asset: Dict[str, Any]) -> str:
    """判断素材的角色。只看素材自身的元信息，不猜用户意图。"""
    if not isinstance(asset, dict):
        return "video"
    asset_type = str(asset.get("type") or "").lower()
    bag = _text_bag(asset)

    if asset_type == "audio":
        if any(hint in bag for hint in MUSIC_HINTS):
            return "music"
        if any(hint in bag for hint in VOICE_HINTS):
            return "voice"
        return "sfx"
    if asset_type == "overlay":
        return "overlay"
    if asset_type == "image":
        # 图片素材里那些明显是叠加特效的（漏光 / 灰尘 / 划痕）走 V4
        return "overlay" if any(hint in bag for hint in OVERLAY_HINTS) else "image"
    if asset_type == "video":
        # 视频素材同样可能是叠加层（光斑 / 粒子 / 故障感）
        return "overlay" if any(hint in bag for hint in OVERLAY_HINTS) else "video"
    return "video"


def for_asset(asset: Dict[str, Any]) -> Placement:
    """素材 → 落位建议。"""
    return POLICIES[classify(asset)]


def for_role(role: str) -> Placement:
    """角色名 → 落位建议；不认识的角色按视频处理（最保守，不会放错 kind）。"""
    return POLICIES.get(str(role or "").lower(), POLICIES["video"])


def for_element_type(element_type: str) -> Placement:
    """元素类型 → 落位建议。库面板拖「字幕模板 / 文字」这类没有素材的东西时用。"""
    mapping = {
        "video": "video",
        "overlay": "image",
        "audio": "sfx",
        "caption": "caption",
        "caption_group": "caption",
        "text": "text",
        "freeze": "freeze",
    }
    return POLICIES[mapping.get(str(element_type or "").lower(), "video")]


# ---------------------------------------------------------------- 选轨


def _track_index(tracks: Sequence[Dict[str, Any]], track_id: str) -> Optional[Dict[str, Any]]:
    for track in tracks:
        if isinstance(track, dict) and track.get("id") == track_id:
            return track
    return None


def track_accepts(track: Optional[Dict[str, Any]], placement: Placement) -> bool:
    """轨道是否能接受这个元素：存在、没锁、kind 对得上。"""
    if not track:
        return False
    if track.get("locked"):
        return False
    return str(track.get("kind") or "") == placement.track_kind


def occupied(elements: Iterable[Dict[str, Any]], track_id: str,
             start: float, duration: float) -> bool:
    """这条轨道在 [start, start+duration) 区间内是否已经有元素。

    端点相接不算冲突（10~20 与 20~30 可以并存），和 tl.ranges_overlap 一致。
    特效 / 转场是依附在别的元素上的，不参与占位判断。
    """
    end = float(start) + float(duration)
    for element in elements:
        if not isinstance(element, dict) or element.get("track") != track_id:
            continue
        if element.get("type") in ("effect", "transition"):
            continue
        other_start = float(element.get("start", 0.0) or 0.0)
        other_end = tl.element_end(element)
        if other_start < end and float(start) < other_end:
            return True
    return False


def next_free_track(placement: Placement,
                    tracks: Sequence[Dict[str, Any]],
                    elements: Iterable[Dict[str, Any]],
                    start: float,
                    duration: float,
                    from_track: str) -> Tuple[str, str]:
    """从鼠标当前指着的轨道开始往后找一条空着的轨道。

    与 choose_track 的区别：这里**以用户指着的那条轨为起点**，
    只有那条轨在这段时间已经被占用时才往策略给的后备轨顺延。
    拖拽过程中调用，ghost 会实时跳到真正会落下的那条轨上，
    用户松手前就看得见结果 —— 不是"松手后被偷偷挪走"。

    返回 (轨道 id, 说明)。说明为空表示没有发生顺延。
    """
    elements = list(elements)
    if not placement.avoid_overlap:
        return from_track, ""
    if not occupied(elements, from_track, start, duration):
        return from_track, ""

    ordered: List[str] = []
    candidates = list(placement.candidates())
    if from_track in candidates:
        index = candidates.index(from_track)
        ordered = candidates[index + 1:] + candidates[:index]
    else:
        ordered = candidates
    for candidate in ordered:
        if not track_accepts(_track_index(tracks, candidate), placement):
            continue
        if occupied(elements, candidate, start, duration):
            continue
        return candidate, f"{from_track} 这段时间被占了，顺延到 {candidate}"
    return from_track, f"{from_track} 这段时间被占了，可用轨道都满了（松手会重叠）"


def choose_track(placement: Placement,
                 tracks: Sequence[Dict[str, Any]],

                 elements: Iterable[Dict[str, Any]],
                 start: float,
                 duration: float,
                 requested_track: str = "") -> Tuple[str, str]:
    """决定最终落在哪条轨道，并给出一句中文原因。

    优先级：
    1. 用户明确指定的轨道（鼠标就悬在那条轨上）—— 只要 kind 合法就照办，
       **哪怕会重叠**：用户指着那里放，就是想放那里。
    2. 策略默认轨；被占用且 avoid_overlap 时依次试 fallback。
    3. 全都被占用：回到默认轨（并说明会重叠），绝不静默丢弃这次操作。
    """
    elements = list(elements)
    if requested_track:
        track = _track_index(tracks, requested_track)
        if track_accepts(track, placement):
            return requested_track, f"放到你指定的 {requested_track}"

    for candidate in placement.candidates():
        track = _track_index(tracks, candidate)
        if not track_accepts(track, placement):
            continue
        if placement.avoid_overlap and occupied(elements, candidate, start, duration):
            continue
        if candidate == placement.default_track:
            return candidate, f"{placement.label}默认放 {candidate}"
        return candidate, f"{placement.default_track} 这段时间被占了，{placement.label}顺延到 {candidate}"

    fallback = placement.default_track
    for candidate in placement.candidates():
        if track_accepts(_track_index(tracks, candidate), placement):
            fallback = candidate
            break
    return fallback, f"{placement.label}可用轨道都被占用了，仍然放在 {fallback}（会重叠）"
