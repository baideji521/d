"""VoicePlanCompiler：VoicePlan + 合成结果 → Timeline 元素 + 标记。

# 链路里的位置（指令第十五条）

    VoicePlan（导演层，不进 Timeline）
        ↓ provider.generate()
    Voice Asset（WAV）+ word timestamps
        ↓ **本模块**
    audio 元素 → A2      逐词字幕 caption_group → T1      voice_peak / voice_pause 标记

A2 与 T1 **共享同一个时间基准**：都以配音在时间线上的落点 `start` 为原点，
所以字幕永远贴着声音，不会因为两边各算一次而错位。

# 只写 Timeline 该有的东西（指令第十二条）

产出的元素里只有 `asset` / `start` / `duration` / `volume` / 字幕时间。
`emotion` / `intensity` / `stability` 这些 provider 私有参数一个都不写进去 ——
它们属于「怎么生成」，不属于「怎么播放」。需要留档的话走
`core/provenance.py` 的决策日志，不污染渲染数据。

# 逐词时间戳的两条来源，报告里必须分得清（指令第十四条）

- provider 给的真实时间戳 → `timing_source = "provider"`
- 本地按字符数比例估算    → `timing_source = "estimated"`，并在报告里标
  `FALLBACK_ALIGNMENT`

估算值够做「逐词高亮字幕」（差几十毫秒看不出来），**不够做口型对齐**。
这句话在 `docs/VOICE_SPEC.md` 里也写着。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core import timeline as tl
from core import voice as voice_mod
from core import voice_director as vd

#: 配音固定落在 A2（人声轨），逐词字幕落在 T1。轨道是产品约定，不是参数。
VOICE_TRACK = "A2"
CAPTION_TRACK = "T1"

#: 逐词时间戳来自估算时，报告里打这个标记
FALLBACK_ALIGNMENT = "FALLBACK_ALIGNMENT"


@dataclass
class CompiledVoice:
    """编译结果。elements 可以直接塞进时间线，markers 走 core/markers.py。"""

    elements: List[Dict[str, Any]] = field(default_factory=list)
    markers: List[Dict[str, Any]] = field(default_factory=list)
    words: List[Dict[str, Any]] = field(default_factory=list)
    segment_spans: List[Dict[str, Any]] = field(default_factory=list)
    timing_source: str = "estimated"
    flags: List[str] = field(default_factory=list)
    duration: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "elements": [dict(e) for e in self.elements],
            "markers": [dict(m) for m in self.markers],
            "words": [dict(w) for w in self.words],
            "segment_spans": [dict(s) for s in self.segment_spans],
            "timing_source": self.timing_source,
            "flags": list(self.flags),
            "duration": self.duration,
        }


def _shift_words(words: List[Dict[str, Any]], offset: float) -> List[Dict[str, Any]]:
    """把「相对音频开头」的时间戳搬到「时间线绝对时间」。"""
    shifted: List[Dict[str, Any]] = []
    for word in words or []:
        text = str(word.get("text", "")).strip()
        if not text:
            continue
        shifted.append(
            {
                "text": text,
                "start": round(tl.as_seconds(word.get("start")) + offset, 3),
                "end": round(tl.as_seconds(word.get("end")) + offset, 3),
            }
        )
    return shifted


def _segment_spans(
    plan: vd.VoicePlan, words: List[Dict[str, Any]], start: float, duration: float
) -> Tuple[List[Dict[str, Any]], bool]:
    """算出每一段在时间线上的起止。

    首选按**词数**对齐：逐段数它有几个词，在全局词表里顺序取走。
    provider 的分词规则可能和 `voice.split_words()` 不一样，导致总数对不上；
    这时退回按段字符数比例分配，并把 `approximate` 置为 True，
    让调用方在报告里如实标注，而不是拿一份对不齐的时间戳当真值。
    """
    spans: List[Dict[str, Any]] = []
    counts = [len(voice_mod.split_words(segment.text)) for segment in plan.segments]
    total_words = sum(counts)

    if words and total_words == len(words):
        cursor = 0
        for index, count in enumerate(counts):
            if count <= 0:
                continue
            chunk = words[cursor:cursor + count]
            cursor += count
            spans.append(
                {
                    "segment": index,
                    "start": chunk[0]["start"],
                    "end": chunk[-1]["end"],
                    "text": plan.segments[index].text,
                }
            )
        return spans, False

    # 兜底：按字符数比例切。字符数比词数稳（不受分词规则影响）。
    lengths = [max(1, len(segment.text)) for segment in plan.segments]
    length_sum = sum(lengths) or 1
    cursor = start
    for index, length in enumerate(lengths):
        span = duration * length / length_sum
        spans.append(
            {
                "segment": index,
                "start": round(cursor, 3),
                "end": round(cursor + span, 3),
                "text": plan.segments[index].text,
            }
        )
        cursor += span
    return spans, True


def compile_plan(
    plan: vd.VoicePlan,
    result: voice_mod.VoiceResult,
    asset_id: str,
    start: float = 0.0,
    volume: float = 1.0,
    element_prefix: str = "voice",
    with_captions: bool = True,
) -> CompiledVoice:
    """把一次配音编译成时间线内容。

    result 必须是**成功**的合成结果；失败的结果不该走到这里
    （调用方应当先看 `result.ok` 并把错误报出去）。
    """
    if not result.ok:
        raise ValueError(f"配音没成功，不能编译：{result.error}")
    if result.duration <= 0:
        raise ValueError("配音时长是 0，无法编译时间线元素（ffprobe 量不到时长）")

    compiled = CompiledVoice(timing_source=result.timing_source, duration=result.duration)
    if result.timing_source != "provider":
        compiled.flags.append(FALLBACK_ALIGNMENT)

    audio_element = tl.make_audio(
        f"{element_prefix}_audio_001",
        asset_id,
        VOICE_TRACK,
        start=start,
        duration=result.duration,
        volume=volume,
    )
    compiled.elements.append(audio_element)

    words = _shift_words(result.words, start)
    compiled.words = words

    spans, approximate = _segment_spans(plan, words, start, result.duration)
    compiled.segment_spans = spans
    if approximate:
        compiled.flags.append("SEGMENT_SPAN_APPROXIMATE")

    if with_captions and words:
        caption_group = voice_mod.words_to_caption_group(
            words,
            element_id=f"{element_prefix}_captiongroup_001",
            track=CAPTION_TRACK,
            emphasis=plan.emphasis_words(),
        )
        if caption_group:
            compiled.elements.append(caption_group)

    # --- 标记：把导演层的「第几段是高潮」翻译成真实时刻
    for hint in vd.plan_hints(plan):
        index = int(hint.get("segment", -1))
        span = next((s for s in spans if s["segment"] == index), None)
        if span is None:
            continue
        if hint["kind"] == "peak":
            compiled.markers.append(
                {
                    "time": span["start"],
                    "type": "voice_peak",
                    "label": str(hint.get("label") or "重音"),
                }
            )
        else:
            compiled.markers.append(
                {
                    "time": span["start"],
                    "type": "voice_pause",
                    "label": f"停顿 {hint.get('seconds')}s",
                }
            )
    compiled.markers.sort(key=lambda m: m["time"])
    return compiled


def synthesize_and_compile(
    text: str,
    provider: voice_mod.VoiceProvider,
    profile_id: str = "",
    asset_id: str = "voice_001",
    start: float = 0.0,
    out_path: str = "",
    volume: float = 1.0,
) -> Tuple[vd.VoicePlan, voice_mod.VoiceResult, Optional[CompiledVoice], Dict[str, Any]]:
    """一条命令走完 文案 → 计划 → 合成 → 时间线内容。

    返回 `(plan, result, compiled, report)`。合成失败时 compiled 是 None，
    report 里写明原因 —— **不造一段假音频糊过去**。
    """
    from core import voice_profile as vp

    profile = vp.get_profile(profile_id)
    if profile is None:
        raise ValueError(f"不认识的配音档位：{profile_id}")

    plan = vd.direct(text, profile.id)
    request, applied, ignored = profile.apply_to(provider, plan.spoken_text(), out_path)
    request.voice_id = request.voice_id or vp.pick_voice_id(provider, profile)

    result = provider.generate(request)
    report: Dict[str, Any] = {
        "provider": provider.id,
        "provider_label": provider.label,
        "profile": profile.id,
        "language": request.language,
        "gender": request.gender,
        "voice_id": request.voice_id,
        "applied_profile_params": applied,
        "ignored_profile_params": ignored,
        "capabilities": provider.capabilities(),
        "ok": result.ok,
        "error": result.error,
        "duration": result.duration,
        "timing_source": result.timing_source,
        "segments": len(plan.segments),
        "words": len(result.words),
    }
    if not result.ok:
        return plan, result, None, report

    compiled = compile_plan(
        plan, result, asset_id, start=start, volume=volume,
    )
    report["flags"] = list(compiled.flags)
    report["markers"] = len(compiled.markers)
    report["elements"] = [element["type"] for element in compiled.elements]
    return plan, result, compiled, report
