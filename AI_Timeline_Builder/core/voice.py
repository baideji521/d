"""Voice Provider 架构：不绑定任何一家 TTS。

指令第十九、二十条要的是**接口**，不是某一家服务：

    VoiceRequest（文本 + 声音参数）
        ↓
    VoiceProvider.generate()          ← 谁实现都行
        ↓
    VoiceResult（音频 / 时长 / 逐词时间戳）
        ↓
    words_to_caption_group()
        ↓
    caption_group 元素 → Timeline JSON → Remotion

现在仓库里只有一个真实可用的实现：`SystemVoiceProvider`，
走 `core/tts.py`（Windows 系统自带语音合成，不联网、不需要 key）。
ElevenLabs / OpenAI / Azure / Google 只需要各写一个子类，
上层链路一行都不用改 —— 这就是这一层存在的全部理由。

**关于逐词时间戳的诚实说明（很重要）**：
系统 TTS 不返回每个词的起止时刻。所以 `SystemVoiceProvider` 给出的
`words` 是按**字符数按比例估算**的，`VoiceResult.timing_source` 会写成
`"estimated"`，而不是假装它是引擎给的真实值。哪天接了能返回真实时间戳的
provider，那边写 `"provider"`，报告里一眼能分出来。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core import timeline as tl

#: 声音参数白名单（指令第十九条）。provider 自己不支持的参数要如实说不支持，
#: 不许悄悄忽略 —— 用户以为调了情绪，其实什么都没发生是最坏的情况。
VOICE_PARAMS = (
    "provider",
    "voice_id",
    "language",
    "gender",
    "style",
    "emotion",
    "speed",
    "pitch",
    "stability",
    "similarity",
)

#: 支持的风格。英文短视频最常用的一组。
STYLES = (
    "natural",
    "energetic",
    "excited",
    "dramatic",
    "friendly",
    "calm",
    "storytelling",
)

#: 重点支持的语言（其它语言按 provider 能力）
PRIMARY_LANGUAGES = ("en-US", "en-GB")

GENDERS = ("female", "male", "neutral")

#: 估算逐词时间戳时，标点后额外分配的停顿权重（相对一个字符）
PUNCTUATION_WEIGHT = 2.0

_WORD_PATTERN = re.compile(r"[A-Za-z0-9'’\-]+|[\u4e00-\u9fff]|[^\sA-Za-z0-9\u4e00-\u9fff]+")


@dataclass
class VoiceRequest:
    """一次配音请求。"""

    text: str
    voice_id: str = ""
    language: str = "en-US"
    gender: str = "female"
    style: str = "natural"
    emotion: str = ""
    speed: float = 1.0
    pitch: float = 0.0
    stability: float = 0.5
    similarity: float = 0.75
    out_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "voice_id": self.voice_id,
            "language": self.language,
            "gender": self.gender,
            "style": self.style,
            "emotion": self.emotion,
            "speed": self.speed,
            "pitch": self.pitch,
            "stability": self.stability,
            "similarity": self.similarity,
        }


@dataclass
class VoiceResult:
    """一次配音结果。

    - ok=False 时 error 必须有内容，audio_path 允许为空；
    - timing_source 说明 words 的来源：provider（引擎给的）/ estimated（估算的）。
    """

    ok: bool
    audio_path: str = ""
    duration: float = 0.0
    words: List[Dict[str, Any]] = field(default_factory=list)
    timing_source: str = "estimated"
    provider: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "audio_path": self.audio_path,
            "duration": self.duration,
            "words": [dict(w) for w in self.words],
            "timing_source": self.timing_source,
            "provider": self.provider,
            "error": self.error,
        }


def split_words(text: str) -> List[str]:
    """分词：英文按空格 / 标点，中文按字。返回的词里不含空白。"""
    return [w for w in _WORD_PATTERN.findall(str(text or "")) if w.strip()]


def estimate_word_timestamps(
    text: str,
    duration: float,
    start: float = 0.0,
) -> List[Dict[str, Any]]:
    """按字符数比例估算逐词时间戳。

    这是**估算**，不是引擎给的真实值：长词占的时间多、标点后留一点停顿。
    调用方必须把 timing_source 标成 estimated，不许当成真实时间戳用在
    「口型对齐」这类要求精确的场合。

    duration <= 0 或没有词时返回空列表（不造数据）。
    """
    words = split_words(text)
    total = tl.as_seconds(duration)
    if not words or total <= 0:
        return []

    weights: List[float] = []
    for word in words:
        weight = float(len(word))
        if re.fullmatch(r"[^\sA-Za-z0-9\u4e00-\u9fff]+", word):
            weight = PUNCTUATION_WEIGHT
        weights.append(max(0.5, weight))
    weight_sum = sum(weights)

    result: List[Dict[str, Any]] = []
    cursor = tl.as_seconds(start)
    for index, word in enumerate(words):
        span = total * weights[index] / weight_sum
        end = cursor + span
        if index == len(words) - 1:
            end = tl.as_seconds(start) + total  # 末词严格对齐总时长
        result.append({"text": word, "start": round(cursor, 3), "end": round(end, 3)})
        cursor = end
    return result


def words_to_caption_group(
    words: List[Dict[str, Any]],
    element_id: str = "captiongroup_001",
    track: str = "T1",
    emphasis: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """逐词时间戳 → caption_group 元素。

    emphasis 里的词会被标 `emphasis: true`。注意 v1 schema 的 word 只允许
    text / start / end 三个键，所以强调信息落在 highlight 样式上，
    不往 word 里塞 schema 不认的字段。
    """
    clean = [
        {
            "text": str(w.get("text", "")),
            "start": round(tl.as_seconds(w.get("start")), 3),
            "end": round(tl.as_seconds(w.get("end")), 3),
        }
        for w in words or []
        if str(w.get("text", "")).strip()
    ]
    if not clean:
        return {}
    element = tl.make_caption_group(element_id, clean, track)
    wanted = {str(w).lower() for w in (emphasis or [])}
    if wanted:
        # 被强调的词用高亮色；具体渲染由 caption_style=highlight_current 负责
        element["highlight"] = {"color": "#FFE347", "backgroundColor": "", "scale": 1.18}
    return element


class VoiceProvider:
    """配音提供方的统一接口。

    子类必须实现 `generate()`；`get_voices` / `get_languages` / `get_styles`
    有默认实现，能力不同的 provider 各自覆盖。
    """

    #: provider 的稳定标识，写进 Timeline / 报告
    id = "base"
    label = "抽象基类"
    #: 这个 provider 能不能给出真实逐词时间戳
    supports_word_timestamps = False
    #: 支持的参数子集（VOICE_PARAMS 的子集）
    supported_params: tuple = ("voice_id", "language", "speed")

    def generate(self, request: VoiceRequest) -> VoiceResult:  # pragma: no cover - 抽象
        raise NotImplementedError

    def get_voices(self, language: str = "") -> List[Dict[str, str]]:
        return []

    def get_languages(self) -> List[str]:
        return list(PRIMARY_LANGUAGES)

    def get_styles(self) -> List[str]:
        return list(STYLES)

    def unsupported(self, request: VoiceRequest) -> List[str]:
        """这次请求里有哪些参数本 provider 其实做不到。

        用来在 GUI / 报告里明说「情绪参数被忽略了」，
        而不是让用户以为调了却没生效。
        """
        missing: List[str] = []
        defaults = VoiceRequest(text="")
        for name in VOICE_PARAMS:
            if name in ("provider",) or name in self.supported_params:
                continue
            value = getattr(request, name, None)
            if value in (None, ""):
                continue
            if value != getattr(defaults, name, None):
                missing.append(name)
        return missing

    def describe(self) -> Dict[str, Any]:
        """能力自述，供 AI_CAPABILITIES / VOICE_SPEC 生成器使用。"""
        return {
            "id": self.id,
            "label": self.label,
            "supports_word_timestamps": self.supports_word_timestamps,
            "supported_params": list(self.supported_params),
            "languages": self.get_languages(),
            "styles": self.get_styles(),
        }


class SystemVoiceProvider(VoiceProvider):
    """Windows 系统自带语音合成（core/tts.py）。

    优点：不联网、不要 key、不用装依赖。
    限制（如实写在这里，不藏）：
    - 没有逐词时间戳 → words 是估算的；
    - 没有 style / emotion / stability / similarity 这些概念，
      传了会出现在 `unsupported()` 里；
    - 只有 Windows 能用。
    """

    id = "system"
    label = "系统自带语音（Windows SAPI）"
    supports_word_timestamps = False
    supported_params = ("voice_id", "language", "speed")

    def __init__(self, root: str = "") -> None:
        self._root = root

    def available(self) -> bool:
        from core import tts

        return bool(tts.available())

    def get_voices(self, language: str = "") -> List[Dict[str, str]]:
        from core import tts

        voices = tts.list_voices()
        if not language:
            return voices
        prefix = language.split("-")[0].lower()
        return [v for v in voices if str(v.get("culture", "")).lower().startswith(prefix)]

    def get_languages(self) -> List[str]:
        cultures = {
            str(v.get("culture", "")) for v in self.get_voices() if v.get("culture")
        }
        return sorted(cultures) or list(PRIMARY_LANGUAGES)

    def get_styles(self) -> List[str]:
        # 系统 TTS 没有风格概念，如实只报 natural
        return ["natural"]

    def generate(self, request: VoiceRequest) -> VoiceResult:
        from core import tts

        text = str(request.text or "").strip()
        if not text:
            return VoiceResult(False, provider=self.id, error="文本是空的，没有可合成的内容")
        if not self.available():
            return VoiceResult(
                False, provider=self.id, error="当前环境没有可用的系统语音合成（只支持 Windows）"
            )
        target = request.out_path or tts.output_path(self._root or os.getcwd(), text)
        # speed 1.0 → rate 0；SAPI 的 rate 是 -10..10 的整数档
        rate = int(round((float(request.speed or 1.0) - 1.0) * 10))
        error = tts.synthesize(text, target, request.voice_id, rate=rate)
        if error:
            return VoiceResult(False, provider=self.id, error=error)
        duration = self._probe_duration(target)
        return VoiceResult(
            True,
            audio_path=target,
            duration=duration,
            words=estimate_word_timestamps(text, duration),
            timing_source="estimated",
            provider=self.id,
        )

    @staticmethod
    def _probe_duration(path: str) -> float:
        """用 ffprobe 量真实时长。量不到就返回 0，不猜。"""
        try:
            from render.ffmpeg import FFmpeg

            info = FFmpeg().probe(path)
        except Exception:  # pragma: no cover - 环境缺 ffmpeg 时
            return 0.0
        return tl.as_seconds((info or {}).get("duration"))


# ---------------------------------------------------------------- 注册表

_PROVIDERS: Dict[str, VoiceProvider] = {}


def register_provider(provider: VoiceProvider) -> None:
    """注册一个 provider。同 id 后注册覆盖前者。"""
    if isinstance(provider, VoiceProvider) and provider.id:
        _PROVIDERS[provider.id] = provider


def get_provider(provider_id: str = "") -> Optional[VoiceProvider]:
    """取 provider。不给 id 就返回默认（system）。"""
    if not provider_id:
        provider_id = SystemVoiceProvider.id
    return _PROVIDERS.get(provider_id)


def provider_ids() -> List[str]:
    return sorted(_PROVIDERS)


def catalog() -> List[Dict[str, Any]]:
    """所有 provider 的能力自述，给文档生成器用。"""
    return [_PROVIDERS[key].describe() for key in provider_ids()]


register_provider(SystemVoiceProvider())
