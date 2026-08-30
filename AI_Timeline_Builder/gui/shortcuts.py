"""快捷键单一数据源。

菜单、工具栏、QShortcut 注册和 F1 速查面板全部从这里取键位，
避免「面板上写着 Ctrl+B，实际按了没反应」这种漂移。

键位以剪映习惯为准；原来项目里的键位如果不冲突，作为备用键一起保留
（例如重做同时支持 Ctrl+Y 和 Ctrl+Shift+Z）。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# 动作 key -> 键位列表（第一个是主键位，后面的是备用）
KEYS: Dict[str, List[str]] = {
    # 播放与播放头
    "play_pause": ["Space"],
    "prev_frame": ["Left"],
    "next_frame": ["Right"],
    "prev_second": ["Shift+Left"],
    "next_second": ["Shift+Right"],
    "goto_start": ["Home"],
    "goto_end": ["End"],
    # 剪辑
    "split": ["Ctrl+B"],
    "freeze": ["Shift+F"],
    "delete": ["Delete", "Backspace"],
    "copy": ["Ctrl+C"],
    "cut": ["Ctrl+X"],
    "paste": ["Ctrl+V"],
    "duplicate": ["Ctrl+D"],
    "undo": ["Ctrl+Z"],
    "redo": ["Ctrl+Y", "Ctrl+Shift+Z"],
    "select_all": ["Ctrl+A"],
    "select_up": ["Up"],
    "select_down": ["Down"],
    "nudge_left": ["Alt+Left"],
    "nudge_right": ["Alt+Right"],
    # 视图
    "zoom_in": ["Ctrl+=", "Ctrl++"],
    "zoom_out": ["Ctrl+-"],
    "zoom_fit": ["Ctrl+0"],
    "toggle_snap": ["Ctrl+M"],
    "cheatsheet": ["F1"],
    # 项目与素材
    "new_project": ["Ctrl+N"],
    "open_project": ["Ctrl+O"],
    "save_project": ["Ctrl+S"],
    "save_project_as": ["Ctrl+Shift+S"],
    "import_assets": ["Ctrl+I"],
    "rescan_assets": ["F5"],
    "validate": ["F8"],
    "render": ["F9"],
    "text_to_speech": ["Ctrl+T"],
    "quit": ["Ctrl+Q"],
}

# 动作 key -> 中文说明（速查面板与工具提示共用）
LABELS: Dict[str, str] = {
    "play_pause": "播放 / 暂停",
    "prev_frame": "上一帧",
    "next_frame": "下一帧",
    "prev_second": "后退 1 秒",
    "next_second": "前进 1 秒",
    "goto_start": "播放头回到开头",
    "goto_end": "播放头跳到结尾",
    "split": "在播放头处分割选中片段",
    "freeze": "在播放头处加冻结帧（定格）",
    "delete": "删除选中元素（支持多选）",
    "copy": "复制选中元素",
    "cut": "剪切选中元素",
    "paste": "粘贴到播放头位置",
    "duplicate": "原地复制一份",
    "undo": "撤销",
    "redo": "重做",
    "select_all": "选中当前所有元素",
    "select_up": "选上一条轨道上同时刻的元素",
    "select_down": "选下一条轨道上同时刻的元素",
    "nudge_left": "选中元素左移一帧",
    "nudge_right": "选中元素右移一帧",
    "zoom_in": "时间线放大",
    "zoom_out": "时间线缩小",
    "zoom_fit": "缩放到整条时间线",
    "toggle_snap": "开关磁吸（吸附到播放头和相邻片段）",
    "cheatsheet": "打开这个快捷键速查面板",
    "new_project": "新建项目",
    "open_project": "打开项目",
    "save_project": "保存项目",
    "save_project_as": "项目另存为",
    "import_assets": "导入素材文件",
    "rescan_assets": "重新扫描素材库",
    "validate": "校验 Timeline",
    "render": "导出并渲染 MP4",
    "text_to_speech": "文本转语音（生成配音）",
    "quit": "退出",
}

# 速查面板的分组顺序
GROUPS: List[Tuple[str, List[str]]] = [
    (
        "播放与播放头",
        [
            "play_pause",
            "prev_frame",
            "next_frame",
            "prev_second",
            "next_second",
            "goto_start",
            "goto_end",
        ],
    ),
    (
        "剪辑",
        [
            "split",
            "freeze",
            "delete",
            "copy",
            "cut",
            "paste",
            "duplicate",
            "nudge_left",
            "nudge_right",
            "undo",
            "redo",
        ],
    ),
    ("选择", ["select_all", "select_up", "select_down"]),
    ("视图", ["zoom_in", "zoom_out", "zoom_fit", "toggle_snap", "cheatsheet"]),
    (
        "项目与素材",
        [
            "new_project",
            "open_project",
            "save_project",
            "save_project_as",
            "import_assets",
            "rescan_assets",
            "validate",
            "render",
            "text_to_speech",
            "quit",
        ],
    ),
]

# 只能靠鼠标完成、但同样影响手感的操作，一并列在面板里
MOUSE_TIPS: List[Tuple[str, str]] = [
    ("拖动片段本体", "移动，可跨同类型轨道"),
    ("拖动片段左右边缘", "裁剪入点 / 出点"),
    ("Alt + 拖动片段", "拖出一个副本"),
    ("空白处拖动", "框选多个元素"),
    ("Ctrl + 点击片段", "加选 / 取消选中"),
    ("刻度区拖动", "拖动播放头"),
    ("Ctrl + 滚轮", "以鼠标位置为锚点缩放时间线"),
    ("Shift + 滚轮", "横向滚动"),
    ("双击片段", "在属性面板里聚焦该元素"),
    ("从资源管理器拖文件进来", "自动导入素材库并落到落点"),
]


def primary(action: str) -> str:
    """主键位，给菜单 / 工具提示用。"""
    keys = KEYS.get(action) or []
    return keys[0] if keys else ""


def alternates(action: str) -> List[str]:
    """备用键位。"""
    return list((KEYS.get(action) or [])[1:])


def display(action: str) -> str:
    """速查面板显示用，多个键位用 / 连起来。"""
    return " / ".join(KEYS.get(action) or [])
