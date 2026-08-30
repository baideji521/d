"""预览渲染器：用 QPainter 把 Timeline JSON 合成成一帧画面。

这是 GUI 侧的「近似渲染」，目的是让参数改动立刻看到结果，
从而搞懂「什么参数对应什么视觉效果」。最终成品仍由 Remotion 渲染。

渲染流程与 Remotion 侧保持同一套语义：
    元素按轨道 Z-Index 从下到上叠
    → 关键帧覆盖 transform
    → 程序特效按 target 修改几何/颜色
    → 转场在两个 Clip 交界处混合
    → 文字与字幕最后画

视频帧通过 FFmpeg 抽帧获得，抽帧在后台线程排队执行，主线程永不阻塞：
拿不到帧时先画占位，帧就绪后发 frameReady 信号让预览重画。
"""

from __future__ import annotations

import math
import os
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from PyQt5.QtCore import QObject, QPointF, QRectF, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QTransform,
)

from core import timeline as tl
from render.ffmpeg import FFmpeg

# 抽帧时间量化步长（秒）。0.1 表示每 0.1 秒一个缓存槽，避免拖动时抽爆 CPU。
FRAME_QUANTUM = 0.1
# 一次 ffmpeg 调用抽多少帧。20 帧 = 2 秒，够播放头跑一会儿。
BATCH_COUNT = 20
SEGMENT_SECONDS = FRAME_QUANTUM * BATCH_COUNT
# 缓存里找不到精确帧时，允许拿多久之前/之后的帧顶替（秒）。
NEAREST_TOLERANCE = 2.0
# 帧缓存上限（张）。一段 2 秒 20 张，600 张约等于 30 段。
FRAME_CACHE_LIMIT = 600
# 处理后（模糊/调色）图片的缓存上限
PROCESSED_CACHE_LIMIT = 120
# 记住多少个「已交付」的片段，防止预取重复解码。要小于 FRAME_CACHE_LIMIT 折算的段数
DONE_SEGMENT_LIMIT = 24


def _quantize(seconds: float) -> float:
    return round(round(float(seconds) / FRAME_QUANTUM) * FRAME_QUANTUM, 3)


def segment_start(seconds: float) -> float:
    """把时刻对齐到片段网格，保证同一段只抽一次。"""
    index = int(max(0.0, float(seconds)) / SEGMENT_SECONDS)
    return round(index * SEGMENT_SECONDS, 3)


def _parse_color(value: Any, fallback: str = "#FFFFFF") -> QColor:
    """支持 #RRGGBB 与 rgba(r,g,b,a) 两种写法。"""
    text = str(value or "").strip()
    if text.startswith("rgba(") and text.endswith(")"):
        parts = text[5:-1].split(",")
        if len(parts) == 4:
            try:
                r, g, b = (int(float(p)) for p in parts[:3])
                a = int(float(parts[3]) * 255)
                return QColor(r, g, b, a)
            except ValueError:
                pass
    color = QColor(text)
    return color if color.isValid() else QColor(fallback)


class FrameWorker(QThread):
    """串行处理抽帧请求的后台线程。

    按「片段」抽帧而不是按单帧抽：逐帧调 ffmpeg 每帧要 0.3 秒以上，
    播放时根本追不上播放头（实测命中率只有 35%，其余全画占位）。
    一次抽 BATCH_COUNT 帧后，单帧成本降到几十毫秒，播放头前面的帧
    也提前躺在缓存里了。

    PNG 解码也在这个线程里做：主线程解一张 540px 的 PNG 要 10ms，
    一段 20 帧就是 200ms 的卡顿，正好压在播放最需要流畅的时候。
    """

    frameDone = pyqtSignal(str, float, QImage)  # asset_id, quantized_time, 解好的画面

    def __init__(self, cache_dir: str, parent=None) -> None:
        super().__init__(parent)
        self._cache_dir = cache_dir
        self._seq_dir = os.path.join(cache_dir, "_seq")
        self._ffmpeg = FFmpeg()
        self._queue: List[Tuple[str, str, float]] = []
        self._pending: set = set()
        # 已经交付过的片段。预取会每帧都请求下一段，不记住的话同一段
        # 会被反复解码 20 张图，播放直接被拖死
        self._done: "OrderedDict[Tuple[str, float], bool]" = OrderedDict()
        self._running = True

    def request(self, asset_id: str, path: str, time_seconds: float) -> None:
        """请求某个时刻的帧；实际抽的是包含该时刻的整段。"""
        segment = segment_start(time_seconds)
        key = (asset_id, segment)
        if key in self._pending or key in self._done:
            return
        self._pending.add(key)
        # 后进先出：用户最关心当前播放头，旧请求让位
        self._queue.append((asset_id, path, segment))
        if len(self._queue) > 8:
            dropped = self._queue.pop(0)
            self._pending.discard((dropped[0], dropped[2]))

    def forget(self) -> None:
        """预览缓存被清空时同步忘掉交付记录，否则不会再补帧。"""
        self._done.clear()

    def stop(self) -> None:
        """请求停机：清空队列并把正在跑的 ffmpeg 子进程杀掉。

        只置标志是不够的 —— run() 可能正卡在一次最长 60 秒的抽帧调用里，
        主线程等不到线程结束就会去销毁一个仍在运行的 QThread（进程级崩溃）。
        """
        self._running = False
        self._queue.clear()
        self._pending.clear()
        self._ffmpeg.cancel()


    def run(self) -> None:  # noqa: D102
        while self._running:
            if not self._queue:
                self.msleep(20)
                continue
            asset_id, path, segment = self._queue.pop()
            self._pending.discard((asset_id, segment))
            self._extract_segment(asset_id, path, segment)
            self._done[(asset_id, segment)] = True
            while len(self._done) > DONE_SEGMENT_LIMIT:
                self._done.popitem(last=False)

    # ------------------------------------------------------------ 内部实现

    def _emit(self, asset_id: str, stamp: float, path: str) -> None:
        """在后台线程里解码，主线程只负责收下现成的 QImage。"""
        image = QImage(path)
        if image.isNull():
            return
        self.frameDone.emit(asset_id, stamp, image.convertToFormat(QImage.Format_ARGB32_Premultiplied))

    def _extract_segment(self, asset_id: str, path: str, segment: float) -> None:
        """抽出 [segment, segment + SEGMENT_SECONDS) 内的所有量化帧。"""
        wanted = [_quantize(segment + i * FRAME_QUANTUM) for i in range(BATCH_COUNT)]
        missing = [t for t in wanted if not os.path.isfile(self._frame_path(asset_id, t))]
        if not missing:
            for t in wanted:
                self._emit(asset_id, t, self._frame_path(asset_id, t))
            return

        produced = self._ffmpeg.extract_sequence(
            path, segment, BATCH_COUNT, FRAME_QUANTUM, self._seq_dir, width=540
        )
        if not produced:
            # 片段抽失败（多半是 seek 到了素材尾部之后），退回单帧兜底
            target = self._frame_path(asset_id, wanted[0])
            if os.path.isfile(target) or self._ffmpeg.extract_frame(path, wanted[0], target, width=540):
                self._emit(asset_id, wanted[0], target)
            return

        for index, src in enumerate(produced):
            if index >= BATCH_COUNT:
                break
            stamp = wanted[index]
            target = self._frame_path(asset_id, stamp)
            if not self._move(src, target):
                continue
            self._emit(asset_id, stamp, target)


    def _frame_path(self, asset_id: str, time_seconds: float) -> str:
        return os.path.join(self._cache_dir, f"{asset_id}_{time_seconds:.3f}.png")

    @staticmethod
    def _move(src: str, target: str) -> bool:
        """把 seq_0001.png 改名成缓存里的正式命名。"""
        try:
            if os.path.isfile(target):
                os.remove(target)
            os.replace(src, target)
            return True
        except OSError:
            return False


class PreviewRenderer(QObject):
    """把某一时刻的 Timeline 合成为 QImage。"""

    frameReady = pyqtSignal()

    def __init__(self, model, assets, libraries, cache_dir: str, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._model = model
        self._assets = assets
        self._libraries = libraries
        self._cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self._frames: "OrderedDict[Tuple[str, float], QImage]" = OrderedDict()
        self._images: Dict[str, QImage] = {}
        self._processed: "OrderedDict[str, QImage]" = OrderedDict()
        # 一批 20 帧会连发 20 次信号，攒 50ms 再通知一次，避免重绘风暴
        self._notify = QTimer(self)
        self._notify.setSingleShot(True)
        self._notify.setInterval(50)
        self._notify.timeout.connect(self.frameReady)
        self._worker = FrameWorker(cache_dir, self)
        self._worker.frameDone.connect(self._on_frame_done)
        self._worker.start()
        self._closed = False


    def shutdown(self) -> None:
        """停掉抽帧线程。**任何退出路径都必须走到这里**，且可以重复调用。

        Qt 一旦销毁「还在运行」的 QThread，就会直接 fastfail
        （Windows 上表现为 0xC0000409，进程无声无息地消失）。
        所以这里不只是置标志：先杀子进程，再等线程真的结束；
        万一还没结束，宁可 terminate 也不能让它带着运行状态被销毁。
        """
        if self._closed:
            return
        self._closed = True
        self._notify.stop()
        self._worker.stop()
        if not self._worker.wait(5000):
            self._worker.terminate()
            self._worker.wait(2000)


    # ------------------------------------------------------------ 帧缓存

    def _on_frame_done(self, asset_id: str, time_seconds: float, image: QImage) -> None:
        if image.isNull():
            return
        self._frames[(asset_id, round(time_seconds, 3))] = image
        while len(self._frames) > FRAME_CACHE_LIMIT:
            self._frames.popitem(last=False)
        if not self._notify.isActive():
            self._notify.start()

    def _video_frame(self, asset_id: str, source_time: float) -> Optional[QImage]:
        """取视频某时刻的画面。

        精确帧没有时，宁可拿附近的旧帧顶一下，也不要退回占位图 ——
        播放时占位图会让整个预览区看起来「什么都没有」。
        """
        quantized = _quantize(max(0.0, source_time))
        cached = self._frames.get((asset_id, quantized))
        path = self._assets.abs_path(asset_id)
        if path and os.path.isfile(path):
            if cached is None:
                self._worker.request(asset_id, path, quantized)
            # 预取下一段，让播放头跨段时不断流
            self._worker.request(asset_id, path, quantized + SEGMENT_SECONDS)
        if cached is not None:
            return cached
        return self._nearest_frame(asset_id, quantized)

    def _nearest_frame(self, asset_id: str, quantized: float) -> Optional[QImage]:
        """在容差范围内找同一素材最近的一帧。"""
        best: Optional[QImage] = None
        best_gap = NEAREST_TOLERANCE
        for (cached_id, stamp), image in self._frames.items():
            if cached_id != asset_id:
                continue
            gap = abs(stamp - quantized)
            if gap <= best_gap:
                best_gap = gap
                best = image
        return best


    def _static_image(self, asset_id: str) -> Optional[QImage]:
        """图片素材直接加载并缓存。"""
        if asset_id in self._images:
            image = self._images[asset_id]
            return image if not image.isNull() else None
        path = self._assets.abs_path(asset_id)
        image = QImage(path) if path and os.path.isfile(path) else QImage()
        self._images[asset_id] = image
        return image if not image.isNull() else None

    def clear_cache(self) -> None:
        self._frames.clear()
        self._images.clear()
        self._processed.clear()
        self._worker.forget()

    # ------------------------------------------------------------ 主渲染

    def render(self, time_seconds: float, size: QSize) -> QImage:
        """渲染指定时刻的画面，输出尺寸由 size 决定（按项目宽高比等比）。"""
        timeline = self._model.timeline
        canvas_w = max(16, size.width())
        canvas_h = max(16, size.height())
        image = QImage(canvas_w, canvas_h, QImage.Format_ARGB32_Premultiplied)
        image.fill(_parse_color(timeline.get("meta", {}).get("background"), "#000000"))

        painter = QPainter(image)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        try:
            self._paint_timeline(painter, timeline, float(time_seconds), canvas_w, canvas_h)
        finally:
            painter.end()
        return image

    def _paint_timeline(
        self,
        painter: QPainter,
        timeline: Dict[str, Any],
        now: float,
        width: int,
        height: int,
    ) -> None:
        elements = timeline.get("elements", [])
        active = [e for e in elements if self._is_active(e, now)]

        # 收集此刻生效的程序特效，按 target 分组
        effects = [e for e in active if e.get("type") == "effect"]
        transitions = [e for e in elements if e.get("type") == "transition" and self._is_active(e, now)]

        # 视觉元素按轨道 Z-Index 从低到高绘制
        visuals = [
            e
            for e in active
            if e.get("type") in ("video", "overlay", "freeze", "text", "caption", "caption_group")
        ]
        visuals.sort(
            key=lambda e: (
                e.get("z_index", tl.track_z_index(timeline, e.get("track", ""))),
                float(e.get("start", 0.0)),
            )
        )

        # 参与转场的片段单独处理，避免重复绘制
        transition_pairs = {(t.get("from"), t.get("to")): t for t in transitions}
        consumed: set = set()
        for (from_id, to_id) in transition_pairs:
            consumed.add(from_id)
            consumed.add(to_id)

        for element in visuals:
            track = tl.get_track(timeline, element.get("track", ""))
            if track and track.get("hidden"):
                continue
            if element.get("id") in consumed:
                continue
            self._paint_element(painter, timeline, element, now, width, height, effects)

        # 转场：在同一位置混合两个片段
        for (from_id, to_id), transition in transition_pairs.items():
            self._paint_transition(painter, timeline, transition, now, width, height, effects)

        # 全屏类特效（闪白、暗角、色差、故障）画在最上层
        self._paint_screen_effects(painter, effects, now, width, height)

    @staticmethod
    def _is_active(element: Dict[str, Any], now: float) -> bool:
        start = float(element.get("start", 0.0))
        end = start + float(element.get("duration", 0.0))
        return start - 1e-6 <= now < end + 1e-6

    # ------------------------------------------------------------ 单元素

    def _paint_element(
        self,
        painter: QPainter,
        timeline: Dict[str, Any],
        element: Dict[str, Any],
        now: float,
        width: int,
        height: int,
        effects: List[Dict[str, Any]],
        alpha_scale: float = 1.0,
        extra_offset: Tuple[float, float] = (0.0, 0.0),
        extra_scale: float = 1.0,
    ) -> None:
        etype = element.get("type")
        local = now - float(element.get("start", 0.0))
        geometry = self._resolve_geometry(element, local, effects, now)
        geometry["x"] += extra_offset[0]
        geometry["y"] += extra_offset[1]
        geometry["scale"] *= extra_scale
        geometry["opacity"] *= alpha_scale

        if etype in ("video", "freeze"):
            self._paint_video_like(painter, timeline, element, now, width, height, geometry)
        elif etype == "overlay":
            self._paint_overlay(painter, element, width, height, geometry)
        elif etype == "text":
            self._paint_text(painter, element, width, height, geometry, local)
        elif etype in ("caption", "caption_group"):
            self._paint_caption(painter, element, width, height, geometry, now, local)

    def _resolve_geometry(
        self,
        element: Dict[str, Any],
        local_time: float,
        effects: List[Dict[str, Any]],
        now: float,
    ) -> Dict[str, float]:
        """合并 transform、关键帧、以及作用于本元素的几何类特效。"""
        geometry = {
            "x": tl.resolve_animated_value(element, "x", local_time),
            "y": tl.resolve_animated_value(element, "y", local_time),
            "scale": tl.resolve_animated_value(element, "scale", local_time),
            "rotation": tl.resolve_animated_value(element, "rotation", local_time),
            "opacity": tl.resolve_animated_value(element, "opacity", local_time),
            "blur": tl.resolve_animated_value(element, "blur", local_time),
            "brightness": tl.resolve_animated_value(element, "brightness", local_time),
            "saturation": tl.resolve_animated_value(element, "saturation", local_time),
        }
        element_id = element.get("id")
        for effect in effects:
            target = effect.get("target")
            # 未指定 target 的特效只作用于视频类元素（与 Remotion 侧一致）
            if target and target != element_id:
                continue
            if not target and element.get("type") not in ("video", "freeze"):
                continue
            self._apply_geometry_effect(geometry, effect, now)
        return geometry

    def _apply_geometry_effect(self, geometry: Dict[str, float], effect: Dict[str, Any], now: float) -> None:
        name = effect.get("name", "")
        params = effect.get("params") or {}
        start = float(effect.get("start", 0.0))
        duration = max(1e-6, float(effect.get("duration", 0.0)))
        progress = min(1.0, max(0.0, (now - start) / duration))
        eased = tl.apply_easing(progress, effect.get("easing", "easeInOut"))

        if name == "zoom":
            scale_from = float(params.get("scale_from", 1.0))
            scale_to = float(params.get("scale_to", 1.3))
            geometry["scale"] *= scale_from + (scale_to - scale_from) * eased
            # 以非中心点缩放时画面会朝该点靠拢
            origin_x = float(params.get("origin_x", 0.5))
            origin_y = float(params.get("origin_y", 0.5))
            zoom = geometry["scale"]
            geometry["x"] += (0.5 - origin_x) * (zoom - 1.0)
            geometry["y"] += (0.5 - origin_y) * (zoom - 1.0)
        elif name == "shake":
            amplitude = float(params.get("amplitude", 0.02))
            frequency = float(params.get("frequency", 18.0))
            phase = (now - start) * frequency * math.tau
            geometry["x"] += math.sin(phase) * amplitude
            geometry["y"] += math.cos(phase * 1.37) * amplitude
            geometry["rotation"] += math.sin(phase * 0.73) * float(params.get("rotation", 0.0))
        elif name == "spin":
            angle_from = float(params.get("from", 0.0))
            angle_to = float(params.get("to", 0.0))
            geometry["rotation"] += angle_from + (angle_to - angle_from) * eased
        elif name == "bounce":
            bounces = max(1, int(params.get("bounces", 2)))
            height_ratio = float(params.get("height", 0.08))
            decay = 1.0 - progress
            geometry["y"] -= abs(math.sin(progress * math.pi * bounces)) * height_ratio * decay
        elif name == "pulse":
            scale_min = float(params.get("scale_min", 1.0))
            scale_max = float(params.get("scale_max", 1.08))
            cycles = max(1, int(params.get("cycles", 2)))
            wave = (1.0 - math.cos(progress * math.tau * cycles)) / 2.0
            geometry["scale"] *= scale_min + (scale_max - scale_min) * wave
        elif name == "blur":
            radius_from = float(params.get("radius_from", 0.0))
            radius_to = float(params.get("radius_to", 0.0))
            geometry["blur"] += radius_from + (radius_to - radius_from) * eased
        elif name == "motion_blur":
            geometry["blur"] += float(params.get("amount", 0.0)) * 0.5
        elif name == "brightness":
            value_from = float(params.get("value_from", 1.0))
            value_to = float(params.get("value_to", 1.0))
            geometry["brightness"] *= value_from + (value_to - value_from) * eased
        elif name == "saturation":
            value_from = float(params.get("value_from", 1.0))
            value_to = float(params.get("value_to", 1.0))
            geometry["saturation"] *= value_from + (value_to - value_from) * eased
        elif name == "contrast":
            value_from = float(params.get("value_from", 1.0))
            value_to = float(params.get("value_to", 1.0))
            # 对比度在预览里用亮度近似，够用来判断方向与强度
            geometry["brightness"] *= 1.0 + (value_from + (value_to - value_from) * eased - 1.0) * 0.5

    def _paint_video_like(
        self,
        painter: QPainter,
        timeline: Dict[str, Any],
        element: Dict[str, Any],
        now: float,
        width: int,
        height: int,
        geometry: Dict[str, float],
    ) -> None:
        """视频片段与冻结帧共用一套绘制：算出源时间，抽帧，按几何画。"""
        if element.get("type") == "freeze":
            target = tl.get_element(timeline, element.get("target", ""))
            asset_id = (target or {}).get("asset", "")
            source_time = float(element.get("source_time", 0.0))
        else:
            asset_id = element.get("asset", "")
            source = element.get("source") or {}
            speed = float(element.get("speed", 1.0) or 1.0)
            local = now - float(element.get("start", 0.0))
            source_time = float(source.get("start", 0.0)) + local * speed

        frame = self._video_frame(asset_id, source_time) if asset_id else None
        if frame is None:
            self._paint_placeholder(
                painter,
                width,
                height,
                f"{element.get('id')}  {self._assets.name_of(asset_id) if asset_id else '无素材'}\n"
                f"源时间 {source_time:.2f}s（抽帧中…）",
            )
            return
        self._draw_image_with_geometry(
            painter,
            frame,
            width,
            height,
            geometry,
            cover=True,
            cache_key=f"{asset_id}@{_quantize(max(0.0, source_time)):.3f}",
        )

    def _paint_overlay(
        self,
        painter: QPainter,
        element: Dict[str, Any],
        width: int,
        height: int,
        geometry: Dict[str, float],
    ) -> None:
        asset_id = element.get("asset", "")
        image = self._static_image(asset_id)
        if image is None:
            # 透明视频这类 overlay 也可能是视频，退回抽帧
            image = self._video_frame(asset_id, 0.1) if asset_id else None
        if image is None:
            return
        self._draw_image_with_geometry(
            painter,
            image,
            width,
            height,
            geometry,
            cover=False,
            cache_key=f"overlay:{asset_id}",
        )

    def _draw_image_with_geometry(
        self,
        painter: QPainter,
        image: QImage,
        width: int,
        height: int,
        geometry: Dict[str, float],
        cover: bool,
        cache_key: str = "",
    ) -> None:
        opacity = max(0.0, min(1.0, geometry.get("opacity", 1.0)))
        if opacity <= 0.001:
            return

        prepared = self._prepare_image(
            image,
            geometry.get("blur", 0.0),
            geometry.get("brightness", 1.0),
            geometry.get("saturation", 1.0),
            cache_key,
        )


        if cover:
            # 视频铺满画面（等比裁切）
            scale_base = max(width / prepared.width(), height / prepared.height())
        else:
            # Overlay 等比适配，不裁切
            scale_base = min(width / prepared.width(), height / prepared.height())
        draw_w = prepared.width() * scale_base * geometry.get("scale", 1.0)
        draw_h = prepared.height() * scale_base * geometry.get("scale", 1.0)

        center_x = geometry.get("x", 0.5) * width
        center_y = geometry.get("y", 0.5) * height

        painter.save()
        painter.setOpacity(opacity)
        painter.translate(center_x, center_y)
        rotation = geometry.get("rotation", 0.0)
        if abs(rotation) > 0.01:
            painter.rotate(rotation)
        painter.drawImage(QRectF(-draw_w / 2, -draw_h / 2, draw_w, draw_h), prepared)
        painter.restore()

    def _prepare_image(
        self,
        image: QImage,
        blur: float,
        brightness: float,
        saturation: float,
        cache_key: str,
    ) -> QImage:
        """按需做模糊 / 调色，结果带缓存。

        同一帧在播放头不动时会被重画多次（选中、面板刷新都会触发），
        没有缓存的话同样的处理要重复做。
        """
        needs_blur = blur > 0.5
        needs_color = abs(brightness - 1.0) > 0.01 or abs(saturation - 1.0) > 0.01
        if not needs_blur and not needs_color:
            return image

        key = ""
        if cache_key:
            key = (
                f"{cache_key}|{round(blur, 1)}|{round(brightness, 2)}|{round(saturation, 2)}"
                f"|{image.width()}x{image.height()}"
            )
            cached = self._processed.get(key)
            if cached is not None:
                return cached

        prepared = image
        if needs_blur:
            prepared = self._cheap_blur(prepared, blur)
        if needs_color:
            prepared = self._adjust_color(prepared, brightness, saturation)

        if key:
            self._processed[key] = prepared
            while len(self._processed) > PROCESSED_CACHE_LIMIT:
                self._processed.popitem(last=False)
        return prepared

    @staticmethod
    def _cheap_blur(image: QImage, radius: float) -> QImage:
        """降采样再放大的近似模糊。够快，方向感与强度感都对。"""
        factor = max(1.0, min(24.0, radius / 2.0))
        small_w = max(1, int(image.width() / factor))
        small_h = max(1, int(image.height() / factor))
        small = image.scaled(small_w, small_h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        return small.scaled(image.width(), image.height(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    @staticmethod
    def _adjust_color(image: QImage, brightness: float, saturation: float) -> QImage:
        """亮度与饱和度调整，全部走 QPainter 合成，不做逐像素循环。

        这里以前是 Python 双层 for 循环调 setPixel，720×1280 一帧要 7.5 秒，
        时间线上只要有 brightness / saturation / contrast 特效，播放就直接卡死。
        现在的做法：
            饱和度 <1 → 与灰度图按 (1-s) 混合（数学上就是标准去饱和）
            饱和度 >1 → 用 Overlay 叠自身近似增艳（预览近似，方向和强度对）
            亮度 <1 → Multiply 一个灰色；亮度 >1 → Screen 一个灰色
        最后用 DestinationIn 把原图 alpha 贴回来，保证透明 Overlay 不会被填成实心。
        """
        result = image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        alpha_source = result.copy()

        painter = QPainter(result)
        if abs(saturation - 1.0) > 0.01:
            if saturation < 1.0:
                gray = alpha_source.convertToFormat(QImage.Format_Grayscale8).convertToFormat(
                    QImage.Format_ARGB32_Premultiplied
                )
                painter.setOpacity(min(1.0, 1.0 - saturation))
                painter.drawImage(0, 0, gray)
                painter.setOpacity(1.0)
            else:
                painter.setCompositionMode(QPainter.CompositionMode_Overlay)
                painter.setOpacity(min(1.0, (saturation - 1.0) * 0.8))
                painter.drawImage(0, 0, alpha_source)
                painter.setOpacity(1.0)
                painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

        if abs(brightness - 1.0) > 0.01:
            if brightness < 1.0:
                level = int(max(0.0, min(1.0, brightness)) * 255)
                painter.setCompositionMode(QPainter.CompositionMode_Multiply)
            else:
                level = int(max(0.0, min(1.0, brightness - 1.0)) * 255)
                painter.setCompositionMode(QPainter.CompositionMode_Screen)
            painter.fillRect(result.rect(), QColor(level, level, level))

        # 把原始 alpha 贴回来，否则上面的 fillRect 会把透明区域也填上
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.drawImage(0, 0, alpha_source)
        painter.end()
        return result


    def _paint_placeholder(self, painter: QPainter, width: int, height: int, text: str) -> None:
        painter.save()
        painter.setPen(QPen(QColor(120, 130, 150), 1, Qt.DashLine))
        painter.setBrush(QBrush(QColor(26, 30, 38)))
        painter.drawRect(QRectF(8, 8, width - 16, height - 16))
        painter.setPen(QPen(QColor(150, 160, 180)))
        font = painter.font()
        font.setPointSizeF(max(7.0, width / 46.0))
        painter.setFont(font)
        painter.drawText(QRectF(12, 12, width - 24, height - 24), Qt.AlignCenter | Qt.TextWordWrap, text)
        painter.restore()

    # ------------------------------------------------------------ 文字

    def _build_font(self, style: Dict[str, Any], width: int, scale: float) -> QFont:
        """字号按项目宽度等比缩放，保证预览和成品视觉一致。"""
        font = QFont(style.get("fontFamily", "Arial"))
        ratio = width / max(1, self._model.width)
        size = float(style.get("fontSize", 64)) * ratio * scale
        font.setPointSizeF(max(4.0, size))
        font.setWeight(self._qt_weight(int(style.get("fontWeight", 700))))
        spacing = float(style.get("letterSpacing", 0) or 0)
        if spacing:
            font.setLetterSpacing(QFont.AbsoluteSpacing, spacing * ratio)
        return font

    @staticmethod
    def _qt_weight(css_weight: int) -> int:
        """CSS 100-900 映射到 Qt 的 0-99。"""
        return max(1, min(99, int(css_weight / 900 * 99)))

    def _draw_styled_text(
        self,
        painter: QPainter,
        text: str,
        center: QPointF,
        style: Dict[str, Any],
        width: int,
        scale: float,
        opacity: float,
        rotation: float,
        color_override: Optional[QColor] = None,
    ) -> QRectF:
        """带描边 / 阴影 / 背景色块的文字绘制。返回文字外接矩形。"""
        font = self._build_font(style, width, scale)
        metrics = QFontMetricsF(font)
        lines = text.split("\n")
        line_height = metrics.height() * float(style.get("lineHeight", 1.2) or 1.2)
        total_h = line_height * len(lines)
        max_w = max((metrics.horizontalAdvance(line) for line in lines), default=0.0)

        painter.save()
        painter.setOpacity(max(0.0, min(1.0, opacity)))
        painter.translate(center)
        if abs(rotation) > 0.01:
            painter.rotate(rotation)
        painter.setFont(font)

        bounds = QRectF(-max_w / 2 - 16, -total_h / 2 - 8, max_w + 32, total_h + 16)

        background = style.get("backgroundColor")
        if background:
            painter.setPen(Qt.NoPen)
            painter.setBrush(_parse_color(background, "rgba(0,0,0,0.6)"))
            painter.drawRoundedRect(bounds, 10, 10)

        stroke = style.get("stroke") or {}
        stroke_width = float(stroke.get("width", 0) or 0) * (width / max(1, self._model.width)) * scale
        shadow = style.get("shadow") or {}
        fill = color_override or _parse_color(style.get("color"), "#FFFFFF")

        for index, line in enumerate(lines):
            baseline_y = -total_h / 2 + line_height * index + metrics.ascent()
            line_w = metrics.horizontalAdvance(line)
            align = style.get("align", "center")
            if align == "left":
                x = -max_w / 2
            elif align == "right":
                x = max_w / 2 - line_w
            else:
                x = -line_w / 2

            path = QPainterPath()
            path.addText(QPointF(x, baseline_y), font, line)

            if shadow:
                offset_x = float(shadow.get("x", 0)) * scale
                offset_y = float(shadow.get("y", 0)) * scale
                painter.save()
                painter.translate(offset_x, offset_y)
                painter.setPen(Qt.NoPen)
                painter.setBrush(_parse_color(shadow.get("color"), "rgba(0,0,0,0.6)"))
                painter.drawPath(path)
                painter.restore()

            if stroke_width > 0.2:
                pen = QPen(_parse_color(stroke.get("color"), "#000000"))
                pen.setWidthF(stroke_width)
                pen.setJoinStyle(Qt.RoundJoin)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(path)

            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(fill))
            painter.drawPath(path)

        painter.restore()
        return bounds

    def _paint_text(
        self,
        painter: QPainter,
        element: Dict[str, Any],
        width: int,
        height: int,
        geometry: Dict[str, float],
        local: float,
    ) -> None:
        text = (element.get("content") or {}).get("text", "")
        if not text:
            return
        center = QPointF(geometry.get("x", 0.5) * width, geometry.get("y", 0.7) * height)
        self._draw_styled_text(
            painter,
            text,
            center,
            element.get("style") or {},
            width,
            geometry.get("scale", 1.0),
            geometry.get("opacity", 1.0),
            geometry.get("rotation", 0.0),
        )

    def _paint_caption(
        self,
        painter: QPainter,
        element: Dict[str, Any],
        width: int,
        height: int,
        geometry: Dict[str, float],
        now: float,
        local: float,
    ) -> None:
        """按 caption_style 分派不同的字幕表现。"""
        style = element.get("style") or {}
        content = element.get("content") or {}
        words = content.get("words") or []
        caption_style = element.get("caption_style", "plain")
        highlight = element.get("highlight") or {}
        center = QPointF(geometry.get("x", 0.5) * width, geometry.get("y", 0.82) * height)
        scale = geometry.get("scale", 1.0)
        opacity = geometry.get("opacity", 1.0)
        duration = max(1e-6, float(element.get("duration", 1.0)))

        # 入场动效类样式：换算成额外的 scale / opacity
        if caption_style == "pop":
            progress = min(1.0, local / min(0.25, duration))
            scale *= 0.7 + 0.3 * tl.apply_easing(progress, "easeOut") + (
                0.12 * math.sin(min(1.0, progress) * math.pi)
            )
        elif caption_style == "bounce":
            progress = min(1.0, local / min(0.4, duration))
            center.setY(center.y() - (1.0 - progress) * height * 0.06 * math.cos(progress * math.pi * 2))
            scale *= 0.85 + 0.15 * tl.apply_easing(progress, "easeOut")

        if not words:
            text = content.get("text", "")
            if caption_style == "char_by_char":
                shown = max(0, int(len(text) * min(1.0, local / duration)))
                text = text[:shown]
            elif caption_style == "two_line":
                text = self._split_two_lines(text)
            if not text:
                return
            self._draw_styled_text(
                painter, text, center, style, width, scale, opacity, geometry.get("rotation", 0.0)
            )
            return

        # 逐词类样式：先决定哪些词要显示，再逐词定位
        if caption_style == "word_by_word":
            visible = [w for w in words if float(w.get("start", 0.0)) <= now]
        else:
            visible = list(words)
        if not visible:
            return

        font = self._build_font(style, width, scale)
        metrics = QFontMetricsF(font)
        space = metrics.horizontalAdvance(" ")
        widths = [metrics.horizontalAdvance(str(w.get("text", ""))) for w in visible]
        total = sum(widths) + space * max(0, len(visible) - 1)
        cursor = center.x() - total / 2

        highlight_color = _parse_color(highlight.get("color"), "#FFE347")
        highlight_scale = float(highlight.get("scale", 1.0) or 1.0)

        for index, word in enumerate(visible):
            word_start = float(word.get("start", 0.0))
            word_end = float(word.get("end", word_start))
            is_current = word_start <= now < word_end
            word_text = str(word.get("text", ""))
            word_scale = scale
            color_override: Optional[QColor] = None

            if caption_style in ("highlight_current", "karaoke") and is_current:
                color_override = highlight_color
                if caption_style == "highlight_current":
                    word_scale = scale * highlight_scale
            elif caption_style == "karaoke" and now >= word_end:
                color_override = highlight_color

            word_center = QPointF(cursor + widths[index] / 2, center.y())
            self._draw_styled_text(
                painter,
                word_text,
                word_center,
                {k: v for k, v in style.items() if k != "backgroundColor"},
                width,
                word_scale,
                opacity,
                geometry.get("rotation", 0.0),
                color_override,
            )
            cursor += widths[index] + space

    @staticmethod
    def _split_two_lines(text: str) -> str:
        """长句拆成上下两行，按空格就近断开。"""
        if "\n" in text or len(text) < 12:
            return text
        parts = text.split(" ")
        if len(parts) < 2:
            middle = len(text) // 2
            return text[:middle] + "\n" + text[middle:]
        best_index = len(parts) // 2
        return " ".join(parts[:best_index]) + "\n" + " ".join(parts[best_index:])

    # ------------------------------------------------------------ 转场

    def _paint_transition(
        self,
        painter: QPainter,
        timeline: Dict[str, Any],
        transition: Dict[str, Any],
        now: float,
        width: int,
        height: int,
        effects: List[Dict[str, Any]],
    ) -> None:
        from_element = tl.get_element(timeline, transition.get("from", ""))
        to_element = tl.get_element(timeline, transition.get("to", ""))
        start = float(transition.get("start", 0.0))
        duration = max(1e-6, float(transition.get("duration", 0.0)))
        progress = min(1.0, max(0.0, (now - start) / duration))
        name = transition.get("name", "crossfade")
        params = transition.get("params") or {}

        direction = str(params.get("direction", "left"))
        vector = {
            "left": (-1.0, 0.0),
            "right": (1.0, 0.0),
            "up": (0.0, -1.0),
            "down": (0.0, 1.0),
        }.get(direction, (-1.0, 0.0))

        # 每种转场给出 (from 的 alpha/位移/缩放, to 的 alpha/位移/缩放)
        if name in ("fade", "flash"):
            # 经过中间色：前半段 from 淡出，后半段 to 淡入
            if progress < 0.5:
                self._paint_transition_side(painter, timeline, from_element, now, width, height, effects, 1.0 - progress * 2)
            else:
                self._paint_transition_side(painter, timeline, to_element, now, width, height, effects, (progress - 0.5) * 2)
            color = _parse_color(params.get("color"), "#FFFFFF" if name == "flash" else "#000000")
            intensity = float(params.get("intensity", 1.0))
            alpha = (1.0 - abs(progress - 0.5) * 2) * intensity
            painter.save()
            painter.setOpacity(max(0.0, min(1.0, alpha)))
            painter.fillRect(0, 0, width, height, color)
            painter.restore()
            return

        if name == "crossfade":
            self._paint_transition_side(painter, timeline, from_element, now, width, height, effects, 1.0 - progress)
            self._paint_transition_side(painter, timeline, to_element, now, width, height, effects, progress)
            return

        if name == "whip":
            intensity = float(params.get("intensity", 0.8))
            blur = float(params.get("blur", 0.6)) * 40.0
            self._paint_transition_side(
                painter, timeline, from_element, now, width, height, effects,
                1.0 - progress,
                offset=(vector[0] * progress * intensity, vector[1] * progress * intensity),
                blur=blur * progress,
            )
            self._paint_transition_side(
                painter, timeline, to_element, now, width, height, effects,
                progress,
                offset=(-vector[0] * (1 - progress) * intensity, -vector[1] * (1 - progress) * intensity),
                blur=blur * (1 - progress),
            )
            return

        if name in ("slide", "push"):
            self._paint_transition_side(
                painter, timeline, from_element, now, width, height, effects,
                1.0,
                offset=(vector[0] * progress, vector[1] * progress) if name == "push" else (0.0, 0.0),
            )
            self._paint_transition_side(
                painter, timeline, to_element, now, width, height, effects,
                1.0,
                offset=(-vector[0] * (1 - progress), -vector[1] * (1 - progress)),
            )
            return

        if name == "zoom":
            zoom = float(params.get("scale", 1.6))
            blur = float(params.get("blur", 0.3)) * 40.0
            self._paint_transition_side(
                painter, timeline, from_element, now, width, height, effects,
                1.0 - progress,
                scale=1.0 + (zoom - 1.0) * progress,
                blur=blur * progress,
            )
            self._paint_transition_side(
                painter, timeline, to_element, now, width, height, effects,
                progress,
                scale=zoom - (zoom - 1.0) * progress,
                blur=blur * (1 - progress),
            )
            return

        if name == "spin":
            angle = float(params.get("angle", 90.0))
            zoom = float(params.get("scale", 1.3))
            self._paint_transition_side(
                painter, timeline, from_element, now, width, height, effects,
                1.0 - progress, rotation=angle * progress, scale=1.0 + (zoom - 1.0) * progress
            )
            self._paint_transition_side(
                painter, timeline, to_element, now, width, height, effects,
                progress, rotation=-angle * (1 - progress), scale=zoom - (zoom - 1.0) * progress
            )
            return

        if name == "blur":
            amount = float(params.get("amount", 24.0))
            wave = 1.0 - abs(progress - 0.5) * 2
            self._paint_transition_side(
                painter, timeline, from_element, now, width, height, effects,
                1.0 - progress, blur=amount * wave
            )
            self._paint_transition_side(
                painter, timeline, to_element, now, width, height, effects,
                progress, blur=amount * wave
            )
            return

        if name in ("wipe", "glitch"):
            # 用裁剪区域实现擦除；glitch 则把裁剪拆成多条错位条带
            self._paint_transition_side(painter, timeline, from_element, now, width, height, effects, 1.0)
            painter.save()
            if name == "wipe":
                if vector[0] != 0:
                    reveal = width * progress
                    x = 0 if vector[0] < 0 else width - reveal
                    painter.setClipRect(QRectF(x, 0, reveal, height))
                else:
                    reveal = height * progress
                    y = 0 if vector[1] < 0 else height - reveal
                    painter.setClipRect(QRectF(0, y, width, reveal))
            else:
                slices = max(2, int(params.get("slices", 14)))
                intensity = float(params.get("intensity", 0.7))
                path = QPainterPath()
                slice_h = height / slices
                for index in range(slices):
                    if (index / slices) > progress:
                        continue
                    shift = math.sin(index * 12.9898) * intensity * width * 0.08
                    path.addRect(QRectF(shift, index * slice_h, width, slice_h + 1))
                painter.setClipPath(path)
            self._paint_transition_side(painter, timeline, to_element, now, width, height, effects, 1.0)
            painter.restore()
            return

        # 未识别的转场名退化为交叉溶解
        self._paint_transition_side(painter, timeline, from_element, now, width, height, effects, 1.0 - progress)
        self._paint_transition_side(painter, timeline, to_element, now, width, height, effects, progress)

    def _paint_transition_side(
        self,
        painter: QPainter,
        timeline: Dict[str, Any],
        element: Optional[Dict[str, Any]],
        now: float,
        width: int,
        height: int,
        effects: List[Dict[str, Any]],
        alpha: float,
        offset: Tuple[float, float] = (0.0, 0.0),
        scale: float = 1.0,
        rotation: float = 0.0,
        blur: float = 0.0,
    ) -> None:
        """画转场中的一侧。element 不在自身时间范围内时用端点帧代替。"""
        if element is None:
            return
        start = float(element.get("start", 0.0))
        end = start + float(element.get("duration", 0.0))
        sample_time = min(max(now, start), max(start, end - 1e-3))
        local = sample_time - start
        geometry = self._resolve_geometry(element, local, effects, sample_time)
        geometry["x"] += offset[0]
        geometry["y"] += offset[1]
        geometry["scale"] *= scale
        geometry["rotation"] += rotation
        geometry["opacity"] *= max(0.0, min(1.0, alpha))
        geometry["blur"] += blur
        self._paint_video_like(painter, timeline, element, sample_time, width, height, geometry)

    # ------------------------------------------------------------ 全屏特效

    def _paint_screen_effects(
        self,
        painter: QPainter,
        effects: List[Dict[str, Any]],
        now: float,
        width: int,
        height: int,
    ) -> None:
        for effect in effects:
            name = effect.get("name", "")
            params = effect.get("params") or {}
            start = float(effect.get("start", 0.0))
            duration = max(1e-6, float(effect.get("duration", 0.0)))
            progress = min(1.0, max(0.0, (now - start) / duration))

            if name == "flash":
                decay = tl.apply_easing(progress, params.get("decay", "easeOut"))
                alpha = float(params.get("intensity", 0.85)) * (1.0 - decay)
                if alpha <= 0.002:
                    continue
                painter.save()
                painter.setOpacity(min(1.0, alpha))
                painter.fillRect(0, 0, width, height, _parse_color(params.get("color"), "#FFFFFF"))
                painter.restore()
            elif name == "vignette":
                intensity = float(params.get("intensity", 0.5))
                radius = float(params.get("radius", 0.75))
                if intensity <= 0.002:
                    continue
                gradient = QRadialGradient(width / 2, height / 2, max(width, height) * radius)
                gradient.setColorAt(0.0, QColor(0, 0, 0, 0))
                gradient.setColorAt(0.65, QColor(0, 0, 0, int(40 * intensity)))
                gradient.setColorAt(1.0, QColor(0, 0, 0, int(235 * intensity)))
                painter.save()
                painter.setBrush(QBrush(gradient))
                painter.setPen(Qt.NoPen)
                painter.drawRect(0, 0, width, height)
                painter.restore()
            elif name == "rgb_split":
                self._paint_rgb_split(painter, params, width, height)
            elif name == "glitch":
                self._paint_glitch_overlay(painter, params, progress, width, height)

    def _paint_rgb_split(self, painter: QPainter, params: Dict[str, Any], width: int, height: int) -> None:
        """色差：把当前画面偏移后用加色模式叠两层。"""
        device = painter.device()
        if not isinstance(device, QImage):
            return
        offset = float(params.get("offset", 8.0)) * (width / max(1, self._model.width))
        if offset < 0.5:
            return
        angle = math.radians(float(params.get("angle", 0.0)))
        dx = math.cos(angle) * offset
        dy = math.sin(angle) * offset
        snapshot = device.copy()

        for shift, mask in ((1.0, QColor(255, 0, 0)), (-1.0, QColor(0, 128, 255))):
            tinted = QImage(snapshot.size(), QImage.Format_ARGB32_Premultiplied)
            tinted.fill(Qt.transparent)
            tint_painter = QPainter(tinted)
            tint_painter.drawImage(0, 0, snapshot)
            tint_painter.setCompositionMode(QPainter.CompositionMode_Multiply)
            tint_painter.fillRect(tinted.rect(), mask)
            tint_painter.end()

            painter.save()
            painter.setOpacity(0.5)
            painter.setCompositionMode(QPainter.CompositionMode_Plus)
            painter.drawImage(QPointF(dx * shift, dy * shift), tinted)
            painter.restore()

    def _paint_glitch_overlay(
        self,
        painter: QPainter,
        params: Dict[str, Any],
        progress: float,
        width: int,
        height: int,
    ) -> None:
        """故障：把画面切成横条并随机左右错位。"""
        device = painter.device()
        if not isinstance(device, QImage):
            return
        slices = max(2, int(params.get("slices", 12)))
        intensity = float(params.get("intensity", 0.6))
        if intensity <= 0.01:
            return
        snapshot = device.copy()
        slice_h = height / slices
        painter.save()
        for index in range(slices):
            # 用确定性伪随机，保证同一帧多次重画结果一致
            seed = math.sin((index + 1) * 12.9898 + progress * 78.233) * 43758.5453
            noise = seed - math.floor(seed)
            if noise > 0.55:
                continue
            shift = (noise - 0.5) * 2 * intensity * width * 0.12
            source = QRectF(0, index * slice_h, width, slice_h + 1)
            target = QRectF(shift, index * slice_h, width, slice_h + 1)
            painter.drawImage(target, snapshot, source)
        painter.restore()
