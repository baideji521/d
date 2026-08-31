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

    **能力必须如实声明**（指令第十条）。下面这组 `supports_*` 类属性就是
    能力表：`VoiceProfile.apply_to()` 只会下发 provider 声明支持的参数，
    做不到的会进 `ignored` 列表被写进报告。默认全 False 是故意的 ——
    新写一个 provider 忘了声明，表现是「参数被忽略并记账」，
    而不是「以为生效其实没生效」。
    """

    #: provider 的稳定标识，写进 Timeline / 报告
    id = "base"
    label = "抽象基类"
    #: 这个 provider 能不能给出真实逐词时间戳
    supports_word_timestamps = False
    supports_speed = False
    supports_pitch = False
    supports_style = False
    supports_emotion = False
    supports_energy = False
    supports_ssml = False
    #: 需不需要联网 / 凭据。GUI 用它决定要不要提示配置 key。
    requires_network = False
    requires_credentials = False
    #: 支持的参数子集（VOICE_PARAMS 的子集）
    supported_params: tuple = ("voice_id", "language", "speed")

    def capabilities(self) -> Dict[str, bool]:
        """能力表。VoiceProfile 与文档生成器只认这个字典。"""
        return {
            "supports_word_timestamps": bool(self.supports_word_timestamps),
            "supports_speed": bool(self.supports_speed),
            "supports_pitch": bool(self.supports_pitch),
            "supports_style": bool(self.supports_style),
            "supports_emotion": bool(self.supports_emotion),
            "supports_energy": bool(self.supports_energy),
            "supports_ssml": bool(self.supports_ssml),
        }

    def available(self) -> bool:
        """当前环境能不能真的用它。基类保守地返回 False。"""
        return False

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
            "kind": getattr(self, "kind", "local"),
            "available": bool(self.available()),
            "requires_network": bool(self.requires_network),
            "requires_credentials": bool(self.requires_credentials),
            "supports_word_timestamps": self.supports_word_timestamps,
            "supported_params": list(self.supported_params),
            "capabilities": self.capabilities(),
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
    kind = "local"
    supports_word_timestamps = False
    #: SAPI 只有 Rate。没有 style / emotion / pitch / energy 的概念，如实全写 False。
    supports_speed = True
    supports_pitch = False
    supports_style = False
    supports_emotion = False
    supports_energy = False
    supports_ssml = False
    requires_network = False
    requires_credentials = False
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


class EdgeVoiceProvider(VoiceProvider):
    """微软 Edge 神经网络语音（`edge-tts`）。免费、不需要 API Key、**要联网**。

    为什么加它：SAPI 本机只有一个英文女声（Zira Desktop），是十几年前的拼接式
    合成，念短视频解说明显机械。Edge 这条链路给的是神经网络音色
    （en-US 女声 8 个，Ava / Emma 带 Expressive 人格），语速 / 音高 / 音量都能调，
    听感与「真人口播」的差距小得多。

    **能力如实说明**（第七、十四条）：
    - 服务只回 `SentenceBoundary`（句级边界），不回 `WordBoundary`。
      所以 `supports_word_timestamps = False`，`timing_source = "sentence"`：
      句子起止是引擎给的真值，句内逐词仍是按字符比例摊开的估算。
      voice_compiler 会因此打上 FALLBACK_ALIGNMENT —— 这是对的，不要绕过。
    - 没有 style / emotion 参数（要 SSML 才有，这条链路不走 SSML），如实报 False。
    - 要联网。断网 / 被墙时 `generate()` 返回明确错误，**绝不静默退回 SAPI**：
      悄悄换音色比报错难查得多。要 fallback 由调用方显式做（见 `best_provider()`）。
    """

    id = "edge"
    label = "Edge 神经网络语音（在线，免费无 key）"
    kind = "cloud"
    supports_word_timestamps = False
    supports_speed = True
    supports_pitch = True
    supports_style = False
    supports_emotion = False
    supports_energy = True
    supports_ssml = False
    requires_network = True
    requires_credentials = False
    supported_params = ("voice_id", "language", "speed", "pitch", "stability")

    #: 默认英文女声。Ava 的人格标签是 Expressive / Friendly，最接近解说腔
    DEFAULT_VOICE = "en-US-AvaNeural"
    #: 句级边界是引擎给的真值，词级仍是摊开的 —— 用独立取值把这件事说清楚
    TIMING_SOURCE = "sentence"
    #: 音色列表要联网拉，进程内缓存一次
    _VOICE_CACHE: Optional[List[Dict[str, str]]] = None

    def __init__(self, root: str = "") -> None:
        self._root = root

    # ------------------------------------------------------------ 环境
    @staticmethod
    def _module():
        """懒加载 edge_tts。没装就返回 None，不抛异常。"""
        try:
            import edge_tts  # noqa: PLC0415
        except Exception:  # pragma: no cover - 没装 edge-tts 的环境
            return None
        return edge_tts

    def available(self) -> bool:
        """只看装没装，**不探网**：available() 会被 GUI 频繁调用，不能每次都联网。

        网络不通的表现是 generate() 明确失败，而不是这里假装不可用。
        """
        return self._module() is not None

    @staticmethod
    def _run_async(coro):
        """在没有事件循环的线程里跑协程；已有循环时新开一个，绝不抢占别人的。"""
        import asyncio  # noqa: PLC0415

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    # ------------------------------------------------------------ 音色
    def get_voices(self, language: str = "") -> List[Dict[str, str]]:
        module = self._module()
        if module is None:
            return []
        if EdgeVoiceProvider._VOICE_CACHE is None:
            try:
                raw = self._run_async(module.list_voices())
            except Exception:  # 拉不到（断网 / 超时）就按空表处理，由 generate 报错
                return []
            EdgeVoiceProvider._VOICE_CACHE = [
                {
                    "name": str(v.get("ShortName", "")),
                    "culture": str(v.get("Locale", "")),
                    "gender": str(v.get("Gender", "")).lower(),
                    "label": ", ".join((v.get("VoiceTag") or {}).get("VoicePersonalities") or []),
                }
                for v in raw
                if v.get("ShortName")
            ]
        voices = EdgeVoiceProvider._VOICE_CACHE or []
        if not language:
            return list(voices)
        prefix = language.split("-")[0].lower()
        return [v for v in voices if v["culture"].lower().startswith(prefix)]

    def get_languages(self) -> List[str]:
        """**不联网**：文档生成器会调 describe() → get_languages()，
        要是这里去拉音色表，离线机器生成的文档就和联网机器不一样（docs 会漂）。
        真要看某个语言下有哪些音色，显式调 `get_voices(language)`。
        """
        return list(PRIMARY_LANGUAGES)

    def get_styles(self) -> List[str]:
        # 这条链路不发 SSML，没有风格可选。不虚报。
        return ["natural"]

    # ------------------------------------------------------------ 参数映射
    @staticmethod
    def _rate(speed: float) -> str:
        """speed 1.0 → "+0%"。edge-tts 的 rate 是相对百分比。"""
        percent = int(round((float(speed or 1.0) - 1.0) * 100))
        return f"{percent:+d}%"

    @staticmethod
    def _pitch(semitones: float) -> str:
        """半音 → Hz。女声基频约 200Hz，一个半音≈12Hz；夹在 ±50Hz 免得变形。"""
        hertz = int(round(max(-4.0, min(4.0, float(semitones or 0.0))) * 12))
        return f"{max(-50, min(50, hertz)):+d}Hz"

    @staticmethod
    def _volume(stability: float) -> str:
        """energy 经 VoiceProfile 映射成 stability = 1 - energy，这里还原成音量。

        energy 0.5（默认）→ +0%；越有劲越响，夹在 ±30% 免得削波。
        """
        energy = 1.0 - max(0.0, min(1.0, float(stability if stability is not None else 0.5)))
        percent = int(round((energy - 0.5) * 60))
        return f"{max(-30, min(30, percent)):+d}%"

    # ------------------------------------------------------------ 合成
    def generate(self, request: VoiceRequest) -> VoiceResult:
        import os as _os  # noqa: PLC0415
        import tempfile  # noqa: PLC0415

        module = self._module()
        text = str(request.text or "").strip()
        if not text:
            return VoiceResult(False, provider=self.id, error="文本是空的，没有可合成的内容")
        if module is None:
            return VoiceResult(
                False,
                provider=self.id,
                error="没装 edge-tts（python -m pip install edge-tts），这条链路用不了",
            )
        target = request.out_path
        if not target:
            from core import tts  # noqa: PLC0415

            target = tts.output_path(self._root or _os.getcwd(), text)
        voice_id = request.voice_id or self.DEFAULT_VOICE

        raw = _os.path.join(
            tempfile.gettempdir(), f"edge_tts_{_os.getpid()}_{abs(hash(text)) % 10**8}.mp3"
        )
        sentences: List[Dict[str, Any]] = []

        async def pull() -> None:
            comm = module.Communicate(
                text,
                voice_id,
                rate=self._rate(request.speed),
                pitch=self._pitch(request.pitch),
                volume=self._volume(request.stability),
            )
            with open(raw, "wb") as handle:
                async for chunk in comm.stream():
                    kind = chunk.get("type")
                    if kind == "audio":
                        handle.write(chunk["data"])
                    elif kind in ("WordBoundary", "SentenceBoundary"):
                        sentences.append(
                            {
                                "text": str(chunk.get("text", "")),
                                "start": float(chunk.get("offset", 0)) / 1e7,
                                "end": (float(chunk.get("offset", 0)) + float(chunk.get("duration", 0))) / 1e7,
                            }
                        )

        try:
            self._run_async(pull())
        except Exception as exc:  # 断网 / 音色名不对 / 服务拒绝
            return VoiceResult(
                False, provider=self.id, error=f"Edge 语音合成失败（要联网）：{type(exc).__name__}: {exc}"
            )
        if not _os.path.isfile(raw) or _os.path.getsize(raw) < 512:
            return VoiceResult(False, provider=self.id, error="Edge 返回的音频是空的")

        error = self._to_wav(raw, target)
        try:
            _os.remove(raw)
        except OSError:
            pass
        if error:
            return VoiceResult(False, provider=self.id, error=error)

        duration = SystemVoiceProvider._probe_duration(target)
        return VoiceResult(
            True,
            audio_path=target,
            duration=duration,
            words=self._words(text, sentences, duration),
            timing_source=self.TIMING_SOURCE if sentences else "estimated",
            provider=self.id,
        )

    @staticmethod
    def _to_wav(source: str, target: str) -> str:
        """MP3 → WAV。整条链路（素材登记 / 预览混音 / Remotion）都按 WAV 走。"""
        import os as _os  # noqa: PLC0415

        from render.ffmpeg import FFmpeg  # noqa: PLC0415

        engine = FFmpeg()
        if not engine.ffmpeg_path:
            return "找不到 ffmpeg，Edge 给的 MP3 转不成 WAV"
        _os.makedirs(_os.path.dirname(_os.path.abspath(target)) or ".", exist_ok=True)
        done = engine.run_command(
            [engine.ffmpeg_path, "-y", "-v", "error", "-i", source,
             "-ac", "1", "-ar", "24000", target],
            timeout=120,
        )
        if done is None or done.returncode != 0 or not _os.path.isfile(target):
            return "Edge 音频转 WAV 失败（ffmpeg 报错）"
        return ""

    @staticmethod
    def _words(
        text: str, sentences: List[Dict[str, Any]], duration: float
    ) -> List[Dict[str, Any]]:
        """句级真值 + 句内估算。

        引擎给的是句子起止，所以**句边界是真的**；句内每个词仍按字符比例摊开。
        这比整段一起摊开准得多（长句不会把后面的词越推越偏），
        但它仍然不是逐词真值 —— timing_source 写 "sentence" 就是为了说清这一点。

        引擎给的句子区间会**互相压线**（下一句的 offset 早于上一句的 offset+duration），
        句尾那一段也可能超出音频实际时长（最多几十毫秒）。所以这里做两件收口：
        句子起点不早于上一句终点、所有时间钳进 [0, duration]。
        不做的话词表就不是单调的，caption_group 的逐词高亮会来回跳。
        """
        if not sentences:
            return estimate_word_timestamps(text, duration)
        total = tl.as_seconds(duration)
        words: List[Dict[str, Any]] = []
        cursor = 0.0
        for item in sentences:
            start = max(cursor, float(item["start"]))
            end = float(item["end"])
            if total > 0:
                start = min(start, total)
                end = min(end, total)
            span = max(0.0, end - start)
            if span <= 0:
                continue
            words.extend(estimate_word_timestamps(item["text"], span, start))
            cursor = end
        return words or estimate_word_timestamps(text, duration)


# ---------------------------------------------------------------- 云端适配层


class CloudVoiceProvider(VoiceProvider):
    """云端 TTS 适配器基类。

    **它本身不联网、也不绑定任何一家**。存在的意义是把「云端 provider 需要什么」
    固定下来，这样接 ElevenLabs / Azure / OpenAI 时只写两个方法：

        class ElevenLabsProvider(CloudVoiceProvider):
            id = "elevenlabs"
            supports_emotion = True
            supports_word_timestamps = True
            def _synthesize(self, request, out_path): ...   # 真正的 HTTP 调用
            def get_voices(self, language=""): ...

    上层（VoiceProfile / VoiceDirector / VoicePlanCompiler / EditingPlanner）
    一行都不用改。

    没有凭据时 `available()` 是 False，`generate()` 返回明确的错误 ——
    **不静默降级到本机语音**。悄悄换了音色比报错难查得多。
    """

    kind = "cloud"
    requires_network = True
    requires_credentials = True
    #: 凭据从哪个环境变量读。子类改成自己的。
    credential_env = ""

    def __init__(self, api_key: str = "", root: str = "") -> None:
        self._api_key = api_key or (os.environ.get(self.credential_env, "") if self.credential_env else "")
        self._root = root

    def available(self) -> bool:
        return bool(self._api_key)

    def missing_reason(self) -> str:
        if not self._api_key:
            env = self.credential_env or "（未声明环境变量名）"
            return f"{self.label} 缺少凭据：请设置环境变量 {env}"
        return ""

    def _synthesize(self, request: VoiceRequest, out_path: str) -> str:
        """真正的合成。成功返回空串，失败返回错误说明。子类必须实现。"""
        raise NotImplementedError

    def _word_timestamps(self, request: VoiceRequest, out_path: str) -> List[Dict[str, Any]]:
        """引擎返回的真实逐词时间戳。做不到就返回空列表（上层会退回估算）。"""
        return []

    def generate(self, request: VoiceRequest) -> VoiceResult:
        text = str(request.text or "").strip()
        if not text:
            return VoiceResult(False, provider=self.id, error="文本是空的，没有可合成的内容")
        reason = self.missing_reason()
        if reason:
            return VoiceResult(False, provider=self.id, error=reason)
        target = request.out_path
        if not target:
            return VoiceResult(False, provider=self.id, error="没有指定输出路径")
        error = self._synthesize(request, target)
        if error:
            return VoiceResult(False, provider=self.id, error=error)
        duration = SystemVoiceProvider._probe_duration(target)
        words = self._word_timestamps(request, target)
        return VoiceResult(
            True,
            audio_path=target,
            duration=duration,
            words=words or estimate_word_timestamps(text, duration),
            timing_source="provider" if words else "estimated",
            provider=self.id,
        )


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


#: 「首选 → 兜底」的顺序。Edge 是神经网络音色，听感明显更接近真人；
#: SAPI 只有一个十几年前的英文女声，作为**离线兜底**保留，不当最终方案。
PREFERRED_ORDER = ("edge", "system")


def best_provider(order: tuple = PREFERRED_ORDER) -> Optional[VoiceProvider]:
    """按首选顺序挑第一个**当前环境真能用**的 provider。

    - 不改 `get_provider()` 的默认值：老调用方拿到的仍然是 system，行为不变；
    - 想要「有网用 Edge、没网退 SAPI」的调用方显式调本函数。
      退回是**显式**的：谁在用哪一家，报告里 `result.provider` 一眼能看到。
    """
    for provider_id in order:
        provider = _PROVIDERS.get(provider_id)
        if provider is not None and provider.available():
            return provider
    return _PROVIDERS.get(SystemVoiceProvider.id)


register_provider(SystemVoiceProvider())
register_provider(EdgeVoiceProvider())
