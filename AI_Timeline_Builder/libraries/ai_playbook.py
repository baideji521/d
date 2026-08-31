"""AI Editing Playbook：能力的**用法**，与能力的**定义**分开放。

为什么要单独一个模块（指令第十八 ~ 二十、四十一条）：

- `libraries/effect_registry.py` 与 `transition_registry.py` 是 **Runtime Renderer
  Definition** —— 参数名、取值范围、默认时长、对应的 Remotion 渲染器。
  它们回答「这个特效怎么渲染」，Remotion 侧的 TSX 靠它们对齐。
- 本模块回答完全不同的问题：「**什么时候该用它、什么时候别用、和谁犯冲**」。
  这是剪辑经验，不是渲染事实。混在一起写，就会出现「改一句用法说明
  顺手动了参数默认值」这种事故，也会让渲染器定义被一堆散文淹掉。

所以两边严格分离，只用 name 关联；`playbook_report()` 负责把两边钉在一起：
**注册了的能力必须有用法说明，写了用法的必须真的注册过**。
少一条、多一条都是 FAIL，不允许「文档里有、系统里没有」。

字段语义（每条能力都必须写全）：

- when_to_use / when_not_to_use：什么场合用 / 什么场合别用
- recommended_duration：[最短, 最长] 秒。不是硬限制，是「超出这个范围通常是错的」
- recommended_intensity：关键参数的建议取值（写实际参数名，与 Registry 对得上）
- compatible_with / conflicts_with：能叠 / 别叠。conflicts 里的东西同时同处出现
  不会报错（Validator 不拦），但基本可以断定是失误
- example_decisions：一条真实可用的 EditingDecision（能直接喂给 Planner）

这些数字与判断都是**剪辑经验**，不是平台规范也不是物理定律。
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

#: Playbook 版本。改过任何一条用法说明都 +1，方便对照 AI 行为的变化。
PLAYBOOK_VERSION = 1

#: 强度档位的统一说法，避免同一个意思三种写法
INTENSITY_LEVELS = ("subtle", "moderate", "strong", "extreme")

#: 时长档位（音效用）
DURATION_CLASSES = ("instant", "short", "medium", "long")


def _decision(action: str, **kwargs: Any) -> Dict[str, Any]:
    """拼一条示例决策，键名与 schemas/editing_decision_schema.json 一致。"""
    payload: Dict[str, Any] = {"action": action}
    payload.update(kwargs)
    return payload


# ---------------------------------------------------------------- 程序特效


EFFECT_PLAYBOOK: Dict[str, Dict[str, Any]] = {
    "zoom": {
        "when_to_use": "强调某个瞬间：人物反应、关键道具出现、结论说出口的那一下",
        "when_not_to_use": "整段视频反复推拉；说话镜头里连续推镜会让人晕",
        "recommended_duration": [0.3, 0.8],
        "recommended_intensity": {"scale_to": [1.1, 1.4], "level": "moderate"},
        "compatible_with": ["freeze", "flash", "shake", "impact 音效"],
        "conflicts_with": ["spin", "bounce"],
        "example_decisions": [
            _decision("zoom", target="clip_001", start=12.4, duration=0.5,
                      parameters={"scale_to": 1.25},
                      reason="他愣住那一下要推近")
        ],
    },
    "shake": {
        "when_to_use": "撞击、爆点、情绪炸开的瞬间，配 impact / boom 音效",
        "when_not_to_use": "长于 1 秒的段落，或需要看清字幕的地方",
        "recommended_duration": [0.15, 0.5],
        "recommended_intensity": {"amplitude": [4, 16], "level": "strong"},
        "compatible_with": ["flash", "zoom", "impact 音效"],
        "conflicts_with": ["motion_blur", "字幕出现的同一帧"],
        "example_decisions": [
            _decision("effect", target="clip_001", start=8.0, duration=0.3,
                      parameters={"name": "shake", "amplitude": 10},
                      reason="东西砸下来的一帧要晃一下")
        ],
    },
    "flash": {
        "when_to_use": "两段之间的硬切点、揭示前的一闪、节拍点重音",
        "when_not_to_use": "连续多次使用（观感刺眼，也容易触发平台的闪烁提示）",
        "recommended_duration": [0.08, 0.25],
        "recommended_intensity": {"opacity": [0.6, 1.0], "level": "strong"},
        "compatible_with": ["shake", "zoom", "cut"],
        "conflicts_with": ["crossfade", "blur"],
        "example_decisions": [
            _decision("effect", start=5.0, duration=0.15,
                      parameters={"name": "flash"}, reason="揭示前先闪一下")
        ],
    },
    "blur": {
        "when_to_use": "转场前后的过渡、回忆感、把注意力从背景拉开",
        "when_not_to_use": "需要看清画面细节或字幕的段落",
        "recommended_duration": [0.3, 1.2],
        "recommended_intensity": {"radius": [4, 20], "level": "moderate"},
        "compatible_with": ["crossfade", "caption"],
        "conflicts_with": ["flash", "glitch"],
        "example_decisions": [
            _decision("effect", target="clip_001", start=3.0, duration=0.6,
                      parameters={"name": "blur", "radius": 12},
                      reason="切回忆之前先虚一下")
        ],
    },
    "glitch": {
        "when_to_use": "科技 / 故障 / 反转语气；配 riser 或电流类音效",
        "when_not_to_use": "温情、教学、产品展示这类需要「稳」的内容",
        "recommended_duration": [0.2, 0.5],
        "recommended_intensity": {"intensity": [0.3, 0.8], "level": "strong"},
        "compatible_with": ["rgb_split", "flash", "whip 转场"],
        "conflicts_with": ["blur", "vignette"],
        "example_decisions": [
            _decision("effect", target="clip_001", start=6.5, duration=0.35,
                      parameters={"name": "glitch", "intensity": 0.6},
                      reason="话锋一转，画面也跟着抽一下")
        ],
    },
    "rgb_split": {
        "when_to_use": "冲击感 / 失真感的短暂点缀，常与 glitch 同用",
        "when_not_to_use": "人脸特写（分色会让皮肤发脏）",
        "recommended_duration": [0.15, 0.4],
        "recommended_intensity": {"offset": [2, 10], "level": "moderate"},
        "compatible_with": ["glitch", "shake"],
        "conflicts_with": ["saturation", "vignette"],
        "example_decisions": [
            _decision("effect", target="clip_001", start=6.5, duration=0.25,
                      parameters={"name": "rgb_split", "offset": 6},
                      reason="配合 glitch 加一点失真")
        ],
    },
    "brightness": {
        "when_to_use": "画面偏暗 / 偏亮的整体修正，或做「亮起来」的情绪变化",
        "when_not_to_use": "当成闪光用（那是 flash 的活，brightness 会连字幕一起提亮）",
        "recommended_duration": [0.4, 3.0],
        "recommended_intensity": {"value": [0.85, 1.25], "level": "subtle"},
        "compatible_with": ["contrast", "saturation"],
        "conflicts_with": ["flash"],
        "example_decisions": [
            _decision("effect", target="clip_001", start=0.0, duration=2.0,
                      parameters={"name": "brightness", "value": 1.1},
                      reason="原片偏暗，整体提一点")
        ],
    },
    "contrast": {
        "when_to_use": "画面发灰、层次不够时提对比",
        "when_not_to_use": "已经压暗过的素材（会直接糊成黑块）",
        "recommended_duration": [0.4, 3.0],
        "recommended_intensity": {"value": [0.9, 1.3], "level": "subtle"},
        "compatible_with": ["brightness", "saturation"],
        "conflicts_with": ["vignette"],
        "example_decisions": [
            _decision("effect", target="clip_001", start=0.0, duration=2.0,
                      parameters={"name": "contrast", "value": 1.15},
                      reason="画面发灰，加一点层次")
        ],
    },
    "saturation": {
        "when_to_use": "调整色彩浓度：做鲜艳感，或降到接近黑白做情绪落差",
        "when_not_to_use": "同一段里反复来回改（观众会看出在调色）",
        "recommended_duration": [0.4, 3.0],
        "recommended_intensity": {"value": [0.0, 1.4], "level": "moderate"},
        "compatible_with": ["brightness", "contrast", "vignette"],
        "conflicts_with": ["rgb_split"],
        "example_decisions": [
            _decision("effect", target="clip_001", start=4.0, duration=1.5,
                      parameters={"name": "saturation", "value": 0.2},
                      reason="讲到糟糕的部分，把颜色抽掉")
        ],
    },
    "vignette": {
        "when_to_use": "把视线往画面中心收，做压抑 / 聚焦 / 复古感",
        "when_not_to_use": "四角有重要信息（字幕、logo、贴纸）时",
        "recommended_duration": [0.8, 4.0],
        "recommended_intensity": {"strength": [0.2, 0.6], "level": "subtle"},
        "compatible_with": ["saturation", "blur"],
        "conflicts_with": ["contrast", "rgb_split"],
        "example_decisions": [
            _decision("effect", target="clip_001", start=2.0, duration=2.0,
                      parameters={"name": "vignette", "strength": 0.35},
                      reason="悬念段落收一下视线")
        ],
    },
    "motion_blur": {
        "when_to_use": "快速运动、甩镜、加速段落的拖影",
        "when_not_to_use": "静态镜头（看着像渲染出错），或需要看清字的地方",
        "recommended_duration": [0.15, 0.4],
        "recommended_intensity": {"amount": [0.2, 0.7], "level": "moderate"},
        "compatible_with": ["whip 转场", "speed_lines"],
        "conflicts_with": ["shake", "freeze"],
        "example_decisions": [
            _decision("effect", target="clip_001", start=7.0, duration=0.25,
                      parameters={"name": "motion_blur", "amount": 0.5},
                      reason="甩过去的那一下加拖影")
        ],
    },
    "spin": {
        "when_to_use": "搞笑 / 夸张语气的转折，或配合 spin 转场做同一动作的延续",
        "when_not_to_use": "正经叙述、访谈、教学",
        "recommended_duration": [0.3, 0.8],
        "recommended_intensity": {"turns": [0.25, 1.0], "level": "strong"},
        "compatible_with": ["bounce", "spin 转场"],
        "conflicts_with": ["zoom", "vignette"],
        "example_decisions": [
            _decision("effect", target="clip_001", start=9.0, duration=0.5,
                      parameters={"name": "spin", "turns": 0.5},
                      reason="这句是玩笑，转一下")
        ],
    },
    "bounce": {
        "when_to_use": "轻快节奏、卡点、可爱风格的小弹动",
        "when_not_to_use": "严肃内容；也别和 shake 同时用（两个都在抖）",
        "recommended_duration": [0.3, 0.7],
        "recommended_intensity": {"amount": [0.05, 0.2], "level": "moderate"},
        "compatible_with": ["pulse", "ui 音效"],
        "conflicts_with": ["shake", "motion_blur"],
        "example_decisions": [
            _decision("effect", target="clip_001", start=4.0, duration=0.4,
                      parameters={"name": "bounce", "amount": 0.12},
                      reason="卡在鼓点上弹一下")
        ],
    },
    "pulse": {
        "when_to_use": "跟着节拍持续呼吸感，或强调一个持续存在的元素",
        "when_not_to_use": "长段落（超过 2 秒就从「有节奏」变成「在抽」）",
        "recommended_duration": [0.4, 1.6],
        "recommended_intensity": {"amount": [0.03, 0.15], "level": "subtle"},
        "compatible_with": ["bounce", "音乐节拍"],
        "conflicts_with": ["zoom", "spin"],
        "example_decisions": [
            _decision("effect", target="clip_001", start=1.0, duration=1.2,
                      parameters={"name": "pulse", "amount": 0.08},
                      reason="跟着 BGM 呼吸")
        ],
    },
    # ---------------- 素材特效（overlay 动作，不是 effect 动作）
    "fire": {
        "when_to_use": "怒气 / 爆发 / 「烧起来了」的比喻，叠在画面上",
        "when_not_to_use": "画面本身已经很亮很杂时（火焰会看不出来）",
        "recommended_duration": [0.8, 2.0],
        "recommended_intensity": {"opacity": [0.5, 0.9], "level": "strong"},
        "compatible_with": ["shake", "impact 音效"],
        "conflicts_with": ["smoke", "light_leak"],
        "example_decisions": [
            _decision("overlay", start=10.0, duration=1.2,
                      parameters={"asset": "<素材库里的火焰 id>"},
                      reason="他彻底火了，画面也烧起来")
        ],
    },
    "smoke": {
        "when_to_use": "神秘 / 消失 / 尘埃落定的过渡氛围",
        "when_not_to_use": "需要画面通透的产品展示",
        "recommended_duration": [1.0, 2.5],
        "recommended_intensity": {"opacity": [0.3, 0.7], "level": "moderate"},
        "compatible_with": ["dust", "blur"],
        "conflicts_with": ["fire", "spark"],
        "example_decisions": [
            _decision("overlay", start=6.0, duration=1.5,
                      parameters={"asset": "<素材库里的烟雾 id>"},
                      reason="东西消失的段落加烟")
        ],
    },
    "explosion": {
        "when_to_use": "最强的爆点，一整条视频用一次就够",
        "when_not_to_use": "作为常规转场反复使用",
        "recommended_duration": [0.5, 1.0],
        "recommended_intensity": {"opacity": [0.7, 1.0], "level": "extreme"},
        "compatible_with": ["shake", "flash", "boom 音效"],
        "conflicts_with": ["smoke", "dust"],
        "example_decisions": [
            _decision("overlay", start=14.0, duration=0.8,
                      parameters={"asset": "<素材库里的爆炸 id>"},
                      reason="全片唯一的爆点")
        ],
    },
    "spark": {
        "when_to_use": "小型撞击、金属碰撞、点睛用的火花",
        "when_not_to_use": "大面积覆盖画面（火花是点缀，不是背景）",
        "recommended_duration": [0.3, 0.8],
        "recommended_intensity": {"opacity": [0.5, 0.9], "level": "moderate"},
        "compatible_with": ["metal 音效", "shake"],
        "conflicts_with": ["explosion", "particle"],
        "example_decisions": [
            _decision("overlay", start=5.5, duration=0.6,
                      parameters={"asset": "<素材库里的火花 id>"},
                      reason="金属撞一下的点睛")
        ],
    },
    "lightning": {
        "when_to_use": "突然的转折、惊吓、天气 / 电力相关内容",
        "when_not_to_use": "已经用了 flash 的同一时刻（两个都在闪）",
        "recommended_duration": [0.25, 0.6],
        "recommended_intensity": {"opacity": [0.6, 1.0], "level": "strong"},
        "compatible_with": ["glitch", "riser 音效"],
        "conflicts_with": ["flash", "light_leak"],
        "example_decisions": [
            _decision("overlay", start=7.5, duration=0.4,
                      parameters={"asset": "<素材库里的闪电 id>"},
                      reason="反转来得突然")
        ],
    },
    "light_leak": {
        "when_to_use": "段落之间的柔和过渡、胶片氛围、回忆开场",
        "when_not_to_use": "需要保持画面干净或对比强烈的段落",
        "recommended_duration": [0.6, 1.5],
        "recommended_intensity": {"opacity": [0.3, 0.6], "level": "subtle"},
        "compatible_with": ["crossfade", "saturation"],
        "conflicts_with": ["fire", "lightning"],
        "example_decisions": [
            _decision("overlay", start=0.0, duration=1.0,
                      parameters={"asset": "<素材库里的漏光 id>"},
                      reason="开场做胶片感")
        ],
    },
    "particle": {
        "when_to_use": "梦幻 / 庆祝 / 高光时刻的持续氛围",
        "when_not_to_use": "信息密集的段落（粒子会抢注意力）",
        "recommended_duration": [1.0, 3.0],
        "recommended_intensity": {"opacity": [0.3, 0.7], "level": "moderate"},
        "compatible_with": ["glow", "pulse"],
        "conflicts_with": ["spark", "dust"],
        "example_decisions": [
            _decision("overlay", start=12.0, duration=2.0,
                      parameters={"asset": "<素材库里的粒子 id>"},
                      reason="结尾高光铺一层")
        ],
    },
    "speed_lines": {
        "when_to_use": "加速、冲刺、漫画式夸张的瞬间",
        "when_not_to_use": "静态画面",
        "recommended_duration": [0.3, 0.7],
        "recommended_intensity": {"opacity": [0.5, 0.9], "level": "strong"},
        "compatible_with": ["motion_blur", "whoosh 音效", "whip 转场"],
        "conflicts_with": ["vignette"],
        "example_decisions": [
            _decision("overlay", start=8.5, duration=0.5,
                      parameters={"asset": "<素材库里的速度线 id>"},
                      reason="冲出去那一下加速度线")
        ],
    },
    "glow": {
        "when_to_use": "让主体发亮：奖杯、按钮、关键道具",
        "when_not_to_use": "整个画面（会变成一片白雾）",
        "recommended_duration": [0.5, 1.5],
        "recommended_intensity": {"opacity": [0.3, 0.7], "level": "subtle"},
        "compatible_with": ["particle", "pulse"],
        "conflicts_with": ["flash", "brightness"],
        "example_decisions": [
            _decision("overlay", start=11.0, duration=1.0,
                      parameters={"asset": "<素材库里的光晕 id>"},
                      reason="奖杯要亮一下")
        ],
    },
    "dust": {
        "when_to_use": "旧照片 / 尘土 / 时间流逝的长时间氛围垫底",
        "when_not_to_use": "短促的爆点（尘埃起效慢，0.3 秒里根本看不出）",
        "recommended_duration": [1.5, 4.0],
        "recommended_intensity": {"opacity": [0.2, 0.5], "level": "subtle"},
        "compatible_with": ["smoke", "saturation"],
        "conflicts_with": ["particle", "explosion"],
        "example_decisions": [
            _decision("overlay", start=0.0, duration=3.0,
                      parameters={"asset": "<素材库里的尘埃 id>"},
                      reason="讲往事，铺一层尘")
        ],
    },
}


# ---------------------------------------------------------------- 转场


TRANSITION_PLAYBOOK: Dict[str, Dict[str, Any]] = {
    "fade": {
        "semantics": "经过纯色的「幕落幕起」，读作时间过去了 / 段落结束",
        "when_to_use": "章节之间、结尾收束、场景彻底切换",
        "when_not_to_use": "同一场景内的连续动作（会显得莫名停顿）",
        "recommended_duration": [0.4, 1.0],
        "recommended_intensity": {"level": "subtle"},
        "compatible_with": ["caption", "blur"],
        "conflicts_with": ["flash", "whip"],
        "example_decisions": [
            _decision("transition", start=6.0, duration=0.6,
                      parameters={"name": "fade", "from": "clip_001", "to": "clip_002"},
                      reason="一段讲完了，落一下幕")
        ],
    },
    "crossfade": {
        "semantics": "两个画面直接叠化，读作「同时 / 相似 / 平滑过渡」",
        "when_to_use": "同一主题的不同镜头、时间轻微跳跃、柔和串场",
        "when_not_to_use": "两个画面构图差异极大时（叠化会糊成一团）",
        "recommended_duration": [0.3, 0.8],
        "recommended_intensity": {"level": "subtle"},
        "compatible_with": ["light_leak", "blur"],
        "conflicts_with": ["flash", "glitch"],
        "example_decisions": [
            _decision("transition", start=4.0, duration=0.5,
                      parameters={"name": "crossfade", "from": "clip_001", "to": "clip_002"},
                      reason="同一件事的另一个角度")
        ],
    },
    "flash": {
        "semantics": "一闪而过的白，读作「重击 / 卡点 / 突然」",
        "when_to_use": "音乐重音上的硬切、揭示前一瞬",
        "when_not_to_use": "连续多个切点都用（刺眼）",
        "recommended_duration": [0.1, 0.3],
        "recommended_intensity": {"level": "strong"},
        "compatible_with": ["shake", "impact 音效"],
        "conflicts_with": ["fade", "crossfade"],
        "example_decisions": [
            _decision("transition", start=8.0, duration=0.15,
                      parameters={"name": "flash", "from": "clip_001", "to": "clip_002"},
                      reason="卡在重音上切")
        ],
    },
    "whip": {
        "semantics": "甩镜，读作「快速转场 / 换个话题」",
        "when_to_use": "节奏快的口播、并列举例之间的切换",
        "when_not_to_use": "抒情段落；连续三次以上会晕",
        "recommended_duration": [0.15, 0.35],
        "recommended_intensity": {"level": "strong"},
        "compatible_with": ["motion_blur", "speed_lines", "whoosh 音效"],
        "conflicts_with": ["fade", "crossfade"],
        "example_decisions": [
            _decision("transition", start=5.0, duration=0.2,
                      parameters={"name": "whip", "from": "clip_001", "to": "clip_002"},
                      reason="换下一个例子")
        ],
    },
    "zoom": {
        "semantics": "推进 / 拉出式转场，读作「进入某处 / 抽离出来」",
        "when_to_use": "进入细节、从细节回到全景",
        "when_not_to_use": "两个片段已经各自有 zoom 特效时（叠着推两次）",
        "recommended_duration": [0.25, 0.6],
        "recommended_intensity": {"level": "moderate"},
        "compatible_with": ["impact 音效"],
        "conflicts_with": ["zoom 特效", "spin"],
        "example_decisions": [
            _decision("transition", start=7.0, duration=0.4,
                      parameters={"name": "zoom", "from": "clip_001", "to": "clip_002"},
                      reason="推进去看细节")
        ],
    },
    "wipe": {
        "semantics": "一条边推着画面走，读作「并列 / 对比」",
        "when_to_use": "前后对比、A 与 B 的并列展示",
        "when_not_to_use": "叙事推进（观众会以为在做对比）",
        "recommended_duration": [0.3, 0.7],
        "recommended_intensity": {"level": "moderate"},
        "compatible_with": ["caption", "ui 音效"],
        "conflicts_with": ["crossfade"],
        "example_decisions": [
            _decision("transition", start=9.0, duration=0.5,
                      parameters={"name": "wipe", "from": "clip_001", "to": "clip_002"},
                      reason="展示改造前后")
        ],
    },
    "slide": {
        "semantics": "新画面滑进来，读作「下一项 / 列表推进」",
        "when_to_use": "分点讲解、清单式内容",
        "when_not_to_use": "情绪段落",
        "recommended_duration": [0.25, 0.6],
        "recommended_intensity": {"level": "subtle"},
        "compatible_with": ["caption", "ui 音效"],
        "conflicts_with": ["whip"],
        "example_decisions": [
            _decision("transition", start=3.0, duration=0.4,
                      parameters={"name": "slide", "from": "clip_001", "to": "clip_002"},
                      reason="讲到第二点")
        ],
    },
    "push": {
        "semantics": "旧画面被推出去，读作「被取代 / 强制往下走」",
        "when_to_use": "步骤演示、流程推进",
        "when_not_to_use": "需要观众停下来思考的地方",
        "recommended_duration": [0.25, 0.6],
        "recommended_intensity": {"level": "moderate"},
        "compatible_with": ["ui 音效"],
        "conflicts_with": ["fade"],
        "example_decisions": [
            _decision("transition", start=4.5, duration=0.4,
                      parameters={"name": "push", "from": "clip_001", "to": "clip_002"},
                      reason="下一步")
        ],
    },
    "spin": {
        "semantics": "旋转切换，读作「玩闹 / 夸张」",
        "when_to_use": "搞笑、整段风格本身就夸张的内容",
        "when_not_to_use": "正经内容；一条视频里最多一次",
        "recommended_duration": [0.3, 0.6],
        "recommended_intensity": {"level": "strong"},
        "compatible_with": ["spin 特效", "whoosh 音效"],
        "conflicts_with": ["fade", "zoom"],
        "example_decisions": [
            _decision("transition", start=10.0, duration=0.45,
                      parameters={"name": "spin", "from": "clip_001", "to": "clip_002"},
                      reason="玩笑段落的切换")
        ],
    },
    "blur": {
        "semantics": "虚化再实化，读作「意识模糊 / 时间跳跃」",
        "when_to_use": "回忆、梦境、时间跳转",
        "when_not_to_use": "需要看清画面的展示段落",
        "recommended_duration": [0.4, 0.9],
        "recommended_intensity": {"level": "moderate"},
        "compatible_with": ["blur 特效", "light_leak"],
        "conflicts_with": ["flash", "glitch"],
        "example_decisions": [
            _decision("transition", start=6.5, duration=0.6,
                      parameters={"name": "blur", "from": "clip_001", "to": "clip_002"},
                      reason="切进回忆")
        ],
    },
    "glitch": {
        "semantics": "信号故障式切换，读作「出错 / 反转 / 数字感」",
        "when_to_use": "科技题材、剧情反转、揭穿真相",
        "when_not_to_use": "温情内容；也别与 glitch 特效叠在同一时刻",
        "recommended_duration": [0.2, 0.5],
        "recommended_intensity": {"level": "strong"},
        "compatible_with": ["rgb_split", "riser 音效"],
        "conflicts_with": ["glitch 特效", "crossfade"],
        "example_decisions": [
            _decision("transition", start=11.5, duration=0.3,
                      parameters={"name": "glitch", "from": "clip_001", "to": "clip_002"},
                      reason="真相反转")
        ],
    },
}


# ---------------------------------------------------------------- 音效分类


SFX_PLAYBOOK: Dict[str, Dict[str, Any]] = {
    "boom": {
        "semantic_tags": ["低频", "重击", "灾难", "结论"],
        "recommended_actions": ["highlight", "freeze", "effect:shake"],
        "intensity": "extreme",
        "duration_class": "medium",
        "note": "整条视频用一到两次；用多了每一次都不重了",
    },
    "impact": {
        "semantic_tags": ["撞击", "强调", "卡点"],
        "recommended_actions": ["highlight", "zoom", "effect:shake", "transition:flash"],
        "intensity": "strong",
        "duration_class": "short",
        "note": "最通用的强调音效，highlight 默认就挑这一类",
    },
    "whoosh": {
        "semantic_tags": ["运动", "转场", "掠过"],
        "recommended_actions": ["transition:whip", "transition:spin", "overlay:speed_lines"],
        "intensity": "moderate",
        "duration_class": "short",
        "note": "跟着画面运动方向走，别在静止画面上用",
    },
    "riser": {
        "semantic_tags": ["蓄力", "悬念", "揭示前"],
        "recommended_actions": ["transition:glitch", "effect:glitch", "caption"],
        "intensity": "strong",
        "duration_class": "long",
        "note": "必须落在一个真正的爆点上；没有落点的 riser 会让人白紧张一场",
    },
    "glass": {
        "semantic_tags": ["破碎", "尖锐", "意外"],
        "recommended_actions": ["effect:shake", "overlay:spark"],
        "intensity": "strong",
        "duration_class": "short",
        "note": "语义很具体（东西碎了），别当通用强调用",
    },
    "metal": {
        "semantic_tags": ["金属", "机械", "碰撞"],
        "recommended_actions": ["overlay:spark", "effect:shake"],
        "intensity": "moderate",
        "duration_class": "short",
        "note": "配画面里真的有金属 / 机械时才不违和",
    },
    "wood": {
        "semantic_tags": ["木质", "敲击", "日常"],
        "recommended_actions": ["caption", "effect:bounce"],
        "intensity": "moderate",
        "duration_class": "instant",
        "note": "轻量点缀，适合生活类内容",
    },
    "footstep": {
        "semantic_tags": ["脚步", "环境", "写实"],
        "recommended_actions": ["音效垫底（不配特效）"],
        "intensity": "subtle",
        "duration_class": "instant",
        "note": "属于拟音，用来补真实感，不是强调工具",
    },
    "ui": {
        "semantic_tags": ["界面", "提示", "点击", "清单"],
        "recommended_actions": ["caption", "transition:slide", "transition:push"],
        "intensity": "subtle",
        "duration_class": "instant",
        "note": "字幕出现、分点推进时用；别拿它当爆点",
    },
    "soft": {
        "semantic_tags": ["柔和", "过渡", "呼吸"],
        "recommended_actions": ["transition:crossfade", "transition:fade"],
        "intensity": "subtle",
        "duration_class": "medium",
        "note": "情绪段落的垫音，音量建议压到 0.3 ~ 0.5",
    },
}


#: 每条能力必须写全的字段（少一个就是没写完，不是「暂时留空」）
REQUIRED_CAPABILITY_FIELDS = (
    "when_to_use",
    "when_not_to_use",
    "recommended_duration",
    "recommended_intensity",
    "compatible_with",
    "conflicts_with",
    "example_decisions",
)

REQUIRED_SFX_FIELDS = ("semantic_tags", "recommended_actions", "intensity", "duration_class")


def effect_usage(name: str) -> Dict[str, Any]:
    """某个特效的用法说明。没写过就返回空 dict，由一致性检查报出来。"""
    return dict(EFFECT_PLAYBOOK.get(name) or {})


def transition_usage(name: str) -> Dict[str, Any]:
    return dict(TRANSITION_PLAYBOOK.get(name) or {})


def sfx_usage(category: str) -> Dict[str, Any]:
    return dict(SFX_PLAYBOOK.get(category) or {})


def catalog() -> Dict[str, Any]:
    """整本 Playbook 的结构化形式，给 AI_CAPABILITIES / 文档生成器用。"""
    return {
        "version": PLAYBOOK_VERSION,
        "note": (
            "本节是**用法**，与渲染器定义分开维护：参数取值范围看 EFFECT_CATALOG / "
            "TRANSITION_CATALOG，什么时候该用看这里。数字是剪辑经验，不是硬限制"
        ),
        "intensity_levels": list(INTENSITY_LEVELS),
        "duration_classes": list(DURATION_CLASSES),
        "effects": {name: dict(row) for name, row in EFFECT_PLAYBOOK.items()},
        "transitions": {name: dict(row) for name, row in TRANSITION_PLAYBOOK.items()},
        "sfx_categories": {name: dict(row) for name, row in SFX_PLAYBOOK.items()},
    }


def playbook_report(
    effect_names: Sequence[str],
    transition_names: Sequence[str],
    sfx_categories: Sequence[str],
) -> Dict[str, Any]:
    """Playbook ↔ Registry 的一致性报告（指令第三十二条）。

    - missing_*：注册了但没写用法（AI 拿不到判断依据）
    - unknown_*：写了用法但系统里没这个能力（文档在骗人）
    - incomplete_*：字段没写全

    三份列表都必须为空，任何一条非空就是 FAIL。
    """
    effects = set(effect_names)
    transitions = set(transition_names)
    categories = set(sfx_categories)

    def incomplete(table: Dict[str, Dict[str, Any]], fields: Sequence[str]) -> List[str]:
        rows: List[str] = []
        for name, row in table.items():
            for key in fields:
                value = row.get(key)
                if value in (None, "", [], {}):
                    rows.append(f"{name}.{key}")
        return sorted(rows)

    return {
        "version": PLAYBOOK_VERSION,
        "missing_effects": sorted(effects - set(EFFECT_PLAYBOOK)),
        "unknown_effects": sorted(set(EFFECT_PLAYBOOK) - effects),
        "missing_transitions": sorted(transitions - set(TRANSITION_PLAYBOOK)),
        "unknown_transitions": sorted(set(TRANSITION_PLAYBOOK) - transitions),
        "missing_sfx_categories": sorted(categories - set(SFX_PLAYBOOK)),
        "unknown_sfx_categories": sorted(set(SFX_PLAYBOOK) - categories),
        "incomplete_effects": incomplete(EFFECT_PLAYBOOK, REQUIRED_CAPABILITY_FIELDS),
        "incomplete_transitions": incomplete(TRANSITION_PLAYBOOK, REQUIRED_CAPABILITY_FIELDS),
        "incomplete_sfx_categories": incomplete(SFX_PLAYBOOK, REQUIRED_SFX_FIELDS),
    }
