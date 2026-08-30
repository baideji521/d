"""对话框集合。"""

from gui.dialogs.track_dialog import TrackDialog
from gui.dialogs.transition_dialog import TransitionDialog
from gui.dialogs.project_dialog import ProjectSettingsDialog, OpenProjectDialog
from gui.dialogs.case_dialog import SaveCaseDialog, CaseBrowserDialog
from gui.dialogs.tts_dialog import TtsDialog, element_text
from gui.dialogs.jianying_dialog import JianyingImportDialog
from gui.dialogs.shortcut_dialog import ShortcutDialog

__all__ = [
    "TrackDialog",
    "TransitionDialog",
    "ProjectSettingsDialog",
    "OpenProjectDialog",
    "SaveCaseDialog",
    "CaseBrowserDialog",
    "TtsDialog",
    "element_text",
    "JianyingImportDialog",
    "ShortcutDialog",
]
