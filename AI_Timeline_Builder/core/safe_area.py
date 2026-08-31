"""Safe Area（安全区）的唯一真相源。

竖版平台的界面会盖住画面的边缘：抖音右侧一列按钮、底部一条文案 + 导航栏，
Reels / Shorts 各有各的占位。字幕、标题、贴纸摆到那些位置上，
在预览里看着好看，发出去就被 UI 压住了。

所以安全区必须是**数据**，一路走到底：

    SAFE_AREA_PRESETS → meta.safe_area → GUI 预览虚线框
                                      → Editing Planner 自动收位
                                      → clamp_to_safe_area() 一键收位
                                      → Validator（RULE_SAFE_AREA_001 / 002）

数字的性质要说清楚：这些内缩比例是按各平台当前界面**实测估算**的经验值，
不是平台官方发布的规范，所以每份工程都记下 `version` 与 `source`
（`{"preset": "tiktok", "version": 1, "source": "empirical"}`），
谁都别把它当官方标准用。

它是**排版约束**，不是渲染效果：

- Remotion 侧完全不读 safe_area —— 画面上不会画出安全框，
  也不会在渲染时偷偷把字幕挪位置；
- 越界的字幕 / 文字 / 叠加素材由 Validator 提示（002，warning），
  显式声明 `safe_area: true` 的越界则是 error（001）；
- 真要改位置得显式调 `clamp_to_safe_area()`，改完的坐标写回
  Timeline JSON —— 落盘的就是最终合法位置，不存在「渲染时才对齐」这种黑盒。

坐标系与 transform 一致：x / y 都是 0..1 的画面归一化坐标，
(0.5, 0.5) 是正中心，y 越大越靠下。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

#: 安全区档位。inset 是四边**内缩比例**（占画面宽 / 高的比例）。
#: 顺序即 GUI 下拉顺序，generic 放最后当兜底。
SAFE_AREA_PRESETS: List[Dict[str, Any]] = [
    {
        "id": "tiktok",
        "label": "抖音 / TikTok",
        "note": "右侧头像与按钮列、底部文案与导航栏占位最多",
        "insets": {"top": 0.11, "bottom": 0.21, "left": 0.05, "right": 0.14},
    },
    {
        "id": "youtube_shorts",
        "label": "YouTube Shorts",
        "note": "底部标题 + 订阅条，右侧互动按钮",
        "insets": {"top": 0.08, "bottom": 0.16, "left": 0.04, "right": 0.12},
    },
    {
        "id": "instagram_reels",
        "label": "Instagram Reels",
        "note": "底部文案区最高，右侧按钮列略窄",
        "insets": {"top": 0.10, "bottom": 0.20, "left": 0.04, "right": 0.13},
    },
    {
        "id": "generic",
        "label": "通用（四边各留 5%）",
        "note": "不确定投放平台时的保守值",
        "insets": {"top": 0.05, "bottom": 0.05, "left": 0.05, "right": 0.05},
    },
]

#: 缺省档位：没写 meta.safe_area 时按通用处理
DEFAULT_PRESET_ID = "generic"

#: 内缩数值的版本号。改过任何一个档位的数字都要 +1，
#: 否则老工程说不清自己当初是按哪套数字收位的（指令第二十三条）。
PRESET_VERSION = 1

#: 数值来源。只有 "empirical"（实测估算）这一种 ——
#: 平台没发布过官方安全区规范，所以**不许**在任何地方写成 official。
PRESET_SOURCE = "empirical"

#: 会被安全区约束的元素类型（指令第二十一条）。
#: 视频与冻帧不在内：它们本来就该满屏，收进安全区等于给画面加黑边。
CONSTRAINED_TYPES = ("caption", "caption_group", "text", "overlay")

#: 元素上「锁进安全区」这个开关的默认值。
#: 默认 False，所以稀疏序列化时整个键不出现（core/sparse.py 的 default elision）。
DEFAULT_ELEMENT_LOCK = False



def preset_ids() -> List[str]:
    """所有档位 id，按 GUI 顺序。"""
    return [str(preset["id"]) for preset in SAFE_AREA_PRESETS]


def get_preset(preset_id: str) -> Optional[Dict[str, Any]]:
    """按 id 取档位；不认识就返回 None，由调用方决定兜底。"""
    for preset in SAFE_AREA_PRESETS:
        if preset["id"] == preset_id:
            return preset
    return None


def label_of(preset_id: str) -> str:
    preset = get_preset(preset_id)
    return str(preset["label"]) if preset else preset_id


def insets(preset_id: str = DEFAULT_PRESET_ID) -> Dict[str, float]:
    """四边内缩比例。不认识的档位退回通用值，绝不抛异常。"""
    preset = get_preset(preset_id) or get_preset(DEFAULT_PRESET_ID)
    return dict(preset["insets"])  # type: ignore[index]


def box(preset_id: str = DEFAULT_PRESET_ID) -> Tuple[float, float, float, float]:
    """安全区矩形，返回 (left, top, right, bottom)，都是 0..1 归一化坐标。"""
    values = insets(preset_id)
    return (
        float(values["left"]),
        float(values["top"]),
        1.0 - float(values["right"]),
        1.0 - float(values["bottom"]),
    )


def timeline_preset(timeline: Dict[str, Any]) -> str:
    """时间线当前使用的安全区档位。

    读 `meta.safe_area.preset`；没写 / 写了不认识的值都按通用处理。
    这是「兼容扩展」：老 JSON 里没有这个键，行为与从前完全一致。
    """
    raw = (timeline.get("meta") or {}).get("safe_area")
    if isinstance(raw, dict):
        candidate = str(raw.get("preset", "") or "")
        if get_preset(candidate):
            return candidate
    return DEFAULT_PRESET_ID


def element_locked(element: Dict[str, Any]) -> bool:
    """这个元素是否声明了「锁进安全区」。"""
    return bool(element.get("safe_area", DEFAULT_ELEMENT_LOCK))


def contains(x: float, y: float, preset_id: str = DEFAULT_PRESET_ID) -> bool:
    """点是否落在安全区内（含边界）。"""
    left, top, right, bottom = box(preset_id)
    eps = 1e-9
    return (left - eps) <= x <= (right + eps) and (top - eps) <= y <= (bottom + eps)


def clamp(x: float, y: float, preset_id: str = DEFAULT_PRESET_ID) -> Tuple[float, float]:
    """把点收进安全区。已经在里面的原样返回（不做任何位移）。"""
    left, top, right, bottom = box(preset_id)
    return (min(max(x, left), right), min(max(y, top), bottom))


def clamp_element(element: Dict[str, Any], preset_id: str = DEFAULT_PRESET_ID) -> bool:
    """把元素的 transform.x / y 收进安全区，返回是否真的改动过。

    只在需要移动时才写 transform —— 本来就在安全区内的元素不会被塞进
    一份「等于默认值」的 transform，否则稀疏 JSON 立刻被污染。
    """
    from core import timeline as tl  # 局部导入：避免 core 内部循环依赖

    current = tl.effective_transform(element)
    x, y = float(current["x"]), float(current["y"])
    new_x, new_y = clamp(x, y, preset_id)
    if abs(new_x - x) < 1e-9 and abs(new_y - y) < 1e-9:
        return False
    transform = dict(element.get("transform") or {})
    if abs(new_x - tl.DEFAULT_TRANSFORM["x"]) > 1e-9 or "x" in transform:
        transform["x"] = round(new_x, 4)
    if abs(new_y - tl.DEFAULT_TRANSFORM["y"]) > 1e-9 or "y" in transform:
        transform["y"] = round(new_y, 4)
    element["transform"] = transform
    return True


def preset_meta(preset_id: str = DEFAULT_PRESET_ID) -> Dict[str, Any]:
    """写进 `meta.safe_area` 的完整档位记录（指令第二十三条）。

        {"preset": "tiktok", "version": 1, "source": "empirical"}

    带上版本与来源，是为了让工程文件自己说清楚「这套数字是哪来的、哪一版」，
    而不是让读文件的人以为它是平台官方规范。
    """
    resolved = preset_id if get_preset(preset_id) else DEFAULT_PRESET_ID
    return {"preset": resolved, "version": PRESET_VERSION, "source": PRESET_SOURCE}


def timeline_preset_meta(timeline: Dict[str, Any]) -> Dict[str, Any]:
    """读回时间线上的档位记录，缺的字段按当前常量补齐。

    老工程只写了 `{"preset": "tiktok"}`，这里会补成 version 1 / empirical ——
    因为 version 1 就是这些数字第一次落盘时的版本，补齐不改变事实。
    """
    raw = (timeline.get("meta") or {}).get("safe_area")
    meta = preset_meta(timeline_preset(timeline))
    if isinstance(raw, dict):
        if isinstance(raw.get("version"), int) and raw["version"] > 0:
            meta["version"] = int(raw["version"])
        if raw.get("source"):
            meta["source"] = str(raw["source"])
    return meta


def constrained(element: Dict[str, Any], types: Sequence[str] = CONSTRAINED_TYPES) -> bool:
    """这个元素是否受安全区约束（类型在名单里 + 有位置语义）。"""
    from core import timeline as tl  # 局部导入：避免 core 内部循环依赖

    return element.get("type") in tuple(types) and tl.supports_transform(element)


def violations(
    timeline: Dict[str, Any],
    types: Sequence[str] = CONSTRAINED_TYPES,
) -> List[Dict[str, Any]]:
    """列出所有「该在安全区内、实际在外面」的元素（指令第二十一条）。

    与 RULE_SAFE_AREA_001 的分工：

    - 001 只管**显式声明** `safe_area: true` 的元素，越界即 error（用户自己要求锁位）；
    - 本函数覆盖所有字幕 / 文字 / 叠加素材，无论有没有声明 ——
      结果由 RULE_SAFE_AREA_002 报成 warning。安全区是排版约束，
      不是「声明了才存在」的装饰；但没声明的越界只提示，不拦渲染。

    返回的每条记录都带 `locked`，调用方据此决定 error 还是 warning。
    """
    from core import timeline as tl

    preset = timeline_preset(timeline)
    left, top, right, bottom = box(preset)
    rows: List[Dict[str, Any]] = []
    for element in timeline.get("elements", []):
        if not isinstance(element, dict) or not constrained(element, types):
            continue
        transform = tl.effective_transform(element)
        x, y = float(transform["x"]), float(transform["y"])
        if contains(x, y, preset):
            continue
        rows.append(
            {
                "id": str(element.get("id", "")),
                "type": str(element.get("type", "")),
                "x": round(x, 4),
                "y": round(y, 4),
                "locked": element_locked(element),
                "preset": preset,
                "box": {"left": left, "top": top, "right": right, "bottom": bottom},
            }
        )
    return rows


def clamp_to_safe_area(
    timeline: Dict[str, Any],
    types: Sequence[str] = CONSTRAINED_TYPES,
    only_locked: bool = False,
) -> List[Dict[str, Any]]:
    """把越界的字幕 / 文字 / 叠加素材收进安全区，**就地改** timeline。

    这是「可选的一键收位」，不是渲染时的隐式行为：Remotion 侧完全不读
    safe_area，画面上也不会画出安全框。收位的结果直接写进 transform，
    所以 Timeline JSON 里记录的就是最终合法位置（指令第二十一、二十二条）。

    返回每个被移动元素的前后坐标，GUI 与报告都靠它说清「动了谁、动了多少」。
    """
    preset = timeline_preset(timeline)
    moved: List[Dict[str, Any]] = []
    for row in violations(timeline, types):
        if only_locked and not row["locked"]:
            continue
        element = next(
            (
                e
                for e in timeline.get("elements", [])
                if isinstance(e, dict) and str(e.get("id", "")) == row["id"]
            ),
            None,
        )
        if element is None:
            continue
        before = (row["x"], row["y"])
        if not clamp_element(element, preset):
            continue
        after = clamp(before[0], before[1], preset)
        moved.append(
            {
                "id": row["id"],
                "type": row["type"],
                "from": {"x": before[0], "y": before[1]},
                "to": {"x": round(after[0], 4), "y": round(after[1], 4)},
                "preset": preset,
            }
        )
    return moved


def describe(preset_id: str = DEFAULT_PRESET_ID) -> str:
    """给报告 / GUI 提示用的一行说明。"""
    left, top, right, bottom = box(preset_id)
    return (
        f"{label_of(preset_id)}：x ∈ [{left:.2f}, {right:.2f}]，"
        f"y ∈ [{top:.2f}, {bottom:.2f}]"
    )


def catalog() -> List[Dict[str, Any]]:
    """给能力目录 / 文档生成器用的结构化档位表。"""
    rows: List[Dict[str, Any]] = []
    for preset in SAFE_AREA_PRESETS:
        preset_id = str(preset["id"])
        left, top, right, bottom = box(preset_id)
        rows.append(
            {
                "id": preset_id,
                "label": preset["label"],
                "note": preset["note"],
                "version": PRESET_VERSION,
                "source": PRESET_SOURCE,
                "insets": dict(preset["insets"]),  # type: ignore[arg-type]
                "box": {"left": left, "top": top, "right": right, "bottom": bottom},
            }
        )
    return rows
