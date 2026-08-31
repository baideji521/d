"""VoiceDirector：英文文案 → VoicePlan。

# 它不是 TTS

VoiceDirector 一行 TTS 代码都没有。它只做「导演」该做的事：

    英文文案
        ↓ 断句
        ↓ 判情绪
        ↓ 找强调词
        ↓ 定语速
        ↓ 排停顿
    VoicePlan

VoicePlan 再交给 provider 合成。这样换 provider 不影响导演逻辑，
换导演逻辑不影响合成链路。

# VoicePlan 不进 Timeline JSON（指令第十二条）

分层是硬约束：

    VoicePlan → TTS → Voice Asset → word timestamps → Timeline Audio + Caption

Timeline 里只留 `asset` / `start` / `duration` / 字幕时间。
`emotion` / `intensity` / `stability` 这类 provider 私有参数**绝不写进 Timeline** ——
它们是「怎么生成这段声音」的过程信息，不是「这段声音在片子里怎么放」。

# 规则是启发式，不是理解

这里没有语言模型。判情绪靠的是标点、全大写、以及一张很短的转折词表。
它对短视频口播文案够用，对文学文本会判得很粗 —— 这一点在
`docs/VOICE_SPEC.md` 里如实写着，不假装是语义分析。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core import voice_profile as vp

#: 句子切分：在 . ! ? 之后切，保留标点。
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

#: 长句再切：逗号 / 分号 / 破折号后面切，避免一段读太久。
_CLAUSE_SPLIT = re.compile(r"(?<=[,;:—])\s+")

#: 一段最多多少个词。超了就在从句处再切。
MAX_WORDS_PER_SEGMENT = 12

#: 全大写词（长度 ≥ 2）算强调。英文口播里 "THIS" / "NEVER" 就是这么写的。
_ALLCAPS = re.compile(r"\b[A-Z][A-Z0-9']{1,}\b")

#: 转折 / 揭晓词：出现在段首时给一个停顿并抬情绪。
TURN_WORDS = (
    "but", "however", "suddenly", "then", "and", "so", "because",
    "until", "except", "actually", "instead",
)

#: 情绪关键词表。key 是情绪，value 是触发词（全小写匹配）。
EMOTION_KEYWORDS: Dict[str, tuple] = {
    "shock": ("wrong", "never", "worst", "disaster", "fail", "broke", "stop", "warning"),
    "excited": ("best", "amazing", "incredible", "finally", "huge", "insane", "wow"),
    "curious": ("why", "how", "what if", "guess", "wonder"),
    "serious": ("must", "important", "careful", "remember", "always"),
}

#: 情绪 → 语速修正（相对档位语速的倍率）
EMOTION_SPEED: Dict[str, float] = {
    "excited": 1.05,
    "shock": 1.02,
    "curious": 0.98,
    "serious": 0.95,
    "neutral": 1.0,
}

#: 强调词导致的额外强度加成
EMPHASIS_BOOST = 0.25

#: 段前停顿的基准（秒）。转折词与情绪都会放大它。
BASE_PAUSE = 0.08

#: 强度高于这个值算「高潮」，会产出 voice_peak 标记
PEAK_INTENSITY = 0.75

#: 停顿长于这个值算「有意义的停顿」，会产出 voice_pause 标记
PEAK_PAUSE = 0.18


@dataclass
class VoiceSegment:
    """一段配音。时间戳在这一层**还不存在** —— 那是合成之后的事。"""

    text: str
    emotion: str = "neutral"
    intensity: float = 0.5
    speed: float = 1.0
    pause_before: float = 0.0
    emphasis: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "text": self.text,
            "emotion": self.emotion,
            "intensity": round(self.intensity, 3),
            "speed": round(self.speed, 3),
        }
        if self.pause_before > 0:
            result["pause_before"] = round(self.pause_before, 3)
        if self.emphasis:
            result["emphasis"] = list(self.emphasis)
        return result


@dataclass
class VoicePlan:
    """一次配音的完整计划。"""

    text: str
    profile: str = vp.DEFAULT_PROFILE_ID
    language: str = "en-US"
    segments: List[VoiceSegment] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "profile": self.profile,
            "language": self.language,
            "segments": [segment.to_dict() for segment in self.segments],
        }

    def spoken_text(self) -> str:
        """真正要交给 TTS 的文本（各段按顺序拼回去）。"""
        return " ".join(segment.text for segment in self.segments).strip()

    def emphasis_words(self) -> List[str]:
        words: List[str] = []
        for segment in self.segments:
            for word in segment.emphasis:
                if word not in words:
                    words.append(word)
        return words


def _split_segments(text: str) -> List[str]:
    """先按句子切，太长的再按从句切。"""
    raw = [part.strip() for part in _SENTENCE_SPLIT.split(str(text or "").strip()) if part.strip()]
    result: List[str] = []
    for sentence in raw:
        if len(sentence.split()) <= MAX_WORDS_PER_SEGMENT:
            result.append(sentence)
            continue
        clauses = [c.strip() for c in _CLAUSE_SPLIT.split(sentence) if c.strip()]
        if len(clauses) <= 1:
            result.append(sentence)
            continue
        # 合并太短的从句，避免切出一堆两三个词的碎片
        buffer = ""
        for clause in clauses:
            candidate = f"{buffer} {clause}".strip()
            if len(candidate.split()) <= MAX_WORDS_PER_SEGMENT or not buffer:
                buffer = candidate
            else:
                result.append(buffer)
                buffer = clause
        if buffer:
            result.append(buffer)
    return result


def _detect_emotion(segment_text: str) -> str:
    lowered = segment_text.lower()
    for emotion, keywords in EMOTION_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return emotion
    if segment_text.rstrip().endswith("?"):
        return "curious"
    if segment_text.rstrip().endswith("!"):
        return "excited"
    return "neutral"


def _detect_emphasis(segment_text: str) -> List[str]:
    """全大写词算强调。首字母大写的普通句首词不算。"""
    found: List[str] = []
    for match in _ALLCAPS.findall(segment_text):
        if match.upper() == match and match not in found:
            found.append(match)
    return found


def _intensity(segment_text: str, emotion: str, emphasis: List[str]) -> float:
    base = {"excited": 0.75, "shock": 0.85, "curious": 0.5, "serious": 0.6}.get(emotion, 0.45)
    base += min(0.3, EMPHASIS_BOOST * len(emphasis))
    base += 0.05 * min(3, segment_text.count("!"))
    return max(0.0, min(1.0, base))


def _pause_before(index: int, segment_text: str, emotion: str,
                  profile: vp.VoiceProfile) -> float:
    if index == 0:
        return 0.0
    pause = BASE_PAUSE * max(0.1, profile.pause_scale)
    first_word = (segment_text.split() or [""])[0].strip(",.;:!?").lower()
    if first_word in TURN_WORDS:
        pause += 0.10 * max(0.1, profile.pause_scale)
    if emotion in ("shock", "excited"):
        pause += 0.06
    pause += profile.sentence_pause
    return round(pause, 3)


def direct(text: str, profile_id: str = "", language: str = "") -> VoicePlan:
    """英文文案 → VoicePlan。

    profile_id 不认识时**报错而不是兜底**：档位决定语速与停顿，
    悄悄换成默认档会让产出与预期差很远。
    """
    profile = vp.get_profile(profile_id)
    if profile is None:
        raise ValueError(f"不认识的配音档位：{profile_id}，可用：{', '.join(vp.profile_ids())}")

    plan = VoicePlan(
        text=str(text or "").strip(),
        profile=profile.id,
        language=language or profile.language,
    )
    for index, chunk in enumerate(_split_segments(plan.text)):
        emotion = _detect_emotion(chunk)
        emphasis = _detect_emphasis(chunk)
        intensity = _intensity(chunk, emotion, emphasis)
        speed = profile.speed * EMOTION_SPEED.get(emotion, 1.0)
        plan.segments.append(
            VoiceSegment(
                text=chunk,
                emotion=emotion,
                intensity=intensity,
                speed=round(speed, 3),
                pause_before=_pause_before(index, chunk, emotion, profile),
                emphasis=emphasis,
            )
        )
    return plan


def plan_hints(plan: VoicePlan) -> List[Dict[str, Any]]:
    """计划层面的「哪里是高潮 / 哪里有停顿」。

    注意：这里给的是**段序号**，不是时间 —— 时间要等合成出音频、
    拿到逐词时间戳才知道。把两件事分开是为了不让导演层假装知道时长。
    """
    hints: List[Dict[str, Any]] = []
    for index, segment in enumerate(plan.segments):
        if segment.intensity >= PEAK_INTENSITY or segment.emphasis:
            hints.append(
                {
                    "segment": index,
                    "kind": "peak",
                    "emotion": segment.emotion,
                    "intensity": round(segment.intensity, 3),
                    "label": segment.emphasis[0] if segment.emphasis else segment.emotion,
                }
            )
        if segment.pause_before >= PEAK_PAUSE:
            hints.append(
                {
                    "segment": index,
                    "kind": "pause",
                    "seconds": round(segment.pause_before, 3),
                    "label": "停顿",
                }
            )
    return hints
