"""素材库管理：扫描 assets/ 目录、维护 asset_manifest.json、生成缩略图。

关键约定（对应开发指令第二十四条）：
Timeline JSON 里只能出现 asset id，绝不能出现绝对路径。
路径映射唯一由 asset_manifest.json 负责，整个项目搬家后 JSON 不用改。

id 一旦分配就不再变化：重新扫描时按 path 复用已有 id，
这样已经写好的 Timeline JSON 不会因为新增素材而失效。
"""

from __future__ import annotations

import json
import os
import shutil
import time
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal

from render.ffmpeg import FFmpeg, guess_asset_type


# 扫描目录 -> 该目录下素材的默认类型归类提示
SCAN_DIRS = [
    "videos",
    "images",
    "audio",
    "fonts",
    "effects",
    "overlays",
    "transitions",
    "captions",
    "animations",
    "templates",
]

# 素材库面板的分类顺序
ASSET_CATEGORIES = [
    ("video", "视频 Video"),
    ("image", "图片 Image"),
    ("audio", "音频 Audio"),
    ("overlay", "叠加 Overlay"),
    ("font", "字体 Font"),
]

# 外部导入（文件对话框 / 从资源管理器拖进来）时，按类型落到哪个目录。
# 统一落到 imported/ 子目录，这样 category 会是 imported，一眼能看出是导入的。
IMPORT_DIRS = {
    "video": os.path.join("videos", "imported"),
    "image": os.path.join("images", "imported"),
    "audio": os.path.join("audio", "imported"),
    "overlay": os.path.join("overlays", "imported"),
    "font": "fonts",
}

# 文件对话框的过滤器
IMPORT_FILE_FILTER = (
    "所有支持的素材 (*.mp4 *.mov *.mkv *.webm *.avi *.m4v *.png *.jpg *.jpeg *.webp *.bmp *.gif "
    "*.wav *.mp3 *.aac *.m4a *.flac *.ogg *.ttf *.otf);;"
    "视频 (*.mp4 *.mov *.mkv *.webm *.avi *.m4v);;"
    "图片 (*.png *.jpg *.jpeg *.webp *.bmp *.gif);;"
    "音频 (*.wav *.mp3 *.aac *.m4a *.flac *.ogg);;"
    "字体 (*.ttf *.otf);;"
    "所有文件 (*.*)"
)


def allocate_asset_id(
    asset_type: str,
    folder: str,
    category: str,
    counters: Dict[str, int],
) -> str:
    """生成语义化 id：video_001 / overlay_arrow_001 / sfx_impact_001。

    扫描与导入共用同一套规则，避免两条路径产生不同风格的 id。
    """
    if asset_type == "audio":
        prefix = f"sfx_{category}" if category else "audio"
    elif asset_type == "overlay":
        prefix = f"overlay_{category}" if category else f"overlay_{folder}"
    elif asset_type == "image":
        prefix = f"image_{category}" if category else "image"
    else:
        prefix = asset_type
    counters[prefix] = counters.get(prefix, 0) + 1
    return f"{prefix}_{counters[prefix]:03d}"


def id_counters(assets: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    """统计各前缀已用到的最大序号，保证新 id 不撞号。"""
    counters: Dict[str, int] = {}
    for asset_id in assets:
        prefix, _, tail = asset_id.rpartition("_")
        if prefix and tail.isdigit():
            counters[prefix] = max(counters.get(prefix, 0), int(tail))
    return counters


def build_thumbnail(ffmpeg: FFmpeg, root: str, full_path: str, asset_type: str) -> str:
    """生成缩略图并返回相对 root 的路径。

    缓存文件名按素材的相对路径生成（不用 asset id），
    这样扫描与导入两条路径共用同一份缓存。
    """
    if asset_type in ("image", "overlay") and os.path.splitext(full_path)[1].lower() in (
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".bmp",
    ):
        return os.path.relpath(full_path, root).replace("\\", "/")
    if not ffmpeg.available:
        return ""
    rel_path = os.path.relpath(full_path, root).replace("\\", "/")
    key = "".join(c if c.isalnum() else "_" for c in rel_path)
    target = os.path.join(root, ".cache", "thumbs", f"{key}.png")
    rel_target = os.path.relpath(target, root).replace("\\", "/")
    if os.path.isfile(target):
        return rel_target
    if asset_type == "audio":
        ok = ffmpeg.extract_waveform(full_path, target, 320, 90)
    else:
        ok = ffmpeg.extract_frame(full_path, 0.2, target, width=320)
    return rel_target if ok else ""


def unique_target_path(directory: str, filename: str) -> str:
    """同名文件不覆盖，自动加 _1 / _2 后缀。"""
    stem, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    index = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{stem}_{index}{ext}")
        index += 1
    return candidate



class ScanWorker(QThread):
    """后台扫描线程。绝不在主线程做 ffprobe，否则 GUI 会卡死。"""

    progress = pyqtSignal(str)
    finished_scan = pyqtSignal(list)

    def __init__(self, root: str, assets_dir: str, existing: Dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self._root = root
        self._assets_dir = assets_dir
        self._existing = dict(existing)  # path -> id，用于保持 id 稳定
        self._ffmpeg = FFmpeg()

    def run(self) -> None:  # noqa: D102
        found: List[Dict[str, Any]] = []
        # 先统计已用过的序号，避免新 id 与旧 id 撞号
        counters: Dict[str, int] = id_counters({v: {} for v in self._existing.values()})


        for sub in SCAN_DIRS:
            directory = os.path.join(self._assets_dir, sub)
            if not os.path.isdir(directory):
                continue
            self.progress.emit(f"正在扫描 assets/{sub} ...")
            for dirpath, _dirnames, filenames in os.walk(directory):
                for filename in sorted(filenames):
                    if filename.startswith("."):
                        continue
                    full_path = os.path.join(dirpath, filename)
                    asset = self._build_asset(full_path, sub, dirpath, directory, counters)
                    if asset:
                        found.append(asset)

        self.progress.emit(f"扫描完成，共 {len(found)} 个素材")
        self.finished_scan.emit(found)

    def _build_asset(
        self,
        full_path: str,
        folder: str,
        dirpath: str,
        base_dir: str,
        counters: Dict[str, int],
    ) -> Optional[Dict[str, Any]]:
        asset_type = guess_asset_type(full_path, folder)
        if not asset_type:
            return None

        rel_path = os.path.relpath(full_path, self._root).replace("\\", "/")
        rel_inside = os.path.relpath(dirpath, base_dir).replace("\\", "/")
        category = "" if rel_inside == "." else rel_inside.split("/")[0]

        asset_id = self._existing.get(rel_path) or allocate_asset_id(
            asset_type, folder, category, counters
        )


        asset: Dict[str, Any] = {
            "id": asset_id,
            "name": os.path.splitext(os.path.basename(full_path))[0],
            "type": asset_type,
            "category": category or folder,
            "path": rel_path,
            "tags": [t for t in [folder, category] if t],
        }
        try:
            asset["size_bytes"] = os.path.getsize(full_path)
        except OSError:
            asset["size_bytes"] = 0

        if asset_type in ("video", "audio", "overlay", "image"):
            info = self._ffmpeg.probe(full_path)
            for key in ("duration", "width", "height", "fps", "has_audio", "has_alpha"):
                if key in info:
                    asset[key] = info[key]

        thumb = build_thumbnail(self._ffmpeg, self._root, full_path, asset_type)
        if thumb:
            asset["thumbnail"] = thumb
        return asset


class ImportWorker(QThread):
    """把外部文件复制进 assets/ 并探测信息的后台线程。

    只做「复制 + 探测 + 缩略图」，id 分配交回主线程做，
    这样素材清单这份共享状态永远只有主线程改，不需要加锁。
    """

    progress = pyqtSignal(str)
    finished_import = pyqtSignal(list, dict)

    def __init__(
        self,
        root: str,
        assets_dir: str,
        paths: List[str],
        context: Dict[str, Any],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._root = root
        self._assets_dir = assets_dir
        self._paths = list(paths)
        self._context = dict(context or {})
        self._ffmpeg = FFmpeg()

    def run(self) -> None:  # noqa: D102
        results: List[Dict[str, Any]] = []
        total = len(self._paths)
        for index, source in enumerate(self._paths, start=1):
            if not os.path.isfile(source):
                self.progress.emit(f"跳过（不是文件）：{source}")
                continue
            asset_type = guess_asset_type(source)
            if not asset_type:
                self.progress.emit(f"跳过（不支持的格式）：{os.path.basename(source)}")
                continue

            sub = IMPORT_DIRS.get(asset_type, "videos")
            directory = os.path.join(self._assets_dir, sub)
            os.makedirs(directory, exist_ok=True)
            target = unique_target_path(directory, os.path.basename(source))

            self.progress.emit(f"正在导入 {index}/{total}：{os.path.basename(source)}")
            in_place = os.path.normcase(os.path.abspath(source)).startswith(
                os.path.normcase(os.path.abspath(self._assets_dir))
            )
            try:
                # 已经在 assets/ 里的文件不再复制，直接登记（例如 TTS 生成的配音）
                if in_place:
                    target = source
                else:
                    shutil.copy2(source, target)
            except OSError as exc:
                self.progress.emit(f"复制失败：{os.path.basename(source)}（{exc}）")
                continue

            rel_path = os.path.relpath(target, self._root).replace("\\", "/")
            if in_place:
                # 原地登记时按它真正所在的目录名归类，别拿 imported/ 去算相对路径
                category = os.path.basename(os.path.dirname(target)) or asset_type
            else:
                rel_inside = os.path.relpath(os.path.dirname(target), directory).replace("\\", "/")
                category = sub.replace("\\", "/").split("/")[-1] if rel_inside == "." else rel_inside

            asset: Dict[str, Any] = {
                "name": os.path.splitext(os.path.basename(target))[0],
                "type": asset_type,
                "category": category,
                "path": rel_path,
                "tags": ["imported", asset_type],
            }
            try:
                asset["size_bytes"] = os.path.getsize(target)
            except OSError:
                asset["size_bytes"] = 0

            if asset_type in ("video", "audio", "overlay", "image"):
                info = self._ffmpeg.probe(target)
                for key in ("duration", "width", "height", "fps", "has_audio", "has_alpha"):
                    if key in info:
                        asset[key] = info[key]
                if asset_type == "video" and not info:
                    self.progress.emit(
                        f"{asset['name']}：FFmpeg 未探测到信息，时长按默认 3 秒处理"
                    )

            thumb = build_thumbnail(self._ffmpeg, self._root, target, asset_type)
            if thumb:
                asset["thumbnail"] = thumb
            results.append(asset)

        self.progress.emit(f"导入完成，成功 {len(results)}/{total} 个")
        self.finished_import.emit(results, self._context)



class AssetManager(QObject):
    """素材清单的读写与查询。"""

    scanStarted = pyqtSignal()
    scanProgress = pyqtSignal(str)
    scanFinished = pyqtSignal(int)
    # 导入完成：(新增素材列表, 发起导入时带的上下文)
    importFinished = pyqtSignal(list, dict)
    logMessage = pyqtSignal(str)

    def __init__(self, root: str, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._root = root
        self._assets_dir = os.path.join(root, "assets")
        self._manifest_path = os.path.join(root, "asset_manifest.json")
        self._assets: Dict[str, Dict[str, Any]] = {}
        self._id_history: Dict[str, str] = {}
        self._worker: Optional[ScanWorker] = None
        self._import_workers: List[ImportWorker] = []
        self.load_manifest()



    # ------------------------------------------------------------ 清单读写

    @property
    def root(self) -> str:
        return self._root

    @property
    def manifest_path(self) -> str:
        return self._manifest_path

    def load_manifest(self) -> None:
        if not os.path.isfile(self._manifest_path):
            self._assets = {}
            self._id_history = {}
            return
        try:
            with open(self._manifest_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            self._assets = {a["id"]: a for a in data.get("assets", []) if a.get("id")}
            history = data.get("id_history") or {}
            self._id_history = {str(k): str(v) for k, v in history.items()}
            self.logMessage.emit(
                f"已加载素材清单：{len(self._assets)} 个素材"
                f"（id 台账 {len(self._id_history)} 条）"
            )
        except (OSError, json.JSONDecodeError) as exc:
            self._assets = {}
            self._id_history = {}
            self.logMessage.emit(f"素材清单读取失败：{exc}")


    def save_manifest(self) -> None:
        payload = {
            "version": 1,
            "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            # path -> id 的历史台账。素材被移出索引、又重新扫描回来时，
            # 靠它拿回原来的 id，已经写好的 Timeline JSON 才不会失效。
            "id_history": dict(sorted(self._merged_history().items())),
            "assets": sorted(self._assets.values(), key=lambda a: (a.get("type", ""), a.get("id", ""))),
        }
        os.makedirs(os.path.dirname(self._manifest_path) or ".", exist_ok=True)
        with open(self._manifest_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        self._id_history = payload["id_history"]
        self.logMessage.emit(f"素材清单已保存：{self._manifest_path}")

    def _merged_history(self) -> Dict[str, str]:
        """历史台账 + 当前素材的 path->id 映射。"""
        merged = dict(self._id_history)
        for asset in self._assets.values():
            if asset.get("path") and asset.get("id"):
                merged[asset["path"]] = asset["id"]
        return merged

    def remember_id(self, rel_path: str, asset_id: str) -> None:
        """手工登记一条 path->id 映射（修复历史数据时用）。"""
        if rel_path and asset_id:
            self._id_history[rel_path.replace("\\", "/")] = asset_id


    def manifest_dict(self) -> Dict[str, Any]:
        """导出给项目目录留档用。"""
        return {
            "version": 1,
            "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "assets": list(self._assets.values()),
        }

    # ------------------------------------------------------------ 扫描

    def rescan(self) -> None:
        """启动后台扫描。重复调用时会忽略后来的请求。"""
        if self._worker is not None and self._worker.isRunning():
            self.logMessage.emit("扫描仍在进行中，忽略本次请求")
            return
        for sub in SCAN_DIRS:
            os.makedirs(os.path.join(self._assets_dir, sub), exist_ok=True)
        existing = self._merged_history()
        self._worker = ScanWorker(self._root, self._assets_dir, existing, self)

        self._worker.progress.connect(self.scanProgress)
        self._worker.progress.connect(self.logMessage)
        self._worker.finished_scan.connect(self._on_scan_finished)
        self.scanStarted.emit()
        self._worker.start()

    def _on_scan_finished(self, found: List[Dict[str, Any]]) -> None:
        self._assets = {a["id"]: a for a in found}
        self.save_manifest()
        self.scanFinished.emit(len(found))

    def rescan_blocking(self) -> int:
        """同步扫描，扫完才返回。

        只给启动阶段（生成 Demo）和无 GUI 的脚本用：
        直接调用 worker.run() 在当前线程执行，信号是直连的，
        所以不依赖 Qt 事件循环也能拿到结果。
        平时 GUI 里的「重新扫描」仍然走 rescan() 的后台线程。
        """
        for sub in SCAN_DIRS:
            os.makedirs(os.path.join(self._assets_dir, sub), exist_ok=True)
        existing = self._merged_history()
        worker = ScanWorker(self._root, self._assets_dir, existing, self)

        worker.progress.connect(self.logMessage)
        worker.finished_scan.connect(self._on_scan_finished)
        self.scanStarted.emit()
        worker.run()
        return len(self._assets)

    def wait_for_scan(self, timeout_ms: int = 60000) -> None:
        """阻塞等待扫描结束。只在无 GUI 的脚本场景（如生成 Demo）使用。"""
        if self._worker is not None:
            self._worker.wait(timeout_ms)

    # ------------------------------------------------------------ 导入

    def import_files(self, paths: List[str], context: Optional[Dict[str, Any]] = None) -> bool:
        """把外部文件导入素材库（复制进 assets/ 并登记）。

        context 会原样回传给 importFinished，主窗口用它决定
        「导入后是否直接落到时间线的某条轨道某个时间点」。
        复制与探测都在后台线程，GUI 不会卡。
        """
        candidates = [p for p in paths if os.path.isfile(p)]
        if not candidates:
            self.logMessage.emit("没有可导入的文件")
            return False
        worker = ImportWorker(self._root, self._assets_dir, candidates, context or {}, self)
        worker.progress.connect(self.scanProgress)
        worker.progress.connect(self.logMessage)
        worker.finished_import.connect(self._on_import_finished)
        worker.finished.connect(lambda w=worker: self._drop_import_worker(w))
        self._import_workers.append(worker)
        self.logMessage.emit(f"开始导入 {len(candidates)} 个文件到素材库…")
        worker.start()
        return True

    def _on_import_finished(self, assets: List[Dict[str, Any]], context: Dict[str, Any]) -> None:
        """在主线程给导入的素材分配 id 并写入清单。"""
        counters = id_counters(self._assets)
        by_path = self._merged_history()

        registered: List[Dict[str, Any]] = []
        for asset in assets:
            existing_id = by_path.get(asset.get("path"))
            asset["id"] = existing_id or allocate_asset_id(
                asset.get("type", ""), "imported", asset.get("category", ""), counters
            )
            self._assets[asset["id"]] = asset
            registered.append(asset)
            self.logMessage.emit(
                f"已导入素材 {asset['id']}：{asset.get('name')}　"
                f"类型 {asset.get('type')}　时长 {asset.get('duration', 0)}s　"
                f"路径 {asset.get('path')}"
            )
        if registered:
            self.save_manifest()
        self.importFinished.emit(registered, context)

    def _drop_import_worker(self, worker: ImportWorker) -> None:
        if worker in self._import_workers:
            self._import_workers.remove(worker)


    # ------------------------------------------------------------ 查询

    def all(self) -> List[Dict[str, Any]]:
        return list(self._assets.values())

    def get(self, asset_id: str) -> Optional[Dict[str, Any]]:
        return self._assets.get(asset_id)

    def name_of(self, asset_id: str) -> str:
        asset = self._assets.get(asset_id)
        return asset.get("name", asset_id) if asset else asset_id

    def abs_path(self, asset_id: str) -> str:
        """asset id -> 磁盘绝对路径。这是路径解析的唯一出口。"""
        asset = self._assets.get(asset_id)
        if not asset:
            return ""
        return os.path.normpath(os.path.join(self._root, asset.get("path", "")))

    def file_exists(self, asset_id: str) -> bool:
        path = self.abs_path(asset_id)
        return bool(path) and os.path.isfile(path)

    def duration_of(self, asset_id: str) -> float:
        asset = self._assets.get(asset_id)
        if not asset:
            return 0.0
        return float(asset.get("duration") or 0.0)

    def thumbnail_path(self, asset_id: str) -> str:
        asset = self._assets.get(asset_id)
        if not asset or not asset.get("thumbnail"):
            return ""
        return os.path.normpath(os.path.join(self._root, asset["thumbnail"]))

    def search(
        self,
        keyword: str = "",
        asset_type: str = "",
        category: str = "",
    ) -> List[Dict[str, Any]]:
        """按名称 / 类型 / 分类 / 标签过滤。"""
        keyword = keyword.strip().lower()
        result: List[Dict[str, Any]] = []
        for asset in self._assets.values():
            if asset_type and asset.get("type") != asset_type:
                continue
            if category and asset.get("category") != category:
                continue
            if keyword:
                haystack = " ".join(
                    [
                        str(asset.get("name", "")),
                        str(asset.get("id", "")),
                        str(asset.get("category", "")),
                        " ".join(asset.get("tags", []) or []),
                        str(asset.get("path", "")),
                    ]
                ).lower()
                if keyword not in haystack:
                    continue
            result.append(asset)
        return sorted(result, key=lambda a: (a.get("type", ""), a.get("id", "")))

    def categories_of(self, asset_type: str) -> List[str]:
        values = {a.get("category", "") for a in self._assets.values() if a.get("type") == asset_type}
        return sorted(v for v in values if v)

    # ------------------------------------------------------------ 索引维护

    def rename(self, asset_id: str, new_name: str) -> bool:
        asset = self._assets.get(asset_id)
        if not asset:
            return False
        asset["name"] = new_name
        self.save_manifest()
        self.logMessage.emit(f"素材 {asset_id} 重命名为 {new_name}")
        return True

    def drop_index(self, asset_id: str) -> bool:
        """只从清单里移除，不删磁盘文件。

        移除前会把 path->id 记进历史台账，所以按 F5 重新扫描时
        这个素材会带着原来的 id 回来，引用它的 Timeline JSON 不会失效。
        """
        asset = self._assets.get(asset_id)
        if asset is None:
            return False
        if asset.get("path"):
            self.remember_id(asset["path"], asset_id)
        self._assets.pop(asset_id)
        self.save_manifest()
        self.logMessage.emit(
            f"已从索引移除素材 {asset_id}（磁盘文件保留，重新扫描会恢复同一个 id）"
        )
        return True


    def register(self, asset: Dict[str, Any]) -> None:
        """手动登记一个素材（Demo 生成器用）。"""
        if asset.get("id"):
            self._assets[asset["id"]] = asset
