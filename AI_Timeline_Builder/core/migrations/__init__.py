"""Timeline JSON 的版本迁移。

阶段 5 的定位：**v1 仍然是运行时格式**，v2 是已经定稿的目标协议。
GUI / PreviewRenderer / RemotionExporter / Remotion Runtime 目前全部读写 v1，
所以这里提供**双向**迁移，让 v2 可以先被校验、被测试、被文档化，
而不需要一次性改动整条链路。

用法：

    from core.migrations import detect_version, migrate_to_v2, migrate_to_v1

    v2 = migrate_to_v2(any_timeline)   # 拿到 v2 视图，用 v2 schema 校验
    v1 = migrate_to_v1(any_timeline)   # 喂给现有 GUI / Remotion
"""

from __future__ import annotations

from core.migrations.migration_v1_v2 import (
    LATEST_VERSION,
    detect_version,
    migrate_to_v1,
    migrate_to_v2,
    migrate_v1_to_v2,
    migrate_v2_to_v1,
)

__all__ = [
    "LATEST_VERSION",
    "detect_version",
    "migrate_to_v1",
    "migrate_to_v2",
    "migrate_v1_to_v2",
    "migrate_v2_to_v1",
]
