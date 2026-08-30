"""生成 tests/fixtures/ 下的示例 Timeline JSON，并产出真实渲染批次。

指令第四十九、五十条要的是一套**能过校验、能真出片**的示例库：

    python tools/build_fixtures.py build   # 生成 JSON + 校验 + 写渲染批次
    python tools/build_fixtures.py check   # 只校验已有 fixture，不改文件
    python tools/build_fixtures.py probe   # 对已渲染的 MP4 做 ffprobe / 黑帧 / 抽帧 / 音频探针

设计要点：

- 素材只用仓库里**真实存在**的文件（out/demo.mp4、out/demo1.mp4、真实音效 /
  overlay / TTS 配音），不造纯色视频冒充素材（指令第五十一条）。
- 每份 fixture 都过一遍 `TimelineModel`，落盘的就是 canonical **稀疏** JSON ——
  fixture 自己就是「稀疏原则」的活样本，谁往里塞默认字段，
  tests/test_fixtures.py 会红。
- 时长刻意短（2~4 秒）：这套 fixture 是要**每次都真渲**的，
  长了就没人愿意跑，验收也就变成纸面工作。
- 渲染批次写到 out/acceptance/logs/fixtures_batch.json，
  由 out/acceptance/render_batch.mjs 真实渲染成 MP4。
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import sys
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCEPTANCE = os.path.join(ROOT, "out", "acceptance")
for path in (ROOT, ACCEPTANCE):
    if path not in sys.path:
        sys.path.insert(0, path)

import harness  # noqa: E402  out/acceptance/harness.py
import analyze  # noqa: E402  out/acceptance/analyze.py（复用已验证的抽帧 / 度量通道）

from core import safe_area as sa  # noqa: E402
from core import timeline as tl  # noqa: E402
from core.timeline_model import TimelineModel  # noqa: E402
from core.timeline_validator import TimelineValidator  # noqa: E402
from core.undo_manager import UndoManager  # noqa: E402
from libraries.asset_library import Libraries  # noqa: E402

FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures")
RENDER_DIR = os.path.join(ACCEPTANCE, "render", "fixtures")
BATCH_PATH = os.path.join(ACCEPTANCE, "logs", "fixtures_batch.json")
MANIFEST_PATH = os.path.join(ACCEPTANCE, "logs", "fixtures_manifest.json")
PROBE_PATH = os.path.join(ACCEPTANCE, "logs", "fixtures_probe.json")

FPS = 30
#: 特征 fixture 的画布：小一点是为了让「每次都真渲」可行
CANVAS = (540, 960)

#: fixture 用到的真实素材。id 是 fixture JSON 里写的 asset id，
#: path 是 remotion/public 下的相对路径（与 RemotionExporter 同一规则）。
ASSETS: Dict[str, Dict[str, str]] = {
    "demo": {
        "src": os.path.join(ROOT, "out", "demo.mp4"),
        "path": "assets/acceptance/demo.mp4",
        "type": "video",
    },
    "demo1": {
        "src": os.path.join(ROOT, "out", "demo1.mp4"),
        "path": "assets/acceptance/demo1.mp4",
        "type": "video",
    },
    "arrow_red": {
        "src": os.path.join(ROOT, "assets", "overlays", "arrow", "arrow_red.png"),
        "path": "assets/overlays/arrow/arrow_red.png",
        "type": "image",
    },
    "ov_flash": {
        "src": os.path.join(ROOT, "assets", "transitions", "flash", "flash_white.webm"),
        "path": "assets/transitions/flash/flash_white.webm",
        "type": "video",
    },
    "bgm_demo": {
        "src": os.path.join(ROOT, "assets", "audio", "bgm", "bgm_demo.wav"),
        "path": "assets/audio/bgm/bgm_demo.wav",
        "type": "audio",
    },
    "sfx_impact": {
        "src": os.path.join(ROOT, "assets", "audio", "impact", "impact_01.wav"),
        "path": "assets/audio/impact/impact_01.wav",
        "type": "audio",
    },
    "sfx_whoosh": {
        "src": os.path.join(ROOT, "assets", "audio", "whoosh", "whoosh_short_01.wav"),
        "path": "assets/audio/whoosh/whoosh_short_01.wav",
        "type": "audio",
    },
    "voice_demo": {
        "src": os.path.join(
            ROOT, "assets", "audio", "tts", "tts_20260830_115834_啊啊啊啊.wav"
        ),
        "path": "assets/audio/tts/voice_demo.wav",
        "type": "audio",
    },
}


# ---------------------------------------------------------------- 素材清单


def asset_entry(asset_id: str) -> Optional[Dict[str, Any]]:
    """探一个素材的真实参数。文件不存在就返回 None —— 缺素材如实缺，不编。"""
    spec = ASSETS.get(asset_id)
    if not spec or not os.path.isfile(spec["src"]):
        return None
    info = harness.probe_media(spec["src"])
    video = info.get("video") or {}
    entry = {
        "id": asset_id,
        "name": os.path.basename(spec["src"]),
        "type": spec["type"],
        "path": spec["path"],
        "duration": round(info.get("duration", 0.0), 3),
    }
    if video.get("width"):
        entry["width"] = video["width"]
        entry["height"] = video["height"]
        entry["fps"] = video.get("fps", 0)
    return entry


def build_manifest() -> Dict[str, Any]:
    assets = [a for a in (asset_entry(i) for i in ASSETS) if a]
    return {"version": 1, "assets": assets}


def copy_assets(manifest: Dict[str, Any]) -> List[str]:
    """拷进 remotion/public/<asset.path>。源文件只读。"""
    copied: List[str] = []
    for asset in manifest["assets"]:
        src = ASSETS[asset["id"]]["src"]
        target = os.path.join(harness.PUBLIC_DIR, asset["path"].replace("/", os.sep))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.isfile(target) and os.path.getmtime(target) >= os.path.getmtime(src):
            continue
        shutil.copy2(src, target)
        copied.append(asset["path"])
    return copied


# ---------------------------------------------------------------- 构造工具


def canonical(name: str, elements: List[Dict[str, Any]], canvas=CANVAS,
              meta_extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """装进时间线并过一遍 TimelineModel，得到 canonical 稀疏 JSON。"""
    data = tl.empty_timeline(name, fps=FPS, width=canvas[0], height=canvas[1])
    data["elements"] = elements
    if meta_extra:
        data["meta"].update(meta_extra)
    model = TimelineModel(UndoManager())
    model.from_dict(data, f"fixture {name}")
    return model.to_dict()


def clip(element_id: str, asset: str, start: float, source_start: float,
         source_end: float, track: str = "V1", **extra) -> Dict[str, Any]:
    element = tl.make_video(element_id, asset, track, start=start,
                            source_start=source_start, source_end=source_end)
    element.update(extra)
    return element


# ---------------------------------------------------------------- 各 fixture


def fx_basic_video() -> Dict[str, Any]:
    """一条最简单的时间线：导入 demo.mp4，什么都没改。

    这份 fixture 同时是**稀疏原则的基准**（指令第二十九条）：
    除了 id / type / track / asset / start / duration / source，
    不许出现 transform / speed / audio / keyframes / params / fade。
    """
    return canonical("基础单视频", [clip("clip_001", "demo", 0.0, 0.0, 3.0)])


def fx_dual_video() -> Dict[str, Any]:
    return canonical(
        "双视频顺接",
        [
            clip("clip_001", "demo", 0.0, 0.0, 2.0),
            clip("clip_002", "demo1", 2.0, 0.0, 2.0),
        ],
    )


def fx_overlay() -> Dict[str, Any]:
    overlay = tl.make_overlay("overlay_001", "arrow_red", "V3", start=0.5, duration=1.5)
    overlay["transform"] = {"x": 0.35, "y": 0.4, "scale": 0.6}
    return canonical(
        "图片叠加",
        [clip("clip_001", "demo", 0.0, 0.0, 3.0), overlay],
    )


def fx_audio() -> Dict[str, Any]:
    return canonical(
        "BGM 与音效",
        [
            clip("clip_001", "demo", 0.0, 0.0, 3.0),
            tl.make_audio("audio_001", "bgm_demo", "A1", 0.0, 3.0, volume=0.6,
                          fade_in=0.3, fade_out=0.5),
            tl.make_audio("audio_002", "sfx_impact", "A3", 1.0, 0.8),
        ],
    )


def fx_caption() -> Dict[str, Any]:
    caption = tl.make_caption("caption_001", "整句字幕", "T1", 0.4, 2.0)
    caption["safe_area"] = True
    sa.clamp_element(caption, "tiktok")
    return canonical(
        "整句字幕",
        [clip("clip_001", "demo", 0.0, 0.0, 3.0), caption],
        meta_extra={"safe_area": {"preset": "tiktok"}},
    )


def fx_caption_group() -> Dict[str, Any]:
    from core import voice as vc

    words = vc.estimate_word_timestamps("THIS IS ABSOLUTELY CRAZY", 2.0, start=0.5)
    group = vc.words_to_caption_group(words, "captiongroup_001", emphasis=["CRAZY"])
    return canonical(
        "逐词字幕",
        [clip("clip_001", "demo", 0.0, 0.0, 3.0), group],
    )


def fx_freeze() -> Dict[str, Any]:
    return canonical(
        "冻结帧",
        [
            clip("clip_001", "demo", 0.0, 0.0, 2.0),
            tl.make_freeze("freeze_001", "clip_001", 1.5, 2.0, 1.0, "V1"),
        ],
    )


def fx_effect() -> Dict[str, Any]:
    return canonical(
        "程序特效",
        [
            clip("clip_001", "demo", 0.0, 0.0, 3.0),
            tl.make_effect("effect_001", "zoom", {"scale_from": 1.0, "scale_to": 1.4},
                           "V1", 0.5, 0.8, target="clip_001"),
            tl.make_effect("effect_002", "shake", {"amplitude": 0.05, "frequency": 20},
                           "V1", 1.6, 0.5, target="clip_001"),
        ],
    )


def fx_transition() -> Dict[str, Any]:
    return canonical(
        "转场",
        [
            clip("clip_001", "demo", 0.0, 0.0, 2.0),
            clip("clip_002", "demo1", 2.0, 0.0, 2.0),
            tl.make_transition("transition_001", "crossfade", "clip_001", "clip_002",
                               1.6, 0.6, {}, "V1"),
        ],
    )


def fx_keyframe() -> Dict[str, Any]:
    element = clip("clip_001", "demo", 0.0, 0.0, 3.0)
    element["keyframes"] = {
        "scale": [
            {"time": 0.0, "value": 1.0},
            {"time": 1.5, "value": 1.25, "easing": "easeOut"},
            {"time": 3.0, "value": 1.0, "easing": "easeInOut"},
        ],
        "opacity": [
            {"time": 0.0, "value": 0.4},
            {"time": 0.8, "value": 1.0, "easing": "easeIn"},
        ],
    }
    return canonical("关键帧动画", [element])


def fx_complex_timeline() -> Dict[str, Any]:
    """多轨综合：视频 + 叠加 + 音频 + 文字 + 特效 + 转场。"""
    text = tl.make_text("text_001", "COMPLEX", "T2", 0.3, 1.4)
    overlay = tl.make_overlay("overlay_001", "ov_flash", "V4", start=1.7, duration=0.6)
    return canonical(
        "多轨综合",
        [
            clip("clip_001", "demo", 0.0, 0.0, 2.0),
            clip("clip_002", "demo1", 2.0, 1.0, 3.0),
            tl.make_transition("transition_001", "wipe", "clip_001", "clip_002",
                               1.7, 0.5, {"direction": "left"}, "V1"),
            overlay,
            tl.make_effect("effect_001", "flash", {"intensity": 0.7}, "V1", 1.9, 0.4),
            tl.make_audio("audio_001", "bgm_demo", "A1", 0.0, 5.0, volume=0.5),
            tl.make_audio("audio_002", "sfx_whoosh", "A3", 1.7, 0.7),
            text,
            tl.make_caption("caption_001", "多轨综合用例", "T1", 2.4, 2.0),
        ],
    )


def fx_demo_timeline() -> Dict[str, Any]:
    """指令第五十条的综合 Demo：所有能力凑在一条时间线上。

    2 视频 / 1 图片 / 1 Overlay / BGM / 配音 / 多个音效 / 字幕 / 逐词字幕 /
    冻结帧 / zoom / shake / blur / flash / 转场 / transform / keyframe / 标记。
    """
    from core import voice as vc

    first = clip("clip_001", "demo", 0.0, 0.0, 3.0)
    first["keyframes"] = {
        "scale": [
            {"time": 0.0, "value": 1.0},
            {"time": 2.0, "value": 1.15, "easing": "easeOut"},
        ]
    }
    second = clip("clip_002", "demo1", 3.0, 0.5, 3.5, speed=1.0)
    image = tl.make_overlay("overlay_001", "arrow_red", "V3", start=0.8, duration=1.2)
    image["transform"] = {"x": 0.3, "y": 0.35, "scale": 0.5, "rotation": -12.0}
    flash_overlay = tl.make_overlay("overlay_002", "ov_flash", "V4", start=2.8, duration=0.5)
    words = vc.estimate_word_timestamps("LOOK AT THIS", 1.5, start=4.2)
    group = vc.words_to_caption_group(words, "captiongroup_001", emphasis=["THIS"])
    caption = tl.make_caption("caption_001", "综合 Demo", "T1", 0.5, 1.6)
    caption["safe_area"] = True
    sa.clamp_element(caption, "youtube_shorts")

    elements = [
        first,
        second,
        tl.make_transition("transition_001", "whip", "clip_001", "clip_002",
                           2.7, 0.35, {}, "V1"),
        tl.make_freeze("freeze_001", "clip_002", 2.0, 6.0, 1.0, "V1"),
        tl.make_effect("effect_001", "zoom", {"scale_from": 1.0, "scale_to": 1.3},
                       "V1", 6.0, 0.8, target="freeze_001"),
        tl.make_effect("effect_002", "shake", {"amplitude": 0.04, "frequency": 18},
                       "V1", 1.2, 0.5, target="clip_001"),
        tl.make_effect("effect_003", "blur", {"radius": 6.0}, "V1", 3.2, 0.5,
                       target="clip_002"),
        tl.make_effect("effect_004", "flash", {"intensity": 0.8}, "V1", 2.8, 0.3),
        image,
        flash_overlay,
        tl.make_audio("audio_001", "bgm_demo", "A1", 0.0, 7.0, volume=0.45,
                      fade_in=0.4, fade_out=0.8),
        tl.make_audio("audio_002", "voice_demo", "A2", 4.2, 1.5),
        tl.make_audio("audio_003", "sfx_whoosh", "A3", 2.7, 0.6),
        tl.make_audio("audio_004", "sfx_impact", "A3", 6.0, 0.8, volume=0.9),
        caption,
        group,
        tl.make_text("text_001", "FINAL", "T2", 6.2, 0.8),
    ]
    return canonical(
        "综合 Demo",
        elements,
        canvas=(810, 1080),
        meta_extra={
            "safe_area": {"preset": "youtube_shorts"},
            "master_volume": 0.9,
            "markers": [
                {"time": 2.7, "type": "transition", "label": "甩镜切换"},
                {"time": 6.0, "type": "ai_highlight", "label": "高光：冻帧 + 推镜 + 撞击"},
            ],
        },
    )


def _resolution_fixture(name: str, canvas) -> Dict[str, Any]:
    """比例矩阵用例：同一套内容换四种画布，验证分辨率一路走到 MP4。"""
    caption = tl.make_caption("caption_001", f"{canvas[0]}×{canvas[1]}", "T1", 0.3, 1.4)
    return canonical(
        name,
        [
            clip("clip_001", "demo", 0.0, 0.0, 1.2),
            clip("clip_002", "demo1", 1.2, 0.0, 1.3),
            tl.make_transition("transition_001", "fade", "clip_001", "clip_002",
                               1.0, 0.4, {}, "V1"),
            tl.make_effect("effect_001", "zoom", {"scale_from": 1.0, "scale_to": 1.2},
                           "V1", 0.2, 0.6, target="clip_001"),
            tl.make_audio("audio_001", "bgm_demo", "A1", 0.0, 2.5, volume=0.5),
            caption,
        ],
        canvas=canvas,
    )


def fx_res_9x16() -> Dict[str, Any]:
    return _resolution_fixture("比例 9:16", (1080, 1920))


def fx_res_3x4() -> Dict[str, Any]:
    return _resolution_fixture("比例 3:4", (1080, 1440))


def fx_res_16x9() -> Dict[str, Any]:
    return _resolution_fixture("比例 16:9", (1920, 1080))


def fx_res_1x1() -> Dict[str, Any]:
    return _resolution_fixture("比例 1:1", (1080, 1080))


#: fixture 名 → 构造函数。顺序即渲染顺序（轻的先渲，早点看到结果）。
FIXTURES = {
    "basic_video": fx_basic_video,
    "dual_video": fx_dual_video,
    "overlay": fx_overlay,
    "audio": fx_audio,
    "caption": fx_caption,
    "caption_group": fx_caption_group,
    "freeze": fx_freeze,
    "effect": fx_effect,
    "transition": fx_transition,
    "keyframe": fx_keyframe,
    "complex_timeline": fx_complex_timeline,
    "demo_timeline": fx_demo_timeline,
    "res_3x4": fx_res_3x4,
    "res_9x16": fx_res_9x16,
    "res_16x9": fx_res_16x9,
    "res_1x1": fx_res_1x1,
}


# ---------------------------------------------------------------- 校验


class _FixtureAssets:
    """给 Validator 用的最小素材管理器：只回答存在性 / 时长。

    不复用 harness._ManifestAssets —— 那个按 harness.ASSETS 查源文件，
    而本脚本的素材表更大（多了配音与 whoosh），复用会让新素材被判成
    「磁盘上找不到」。这类假错误比没有检查更糟。
    """

    def __init__(self, manifest: Dict[str, Any]) -> None:
        self._by_id = {a["id"]: a for a in manifest["assets"]}

    def get(self, asset_id: str):
        return self._by_id.get(asset_id)

    def all(self):
        return list(self._by_id.values())

    def name_of(self, asset_id: str) -> str:
        return self._by_id.get(asset_id, {}).get("name", asset_id)

    def abs_path(self, asset_id: str) -> str:
        spec = ASSETS.get(asset_id)
        return spec["src"] if spec else ""

    def file_exists(self, asset_id: str) -> bool:
        spec = ASSETS.get(asset_id)
        return bool(spec and os.path.isfile(spec["src"]))

    def duration_of(self, asset_id: str) -> float:
        return float(self._by_id.get(asset_id, {}).get("duration", 0.0))


def make_validator(manifest: Dict[str, Any]) -> TimelineValidator:
    assets = _FixtureAssets(manifest)
    libraries = Libraries(os.path.join(ROOT, "assets"), assets).as_dict()
    return TimelineValidator(os.path.join(ROOT, "schemas"), assets, libraries)


def validate_all(manifest: Dict[str, Any], timelines: Dict[str, Dict[str, Any]]):
    validator = make_validator(manifest)
    rows = []
    for name, data in timelines.items():
        report = validator.validate_report(data)
        rows.append(
            {
                "name": name,
                "valid": report["valid"],
                "errors": report["errors"],
                "warnings": [w["rule"] for w in report["warnings"]],
                "elements": len(data.get("elements", [])),
                "resolution": f"{data['meta']['width']}×{data['meta']['height']}",
                "duration": data["meta"].get("duration", 0.0),
            }
        )
    return rows


# ---------------------------------------------------------------- 命令


def build(write: bool = True) -> int:
    os.makedirs(FIXTURE_DIR, exist_ok=True)
    manifest = build_manifest()
    missing = [i for i in ASSETS if i not in {a["id"] for a in manifest["assets"]}]
    if missing:
        print(f"FAIL 缺少素材文件：{', '.join(missing)}")
        return 1
    copied = copy_assets(manifest)
    print(f"素材 {len(manifest['assets'])} 个，新拷贝 {len(copied)} 个")

    timelines = {name: builder() for name, builder in FIXTURES.items()}
    rows = validate_all(manifest, timelines)
    bad = [r for r in rows if not r["valid"]]
    for row in rows:
        flag = "OK  " if row["valid"] else "FAIL"
        print(f"{flag} {row['name']:<18} {row['resolution']:>10}  "
              f"{row['duration']:>5.2f}s  元素 {row['elements']:>2}  "
              f"警告 {len(row['warnings'])}")
    if bad:
        for row in bad:
            for error in row["errors"]:
                print(f"     {row['name']}: {error['rule']} {error['message']}")
        return 1

    if not write:
        return 0

    for name, data in timelines.items():
        harness.write_json(os.path.join(FIXTURE_DIR, f"{name}.json"), data)
    harness.write_json(MANIFEST_PATH, manifest)

    jobs = [
        {
            "name": f"fixture_{name}",
            "timeline": os.path.join(FIXTURE_DIR, f"{name}.json"),
            "out": os.path.join(RENDER_DIR, f"{name}.mp4"),
        }
        for name in FIXTURES
    ]
    harness.write_json(
        BATCH_PATH,
        {"manifest": MANIFEST_PATH, "remotion_dir": harness.REMOTION_DIR, "jobs": jobs},
    )
    print(f"已写出 {len(jobs)} 份 fixture 与渲染批次 {os.path.relpath(BATCH_PATH, ROOT)}")
    return 0


def check() -> int:
    """校验磁盘上已有的 fixture（不重新生成），并与重新生成的结果比对。"""
    manifest = build_manifest()
    on_disk: Dict[str, Dict[str, Any]] = {}
    for name in FIXTURES:
        path = os.path.join(FIXTURE_DIR, f"{name}.json")
        if not os.path.isfile(path):
            print(f"FAIL 缺少 fixture {name}.json，请先跑 build")
            return 1
        on_disk[name] = harness.read_json(path)

    rows = validate_all(manifest, on_disk)
    drift = [
        name for name, builder in FIXTURES.items() if builder() != on_disk[name]
    ]
    for row in rows:
        print(f"{'OK  ' if row['valid'] else 'FAIL'} {row['name']}")
    if drift:
        print(f"DRIFT 与生成器不一致：{', '.join(drift)}")
    return 0 if all(r["valid"] for r in rows) and not drift else 1


# ---------------------------------------------------------------- 探针

#: YAVG 低于这个值算「黑」。只用来触发分类，不直接判 FAIL ——
#: fade / flash 转场设计上会经过纯色，那是对的画面。
DARK_LUMA = 8.0
#: 平均音量高于这个值算「真的有声音」。素材本身有响度余量，-50dB 已经很宽松。
AUDIBLE_DB = -50.0
#: 设计上会出现近纯色帧的转场（renderer 里就是「经过一层纯色」）
VEIL_TRANSITIONS = ("fade", "flash")


def _elements_of(data: Dict[str, Any], *types: str) -> List[Dict[str, Any]]:
    return [e for e in data.get("elements", []) if e.get("type") in types]


def _veil_windows(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """允许出现近黑帧的时间窗口。

    两种来源，都从 JSON 推导，不按用例名字开白名单（白名单会把真的黑帧放过去）：

    1. fade / flash 转场 —— renderer 的设计就是「经过一层纯色」；
    2. **没有任何可见元素覆盖**的时间段 —— 画面上本来就没东西，黑是正确结果。
       fixture 里 BGM 比画面长就会出现这种尾巴。
    """
    windows = []
    for element in _elements_of(data, "transition"):
        if (element.get("name") or "") not in VEIL_TRANSITIONS:
            continue
        start = float(element.get("start", 0.0))
        windows.append({
            "id": element.get("id", ""),
            "reason": f"{element.get('name')} 转场经过纯色",
            "start": start,
            "end": start + float(element.get("duration", 0.0)),
        })
    windows.extend(_uncovered_ranges(data))
    return windows


#: 会给画面提供**主体内容**的元素类型。
#: 文字 / 字幕**不算**：它们只占一小块，底下没有画面时整帧本来就是黑底 ——
#: 那是设计结果，不是渲染错误。audio 同理不算。
PICTURE_TYPES = ("video", "image", "overlay", "freeze", "group")


def _uncovered_ranges(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """没有任何画面主体覆盖的时间段（合并后的补集）。"""
    total = round(tl.timeline_duration(data), 3)
    spans = sorted(
        (float(e.get("start", 0.0)),
         float(e.get("start", 0.0)) + float(e.get("duration", 0.0)))
        for e in data.get("elements", [])
        if e.get("type") in PICTURE_TYPES and e.get("enabled") is not False
    )
    gaps: List[Dict[str, Any]] = []
    cursor = 0.0
    for start, end in spans:
        if start > cursor + 1e-6:
            gaps.append({"id": "", "reason": "这一段没有画面主体（只可能有文字 / 声音）",
                         "start": round(cursor, 3), "end": round(start, 3)})
        cursor = max(cursor, end)
    if total > cursor + 1e-6:
        gaps.append({"id": "", "reason": "这一段没有画面主体（只可能有文字 / 声音）",
                     "start": round(cursor, 3), "end": round(total, 3)})
    return gaps


def _expects_sound(data: Dict[str, Any]) -> bool:
    """这条时间线**应当**出声吗？

    只认两种声源：独立 audio 元素，和没被关掉音轨的 video 片段
    （demo.mp4 / demo1.mp4 自带音轨）。volume=0 / enabled=false 算静音，
    这里必须按值判断，不能用真值判断 —— 0 是有意义的设置。
    """
    for element in data.get("elements", []):
        if element.get("enabled") is False:
            continue
        kind = element.get("type")
        if kind == "audio":
            if float(element.get("volume", 1.0)) != 0.0:
                return True
        elif kind == "video":
            audio = element.get("audio") or {}
            if audio.get("enabled") is False:
                continue
            if float(audio.get("volume", 1.0)) == 0.0:
                continue
            return True
    return False


def _sample_stamps(duration: float, fps: float) -> List[float]:
    """百分位采样点，对齐到真实存在的帧时刻（-ss 取 ≥t 的第一帧，所以向下截）。"""
    total = max(1, int(round(duration * fps)))
    stamps = []
    for percent in (0.02, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 0.98):
        index = min(total - 1, int(duration * percent * fps))
        stamps.append(int(index) / fps)
    return sorted(set(round(s, 6) for s in stamps))


def _frame_count(path: str) -> Optional[int]:
    result = harness.run([
        harness.ffmpeg.ffprobe_path, "-v", "error", "-select_streams", "v:0",
        "-count_frames", "-show_entries", "stream=nb_read_frames",
        "-of", "default=nokey=1:noprint_wrappers=1", path,
    ])
    text = (result.stdout or "").strip()
    return int(text) if text.isdigit() else None


def probe_one(name: str, json_path: str, mp4: str) -> Dict[str, Any]:
    """量一份成片：ffprobe + 帧数 + 抽帧亮度 + 黑帧分类 + 音量。

    判据全部由**这份成片对应的 Timeline JSON**推出来，所以同一套逻辑既能量
    fixture，也能量 GUI 手势产出的时间线，不需要第二份「差不多」的实现。
    """
    data = harness.read_json(json_path)
    meta = data.get("meta", {})
    fps = float(meta.get("fps", 30) or 30)
    expected_duration = round(tl.timeline_duration(data), 3)
    row: Dict[str, Any] = {
        "name": name,
        "json": os.path.relpath(json_path, ROOT),
        "mp4": os.path.relpath(mp4, ROOT),
        "expected": {
            "width": int(meta.get("width", 0)),
            "height": int(meta.get("height", 0)),
            "fps": fps,
            "duration": expected_duration,
            "frames": max(1, int(round(expected_duration * fps))),
            "sound": _expects_sound(data),
        },
        "failures": [],
    }
    if not os.path.isfile(mp4):
        row["failures"].append("MP4 不存在（未渲染）")
        return row

    info = harness.probe_media(mp4)
    row["ffprobe"] = info
    video = info.get("video") or {}
    expect = row["expected"]
    if int(video.get("width") or 0) != expect["width"] or \
            int(video.get("height") or 0) != expect["height"]:
        row["failures"].append(
            f"分辨率不符：期望 {expect['width']}×{expect['height']}，"
            f"实测 {video.get('width')}×{video.get('height')}"
        )
    if abs(float(video.get("fps") or 0.0) - fps) > 0.01:
        row["failures"].append(f"帧率不符：期望 {fps}，实测 {video.get('fps')}")
    # 时长看**视频流**：容器时长会被 AAC 尾巴顶长（48kHz 一个 AAC 帧 ≈ 21ms），
    # 拿容器时长当画面时长会把「正常的音频对齐」误判成时长错误。
    measured = float(video.get("duration") or 0.0) or float(info.get("duration") or 0.0)
    row["video_duration"] = measured
    if abs(measured - expected_duration) > 1.5 / fps:
        row["failures"].append(
            f"视频流时长不符：期望 {expected_duration}s，实测 {measured}s"
        )
    count = _frame_count(mp4)
    row["frame_count"] = count
    if count is not None and abs(count - expect["frames"]) > 1:
        row["failures"].append(f"帧数不符：期望 {expect['frames']}，实测 {count}")

    # ---- 抽帧：每个采样点的平均亮度 / 方差（走验收脚本里那套原始像素通道，
    #      signalstats 的 metadata 在 -v error 下不会输出，拿不到数）
    stamps = _sample_stamps(measured or expected_duration, fps)
    size = analyze.raw_size(info)
    luma: Dict[str, float] = {}
    variance: Dict[str, float] = {}
    for stamp in stamps:
        frame_bytes = analyze.raw_frame(mp4, stamp, size)
        if not frame_bytes:
            row["failures"].append(f"{stamp:.3f}s 抽帧失败")
            continue
        stats = analyze.metrics_of(frame_bytes, size)
        luma[f"{stamp:.3f}"] = round(stats["mean"], 2)
        variance[f"{stamp:.3f}"] = round(stats["variance"], 2)
    row["luma"] = luma
    row["variance"] = variance

    # ---- 黑帧：区分「设计上的纯色过渡」与异常黑帧
    veils = _veil_windows(data)
    row["veil_windows"] = veils
    hits = harness.blackdetect(mp4)
    row["black"] = hits
    unexpected = [
        hit for hit in hits
        if not any(hit["start"] < w["end"] + 0.05 and hit["end"] > w["start"] - 0.05
                   for w in veils)
    ]
    row["black_unexpected"] = unexpected
    if unexpected:
        row["failures"].append(f"异常黑帧 {len(unexpected)} 段：{unexpected[:2]}")
    dark = [s for s, v in luma.items() if v < DARK_LUMA]
    row["dark_samples"] = dark
    dark_outside = [
        s for s in dark
        if not any(w["start"] - 0.05 <= float(s) <= w["end"] + 0.05 for w in veils)
    ]
    if dark_outside:
        row["failures"].append(f"非转场窗口内的近黑采样点：{dark_outside}")

    # ---- 音频
    volume = harness.mean_volume(mp4)
    row["mean_volume"] = volume
    has_track = bool(info.get("audio"))
    row["has_audio_stream"] = has_track
    if expect["sound"]:
        if not has_track:
            row["failures"].append("应当有音轨，实测没有音频流")
        elif volume is None or volume <= AUDIBLE_DB:
            row["failures"].append(f"音轨存在但听不见：mean_volume={volume}dB")
    elif has_track and volume is not None and volume > AUDIBLE_DB:
        row["failures"].append(f"不应出声却测到 {volume}dB")
    return row


def fixture_targets() -> List[tuple]:
    return [
        (name, os.path.join(FIXTURE_DIR, f"{name}.json"),
         os.path.join(RENDER_DIR, f"{name}.mp4"))
        for name in FIXTURES
    ]


def batch_targets(batch_path: str) -> List[tuple]:
    """从渲染批次文件里取 (name, timeline json, mp4)。"""
    batch = harness.read_json(batch_path)
    return [(job["name"], job["timeline"], job["out"]) for job in batch.get("jobs", [])]


def probe(targets: Optional[List[tuple]] = None,
          out_path: Optional[str] = None) -> int:
    """对已渲染的 MP4 做真实探针：ffprobe + 黑帧分类 + 抽帧 + 音频。

    这一步只**读**成片，不改任何源文件；判 FAIL 的依据全部来自 ffmpeg/ffprobe 实测。
    """
    if not harness.ffmpeg.ffprobe_path or not harness.ffmpeg.ffmpeg_path:
        print("FAIL 找不到 ffmpeg / ffprobe，无法探针（不允许跳过真实验证）")
        return 1

    targets = targets or fixture_targets()
    out_path = out_path or PROBE_PATH
    rows = [probe_one(name, json_path, mp4) for name, json_path, mp4 in targets]

    harness.write_json(out_path, rows)
    bad = [r for r in rows if r["failures"]]
    for row in rows:
        video = row.get("ffprobe", {}).get("video") or {}
        print(
            f"{'FAIL' if row['failures'] else 'OK  '} {row['name']:<20} "
            f"{video.get('width', '?')}×{video.get('height', '?')} "
            f"{row.get('frame_count', '?')}帧 "
            f"音量 {row.get('mean_volume')}dB "
            f"黑帧 {len(row.get('black', []))}(异常 {len(row.get('black_unexpected', []))})"
        )
        for reason in row["failures"]:
            print(f"     {reason}")
    print(f"探针完成：{len(rows)} 份成片，FAIL {len(bad)}，报告 "
          f"{os.path.relpath(out_path, ROOT)}")
    return 1 if bad else 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="生成 / 校验 tests/fixtures")
    parser.add_argument("command", choices=("build", "check", "probe"),
                        nargs="?", default="build")
    parser.add_argument("--batch", default="",
                        help="probe 用：渲染批次文件，量它列出的成片而不是 fixture")
    parser.add_argument("--out", default="",
                        help="probe 用：探针报告写到哪（默认 logs/fixtures_probe.json）")
    args = parser.parse_args(argv)
    if args.command == "build":
        return build()
    if args.command == "check":
        return check()
    targets = batch_targets(args.batch) if args.batch else None
    return probe(targets, args.out or None)


if __name__ == "__main__":
    raise SystemExit(main())
