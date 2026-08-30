"""撤销 / 重做管理器。

采用「整份 Timeline JSON 快照」策略，而不是逐操作的反向指令。
理由：本项目的核心数据就是一份不大的 JSON（几十到几百个元素），
快照方式能一次性覆盖添加、删除、移动、裁剪、改参数、改文字、
加删特效、改转场、改字幕等全部操作，且绝不会出现反向指令写错导致的状态漂移。
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple


class UndoManager:
    """基于快照的撤销栈。"""

    def __init__(self, limit: int = 200) -> None:
        self._limit = limit
        # 每项为 (操作描述, Timeline JSON 快照)
        self._undo_stack: List[Tuple[str, Dict[str, Any]]] = []
        self._redo_stack: List[Tuple[str, Dict[str, Any]]] = []

    def clear(self) -> None:
        """清空历史，通常在新建 / 加载项目时调用。"""
        self._undo_stack.clear()
        self._redo_stack.clear()

    def push(self, description: str, snapshot: Dict[str, Any]) -> None:
        """在修改「之前」记录快照。"""
        self._undo_stack.append((description, copy.deepcopy(snapshot)))
        if len(self._undo_stack) > self._limit:
            self._undo_stack.pop(0)
        # 新操作让重做链失效
        self._redo_stack.clear()

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def undo_label(self) -> str:
        return self._undo_stack[-1][0] if self._undo_stack else ""

    def redo_label(self) -> str:
        return self._redo_stack[-1][0] if self._redo_stack else ""

    def undo(self, current: Dict[str, Any]) -> Optional[Tuple[str, Dict[str, Any]]]:
        """回退一步。current 为当前状态，会被压入重做栈。"""
        if not self._undo_stack:
            return None
        description, snapshot = self._undo_stack.pop()
        self._redo_stack.append((description, copy.deepcopy(current)))
        return description, snapshot

    def redo(self, current: Dict[str, Any]) -> Optional[Tuple[str, Dict[str, Any]]]:
        """前进一步。"""
        if not self._redo_stack:
            return None
        description, snapshot = self._redo_stack.pop()
        self._undo_stack.append((description, copy.deepcopy(current)))
        return description, snapshot
