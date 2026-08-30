"""AI_Timeline_Builder 入口。

启动方式：
    python main.py

这里只做装配：把素材管理、库、校验器、模型、预览渲染器、Remotion 导出器
组装好后交给主窗口，然后准备 Demo 项目。
业务逻辑一律不写在本文件里。
"""

from __future__ import annotations

import os
import sys

# 保证无论从哪个目录启动，import core / gui / render 都能找到
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt5.QtCore import Qt, QTimer  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from core.asset_manager import AssetManager  # noqa: E402
from core.project_manager import ProjectManager  # noqa: E402
from core.timeline_model import TimelineModel  # noqa: E402
from core.timeline_validator import TimelineValidator  # noqa: E402
from core.undo_manager import UndoManager  # noqa: E402
from core import demo_project  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402
from libraries.asset_library import Libraries  # noqa: E402
from render.preview_renderer import PreviewRenderer  # noqa: E402
from render.remotion_exporter import RemotionExporter  # noqa: E402

DARK_STYLESHEET = """
QWidget { background-color: #1b1f27; color: #d8dee9; font-size: 12px; }
QMainWindow::separator { background: #2a3040; width: 3px; height: 3px; }
QMenuBar { background-color: #171b24; }
QMenuBar::item:selected { background: #2d3546; }
QMenu { background-color: #1f2531; border: 1px solid #2f3746; }
QMenu::item:selected { background: #2d3546; }
QDockWidget { titlebar-close-icon: none; }
QDockWidget::title { background: #171b24; padding: 5px; }
QTabWidget::pane { border: 1px solid #2a3040; }
QTabBar::tab { background: #1f2531; padding: 5px 10px; border: 1px solid #2a3040; }
QTabBar::tab:selected { background: #2d3546; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QListWidget,
QTreeWidget, QTableWidget {
    background-color: #141821; border: 1px solid #2f3746; selection-background-color: #35507a;
}
QPushButton { background-color: #29313f; border: 1px solid #3a4456; padding: 4px 10px; }
QPushButton:hover { background-color: #34405266; }
QPushButton:pressed { background-color: #35507a; }
QPushButton:disabled { color: #6b7484; }
QGroupBox { border: 1px solid #2f3746; margin-top: 12px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; color: #9fb3cc; }
QScrollBar:vertical { background: #171b24; width: 12px; }
QScrollBar:horizontal { background: #171b24; height: 12px; }
QScrollBar::handle { background: #3a4456; border-radius: 3px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QStatusBar { background: #171b24; color: #9fb3cc; }
QSlider::groove:horizontal { height: 4px; background: #2f3746; }
QSlider::handle:horizontal { background: #5aa9e6; width: 10px; margin: -5px 0; border-radius: 5px; }
QToolTip { background-color: #141821; color: #d8dee9; border: 1px solid #3a4456; }
"""


def main() -> int:
    # Windows 11 在 125% / 150% / 175% 缩放下，Qt5 默认不缩放 → 界面按物理像素显示，
    # 行高 44px 在 150% 屏上观感只有 29px，片段很难点。开启逻辑像素缩放后：
    # 鼠标事件与 QPainter **都**在逻辑像素坐标系里，两者单位一致，
    # 所以 TimelineCoordinate 的换算不需要关心 devicePixelRatio（审计第 15、16 问）。
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("AI Timeline Builder")
    app.setStyleSheet(DARK_STYLESHEET)

    assets_dir = os.path.join(ROOT, "assets")
    schemas_dir = os.path.join(ROOT, "schemas")
    cache_dir = os.path.join(ROOT, ".cache", "preview")

    asset_manager = AssetManager(ROOT)
    libraries = Libraries(assets_dir, asset_manager)
    validator = TimelineValidator(schemas_dir, asset_manager, libraries.as_dict())
    undo_manager = UndoManager()
    model = TimelineModel(undo_manager)
    model.set_validator(validator)   # GUI → Model → Schema 校验 → JSON 这条链的接线点
    renderer = PreviewRenderer(model, asset_manager, libraries, cache_dir)
    exporter = RemotionExporter(ROOT, asset_manager)
    projects = ProjectManager(ROOT)

    window = MainWindow(
        ROOT,
        model,
        asset_manager,
        libraries,
        validator,
        renderer,
        exporter,
        projects,
    )
    window.show()

    # 退出收尾必须挂在 aboutToQuit 上，不能只写在 closeEvent 里：
    # 「文件 → 退出」、app.quit()、任务栏结束、Ctrl+C 这些路径**不经过** closeEvent，
    # 抽帧线程就会带着运行状态被 Qt 销毁 —— 那是进程级 fastfail（0xC0000409），
    # 用户看到的现象是「什么都没动，程序自己崩了」。shutdown() 是幂等的。
    app.aboutToQuit.connect(window.preview.stop)
    app.aboutToQuit.connect(renderer.shutdown)


    window.log("AI 视频时间线规则实验器已启动。所有时间单位为秒，帧率只在渲染时使用。")
    window.log(f"工作目录：{ROOT}")

    def bootstrap() -> None:
        """窗口显示后再准备 Demo，避免启动时黑屏。"""
        window.log("正在准备 Demo 项目（首次启动需要合成演示素材）…")
        timeline = demo_project.bootstrap_demo(asset_manager, window.log)
        window.load_initial_timeline(timeline, "加载 Demo 项目")
        window.asset_panel.refresh()
        window.library_panel.refresh()
        window.log("Demo 已就绪：拖素材、改参数、看 JSON，然后用「导出 → 导出并渲染 MP4」出片。")

    QTimer.singleShot(50, bootstrap)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
