"""本地素材库面板。

上半部分是分类 + 搜索，下半部分是素材列表（带缩略图）。
列表项可以直接拖到 Timeline 上，双击预览，右键有完整的文件操作菜单。

扫描是后台线程做的，扫描期间面板不会卡住，只是列表暂时是旧数据。
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QDrag, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.asset_manager import ASSET_CATEGORIES, IMPORT_FILE_FILTER
from gui.timeline_widget import make_drag_payload

THUMB_SIZE = QSize(104, 68)


class AssetListWidget(QListWidget):
    """支持拖出的素材列表，同时接收从资源管理器拖进来的文件。"""

    filesDropped = pyqtSignal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setViewMode(QListWidget.IconMode)
        self.setIconSize(THUMB_SIZE)
        self.setGridSize(QSize(THUMB_SIZE.width() + 18, THUMB_SIZE.height() + 44))
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setWordWrap(True)
        self.setSpacing(4)

    def startDrag(self, supported_actions) -> None:  # noqa: N802
        item = self.currentItem()
        if item is None:
            return
        asset = item.data(Qt.UserRole)
        if not asset:
            return
        drag = QDrag(self)
        drag.setMimeData(make_drag_payload("asset", asset["id"], {"asset_type": asset.get("type")}))
        icon = item.icon()
        if not icon.isNull():
            drag.setPixmap(icon.pixmap(THUMB_SIZE))
        drag.exec_(Qt.CopyAction)

    # ------------------------------------------------------------ 外部文件拖入

    @staticmethod
    def _local_files(mime) -> List[str]:
        if not mime.hasUrls():
            return []
        return [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._local_files(event.mimeData()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._local_files(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        files = self._local_files(event.mimeData())
        if not files:
            return
        self.filesDropped.emit(files)
        event.acceptProposedAction()



class AssetPanel(QWidget):
    """素材库面板。"""

    assetActivated = pyqtSignal(str)  # 双击预览
    addToTimelineRequested = pyqtSignal(str)  # 右键「加入时间线」
    logMessage = pyqtSignal(str)

    def __init__(self, asset_manager, asset_library, parent=None) -> None:
        super().__init__(parent)
        self._assets = asset_manager
        self._library = asset_library

        self._type_box = QComboBox()
        for key, label in ASSET_CATEGORIES:
            self._type_box.addItem(label, key)
        self._type_box.currentIndexChanged.connect(self._on_type_changed)

        self._category_box = QComboBox()
        self._category_box.addItem("全部分类", "")
        self._category_box.currentIndexChanged.connect(lambda _i: self.refresh())

        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索名称 / id / 标签 / 路径")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(lambda _t: self.refresh())

        import_button = QPushButton("导入素材…")
        import_button.setToolTip(
            "从任意位置选视频 / 图片 / 音频 / 字体，文件会被复制进 assets/ 并自动登记 id。\n"
            "也可以直接把文件从资源管理器拖到这个列表，或者拖到时间线上。"
        )
        import_button.clicked.connect(self._on_import_clicked)

        rescan_button = QPushButton("重新扫描")
        rescan_button.setFixedWidth(78)
        rescan_button.clicked.connect(self._assets.rescan)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#7f8a99;")
        self._status.setWordWrap(True)

        self.list_widget = AssetListWidget()
        self.list_widget.itemDoubleClicked.connect(self._on_double_clicked)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_context_menu)
        self.list_widget.filesDropped.connect(self._on_files_dropped)

        top_row = QHBoxLayout()
        top_row.setSpacing(4)
        top_row.addWidget(self._type_box, 1)
        top_row.addWidget(rescan_button)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(4)
        filter_row.addWidget(self._category_box, 1)
        filter_row.addWidget(import_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.addLayout(top_row)
        layout.addLayout(filter_row)
        layout.addWidget(self._search)
        layout.addWidget(self.list_widget, 1)
        layout.addWidget(self._status)

        asset_manager.scanFinished.connect(self._on_scan_finished)
        asset_manager.scanProgress.connect(self._status.setText)
        asset_manager.importFinished.connect(self._on_import_finished)
        self._on_type_changed(0)

    # ------------------------------------------------------------ 导入

    def _on_import_clicked(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self, "导入素材到素材库", "", IMPORT_FILE_FILTER
        )
        if paths:
            self._assets.import_files(paths)

    def _on_files_dropped(self, paths: List[str]) -> None:
        """从资源管理器直接拖到素材面板。"""
        self._assets.import_files(paths)

    def _on_import_finished(self, assets: List[Dict[str, Any]], _context: Dict[str, Any]) -> None:
        if not assets:
            self._status.setText("没有导入任何素材（格式不支持或复制失败）")
            return
        self._status.setText(f"已导入 {len(assets)} 个素材")
        # 切到第一个导入素材所属的类型，让用户马上看到它
        first_type = assets[0].get("type", "")
        index = self._type_box.findData(first_type)
        if index >= 0 and index != self._type_box.currentIndex():
            self._type_box.setCurrentIndex(index)
        else:
            self._on_type_changed(self._type_box.currentIndex())


    # ------------------------------------------------------------ 刷新

    def _current_type(self) -> str:
        return self._type_box.currentData() or "video"

    def _on_type_changed(self, _index: int) -> None:
        section = self._current_type()
        self._category_box.blockSignals(True)
        self._category_box.clear()
        self._category_box.addItem("全部分类", "")
        for category in self._assets.categories_of(section):
            self._category_box.addItem(category, category)
        self._category_box.blockSignals(False)
        self.refresh()

    def _on_scan_finished(self, count: int) -> None:
        self._status.setText(f"扫描完成，索引 {count} 个素材")
        self._on_type_changed(self._type_box.currentIndex())

    def refresh(self) -> None:
        asset_type = self._current_type()
        keyword = self._search.text()
        category = self._category_box.currentData() or ""
        items = self._assets.search(keyword=keyword, asset_type=asset_type, category=category)

        self.list_widget.clear()
        for asset in items:
            item = QListWidgetItem()
            item.setText(f"{asset.get('name', '')}\n{self._library.describe(asset)}")
            item.setData(Qt.UserRole, asset)
            item.setToolTip(
                f"id: {asset.get('id')}\n"
                f"类型: {asset.get('type')}  分类: {asset.get('category')}\n"
                f"路径: {asset.get('path')}\n"
                f"{self._library.describe(asset)}"
            )
            icon = self._icon_for(asset)
            if icon is not None:
                item.setIcon(icon)
            self.list_widget.addItem(item)

        self._status.setText(f"{asset_type}：{len(items)} 项")

    def _icon_for(self, asset: Dict[str, Any]) -> Optional[QIcon]:
        path = self._assets.thumbnail_path(asset["id"])
        if path and os.path.isfile(path):
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                return QIcon(pixmap)
        return None

    # ------------------------------------------------------------ 交互

    def _selected_asset(self) -> Optional[Dict[str, Any]]:
        item = self.list_widget.currentItem()
        return item.data(Qt.UserRole) if item else None

    def current_asset_id(self) -> str:
        """当前选中素材的 id，供主窗口菜单「加到播放头位置」使用。"""
        asset = self._selected_asset()
        return str(asset.get("id", "")) if asset else ""


    def _on_double_clicked(self, item: QListWidgetItem) -> None:
        asset = item.data(Qt.UserRole)
        if asset:
            self.assetActivated.emit(asset["id"])

    def _on_context_menu(self, position) -> None:
        item = self.list_widget.itemAt(position)
        if item is None:
            return
        self.list_widget.setCurrentItem(item)
        asset = item.data(Qt.UserRole)
        if not asset:
            return

        menu = QMenu(self)
        menu.addAction("加入时间线", lambda: self.addToTimelineRequested.emit(asset["id"]))
        menu.addAction("预览", lambda: self.assetActivated.emit(asset["id"]))
        menu.addSeparator()
        menu.addAction("打开文件", lambda: self._open_file(asset))
        menu.addAction("定位文件", lambda: self._reveal_file(asset))
        menu.addSeparator()
        menu.addAction("重命名", lambda: self._rename(asset))
        menu.addAction("刷新索引", self._assets.rescan)
        menu.addAction("从索引删除", lambda: self._drop_index(asset))
        menu.exec_(self.list_widget.mapToGlobal(position))

    def _open_file(self, asset: Dict[str, Any]) -> None:
        path = self._assets.abs_path(asset["id"])
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "打开失败", f"文件不存在：{path}")
            return
        os.startfile(path)  # noqa: S606  Windows 专用，本工具就是 Windows 桌面工具

    def _reveal_file(self, asset: Dict[str, Any]) -> None:
        path = self._assets.abs_path(asset["id"])
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "定位失败", f"文件不存在：{path}")
            return
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])

    def _rename(self, asset: Dict[str, Any]) -> None:
        new_name, ok = QInputDialog.getText(
            self, "重命名素材", "新名称：", text=asset.get("name", "")
        )
        if ok and new_name.strip():
            self._assets.rename(asset["id"], new_name.strip())
            self.refresh()

    def set_usage_checker(self, checker) -> None:
        """主窗口注入「这个素材被时间线用了几次」的查询函数。

        素材面板本身不认识时间线，靠这个回调才能在移出索引前给出警告。
        """
        self._usage_checker = checker

    def _drop_index(self, asset: Dict[str, Any]) -> None:
        used = 0
        checker = getattr(self, "_usage_checker", None)
        if callable(checker):
            used = int(checker(asset["id"]))

        if used:
            confirm = QMessageBox.warning(
                self,
                "该素材正在使用中",
                f"{asset['id']} 正被当前时间线上的 {used} 个元素引用。\n"
                f"移出索引后这些元素会立刻报 RULE_ASSET_001 错误，导出也会失败。\n\n"
                f"磁盘文件不会删除，按 F5 重新扫描可以带着原来的 id 恢复。\n"
                f"确定仍要移出索引吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
        else:
            confirm = QMessageBox.question(
                self,
                "从索引删除",
                f"确定把 {asset['id']} 从素材清单移除吗？\n"
                f"磁盘文件不会被删除，重新扫描会带着原来的 id 再次出现。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
        if confirm == QMessageBox.Yes:
            self._assets.drop_index(asset["id"])
            self.refresh()

