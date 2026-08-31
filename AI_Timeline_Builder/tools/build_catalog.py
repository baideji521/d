"""Catalog Generator：把仓库里**真实注册**的能力导出成人读文档 + 机器可读目录。

用法::

    python tools/build_catalog.py           # 写入 docs/
    python tools/build_catalog.py --check   # 只比对，不写文件；有漂移就 exit 1

产物::

    docs/EFFECT_CATALOG.md
    docs/TRANSITION_CATALOG.md
    docs/SOUND_EFFECT_CATALOG.md
    docs/RESOLUTION_GUIDE.md
    docs/TIMELINE_GUI_GUIDE.md
    docs/TIMELINE_JSON_EXAMPLES.md
    docs/AI_MEDIA_CATALOG.json

三条硬规矩：

1. **只扫真实数据源。** 特效 / 转场来自 Python 注册表实例，音效来自 asset manifest
   且必须 `os.path.exists`，分辨率来自 `core/resolution.py`，快捷键来自 `gui/shortcuts.py`。
   不手写清单，不"补全"看起来应该有的条目。
2. **Renderer 名单从 Remotion 运行时读**（node 跑 `out/acceptance/discover_renderers.mjs`）。
   `fade` / `slide` / `push` 是工厂函数生成的，正则扫源码会漏。node 不可用时写
   "未探测"，绝不假装探测过。
3. **输出必须确定。** 不写时间戳，同样的仓库状态生成同样的文件，`--check` 才有意义。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import markers as mk  # noqa: E402
from core import resolution as res  # noqa: E402
from core import rule_engine as rules_mod  # noqa: E402
from core import safe_area as safe  # noqa: E402
from core import sparse  # noqa: E402
from core import timeline as tl  # noqa: E402
from core import voice as voice_mod  # noqa: E402
from core.editing_planner import ACTIONS, action_catalog  # noqa: E402
from core.timeline_validator import TimelineValidator  # noqa: E402
from gui import asset_placement as ap  # noqa: E402
from gui import shortcuts as sc  # noqa: E402
from gui.timeline_coordinate import PERCENT_STEPS, PPS_AT_100  # noqa: E402
from gui.timeline_snap import MAX_SNAP_SECONDS, SNAP_PIXELS  # noqa: E402
from libraries.asset_registry import AssetRegistry  # noqa: E402
from libraries.effect_library import EffectLibrary  # noqa: E402
from libraries.sound_library import SoundLibrary  # noqa: E402
from libraries.transition_library import TransitionLibrary  # noqa: E402

DOCS = os.path.join(ROOT, "docs")
ASSETS_DIR = os.path.join(ROOT, "assets")
MANIFEST = os.path.join(ROOT, "asset_manifest.json")
RULES_PATH = os.path.join(ROOT, "schemas", "rules.json")
DISCOVER = os.path.join(ROOT, "out", "acceptance", "discover_renderers.mjs")

GENERATED_BY = "由 `python tools/build_catalog.py` 扫描真实注册表生成，**请勿手改**。"


# ---------------------------------------------------------------- 工具


def _fmt(value: Any) -> str:
    """把参数默认值渲染成人读文本。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}"
    if value is None:
        return "—"
    if isinstance(value, str):
        return f"`{value}`" if value else "（空）"
    return f"`{json.dumps(value, ensure_ascii=False)}`"


def _range_text(param: Dict[str, Any]) -> str:
    options = param.get("options")
    if options:
        return " / ".join(f"`{o}`" for o in options)
    low, high = param.get("min"), param.get("max")
    if low is None and high is None:
        return "—"
    step = param.get("step")
    text = f"{_fmt(low)} ~ {_fmt(high)}"
    if step is not None:
        text += f"，步长 {_fmt(step)}"
    return text


def _param_table(params: List[Dict[str, Any]]) -> List[str]:
    if not params:
        return ["无参数。", ""]
    lines = ["| 参数 | 名称 | 类型 | 默认 | 取值 |", "| --- | --- | --- | --- | --- |"]
    for param in params:
        lines.append(
            f'| `{param.get("key","")}` | {param.get("label","")} | `{param.get("type","")}` '
            f'| {_fmt(param.get("default"))} | {_range_text(param)} |'
        )
    lines.append("")
    return lines


def _json_block(payload: Any) -> List[str]:
    return ["```json", json.dumps(payload, ensure_ascii=False, indent=2), "```", ""]


def discover_renderers() -> Tuple[Optional[Dict[str, Any]], str]:
    """从 Remotion 侧注册表读真实 renderer 名单。

    返回 `(payload, note)`。探测失败时 payload 为 None，note 写明原因——
    文档里就会显示"未探测"，而不是假装两边一致。
    """
    node = os.environ.get("NODE_BIN") or shutil.which("node")
    if not node:
        # Windows 上 "C:\Program Files\nodejs\node.exe" 带空格，cmd 会把引号吃掉，
        # 所以退回 8.3 短路径。
        for candidate in (r"C:\PROGRA~1\nodejs\node.exe", r"C:\PROGRA~2\nodejs\node.exe"):
            if os.path.exists(candidate):
                node = candidate
                break
    if not node:
        return None, "未探测（找不到 node 可执行文件）"
    if not os.path.exists(DISCOVER):
        return None, f"未探测（缺少 {os.path.relpath(DISCOVER, ROOT)}）"
    try:
        result = subprocess.run(
            [node, "--experimental-strip-types", "--no-warnings", DISCOVER],
            cwd=ROOT, capture_output=True, text=True, timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - 环境相关
        return None, f"未探测（node 执行失败：{exc}）"
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit {result.returncode}"
        return None, f"未探测（node 退出码 {result.returncode}：{tail}）"
    try:
        return json.loads(result.stdout), "已从 Remotion 运行时注册表读取"
    except ValueError:
        return None, "未探测（discover_renderers 输出不是 JSON）"


def _coverage_lines(names: List[str], runtime: Optional[List[str]], note: str,
                    subject: str) -> List[str]:
    """Python 注册表 ↔ Remotion renderer 的覆盖对照。"""
    lines = [f"## Renderer 覆盖（{subject}）", "", f"探测方式：{note}", ""]
    if runtime is None:
        lines += [
            f"- Python 注册表：{len(names)} 个",
            "- Remotion 注册表：未探测，本次不做覆盖结论（不能凭源码猜）",
            "",
        ]
        return lines
    missing = [n for n in names if n not in runtime]
    extra = [n for n in runtime if n not in names]
    lines += [
        f"- Python 注册表：{len(names)} 个",
        f"- Remotion 注册表：{len(runtime)} 个",
        f'- Python 有、Remotion 缺 renderer：{"无" if not missing else "、".join(f"`{n}`" for n in missing)}',
        f'- Remotion 有、Python 未登记：{"无" if not extra else "、".join(f"`{n}`" for n in extra)}',
        "",
    ]
    return lines


# ---------------------------------------------------------------- Effect


def _material_assets(registry: AssetRegistry, name: str) -> List[str]:
    """素材特效靠 overlay 元素 + 一个真实素材文件落地。
    按 asset id 去空格下划线后包含特效名来匹配（`ov_lightleak` ↔ `light_leak`），
    只认 id、不拿文件名模糊匹配 —— 否则 `dust_sparkle` 会被 `spark` 抢走。
    盘上找不到文件的素材不算可用。"""
    token = name.replace("_", "").lower()
    hits = []
    for asset in registry.all():
        path = str(asset.get("path", ""))
        if not path.startswith(("assets/transitions", "assets/overlays")):
            continue
        if token not in str(asset.get("id", "")).replace("_", "").lower():
            continue
        full = os.path.join(ROOT, path.replace("/", os.sep))
        if os.path.isfile(full):
            hits.append(str(asset.get("id", "")))
    return sorted(hits)


def build_effect_catalog(effects, runtime: Optional[Dict[str, Any]], note: str,
                         registry: AssetRegistry) -> str:
    items = sorted(effects.all(), key=lambda d: (d.category, d.name))
    runtime_names = None
    if runtime is not None:
        runtime_names = [e.get("name") for e in runtime.get("effects", [])]
    kinds: Dict[str, int] = {}
    for item in items:
        kinds[str(item.get("kind") or "program")] = kinds.get(str(item.get("kind") or "program"), 0) + 1

    lines = [
        "# Effect 目录",
        "",
        GENERATED_BY,
        "",
        "- Python 注册表：`libraries/effect_library.py`（`EffectRegistry`）",
        "- Remotion renderer：`remotion/src/effects/index.ts`",
        f"- 共 {len(items)} 个特效："
        + "、".join(f"{k} {v} 个" for k, v in sorted(kinds.items())),
        "",
        "`kind=program` 是程序特效（`type=effect` 元素，靠 `target` 绑定被作用元素）；",
        "`kind=material` 是素材特效（写成 `type=overlay` 元素，本质是叠加一段素材）。",
        "",
    ]
    lines += _coverage_lines(
        [d.renderer or d.name for d in items if str(d.get("kind") or "program") == "program"],
        runtime_names, note, "program 特效",
    )

    lines += ["## 一览", "",
              "| name | 中文名 | 分类 | kind | renderer | 默认时长 | 素材可用性 |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for item in items:
        kind = str(item.get("kind", "program"))
        if kind == "program":
            availability = "不需要素材（程序渲染）"
        else:
            hits = _material_assets(registry, item.name)
            availability = ("AVAILABLE：" + "、".join(f"`{i}`" for i in hits)) if hits \
                else "MISSING：素材库里没有对应文件，放上去之前渲染不出东西"
        lines.append(
            f'| `{item.name}` | {item.display_name} | {item.display_category}'
            f'（{item.category}） | `{kind}` | `{item.renderer or "—"}` '
            f'| {item.default_duration:g}s | {availability} |'
        )
    lines.append("")

    lines += ["## 逐个说明", ""]
    for item in items:
        kind = str(item.get("kind", "program"))
        lines += [
            f"### `{item.name}` · {item.display_name}",
            "",
            f"- 分类：{item.display_category}（`{item.category}`）",
            f'- kind：`{kind}`　scope：`{item.get("scope","element")}`',
            f'- renderer：`{item.renderer or "—"}`',
            f"- 默认时长：{item.default_duration:g}s",
            f'- 可作用元素：{"、".join(f"`{t}`" for t in item.get("supported_targets", [])) or "—"}',
            f"- 说明：{item.description or '—'}",
        ]
        if kind != "program":
            hits = _material_assets(registry, item.name)
            lines.append(
                "- 素材可用性：" + ("AVAILABLE —— " + "、".join(f"`{i}`" for i in hits)
                                if hits else
                                "**MISSING** —— 注册表里有这个特效，但 `assets/overlays` / "
                                "`assets/transitions` 里没有对应素材文件；"
                                "在导入素材之前它渲染不出任何画面")
            )
        lines.append("")
        lines += _param_table([dict(p) for p in item.get("params", [])])
    return "\n".join(lines).rstrip() + "\n"



# ---------------------------------------------------------------- Transition


def build_transition_catalog(transitions, runtime: Optional[Dict[str, Any]], note: str) -> str:
    items = sorted(transitions.all(), key=lambda d: (d.category, d.name))
    runtime_names = runtime.get("transitions") if runtime is not None else None

    lines = [
        "# Transition 目录",
        "",
        GENERATED_BY,
        "",
        "- Python 注册表：`libraries/transition_library.py`（`TransitionRegistry`）",
        "- Remotion renderer：`remotion/src/transitions/index.ts`",
        f"- 共 {len(items)} 个转场，覆盖 {len(transitions.categories())} 个分类",
        "",
        "转场元素必须同时绑定 `from` / `to` 两个片段，且窗口要落在两者的重叠区间内；",
        "Remotion 侧未知名字会退回 `crossfade`（拦截未知名字是 Validator 的职责）。",
        "",
    ]
    lines += _coverage_lines([d.renderer or d.name for d in items], runtime_names, note, "转场")

    lines += ["## 一览", "", "| name | 中文名 | 分类 | renderer | 默认时长 | from → to |",
              "| --- | --- | --- | --- | --- | --- |"]
    for item in items:
        lines.append(
            f"| `{item.name}` | {item.display_name} | {item.display_category}"
            f'（{item.category}） | `{item.renderer or "—"}` | {item.default_duration:g}s '
            f'| {"/".join(item.supported_from)} → {"/".join(item.supported_to)} |'
        )
    lines.append("")

    lines += ["## 逐个说明", ""]
    for item in items:
        lines += [
            f"### `{item.name}` · {item.display_name}",
            "",
            f"- 分类：{item.display_category}（`{item.category}`）",
            f'- renderer：`{item.renderer or "—"}`',
            f"- 默认时长：{item.default_duration:g}s",
            f'- 接受的 from：{"、".join(f"`{t}`" for t in item.supported_from) or "—"}',
            f'- 接受的 to：{"、".join(f"`{t}`" for t in item.supported_to) or "—"}',
            f"- 说明：{item.description or '—'}",
            "",
        ]
        lines += _param_table([dict(p) for p in item.get("params", [])])
        lines += _json_block(tl.make_transition(
            "transition_001", item.name, "clip_001", "clip_002",
            1.0, item.default_duration, {}, "V1",
        ))
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------- Sound


def build_sound_catalog(sounds: SoundLibrary) -> str:
    summary = sounds.summary()
    counts = summary["count_by_category"]
    lines = [
        "# 音效库目录",
        "",
        GENERATED_BY,
        "",
        "本文件把两件事分开写，**不要混着看**：",
        "",
        "1. **系统支持的音效类型**：协议层面的分类（`libraries/sound_library.py`），",
        "   跟本地有没有文件无关；0 个文件的类型也会列出来，数量写 0。",
        "2. **本地实际存在的音效文件**：来自 `asset_manifest.json`，并且逐个做过",
        "   `os.path.exists`。清单里指向已删除文件的条目列在「失效条目」里，不算可用。",
        "",
        f'- 支持的类型：{len(summary["supported_categories"])} 个',
        f'- 本地可用文件：{summary["local_file_count"]} 个',
        f'- 失效条目：{len(summary["missing_files"])} 个',
        "",
        "## 支持的类型",
        "",
        "| category | 名称 | 建议轨道 | 本地文件数 | 用途 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in summary["supported_categories"]:
        lines.append(
            f'| `{item["key"]}` | {item["label"]} | `{item["track"]}` '
            f'| {counts.get(item["key"], 0)} | {item["description"]} |'
        )
    lines.append("")

    empty = summary["categories_without_local_file"]
    lines += [
        "本地一个文件都没有的类型："
        + ("无" if not empty else "、".join(f"`{k}`" for k in empty))
        + "。这不是 bug，是「支持但没素材」，导入音频到 `assets/audio/<category>/` 即可。",
        "",
    ]
    if summary["unknown_categories"]:
        lines += [
            "以下 category 本地有文件但分类表没登记，需要补进 `SFX_CATEGORIES`："
            + "、".join(f"`{k}`" for k in summary["unknown_categories"]),
            "",
        ]
    if summary["missing_files"]:
        lines += ["## 失效条目（清单里有、磁盘上没有）", ""]
        lines += [f"- `{path}`" for path in summary["missing_files"]]
        lines.append("")

    lines += ["## 本地文件清单", ""]
    for item in summary["supported_categories"]:
        rows = sounds.files(item["key"])
        lines += [f'### `{item["key"]}` · {item["label"]}（{len(rows)} 个）', ""]
        if not rows:
            lines += ["本地暂无文件。", ""]
            continue
        lines += ["| asset id | 文件 | 时长 |", "| --- | --- | --- |"]
        for asset in rows:
            duration = asset.get("duration") or 0
            lines.append(
                f'| `{asset.get("id","")}` | `{asset.get("path","")}` | {float(duration):.3f}s |'
            )
        lines.append("")

    lines += [
        "## 写进 Timeline JSON",
        "",
        "音效就是 `type=audio` 元素，靠轨道区分用途（BGM→A1，人声→A2，音效→A3）。",
        "`volume` 等于 1 时不写，`fade` 只写非零的那一侧——这是稀疏原则。",
        "",
    ]
    sample = sounds.first_of("impact") or sounds.first_of("ui")
    asset_id = str(sample.get("id")) if sample else "sfx_impact_001"
    lines += _json_block(tl.make_audio(
        "audio_001", asset_id, track="A3", start=1.2, duration=0.6,
        volume=0.8, fade_in=0.05, fade_out=0.15,
    ))
    lines += [
        "Remotion 侧由 `remotion/src/elements/AudioLayer.tsx` 执行：`volume` 是基础音量，",
        "`fade.in` / `fade.out` 换算成帧后用 volume 回调做线性淡入淡出。",
        "",
        "## 全局输出音量",
        "",
        f"`meta.master_volume` 是整片输出音量，缺省 {tl.DEFAULT_MASTER_VOLUME:g}（等于默认值时不落盘），"
        f"范围 {tl.MASTER_VOLUME_RANGE[0]:g}~{tl.MASTER_VOLUME_RANGE[1]:g}，0 = 整片静音。",
        "最终音量 = 元素 `volume` × fade 系数 × `meta.master_volume`。",
        "",
        "注意：预览窗口**没有音频通路**，所以播放器上的音量 / 静音控件调的是导出音量，",
        "改了以后预览听不出区别，要在渲染出的 MP4 上验证。",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------- Resolution


def build_resolution_guide() -> str:
    lines = [
        "# 分辨率与画面比例",
        "",
        GENERATED_BY,
        "",
        "唯一数据源：`core/resolution.py`。GUI 的比例 / 分辨率下拉、预览画布、",
        "导出的 `meta.width` / `meta.height` 全部从这里取，不允许各写一份。",
        "",
        f"- 默认比例：`{res.DEFAULT_ASPECT_ID}`",
        f"- 默认分辨率：{res.DEFAULT_RESOLUTION[0]}×{res.DEFAULT_RESOLUTION[1]}",
        f"- 比例识别容差：{res.ASPECT_TOLERANCE}",
        "",
        "## 档位",
        "",
        "| 比例 | 说明 | 分辨率档位 |",
        "| --- | --- | --- |",
    ]
    for aspect_id in res.aspect_ids():
        aspect = res.get_aspect(aspect_id)
        sizes = "、".join(f"{w}×{h}" for w, h in res.resolutions_for(aspect_id))
        lines.append(f'| `{aspect_id}` | {aspect["label"]} | {sizes} |')
    lines += [
        "",
        "## 联动规则",
        "",
        "- 换比例 → 分辨率跳到该比例的默认档（`default_resolution`，取 1080 宽的那一档）",
        "- 换分辨率 → 只有选「自定义」时宽高输入框才可编辑",
        "- 手填的宽高如果落在容差内，`aspect_of()` 仍然认得出比例；认不出就返回 None，",
        "  不猜、不强行归类",
        "",
        "## 一路传到 MP4",
        "",
        "```",
        "GUI 分辨率下拉 → TimelineModel.set_canvas() → JSON meta.width/height",
        "  → Remotion Composition 宽高 → MP4 → ffprobe 校验",
        "```",
        "",
        "预览画布同样按 `meta.width/height` 算目标矩形，所以安全区（Title 90% /",
        "Action 93%）在两种比例下都是对的。",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------- GUI guide


def build_gui_guide() -> str:
    lines = [
        "# 时间线 GUI 使用说明",
        "",
        GENERATED_BY,
        "",
        "键位来自 `gui/shortcuts.py`，坐标 / 缩放常量来自 `gui/timeline_coordinate.py`，",
        "磁吸阈值来自 `gui/timeline_snap.py`，落轨策略来自 `gui/asset_placement.py`。",
        "文档不重复定义任何数值。",
        "",
        "## 坐标系",
        "",
        "所有组件共用一份坐标换算（`TimelineCoordinate`）：",
        "",
        "- `time_to_x(t)` / `x_to_time(x)`，含 scroll 与轨道头宽度",
        "- 一次手势开始时对坐标系做快照，手势期间不受滚动 / 缩放变化影响",
        "- `grab_offset = 按下时的鼠标时间 - 元素 start`，整个拖动过程保持不变，",
        "  所以拖动只改 start，不改 duration",
        "- 帧量化（`snap_time`）永远是**最后一步**，磁吸算完再量化",
        "",
        "## 缩放",
        "",
        f'- 档位：{"、".join(f"{p:g}%" for p in PERCENT_STEPS)}',
        f"- 100% = {PPS_AT_100:g} px/s",
        "- `Ctrl + 滚轮` 以鼠标所在时间为锚点缩放，锚点在屏幕上不动",
        "- 下拉框选档位时以画布中心为锚点",
        "",
        "## 磁吸",
        "",
        f"- 阈值是**像素**：{SNAP_PIXELS:g}px，换算成时间再与 {MAX_SNAP_SECONDS:g}s 取小",
        "- 吸附目标：播放头、相邻片段的头 / 尾、时间 0、标记点",
        "- 头尾同时可吸时按距离竞争，谁近吸谁",
        f'- `{sc.display("toggle_snap")}` 开关磁吸',
        "",
        "## 素材落轨策略",
        "",
        "从素材库拖进时间线时，落到哪条轨道由策略表决定，GUI 里不再散落硬编码：",
        "",
        "| 素材角色 | 元素类型 | 默认轨道 | 备选轨道 | 避免重叠 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for role, policy in ap.POLICIES.items():
        lines.append(
            f"| {policy.label}（`{role}`） | `{policy.element_type}` | `{policy.default_track}` "
            f'| {"、".join(f"`{t}`" for t in policy.fallback_tracks) or "—"} '
            f'| {"是" if policy.avoid_overlap else "否"} |'
        )
    lines += [
        "",
        "- 默认轨道被占 → 顺延到备选轨道，**不覆盖**已有元素",
        "- 明确指定轨道（拖到某条轨道上）时以指定为准；类型不匹配或轨道锁定则拒绝并提示",
        "- 字幕 / 文字不做顺延：同轨叠字是正常需求",
        "",
        "## 标记",
        "",
        "标记以兼容扩展的方式存在 `meta.markers`：Remotion 不读它，为空时整个字段不写，",
        "v1 / v2 schema 都显式允许。类型：",
        "",
        "| type | 名称 |",
        "| --- | --- |",
    ]
    for key in mk.MARKER_TYPES:
        lines.append(f'| `{key}` | {mk.MARKER_TYPES[key]["label"]} |')
    lines += ["", "## 快捷键", ""]
    for group, actions in sc.GROUPS:
        lines += [f"### {group}", "", "| 键位 | 作用 |", "| --- | --- |"]
        for action in actions:
            lines.append(f'| `{sc.display(action)}` | {sc.LABELS.get(action, action)} |')
        lines.append("")
    lines += ["### 鼠标操作", "", "| 操作 | 作用 |", "| --- | --- |"]
    for gesture, effect in sc.MOUSE_TIPS:
        lines.append(f"| {gesture} | {effect} |")
    lines += [
        "",
        "## 拖动过程中不会发生的事",
        "",
        "拖动 / 裁剪只碰 GUI 与 `TimelineModel`：不解码视频、不调 FFmpeg、不起 Remotion、",
        "不请求任何 AI 接口。一次手势结束才提交一条模型记录（也就是一步 Undo）。",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------- JSON examples


def _example_timelines(sounds: SoundLibrary) -> List[Tuple[str, str, Dict[str, Any]]]:
    """构造示例。全部用 `core/timeline.py` 的 make_* 造，再走稀疏序列化。"""
    sfx = sounds.first_of("impact") or sounds.first_of("ui")
    sfx_id = str(sfx.get("id")) if sfx else "sfx_impact_001"
    bgm = sounds.first_of("bgm")
    bgm_id = str(bgm.get("id")) if bgm else "sfx_bgm_001"

    def base(name: str, duration: float, width: int = 1080, height: int = 1920) -> Dict[str, Any]:
        timeline = tl.empty_timeline(name=name, width=width, height=height)
        timeline["meta"]["duration"] = duration
        return timeline

    examples: List[Tuple[str, str, Dict[str, Any]]] = []

    single = base("single_video", 4.0)
    single["elements"] = [tl.make_video("clip_001", "video_001", "V1", 0.0, 0.0, 4.0)]
    examples.append((
        "最小单视频",
        "只有一个片段。没有 `speed`、没有 `volume`、没有 `transform`、没有 `keyframes`——"
        "缺省就是默认值，写出来只是噪声。",
        single,
    ))

    two = base("two_clips_transition", 6.0)
    two["elements"] = [
        tl.make_video("clip_001", "video_001", "V1", 0.0, 0.0, 3.0),
        tl.make_video("clip_002", "video_002", "V1", 2.5, 0.0, 3.5),
        tl.make_transition("transition_001", "whip", "clip_001", "clip_002", 2.5, 0.5, {}, "V1"),
    ]
    examples.append((
        "两段视频 + 转场",
        "转场窗口必须落在两个片段的重叠区间内；`params` 为空表示全用注册表默认值。",
        two,
    ))

    effect = base("video_with_effect", 4.0)
    effect["elements"] = [
        tl.make_video("clip_001", "video_001", "V1", 0.0, 0.0, 4.0),
        tl.make_effect("effect_001", "zoom", {"scale_to": 1.5}, "V1", 1.0, 0.6, target="clip_001"),
    ]
    examples.append((
        "视频 + 特效",
        "程序特效用 `type=effect`，靠 `target` 绑定被作用的片段；`params` 只写和默认值不同的项。",
        effect,
    ))

    audio = base("video_with_sfx", 4.0)
    audio["elements"] = [
        tl.make_video("clip_001", "video_001", "V1", 0.0, 0.0, 4.0),
        tl.make_audio("audio_001", bgm_id, "A1", 0.0, 4.0, volume=0.35, fade_in=0.3, fade_out=0.5),
        tl.make_audio("audio_002", sfx_id, "A3", 1.0, 0.6, volume=0.9),
    ]
    examples.append((
        "视频 + BGM + 音效",
        "BGM 在 A1、音效在 A3；`fade` 只写非零的一侧，`volume` 等于 1 时不写。",
        audio,
    ))

    full = base("full_combo", 6.0)
    full["elements"] = [
        tl.make_video("clip_001", "video_001", "V1", 0.0, 0.0, 3.0),
        tl.make_video("clip_002", "video_002", "V1", 2.6, 0.0, 3.4),
        tl.make_transition("transition_001", "crossfade", "clip_001", "clip_002", 2.6, 0.4, {}, "V1"),
        tl.make_overlay("overlay_001", "overlay_arrow_001", "V3", 1.0, 1.5),
        tl.make_text("text_001", "标题", "T2", 0.2, 2.0),
        tl.make_caption("caption_001", "这是一条字幕", "T1", 1.0, 2.5),
        tl.make_effect("effect_001", "shake", {}, "V1", 2.4, 0.4, target="clip_001"),
        tl.make_audio("audio_001", bgm_id, "A1", 0.0, 6.0, volume=0.3, fade_out=0.8),
        tl.make_audio("audio_002", sfx_id, "A3", 2.6, 0.6),
    ]
    full["meta"]["markers"] = [
        {"time": 2.6, "type": "transition"},
        {"time": 4.0, "type": "highlight", "label": "高光"},
    ]
    examples.append((
        "全类型组合",
        "视频 + 转场 + 叠加 + 文字 + 字幕 + 特效 + BGM + 音效，外加两个标记点。"
        "标记写在 `meta.markers`，Remotion 会忽略它。",
        full,
    ))
    return examples


def build_json_examples(sounds: SoundLibrary) -> str:
    validator = TimelineValidator(os.path.join(ROOT, "schemas"))
    lines = [
        "# Timeline JSON 示例",
        "",
        GENERATED_BY,
        "",
        "示例不是手写的：全部由 `core/timeline.py` 的 `make_*` 构造，再经",
        "`core/sparse.py` 序列化，最后过一遍 `TimelineValidator`。",
        "所以「示例语法过时了」这件事不可能发生。",
        "",
        "## 协议要点",
        "",
        "- Timeline JSON 表达的是**剪辑意图**；怎么画由 Remotion 决定。AI 只产 JSON，永不产 TSX。",
        "- **稀疏**：字段等于 Runtime 默认值就不写。`speed=1`、`volume=1`、全默认 `transform`、",
        "  空 `keyframes` 都属于噪声。",
        "- 时间单位是秒（`time_unit=seconds`），帧数由 `meta.fps` 换算。",
        "- `asset` 写的是 asset id，导出时会连同 `remotion/asset_manifest.json` 一起带过去。",
        "- `meta.width` / `meta.height` 决定画布，见 `RESOLUTION_GUIDE.md`。",
        "",
    ]
    for title, note, timeline in _example_timelines(sounds):
        payload = sparse.sparse_timeline(timeline)
        report = validator.validate_report(timeline)
        errors = [i for i in report.get("issues", []) if i.get("level") == "error"]
        verdict = "校验通过（0 error）" if not errors else (
            "校验有 error：" + "；".join(str(i.get("message")) for i in errors)
        )
        lines += [f"## {title}", "", note, "", f"- 校验结果：{verdict}", ""]
        lines += _json_block(payload)
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------- AI catalog


def build_ai_catalog(effects, transitions, sounds: SoundLibrary,
                     runtime: Optional[Dict[str, Any]], note: str) -> Dict[str, Any]:
    def param_payload(params) -> List[Dict[str, Any]]:
        out = []
        for param in params:
            row = {k: v for k, v in dict(param).items() if v is not None}
            out.append(row)
        return out

    return {
        "version": 1,
        "generated_by": "tools/build_catalog.py",
        "purpose": "AI 生成 Timeline JSON 时的唯一能力清单：这里没有的能力就是没有。",
        "contract": {
            "ai_outputs": "Timeline JSON only",
            "ai_never_outputs": "TSX / React / 渲染代码",
            "time_unit": tl.TIME_UNIT,
            "schema_version": tl.SCHEMA_VERSION,
            "sparse_rule": "字段等于 Runtime 默认值就不要写",
            "defaults": {
                "transform": tl.DEFAULT_TRANSFORM,
                "speed": tl.DEFAULT_SPEED,
                "volume": tl.DEFAULT_VOLUME,
                "audio": tl.DEFAULT_AUDIO,
                "fade": tl.DEFAULT_FADE,
                "background": tl.DEFAULT_BACKGROUND,
                "master_volume": tl.DEFAULT_MASTER_VOLUME,
            },
        },
        "renderer_discovery": {
            "note": note,
            "runtime_effects": None if runtime is None else [
                e.get("name") for e in runtime.get("effects", [])
            ],
            "runtime_transitions": None if runtime is None else runtime.get("transitions"),
        },
        "element_types": tl.ELEMENT_TYPE_LABELS,
        "tracks": {
            "presets": tl.DEFAULT_TRACKS,
            "display_order": tl.TRACK_DISPLAY_ORDER,
            "type_to_kind": tl.TYPE_TRACK_KIND,
        },
        "placement_policy": {
            role: {
                "element_type": policy.element_type,
                "default_track": policy.default_track,
                "fallback_tracks": list(policy.fallback_tracks),
                "avoid_overlap": policy.avoid_overlap,
                "label": policy.label,
            }
            for role, policy in ap.POLICIES.items()
        },
        "effects": [
            {
                "name": d.name,
                "label": d.display_name,
                "kind": d.get("kind", "program"),
                "category": d.category,
                "display_category": d.display_category,
                "renderer": d.renderer,
                "default_duration": d.default_duration,
                "supported_targets": list(d.get("supported_targets", [])),
                "description": d.description,
                "params": param_payload(d.get("params", [])),
            }
            for d in sorted(effects.all(), key=lambda d: (d.category, d.name))
        ],
        "transitions": [
            {
                "name": d.name,
                "label": d.display_name,
                "category": d.category,
                "display_category": d.display_category,
                "renderer": d.renderer,
                "default_duration": d.default_duration,
                "supported_from": d.supported_from,
                "supported_to": d.supported_to,
                "description": d.description,
                "params": param_payload(d.get("params", [])),
            }
            for d in sorted(transitions.all(), key=lambda d: (d.category, d.name))
        ],
        "sound_effects": {
            "supported_categories": sounds.categories(),
            "local_files": [
                {
                    "id": a.get("id"),
                    "category": a.get("category"),
                    "path": a.get("path"),
                    "duration": a.get("duration"),
                }
                for a in sounds.files()
            ],
            "count_by_category": sounds.count_by_category(),
            "missing_files": sounds.summary()["missing_files"],
            "element_shape": tl.make_audio(
                "audio_001", "<asset id>", track="A3", start=0.0, duration=0.6,
                volume=0.8, fade_in=0.05, fade_out=0.1,
            ),
        },
        "resolutions": {
            "default_aspect": res.DEFAULT_ASPECT_ID,
            "default_resolution": list(res.DEFAULT_RESOLUTION),
            "aspects": [
                {
                    "id": aspect_id,
                    "label": res.label_of(aspect_id),
                    "ratio": list(res.get_aspect(aspect_id)["ratio"]),
                    "default": list(res.default_resolution(aspect_id)),
                    "resolutions": [list(size) for size in res.resolutions_for(aspect_id)],
                    "tiers": [res.tier_of(w, h) for w, h in res.resolutions_for(aspect_id)],
                }
                for aspect_id in res.aspect_ids()
            ],
        },
        "markers": {
            "location": "meta.markers",
            "note": "兼容扩展：Remotion 忽略；为空时不写该字段",
            "types": mk.MARKER_TYPES,
        },
        "docs": {
            "effects": "docs/EFFECT_CATALOG.md",
            "transitions": "docs/TRANSITION_CATALOG.md",
            "sound_effects": "docs/SOUND_EFFECT_CATALOG.md",
            "resolutions": "docs/RESOLUTION_GUIDE.md",
            "gui": "docs/TIMELINE_GUI_GUIDE.md",
            "json_examples": "docs/TIMELINE_JSON_EXAMPLES.md",
        },
    }


# ---------------------------------------------------------------- 阶段十四新增
#
# 这一段负责三份「AI 只准照着这个来」的文件：
#
#   docs/SFX_CATALOG.{md,json}      音效能力清单（AI 只能从里面挑）
#   docs/AI_CAPABILITIES.{md,json}  能力白名单总表
#   docs/AI_SYSTEM_PROMPT.md        直接可粘给模型的系统提示
#
# 三份都从**真实注册表**生成，不手写第二份数据。


def _json_payload(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def build_sfx_catalog_json(registry: AssetRegistry) -> Dict[str, Any]:
    """音效清单（指令第八条的形状）：id / name / path / duration / category / tags。"""
    rows: List[Dict[str, Any]] = []
    for record in registry.search(semantic="sfx"):
        row = {
            "id": record["id"],
            "name": record["name"],
            "path": record["path"],
            "category": record["category"],
            "tags": record["tags"],
        }
        if record.get("duration"):
            row["duration"] = record["duration"]
        rows.append(row)
    categories = sorted({r["category"] for r in rows if r["category"]})
    return {
        "version": 1,
        "note": "AI 只能从本清单里挑音效；编造 asset id 会被 RULE_ASSET_001 拦下",
        "total": len(rows),
        "categories": [
            {
                "key": key,
                "count": sum(1 for r in rows if r["category"] == key),
                "default_track": "A3",
            }
            for key in categories
        ],
        "element_shape": {
            "type": "audio",
            "track": "A3",
            "asset": "<清单里的 id>",
            "start": 12.3,
            "duration": 0.8,
        },
        "sound_effects": rows,
    }


def build_sfx_catalog_md(payload: Dict[str, Any], registry: AssetRegistry) -> str:
    lines = [
        "# 音效能力清单 SFX Catalog",
        "",
        GENERATED_BY,
        "",
        f"共 {payload['total']} 个音效，{len(payload['categories'])} 个分类。",
        "全部落在 `A3 音效` 轨；AI 只能从本清单挑，编造 id 会被 `RULE_ASSET_001` 拦下。",
        "",
        "## 分类总览",
        "",
        "| 分类 | 数量 | 默认轨道 |",
        "| --- | --- | --- |",
    ]
    for row in payload["categories"]:
        lines.append(f"| `{row['key']}` | {row['count']} | `{row['default_track']}` |")
    lines.append("")
    lines.append("## 逐条清单")
    lines.append("")
    for category in payload["categories"]:
        key = category["key"]
        lines.append(f"### `{key}`（{category['count']} 个）")
        lines.append("")
        lines.append("| id | 文件 | 时长 | 标签 |")
        lines.append("| --- | --- | --- | --- |")
        for row in payload["sound_effects"]:
            if row["category"] != key:
                continue
            duration = f"{row['duration']:.2f}s" if row.get("duration") else "—"
            lines.append(
                f"| `{row['id']}` | `{row['path']}` | {duration} | "
                f"{' '.join(f'`{t}`' for t in row['tags'])} |"
            )
        lines.append("")
    missing = registry.missing_files()
    lines.append("## 完整性")
    lines.append("")
    lines.append(
        f"清单里的文件全部经过磁盘存在性检查：缺失 {len(missing)} 个。"
        if not missing
        else f"**缺失 {len(missing)} 个文件**：" + ", ".join(m["id"] for m in missing)
    )
    lines.append("")
    return "\n".join(lines)


def build_ai_capabilities(
    media: Dict[str, Any],
    effects: EffectLibrary,
    transitions: TransitionLibrary,
    registry: AssetRegistry,
    sfx: Dict[str, Any],
) -> Dict[str, Any]:
    """AI 能力白名单（指令第九、三十条）。

    `media` 直接复用 AI_MEDIA_CATALOG.json 的内容 —— 不另写一份元素 / 特效 /
    转场的描述，否则两份数据必然漂移。本函数只负责把「AI 视角还缺的部分」补上：
    动作白名单、规则、安全区、语音 provider、素材统计、示例库。
    """
    return {
        "version": 1,
        "note": (
            "AI 剪辑能力白名单。AI 只能使用这里列出的能力与参数；"
            "凡是这里没有的特效 / 转场 / 音效 / 动作，一律视为非法。"
        ),
        "contract": media.get("contract", {}),
        "pipeline": [
            "AI 输出 EditingDecision（做什么 / 什么时候 / 多久 / 为什么）",
            "core/editing_planner.py 展开成 Timeline 元素",
            "core/timeline_validator.py 校验（Schema + 语义 + Registry + Rule Engine）",
            "Remotion Runtime 渲染成 MP4",
            "ffprobe / 抽帧 / 音频探针验收",
        ],
        "media": media,
        "actions": {
            "note": "AI 只能表达这些动作；未列出的动作会被 Planner 报 UNKNOWN_ACTION",
            "whitelist": list(ACTIONS),
            "detail": action_catalog(),
            "schema": "schemas/editing_decision_schema.json",
            "contract": (
                "AI 的输出**只能**是 EditingDecision 列表（{\"decisions\": [...]}），"
                "不是 Timeline JSON，不是 TSX，也不是 ffmpeg 命令行。"
                "Timeline JSON 由 EditingPlanner 生成，由 TimelineValidator 判定"
            ),
            "decision_shape": {
                "action": "zoom",
                "target": "clip_003",
                "start": 12.4,
                "duration": 0.6,
                "parameters": {"scale_to": 1.2},
                "reason": "强调反应瞬间",
                "confidence": 0.8,
            },
            "runtime_ignores": ["reason", "confidence", "decision_id"],
            "provenance": (
                "reason / confidence / 输入引用写进 decisions.json（core/provenance.py），"
                "不进 timeline.json —— 删掉它渲染结果一模一样"
            ),
        },
        "rules": {
            "note": "校验规则全表。level=error 会阻止导出，warning 只提示",
            "source": "schemas/rules.json",
            "items": rules_mod.rule_catalog(RULES_PATH),
            "max_clip_seconds": rules_mod.MAX_CLIP_SECONDS,
            "closing_clip_exempt": rules_mod.CLOSING_CLIP_EXEMPT,
        },
        "safe_area": {
            "note": (
                "安全区是**排版约束**：字幕 / 文字 / 叠加素材越界会被 RULE_SAFE_AREA_002 "
                "提示（warning），显式写 safe_area: true 的元素越界是 RULE_SAFE_AREA_001 "
                "（error）。内缩比例是各平台界面的实测估算值，不是平台官方规范；"
                "Remotion 不读它，既不会画出安全框，也不会在渲染时偷偷挪位置 —— "
                "要收位就显式调 clamp_to_safe_area()，结果写回 transform"
            ),
            "location": "meta.safe_area",
            "default": safe.DEFAULT_PRESET_ID,
            "version": safe.PRESET_VERSION,
            "source": safe.PRESET_SOURCE,
            "constrained_types": list(safe.CONSTRAINED_TYPES),
            "meta_shape": safe.preset_meta("tiktok"),
            "presets": safe.catalog(),
        },
        "voice": {
            "note": (
                "配音走 VoiceProvider 抽象，不绑定任何一家 TTS。"
                "timing_source=estimated 表示逐词时间戳是按字符比例估算的，不是引擎给的"
            ),
            "params": list(voice_mod.VOICE_PARAMS),
            "styles": list(voice_mod.STYLES),
            "languages": list(voice_mod.PRIMARY_LANGUAGES),
            "genders": list(voice_mod.GENDERS),
            "providers": voice_mod.catalog(),
        },
        "assets": {
            "note": "素材语义类型与建议轨道。AI 只能引用清单里已有的 asset id",
            "summary": registry.summary(),
            "sfx_categories": [row["key"] for row in sfx["categories"]],
        },
        "resolutions": media.get("resolutions", {}),
        "examples": {
            "note": "tests/fixtures/ 下每份都过校验、且每轮验收都真实渲染成 MP4",
            "fixtures": sorted(
                os.path.splitext(f)[0]
                for f in os.listdir(os.path.join(ROOT, "tests", "fixtures"))
                if f.endswith(".json")
            )
            if os.path.isdir(os.path.join(ROOT, "tests", "fixtures"))
            else [],
        },
    }


def build_ai_capabilities_md(payload: Dict[str, Any]) -> str:
    media = payload["media"]
    effects = media.get("effects") or []
    transitions = media.get("transitions") or []
    program = [e for e in effects if e.get("kind") == "program"]
    material = [e for e in effects if e.get("kind") != "program"]
    lines = [
        "# AI 剪辑能力白名单 AI_CAPABILITIES",
        "",
        GENERATED_BY,
        "",
        "> AI 只能使用本文件列出的能力与参数。**没列的就是不存在的**：",
        "> 未注册的特效 / 转场会被 Validator 报错，编造的 asset id 会被拦下，",
        "> 白名单外的动作会被 Editing Planner 报 `UNKNOWN_ACTION`。",
        "",
        "## 链路",
        "",
    ]
    for index, step in enumerate(payload["pipeline"], start=1):
        lines.append(f"{index}. {step}")
    lines += ["", "## 动作白名单", "", "| 动作 | 说明 | 需要 target | 备注 |",
              "| --- | --- | --- | --- |"]
    for row in payload["actions"]["detail"]:
        extra: List[str] = []
        if row.get("expands_to"):
            extra.append("展开为 " + " + ".join(f"`{s}`" for s in row["expands_to"]))
        if row.get("requires_registry_name"):
            extra.append("name 必须在 Registry 里")
        if row.get("requires_asset"):
            extra.append("必须给 asset")
        lines.append(
            f"| `{row['action']}` | {row['label']} | "
            f"{'是' if row['requires_target'] else '否'} | {'；'.join(extra) or '—'} |"
        )
    lines += ["", "决策形状：", ""] + _json_block(payload["actions"]["decision_shape"])

    lines += ["", "## 元素类型", "", "| type | 说明 |", "| --- | --- |"]
    for key, label in (media.get("element_types") or {}).items():
        lines.append(f"| `{key}` | {label} |")

    lines += [
        "",
        "## 特效 / 转场",
        "",
        f"- 程序特效 {len(program)} 个，素材特效 {len(material)} 个"
        " —— 逐条参数见 `EFFECT_CATALOG.md`",
        f"- 转场 {len(transitions)} 个 —— 逐条参数见 `TRANSITION_CATALOG.md`",
        f"- 音效 {payload['assets']['summary']['by_type'].get('sfx', 0)} 个 —— "
        "逐条清单见 `SFX_CATALOG.md`",
        "",
        "## 画面比例",
        "",
        "| 比例 | 默认分辨率 | 可选档位 |",
        "| --- | --- | --- |",
    ]
    for aspect in (payload["resolutions"].get("aspects") or []):
        options = "、".join(f"{w}×{h}" for w, h in aspect.get("resolutions", []))
        default = aspect.get("default") or []
        lines.append(
            f"| `{aspect['id']}` | "
            f"{f'{default[0]}×{default[1]}' if default else '—'} | {options} |"
        )

    lines += ["", "## 安全区", "", payload["safe_area"]["note"], "",
              f"数值版本 v{payload['safe_area']['version']}"
              f"（来源：{payload['safe_area']['source']} / 实测估算）。"
              f"受约束的元素类型：{', '.join(payload['safe_area']['constrained_types'])}。", "",
              "| 档位 | 说明 | x 范围 | y 范围 |", "| --- | --- | --- | --- |"]
    for preset in payload["safe_area"]["presets"]:
        box = preset["box"]
        lines.append(
            f"| `{preset['id']}` | {preset['note']} | "
            f"{box['left']:.2f} ~ {box['right']:.2f} | {box['top']:.2f} ~ {box['bottom']:.2f} |"
        )

    lines += ["", "## 规则", "", payload["rules"]["note"],
              f"（普通片段上限 {payload['rules']['max_clip_seconds']:g}s，"
              f"收尾片段豁免：{'是' if payload['rules']['closing_clip_exempt'] else '否'}）",
              "", "| 规则 | 级别 | 说明 |", "| --- | --- | --- |"]
    for rule in payload["rules"]["items"]:
        level = {"error": "错误", "warning": "警告"}.get(rule["level"], rule["level"])
        suffix = "（豁免条件）" if rule["kind"] == "exemption" else ""
        lines.append(f"| `{rule['id']}` | {level} | {rule['description']}{suffix} |")

    lines += ["", "## 配音", "", payload["voice"]["note"], "",
              "| provider | 逐词时间戳 | 支持参数 |", "| --- | --- | --- |"]
    for provider in payload["voice"]["providers"]:
        lines.append(
            f"| `{provider['id']}` | "
            f"{'引擎提供' if provider['supports_word_timestamps'] else '估算'} | "
            f"{' '.join(f'`{p}`' for p in provider['supported_params'])} |"
        )

    lines += ["", "## 示例库", "", payload["examples"]["note"], ""]
    for name in payload["examples"]["fixtures"]:
        lines.append(f"- `tests/fixtures/{name}.json`")
    lines.append("")
    return "\n".join(lines)


def build_ai_system_prompt(payload: Dict[str, Any], effects: EffectLibrary,
                          transitions: TransitionLibrary) -> str:
    """可直接粘给模型的系统提示（指令第四十八条）。"""
    program = sorted(d.name for d in effects.all() if d.element_type == "effect")
    material = sorted(d.name for d in effects.all() if d.element_type != "effect")
    lines = [
        "# AI 剪辑系统提示 AI_SYSTEM_PROMPT",
        "",
        GENERATED_BY,
        "",
        "把以下内容作为系统提示交给模型。所有清单都是从真实注册表生成的，",
        "改了注册表就重新跑生成器，不要手改本文件。",
        "",
        "---",
        "",
        "你是一个短视频剪辑决策器。你的输出**只能**是 JSON 决策列表，",
        "不允许输出 TSX / React / 任何渲染代码，也不允许直接编辑 Timeline JSON。",
        "",
        "## 你的输出格式",
        "",
    ]
    lines += _json_block(
        {
            "decisions": [
                payload["actions"]["decision_shape"],
                {
                    "action": "highlight",
                    "start": 24.0,
                    "params": {"text": "LOOK AT THIS"},
                    "reason": "情绪最高点，需要强调",
                },
            ]
        }
    )
    lines += [
        "",
        "## 你能做的动作",
        "",
        "".join(f"`{a}` " for a in payload["actions"]["whitelist"]).strip(),
        "",
        "`highlight` 会被自动展开为："
        + " + ".join(f"`{s}`" for s in
                     next(r for r in payload["actions"]["detail"]
                          if r["action"] == "highlight")["expands_to"]),
        "",
        "## 你能用的程序特效（写在 params.name）",
        "",
        " ".join(f"`{n}`" for n in program),
        "",
        "以下是**素材特效**，必须用 `overlay` 动作，不能当程序特效：",
        "",
        " ".join(f"`{n}`" for n in material) or "（无）",
        "",
        "## 你能用的转场（写在 params.name）",
        "",
        " ".join(f"`{n}`" for n in sorted(transitions.names())),
        "",
        "## 你能用的音效分类",
        "",
        " ".join(f"`{c}`" for c in payload["assets"]["sfx_categories"]),
        "",
        "具体 id 见 `docs/SFX_CATALOG.json`。不给 asset 时系统会按分类自动挑一个。",
        "",
        "## 硬性规则",
        "",
        "1. 时间单位一律是**秒**，不要出现帧。",
        "2. 不要发明特效 / 转场 / 音效 / 动作名，也不要发明参数名。",
        f"3. 普通片段不要超过 {payload['rules']['max_clip_seconds']:g} 秒"
        "（每条轨最后一个收尾片段除外）。",
        "4. 需要摆位置的元素（字幕 / 标题 / 贴纸）如果要求不被平台 UI 压住，",
        "   在 params 里写 `safe_area: true`，系统会自动收进安全区。",
        "5. 每条决策都要写 `reason`，说明为什么这么剪。",
        "6. 参数取值必须落在能力表给的范围内；超范围会被 Validator 拦下。",
        "",
        "## 完整能力表",
        "",
        "见 `docs/AI_CAPABILITIES.json`（机器读）与 `docs/AI_CAPABILITIES.md`（人读）。",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- main



def build_all() -> Dict[str, str]:
    effects = EffectLibrary(ASSETS_DIR)
    transitions = TransitionLibrary(ASSETS_DIR)
    sounds = SoundLibrary.from_manifest(MANIFEST)
    registry = AssetRegistry.from_manifest(MANIFEST)
    runtime, note = discover_renderers()
    catalog = build_ai_catalog(effects, transitions, sounds, runtime, note)
    sfx = build_sfx_catalog_json(registry)
    capabilities = build_ai_capabilities(catalog, effects, transitions, registry, sfx)
    return {
        "EFFECT_CATALOG.md": build_effect_catalog(effects, runtime, note, registry),
        "TRANSITION_CATALOG.md": build_transition_catalog(transitions, runtime, note),
        "SOUND_EFFECT_CATALOG.md": build_sound_catalog(sounds),
        "RESOLUTION_GUIDE.md": build_resolution_guide(),
        "TIMELINE_GUI_GUIDE.md": build_gui_guide(),
        "TIMELINE_JSON_EXAMPLES.md": build_json_examples(sounds),
        "AI_MEDIA_CATALOG.json": _json_payload(catalog),
        "EFFECT_CATALOG.json": _json_payload(effects.export_definitions()),
        "TRANSITION_CATALOG.json": _json_payload(transitions.export_definitions()),
        "SFX_CATALOG.json": _json_payload(sfx),
        "SFX_CATALOG.md": build_sfx_catalog_md(sfx, registry),
        "AI_CAPABILITIES.json": _json_payload(capabilities),
        "AI_CAPABILITIES.md": build_ai_capabilities_md(capabilities),
        "AI_SYSTEM_PROMPT.md": build_ai_system_prompt(capabilities, effects, transitions),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="生成 docs/ 下的能力目录")
    parser.add_argument("--check", action="store_true", help="只比对，不写文件")
    args = parser.parse_args(argv)

    payloads = build_all()
    os.makedirs(DOCS, exist_ok=True)
    drifted: List[str] = []
    for filename, content in payloads.items():
        path = os.path.join(DOCS, filename)
        current = None
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                current = handle.read()
        if current == content:
            print(f"OK    {filename}")
            continue
        drifted.append(filename)
        if args.check:
            print(f"DRIFT {filename}")
            continue
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        print(f"WRITE {filename}")
    if args.check and drifted:
        print(f"FAIL 有 {len(drifted)} 个文件与当前仓库状态不一致，请重新生成")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
