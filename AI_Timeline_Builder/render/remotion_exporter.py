"""Remotion 导出器。

做四件事：
1. 把当前 Timeline JSON 写到 remotion/timeline.json（原样，不做任何转换）
2. 把素材清单写到 remotion/asset_manifest.json
3. 重新生成 remotion/src/timeline-data.ts，让 Studio 与 render.mjs 都能拿到最新数据
4. 把被引用到的素材拷进 remotion/public/，保持 manifest 里的相对路径不变

第 4 步是必须的：Remotion 只能通过 staticFile() 访问 public/ 下的文件，
而 asset_manifest.json 里的路径形如 assets/videos/a.mp4，
拷成 remotion/public/assets/videos/a.mp4 后 staticFile 就能原样命中。

渲染在后台线程跑 node render.mjs，输出逐行回传给 GUI 日志。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Set

from PyQt5.QtCore import QThread, pyqtSignal

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

_NODE_DIRS = [
    r"C:\Program Files\nodejs",
    os.path.expandvars(r"%ProgramFiles%\nodejs"),
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\nodejs"),
]


def find_node() -> str:
    """找 node 可执行文件。PATH 没刷新时兜底去常见安装目录找。"""
    exe = "node.exe" if os.name == "nt" else "node"
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(directory.strip('"'), exe)
        if os.path.isfile(candidate):
            return candidate
    for directory in _NODE_DIRS:
        candidate = os.path.join(directory, exe)
        if os.path.isfile(candidate):
            return candidate
    return ""


def find_npm() -> str:
    """Windows 上必须用 npm.cmd，npm.ps1 会被执行策略拦住。"""
    names = ["npm.cmd", "npm"] if os.name == "nt" else ["npm"]
    for name in names:
        for directory in os.environ.get("PATH", "").split(os.pathsep):
            candidate = os.path.join(directory.strip('"'), name)
            if os.path.isfile(candidate):
                return candidate
        for directory in _NODE_DIRS:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
    return ""


class RemotionExporter:
    """把 Timeline JSON 落地成一个可渲染的 Remotion 工程。"""

    def __init__(self, root: str, asset_manager) -> None:
        self._root = root
        self._assets = asset_manager
        self._remotion_dir = os.path.join(root, "remotion")

    @property
    def remotion_dir(self) -> str:
        return self._remotion_dir

    @property
    def node_modules_ready(self) -> bool:
        return os.path.isdir(os.path.join(self._remotion_dir, "node_modules"))

    def status_text(self) -> str:
        node = find_node()
        if not node:
            return "未找到 Node.js，无法渲染（请安装 Node 18+ 并加入 PATH）"
        if not self.node_modules_ready:
            return f"Node 就绪（{node}），但 remotion/node_modules 尚未安装"
        return f"Node 与 Remotion 依赖均就绪：{node}"

    # ------------------------------------------------------------ 导出

    def export(self, timeline: Dict[str, Any]) -> Dict[str, Any]:
        """执行导出，返回结果摘要。"""
        os.makedirs(self._remotion_dir, exist_ok=True)
        os.makedirs(os.path.join(self._remotion_dir, "src"), exist_ok=True)

        referenced = self._referenced_assets(timeline)
        manifest = self._build_manifest(referenced)
        copied, missing = self._copy_assets(manifest)

        timeline_path = os.path.join(self._remotion_dir, "timeline.json")
        manifest_path = os.path.join(self._remotion_dir, "asset_manifest.json")
        self._write_json(timeline_path, timeline)
        self._write_json(manifest_path, manifest)
        self._write_timeline_data(timeline, manifest)

        return {
            "remotion_dir": self._remotion_dir,
            "timeline_path": timeline_path,
            "manifest_path": manifest_path,
            "asset_count": len(manifest["assets"]),
            "copied": copied,
            "missing": missing,
        }

    def _referenced_assets(self, timeline: Dict[str, Any]) -> Set[str]:
        """收集 Timeline 里所有被引用的 asset id，包含 params 里的素材特效。"""
        referenced: Set[str] = set()
        for element in timeline.get("elements", []):
            asset_id = element.get("asset")
            if asset_id:
                referenced.add(asset_id)
            params = element.get("params") or {}
            param_asset = params.get("asset")
            if isinstance(param_asset, str) and param_asset:
                referenced.add(param_asset)
        return referenced

    def _build_manifest(self, referenced: Set[str]) -> Dict[str, Any]:
        assets: List[Dict[str, Any]] = []
        for asset_id in sorted(referenced):
            asset = self._assets.get(asset_id)
            if not asset:
                continue
            assets.append(
                {
                    "id": asset["id"],
                    "name": asset.get("name", ""),
                    "type": asset.get("type", ""),
                    "path": asset.get("path", ""),
                    "duration": asset.get("duration", 0),
                    "width": asset.get("width", 0),
                    "height": asset.get("height", 0),
                    "fps": asset.get("fps", 0),
                }
            )
        return {"version": 1, "assets": assets}

    def _copy_assets(self, manifest: Dict[str, Any]) -> tuple:
        """把素材拷进 remotion/public/，返回 (已拷贝数, 缺失清单)。"""
        public_dir = os.path.join(self._remotion_dir, "public")
        copied = 0
        missing: List[str] = []
        for asset in manifest["assets"]:
            source = self._assets.abs_path(asset["id"])
            if not source or not os.path.isfile(source):
                missing.append(f"{asset['id']}（{asset.get('path')}）")
                continue
            target = os.path.join(public_dir, asset["path"].replace("/", os.sep))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            # 源文件更新过才重拷，避免每次导出都搬几百 MB
            if os.path.isfile(target) and os.path.getmtime(target) >= os.path.getmtime(source):
                continue
            shutil.copy2(source, target)
            copied += 1
        return copied, missing

    def _write_timeline_data(self, timeline: Dict[str, Any], manifest: Dict[str, Any]) -> None:
        """生成 src/timeline-data.ts。"""
        header = (
            "/**\n"
            " * 由 AI_Timeline_Builder 的「导出 Remotion」自动生成，请不要手改。\n"
            " * 下次导出会整体覆盖本文件。\n"
            " */\n\n"
            'import type { AssetManifest, Timeline } from "./lib/timeline";\n\n'
        )
        timeline_json = json.dumps(timeline, ensure_ascii=False, indent=2)
        manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2)
        body = (
            f"export const TIMELINE: Timeline = {timeline_json} as Timeline;\n\n"
            f"export const ASSET_MANIFEST: AssetManifest = {manifest_json};\n"
        )
        path = os.path.join(self._remotion_dir, "src", "timeline-data.ts")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(header + body)

    @staticmethod
    def _write_json(path: str, payload: Any) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)


class RemotionRenderWorker(QThread):
    """后台执行 npm install（按需）与 node render.mjs。"""

    output = pyqtSignal(str)
    finishedRender = pyqtSignal(bool, str)

    def __init__(
        self,
        remotion_dir: str,
        output_path: str,
        install_first: bool,
        extra_args: Optional[List[str]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._dir = remotion_dir
        self._output = output_path
        self._install = install_first
        self._extra = list(extra_args or [])

    def run(self) -> None:  # noqa: D102
        node = find_node()
        if not node:
            self.finishedRender.emit(False, "未找到 Node.js，无法渲染")
            return

        if self._install:
            npm = find_npm()
            if not npm:
                self.finishedRender.emit(False, "未找到 npm，无法安装 Remotion 依赖")
                return
            self.output.emit("正在安装 Remotion 依赖（首次较慢，请耐心等待）…")
            code = self._stream([npm, "install", "--no-audit", "--no-fund"])
            if code != 0:
                self.finishedRender.emit(False, f"npm install 失败，退出码 {code}")
                return
            self.output.emit("依赖安装完成")

        command = [node, "render.mjs", f"--out={self._output}"] + self._extra
        self.output.emit(f"开始渲染：{' '.join(command)}")
        code = self._stream(command)

        # Node 24 在退出时可能抛 libuv 断言，但文件已经写好，
        # 所以以「输出文件是否存在」为准，而不是只看退出码
        target = self._output if os.path.isabs(self._output) else os.path.join(self._dir, self._output)
        if os.path.isfile(target):
            self.finishedRender.emit(True, target)
        else:
            self.finishedRender.emit(False, f"渲染失败，退出码 {code}，未生成输出文件")

    def _stream(self, command: List[str]) -> int:
        """执行命令并逐行把输出发给 GUI。"""
        try:
            process = subprocess.Popen(
                command,
                cwd=self._dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=_CREATE_NO_WINDOW,
            )
        except OSError as exc:
            self.output.emit(f"命令启动失败：{exc}")
            return -1
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                self.output.emit(line)
        process.wait()
        return process.returncode
