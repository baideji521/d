"""主窗口：把所有面板拼起来，并把菜单 / 拖放 / 右键 / 快捷键接到模型上。

布局（对应开发指令里的界面草图）：

    ┌───────────┬──────────────────────────┬────────────┐
    │ 素材库    │ 预览                     │ 属性面板   │
    │ 特效/转场 ├──────────────────────────┤            │
    │ 字幕/动画 │ 时间线（多轨）           │            │
    │ 模板      ├──────────────────────────┤            │
    │           │ JSON 面板（可切换显示）  │            │
    ├───────────┴──────────────────────────┴────────────┤
    │ 中文日志                                          │
    └───────────────────────────────────────────────────┘

这里只做「连线」，所有对时间线的修改都必须落到 TimelineModel 的方法上，
这样撤销、JSON 同步、预览刷新才会同时生效。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from PyQt5.QtCore import QSize, Qt, QTimer
from PyQt5.QtGui import QFont, QKeySequence
from PyQt5.QtWidgets import (
    QAction,
    QActionGroup,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QShortcut,
    QSplitter,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core import demo_project
from core import markers as marker_utils
from core import timeline as tl
from core import tts
from core.asset_manager import IMPORT_FILE_FILTER
from gui.asset_panel import AssetPanel
from gui.asset_placement import choose_track as choose_placement_track
from gui.asset_placement import for_asset as placement_for_asset
from gui.asset_placement import for_element_type as placement_for_element_type

from gui.dialogs import (
    CaseBrowserDialog,
    JianyingImportDialog,
    OpenProjectDialog,
    ProjectSettingsDialog,
    SaveCaseDialog,
    ShortcutDialog,
    TrackDialog,
    TransitionDialog,
    TtsDialog,
    element_text,
)
from gui import shortcuts
from gui.json_panel import JsonPanel
from gui.library_panel import LibraryPanel
from gui.preview_widget import PreviewWidget
from gui.property_panel import PropertyPanel
from gui.timeline_widget import TimelineWidget
from render.ffmpeg import FFmpeg
from render.preview_audio import PreviewAudio
from render.remotion_exporter import RemotionRenderWorker, find_node

VIEW_MODES = [
    ("timeline", "只看 Timeline"),
    ("json", "只看 JSON"),
    ("both", "Timeline + JSON（默认）"),
]


class MainWindow(QMainWindow):
    """AI 视频时间线规则实验器主窗口。"""

    def __init__(
        self,
        root: str,
        model,
        asset_manager,
        libraries,
        validator,
        renderer,
        exporter,
        project_manager,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._root = root
        self._model = model
        self._assets = asset_manager
        self._libraries = libraries
        self._validator = validator
        self._renderer = renderer
        self._exporter = exporter
        self._projects = project_manager
        self._ffmpeg = FFmpeg()
        self._render_worker: Optional[RemotionRenderWorker] = None
        self._tts_worker: Optional[tts.TtsWorker] = None
        self._tts_batch: Optional[tts.TtsBatchWorker] = None
        self._tts_placement: Dict[str, Any] = {}
        # 复制 / 剪切用的剪贴板：{"base": 最早的 start, "elements": [...]}
        self._clipboard: Dict[str, Any] = {}

        self.setWindowTitle("AI 视频时间线规则实验器 · AI Timeline Builder")
        self.resize(1680, 980)
        # 允许把文件从资源管理器直接拖到窗口任意位置导入素材
        self.setAcceptDrops(True)

        self._build_panels()
        self._build_docks()
        self._build_menus()
        self._build_toolbar()
        self._register_shortcuts()
        self._build_status_bar()
        self._connect_signals()
        self._apply_view_mode("both")
        self._refresh_history_actions()

    # ================================================================ 构建

    def _build_panels(self) -> None:
        self.asset_panel = AssetPanel(self._assets, self._libraries.asset)
        self.library_panel = LibraryPanel(self._libraries)
        # 预览音频与抽帧共用同一个缓存目录：一个放帧 PNG，一个放混音 WAV
        self.preview_audio = PreviewAudio(
            self._model,
            self._assets,
            os.path.join(self._root, ".cache", "preview"),
            self,
        )
        self.preview = PreviewWidget(self._model, self._renderer, self.preview_audio)
        self.timeline = TimelineWidget(self._model)
        self.json_panel = JsonPanel(self._model, self._validator)
        self.property_panel = PropertyPanel(self._model, self._assets, self._libraries)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        log_font = QFont("Consolas")
        log_font.setPointSize(9)
        self.log_view.setFont(log_font)
        self.log_view.setMaximumBlockCount(4000)

        # 中间区域：预览 / 时间线 / JSON 垂直分割
        self._center_splitter = QSplitter(Qt.Vertical)
        self._center_splitter.addWidget(self.preview)
        self._center_splitter.addWidget(self.timeline)
        self._center_splitter.addWidget(self.json_panel)
        self._center_splitter.setStretchFactor(0, 4)
        self._center_splitter.setStretchFactor(1, 3)
        self._center_splitter.setStretchFactor(2, 3)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._center_splitter)
        self.setCentralWidget(container)

    def _build_docks(self) -> None:
        left_tabs = QTabWidget()
        left_tabs.addTab(self.asset_panel, "素材库")
        left_tabs.addTab(self.library_panel, "特效 / 转场 / 字幕 / 动画 / 模板")
        left_tabs.setTabPosition(QTabWidget.North)

        self._left_dock = QDockWidget("素材与库", self)
        self._left_dock.setObjectName("dock_left")
        self._left_dock.setWidget(left_tabs)
        self._left_dock.setMinimumWidth(320)
        self.addDockWidget(Qt.LeftDockWidgetArea, self._left_dock)

        self._right_dock = QDockWidget("属性 / 参数实验", self)
        self._right_dock.setObjectName("dock_right")
        self._right_dock.setWidget(self.property_panel)
        self._right_dock.setMinimumWidth(360)
        self.addDockWidget(Qt.RightDockWidgetArea, self._right_dock)

        self._log_dock = QDockWidget("日志", self)
        self._log_dock.setObjectName("dock_log")
        self._log_dock.setWidget(self.log_view)
        self._log_dock.setMinimumHeight(120)
        self.addDockWidget(Qt.BottomDockWidgetArea, self._log_dock)

    def _build_menus(self) -> None:
        bar = self.menuBar()

        # ---- 项目
        project_menu = bar.addMenu("项目(&P)")
        self._add_action(project_menu, "新建项目", self._on_new_project, "new_project")
        self._add_action(project_menu, "打开项目…", self._on_open_project, "open_project")
        self._add_action(project_menu, "保存项目", self._on_save_project, "save_project")
        self._add_action(project_menu, "项目另存为…", self._on_save_project_as, "save_project_as")
        project_menu.addSeparator()
        self._add_action(project_menu, "加载 Timeline JSON…（AI 生成的 JSON 走这里）", self._on_load_timeline_json)
        self._add_action(project_menu, "导出 Timeline JSON…", self._on_export_timeline_json)
        project_menu.addSeparator()
        self._add_action(project_menu, "项目设置…", self._on_project_settings)
        self._add_action(project_menu, "重新生成 Demo 项目", self._on_reload_demo)
        project_menu.addSeparator()
        self._add_action(project_menu, "退出", self.close, "quit")

        # ---- 编辑（键位按剪映习惯）
        edit_menu = bar.addMenu("编辑(&E)")
        self._undo_action = self._add_action(edit_menu, "撤销", self._model.undo, "undo")
        self._redo_action = self._add_action(edit_menu, "重做", self._model.redo, "redo")
        edit_menu.addSeparator()
        self._add_action(edit_menu, "在播放头处分割", self._on_split_current, "split")
        self._add_action(edit_menu, "在播放头处加定格", self._on_freeze_current, "freeze")
        edit_menu.addSeparator()
        self._add_action(edit_menu, "复制", self._on_copy, "copy")
        self._add_action(edit_menu, "剪切", self._on_cut, "cut")
        self._add_action(edit_menu, "粘贴到播放头", self._on_paste, "paste")
        self._add_action(edit_menu, "原地复制一份", self._on_duplicate, "duplicate")
        self._add_action(edit_menu, "删除选中元素", self._on_delete, "delete")
        edit_menu.addSeparator()
        self._add_action(edit_menu, "全选", self._on_select_all, "select_all")
        self._add_action(edit_menu, "选中元素左移一帧", lambda: self._nudge_selection(-1), "nudge_left")
        self._add_action(edit_menu, "选中元素右移一帧", lambda: self._nudge_selection(1), "nudge_right")
        edit_menu.addSeparator()
        self._add_action(
            edit_menu, "校验 Timeline", lambda: self.json_panel.validate(verbose=True), "validate"
        )

        # ---- 素材
        asset_menu = bar.addMenu("素材(&A)")
        self._add_action(
            asset_menu, "导入素材文件…（视频 / 图片 / 音频 / 字体）", self._on_import_assets, "import_assets"
        )
        self._add_action(asset_menu, "重新扫描素材库", self._assets.rescan, "rescan_assets")
        self._add_action(asset_menu, "打开 assets 目录", self._on_open_assets_dir)
        asset_menu.addSeparator()
        self._add_action(asset_menu, "把选中素材加到播放头位置", self._on_add_selected_asset)

        # ---- 轨道
        track_menu = bar.addMenu("轨道(&T)")
        self._add_action(track_menu, "新增轨道…", self._on_add_track)
        self._add_action(track_menu, "删除当前元素所在轨道…", self._on_remove_current_track)

        # ---- 特效 / 转场 / 字幕 / 模板
        effect_menu = bar.addMenu("特效(&F)")
        self._add_action(effect_menu, "给选中元素加程序特效…", lambda: self._quick_add_from_library("effect"))
        self._add_action(effect_menu, "加素材特效（Overlay）…", lambda: self._quick_add_from_library("effect_material"))

        transition_menu = bar.addMenu("转场(&R)")
        self._add_action(transition_menu, "插入转场…", self._on_insert_transition)

        caption_menu = bar.addMenu("字幕(&C)")
        self._add_action(caption_menu, "新增整句字幕…", self._on_add_caption)
        self._add_action(caption_menu, "新增逐词字幕…", self._on_add_caption_group)
        self._add_action(caption_menu, "新增文字…", self._on_add_text)
        caption_menu.addSeparator()
        self._add_action(
            caption_menu, "文本转语音（生成配音）…", self._on_text_to_speech, "text_to_speech"
        )
        self._add_action(caption_menu, "把选中字幕转成配音…", self._on_caption_to_speech)
        self._add_action(
            caption_menu, "导入剪映文本 / 字幕（可批量转配音）…", self._on_import_jianying
        )
        caption_menu.addSeparator()
        self._add_action(caption_menu, "把当前字幕样式存为模板…", self._on_save_caption_template)

        template_menu = bar.addMenu("模板(&M)")
        self._add_action(template_menu, "在播放头展开模板…", lambda: self._quick_add_from_library("template"))

        # ---- 标记
        marker_menu = bar.addMenu("标记(&K)")
        self._add_action(marker_menu, "在播放头打标记", self._on_add_marker, "add_marker")
        for marker_type, spec in marker_utils.MARKER_TYPES.items():
            if marker_type == marker_utils.DEFAULT_TYPE:
                continue
            self._add_action(
                marker_menu,
                f'打{spec["label"]}标记',
                lambda t=marker_type: self._on_add_marker(t),
            )
        marker_menu.addSeparator()
        self._add_action(marker_menu, "删除播放头附近的标记", self._on_remove_marker, "remove_marker")
        self._add_action(marker_menu, "清空全部标记", self._model.clear_markers)
        marker_menu.addSeparator()
        self._add_action(marker_menu, "上一个标记", lambda: self._jump_marker(-1), "prev_marker")
        self._add_action(marker_menu, "下一个标记", lambda: self._jump_marker(1), "next_marker")

        # ---- 实验
        case_menu = bar.addMenu("实验(&X)")
        self._add_action(case_menu, "保存为实验案例…", self._on_save_case)
        self._add_action(case_menu, "打开案例库…", self._on_open_cases)

        # ---- 视图
        view_menu = bar.addMenu("视图(&V)")
        self._view_group = QActionGroup(self)
        self._view_group.setExclusive(True)
        for key, label in VIEW_MODES:
            action = QAction(label, self, checkable=True)
            action.setData(key)
            action.triggered.connect(lambda _c, k=key: self._apply_view_mode(k))
            self._view_group.addAction(action)
            view_menu.addAction(action)
        view_menu.addSeparator()
        self._add_action(view_menu, "时间线放大", lambda: self.timeline.zoom(1.25), "zoom_in")
        self._add_action(view_menu, "时间线缩小", lambda: self.timeline.zoom(0.8), "zoom_out")
        self._add_action(view_menu, "缩放到整条时间线", self.timeline.zoom_to_fit, "zoom_fit")
        self._add_action(view_menu, "开关磁吸", self._on_toggle_snap, "toggle_snap")
        view_menu.addSeparator()
        view_menu.addAction(self._left_dock.toggleViewAction())
        view_menu.addAction(self._right_dock.toggleViewAction())
        view_menu.addAction(self._log_dock.toggleViewAction())
        view_menu.addSeparator()
        self._add_action(view_menu, "快捷键速查…", self._on_show_shortcuts, "cheatsheet")

        # ---- 导出
        export_menu = bar.addMenu("导出(&O)")
        self._add_action(export_menu, "导出到 Remotion 工程", self._on_export_remotion)
        self._add_action(export_menu, "导出并渲染 MP4…", self._on_render_mp4, "render")
        export_menu.addSeparator()
        self._add_action(export_menu, "打开 remotion 目录", self._on_open_remotion_dir)

    def _build_toolbar(self) -> None:
        """顶部常用动作条，常用功能不用翻菜单（剪映式手感的一半靠这个）。"""
        bar = QToolBar("常用", self)
        bar.setObjectName("toolbar_main")
        bar.setMovable(False)
        bar.setIconSize(QSize(16, 16))
        bar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(Qt.TopToolBarArea, bar)

        def add(text: str, tip_action: str, slot) -> QAction:
            action = QAction(text, self)
            keys = shortcuts.primary(tip_action) if tip_action else ""
            action.setToolTip(f"{text}（{keys}）" if keys else text)
            action.triggered.connect(lambda _c=False: slot())
            bar.addAction(action)
            return action

        add("导入素材", "import_assets", self._on_import_assets)
        bar.addSeparator()
        self._toolbar_undo = add("撤销", "undo", self._model.undo)
        self._toolbar_redo = add("重做", "redo", self._model.redo)
        bar.addSeparator()
        add("分割", "split", self._on_split_current)
        add("定格", "freeze", self._on_freeze_current)
        add("删除", "delete", self._on_delete)
        add("复制", "copy", self._on_copy)
        add("粘贴", "paste", self._on_paste)
        bar.addSeparator()
        add("字幕", "", self._on_add_caption)
        add("配音", "text_to_speech", self._on_text_to_speech)
        add("导入剪映字幕", "", self._on_import_jianying)
        bar.addSeparator()
        add("校验", "validate", lambda: self.json_panel.validate(verbose=True))
        add("渲染 MP4", "render", self._on_render_mp4)
        bar.addSeparator()
        add("快捷键", "cheatsheet", self._on_show_shortcuts)

    def _register_shortcuts(self) -> None:
        """注册不挂在菜单上的键位（播放、帧步进、多选等）。

        这些键位都是单键或方向键，如果挂进菜单会被 QAction 抢焦点，
        所以统一用 QShortcut + WindowShortcut，并把按钮设成不接受焦点，
        免得空格被某个按钮吃掉。
        """
        bindings = [
            ("play_pause", self.preview.toggle_play),
            ("prev_frame", lambda: self._step_frames(-1)),
            ("next_frame", lambda: self._step_frames(1)),
            ("prev_second", lambda: self._step_seconds(-1.0)),
            ("next_second", lambda: self._step_seconds(1.0)),
            ("goto_start", self._goto_start),
            ("goto_end", self._goto_end),
            ("select_up", lambda: self._select_vertical(1)),
            ("select_down", lambda: self._select_vertical(-1)),
            ("add_marker", self._on_add_marker),
            ("remove_marker", self._on_remove_marker),
            ("prev_marker", lambda: self._jump_marker(-1)),
            ("next_marker", lambda: self._jump_marker(1)),
        ]
        self._shortcut_objects: List[QShortcut] = []
        for action_key, slot in bindings:
            for keys in shortcuts.KEYS.get(action_key, []):
                shortcut = QShortcut(QKeySequence(keys), self)
                shortcut.setContext(Qt.WindowShortcut)
                shortcut.activated.connect(slot)
                self._shortcut_objects.append(shortcut)

        # 时间线底部工具条按钮走同一套实现
        self.timeline.splitRequested.connect(self._on_split_current)
        self.timeline.deleteRequested.connect(self._on_delete)
        self.timeline.freezeRequested.connect(self._on_freeze_current)
        self.timeline.duplicateRequested.connect(self._on_duplicate)

    def _add_action(self, menu: QMenu, text: str, slot, action_key: str = "") -> QAction:
        """建菜单项。键位统一从 gui/shortcuts.py 取，主键位 + 备用键位一起注册。"""
        action = QAction(text, self)
        keys = shortcuts.KEYS.get(action_key, []) if action_key else []
        if keys:
            action.setShortcuts([QKeySequence(k) for k in keys])
        action.triggered.connect(lambda _checked=False: slot())
        menu.addAction(action)
        return action

    def _build_status_bar(self) -> None:
        self._status_project = QLabel()
        self._status_tools = QLabel()
        self.statusBar().addWidget(self._status_project, 1)
        self.statusBar().addPermanentWidget(self._status_tools)
        node = find_node()
        tools = [
            "FFmpeg 就绪" if self._ffmpeg.available else "FFmpeg 未找到",
            "Node 就绪" if node else "Node 未找到",
            "Remotion 依赖已安装" if self._exporter.node_modules_ready else "Remotion 依赖未安装",
        ]
        self._status_tools.setText("　|　".join(tools))
        self._update_status()

    def _connect_signals(self) -> None:
        self._model.logMessage.connect(self.log)
        self._model.timelineChanged.connect(self._on_timeline_changed)
        self._model.elementUpdated.connect(lambda _id: self._update_status())
        self._model.historyChanged.connect(self._refresh_history_actions)
        self._model.selectionChanged.connect(self._on_selection_changed)

        self._assets.logMessage.connect(self.log)
        self._assets.scanFinished.connect(lambda count: self._on_scan_finished(count))
        self._assets.importFinished.connect(self._on_import_finished)


        self.asset_panel.logMessage.connect(self.log)
        self.asset_panel.assetActivated.connect(self._on_asset_preview)
        self.asset_panel.addToTimelineRequested.connect(self._on_asset_add_requested)
        # 移出索引前让素材面板能查到「这个素材被时间线用了几次」
        self.asset_panel.set_usage_checker(self._asset_usage_count)


        self.library_panel.logMessage.connect(self.log)
        self.library_panel.itemActivated.connect(self._on_library_item_activated)

        self.property_panel.logMessage.connect(self.log)
        self.property_panel.saveCaseRequested.connect(self._on_save_case)

        self.json_panel.logMessage.connect(self.log)
        self.json_panel.loadRequested.connect(self._on_json_loaded)
        self.json_panel.exportRequested.connect(self._on_export_remotion)
        self.json_panel.elementPicked.connect(self._on_json_element_picked)

        self.timeline.itemDropped.connect(self._on_item_dropped)
        self.timeline.filesDropped.connect(self._on_files_dropped_on_timeline)
        self.timeline.statusMessage.connect(self.log)
        # ghost clip 要按真实时长画，所以把"payload → (元素类型, 时长, 显示名)"注入给画布
        self.timeline.set_drop_info_provider(self._drop_info_for_payload)

        self.timeline.elementDoubleClicked.connect(self._on_element_double_clicked)
        self.timeline.elementContextRequested.connect(self._on_element_context)
        self.timeline.emptyContextRequested.connect(self._on_empty_context)
        self.timeline.trackContextRequested.connect(self._on_track_context)

    # ================================================================ 日志与状态

    def log(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    def _update_status(self) -> None:
        meta = self._model.timeline.get("meta", {})
        project = self._projects.current_name or "未保存"
        self._status_project.setText(
            f"项目：{meta.get('name', '')}（{project}）　"
            f"{meta.get('width')}×{meta.get('height')}　{meta.get('fps')}fps　"
            f"时长 {self._model.duration:.2f}s　"
            f"元素 {len(self._model.elements())} 个　轨道 {len(self._model.tracks())} 条"
        )

    def _on_timeline_changed(self) -> None:
        self.timeline.set_issues(self.json_panel.issue_map())
        self.timeline.refresh()
        self._update_status()

    def _on_selection_changed(self, element_id: str) -> None:
        element = self._model.element(element_id)
        if element:
            self.timeline.scroll_to_time(float(element.get("start", 0.0)))

    def _on_scan_finished(self, count: int) -> None:
        self.log(f"素材扫描完成，共 {count} 个素材")
        self.asset_panel.refresh()
        self.library_panel.refresh()
        self.property_panel.rebuild()
        self._renderer.clear_cache()

    def _refresh_history_actions(self) -> None:
        self._undo_action.setEnabled(self._model.can_undo())
        self._redo_action.setEnabled(self._model.can_redo())

    def _apply_view_mode(self, mode: str) -> None:
        self.timeline.setVisible(mode in ("timeline", "both"))
        self.json_panel.setVisible(mode in ("json", "both"))
        for action in self._view_group.actions():
            action.setChecked(action.data() == mode)

    # ================================================================ 拖放落地

    def _drop_info_for_payload(self, payload: Dict[str, Any]) -> Tuple[str, float, str]:
        """拖放预览信息：(元素类型, 时长秒, 显示名)。

        元素类型决定 ghost 能不能落进目标轨道；返回 `""` 表示**不做轨道限制**——
        动画 / 模板 / 转场 / 字幕模板的落地逻辑自己会挑元素或轨道
        （见 _apply_animation / _expand_template / _insert_transition / _apply_caption_template），
        在这里拦住反而会砍掉原有功能。
        """
        kind = str(payload.get("kind", ""))
        item_id = str(payload.get("id", ""))
        if kind == "asset":
            asset = self._assets.get(item_id) or {}
            duration = float(asset.get("duration") or 0.0)
            asset_type = str(asset.get("type", ""))
            if asset_type == "audio":
                return ("audio", duration if duration > 0 else 3.0, self._assets.name_of(item_id))
            if asset_type == "video":
                return ("video", duration if duration > 0 else 3.0, self._assets.name_of(item_id))
            if asset_type == "overlay" and duration > 0:
                return ("video", duration, self._assets.name_of(item_id))
            if asset_type in ("image", "overlay"):
                return ("overlay", 2.0, self._assets.name_of(item_id))
            return ("", 2.0, self._assets.name_of(item_id))
        if kind == "effect":
            effect = self._libraries.effect.get(item_id) or {}
            return (
                "effect",
                float(effect.get("default_duration", 0.5)),
                str(effect.get("label", item_id)),
            )
        if kind == "effect_material":
            effect = self._libraries.effect.get(item_id) or {}
            return (
                "overlay",
                float(effect.get("default_duration", 1.0)),
                str(effect.get("label", item_id)),
            )
        if kind == "transition":
            return ("", self._libraries.transition.default_duration(item_id), item_id)
        if kind == "caption":
            return ("", 1.6, item_id)
        return ("", 1.0, item_id)

    def _on_item_dropped(self, payload: Dict[str, Any], track_id: str, time_seconds: float) -> None:
        """时间线接到一次拖放。payload 的 kind 决定生成什么元素。"""
        kind = payload.get("kind", "")
        item_id = payload.get("id", "")
        start = max(0.0, round(float(time_seconds), 3))

        if kind == "asset":
            self._add_asset_element(item_id, track_id, start)
        elif kind == "effect":
            self._add_program_effect(item_id, track_id, start)
        elif kind == "effect_material":
            self._add_material_effect(item_id, track_id, start)
        elif kind == "transition":
            self._insert_transition(item_id, start)
        elif kind == "caption":
            self._apply_caption_template(item_id, track_id, start)
        elif kind == "animation":
            self._apply_animation(item_id, start)
        elif kind == "template":
            self._expand_template(item_id, start)
        else:
            self.log(f"未识别的拖放类型：{kind}")

    def _add_asset_element(self, asset_id: str, track_id: str, start: float) -> None:
        """把素材建成元素落到时间线。

        轨道怎么定，全部交给 gui/asset_placement.py：
        - track_id 传空（菜单 / 双击路径）→ 按素材角色选默认轨，被占就顺延
        - track_id 有值（鼠标就悬在那条轨上）→ 尊重用户，只在 kind 不匹配时拒绝

        拒绝时必须说清楚「该放哪」，不能静默失败。
        """
        asset = self._assets.get(asset_id)
        if not asset:
            self.log(f"素材 {asset_id} 不在索引里")
            return

        placement = placement_for_asset(asset)
        duration = float(asset.get("duration") or 0.0)
        # 先按素材本身的时长估一个占位长度，用于「这段时间被占了没有」的判断
        span = duration if duration > 0 else (2.0 if placement.element_type == "overlay" else 3.0)

        if track_id:
            track = self._model.track(track_id) or {}
            kind = str(track.get("kind") or "")
            if kind != placement.track_kind:
                self.log(
                    f"{placement.label}素材要放到 {placement.track_kind} 轨，"
                    f"{track_id} 是 {kind or '未知'} 轨；默认位置是 {placement.default_track}"
                )
                return
            if track.get("locked"):
                self.log(f"{track_id} 已锁定，先解锁再放素材")
                return

        target_track, reason = choose_placement_track(
            placement, self._model.tracks(), self._model.elements(), start, span,
            requested_track=track_id,
        )
        if not track_id and reason:
            self.log(reason)

        asset_type = asset.get("type", "")
        element_id = self._model.new_element_id("video")

        if placement.element_type == "audio":
            length = duration if duration > 0 else 3.0
            element = tl.make_audio(
                self._model.new_element_id("audio"), asset_id, target_track, start, round(length, 3)
            )
        elif asset_type == "video" or (asset_type == "overlay" and duration > 0):
            # 带时长的透明视频也当视频叠加处理，保留 source 区间
            source_end = duration if duration > 0 else 3.0
            element = tl.make_video(element_id, asset_id, target_track, start, 0.0, round(source_end, 3))
        elif asset_type in ("image", "overlay"):
            element = tl.make_overlay(
                self._model.new_element_id("overlay"), asset_id, target_track, start, 2.0
            )
        else:
            self.log(f"素材类型 {asset_type} 不能直接放到时间线")
            return

        self._model.add_element(element, f"添加素材 {self._assets.name_of(asset_id)}")


    def _add_program_effect(self, name: str, track_id: str, start: float) -> None:
        effect = self._libraries.effect.get(name)
        if not effect:
            self.log(f"特效 {name} 不存在")
            return
        target = self._element_at(track_id, start) or self._element_at("V1", start)
        element = tl.make_effect(
            self._model.new_element_id("effect"),
            name,
            self._libraries.effect.default_params(name),
            track=track_id,
            start=start,
            duration=float(effect.get("default_duration", 0.5)),
            target=target.get("id") if target else None,
        )
        self._model.add_element(element, f"添加特效 {effect.get('label', name)}")

    def _add_material_effect(self, name: str, track_id: str, start: float) -> None:
        """素材特效写成 overlay 元素，asset 取参数表里的默认素材。"""
        effect = self._libraries.effect.get(name)
        if not effect:
            return
        params = self._libraries.effect.default_params(name)
        asset_id = str(params.get("asset") or "")
        if not asset_id or not self._assets.get(asset_id):
            # assets/effects 下还没有对应素材，就按关键词猜一个
            guess = self._libraries.asset.first_of_category("overlay", name)
            asset_id = guess.get("id", "") if guess else ""
        if not asset_id:
            self.log(
                f"素材特效 {effect.get('label', name)} 需要一个 overlay 素材，"
                f"请先把素材放到 assets/effects/ 或 assets/overlays/ 再扫描"
            )
            return
        element = tl.make_overlay(
            self._model.new_element_id("overlay"),
            asset_id,
            track_id,
            start,
            float(effect.get("default_duration", 1.0)),
        )
        # 素材特效的来路记在 label（schema 里声明过的字段），不要再写 effect_name ——
        # 那个字段全仓库没人读，且 schema 没声明，属于会静默通过校验的死数据
        element["label"] = str(effect.get("label", name))
        element["params"] = params
        self._model.add_element(element, f"添加素材特效 {effect.get('label', name)}")

    def _insert_transition(self, name: str, start: float) -> None:
        """拖转场到时间线：找落点附近的两个视频片段自动绑定。"""
        clips = sorted(
            [e for e in self._model.elements() if e.get("type") == "video" and e.get("track") == "V1"],
            key=lambda e: float(e.get("start", 0.0)),
        )
        if len(clips) < 2:
            self.log("V1 上至少需要两个视频片段才能插入转场")
            return
        # 找与落点最近的相邻片段边界
        best_index = 0
        best_delta = None
        for index in range(len(clips) - 1):
            boundary = tl.element_end(clips[index])
            delta = abs(boundary - start)
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_index = index
        from_clip, to_clip = clips[best_index], clips[best_index + 1]
        duration = self._libraries.transition.default_duration(name)
        boundary = tl.element_end(from_clip)
        element = tl.make_transition(
            self._model.new_element_id("transition"),
            name,
            from_clip["id"],
            to_clip["id"],
            max(0.0, round(boundary - duration / 2.0, 3)),
            duration,
            self._libraries.transition.default_params(name),
            track=from_clip.get("track", "V1"),
        )
        self._model.add_element(element, f"插入转场 {self._libraries.transition.label_of(name)}")

    def _apply_caption_template(self, template_name: str, track_id: str, start: float) -> None:
        """拖字幕模板：落在已有字幕上就套样式，否则新建一条字幕。"""
        target = self._element_at(track_id, start)
        if target and target.get("type") in ("caption", "caption_group"):
            element = self._model.element(target["id"])
            before = json.dumps(element.get("style", {}), ensure_ascii=False)
            self._libraries.caption.apply_to_element(element, template_name)
            self._model.set_element_field(
                target["id"],
                ["template"],
                template_name,
                f"套用字幕模板 {self._libraries.caption.label_of(template_name)}",
            )
            self.log(f"字幕 {target['id']} 样式已更新（原 style: {before}）")
            return
        text, ok = QInputDialog.getText(self, "新增字幕", "字幕内容：", text="在这里输入字幕")
        if not ok or not text.strip():
            return
        template = self._libraries.caption.get(template_name) or {}
        element = tl.make_caption(
            self._model.new_element_id("caption"),
            text.strip(),
            track_id if (self._model.track(track_id) or {}).get("kind") == "text" else "T1",
            start,
            1.6,
            template=template_name,
            caption_style=template.get("caption_style", "plain"),
        )
        self._libraries.caption.apply_to_element(element, template_name)
        self._model.add_element(element, "添加字幕")

    def _apply_animation(self, animation_id: str, start: float) -> None:
        """动画必须落在某个元素上，套用后写进该元素的 keyframes。"""
        target = None
        for element in self._model.elements():
            if element.get("type") in ("video", "overlay", "text", "caption", "caption_group", "freeze"):
                if float(element.get("start", 0.0)) <= start <= tl.element_end(element):
                    target = element
                    break
        target = target or self._model.element(self._model.selected_id)
        if not target:
            self.log("动画需要落在一个视频 / 图片 / 文字 / 字幕元素上")
            return
        animation = self._libraries.animation.get(animation_id)
        if not animation:
            return
        scaled = dict(animation)
        scaled["keyframes"] = self._libraries.animation.scaled_keyframes(
            animation_id, min(float(target.get("duration", 1.0)), float(animation.get("duration", 0.3)))
        )
        self._model.apply_animation(target["id"], scaled)

    def _expand_template(self, template_id: str, start: float) -> None:
        base_clip = self._element_at("V1", start)
        base_source_time = 0.0
        if base_clip:
            source = base_clip.get("source") or {}
            offset = (start - float(base_clip.get("start", 0.0))) * float(base_clip.get("speed", 1.0) or 1.0)
            base_source_time = round(float(source.get("start", 0.0)) + offset, 3)
        impact = self._libraries.asset.first_of_category("audio", "impact")
        context = {
            "base_clip_id": base_clip.get("id") if base_clip else "",
            "base_source_time": base_source_time,
            "impact_asset": impact.get("id", "") if impact else "",
            "caption_library": self._libraries.caption,
            "animation_library": self._libraries.animation,
        }
        elements = self._libraries.template.expand(
            template_id, start, context, lambda type_name: self._model.new_element_id(type_name)
        )
        if not elements:
            self.log(f"模板 {template_id} 展开结果为空")
            return
        self._model.add_elements(
            elements, f"展开模板 {self._libraries.template.label_of(template_id)}"
        )

    def _element_at(self, track_id: str, time_seconds: float) -> Optional[Dict[str, Any]]:
        """找某轨道上覆盖该时间点的元素。"""
        for element in tl.elements_on_track(self._model.timeline, track_id):
            if float(element.get("start", 0.0)) <= time_seconds <= tl.element_end(element):
                return element
        return None

    # ================================================================ 素材导入

    def _on_import_assets(self) -> None:
        """菜单：选文件导入素材库。"""
        paths, _filter = QFileDialog.getOpenFileNames(
            self, "导入素材到素材库", "", IMPORT_FILE_FILTER
        )
        if paths:
            self._assets.import_files(paths)

    def _on_files_dropped_on_timeline(
        self,
        paths: List[str],
        track_id: str,
        time_seconds: float,
    ) -> None:
        """从资源管理器把文件直接拖到时间线：先导入素材库，导入完成后落到落点。"""
        self.log(f"接到 {len(paths)} 个文件，落点 {track_id} @ {time_seconds:.2f}s，先导入素材库…")
        self._assets.import_files(
            paths, {"track": track_id, "time": max(0.0, round(float(time_seconds), 3))}
        )

    def _on_import_finished(self, assets: List[Dict[str, Any]], context: Dict[str, Any]) -> None:
        """导入完成：刷新面板；若是拖到时间线的，顺序排到落点上。"""
        self.library_panel.refresh()
        self._renderer.clear_cache()
        if not assets:
            return
        if context.get("starts_by_file"):
            # 批量配音：每段有自己的时间点，不能顺序排
            self._place_batch_audio(assets, context)
            self.timeline.refresh()
            return
        track_id = context.get("track", "")
        if not track_id:
            self.log(f"已导入 {len(assets)} 个素材，可以从左侧素材库拖到时间线")
            return

        cursor = float(context.get("time", self._model.playhead))
        for asset in assets:
            target_track = self._track_for_asset(asset, track_id)
            before = len(self._model.elements())
            self._add_asset_element(asset["id"], target_track, cursor)
            if len(self._model.elements()) == before:
                continue
            # 多个文件依次排开，不互相压住
            added = self._model.elements()[-1]
            cursor = round(tl.element_end(added), 3)
        self.timeline.refresh()

    def _track_for_asset(self, asset: Dict[str, Any], preferred: str) -> str:
        """落点轨道类型和素材不匹配时，换到策略给的默认轨。

        规则不在这里，在 gui/asset_placement.py —— 这里只做「合法就尊重用户，
        不合法就回落到策略默认轨」这一步转换。
        """
        placement = placement_for_asset(asset)
        kind = (self._model.track(preferred) or {}).get("kind", "")
        if kind == placement.track_kind:
            return preferred
        return placement.default_track


    # ================================================================ 文本转语音

    def _on_text_to_speech(self) -> None:
        """菜单：文本转语音。默认落在播放头位置的 A2 人声轨。"""
        self._open_tts_dialog("", self._model.playhead)

    def _on_caption_to_speech(self) -> None:
        """把选中的字幕 / 逐词字幕 / 文字元素的文本拿来配音，起点对齐该元素。"""
        element = self._model.element(self._model.selected_id)
        if not element or element.get("type") not in ("caption", "caption_group", "text"):
            QMessageBox.information(
                self,
                "先选一条字幕",
                "请先在时间线上选中一条字幕、逐词字幕或文字元素，再执行「把选中字幕转成配音」。",
            )
            return
        text = element_text(element)
        if not text.strip():
            QMessageBox.information(self, "这条元素没有文本", f"{element.get('id')} 里取不到可朗读的文本。")
            return
        self._open_tts_dialog(text, float(element.get("start", 0.0)))

    def _element_to_speech(self, element_id: str) -> None:
        """右键菜单入口：先选中再走同一套流程。"""
        self._model.select(element_id)
        self._on_caption_to_speech()

    def _open_tts_dialog(self, text: str, start: float, track_id: str = "A2") -> None:
        if not tts.available():
            QMessageBox.warning(
                self,
                "本机不能用内置配音",
                "内置文本转语音用的是 Windows 自带的离线语音合成，"
                "当前系统里没找到可用音色。\n\n"
                "可以在「设置 → 时间和语言 → 语音」里安装中文语音包后重试。",
            )
            return
        dialog = TtsDialog(
            self._model.tracks(),
            default_text=text,
            default_start=start,
            default_track=track_id or "A2",
            root=self._root,
            parent=self,
        )
        if not dialog.exec_():
            return
        self._start_tts(dialog.result_values())

    def _start_tts(self, values: Dict[str, Any]) -> None:
        """合成走后台线程，主线程不能等在 PowerShell 上。"""
        if self._tts_worker is not None and self._tts_worker.isRunning():
            self.log("上一段配音还在合成中，等它完成再试")
            return
        worker = tts.TtsWorker(
            self._root,
            values["text"],
            values["voice"],
            values["rate"],
            values["volume"],
            {
                "track": values["track"],
                "time": values["start"],
                "place": values["place"],
            },
            parent=self,
        )
        worker.progress.connect(self.log)
        worker.finished_tts.connect(self._on_tts_finished)
        worker.failed.connect(self._on_tts_failed)
        self._tts_worker = worker
        worker.start()

    def _on_tts_finished(self, wav_path: str, context: Dict[str, Any]) -> None:
        """配音文件已生成：登记进素材库，入库完成后由 _on_import_finished 落到轨道。"""
        self.log(f"配音已生成：{os.path.basename(wav_path)}，正在登记到素材库…")
        if context.get("place", True):
            self._assets.import_files(
                [wav_path],
                {"track": context.get("track", "A2"), "time": float(context.get("time", 0.0))},
            )
        else:
            self._assets.import_files([wav_path])

    def _on_tts_failed(self, message: str) -> None:
        self.log(f"配音生成失败：{message}")
        QMessageBox.warning(self, "配音生成失败", message)

    # ================================================================ 导入剪映文本

    def _on_import_jianying(self) -> None:
        """导入剪映草稿 / SRT / 纯文本，可同时生成字幕元素和逐行配音。"""
        dialog = JianyingImportDialog(
            self._model.tracks(), self._model.playhead, self._root, self
        )
        if not dialog.exec_():
            return
        values = dialog.result_values()
        lines = values.get("lines") or []
        if not lines:
            return
        self.log(f"从 {os.path.basename(values.get('source', ''))} 解析到 {len(lines)} 行文本")

        if values["make_caption"]:
            self._add_caption_lines(lines, values["caption_track"])
        if values["make_voice"]:
            self._start_batch_tts(values)

    def _add_caption_lines(self, lines: List[Dict[str, Any]], track_id: str) -> None:
        """把解析出的每一行做成一个整句字幕元素，只占一次撤销。"""
        elements = []
        for line in lines:
            duration = max(0.2, round(float(line["end"]) - float(line["start"]), 3))
            elements.append(
                tl.make_caption("", line["text"], track_id, float(line["start"]), duration)
            )
        added = self._model.add_elements(elements, f"导入剪映字幕（{len(elements)} 行）")
        self.log(f"已在 {track_id} 生成 {len(added)} 条字幕")

    def _start_batch_tts(self, values: Dict[str, Any]) -> None:
        """逐行合成配音。串行跑，进度写日志。"""
        if self._tts_batch is not None and self._tts_batch.isRunning():
            self.log("上一批配音还在合成中，等它完成再试")
            return
        lines = values["lines"]
        self._tts_placement = {
            "track": values["audio_track"],
            "avoid_overlap": values["avoid_overlap"],
        }
        worker = tts.TtsBatchWorker(
            self._root,
            lines,
            values["voice"],
            values["rate"],
            values["volume"],
            parent=self,
        )
        worker.progress.connect(self.log)
        worker.finished_batch.connect(self._on_batch_tts_finished)
        self._tts_batch = worker
        self.log(f"开始逐行合成配音，共 {len(lines)} 行（用系统离线语音，串行执行）")
        worker.start()

    def _on_batch_tts_finished(
        self,
        done: List[Dict[str, Any]],
        errors: List[str],
    ) -> None:
        for message in errors:
            self.log(f"配音：{message}")
        if not done:
            QMessageBox.warning(self, "批量配音失败", "\n".join(errors) or "没有生成任何配音")
            return
        self.log(f"配音合成完成 {len(done)} 行，正在登记到素材库…")
        starts = {os.path.basename(row["path"]): float(row["start"]) for row in done}
        self._assets.import_files(
            [row["path"] for row in done],
            {
                "track": self._tts_placement.get("track", "A2"),
                "starts_by_file": starts,
                "avoid_overlap": self._tts_placement.get("avoid_overlap", True),
            },
        )

    def _place_batch_audio(self, assets: List[Dict[str, Any]], context: Dict[str, Any]) -> None:
        """把批量配音按各自的时间点排到音频轨上。

        配音实际时长由合成结果决定，和原字幕时长不一定一致；
        勾了「避免压住」就把后面的往后顺延，否则原样放（可能重叠，会记日志）。
        """
        track_id = context.get("track", "A2")
        starts = context.get("starts_by_file") or {}
        avoid = bool(context.get("avoid_overlap", True))
        ordered = sorted(
            assets,
            key=lambda a: starts.get(os.path.basename(a.get("path", "")), 0.0),
        )
        cursor = 0.0
        overlaps = 0
        placed = []
        for asset in ordered:
            wanted = float(starts.get(os.path.basename(asset.get("path", "")), 0.0))
            duration = float(asset.get("duration") or 0.0) or 1.0
            start = wanted
            if wanted < cursor:
                overlaps += 1
                if avoid:
                    start = round(cursor, 3)
            placed.append(
                tl.make_audio("", asset["id"], track_id, round(start, 3), round(duration, 3))
            )
            cursor = round(start + duration, 3)
        added = self._model.add_elements(placed, f"导入剪映配音（{len(placed)} 段）")
        self.log(f"已在 {track_id} 放入 {len(added)} 段配音")
        if overlaps:
            if avoid:
                self.log(f"其中 {overlaps} 段配音比原字幕长，已自动往后顺延")
            else:
                self.log(f"注意：{overlaps} 段配音比原字幕长，和后一句重叠了，需要手动调整")

    # ================================================================ 窗口级文件拖放

    @staticmethod
    def _dropped_files(mime) -> List[str]:
        if not mime.hasUrls():
            return []
        return [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._dropped_files(event.mimeData()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._dropped_files(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        """拖到窗口任意空白处：只导入素材库，不自动上时间线。"""
        files = self._dropped_files(event.mimeData())
        if not files:
            return
        self._assets.import_files(files)
        event.acceptProposedAction()


    # ================================================================ 面板互动

    def _asset_usage_count(self, asset_id: str) -> int:
        """当前时间线上有多少个元素引用了这个素材。"""
        count = 0
        for element in self._model.elements():
            if element.get("asset") == asset_id:
                count += 1
            elif (element.get("params") or {}).get("asset") == asset_id:
                count += 1
        return count

    def _on_asset_preview(self, asset_id: str) -> None:
        asset = self._assets.get(asset_id)
        if asset:
            self.log(
                f"素材 {asset_id}：{asset.get('name')}　类型 {asset.get('type')}　"
                f"时长 {asset.get('duration', 0)}s　"
                f"{asset.get('width', 0)}×{asset.get('height', 0)}　路径 {asset.get('path')}"
            )

    def _on_asset_add_requested(self, asset_id: str) -> None:
        asset = self._assets.get(asset_id)
        if not asset:
            return
        # 落位规则只有一份：gui/asset_placement.py。
        # 这里不再自己写「视频 V1、音频 A3」，音乐/人声/音效也能各归各轨。
        self._add_asset_element(asset_id, "", self._model.playhead)


    def _on_add_selected_asset(self) -> None:
        asset_id = self.asset_panel.current_asset_id()
        if asset_id:
            self._on_asset_add_requested(asset_id)
        else:
            self.log("请先在素材库里选一个素材")

    def _on_library_item_activated(self, payload: Dict[str, Any]) -> None:
        """库面板双击：等价于拖到播放头位置。

        字幕 / 素材特效走统一落位策略；特效 / 转场 / 动画 / 模板依附在宿主元素上，
        轨道由宿主决定，这里只给一个进入点 V1。
        """
        kind = payload.get("kind", "")
        if kind == "asset":
            # 音效库双击：轨道交给落位策略（BGM→A1 / 人声→A2 / 音效→A3）
            default_track = ""
        elif kind == "caption":
            default_track = placement_for_element_type("caption").default_track
        elif kind == "effect_material":
            default_track = placement_for_element_type("overlay").default_track
        else:
            default_track = "V1"
        self._on_item_dropped(payload, default_track, self._model.playhead)

    def _on_json_loaded(self, data: Dict[str, Any]) -> None:
        self._model.set_timeline(data, "从 JSON 面板加载")
        self._renderer.clear_cache()

    def _on_json_element_picked(self, element_id: str) -> None:
        if self._model.element(element_id):
            self._model.select(element_id)

    def _on_element_double_clicked(self, element_id: str) -> None:
        element = self._model.element(element_id)
        if element:
            self._model.set_playhead(float(element.get("start", 0.0)))
            self._model.select(element_id)

    # ================================================================ 右键菜单

    def _on_element_context(self, element_id: str, global_pos) -> None:
        element = self._model.element(element_id)
        if not element:
            return
        menu = QMenu(self)
        menu.addAction("定位播放头到此", lambda: self._model.set_playhead(float(element.get("start", 0.0))))
        menu.addAction("复制元素", lambda: self._model.duplicate_element(element_id))
        menu.addAction("删除元素", lambda: self._model.remove_element(element_id))
        menu.addSeparator()
        if element.get("type") == "video":
            menu.addAction("在播放头处拆分", lambda: self._split_element(element_id))
            menu.addAction("在播放头处加冻结帧", lambda: self._add_freeze(element_id))
            menu.addAction("以此为起点插入转场…", lambda: self._on_insert_transition(element_id))
        if element.get("type") in ("caption", "caption_group"):
            caption_menu = menu.addMenu("套用字幕模板")
            for template in self._libraries.caption.all():
                caption_menu.addAction(
                    template.get("label", template["name"]),
                    lambda _c=False, n=template["name"]: self._apply_caption_template_to(element_id, n),
                )
        if element.get("type") in ("caption", "caption_group", "text"):
            menu.addAction("把这条文本转成配音…", lambda: self._element_to_speech(element_id))
        if element.get("type") in ("video", "overlay", "text", "caption", "caption_group", "freeze"):
            animation_menu = menu.addMenu("套用动画（关键帧模板）")
            for animation in self._libraries.animation.all():
                animation_menu.addAction(
                    animation.get("label", animation["id"]),
                    lambda _c=False, a=animation["id"]: self._apply_animation_to(element_id, a),
                )
            effect_menu = menu.addMenu("加程序特效")
            for effect in self._libraries.effect.program_effects():
                effect_menu.addAction(
                    effect.get("label", effect["name"]),
                    lambda _c=False, n=effect["name"]: self._add_effect_to(element_id, n),
                )
        menu.exec_(global_pos)

    def _on_empty_context(self, track_id: str, time_seconds: float, global_pos) -> None:
        menu = QMenu(self)
        track = self._model.track(track_id) or {}
        kind = track.get("kind", "video")
        menu.addAction(
            f"播放头移到 {time_seconds:.2f}s",
            lambda: self._model.set_playhead(time_seconds),
        )
        menu.addSeparator()
        if kind == "text":
            menu.addAction("在此新增字幕…", lambda: self._on_add_caption(track_id, time_seconds))
            menu.addAction("在此新增逐词字幕…", lambda: self._on_add_caption_group(track_id, time_seconds))
            menu.addAction("在此新增文字…", lambda: self._on_add_text(track_id, time_seconds))
        else:
            asset_menu = menu.addMenu("在此放入素材")
            wanted = "audio" if kind == "audio" else ""
            for asset in self._assets.search(asset_type=wanted)[:40]:
                asset_menu.addAction(
                    f"{asset.get('name')}（{asset.get('id')}）",
                    lambda _c=False, a=asset["id"]: self._add_asset_element(a, track_id, time_seconds),
                )
            if kind == "audio":
                menu.addAction(
                    "在此生成配音（文本转语音）…",
                    lambda: self._open_tts_dialog("", time_seconds, track_id),
                )
        menu.exec_(global_pos)

    def _on_track_context(self, track_id: str, global_pos) -> None:
        track = self._model.track(track_id)
        if not track:
            return
        menu = QMenu(self)
        menu.addAction("重命名轨道…", lambda: self._rename_track(track_id))
        menu.addAction(
            "解锁轨道" if track.get("locked") else "锁定轨道",
            lambda: self._model.toggle_track_flag(track_id, "locked"),
        )
        menu.addAction(
            "显示轨道" if track.get("hidden") else "隐藏轨道",
            lambda: self._model.toggle_track_flag(track_id, "hidden"),
        )
        menu.addSeparator()
        menu.addAction("上移一层（Z-Index +）", lambda: self._model.move_track(track_id, 1))
        menu.addAction("下移一层（Z-Index -）", lambda: self._model.move_track(track_id, -1))
        menu.addSeparator()
        menu.addAction("新增轨道…", self._on_add_track)
        menu.addAction("删除此轨道…", lambda: self._remove_track(track_id))
        menu.exec_(global_pos)

    # ================================================================ 元素操作

    def _apply_caption_template_to(self, element_id: str, template_name: str) -> None:
        element = self._model.element(element_id)
        if not element:
            return
        self._libraries.caption.apply_to_element(element, template_name)
        self._model.set_element_field(
            element_id,
            ["template"],
            template_name,
            f"套用字幕模板 {self._libraries.caption.label_of(template_name)}",
        )

    def _apply_animation_to(self, element_id: str, animation_id: str) -> None:
        element = self._model.element(element_id)
        animation = self._libraries.animation.get(animation_id)
        if not element or not animation:
            return
        scaled = dict(animation)
        scaled["keyframes"] = self._libraries.animation.scaled_keyframes(
            animation_id, min(float(element.get("duration", 1.0)), float(animation.get("duration", 0.3)))
        )
        self._model.apply_animation(element_id, scaled)

    def _add_effect_to(self, element_id: str, name: str) -> None:
        element = self._model.element(element_id)
        effect = self._libraries.effect.get(name)
        if not element or not effect:
            return
        start = max(float(element.get("start", 0.0)), self._model.playhead)
        duration = min(
            float(effect.get("default_duration", 0.5)),
            max(0.1, tl.element_end(element) - start),
        )
        new_element = tl.make_effect(
            self._model.new_element_id("effect"),
            name,
            self._libraries.effect.default_params(name),
            track=element.get("track", "V1"),
            start=round(start, 3),
            duration=round(duration, 3),
            target=element_id,
        )
        self._model.add_element(new_element, f"给 {element_id} 加特效 {effect.get('label', name)}")

    def _split_element(self, element_id: str) -> None:
        """在播放头处把视频片段拆成两段，两段的 source 区间自动接续。"""
        element = self._model.element(element_id)
        if not element or element.get("type") != "video":
            return
        cut = self._model.playhead
        start = float(element.get("start", 0.0))
        end = tl.element_end(element)
        if not (start + 0.04 < cut < end - 0.04):
            self.log("播放头必须落在片段内部才能拆分")
            return
        speed = float(element.get("speed", 1.0)) or 1.0
        source = element.get("source") or {"start": 0.0, "end": end - start}
        cut_source = float(source["start"]) + (cut - start) * speed

        tail = json.loads(json.dumps(element))  # 深拷贝
        tail["id"] = self._model.new_element_id("video")
        tail["start"] = round(cut, 3)
        tail["duration"] = round(end - cut, 3)
        tail["source"] = {"start": round(cut_source, 3), "end": round(float(source["end"]), 3)}

        self._model.resize_element(element_id, start, cut - start)
        self._model.set_element_field(
            element_id, ["source"], {"start": round(float(source["start"]), 3), "end": round(cut_source, 3)},
            "拆分片段（前半段）",
        )
        self._model.add_element(tail, "拆分片段（后半段）")

    def _add_freeze(self, element_id: str) -> None:
        element = self._model.element(element_id)
        if not element or element.get("type") != "video":
            return
        start = self._model.playhead
        if not (float(element.get("start", 0.0)) <= start <= tl.element_end(element)):
            start = float(element.get("start", 0.0))
        source = element.get("source") or {}
        offset = (start - float(element.get("start", 0.0))) * float(element.get("speed", 1.0) or 1.0)
        source_time = round(float(source.get("start", 0.0)) + offset, 3)
        freeze = tl.make_freeze(
            self._model.new_element_id("freeze"),
            element_id,
            source_time,
            round(tl.element_end(element), 3),
            1.2,
            element.get("track", "V1"),
        )
        self._model.add_element(freeze, "添加冻结帧")

    def _on_duplicate(self) -> None:
        if self._model.selected_id:
            self._model.duplicate_element(self._model.selected_id)

    def _on_delete(self) -> None:
        selection = self._model.selection()
        if len(selection) > 1:
            self._model.remove_elements(selection)
        elif self._model.selected_id:
            self._model.remove_element(self._model.selected_id)

    # ================================================================ 剪映式剪辑操作

    def _on_split_current(self) -> None:
        """Ctrl+B / 工具条：拆分播放头下的片段。

        没选中片段时，自动找播放头下面的视频片段，和剪映一样不用先点一下。
        """
        target = self._model.selected_id
        element = self._model.element(target) if target else None
        if element is None or element.get("type") != "video":
            element = self._video_under_playhead()
        if element is None:
            self.log("播放头下没有可拆分的视频片段")
            return
        self._split_element(element["id"])

    def _on_freeze_current(self) -> None:
        target = self._model.selected_id
        element = self._model.element(target) if target else None
        if element is None or element.get("type") != "video":
            element = self._video_under_playhead()
        if element is None:
            self.log("播放头下没有可加定格的视频片段")
            return
        self._add_freeze(element["id"])

    def _video_under_playhead(self) -> Optional[Dict[str, Any]]:
        """播放头下最上层的视频片段（按轨道顺序，越靠后越上层）。"""
        now = self._model.playhead
        found = None
        for element in self._model.elements():
            if element.get("type") != "video":
                continue
            if float(element.get("start", 0.0)) <= now <= tl.element_end(element):
                found = element
        return found

    def _on_copy(self) -> None:
        selection = self._model.selection()
        if not selection:
            self.log("没有选中元素，复制取消")
            return
        elements = [self._model.element(eid) for eid in selection]
        elements = [json.loads(json.dumps(e)) for e in elements if e]
        if not elements:
            return
        base = min(float(e.get("start", 0.0)) for e in elements)
        # 记住相对偏移，粘贴时以播放头为新的基准
        self._clipboard = {"base": base, "elements": elements}
        self.log(f"已复制 {len(elements)} 个元素，按 {shortcuts.primary('paste')} 粘贴到播放头")

    def _on_cut(self) -> None:
        self._on_copy()
        if self._clipboard.get("elements"):
            self._on_delete()

    def _on_paste(self) -> None:
        elements = (self._clipboard or {}).get("elements") or []
        if not elements:
            self.log("剪贴板是空的")
            return
        base = float(self._clipboard.get("base", 0.0))
        cursor = self._model.playhead
        pasted = []
        for raw in elements:
            clone = json.loads(json.dumps(raw))
            clone["id"] = ""  # 交给 add_elements 分配新 id
            offset = float(clone.get("start", 0.0)) - base
            clone["start"] = round(max(0.0, cursor + offset), 3)
            # 转场 / 特效 / 冻结帧引用的是原元素 id，粘贴后引用会失效，直接跳过
            if clone.get("type") in ("transition", "effect", "freeze"):
                continue
            pasted.append(clone)
        skipped = len(elements) - len(pasted)
        if not pasted:
            self.log("剪贴板里只有转场/特效/冻结帧，它们依附于原片段，不能单独粘贴")
            return
        added = self._model.add_elements(pasted, f"粘贴 {len(pasted)} 个元素")
        self._model.select_many(added)
        if skipped:
            self.log(f"粘贴 {len(added)} 个元素；跳过 {skipped} 个依附型元素（转场/特效/冻结帧）")

    def _step_frames(self, frames: int) -> None:
        """按帧移动播放头。播放中按方向键会先暂停，和剪映一致。"""
        self.preview.stop()
        fps = max(1.0, self._model.fps)
        self._model.set_playhead(max(0.0, self._model.playhead + frames / fps))

    def _step_seconds(self, seconds: float) -> None:
        self.preview.stop()
        self._model.set_playhead(max(0.0, self._model.playhead + seconds))

    def _goto_start(self) -> None:
        self._model.set_playhead(0.0)

    def _goto_end(self) -> None:
        self._model.set_playhead(self._model.duration)

    # ------------------------------------------------------------ 标记

    def _on_add_marker(self, marker_type: str = marker_utils.DEFAULT_TYPE) -> None:
        """在播放头处打标记。标记只写进 meta.markers，不产生任何渲染元素。"""
        self._model.add_marker(float(self._model.playhead), marker_type)

    def _on_remove_marker(self) -> None:
        """删掉播放头附近的标记。容差在 core/markers.py 里统一定义。"""
        self._model.remove_marker_at(float(self._model.playhead))

    def _jump_marker(self, direction: int) -> None:
        """跳到上/下一个标记。没有就原地不动，不要绕回去让人迷路。"""
        marker = marker_utils.nearest_marker(
            self._model.timeline, float(self._model.playhead), direction
        )
        if marker is None:
            self.log("这个方向没有标记了")
            return
        self.preview.stop()
        self._model.set_playhead(float(marker["time"]))


    def _nudge_selection(self, frames: int) -> None:
        """选中元素整体左右各挪一帧，用来对齐音画。"""
        selection = self._model.selection()
        if not selection:
            return
        delta = frames / max(1.0, self._model.fps)
        for element_id in selection:
            element = self._model.element(element_id)
            if element is None or self._model.is_track_locked(element.get("track", "")):
                continue
            self._model.move_element(
                element_id, max(0.0, float(element.get("start", 0.0)) + delta), None
            )

    def _select_vertical(self, direction: int) -> None:
        """↑↓：跳到上一条 / 下一条轨道上、同时刻的元素。"""
        order = [t.get("id") for t in self._model.tracks()]
        current = self._model.element(self._model.selected_id) or {}
        now = self._model.playhead
        if current:
            now = max(float(current.get("start", 0.0)), min(now, tl.element_end(current)))
            index = order.index(current.get("track")) if current.get("track") in order else 0
        else:
            index = 0
        index += direction
        while 0 <= index < len(order):
            candidate = self._element_at(order[index], now)
            if candidate is not None:
                self._model.select(candidate["id"])
                return
            index += direction
        self.log("那个方向上同一时刻没有元素")

    def _on_select_all(self) -> None:
        self._model.select_all()
        self.log(f"已选中 {len(self._model.selection())} 个元素")

    def _on_toggle_snap(self) -> None:
        self.timeline.toggle_snap()
        self.log("磁吸已" + ("打开" if self.timeline.snap_enabled() else "关闭"))

    def _on_show_shortcuts(self) -> None:
        ShortcutDialog(self).exec_()

    # ================================================================ 轨道操作

    def _on_add_track(self) -> None:
        dialog = TrackDialog([t.get("id") for t in self._model.tracks()], self)
        if dialog.exec_():
            track_id, name, kind = dialog.result_values()
            self._model.add_track(track_id, name, kind)

    def _rename_track(self, track_id: str) -> None:
        track = self._model.track(track_id) or {}
        name, ok = QInputDialog.getText(self, "重命名轨道", "轨道名称：", text=track.get("name", track_id))
        if ok and name.strip():
            self._model.rename_track(track_id, name.strip())

    def _remove_track(self, track_id: str) -> None:
        count = len([e for e in self._model.elements() if e.get("track") == track_id])
        answer = QMessageBox.question(
            self,
            "删除轨道",
            f"删除轨道 {track_id} 会同时删除它上面的 {count} 个元素，继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._model.remove_track(track_id)

    def _on_remove_current_track(self) -> None:
        element = self._model.element(self._model.selected_id)
        if element:
            self._remove_track(element.get("track", ""))
        else:
            self.log("请先选中一个元素，用来确定要删除哪条轨道")

    # ================================================================ 新增元素

    def _on_insert_transition(self, from_id: str = "") -> None:
        to_id = ""
        if from_id:
            clips = sorted(
                [e for e in self._model.elements() if e.get("type") == "video"],
                key=lambda e: float(e.get("start", 0.0)),
            )
            ids = [c["id"] for c in clips]
            if from_id in ids:
                index = ids.index(from_id)
                if index + 1 < len(ids):
                    to_id = ids[index + 1]
        dialog = TransitionDialog(self._model.timeline, self._libraries.transition, from_id, to_id, self)
        if dialog.exec_():
            element = dialog.result_element(self._model.new_element_id("transition"))
            if element:
                self._model.add_element(element, "插入转场")

    def _on_add_caption(self, track_id: str = "T1", start: float = -1.0) -> None:
        text, ok = QInputDialog.getText(self, "新增整句字幕", "字幕内容：")
        if not ok or not text.strip():
            return
        start = self._model.playhead if start < 0 else start
        element = tl.make_caption(
            self._model.new_element_id("caption"), text.strip(), track_id or "T1", round(start, 3), 1.6
        )
        self._model.add_element(element, "添加整句字幕")

    def _on_add_caption_group(self, track_id: str = "T1", start: float = -1.0) -> None:
        text, ok = QInputDialog.getText(
            self, "新增逐词字幕", "用空格分词，例如：这是 一个 逐词 字幕："
        )
        if not ok or not text.strip():
            return
        start = self._model.playhead if start < 0 else start
        words: List[Dict[str, Any]] = []
        cursor = round(start, 3)
        for word in text.split():
            words.append({"text": word, "start": round(cursor, 3), "end": round(cursor + 0.4, 3)})
            cursor += 0.4
        element = tl.make_caption_group(
            self._model.new_element_id("caption_group"), words, track_id or "T1"
        )
        self._model.add_element(element, "添加逐词字幕")

    def _on_add_text(self, track_id: str = "T2", start: float = -1.0) -> None:
        text, ok = QInputDialog.getText(self, "新增文字", "文字内容：")
        if not ok or not text.strip():
            return
        start = self._model.playhead if start < 0 else start
        element = tl.make_text(
            self._model.new_element_id("text"), text.strip(), track_id or "T2", round(start, 3), 2.0
        )
        self._model.add_element(element, "添加文字")

    def _quick_add_from_library(self, kind: str) -> None:
        """从菜单快速添加库项目：弹一个选择列表。"""
        if kind == "effect":
            items = [(e["name"], e.get("label", e["name"])) for e in self._libraries.effect.program_effects()]
            track = "V1"   # 程序特效依附宿主元素，V1 只是进入点
        elif kind == "effect_material":
            items = [(e["name"], e.get("label", e["name"])) for e in self._libraries.effect.material_effects()]
            track = placement_for_element_type("overlay").default_track
        elif kind == "template":
            items = [(t["id"], t.get("name", t["id"])) for t in self._libraries.template.all()]
            track = "V1"

        else:
            return
        if not items:
            self.log("库里没有可用项目")
            return
        labels = [label for _key, label in items]
        label, ok = QInputDialog.getItem(self, "选择", "选一个加到播放头位置：", labels, 0, False)
        if not ok:
            return
        key = items[labels.index(label)][0]
        self._on_item_dropped({"kind": kind, "id": key}, track, self._model.playhead)

    def _on_save_caption_template(self) -> None:
        element = self._model.element(self._model.selected_id)
        if not element or element.get("type") not in ("caption", "caption_group"):
            self.log("请先选中一条字幕")
            return
        name, ok = QInputDialog.getText(self, "保存字幕模板", "模板名称（英文小写下划线）：")
        if not ok or not name.strip():
            return
        template = {
            "name": name.strip(),
            "label": name.strip(),
            "caption_style": element.get("caption_style", "plain"),
            "category": "自定义",
            "description": "由 GUI 保存",
            "style": element.get("style", {}),
            "highlight": element.get("highlight", {}),
            "transform": element.get("transform", {}),
        }
        path = self._libraries.caption.save_template(template)
        self.log(f"字幕模板已保存：{path}")
        self.library_panel.refresh()

    # ================================================================ 项目

    def _on_new_project(self) -> None:
        self._model.reset("未命名项目")
        self._renderer.clear_cache()
        self._update_status()

    def _on_open_project(self) -> None:
        dialog = OpenProjectDialog(self._projects, self)
        if not dialog.exec_():
            return
        target = dialog.selected_dir()
        if not target:
            return
        try:
            timeline, info = self._projects.load(target)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "打开项目失败", str(exc))
            return
        self._model.set_timeline(timeline, f"打开项目 {info.get('name', os.path.basename(target))}")
        self._renderer.clear_cache()
        self._update_status()

    def _on_save_project(self) -> None:
        target = self._projects.save(self._model.to_dict(), self._assets.manifest_dict())
        self.log(f"项目已保存：{target}")
        self._update_status()

    def _on_save_project_as(self) -> None:
        name, ok = QInputDialog.getText(
            self, "项目另存为", "项目目录名：", text=self._projects.next_project_name()
        )
        if not ok or not name.strip():
            return
        target = os.path.join(self._projects.projects_dir, name.strip())
        self._projects.save(self._model.to_dict(), self._assets.manifest_dict(), target)
        self.log(f"项目已另存为：{target}")
        self._update_status()

    def _on_load_timeline_json(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "加载 Timeline JSON", self._root, "JSON 文件 (*.json)"
        )
        if not path:
            return
        try:
            data = self._projects.load_timeline_file(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "加载失败", str(exc))
            return
        self._model.set_timeline(data, f"加载 {os.path.basename(path)}")
        self._renderer.clear_cache()
        issues = self.json_panel.validate(verbose=True)
        errors = [i for i in issues if i.is_error()]
        if errors:
            self.log(f"注意：这份 JSON 有 {len(errors)} 个错误，红色标记的元素需要修正")

    def _on_export_timeline_json(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, "导出 Timeline JSON", os.path.join(self._root, "timeline.json"), "JSON 文件 (*.json)"
        )
        if not path:
            return
        self._projects.save_timeline_only(self._model.to_dict(), path)
        self.log(f"Timeline JSON 已导出：{path}")

    def _on_project_settings(self) -> None:
        dialog = ProjectSettingsDialog(self._model.timeline.get("meta", {}), self)
        if not dialog.exec_():
            return
        for key, value in dialog.result_meta().items():
            self._model.set_meta(key, value)
        self._renderer.clear_cache()
        self._update_status()

    def _on_reload_demo(self) -> None:
        self.log("正在重新生成 Demo 项目…")
        timeline = demo_project.bootstrap_demo(self._assets, self.log)
        self._model.set_timeline(timeline, "加载 Demo 项目")
        self.asset_panel.refresh()
        self._renderer.clear_cache()
        self.timeline.zoom_to_fit()
        self._update_status()

    def _on_open_assets_dir(self) -> None:
        self._open_in_explorer(os.path.join(self._root, "assets"))

    def _on_open_remotion_dir(self) -> None:
        self._open_in_explorer(self._exporter.remotion_dir)

    def _open_in_explorer(self, path: str) -> None:
        if not os.path.isdir(path):
            self.log(f"目录不存在：{path}")
            return
        os.startfile(path)  # noqa: S606  仅 Windows，打开资源管理器

    # ================================================================ 实验案例

    def _on_save_case(self) -> None:
        element_id = self._model.selected_id
        summary = f"当前关注元素：{element_id or '（无）'}，元素总数 {len(self._model.elements())}"
        dialog = SaveCaseDialog(f"案例_{len(self._projects.list_cases()) + 1:03d}", summary, self)
        if not dialog.exec_():
            return
        payload = {
            "name": dialog.case_name(),
            "note": dialog.case_note(),
            "focus_element": element_id,
            "timeline": self._model.to_dict(),
        }
        path = self._projects.save_case(dialog.case_name(), payload)
        self.log(f"实验案例已保存：{path}")

    def _on_open_cases(self) -> None:
        dialog = CaseBrowserDialog(self._projects, self)
        if not dialog.exec_():
            return
        case = dialog.loaded_case()
        if not case:
            return
        self._model.set_timeline(case["timeline"], f"加载案例 {case.get('name', '')}")
        self._renderer.clear_cache()
        if case.get("focus_element"):
            self._model.select(case["focus_element"])

    # ================================================================ 导出与渲染

    def _on_export_remotion(self) -> Optional[Dict[str, Any]]:
        issues = self._validator.validate(self._model.timeline)
        errors = [i for i in issues if i.is_error()]
        if errors:
            answer = QMessageBox.question(
                self,
                "校验未通过",
                f"当前 Timeline 有 {len(errors)} 个错误，仍然导出？\n\n"
                + "\n".join(i.display() for i in errors[:8]),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return None
        result = self._exporter.export(self._model.to_dict())
        self.log(
            f"已导出到 Remotion 工程：{result['remotion_dir']}　"
            f"素材 {result['asset_count']} 个（复制 {result['copied']} 个）"
        )
        if result["missing"]:
            self.log(f"注意：以下素材文件缺失，渲染会失败：{result['missing']}")
        return result

    def _on_render_mp4(self) -> None:
        if self._render_worker is not None and self._render_worker.isRunning():
            self.log("已有渲染任务在跑，请等它结束")
            return
        if self._on_export_remotion() is None:
            return
        default_name = os.path.join(self._root, "out", "timeline.mp4")
        path, _filter = QFileDialog.getSaveFileName(self, "渲染 MP4", default_name, "MP4 视频 (*.mp4)")
        if not path:
            return
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        install = not self._exporter.node_modules_ready
        if install:
            self.log("首次渲染需要先安装 Remotion 依赖，这一步比较慢")
        self._render_worker = RemotionRenderWorker(self._exporter.remotion_dir, path, install, parent=self)
        self._render_worker.output.connect(self.log)
        self._render_worker.finishedRender.connect(self._on_render_finished)
        self._render_worker.start()
        self.log("渲染已在后台开始，GUI 不会卡住")

    def _on_render_finished(self, ok: bool, message: str) -> None:
        if ok:
            self.log(f"渲染完成：{message}")
            QMessageBox.information(self, "渲染完成", f"MP4 已生成：\n{message}")
        else:
            self.log(f"渲染失败：{message}")
            QMessageBox.warning(self, "渲染失败", message)

    # ================================================================ 生命周期

    def closeEvent(self, event) -> None:  # noqa: N802
        self.preview.stop()
        self.preview_audio.shutdown()
        self._renderer.shutdown()
        if self._render_worker is not None and self._render_worker.isRunning():
            self._render_worker.wait(2000)
        super().closeEvent(event)

    def load_initial_timeline(self, timeline: Dict[str, Any], description: str) -> None:
        """启动时把 Demo / 上次项目塞进模型，并把视图调到合适缩放。"""
        self._model.set_timeline(timeline, description)
        QTimer.singleShot(0, self.timeline.zoom_to_fit)
        self._update_status()
