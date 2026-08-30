"""pytest 共享配置。

把仓库根加进 sys.path，这样 tests/ 里可以直接 `from core import timeline as tl`，
不需要安装成包。
"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import timeline as tl  # noqa: E402
from core.timeline_model import TimelineModel  # noqa: E402
from core.timeline_validator import TimelineValidator  # noqa: E402
from core.undo_manager import UndoManager  # noqa: E402


class FakeAssetManager:
    """最小素材管理器替身。

    真的 AssetManager 会扫磁盘、写 asset_manifest.json，测试里不需要，
    只要能回答「这个 id 存在吗 / 时长多少 / 文件在不在」就够了。
    """

    def __init__(self, assets=None) -> None:
        self._assets = dict(assets or {})

    def add(self, asset_id: str, duration: float = 10.0, asset_type: str = "video") -> None:
        self._assets[asset_id] = {
            "id": asset_id,
            "name": asset_id,
            "type": asset_type,
            "path": f"assets/{asset_type}s/{asset_id}.bin",
            "duration": duration,
            "width": 1080,
            "height": 1920,
            "fps": 30,
        }

    def get(self, asset_id: str):
        return self._assets.get(asset_id)

    def all(self):
        return list(self._assets.values())

    def name_of(self, asset_id: str) -> str:
        return self._assets.get(asset_id, {}).get("name", asset_id)

    def abs_path(self, asset_id: str) -> str:
        asset = self._assets.get(asset_id)
        return asset["path"] if asset else ""

    def file_exists(self, asset_id: str) -> bool:
        # 测试环境不落真实文件，登记过就算存在，让 RULE_ASSET_002 不误报
        return asset_id in self._assets

    def duration_of(self, asset_id: str) -> float:
        return float(self._assets.get(asset_id, {}).get("duration", 0.0))


@pytest.fixture
def assets() -> FakeAssetManager:
    manager = FakeAssetManager()
    manager.add("video_001", duration=12.0, asset_type="video")
    manager.add("video_002", duration=12.0, asset_type="video")
    manager.add("image_001", duration=0.0, asset_type="image")
    manager.add("audio_001", duration=30.0, asset_type="audio")
    manager.add("sfx_001", duration=2.0, asset_type="audio")
    return manager


@pytest.fixture
def libraries(assets):
    """真的库对象，不替身 —— Effect / Transition 名字校验必须用真表。"""
    from libraries.asset_library import Libraries

    return Libraries(os.path.join(ROOT, "assets"), assets)


@pytest.fixture
def validator(assets, libraries) -> TimelineValidator:
    return TimelineValidator(os.path.join(ROOT, "schemas"), assets, libraries.as_dict())


@pytest.fixture
def model() -> TimelineModel:
    return TimelineModel(UndoManager())


@pytest.fixture
def timeline() -> dict:
    """一条最小可用时间线：两个视频片段。"""
    data = tl.empty_timeline("测试项目")
    data["elements"].append(
        tl.make_video("clip_001", "video_001", "V1", start=0.0, source_start=0.0, source_end=5.0)
    )
    data["elements"].append(
        tl.make_video("clip_002", "video_002", "V1", start=5.0, source_start=0.0, source_end=5.0)
    )
    return data
