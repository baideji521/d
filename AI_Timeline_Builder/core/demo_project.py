"""Demo Project 生成器。

开发指令第二十九条要求：启动后必须自带一个可以立刻玩的 Demo Project，
里面要覆盖 Video A / Video B / 图片箭头 / Impact 音效 / Caption / Text /
Zoom / Shake / Flash / Freeze / Whip 转场。

assets/ 初始是空的，所以这里做两件事：
1. 用 FFmpeg 的 lavfi 合成一批演示素材（不依赖任何外部下载）
2. 用 asset id 组装一条约 15 秒的时间线

演示素材只在缺失时生成，生成完走一次正常的素材扫描，
id 依旧由 asset_manifest.json 分配 —— Demo 不走任何特殊后门。
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Callable, Dict, List, Optional

from core import timeline as tl
from render.ffmpeg import FFmpeg

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# 相对 root 的演示素材路径。demo 时长给足 10 秒，方便试各种 source 区间。
DEMO_VIDEO_A = "assets/videos/demo/demo_a.mp4"
DEMO_VIDEO_B = "assets/videos/demo/demo_b.mp4"
DEMO_ARROW = "assets/overlays/arrow/arrow_red.png"
DEMO_IMPACT = "assets/audio/impact/impact_01.wav"
DEMO_BGM = "assets/audio/bgm/bgm_demo.wav"

DEMO_MEDIA = [DEMO_VIDEO_A, DEMO_VIDEO_B, DEMO_ARROW, DEMO_IMPACT, DEMO_BGM]

Logger = Callable[[str], None]


def _noop(_message: str) -> None:
    pass


# ---------------------------------------------------------------- 素材合成


def demo_media_missing(root: str) -> List[str]:
    """返回还缺哪些演示素材。"""
    return [rel for rel in DEMO_MEDIA if not os.path.isfile(os.path.join(root, rel))]


def ensure_demo_media(root: str, log: Logger = _noop) -> bool:
    """生成缺失的演示素材。返回是否真的写了新文件。"""
    missing = demo_media_missing(root)
    if not missing:
        return False

    ffmpeg = FFmpeg()
    created = False

    if DEMO_ARROW in missing:
        if _make_arrow_png(os.path.join(root, DEMO_ARROW)):
            log(f"已生成演示素材：{DEMO_ARROW}")
            created = True
        else:
            log(f"生成 {DEMO_ARROW} 失败")

    video_audio_missing = [m for m in missing if m != DEMO_ARROW]
    if video_audio_missing and not ffmpeg.available:
        log("未找到 FFmpeg，无法合成演示视频与音频，Demo 将只包含文字与箭头")
        return created

    for rel in video_audio_missing:
        target = os.path.join(root, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        args = _synth_args(rel)
        if args is None:
            continue
        log(f"正在合成演示素材 {rel} ...")
        if _run_ffmpeg(ffmpeg.ffmpeg_path, args + [target]):
            log(f"已生成演示素材：{rel}")
            created = True
        else:
            log(f"生成 {rel} 失败（FFmpeg 未成功返回）")
    return created


def _synth_args(rel: str) -> Optional[List[str]]:
    """给每个演示素材配一套 lavfi 合成参数。"""
    if rel == DEMO_VIDEO_A:
        return [
            "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=10",
            "-f", "lavfi", "-i", "sine=frequency=220:duration=10",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", "-t", "10",
        ]
    if rel == DEMO_VIDEO_B:
        return [
            "-f", "lavfi", "-i", "smptebars=size=1080x1920:rate=30:duration=10",
            "-f", "lavfi", "-i", "sine=frequency=330:duration=10",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", "-t", "10",
        ]
    if rel == DEMO_IMPACT:
        # 低频短促一击，配合 Flash 用
        return [
            "-f", "lavfi", "-i", "sine=frequency=110:duration=0.6",
            "-af", "afade=t=out:st=0.05:d=0.55,volume=1.4",
        ]
    if rel == DEMO_BGM:
        return [
            "-f", "lavfi", "-i", "sine=frequency=330:duration=16",
            "-af", "volume=0.25,tremolo=f=4:d=0.6",
        ]
    return None


def _run_ffmpeg(ffmpeg_path: Optional[str], args: List[str]) -> bool:
    if not ffmpeg_path:
        return False
    command = [ffmpeg_path, "-y", "-loglevel", "error"] + args
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=180,
            creationflags=_CREATE_NO_WINDOW,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return result.returncode == 0 and os.path.isfile(command[-1])


def _make_arrow_png(path: str) -> bool:
    """用 QPainter 画一个带描边的红色箭头 PNG（带 Alpha）。"""
    try:
        from PyQt5.QtCore import QPointF, Qt
        from PyQt5.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
    except ImportError:
        return False

    size = 512
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)

    # 一个指向右下方的粗箭头
    path_obj = QPainterPath()
    points = [
        (40, 200), (300, 200), (300, 110), (470, 256),
        (300, 402), (300, 312), (40, 312),
    ]
    path_obj.moveTo(QPointF(*points[0]))
    for point in points[1:]:
        path_obj.lineTo(QPointF(*point))
    path_obj.closeSubpath()

    painter.setBrush(QColor("#FF3B30"))
    painter.setPen(QPen(QColor("#FFFFFF"), 14))
    painter.drawPath(path_obj)
    painter.end()

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    return image.save(path, "PNG")


# ---------------------------------------------------------------- 时间线组装


def _asset_id_for(asset_manager, rel_path: str) -> str:
    """按清单里的相对路径反查 asset id。找不到返回空字符串。"""
    normalized = rel_path.replace("\\", "/").lower()
    for asset in asset_manager.all():
        if str(asset.get("path", "")).replace("\\", "/").lower() == normalized:
            return str(asset.get("id", ""))
    return ""


def build_demo_timeline(asset_manager, log: Logger = _noop) -> Dict[str, Any]:
    """组装 Demo 时间线。缺素材时相应元素会被跳过，其余照常生成。"""
    video_a = _asset_id_for(asset_manager, DEMO_VIDEO_A)
    video_b = _asset_id_for(asset_manager, DEMO_VIDEO_B)
    arrow = _asset_id_for(asset_manager, DEMO_ARROW)
    impact = _asset_id_for(asset_manager, DEMO_IMPACT)
    bgm = _asset_id_for(asset_manager, DEMO_BGM)

    timeline = tl.empty_timeline("Demo 项目（参数实验起点）", fps=30, width=1080, height=1920)
    elements: List[Dict[str, Any]] = []

    # ---- V1 主视频：两段 + Whip 转场 + 冻结帧
    if video_a:
        clip_a = tl.make_video("clip_001", video_a, "V1", start=0.0, source_start=0.5, source_end=6.5)
        elements.append(clip_a)
    if video_b:
        start_b = 6.0 if video_a else 0.0
        clip_b = tl.make_video("clip_002", video_b, "V1", start=start_b, source_start=1.0, source_end=8.0)
        elements.append(clip_b)

    if video_a and video_b:
        elements.append(
            tl.make_transition(
                "transition_001",
                "whip",
                "clip_001",
                "clip_002",
                start=5.75,
                duration=0.5,
                params={"direction": "left", "intensity": 0.8, "blur": 0.6},
                track="V1",
            )
        )
        # 冻结 clip_002 的第 3 秒（源时间），接在它后面做定格强调
        elements.append(
            tl.make_freeze("freeze_001", "clip_002", source_time=3.0, start=13.0, duration=1.5, track="V1")
        )

    # ---- V2 视频叠加：把 B 素材缩小放右上角当画中画
    if video_b:
        overlay_video = tl.make_video("clip_003", video_b, "V2", start=7.0, source_start=4.0, source_end=9.5)
        overlay_video["transform"] = {"x": 0.72, "y": 0.22, "scale": 0.38, "rotation": -4.0, "opacity": 1.0}
        overlay_video["audio"] = {"enabled": False, "volume": 0.0}
        elements.append(overlay_video)

    # ---- V3 图片箭头：带淡入淡出关键帧
    if arrow:
        arrow_element = tl.make_overlay("overlay_001", arrow, "V3", start=2.0, duration=2.5)
        arrow_element["transform"] = {"x": 0.34, "y": 0.46, "scale": 0.55, "rotation": 12.0, "opacity": 1.0}
        arrow_element["keyframes"] = {
            "opacity": [
                {"time": 0.0, "value": 0.0, "easing": "easeOut"},
                {"time": 0.3, "value": 1.0, "easing": "easeOut"},
                {"time": 2.2, "value": 1.0, "easing": "linear"},
                {"time": 2.5, "value": 0.0, "easing": "easeIn"},
            ],
            "scale": [
                {"time": 0.0, "value": 0.4, "easing": "easeOut"},
                {"time": 0.35, "value": 0.62, "easing": "easeOut"},
                {"time": 0.5, "value": 0.55, "easing": "easeInOut"},
            ],
        }
        elements.append(arrow_element)

    # ---- T1 字幕：逐词高亮 + 整句
    elements.append(
        tl.make_caption_group(
            "captiongroup_001",
            [
                {"text": "这是", "start": 0.4, "end": 0.9},
                {"text": "一个", "start": 0.9, "end": 1.4},
                {"text": "参数", "start": 1.4, "end": 2.0},
                {"text": "实验", "start": 2.0, "end": 2.6},
                {"text": "Demo", "start": 2.6, "end": 3.4},
            ],
            track="T1",
            template="highlight_yellow",
            caption_style="highlight_current",
        )
    )
    elements.append(
        tl.make_caption(
            "caption_001",
            "改任意参数，预览和 JSON 会同时变",
            track="T1",
            start=8.2,
            duration=2.4,
            template="bold_white",
            caption_style="plain",
        )
    )

    # ---- T2 文字：定格时的强调标题，带 Punch In 关键帧
    text_element = tl.make_text("text_001", "冻结 + 推进", track="T2", start=13.0, duration=2.0)
    text_element["transform"] = {"x": 0.5, "y": 0.32, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}
    text_element["keyframes"] = {
        "scale": [
            {"time": 0.0, "value": 0.8, "easing": "easeOut"},
            {"time": 0.12, "value": 1.15, "easing": "easeOut"},
            {"time": 0.26, "value": 1.0, "easing": "easeInOut"},
        ]
    }
    elements.append(text_element)

    # ---- A1 BGM / A3 音效
    if bgm:
        bgm_element = tl.make_audio("audio_001", bgm, "A1", start=0.0, duration=15.0, volume=0.35)
        bgm_element["fade"] = {"in": 0.6, "out": 1.2}
        elements.append(bgm_element)
    if impact:
        impact_duration = max(0.3, min(0.6, asset_manager.duration_of(impact) or 0.6))
        elements.append(
            tl.make_audio("audio_002", impact, "A3", start=5.9, duration=impact_duration, volume=1.0)
        )

    # ---- 程序特效：Zoom / Shake / Flash
    if video_a:
        elements.append(
            tl.make_effect(
                "effect_001",
                "zoom",
                {"scale_from": 1.0, "scale_to": 1.35, "origin_x": 0.5, "origin_y": 0.45},
                track="V1",
                start=4.6,
                duration=1.2,
                target="clip_001",
                easing="easeInOut",
            )
        )
    if video_b:
        elements.append(
            tl.make_effect(
                "effect_002",
                "shake",
                {"amplitude": 0.02, "frequency": 18.0, "rotation": 1.5},
                track="V1",
                start=6.05,
                duration=0.4,
                target="clip_002",
                easing="easeOut",
            )
        )
    elements.append(
        tl.make_effect(
            "effect_003",
            "flash",
            {"color": "#FFFFFF", "intensity": 0.85, "decay": "easeOut"},
            track="V4",
            start=5.95,
            duration=0.25,
            easing="easeOut",
        )
    )

    timeline["elements"] = elements
    timeline["meta"]["duration"] = tl.timeline_duration(timeline)
    log(
        f"Demo 时间线已组装：{len(elements)} 个元素，"
        f"总时长 {timeline['meta']['duration']} 秒"
    )
    return timeline


def demo_assets_unindexed(asset_manager) -> List[str]:
    """返回磁盘上有、但清单里查不到 id 的演示素材。"""
    root = asset_manager.root
    result = []
    for rel in DEMO_MEDIA:
        if not os.path.isfile(os.path.join(root, rel)):
            continue
        if not _asset_id_for(asset_manager, rel):
            result.append(rel)
    return result


def bootstrap_demo(asset_manager, log: Logger = _noop) -> Dict[str, Any]:
    """完整流程：补素材 → 扫描 → 组装时间线。

    扫描走同步版本，因为紧接着就要按路径反查 asset id；
    只在启动时调用一次，平时 GUI 里的重新扫描仍然是后台线程。
    """
    root = asset_manager.root
    created = ensure_demo_media(root, log)
    # 演示素材没进清单时也要扫：否则 Demo 时间线会静默少掉视频/音频元素
    unindexed = demo_assets_unindexed(asset_manager)
    if created or not asset_manager.all() or unindexed:
        if unindexed and not created:
            log(f"演示素材未收录进清单（{len(unindexed)} 个），重新扫描素材库…")
        asset_manager.rescan_blocking()
    return build_demo_timeline(asset_manager, log)

