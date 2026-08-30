"""文本转语音（TTS）：把文字合成成配音 WAV，登记进素材库后落到 A2 人声轨。

v1 不接任何 AI 云服务，用 Windows 自带的 System.Speech（.NET）离线合成：
不联网、不需要 API Key、不需要额外 pip 包，装了系统语音包就能用。
本机可用音色由系统决定（中文一般是 Microsoft Huihui，英文是 Zira）。

合成产物统一落在 assets/audio/tts/，随后走 AssetManager.import_files()
按普通音频素材登记（原地登记，不再复制），因此 Timeline JSON 里
仍然只出现 asset id，绝不出现文件路径。

合成本身是起子进程 + 写文件，绝不能放在主线程，所以有 TtsWorker。
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import QThread, pyqtSignal

# 合成产物目录（相对项目根）
TTS_SUBDIR = os.path.join("assets", "audio", "tts")
# 合成脚本与本模块同目录
SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_synth.ps1")

# 语速范围（System.Speech 的 Rate）与音量范围
RATE_MIN, RATE_MAX = -10, 10
VOLUME_MIN, VOLUME_MAX = 0, 100

# 起子进程时不要弹黑窗
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

_VOICE_CACHE: Optional[List[Dict[str, str]]] = None


def _powershell() -> str:
    """返回 PowerShell 可执行文件路径。"""
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return candidate if os.path.isfile(candidate) else "powershell"


def _run_script(args: List[str], timeout: int = 120) -> subprocess.CompletedProcess:
    command = [
        _powershell(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        SCRIPT_PATH,
    ] + args
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=_CREATE_NO_WINDOW,
    )


def available() -> bool:
    """本机能不能做 TTS。"""
    return os.name == "nt" and os.path.isfile(SCRIPT_PATH) and bool(list_voices())


def list_voices(refresh: bool = False) -> List[Dict[str, str]]:
    """列出系统里已安装的音色。结果会缓存，探测一次约 0.3 秒。"""
    global _VOICE_CACHE
    if _VOICE_CACHE is not None and not refresh:
        return _VOICE_CACHE
    voices: List[Dict[str, str]] = []
    if os.name == "nt" and os.path.isfile(SCRIPT_PATH):
        try:
            result = _run_script(["-ListVoices"], timeout=30)
            for line in (result.stdout or "").splitlines():
                parts = line.strip().split("\t")
                if len(parts) >= 3 and parts[0]:
                    voices.append({"name": parts[0], "culture": parts[1], "gender": parts[2]})
        except (OSError, subprocess.SubprocessError):
            voices = []
    _VOICE_CACHE = voices
    return voices


def default_voice(prefer_chinese: bool = True) -> str:
    """挑一个默认音色：优先中文。"""
    voices = list_voices()
    if not voices:
        return ""
    if prefer_chinese:
        for voice in voices:
            if voice.get("culture", "").lower().startswith("zh"):
                return voice["name"]
    return voices[0]["name"]


def safe_stem(text: str, limit: int = 18) -> str:
    """用文本前几个字做文件名，去掉不能进文件名的字符。"""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]+', "", text).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:limit] or "voice"


def output_path(root: str, text: str) -> str:
    """生成不会撞名的输出路径 assets/audio/tts/tts_时间戳_文本片段.wav。"""
    directory = os.path.join(root, TTS_SUBDIR)
    os.makedirs(directory, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    candidate = os.path.join(directory, f"tts_{stamp}_{safe_stem(text)}.wav")
    index = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"tts_{stamp}_{safe_stem(text)}_{index}.wav")
        index += 1
    return candidate


def synthesize(
    text: str,
    target_path: str,
    voice: str = "",
    rate: int = 0,
    volume: int = 100,
    cache_dir: str = "",
) -> str:
    """同步合成一段配音，成功返回空字符串，失败返回错误说明。

    文本先写成 UTF-8 临时文件再交给脚本读，
    这样中文和引号都不会被命令行转义搞坏。
    """
    content = (text or "").strip()
    if not content:
        return "文本是空的，没有可合成的内容"
    if os.name != "nt":
        return "内置 TTS 只支持 Windows（用的是系统自带语音合成）"
    if not os.path.isfile(SCRIPT_PATH):
        return f"找不到合成脚本：{SCRIPT_PATH}"

    # 文本临时文件默认放系统临时目录，别把 assets/ 弄脏
    work_dir = cache_dir or tempfile.gettempdir()
    os.makedirs(work_dir, exist_ok=True)
    text_file = os.path.join(work_dir, f"tts_text_{os.getpid()}_{int(time.time() * 1000)}.txt")
    try:
        with open(text_file, "w", encoding="utf-8") as handle:
            handle.write(content)

        args = [
            "-TextPath",
            text_file,
            "-OutPath",
            target_path,
            "-Rate",
            str(max(RATE_MIN, min(RATE_MAX, int(rate)))),
            "-Volume",
            str(max(VOLUME_MIN, min(VOLUME_MAX, int(volume)))),
        ]
        if voice:
            args += ["-VoiceName", voice]

        try:
            result = _run_script(args, timeout=300)
        except subprocess.TimeoutExpired:
            return "合成超时（文本可能太长），已放弃"
        except OSError as exc:
            return f"启动语音合成失败：{exc}"

        if result.returncode != 0 or not os.path.isfile(target_path):
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            reason = detail[0] if detail else f"退出码 {result.returncode}"
            return f"语音合成失败：{reason}"
        if os.path.getsize(target_path) < 1024:
            return "语音合成产物过小，可能是音色不支持该文本"
        return ""
    finally:
        try:
            os.remove(text_file)
        except OSError:
            pass


class TtsWorker(QThread):
    """后台合成线程。合成要起 PowerShell 子进程，绝不能占着主线程。"""

    progress = pyqtSignal(str)
    # 成功：(wav 绝对路径, 发起时带的上下文)
    finished_tts = pyqtSignal(str, dict)
    failed = pyqtSignal(str)

    def __init__(
        self,
        root: str,
        text: str,
        voice: str,
        rate: int,
        volume: int,
        context: Optional[Dict[str, Any]] = None,
        target_path: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._root = root
        self._text = text
        self._voice = voice
        self._rate = int(rate)
        self._volume = int(volume)
        self._context = dict(context or {})
        self._target = target_path

    def run(self) -> None:  # noqa: D102
        target = self._target or output_path(self._root, self._text)
        self.progress.emit(f"正在合成配音：{safe_stem(self._text, 24)} …")
        error = synthesize(
            self._text,
            target,
            voice=self._voice,
            rate=self._rate,
            volume=self._volume,
            cache_dir=os.path.join(self._root, ".cache", "tts"),
        )
        if error:
            self.failed.emit(error)
            return
        self.finished_tts.emit(target, self._context)


class TtsBatchWorker(QThread):
    """批量合成：一行字幕一个 WAV，串行跑完再一次性回报。

    用于「导入剪映字幕 → 逐行转配音」。串行是故意的：
    同时开多个 PowerShell 合成进程既不会更快，还容易抢占音频设备。
    """

    progress = pyqtSignal(str)
    # 每行完成：(行号, 总行数, wav 路径)
    lineDone = pyqtSignal(int, int, str)
    # 全部结束：(成功的行列表, 失败说明列表)
    # 成功行形如 {"index","text","start","end","path"}
    finished_batch = pyqtSignal(list, list)

    def __init__(
        self,
        root: str,
        lines: List[Dict[str, Any]],
        voice: str,
        rate: int,
        volume: int,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._root = root
        self._lines = [dict(line) for line in lines]
        self._voice = voice
        self._rate = int(rate)
        self._volume = int(volume)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:  # noqa: D102
        done: List[Dict[str, Any]] = []
        errors: List[str] = []
        total = len(self._lines)
        cache_dir = os.path.join(self._root, ".cache", "tts")
        for position, line in enumerate(self._lines, start=1):
            if self._cancelled:
                errors.append(f"已取消，剩余 {total - position + 1} 行未合成")
                break
            text = str(line.get("text", "")).strip()
            if not text:
                continue
            target = output_path(self._root, text)
            self.progress.emit(f"合成第 {position}/{total} 行：{safe_stem(text, 20)} …")
            error = synthesize(
                text,
                target,
                voice=self._voice,
                rate=self._rate,
                volume=self._volume,
                cache_dir=cache_dir,
            )
            if error:
                errors.append(f"第 {position} 行失败：{error}")
                continue
            record = dict(line)
            record["path"] = target
            done.append(record)
            self.lineDone.emit(position, total, target)
        self.finished_batch.emit(done, errors)
