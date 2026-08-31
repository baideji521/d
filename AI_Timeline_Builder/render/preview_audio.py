"""预览音频：给 GUI 播放头配上真实声音。

# 为什么不是「实时混音」

预览需要的是「拖到 12.350s 立刻听到那一刻的声音」。要在 Qt 里做真正的实时
多轨混音，得自己维护解码器 + 环形缓冲 + 时钟同步，那是一套播放器内核，
不是这个工具该有的复杂度。

所以这里走**预混一份 WAV**的路子：

    Timeline JSON
        ↓  audio_jobs()          纯函数，把每个出声元素翻译成一段 ffmpeg 任务
        ↓  mix_command()         一次 ffmpeg 调用，atrim/atempo/volume/afade/adelay/amix
        ↓  预览混音 WAV（缓存在 .cache 下）
        ↓  QMediaPlayer          seek / play / pause 都是毫秒级

音频是纯音频转码，没有画面编码，成本比视频渲染低一到两个数量级：
一条十几秒、十来个元素的时间线通常几百毫秒混完。混音在后台线程里跑，
主线程永不阻塞（和抽帧线程一样的规矩）。

# 明确不做的事

- **不调用 Remotion**。指令第六条：预览必须是轻量播放器，
  seek 一下就重跑一次 Remotion 是绝对不行的。
- **不逐帧调 ffmpeg**。整条时间线只混一次，改动后才重混。

# 语义必须和 Remotion 对齐

对齐的依据是 `remotion/src/elements/AudioLayer.tsx` 与 `VideoLayer.tsx`：

- `audio` 元素：`volume = (element.volume ?? 1) × master`，`fade.in/out` 线性，
  `source.start → trimBefore`，`speed → playbackRate`
- `video` 元素：内嵌音轨，`audio.enabled === false` 或 `master <= 0` → 静音，
  `volume = (audio.volume ?? 1) × master`，`source.start/end → trimBefore/After`
- `overlay` / `freeze`：Remotion 侧写死 `muted`，这里也必须不出声
- `master_volume` 上限 4（`resolveVolume` 的 clamp），0 = 整片静音

一处偏差要如实记下：`atempo` 是保持音高的变速，浏览器 `playbackRate`
默认也保持音高（`preservesPitch`），两者语义一致；但重采样算法不同，
所以变速片段的音色不会逐样本相同。预览是监听用途，这个差异可接受。
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from core import timeline as tl

#: 预览混音采样率 / 声道。48kHz 立体声与最终成片一致，便于对照响度。
MIX_SAMPLE_RATE = 48000
MIX_CHANNELS = 2

#: 预览混音文件名（放在预览缓存目录下）
MIX_FILENAME = "preview_mix.wav"

#: Remotion 侧 `masterVolume()` 的 clamp 上限
MASTER_VOLUME_CEILING = 4.0

#: `atempo` 单级可用范围。超出要串联多级，超太多就如实放弃变速。
ATEMPO_MIN = 0.5
ATEMPO_MAX = 2.0

#: 会出声的元素类型。overlay / freeze 在 Remotion 侧写死 muted，不在此列。
SOUNDING_TYPES = ("video", "audio")


def _clamp_master(timeline: Dict[str, Any]) -> float:
    """和 Remotion `masterVolume()` 完全一致：非数字回 1，其余 clamp 到 0..4。"""
    raw = (timeline.get("meta") or {}).get("master_volume")
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return tl.DEFAULT_MASTER_VOLUME
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return tl.DEFAULT_MASTER_VOLUME
    if value != value or value in (float("inf"), float("-inf")):  # NaN / Inf
        return tl.DEFAULT_MASTER_VOLUME
    return max(0.0, min(MASTER_VOLUME_CEILING, value))


def _source_span(element: Dict[str, Any]) -> Tuple[float, float]:
    """源区间 (start, end)。缺 source 时按 0..duration 处理，和 Remotion 一致。"""
    source = element.get("source")
    duration = tl.as_seconds(element.get("duration"))
    if not isinstance(source, dict):
        return 0.0, max(0.0, duration)
    start = tl.as_seconds(source.get("start"))
    end = source.get("end")
    if end is None:
        return start, start + max(0.0, duration)
    return start, tl.as_seconds(end)


def audio_jobs(
    timeline: Dict[str, Any],
    resolve_path: Callable[[str], str],
    has_audio: Optional[Callable[[str], bool]] = None,
) -> List[Dict[str, Any]]:
    """把时间线里所有**真的会出声**的元素翻译成混音任务。

    纯函数：不碰文件系统（路径与「有没有音轨」都由调用方注入），
    所以可以直接用假数据做单元测试。

    返回的每一项：

        element_id  来源元素（报告 / 调试用）
        path        音频来源文件
        source_start / take   要从源文件里取的区间（秒，未变速）
        speed       变速倍率
        volume      最终线性音量（已乘 master）
        fade_in / fade_out    淡入淡出秒数（只有 audio 元素有）
        start       在时间线上的落点（秒）
        duration    在时间线上占的长度（秒）

    被跳过的情况（都是「本来就不该出声」，不是偷懒）：
    - 类型不在 SOUNDING_TYPES（文字 / 字幕 / 特效 / 转场 / overlay / freeze）
    - `audio.enabled == false`（显式关掉了这一路声音）
    - 最终音量 <= 0（元素静音或 `master_volume == 0`）
    - 素材文件不存在，或素材根本没有音轨
    """
    master = _clamp_master(timeline)
    jobs: List[Dict[str, Any]] = []
    for element in timeline.get("elements", []) or []:
        if not isinstance(element, dict):
            continue
        kind = str(element.get("type") or "")
        if kind not in SOUNDING_TYPES:
            continue

        duration = tl.as_seconds(element.get("duration"))
        if duration <= 0:
            continue

        if kind == "video":
            audio = element.get("audio")
            if isinstance(audio, dict) and audio.get("enabled") is False:
                continue
            element_volume = tl.DEFAULT_AUDIO["volume"]
            if isinstance(audio, dict) and "volume" in audio:
                element_volume = tl.as_seconds(audio.get("volume"))
            fade_in = 0.0
            fade_out = 0.0
        else:
            element_volume = tl.effective_volume(element)
            fade = tl.effective_fade(element)
            fade_in = max(0.0, tl.as_seconds(fade.get("in")))
            fade_out = max(0.0, tl.as_seconds(fade.get("out")))

        volume = max(0.0, element_volume) * master
        if volume <= 0:
            continue

        asset_id = str(element.get("asset") or "")
        path = resolve_path(asset_id) if asset_id else ""
        if not path:
            continue
        if has_audio is not None and not has_audio(asset_id):
            continue

        speed = max(0.01, tl.effective_speed(element))
        source_start, source_end = _source_span(element)
        # 时间线上占 duration 秒，按 speed 倍率消耗的源长度就是 duration × speed。
        # 用它而不是 source_end - source_start：两者理论上相等，但用户手改过
        # JSON 时可能不一致，播放头看到的长度以 duration 为准。
        take = duration * speed
        if source_end > source_start:
            take = min(take, source_end - source_start)
        if take <= 0:
            continue

        jobs.append(
            {
                "element_id": str(element.get("id") or ""),
                "path": path,
                "source_start": round(source_start, 4),
                "take": round(take, 4),
                "speed": round(speed, 4),
                "volume": round(volume, 4),
                "fade_in": round(min(fade_in, duration), 4),
                "fade_out": round(min(fade_out, duration), 4),
                "start": round(tl.as_seconds(element.get("start")), 4),
                "duration": round(duration, 4),
            }
        )
    jobs.sort(key=lambda job: (job["start"], job["element_id"]))
    return jobs


def mix_signature(jobs: List[Dict[str, Any]], duration: float) -> str:
    """混音任务的指纹。只有它变了才需要重混。

    指纹只包含**影响声音**的字段，所以改标题颜色、拖动画面位置、
    换分辨率都不会触发重混。
    """
    payload = json.dumps(
        {"jobs": jobs, "duration": round(float(duration), 4)},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _atempo_chain(speed: float) -> List[str]:
    """把任意倍率拆成若干级 atempo（单级只支持 0.5~2.0）。

    拆不出来（例如 0.05 倍这种极端值）时返回空列表，
    调用方按「不变速」处理并如实记录，不假装做到了。
    """
    if abs(speed - 1.0) < 1e-6:
        return []
    stages: List[str] = []
    remaining = float(speed)
    for _ in range(4):
        if ATEMPO_MIN <= remaining <= ATEMPO_MAX:
            stages.append(f"atempo={remaining:.6f}")
            return stages
        if remaining > ATEMPO_MAX:
            stages.append(f"atempo={ATEMPO_MAX:.6f}")
            remaining /= ATEMPO_MAX
        else:
            stages.append(f"atempo={ATEMPO_MIN:.6f}")
            remaining /= ATEMPO_MIN
    return []


def build_filter_complex(jobs: List[Dict[str, Any]]) -> str:
    """生成 ffmpeg filter_complex 字符串。

    每一路：截取 → 变速 → 音量 → 淡入淡出 → 延迟到落点 → 统一采样率；
    最后 `amix=normalize=0` 相加。**normalize 必须是 0**：
    默认的 normalize=1 会把每一路都除以路数，两条音轨叠加会莫名变小，
    和 Remotion 的「直接相加」语义不符。
    """
    chains: List[str] = []
    labels: List[str] = []
    for index, job in enumerate(jobs):
        steps = [
            f"atrim=start={job['source_start']:.4f}:duration={job['take']:.4f}",
            "asetpts=N/SR/TB",
        ]
        steps.extend(_atempo_chain(float(job["speed"])))
        if abs(float(job["volume"]) - 1.0) > 1e-6:
            steps.append(f"volume={float(job['volume']):.4f}")
        fade_in = float(job["fade_in"])
        if fade_in > 0:
            steps.append(f"afade=t=in:st=0:d={fade_in:.4f}")
        fade_out = float(job["fade_out"])
        if fade_out > 0:
            start = max(0.0, float(job["duration"]) - fade_out)
            steps.append(f"afade=t=out:st={start:.4f}:d={fade_out:.4f}")
        delay_ms = int(round(float(job["start"]) * 1000))
        if delay_ms > 0:
            steps.append(f"adelay={delay_ms}:all=1")
        steps.append(f"aresample={MIX_SAMPLE_RATE}")
        label = f"a{index}"
        chains.append(f"[{index}:a]" + ",".join(steps) + f"[{label}]")
        labels.append(f"[{label}]")

    mix = (
        "".join(labels)
        + f"amix=inputs={len(jobs)}:normalize=0:dropout_transition=0[mix]"
    )
    return ";".join(chains + [mix])


def mix_command(
    ffmpeg_path: str,
    jobs: List[Dict[str, Any]],
    duration: float,
    out_path: str,
) -> List[str]:
    """完整的 ffmpeg 命令行。jobs 为空时返回空列表（没有声音就不该跑 ffmpeg）。"""
    if not ffmpeg_path or not jobs or duration <= 0:
        return []
    command = [ffmpeg_path, "-y", "-loglevel", "error"]
    for job in jobs:
        command += ["-i", job["path"]]
    command += [
        "-filter_complex",
        build_filter_complex(jobs),
        "-map",
        "[mix]",
        "-t",
        f"{float(duration):.3f}",
        "-ar",
        str(MIX_SAMPLE_RATE),
        "-ac",
        str(MIX_CHANNELS),
        "-c:a",
        "pcm_s16le",
        out_path,
    ]
    return command


# ---------------------------------------------------------------- Qt 层

try:  # pragma: no cover - 取决于运行环境
    from PyQt5.QtCore import QObject, QThread, QTimer, QUrl, pyqtSignal
    from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer

    _QT_AUDIO_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover - 缺 QtMultimedia 时
    QObject = object  # type: ignore[assignment,misc]
    QThread = object  # type: ignore[assignment,misc]
    _QT_AUDIO_IMPORT_ERROR = str(exc)


if not _QT_AUDIO_IMPORT_ERROR:  # pragma: no branch

    class MixWorker(QThread):
        """在后台线程里混一份预览音频。

        和抽帧线程同一套规矩：`stop()` 之后不再启新子进程，
        正在跑的 ffmpeg 直接杀掉 —— 否则退出时 Qt 会去销毁一个仍在运行的
        QThread，那是进程级 fastfail。
        """

        mixDone = pyqtSignal(str, str, str)  # signature, path, error

        def __init__(self, parent: Optional[QObject] = None) -> None:
            super().__init__(parent)
            from render.ffmpeg import FFmpeg

            self._ffmpeg = FFmpeg()
            self._pending: Optional[Tuple[str, List[str], str]] = None
            self._stopped = False

        def submit(self, signature: str, command: List[str], out_path: str) -> None:
            self._pending = (signature, list(command), out_path)

        def stop(self) -> None:
            self._stopped = True
            self._pending = None
            self._ffmpeg.cancel()

        def run(self) -> None:  # noqa: D102
            job = self._pending
            self._pending = None
            if not job or self._stopped:
                return
            signature, command, out_path = job
            if not command:
                self.mixDone.emit(signature, "", "没有需要混音的音频元素")
                return
            try:
                os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
                result = self._ffmpeg.run_command(command, timeout=120)
            except OSError as exc:
                self.mixDone.emit(signature, "", f"混音失败：{exc}")
                return
            if self._stopped:
                return
            if result is None or result.returncode != 0:
                detail = ""
                if result is not None:
                    detail = result.stderr.decode("utf-8", errors="replace").strip()
                self.mixDone.emit(signature, "", detail or "ffmpeg 混音失败")
                return
            self.mixDone.emit(signature, out_path, "")

    class PreviewAudio(QObject):
        """预览音频通道：混音 + 播放 + 跟随播放头。

        对外只有六个动作：`refresh()` / `play(at)` / `pause()` / `seek(at)`
        / `sync_volume()` / `shutdown()`。它自己判断要不要重混，
        调用方（PreviewWidget）不需要关心缓存和线程。
        """

        stateChanged = pyqtSignal()

        def __init__(self, model, assets, cache_dir: str, parent: Optional[QObject] = None) -> None:
            super().__init__(parent)
            self._model = model
            self._assets = assets
            self._cache_dir = cache_dir
            self._mix_path = os.path.join(cache_dir, MIX_FILENAME)
            self._signature = ""
            self._ready_signature = ""
            self._error = ""
            self._closed = False
            self._pending_play_at: Optional[float] = None
            self._worker: Optional[MixWorker] = None

            self._player = QMediaPlayer(self)
            self._player.setNotifyInterval(20)

            # 时间线变了就标脏，但不立刻重混 —— 连续拖动会触发几十次变更，
            # 攒 250ms 只混最后一次。
            self._debounce = QTimer(self)
            self._debounce.setSingleShot(True)
            self._debounce.setInterval(250)
            self._debounce.timeout.connect(self._start_mix)

            model.timelineChanged.connect(self.invalidate)
            model.elementUpdated.connect(lambda _id: self.invalidate())

        # ------------------------------------------------------ 状态

        def available(self) -> bool:
            """有没有可播的混音。"""
            return bool(self._ready_signature) and os.path.isfile(self._mix_path)

        def status_text(self) -> str:
            if self._error:
                return f"预览音频不可用：{self._error}"
            if self.available():
                return "预览音频就绪"
            return "预览音频准备中"

        def last_error(self) -> str:
            return self._error

        def position_seconds(self) -> float:
            """播放器当前音频位置（秒）。音视频同步测试量的就是它。"""
            return max(0.0, self._player.position() / 1000.0)

        # ------------------------------------------------------ 混音

        def invalidate(self) -> None:
            """时间线可能改了：标脏，攒一会儿再混。"""
            if self._closed:
                return
            self._debounce.start()

        def refresh(self, force: bool = False) -> None:
            """立刻重混（force=True 时无视指纹）。"""
            if force:
                self._ready_signature = ""
            self._start_mix()

        def _start_mix(self) -> None:
            if self._closed:
                return
            timeline = self._model.timeline
            duration = tl.timeline_duration(timeline)
            jobs = audio_jobs(
                timeline,
                self._resolve_path,
                self._asset_has_audio,
            )
            signature = mix_signature(jobs, duration)
            self._signature = signature
            if signature == self._ready_signature and os.path.isfile(self._mix_path):
                return  # 声音没变，不重混

            if not jobs:
                # 整片没有声音是**合法状态**（比如只有文字，或者 master_volume=0），
                # 不是错误：停掉播放器，报告里也不写 error。
                self._ready_signature = ""
                self._error = ""
                self._player.stop()
                self._player.setMedia(QMediaContent())
                self.stateChanged.emit()
                return

            if self._worker is not None and self._worker.isRunning():
                return  # 上一轮还在混，等它结束时会自动再检查一次
            from render.ffmpeg import FFmpeg

            ffmpeg_path = FFmpeg().ffmpeg_path or ""
            command = mix_command(ffmpeg_path, jobs, duration, self._mix_path)
            if not command:
                self._error = "没找到 ffmpeg，预览音频不可用"
                self.stateChanged.emit()
                return
            worker = MixWorker(self)
            worker.submit(signature, command, self._mix_path)
            worker.mixDone.connect(self._on_mix_done)
            worker.finished.connect(lambda: self._drop_worker(worker))
            self._worker = worker
            worker.start()

        def _drop_worker(self, worker: "MixWorker") -> None:
            if self._worker is worker:
                self._worker = None
            worker.deleteLater()
            if not self._closed and self._signature != self._ready_signature:
                self._debounce.start()

        def _on_mix_done(self, signature: str, path: str, error: str) -> None:
            if self._closed:
                return
            if error or not path:
                self._error = error or "混音失败"
                self._ready_signature = ""
                self.stateChanged.emit()
                return
            self._error = ""
            self._ready_signature = signature
            # 换文件必须先清空 media，否则 Qt 可能继续用旧的解码器
            self._player.setMedia(QMediaContent())
            self._player.setMedia(QMediaContent(QUrl.fromLocalFile(os.path.abspath(path))))
            at = self._pending_play_at
            self._pending_play_at = None
            if at is not None:
                self._play_now(at)
            else:
                self.seek(self._model.playhead)
            self.stateChanged.emit()

        # ------------------------------------------------------ 素材解析

        def _resolve_path(self, asset_id: str) -> str:
            """素材 id → 绝对路径。文件不存在就返回空串（调用方会跳过）。"""
            try:
                path = self._assets.abs_path(asset_id)
            except Exception:
                return ""
            return path if path and os.path.isfile(path) else ""

        def _asset_has_audio(self, asset_id: str) -> bool:
            """素材有没有音轨。

            用素材清单里 ffprobe 探测出来的 `has_audio`；清单里没这一项时
            **按有音轨处理** —— 宁可让 ffmpeg 报一次错，也不要把本该有声的
            片段悄悄丢掉（丢掉是听不出来的，报错是能看见的）。
            """
            try:
                asset = self._assets.get(asset_id) or {}
            except Exception:
                return True
            if "has_audio" not in asset:
                return True
            return bool(asset.get("has_audio"))

        # ------------------------------------------------------ 播放

        def play(self, at: float) -> None:
            """从 at 秒开始播。混音还没好就先记下来，好了立刻接上。"""
            if self._closed:
                return
            if not self.available():
                self._pending_play_at = max(0.0, float(at))
                self._start_mix()
                return
            self._play_now(at)

        def _play_now(self, at: float) -> None:
            self._player.setPosition(int(max(0.0, float(at)) * 1000))
            self._player.play()

        def pause(self) -> None:
            if not self._closed:
                self._pending_play_at = None
                self._player.pause()

        def seek(self, at: float) -> None:
            """跟随播放头。播放头跳到 12.350s，音频也跳到 12.350s。"""
            if self._closed or not self.available():
                return
            self._player.setPosition(int(max(0.0, float(at)) * 1000))

        def is_playing(self) -> bool:
            return self._player.state() == QMediaPlayer.PlayingState

        def sync_volume(self) -> None:
            """`meta.master_volume` 已经混进 WAV 了，播放器这一级保持 100%。

            为什么不用播放器音量去做 master_volume：那样预览听到的和导出的
            就是两条不同的算法，用户调 0.5 听着像 0.5、导出却是别的值。
            现在两边都走 `resolveVolume` 的同一套语义。
            """
            self._player.setVolume(100)

        # ------------------------------------------------------ 收尾

        def shutdown(self) -> None:
            """任何退出路径都必须走到这里，且可重复调用。"""
            if self._closed:
                return
            self._closed = True
            self._debounce.stop()
            self._player.stop()
            self._player.setMedia(QMediaContent())
            worker = self._worker
            if worker is not None:
                worker.stop()
                if not worker.wait(3000):
                    worker.terminate()
                    worker.wait(1000)
                self._worker = None

else:  # pragma: no cover - 没有 QtMultimedia 的环境

    class PreviewAudio:  # type: ignore[no-redef]
        """QtMultimedia 缺失时的空实现：接口一致，行为是「明确不可用」。

        这样 GUI 代码不需要到处写 if；报告里也能如实写出原因，
        而不是让人以为「预览有声音只是没听见」。
        """

        def __init__(self, *_args, **_kwargs) -> None:
            self._error = f"当前环境缺少 PyQt5.QtMultimedia：{_QT_AUDIO_IMPORT_ERROR}"

        def available(self) -> bool:
            return False

        def status_text(self) -> str:
            return f"预览音频不可用：{self._error}"

        def last_error(self) -> str:
            return self._error

        def position_seconds(self) -> float:
            return 0.0

        def invalidate(self) -> None:
            return None

        def refresh(self, force: bool = False) -> None:
            return None

        def play(self, at: float) -> None:
            return None

        def pause(self) -> None:
            return None

        def seek(self, at: float) -> None:
            return None

        def is_playing(self) -> bool:
            return False

        def sync_volume(self) -> None:
            return None

        def shutdown(self) -> None:
            return None
