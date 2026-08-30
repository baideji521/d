"""项目存取。

项目就是磁盘上的一个目录，里面全是可读 JSON，没有任何二进制私有格式：

    projects/project_001/
    ├── project.json          项目级信息（名称、fps、分辨率、最后修改时间）
    ├── timeline.json         原始 Timeline JSON —— 本工具的核心产物
    ├── asset_manifest.json   当时的素材清单快照，便于复现
    └── preview/              预览帧缓存

对应开发指令第二十六条：JSON 必须是核心数据格式，不允许藏在 Python 对象里。
"""

from __future__ import annotations

import json
import os
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple


class ProjectManager:
    """项目目录的创建、保存、加载。"""

    def __init__(self, root: str) -> None:
        self._root = root
        self._projects_dir = os.path.join(root, "projects")
        os.makedirs(self._projects_dir, exist_ok=True)
        self._current_dir: str = ""

    # ------------------------------------------------------------ 基本信息

    @property
    def projects_dir(self) -> str:
        return self._projects_dir

    @property
    def current_dir(self) -> str:
        return self._current_dir

    @property
    def current_name(self) -> str:
        return os.path.basename(self._current_dir) if self._current_dir else ""

    def timeline_path(self, project_dir: str = "") -> str:
        return os.path.join(project_dir or self._current_dir, "timeline.json")

    def preview_dir(self, project_dir: str = "") -> str:
        target = os.path.join(project_dir or self._current_dir or self._root, "preview")
        os.makedirs(target, exist_ok=True)
        return target

    def list_projects(self) -> List[str]:
        if not os.path.isdir(self._projects_dir):
            return []
        names = []
        for entry in sorted(os.listdir(self._projects_dir)):
            if os.path.isfile(os.path.join(self._projects_dir, entry, "timeline.json")):
                names.append(entry)
        return names

    def next_project_name(self) -> str:
        index = 1
        while True:
            candidate = f"project_{index:03d}"
            if not os.path.isdir(os.path.join(self._projects_dir, candidate)):
                return candidate
            index += 1

    # ------------------------------------------------------------ 保存

    def save(
        self,
        timeline: Dict[str, Any],
        asset_manifest: Dict[str, Any],
        project_dir: str = "",
    ) -> str:
        """保存到项目目录，返回目录路径。"""
        target = project_dir or self._current_dir
        if not target:
            target = os.path.join(self._projects_dir, self.next_project_name())
        os.makedirs(target, exist_ok=True)
        os.makedirs(os.path.join(target, "preview"), exist_ok=True)

        meta = timeline.get("meta", {})
        project_info = {
            "version": 1,
            "name": meta.get("name", os.path.basename(target)),
            "fps": meta.get("fps", 30),
            "width": meta.get("width", 1080),
            "height": meta.get("height", 1920),
            "duration": meta.get("duration", 0),
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "timeline": "timeline.json",
            "asset_manifest": "asset_manifest.json",
        }

        self._write_json(os.path.join(target, "project.json"), project_info)
        self._write_json(os.path.join(target, "timeline.json"), timeline)
        self._write_json(os.path.join(target, "asset_manifest.json"), asset_manifest)

        self._current_dir = target
        return target

    def save_timeline_only(self, timeline: Dict[str, Any], path: str) -> None:
        """把 Timeline JSON 单独另存为任意文件。"""
        self._write_json(path, timeline)

    # ------------------------------------------------------------ 加载

    def load(self, project_dir: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """加载项目，返回 (timeline, project_info)。"""
        timeline_path = os.path.join(project_dir, "timeline.json")
        if not os.path.isfile(timeline_path):
            raise FileNotFoundError(f"找不到 {timeline_path}")
        timeline = self._read_json(timeline_path)
        info_path = os.path.join(project_dir, "project.json")
        info = self._read_json(info_path) if os.path.isfile(info_path) else {}
        self._current_dir = project_dir
        return timeline, info

    def load_timeline_file(self, path: str) -> Dict[str, Any]:
        """加载单独的 Timeline JSON 文件（未来 AI 生成的 JSON 走这个入口）。"""
        return self._read_json(path)

    def delete(self, project_dir: str) -> None:
        if os.path.isdir(project_dir):
            shutil.rmtree(project_dir, ignore_errors=True)
            if self._current_dir == project_dir:
                self._current_dir = ""

    # ------------------------------------------------------------ 实验案例库

    def cases_dir(self) -> str:
        """参数实验案例的存放目录。"""
        target = os.path.join(self._root, "projects", "_cases")
        os.makedirs(target, exist_ok=True)
        return target

    def save_case(self, name: str, payload: Dict[str, Any]) -> str:
        """保存一个参数实验案例。名字里的非法字符会被替换。"""
        safe = "".join(c if c.isalnum() or c in "-_（）()" else "_" for c in name).strip("_")
        safe = safe or "case"
        path = os.path.join(self.cases_dir(), f"{safe}.json")
        payload = dict(payload)
        payload["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._write_json(path, payload)
        return path

    def list_cases(self) -> List[Dict[str, Any]]:
        """列出所有案例，附带文件路径。"""
        directory = self.cases_dir()
        cases: List[Dict[str, Any]] = []
        for entry in sorted(os.listdir(directory)):
            if not entry.endswith(".json"):
                continue
            path = os.path.join(directory, entry)
            try:
                data = self._read_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            data["_path"] = path
            data.setdefault("name", os.path.splitext(entry)[0])
            cases.append(data)
        return cases

    def delete_case(self, path: str) -> None:
        if os.path.isfile(path):
            os.remove(path)

    # ------------------------------------------------------------ 工具

    @staticmethod
    def _write_json(path: str, payload: Any) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    @staticmethod
    def _read_json(path: str) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
