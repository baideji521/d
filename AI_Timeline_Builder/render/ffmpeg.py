"""FFmpeg / FFprobe 封装。

只做三件事：
1. 探测媒体信息（时长、分辨率、fps、是否有音轨、是否有 Alpha）
2. 抽取某一时刻的画面（预览与缩略图共用）
3. 定位 ffmpeg 可执行文件

所有调用都是同步阻塞的，必须由后台线程调用，不允许在 GUI 主线程里直接用。
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Dict, List, Optional

# Windows 下隐藏黑色控制台窗口
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
AUDIO_EXTS = {".wav", ".mp3", ".aac", ".m4a", ".flac", ".ogg"}
FONT_EXTS = {".ttf", ".otf", ".woff", ".woff2"}

# winget 安装 Gyan.FFmpeg 后的常见落点，PATH 未刷新时用来兜底
_FALLBACK_DIRS = [
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links"),
    r"C:\Program Files\ffmpeg\bin",
]


def _find_binary(name: str) -> Optional[str]:
    """在 PATH 与常见安装目录里找 ffmpeg / ffprobe。"""
    exe = f"{name}.exe" if os.name == "nt" else name
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(directory.strip('"'), exe)
        if os.path.isfile(candidate):
            return candidate
    for directory in _FALLBACK_DIRS:
        candidate = os.path.join(directory, exe)
        if os.path.isfile(candidate):
            return candidate
    # winget 的 Packages 目录层级不固定，做一次浅层扫描
    packages = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
    if os.path.isdir(packages):
        for entry in os.listdir(packages):
            if "FFmpeg" not in entry:
                continue
            for root, _dirs, files in os.walk(os.path.join(packages, entry)):
                if exe in files:
                    return os.path.join(root, exe)
    return None


class FFmpeg:
    """ffmpeg / ffprobe 的薄封装。找不到可执行文件时所有方法安全降级。"""

    def __init__(self) -> None:
        self.ffmpeg_path = _find_binary("ffmpeg")
        self.ffprobe_path = _find_binary("ffprobe")

    @property
    def available(self) -> bool:
        return bool(self.ffmpeg_path and self.ffprobe_path)

    def status_text(self) -> str:
        if self.available:
            return f"FFmpeg 就绪：{self.ffmpeg_path}"
        return "未找到 FFmpeg，素材时长/分辨率探测与画面预览不可用（请安装 FFmpeg 并加入 PATH）"

    # ------------------------------------------------------------ 探测

    def probe(self, path: str) -> Dict[str, Any]:
        """返回归一化的媒体信息。失败时返回空 dict。"""
        if not self.ffprobe_path or not os.path.isfile(path):
            return {}
        command = [
            self.ffprobe_path,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            path,
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                timeout=30,
                creationflags=_CREATE_NO_WINDOW,
            )
            if result.returncode != 0:
                return {}
            data = json.loads(result.stdout.decode("utf-8", errors="replace"))
        except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
            return {}

        info: Dict[str, Any] = {}
        streams: List[Dict[str, Any]] = data.get("streams", [])
        fmt: Dict[str, Any] = data.get("format", {})

        duration = fmt.get("duration")
        if duration:
            try:
                info["duration"] = round(float(duration), 3)
            except ValueError:
                pass

        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

        if video_stream:
            info["width"] = int(video_stream.get("width") or 0)
            info["height"] = int(video_stream.get("height") or 0)
            info["fps"] = self._parse_fps(video_stream.get("r_frame_rate"))
            pix_fmt = str(video_stream.get("pix_fmt") or "")
            # WebM/VP9 的 Alpha 是独立通道，ffprobe 仍然报 yuv420p，
            # 只有容器里的 alpha_mode 标签能说明它带透明，两个条件都要看。
            alpha_mode = str((video_stream.get("tags") or {}).get("alpha_mode") or "")
            info["has_alpha"] = (
                any(token in pix_fmt for token in ("yuva", "rgba", "argb", "bgra"))
                or alpha_mode == "1"
            )

            if "duration" not in info and video_stream.get("duration"):
                try:
                    info["duration"] = round(float(video_stream["duration"]), 3)
                except ValueError:
                    pass
        info["has_audio"] = audio_stream is not None
        return info

    @staticmethod
    def _parse_fps(raw: Optional[str]) -> float:
        """把 "30000/1001" 这类分数转成浮点 fps。"""
        if not raw:
            return 0.0
        try:
            if "/" in raw:
                numerator, denominator = raw.split("/", 1)
                denominator_value = float(denominator)
                if denominator_value == 0:
                    return 0.0
                return round(float(numerator) / denominator_value, 3)
            return round(float(raw), 3)
        except ValueError:
            return 0.0

    # ------------------------------------------------------------ 抽帧

    def extract_frame(
        self,
        path: str,
        time_seconds: float,
        output_path: str,
        width: int = 0,
    ) -> bool:
        """抽取指定时刻的一帧写成 PNG。用于缩略图与预览。"""
        if not self.ffmpeg_path or not os.path.isfile(path):
            return False
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        command = [
            self.ffmpeg_path,
            "-y",
            "-loglevel",
            "error",
            # -ss 放在 -i 前面用关键帧快速定位，预览要的是速度
            "-ss",
            f"{max(0.0, float(time_seconds)):.3f}",
            "-i",
            path,
            "-frames:v",
            "1",
        ]
        if width > 0:
            command += ["-vf", f"scale={int(width)}:-2:flags=fast_bilinear"]
        command += ["-f", "image2", output_path]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                timeout=30,
                creationflags=_CREATE_NO_WINDOW,
            )
        except (subprocess.SubprocessError, OSError):
            return False
        return result.returncode == 0 and os.path.isfile(output_path)

    def extract_sequence(
        self,
        path: str,
        start_seconds: float,
        count: int,
        quantum: float,
        output_dir: str,
        width: int = 0,
    ) -> List[str]:
        """一次调用抽出连续多帧，返回按时间顺序的 PNG 路径列表。

        预览播放时逐帧调用 ffmpeg 太慢（每次进程启动 + seek 约 0.3 秒），
        用 fps 滤镜一次抽一批，单帧成本能降到几十毫秒。
        文件名形如 seq_0001.png，调用方负责改成自己的缓存命名。
        """
        if not self.ffmpeg_path or not os.path.isfile(path) or count <= 0 or quantum <= 0:
            return []
        os.makedirs(output_dir, exist_ok=True)
        pattern = os.path.join(output_dir, "seq_%04d.png")
        for stale in os.listdir(output_dir):
            if stale.startswith("seq_") and stale.endswith(".png"):
                try:
                    os.remove(os.path.join(output_dir, stale))
                except OSError:
                    pass

        vf = f"fps=1/{quantum:.6f}"
        if width > 0:
            vf += f",scale={int(width)}:-2:flags=fast_bilinear"
        command = [
            self.ffmpeg_path,
            "-y",
            "-loglevel",
            "error",
            "-ss",
            f"{max(0.0, float(start_seconds)):.3f}",
            "-i",
            path,
            "-t",
            f"{count * quantum:.3f}",
            "-vf",
            vf,
            "-frames:v",
            str(int(count)),
            "-f",
            "image2",
            pattern,
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                timeout=60,
                creationflags=_CREATE_NO_WINDOW,
            )
        except (subprocess.SubprocessError, OSError):
            return []
        if result.returncode != 0:
            return []
        files = sorted(
            os.path.join(output_dir, name)
            for name in os.listdir(output_dir)
            if name.startswith("seq_") and name.endswith(".png")
        )
        return files

    def extract_waveform(self, path: str, output_path: str, width: int = 600, height: int = 60) -> bool:

        """生成音频波形图，Timeline 上的音频块用它当背景。"""
        if not self.ffmpeg_path or not os.path.isfile(path):
            return False
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        command = [
            self.ffmpeg_path,
            "-y",
            "-loglevel",
            "error",
            "-i",
            path,
            "-filter_complex",
            f"showwavespic=s={int(width)}x{int(height)}:colors=#5aa9e6",
            "-frames:v",
            "1",
            output_path,
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                timeout=60,
                creationflags=_CREATE_NO_WINDOW,
            )
        except (subprocess.SubprocessError, OSError):
            return False
        return result.returncode == 0 and os.path.isfile(output_path)


def guess_asset_type(path: str, folder_hint: str = "") -> str:
    """根据扩展名与所在目录猜素材类型。"""
    ext = os.path.splitext(path)[1].lower()
    hint = folder_hint.lower()
    if ext in FONT_EXTS:
        return "font"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in IMAGE_EXTS:
        # overlays / effects 目录里的图片按 overlay 归类，方便素材库分栏
        if "overlay" in hint or "effect" in hint or "transition" in hint:
            return "overlay"
        return "image"
    if ext in VIDEO_EXTS:
        if "overlay" in hint or "effect" in hint or "transition" in hint:
            return "overlay"
        return "video"
    return ""
