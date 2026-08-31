"""VoiceProfile：英文女声优先的配音档位表。

# 这一层解决什么问题

`VoiceRequest` 是「一次请求的参数」，太底层：调用方得自己知道
「激情解说该用多快的语速、多大的起伏」。VoiceProfile 把这些经验固化成档位：

    female_energetic / female_excited / female_storytelling / female_funny /
    female_dramatic / female_casual / female_suspense

档位只描述**想要什么效果**，不描述某一家 provider 的私有参数名。
真正能不能做到，由 provider 的能力表决定 —— 见 `apply_to()`。

# 不许伪装（指令第十条）

不同 TTS 支持的能力差别很大：Windows 系统语音只有语速，没有情绪、没有音高、
没有风格。这种情况下**不能假装支持**：`apply_to()` 会返回
`(request, applied, ignored)`，`ignored` 里写清楚哪些档位参数这次没生效。
GUI 与报告都拿这个列表说话，用户不会以为「调了情绪」结果什么都没发生。

# 为什么不写死某一家

指令第八条：接口继续保持 Provider 化。所以本模块**不 import 任何具体 provider**，
只依赖 `VoiceProvider.capabilities()` 这个抽象。新增云端 provider 时，
它自己声明能力，这里一行都不用改。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.voice import VoiceProvider, VoiceRequest

#: 档位可以表达的能力维度。key 就是 provider 能力表里的键名。
CAPABILITY_KEYS = (
    "supports_speed",
    "supports_pitch",
    "supports_style",
    "supports_emotion",
    "supports_energy",
    "supports_ssml",
    "supports_word_timestamps",
)


@dataclass
class VoiceProfile:
    """一个配音档位。

    字段对应指令第九条要求的那一组；`provider` 留空表示「不限定，用默认」。

    - speed：1.0 = 正常
    - pitch：半音偏移，0 = 不变
    - energy：0..1 的主观强度，映射到各 provider 各自的参数
    - pause_scale：句间停顿倍率，1.0 = provider 默认
    - sentence_pause：句末额外停顿（秒），悬念 / 戏剧类档位靠它拉张力
    """

    id: str
    label: str
    language: str = "en-US"
    gender: str = "female"
    style: str = "natural"
    emotion: str = ""
    speed: float = 1.0
    pitch: float = 0.0
    energy: float = 0.5
    pause_scale: float = 1.0
    sentence_pause: float = 0.0
    voice_id: str = ""
    provider: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "language": self.language,
            "gender": self.gender,
            "style": self.style,
            "emotion": self.emotion,
            "speed": self.speed,
            "pitch": self.pitch,
            "energy": self.energy,
            "pause_scale": self.pause_scale,
            "sentence_pause": self.sentence_pause,
            "voice_id": self.voice_id,
            "provider": self.provider,
            "notes": self.notes,
        }

    def apply_to(
        self, provider: VoiceProvider, text: str, out_path: str = ""
    ) -> Tuple[VoiceRequest, List[str], List[str]]:
        """把档位翻译成一次具体请求。

        返回 `(request, applied, ignored)`：

        - applied：这次真的会生效的档位维度
        - ignored：provider 做不到、**本次被忽略**的维度

        `ignored` 不为空不是错误 —— 系统语音只能调语速是客观事实。
        重要的是把它说出来，而不是让 request 里带着一个没人读的 emotion。
        """
        caps = provider.capabilities()
        applied: List[str] = []
        ignored: List[str] = []

        request = VoiceRequest(
            text=text,
            voice_id=self.voice_id,
            language=self.language,
            gender=self.gender,
            out_path=out_path,
        )

        def take(dimension: str, capability: str, assign) -> None:
            if caps.get(capability):
                assign()
                applied.append(dimension)
            else:
                ignored.append(dimension)

        if self.speed != 1.0:
            take("speed", "supports_speed", lambda: setattr(request, "speed", self.speed))
        if self.pitch != 0.0:
            take("pitch", "supports_pitch", lambda: setattr(request, "pitch", self.pitch))
        if self.style and self.style != "natural":
            take("style", "supports_style", lambda: setattr(request, "style", self.style))
        if self.emotion:
            take("emotion", "supports_emotion", lambda: setattr(request, "emotion", self.emotion))
        if self.energy != 0.5:
            # energy 没有统一的字段名，映射到 stability（越有劲越不稳）
            take(
                "energy",
                "supports_energy",
                lambda: setattr(request, "stability", max(0.0, min(1.0, 1.0 - self.energy))),
            )
        # 停顿由 VoiceDirector 在文本层面实现（插停顿标记 / 拆段），
        # 不依赖 provider 能力，所以永远算 applied。
        if self.pause_scale != 1.0 or self.sentence_pause:
            applied.append("pause")

        return request, applied, ignored


#: 英文女声档位表（指令第九条）。数值是短视频解说的常用区间，
#: 不是「官方推荐值」—— 哪家 provider 都没给过这种表。
PROFILES: List[VoiceProfile] = [
    VoiceProfile(
        id="female_energetic",
        label="英文女声 · 有劲（通用解说）",
        style="energetic",
        emotion="excited",
        speed=1.08,
        pitch=1.0,
        energy=0.75,
        pause_scale=0.9,
        notes="默认档。语速略快、停顿略短，适合大部分短视频口播。",
    ),
    VoiceProfile(
        id="female_excited",
        label="英文女声 · 激动（爆点 / reveal）",
        style="excited",
        emotion="excited",
        speed=1.15,
        pitch=2.0,
        energy=0.9,
        pause_scale=0.8,
        notes="用在揭晓和转折上；整段都用会很吵。",
    ),
    VoiceProfile(
        id="female_storytelling",
        label="英文女声 · 讲故事",
        style="storytelling",
        emotion="warm",
        speed=0.98,
        pitch=0.0,
        energy=0.5,
        pause_scale=1.15,
        sentence_pause=0.12,
        notes="句间停顿更长，适合叙事铺垫。",
    ),
    VoiceProfile(
        id="female_funny",
        label="英文女声 · 搞笑",
        style="friendly",
        emotion="playful",
        speed=1.12,
        pitch=2.5,
        energy=0.8,
        pause_scale=0.85,
        sentence_pause=0.08,
        notes="音高偏高、节奏跳；配 pop 类音效效果最好。",
    ),
    VoiceProfile(
        id="female_dramatic",
        label="英文女声 · 戏剧",
        style="dramatic",
        emotion="serious",
        speed=0.92,
        pitch=-1.0,
        energy=0.65,
        pause_scale=1.25,
        sentence_pause=0.2,
        notes="慢、沉、停顿长；适合冲突和结论。",
    ),
    VoiceProfile(
        id="female_casual",
        label="英文女声 · 随意（vlog）",
        style="friendly",
        emotion="",
        speed=1.0,
        pitch=0.0,
        energy=0.45,
        pause_scale=1.0,
        notes="最接近 provider 原始音色，改动最少。",
    ),
    VoiceProfile(
        id="female_suspense",
        label="英文女声 · 悬念",
        style="calm",
        emotion="mysterious",
        speed=0.9,
        pitch=-2.0,
        energy=0.4,
        pause_scale=1.35,
        sentence_pause=0.28,
        notes="停顿最长；配 riser 音效做 buildup。",
    ),
]

DEFAULT_PROFILE_ID = "female_energetic"

_BY_ID: Dict[str, VoiceProfile] = {profile.id: profile for profile in PROFILES}


def profile_ids() -> List[str]:
    return [profile.id for profile in PROFILES]


def get_profile(profile_id: str = "") -> Optional[VoiceProfile]:
    """按 id 取档位；不给 id 返回默认档；不认识的 id 返回 None（不偷偷兜底）。"""
    if not profile_id:
        return _BY_ID.get(DEFAULT_PROFILE_ID)
    return _BY_ID.get(profile_id)


def catalog() -> List[Dict[str, Any]]:
    """档位表，给 AI_CAPABILITIES / VOICE_SPEC 生成器用。"""
    return [profile.to_dict() for profile in PROFILES]


def pick_voice_id(provider: VoiceProvider, profile: VoiceProfile) -> str:
    """在 provider 的音色列表里挑一个符合档位语言 / 性别的。

    挑不到就返回空串 —— 让 provider 用自己的默认音色，
    而不是硬塞一个语言不对的 voice_id（那会念出一口中文腔的英文）。
    """
    if profile.voice_id:
        return profile.voice_id
    language = profile.language or "en-US"
    wanted_gender = (profile.gender or "").lower()
    voices = provider.get_voices(language)
    for voice in voices:
        if str(voice.get("gender", "")).lower() == wanted_gender:
            return str(voice.get("name") or voice.get("id") or "")
    # 性别不匹配但语言匹配，仍然比换语言好
    if voices:
        return str(voices[0].get("name") or voices[0].get("id") or "")
    return ""


def resolution_report(provider: VoiceProvider, profile: VoiceProfile) -> Dict[str, Any]:
    """这个档位在这个 provider 上能落地到什么程度。写进 VOICE_QUALITY_REPORT。"""
    request, applied, ignored = profile.apply_to(provider, "probe")
    return {
        "profile": profile.id,
        "provider": provider.id,
        "voice_id": pick_voice_id(provider, profile),
        "applied": applied,
        "ignored": ignored,
        "capabilities": provider.capabilities(),
        "request": request.to_dict(),
    }
