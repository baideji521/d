"""画面比例 / 输出分辨率的唯一真相源。

为什么单独一个模块：分辨率不是「GUI 上显示一下」的东西，它要一路走到底 ——

    GUI 比例下拉 → meta.width / meta.height → Timeline JSON
        → Remotion Composition → 真实 MP4 → ffprobe width/height

只要有第二处地方自己写 `1080, 1920`，就会出现「预览是 9:16、导出是 3:4」这种
对不上的问题。所以比例档位、每个比例允许的分辨率、默认分辨率全部只在这里定义，
GUI / 导出 / 验收脚本 / 文档生成器都从这里读。

比例与分辨率是**联动**的：选 3:4 时分辨率下拉只出现 3:4 的档位。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

#: 画质档位。按**短边**命名，因为竖版与横版共用同一套档位名：
#: 720 / 1080 / 1440 / 2160 分别对应「省流 / 标准 / 高清 / 4K」。
QUALITY_TIERS = (720, 1080, 1440, 2160)

TIER_LABELS: Dict[int, str] = {
    720: "720 省流",
    810: "810 旧工程默认",
    1080: "1080 标准",
    1440: "1440 高清",
    2160: "2160 4K",
}

#: 比例档位。顺序即 GUI 下拉里的顺序。
#: ratio 用最简整数比，用来算宽高比和显示 "3:4"；resolutions 按从小到大排；
#: default 是该比例的推荐档位（指令第十四条给的那一组）。
#:
#: 3:4 里的 810×1080 是仓库里既有工程与验收用例用了很久的档位，
#: 不属于 720/1080/1440/2160 这套命名，但**必须保留** —— 删掉它等于
#: 让所有历史工程在打开时被判成「自定义比例」。
ASPECT_PRESETS: List[Dict[str, object]] = [
    {
        "id": "3:4",
        "label": "3:4 竖版（横屏内容裁竖）",
        "ratio": (3, 4),
        "resolutions": [(720, 960), (810, 1080), (1080, 1440), (1440, 1920), (2160, 2880)],
        "default": (1080, 1440),
    },
    {
        "id": "9:16",
        "label": "9:16 全屏竖版（抖音 / 视频号）",
        "ratio": (9, 16),
        "resolutions": [(720, 1280), (1080, 1920), (1440, 2560), (2160, 3840)],
        "default": (1080, 1920),
    },
    {
        "id": "16:9",
        "label": "16:9 横版（YouTube / B 站）",
        "ratio": (16, 9),
        "resolutions": [(1280, 720), (1920, 1080), (2560, 1440), (3840, 2160)],
        "default": (1920, 1080),
    },
    {
        "id": "1:1",
        "label": "1:1 方版（信息流 / 朋友圈）",
        "ratio": (1, 1),
        "resolutions": [(720, 720), (1080, 1080), (1440, 1440), (2160, 2160)],
        "default": (1080, 1080),
    },
]

#: 新项目的默认档位：沿用仓库里既有工程与验收用例的 810×1080
DEFAULT_ASPECT_ID = "3:4"
DEFAULT_RESOLUTION = (810, 1080)

#: 判定「这个宽高属于哪个比例」时允许的相对误差。
#: 810/1080 = 0.75 正好，720/1280 = 0.5625 正好，
#: 但用户可能手写 1082×1920 这种，差一点也应当认成 9:16。
ASPECT_TOLERANCE = 0.01


def aspect_ids() -> List[str]:
    """所有比例档位 id，按 GUI 顺序。"""
    return [str(preset["id"]) for preset in ASPECT_PRESETS]


def get_aspect(aspect_id: str) -> Optional[Dict[str, object]]:
    """按 id 取比例档位；不认识就返回 None（调用方自己决定兜底）。"""
    for preset in ASPECT_PRESETS:
        if preset["id"] == aspect_id:
            return preset
    return None


def label_of(aspect_id: str) -> str:
    preset = get_aspect(aspect_id)
    return str(preset["label"]) if preset else aspect_id


def ratio_value(aspect_id: str) -> Optional[float]:
    """宽 / 高 的比值，例如 3:4 → 0.75。"""
    preset = get_aspect(aspect_id)
    if not preset:
        return None
    width, height = preset["ratio"]  # type: ignore[misc]
    return float(width) / float(height)


def resolutions_for(aspect_id: str) -> List[Tuple[int, int]]:
    """这个比例下允许选的分辨率。不认识的比例返回空列表。"""
    preset = get_aspect(aspect_id)
    if not preset:
        return []
    return [(int(w), int(h)) for w, h in preset["resolutions"]]  # type: ignore[misc]


def default_resolution(aspect_id: str) -> Tuple[int, int]:
    """比例的推荐分辨率。

    优先用档位表里显式声明的 default（指令第十四条给定的那一组：
    9:16=1080×1920、3:4=1080×1440、16:9=1920×1080、1:1=1080×1080）。
    没声明时退回「短边 1080」那一档，再退回中间档 —— 不能靠 width==1080
    去猜，横版的 1080 档宽度是 1920。
    """
    preset = get_aspect(aspect_id)
    options = resolutions_for(aspect_id)
    if not options:
        return DEFAULT_RESOLUTION
    declared = preset.get("default") if preset else None
    if declared:
        candidate = (int(declared[0]), int(declared[1]))  # type: ignore[index]
        if candidate in options:
            return candidate
    for width, height in options:
        if min(width, height) == 1080:
            return (width, height)
    return options[len(options) // 2]


def tier_of(width: int, height: int) -> int:
    """这个分辨率属于哪个画质档位（按短边）。"""
    return min(int(width), int(height))


def tier_label(width: int, height: int) -> str:
    """画质档位的中文名，用于 GUI 下拉与文档。"""
    tier = tier_of(width, height)
    return TIER_LABELS.get(tier, f"{tier} 自定义")


def resolution_for_tier(aspect_id: str, tier: int) -> Optional[Tuple[int, int]]:
    """按 (比例, 画质档位) 取分辨率。没有这一档就返回 None。"""
    for width, height in resolutions_for(aspect_id):
        if tier_of(width, height) == int(tier):
            return (width, height)
    return None


def aspect_of(width: int, height: int) -> Optional[str]:
    """反查：这个宽高属于哪个比例档位。

    先按精确档位匹配（最可靠），再按比值容差匹配（用户手改过 JSON 的情况）。
    都不匹配时返回 None —— 调用方应当如实显示「自定义」，不要悄悄改用户的数字。
    """
    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None

    for preset in ASPECT_PRESETS:
        if (width, height) in [(int(w), int(h)) for w, h in preset["resolutions"]]:  # type: ignore[misc]
            return str(preset["id"])

    actual = width / height
    for preset in ASPECT_PRESETS:
        target = ratio_value(str(preset["id"]))
        if target and abs(actual - target) <= ASPECT_TOLERANCE * target:
            return str(preset["id"])
    return None


def describe(width: int, height: int) -> str:
    """给 GUI / 报告用的一行说明，例如 "1080×1920（9:16）"。"""
    aspect_id = aspect_of(width, height)
    suffix = f"（{aspect_id}）" if aspect_id else "（自定义比例）"
    return f"{int(width)}×{int(height)}{suffix}"


def is_preset(width: int, height: int) -> bool:
    """是否是预置档位里的分辨率（验收报告要区分预置与自定义）。"""
    for preset in ASPECT_PRESETS:
        if (int(width), int(height)) in [(int(w), int(h)) for w, h in preset["resolutions"]]:  # type: ignore[misc]
            return True
    return False


def all_resolutions() -> List[Tuple[str, int, int]]:
    """(比例 id, 宽, 高) 全表，文档生成器和渲染矩阵直接遍历这个。"""
    rows: List[Tuple[str, int, int]] = []
    for preset in ASPECT_PRESETS:
        for width, height in preset["resolutions"]:  # type: ignore[misc]
            rows.append((str(preset["id"]), int(width), int(height)))
    return rows
