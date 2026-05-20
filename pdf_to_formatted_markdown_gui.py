from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
from typing import Iterable

from PySide6.QtCore import QObject, QEasingCurve, Property, QPropertyAnimation, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QDragEnterEvent, QDropEvent, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QSizePolicy,
    QSplitter,
    QStyle,
    QTabWidget,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qt_material import apply_stylesheet

from pdf_to_formatted_markdown import (
    ConversionCancelled,
    ConversionOptions,
    ConversionProgress,
    DEFAULT_API_URL,
    DEFAULT_MODEL,
    SUPPORTED_INPUT_SUFFIXES,
    StreamProgress,
    call_responses_api,
    convert_pdf_to_markdown,
    find_soffice_executable,
    get_office_conversion_help_text,
    list_available_models,
)


CONFIG_FILE_NAME = "pdf2md.config"
APP_CONFIG_DIR_NAME = "PDF2MD Workbench"
CONFIG_VERSION = 2
SUPPORTED_INPUT_LABEL = "PDF, DOC, DOCX, PPT, or PPTX"
CONFIG_DEFAULTS = {
    "config_version": CONFIG_VERSION,
    "api_key": "",
    "api_url": DEFAULT_API_URL,
    "model": DEFAULT_MODEL,
    "known_models": [],
    "output_dir": "",
    "style_reference": "",
    "pages_per_request": "4",
    "max_concurrency": "4",
    "render_dpi": "160",
    "page_text_limit": "0",
    "timeout": "300",
    "chunk_cache_dir": "",
    "overwrite_mode": "rename",
    "stream": True,
    "auto_crop_images": True,
}

STATUS_QUEUED = "Queued"
STATUS_RUNNING = "Running"
STATUS_DONE = "Done"
STATUS_FAILED = "Failed"
STATUS_CANCELLED = "Cancelled"
ICON_DIRECTORY = Path("assets") / "icons"

THEME_NAME = "light_cyan_500.xml"
APP_STYLESHEET = """
QMainWindow {
    background: #f5f7fb;
}
QWidget#centralWidget {
    background: #f5f7fb;
}
QFrame#card, QFrame#queueCard, QFrame#sideCard {
    background: rgba(255, 255, 255, 0.94);
    border: 1px solid rgba(15, 23, 42, 0.08);
    border-radius: 18px;
}
QFrame#subCard {
    background: rgba(248, 250, 252, 0.95);
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-radius: 16px;
}
QFrame#surfaceHost {
    background: rgba(248, 250, 252, 0.74);
    border: 1px solid rgba(148, 163, 184, 0.16);
    border-radius: 16px;
}
QLabel#titleLabel {
    color: #0f172a;
    font-size: 26px;
    font-weight: 700;
}
QLabel#eyebrowLabel {
    color: #0891b2;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
QLabel#subtitleLabel {
    color: #475569;
    font-size: 13px;
}
QLabel#summaryLabel, QLabel#statusLabel, QLabel#streamLabel {
    color: #475569;
    font-size: 12px;
}
QLabel#panelTitle {
    color: #0f172a;
    font-size: 18px;
    font-weight: 700;
}
QLabel#panelCaption {
    color: #64748b;
    font-size: 12px;
}
QLabel#cardTitle {
    color: #0f172a;
    font-size: 15px;
    font-weight: 700;
}
QLabel#cardCaption {
    color: #64748b;
    font-size: 12px;
}
QLabel#sectionTitle {
    color: #0f172a;
    font-size: 14px;
    font-weight: 600;
}
QLabel#metaLabel {
    color: #64748b;
    font-size: 11px;
    font-weight: 600;
}
QLabel#metaValue {
    color: #0f172a;
    font-size: 13px;
    font-weight: 600;
}
QLabel#noteBody {
    color: #475569;
    font-size: 12px;
}
QLabel#dropLabel {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ecfeff, stop:1 #e0f2fe);
    color: #0f766e;
    border: 1px dashed rgba(13, 148, 136, 0.35);
    border-radius: 14px;
    padding: 20px;
    font-size: 13px;
    font-weight: 600;
}
QTabWidget::pane {
    border: none;
    background: transparent;
}
QTabWidget#workspaceTabs, QTabWidget#previewTabs {
    background: transparent;
}
QTabWidget#workspaceTabs QTabBar, QTabWidget#previewTabs QTabBar {
    background: transparent;
}
QTabWidget#workspaceTabs QStackedWidget, QTabWidget#previewTabs QStackedWidget {
    background: transparent;
}
QTabWidget#workspaceTabs::pane {
    top: 6px;
}
QTabWidget#workspaceTabs QTabBar {
    left: 0;
}
QTabWidget#workspaceTabs QTabBar::tab {
    background: rgba(241, 245, 249, 0.95);
    color: #334155;
    border: 1px solid rgba(148, 163, 184, 0.2);
    border-radius: 11px;
    padding: 7px 14px;
    margin-right: 8px;
    min-width: 86px;
    font-size: 12px;
    font-weight: 600;
}
QTabWidget#workspaceTabs QTabBar::tab:selected {
    color: #0f172a;
    background: rgba(255, 255, 255, 0.98);
    border-color: rgba(37, 99, 235, 0.24);
}
QTabWidget#workspaceTabs QTabBar::tab:hover:!selected {
    color: #1d4ed8;
    background: rgba(219, 234, 254, 0.88);
}
QTabWidget#previewTabs::pane {
    top: 6px;
}
QTabWidget#previewTabs QTabBar {
    left: 0;
}
QTabWidget#previewTabs QTabBar::tab {
    background: rgba(241, 245, 249, 0.92);
    color: #475569;
    border: 1px solid rgba(148, 163, 184, 0.2);
    border-radius: 10px;
    padding: 6px 12px;
    margin-right: 6px;
    min-width: 88px;
    font-size: 11px;
    font-weight: 600;
}
QTabWidget#previewTabs QTabBar::tab:selected {
    color: #0f172a;
    background: rgba(255, 255, 255, 0.98);
    border-color: rgba(37, 99, 235, 0.2);
}
QTabWidget#previewTabs QTabBar::tab:hover:!selected {
    color: #1d4ed8;
    background: rgba(219, 234, 254, 0.8);
}
QTreeWidget {
    background: transparent;
    border: none;
    alternate-background-color: rgba(15, 23, 42, 0.025);
}
QTreeWidget::item {
    height: 32px;
}
QComboBox#filterCombo {
    min-width: 130px;
}
QFrame#navRail {
    background: rgba(241, 245, 249, 0.9);
    border: 1px solid rgba(148, 163, 184, 0.22);
    border-radius: 16px;
}
QScrollArea#panelScroll {
    background: transparent;
    border: none;
}
QWidget#stackPage, QWidget#panelHost, QWidget#scrollPage {
    background: transparent;
}
QStackedWidget#queueStack, QStackedWidget#pageStack {
    background: transparent;
    border: none;
}
QStackedWidget#queueStack > QWidget, QStackedWidget#pageStack > QWidget {
    background: transparent;
}
QScrollArea#panelScroll QWidget#qt_scrollarea_viewport {
    background: transparent;
}
QScrollArea#panelScroll > QWidget > QWidget {
    background: transparent;
}
QPushButton#navButton {
    text-align: left;
    border: none;
    border-radius: 10px;
    padding: 9px 10px;
    font-size: 12px;
    font-weight: 600;
    color: #334155;
    background: transparent;
}
QPushButton#navButton:hover {
    background: rgba(37, 99, 235, 0.08);
    color: #1d4ed8;
}
QPushButton#navButton:checked {
    color: white;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0ea5e9, stop:1 #2563eb);
}
QFrame#emptyStateCard {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(236, 254, 255, 0.98), stop:1 rgba(239, 246, 255, 0.98));
    border: 1px solid rgba(14, 165, 233, 0.14);
    border-radius: 18px;
}
QLabel#emptyTitle {
    color: #0f172a;
    font-size: 20px;
    font-weight: 700;
}
QLabel#emptyBody {
    color: #475569;
    font-size: 13px;
}
QLabel#emptyTag {
    color: #0f766e;
    background: rgba(13, 148, 136, 0.12);
    border-radius: 999px;
    padding: 6px 10px;
    font-size: 11px;
    font-weight: 600;
}
QLabel#statusChip {
    color: #0f172a;
    background: rgba(37, 99, 235, 0.1);
    border-radius: 999px;
    padding: 6px 10px;
    font-size: 11px;
    font-weight: 700;
}
QPlainTextEdit#logText {
    background: #0f172a;
    color: #e2e8f0;
    border-radius: 14px;
    border: 1px solid rgba(148, 163, 184, 0.2);
    padding: 8px;
}
QPlainTextEdit#previewText, QTextBrowser#previewText {
    background: rgba(255, 255, 255, 0.9);
    color: #0f172a;
    border-radius: 12px;
    border: 1px solid rgba(148, 163, 184, 0.18);
    padding: 8px;
}
QProgressBar {
    min-height: 12px;
    border-radius: 6px;
    background: rgba(148, 163, 184, 0.18);
    text-align: center;
}
QProgressBar::chunk {
    border-radius: 6px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #06b6d4, stop:1 #2563eb);
}
"""


def build_button_style(variant: str) -> str:
    if variant == "toolbar-accent":
        return (
            "QPushButton { background: #2563eb; color: white; border: none; border-radius: 10px; "
            "padding: 3px 8px; font-size: 10px; font-weight: 600; }"
            "QPushButton:hover { background: #1d4ed8; }"
            "QPushButton:disabled { background: #94a3b8; color: #e2e8f0; }"
        )
    if variant == "toolbar-danger":
        return (
            "QPushButton { background: #b42318; color: white; border: none; border-radius: 10px; "
            "padding: 3px 8px; font-size: 10px; font-weight: 600; }"
            "QPushButton:hover { background: #912018; }"
            "QPushButton:disabled { background: #f1a7a0; color: white; }"
        )
    if variant == "toolbar":
        return (
            "QPushButton { background: rgba(255,255,255,0.92); color: #0f172a; border: 1px solid rgba(15, 23, 42, 0.08); "
            "border-radius: 10px; padding: 3px 8px; font-size: 10px; font-weight: 600; }"
            "QPushButton:hover { background: rgba(241,245,249,1); }"
            "QPushButton:disabled { color: #94a3b8; background: rgba(248,250,252,0.7); }"
        )
    if variant == "accent":
        return (
            "QPushButton { background: #2563eb; color: white; border: none; border-radius: 11px; "
            "padding: 8px 13px; font-size: 12px; font-weight: 600; }"
            "QPushButton:hover { background: #1d4ed8; }"
            "QPushButton:disabled { background: #94a3b8; color: #e2e8f0; }"
        )
    if variant == "danger":
        return (
            "QPushButton { background: #b42318; color: white; border: none; border-radius: 11px; "
            "padding: 8px 13px; font-size: 12px; font-weight: 600; }"
            "QPushButton:hover { background: #912018; }"
            "QPushButton:disabled { background: #f1a7a0; color: white; }"
        )
    if variant == "compact":
        return (
            "QPushButton { background: rgba(255,255,255,0.95); color: #0f172a; border: 1px solid rgba(15, 23, 42, 0.08); "
            "border-radius: 9px; padding: 6px 9px; font-size: 10px; font-weight: 600; }"
            "QPushButton:hover { background: rgba(241,245,249,1); }"
            "QPushButton:disabled { color: #94a3b8; background: rgba(248,250,252,0.7); }"
        )
    return (
        "QPushButton { background: rgba(255,255,255,0.9); color: #0f172a; border: 1px solid rgba(15, 23, 42, 0.08); "
        "border-radius: 11px; padding: 8px 12px; font-size: 12px; font-weight: 500; }"
        "QPushButton:hover { background: rgba(241,245,249,1); }"
        "QPushButton:disabled { color: #94a3b8; background: rgba(248,250,252,0.7); }"
    )


@dataclass
class ConversionJob:
    job_id: str
    input_path: Path
    output_path: Path | None = None
    status: str = STATUS_QUEUED
    stage: str = "Waiting"
    message: str = "Ready"
    progress: int = 0
    output_tokens: int = 0
    token_rate: float = 0.0
    error: str = ""
    started_at: float | None = None
    finished_at: float | None = None
    stream_chunks: dict[int, StreamProgress] = field(default_factory=dict)

    @property
    def file_type(self) -> str:
        return self.input_path.suffix.lower().lstrip(".").upper()


class GuiSignals(QObject):
    log_message = Signal(str)
    job_refresh = Signal(str)
    conversion_progress = Signal(str, object)
    stream_progress = Signal(str, int, int, int, int, object)
    status_changed = Signal(str)
    overall_progress = Signal(int, int)
    batch_finished = Signal(int, int, int)
    models_fetched = Signal(bool, str, object)
    model_test_finished = Signal(bool, str, str, float)


def parse_dropped_paths_from_urls(urls: list) -> list[Path]:
    paths: list[Path] = []
    for url in urls:
        if hasattr(url, "isLocalFile") and url.isLocalFile():
            candidate = Path(url.toLocalFile()).expanduser()
            if is_supported_input_path(candidate):
                paths.append(candidate)
    return paths


class DropLabel(QLabel):
    files_dropped = Signal(object)

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setObjectName("dropLabel")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        files = parse_dropped_paths_from_urls(event.mimeData().urls())
        if files:
            self.files_dropped.emit(files)
            event.acceptProposedAction()
        else:
            event.ignore()


class DropTreeWidget(QTreeWidget):
    files_dropped = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        files = parse_dropped_paths_from_urls(event.mimeData().urls())
        if files:
            self.files_dropped.emit(files)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


def get_application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_windows_user_config_directory() -> Path:
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        return Path(appdata).expanduser() / APP_CONFIG_DIR_NAME
    return Path.home() / "AppData" / "Roaming" / APP_CONFIG_DIR_NAME


def get_macos_user_config_directory() -> Path:
    return Path.home() / "Library" / "Application Support" / APP_CONFIG_DIR_NAME


def get_platform_user_config_directory() -> Path | None:
    if sys.platform == "win32":
        return get_windows_user_config_directory()
    if sys.platform == "darwin":
        return get_macos_user_config_directory()
    return None


def get_config_path() -> Path:
    user_config_directory = get_platform_user_config_directory()
    if user_config_directory is not None:
        return user_config_directory / CONFIG_FILE_NAME
    return get_application_directory() / CONFIG_FILE_NAME


def migrate_legacy_application_config(config_path: Path) -> str | None:
    if sys.platform not in {"win32", "darwin"}:
        return None

    legacy_path = get_application_directory() / CONFIG_FILE_NAME
    if legacy_path == config_path or not legacy_path.is_file() or config_path.exists():
        return None

    config_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(legacy_path, config_path)
    except OSError as exc:
        return f"Could not migrate legacy config from {legacy_path}: {exc}"
    return f"Migrated legacy config from {legacy_path} to {config_path}."


def load_config_file(config_path: Path) -> tuple[dict, str | None]:
    migration_message = migrate_legacy_application_config(config_path)
    if not config_path.is_file():
        return dict(CONFIG_DEFAULTS), migration_message

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return dict(CONFIG_DEFAULTS), f"Could not read {config_path.name}: {exc}"

    if not isinstance(payload, dict):
        return dict(CONFIG_DEFAULTS), f"Ignored {config_path.name}: expected a JSON object."

    config_data = {**CONFIG_DEFAULTS, **payload, "config_version": CONFIG_VERSION}
    return config_data, migration_message


def write_config_file(config_path: Path, config_data: dict) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_supported_input_path(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_INPUT_SUFFIXES


def open_path(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def get_runtime_base_directory() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_icon_file_path(icon_name: str) -> Path:
    return get_runtime_base_directory() / ICON_DIRECTORY / f"{icon_name}.svg"


class MarkdownConverterApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PDF2MD Workbench")
        self.resize(1320, 840)
        self.setMinimumSize(1120, 720)

        self.config_path = get_config_path()
        self.config_data, self.config_load_error = load_config_file(self.config_path)
        self.jobs: dict[str, ConversionJob] = {}
        self.job_items: dict[str, QTreeWidgetItem] = {}
        self.next_job_number = 1
        self.is_processing = False
        self.cancel_event = threading.Event()
        self.signals = GuiSignals()
        self._progress_value = 0
        self._progress_animation = QPropertyAnimation(self, b"animatedProgress", self)
        self._progress_animation.setDuration(220)
        self._progress_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.available_models = self.build_initial_model_choices()

        self._build_ui()
        self._configure_signals()
        self.report_config_status()
        self.refresh_summary()

    def get_config_string(self, key: str, default: str) -> str:
        value = self.config_data[key] if key in self.config_data else default
        if value is None:
            return default
        return str(value)

    def get_config_bool(self, key: str, default: bool) -> bool:
        value = self.config_data[key] if key in self.config_data else default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        return bool(value) if value is not None else default

    def get_config_list(self, key: str) -> list[str]:
        value = self.config_data.get(key, [])
        if not isinstance(value, list):
            return []
        items: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                items.append(item.strip())
        return items

    def build_initial_model_choices(self) -> list[str]:
        model_choices = self.get_config_list("known_models")
        current_model = self.get_config_string("model", DEFAULT_MODEL).strip()
        for candidate in (current_model, DEFAULT_MODEL):
            if candidate and candidate not in model_choices:
                model_choices.append(candidate)
        return sorted(set(model_choices), key=str.casefold)

    def update_model_choices(self, models: list[str], preferred_model: str | None = None) -> None:
        normalized = [model.strip() for model in models if isinstance(model, str) and model.strip()]
        if preferred_model and preferred_model.strip():
            normalized.append(preferred_model.strip())
        normalized.append(DEFAULT_MODEL)
        self.available_models = sorted(set(normalized), key=str.casefold)
        target_model = preferred_model.strip() if preferred_model and preferred_model.strip() else self.model_combo.currentText().strip()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(self.available_models)
        if target_model and target_model in self.available_models:
            self.model_combo.setCurrentText(target_model)
        elif self.available_models:
            self.model_combo.setCurrentText(self.available_models[0])
        self.model_combo.blockSignals(False)

        if self.available_models:
            self.model_status_label.setText(f"Models: {len(self.available_models)} loaded")
        else:
            self.model_status_label.setText("Models: manual entry or fetch list")
        self.refresh_guidance_panel()

    def _configure_signals(self) -> None:
        self.signals.log_message.connect(self.append_log)
        self.signals.job_refresh.connect(self.on_job_refresh)
        self.signals.conversion_progress.connect(self.update_conversion_progress)
        self.signals.stream_progress.connect(self.update_stream_metrics)
        self.signals.status_changed.connect(self.status_label.setText)
        self.signals.overall_progress.connect(self.update_overall_progress)
        self.signals.batch_finished.connect(self.finish_processing)
        self.signals.models_fetched.connect(self.finish_fetch_models)
        self.signals.model_test_finished.connect(self.finish_model_test)
        self.api_key_edit.textChanged.connect(self.refresh_guidance_panel)
        self.api_url_edit.textChanged.connect(self.refresh_guidance_panel)
        self.output_dir_edit[1].textChanged.connect(self.refresh_guidance_panel)
        self.model_combo.currentTextChanged.connect(self.refresh_guidance_panel)
        self.pages_per_request_edit.textChanged.connect(self.refresh_guidance_panel)
        self.max_concurrency_edit.textChanged.connect(self.refresh_guidance_panel)
        self.render_dpi_edit.textChanged.connect(self.refresh_guidance_panel)
        self.overwrite_combo.currentTextChanged.connect(self.refresh_guidance_panel)

    def _build_ui(self) -> None:
        self.setStyleSheet(APP_STYLESHEET)
        central = QWidget(self)
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(12)

        self.header_card = self._build_header()
        self.toolbar_card = self._build_toolbar()
        self.workspace_tabs = self._build_workspace()
        self.footer_card = self._build_footer()

        root_layout.addWidget(self.header_card)
        root_layout.addWidget(self.toolbar_card)
        root_layout.addWidget(self.workspace_tabs, stretch=1)
        root_layout.addWidget(self.footer_card)

    def _build_header(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        eyebrow = QLabel("Structured Extraction Workbench")
        eyebrow.setObjectName("eyebrowLabel")
        text_layout.addWidget(eyebrow)

        title = QLabel("PDF2MD Workbench")
        title.setObjectName("titleLabel")
        text_layout.addWidget(title)

        subtitle = QLabel(
            "Batch convert PDFs and Office documents into formatted Markdown with queue status, retry, cache, and streaming metrics."
        )
        subtitle.setObjectName("subtitleLabel")
        subtitle.setWordWrap(True)
        text_layout.addWidget(subtitle)

        layout.addLayout(text_layout, stretch=1)

        right_layout = QVBoxLayout()
        right_layout.setSpacing(6)
        right_layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.summary_label = QLabel("0 queued | 0 running | 0 done | 0 failed | 0 cancelled")
        self.summary_label.setObjectName("summaryLabel")
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        right_layout.addWidget(self.summary_label)

        self.workspace_hint_label = QLabel("Files tab ready")
        self.workspace_hint_label.setObjectName("subtitleLabel")
        self.workspace_hint_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        right_layout.addWidget(self.workspace_hint_label)

        layout.addLayout(right_layout)
        return card

    def _build_toolbar(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        action_row = QHBoxLayout()
        action_row.setSpacing(4)

        self.add_button = self._create_button("Add Files", self.add_files_from_dialog, variant="toolbar")
        self.remove_button = self._create_button("Remove", self.remove_selected_jobs, variant="toolbar")
        self.clear_button = self._create_button("Clear", self.clear_jobs, variant="toolbar")
        self.retry_button = self._create_button("Retry", self.retry_failed_jobs, variant="toolbar")
        self.open_output_button = self._create_button("Output", self.open_selected_output, variant="toolbar")
        self.open_config_button = self._create_button("Config", self.open_config, variant="toolbar")
        self.test_api_button = self._create_button("Test", self.test_api, variant="toolbar")
        self.preflight_button = self._create_button("Preflight", self.run_preflight_dialog, variant="toolbar")
        self.cancel_button = self._create_button("Cancel", self.cancel_processing, variant="toolbar-danger")
        self.process_button = self._create_button("Process", self.start_processing, variant="toolbar-accent")

        self.apply_app_icon(self.add_button, "add-files", QStyle.StandardPixmap.SP_DialogOpenButton)
        self.apply_app_icon(self.remove_button, "remove-item", QStyle.StandardPixmap.SP_TrashIcon)
        self.apply_app_icon(self.clear_button, "clear-reset", QStyle.StandardPixmap.SP_DialogResetButton)
        self.apply_app_icon(self.retry_button, "retry-cycle", QStyle.StandardPixmap.SP_BrowserReload)
        self.apply_app_icon(self.open_output_button, "open-output", QStyle.StandardPixmap.SP_DirOpenIcon)
        self.apply_app_icon(self.open_config_button, "config-file", QStyle.StandardPixmap.SP_FileIcon)
        self.apply_app_icon(self.test_api_button, "test-beaker", QStyle.StandardPixmap.SP_DialogApplyButton)
        self.apply_app_icon(self.preflight_button, "preflight-shield", QStyle.StandardPixmap.SP_FileDialogDetailedView)
        self.apply_app_icon(self.cancel_button, "cancel-stop", QStyle.StandardPixmap.SP_BrowserStop)
        self.apply_app_icon(self.process_button, "process-play", QStyle.StandardPixmap.SP_MediaPlay)

        self.retry_button.setToolTip("Retry failed jobs")
        self.open_output_button.setToolTip("Open selected output")
        self.open_config_button.setToolTip("Open config file")
        self.test_api_button.setToolTip("Test the selected model")
        self.process_button.setToolTip("Process the current queue")

        for widget in (
            self.add_button,
            self.remove_button,
            self.clear_button,
            self.retry_button,
            self.open_output_button,
            self.open_config_button,
            self.test_api_button,
            self.preflight_button,
            self.cancel_button,
            self.process_button,
        ):
            widget.setIconSize(QSize(12, 12))
            widget.setFixedHeight(32)

        for widget in (
            self.add_button,
            self.remove_button,
            self.clear_button,
            self.retry_button,
            self.open_output_button,
            self.open_config_button,
            self.test_api_button,
            self.preflight_button,
        ):
            action_row.addWidget(widget)

        action_row.addStretch(1)
        self.cancel_button.setEnabled(False)
        action_row.addWidget(self.cancel_button)
        action_row.addWidget(self.process_button)

        layout.addLayout(action_row)
        return card

    def _build_workspace(self) -> QWidget:
        workspace_tabs = QTabWidget()
        workspace_tabs.setObjectName("workspaceTabs")
        workspace_tabs.setDocumentMode(False)
        workspace_tabs.tabBar().setDrawBase(False)
        workspace_tabs.tabBar().setExpanding(False)

        queue_card = QFrame()
        queue_card.setObjectName("queueCard")
        queue_layout = QVBoxLayout(queue_card)
        queue_layout.setContentsMargins(14, 14, 14, 14)
        queue_layout.setSpacing(10)

        queue_title = QLabel("Queue")
        queue_title.setObjectName("sectionTitle")
        queue_layout.addWidget(queue_title)

        self.drop_label = DropLabel("Drop PDF, DOC, DOCX, PPT, or PPTX files here")
        self.drop_label.files_dropped.connect(self.add_files)
        queue_layout.addWidget(self.drop_label)

        queue_meta_row = QHBoxLayout()
        queue_meta_row.setSpacing(8)
        self.queue_metrics_label = QLabel("0 shown / 0 total")
        self.queue_metrics_label.setObjectName("subtitleLabel")
        queue_meta_row.addWidget(self.queue_metrics_label)
        queue_meta_row.addStretch(1)
        filter_label = QLabel("Filter")
        filter_label.setObjectName("metaLabel")
        queue_meta_row.addWidget(filter_label)
        self.queue_filter_combo = QComboBox()
        self.queue_filter_combo.setObjectName("filterCombo")
        self.queue_filter_combo.addItems(["All jobs", "Queued", "Running", "Done", "Failed", "Cancelled"])
        self.queue_filter_combo.currentIndexChanged.connect(self.apply_queue_filter)
        queue_meta_row.addWidget(self.queue_filter_combo)
        queue_layout.addLayout(queue_meta_row)

        self.queue_stack = QStackedWidget()
        self.queue_stack.setObjectName("queueStack")
        self.queue_empty_page = self._build_empty_state_page()

        self.queue_tree = DropTreeWidget()
        self.queue_tree.files_dropped.connect(self.add_files)
        self.queue_tree.itemSelectionChanged.connect(self.update_details_panel)
        self.queue_tree.setColumnCount(7)
        self.queue_tree.setHeaderLabels(["File", "Type", "Status", "Progress", "Stage", "Tokens", "Output"])
        self.queue_tree.setRootIsDecorated(False)
        self.queue_tree.setAlternatingRowColors(True)
        self.queue_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.queue_tree.setUniformRowHeights(True)
        self.queue_tree.setSortingEnabled(False)
        header = self.queue_tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)

        queue_list_page = QWidget()
        queue_list_page.setObjectName("stackPage")
        queue_list_layout = QVBoxLayout(queue_list_page)
        queue_list_layout.setContentsMargins(0, 0, 0, 0)
        queue_list_layout.addWidget(self.queue_tree)

        self.queue_stack.addWidget(self.queue_empty_page)
        self.queue_stack.addWidget(queue_list_page)
        queue_surface = QFrame()
        queue_surface.setObjectName("surfaceHost")
        queue_surface_layout = QVBoxLayout(queue_surface)
        queue_surface_layout.setContentsMargins(12, 12, 12, 12)
        queue_surface_layout.setSpacing(0)
        queue_surface_layout.addWidget(self.queue_stack)
        queue_layout.addWidget(queue_surface, stretch=1)

        details_host = QFrame()
        details_host.setObjectName("sideCard")
        details_layout = QVBoxLayout(details_host)
        details_layout.setContentsMargins(14, 14, 14, 14)
        details_layout.setSpacing(10)
        self.details_card = self._build_details_card()
        details_layout.addWidget(self.details_card, stretch=1)

        files_splitter = QSplitter(Qt.Orientation.Horizontal)
        files_splitter.setChildrenCollapsible(False)
        files_splitter.addWidget(queue_card)
        files_splitter.addWidget(details_host)
        files_splitter.setStretchFactor(0, 3)
        files_splitter.setStretchFactor(1, 2)
        files_splitter.setSizes([760, 420])

        side_card = QFrame()
        side_card.setObjectName("sideCard")
        side_layout = QVBoxLayout(side_card)
        side_layout.setContentsMargins(14, 14, 14, 14)
        side_layout.setSpacing(10)

        side_title = QLabel("Settings")
        side_title.setObjectName("sectionTitle")
        side_layout.addWidget(side_title)

        side_body = QHBoxLayout()
        side_body.setSpacing(12)
        side_layout.addLayout(side_body, stretch=1)

        nav_rail = QFrame()
        nav_rail.setObjectName("navRail")
        nav_layout = QVBoxLayout(nav_rail)
        nav_layout.setContentsMargins(10, 10, 10, 10)
        nav_layout.setSpacing(8)
        nav_rail.setMinimumWidth(128)
        nav_rail.setMaximumWidth(144)
        nav_label = QLabel("Sections")
        nav_label.setObjectName("subtitleLabel")
        nav_layout.addWidget(nav_label)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        side_body.addWidget(nav_rail, stretch=0)

        panel_host = QWidget()
        panel_host.setObjectName("panelHost")
        panel_host_layout = QVBoxLayout(panel_host)
        panel_host_layout.setContentsMargins(0, 0, 0, 0)
        panel_host_layout.setSpacing(8)
        self.panel_title_label = QLabel("Connection")
        self.panel_title_label.setObjectName("panelTitle")
        self.panel_caption_label = QLabel("API endpoint, model selection, output location, and save defaults.")
        self.panel_caption_label.setObjectName("panelCaption")
        panel_host_layout.addWidget(self.panel_title_label)
        panel_host_layout.addWidget(self.panel_caption_label)

        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("pageStack")
        panel_host_layout.addWidget(self.page_stack, stretch=1)
        panel_surface = QFrame()
        panel_surface.setObjectName("surfaceHost")
        panel_surface_layout = QVBoxLayout(panel_surface)
        panel_surface_layout.setContentsMargins(12, 12, 12, 12)
        panel_surface_layout.setSpacing(0)
        panel_surface_layout.addWidget(panel_host)
        side_body.addWidget(panel_surface, stretch=1)

        self.settings_tab = self._create_scroll_page()
        self.advanced_tab = self._create_scroll_page()
        self.log_tab = self._create_scroll_page()
        self.page_stack.addWidget(self.settings_tab)
        self.page_stack.addWidget(self.advanced_tab)
        self.page_stack.addWidget(self.log_tab)
        self._build_settings_tab()
        self._build_advanced_tab()
        self._build_log_tab()

        nav_items = [
            ("Connection", "API endpoint, model selection, output location, and save defaults.", QStyle.StandardPixmap.SP_ComputerIcon),
            ("Processing", "Concurrency, rendering, cache behavior, and output overwrite strategy.", QStyle.StandardPixmap.SP_FileDialogDetailedView),
            ("Activity", "Observe run logs, streaming notes, and operational trace output.", QStyle.StandardPixmap.SP_FileDialogInfoView),
        ]
        for index, (label, caption, icon_type) in enumerate(nav_items):
            nav_button = self._create_nav_button(label, icon_type)
            icon_name = ("connection-plug", "processing-sliders", "activity-pulse")[index]
            self.apply_app_icon(nav_button, icon_name, icon_type)
            nav_button.clicked.connect(
                lambda checked=False, page_index=index, title=label, description=caption: self.switch_panel(page_index, title, description)
            )
            self.nav_group.addButton(nav_button, index)
            nav_layout.addWidget(nav_button)
            if index == 0:
                nav_button.setChecked(True)
        nav_layout.addStretch(1)

        self.switch_panel(0, nav_items[0][0], nav_items[0][1], animate=False)
        self.update_queue_empty_state(animate=False)

        workspace_tabs.addTab(files_splitter, self.get_app_icon("file-pdf", QStyle.StandardPixmap.SP_FileIcon), "Files")
        workspace_tabs.addTab(side_card, self.get_app_icon("config-file", QStyle.StandardPixmap.SP_FileIcon), "Settings")
        return workspace_tabs

    def _build_empty_state_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("stackPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 12, 24, 12)
        layout.addStretch(1)

        card = QFrame()
        card.setObjectName("emptyStateCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 28, 28, 28)
        card_layout.setSpacing(12)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setPixmap(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton).pixmap(QSize(54, 54)))
        card_layout.addWidget(icon_label)

        empty_title = QLabel("Start with a clean conversion queue")
        empty_title.setObjectName("emptyTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(empty_title)

        empty_body = QLabel(
            "Drop a batch into the workspace or add files manually. The queue will track progress, token output, retry state, and generated Markdown destinations."
        )
        empty_body.setObjectName("emptyBody")
        empty_body.setWordWrap(True)
        empty_body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(empty_body)

        tag_row = QHBoxLayout()
        tag_row.setSpacing(8)
        tag_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for text in ("Drag and drop", "Model testing", "Retry failed", "Live logs"):
            tag = QLabel(text)
            tag.setObjectName("emptyTag")
            tag_row.addWidget(tag)
        card_layout.addLayout(tag_row)

        empty_button = self._create_button("Add First Files", self.add_files_from_dialog, variant="accent")
        self.apply_app_icon(empty_button, "add-files", QStyle.StandardPixmap.SP_DialogOpenButton)
        card_layout.addWidget(empty_button, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _build_details_card(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("panelScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        card, body = self._create_content_card(
            "Selection Details",
            "Use this area to inspect the focused file, understand failures, and jump to generated output.",
        )
        card.setMinimumHeight(0)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        self.detail_file_value = self._create_meta_value_label(word_wrap=True)
        self.detail_status_chip = QLabel("No selection")
        self.detail_status_chip.setObjectName("statusChip")
        self.detail_stage_value = self._create_meta_value_label()
        self.detail_tokens_value = self._create_meta_value_label()
        self.detail_output_value = self._create_meta_value_label(word_wrap=True)
        self.detail_message_value = self._create_meta_value_label(word_wrap=True)

        detail_rows = [
            ("File", self.detail_file_value),
            ("Status", self.detail_status_chip),
            ("Stage", self.detail_stage_value),
            ("Tokens", self.detail_tokens_value),
            ("Output", self.detail_output_value),
            ("Message", self.detail_message_value),
        ]
        for row, (label_text, value_widget) in enumerate(detail_rows):
            label = QLabel(label_text)
            label.setObjectName("metaLabel")
            grid.addWidget(label, row, 0)
            grid.addWidget(value_widget, row, 1)

        body.addLayout(grid)

        actions = QGridLayout()
        actions.setHorizontalSpacing(8)
        actions.setVerticalSpacing(8)
        self.open_source_button = self._create_button("Open Source", self.open_selected_source, variant="compact")
        self.open_result_button = self._create_button("Open Result", self.open_selected_output_file, variant="compact")
        self.retry_selected_button = self._create_button("Retry Failed", self.retry_selected_jobs, variant="compact")
        self.apply_app_icon(self.open_source_button, "source-link", QStyle.StandardPixmap.SP_FileLinkIcon)
        self.apply_app_icon(self.open_result_button, "open-output", QStyle.StandardPixmap.SP_DirOpenIcon)
        self.apply_app_icon(self.retry_selected_button, "retry-cycle", QStyle.StandardPixmap.SP_BrowserReload)
        actions.addWidget(self.open_source_button, 0, 0)
        actions.addWidget(self.open_result_button, 0, 1)
        actions.addWidget(self.retry_selected_button, 1, 0, 1, 2)
        body.addLayout(actions)

        preview_label = QLabel("Output preview")
        preview_label.setObjectName("metaLabel")
        body.addWidget(preview_label)
        self.preview_tabs = QTabWidget()
        self.preview_tabs.setObjectName("previewTabs")
        self.preview_tabs.setDocumentMode(False)
        self.preview_tabs.tabBar().setDrawBase(False)
        self.preview_tabs.tabBar().setExpanding(False)
        self.raw_preview = QPlainTextEdit()
        self.raw_preview.setObjectName("previewText")
        self.raw_preview.setReadOnly(True)
        self.raw_preview.setMaximumHeight(120)
        self.rendered_preview = QTextBrowser()
        self.rendered_preview.setObjectName("previewText")
        self.rendered_preview.setOpenExternalLinks(True)
        self.rendered_preview.setMaximumHeight(120)
        self.preview_tabs.addTab(self.raw_preview, "Markdown")
        self.preview_tabs.addTab(self.rendered_preview, "Rendered")
        self.preview_tabs.setTabIcon(0, self.get_app_icon("preview-markdown", QStyle.StandardPixmap.SP_FileIcon))
        self.preview_tabs.setTabIcon(1, self.get_app_icon("preview-rendered", QStyle.StandardPixmap.SP_FileDialogContentsView))
        body.addWidget(self.preview_tabs)
        body.addStretch(1)
        scroll.setWidget(card)
        return scroll

    def _build_settings_tab(self) -> None:
        layout = QVBoxLayout(self.settings_tab.widget())
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(14)

        guidance_card, guidance_body = self._create_content_card(
            "Quick Start",
            "This checklist keeps first-run setup obvious instead of burying critical steps in blank form fields.",
        )
        self.setup_checklist_label = QLabel()
        self.setup_checklist_label.setObjectName("noteBody")
        self.setup_checklist_label.setWordWrap(True)
        guidance_body.addWidget(self.setup_checklist_label)
        layout.addWidget(guidance_card)

        form_card, form_body = self._create_content_card(
            "Connection Settings",
            "Configure the endpoint, confirm the model, and define where generated Markdown should land.",
        )

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.api_key_edit = QLineEdit(self.get_config_string("api_key", os.environ.get("ARK_API_KEY", "")))
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("Paste API key or use ARK_API_KEY")
        form.addRow("API key", self.api_key_edit)

        self.api_url_edit = QLineEdit(self.get_config_string("api_url", DEFAULT_API_URL))
        self.api_url_edit.setPlaceholderText("https://.../responses")
        form.addRow("API URL", self.api_url_edit)

        model_row = QWidget()
        model_layout = QHBoxLayout(model_row)
        model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.setSpacing(8)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        model_layout.addWidget(self.model_combo, stretch=1)
        self.fetch_models_button = self._create_button("Fetch Models", self.fetch_models)
        self.test_model_button = self._create_button("Test Model", self.test_selected_model)
        self.apply_app_icon(self.fetch_models_button, "retry-cycle", QStyle.StandardPixmap.SP_BrowserReload)
        self.apply_app_icon(self.test_model_button, "test-beaker", QStyle.StandardPixmap.SP_DialogApplyButton)
        model_layout.addWidget(self.fetch_models_button)
        model_layout.addWidget(self.test_model_button)
        form.addRow("Model", model_row)

        self.model_status_label = QLabel("Models: manual entry or fetch list")
        self.model_status_label.setObjectName("subtitleLabel")
        form.addRow("", self.model_status_label)

        self.output_dir_edit = self._create_browse_row(self.get_config_string("output_dir", ""), self.select_output_dir)
        self.output_dir_edit[1].setPlaceholderText("Leave empty to write next to the source file")
        form.addRow("Output folder", self.output_dir_edit[0])

        self.style_reference_edit = self._create_browse_row(self.get_config_string("style_reference", ""), self.select_style_reference)
        self.style_reference_edit[1].setPlaceholderText("Optional Markdown style reference")
        form.addRow("Style reference", self.style_reference_edit[0])

        self.overwrite_combo = QComboBox()
        self.overwrite_combo.addItems(["rename", "overwrite", "fail"])
        self.overwrite_combo.setCurrentText(self.get_config_string("overwrite_mode", "rename"))
        form.addRow("Existing output", self.overwrite_combo)

        form_body.addLayout(form)

        self.stream_check = QCheckBox("Use streaming responses")
        self.stream_check.setChecked(self.get_config_bool("stream", True))
        form_body.addWidget(self.stream_check)

        self.save_settings_button = self._create_button("Save Settings", lambda: self.save_config_from_current_fields())
        self.apply_app_icon(self.save_settings_button, "config-file", QStyle.StandardPixmap.SP_DialogSaveButton)
        form_body.addWidget(self.save_settings_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(form_card)
        layout.addStretch(1)

        self.update_model_choices(self.available_models, self.get_config_string("model", DEFAULT_MODEL))

    def _build_advanced_tab(self) -> None:
        layout = QVBoxLayout(self.advanced_tab.widget())
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(14)

        settings_card, settings_body = self._create_content_card(
            "Processing Controls",
            "Tune throughput, rendering quality, cache behavior, and output collision policy for the current batch.",
        )

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.pages_per_request_edit = QLineEdit(self.get_config_string("pages_per_request", "4"))
        self.pages_per_request_edit.setPlaceholderText("4")
        form.addRow("Pages/request", self.pages_per_request_edit)
        self.max_concurrency_edit = QLineEdit(self.get_config_string("max_concurrency", "4"))
        self.max_concurrency_edit.setPlaceholderText("4")
        form.addRow("Workers", self.max_concurrency_edit)
        self.render_dpi_edit = QLineEdit(self.get_config_string("render_dpi", "160"))
        self.render_dpi_edit.setPlaceholderText("160")
        form.addRow("Render DPI", self.render_dpi_edit)
        self.page_text_limit_edit = QLineEdit(self.get_config_string("page_text_limit", "0"))
        self.page_text_limit_edit.setPlaceholderText("0")
        form.addRow("Text limit", self.page_text_limit_edit)
        self.timeout_edit = QLineEdit(self.get_config_string("timeout", "300"))
        self.timeout_edit.setPlaceholderText("300")
        form.addRow("Timeout (s)", self.timeout_edit)

        self.chunk_cache_edit = self._create_browse_row(self.get_config_string("chunk_cache_dir", ""), self.select_chunk_cache_dir)
        self.chunk_cache_edit[1].setPlaceholderText("Optional cache directory for chunk reuse")
        form.addRow("Chunk cache", self.chunk_cache_edit[0])

        settings_body.addLayout(form)
        self.auto_crop_check = QCheckBox("Auto-crop rendered page images")
        self.auto_crop_check.setChecked(self.get_config_bool("auto_crop_images", True))
        settings_body.addWidget(self.auto_crop_check)
        layout.addWidget(settings_card)

        note_card, note_body = self._create_content_card(
            "Compatibility Notes",
            "Use this page to verify the heavy-lifting assumptions before you launch a long batch.",
        )
        self.processing_note_label = QLabel()
        self.processing_note_label.setObjectName("noteBody")
        self.processing_note_label.setWordWrap(True)
        note_body.addWidget(self.processing_note_label)
        layout.addWidget(note_card)
        layout.addStretch(1)

    def _build_log_tab(self) -> None:
        layout = QVBoxLayout(self.log_tab.widget())
        layout.setContentsMargins(10, 10, 10, 10)
        status_card, status_body = self._create_content_card(
            "Run Summary",
            "Surface the current batch health here so the activity area is useful even before the log fills up.",
        )
        self.activity_summary_label = QLabel()
        self.activity_summary_label.setObjectName("noteBody")
        self.activity_summary_label.setWordWrap(True)
        status_body.addWidget(self.activity_summary_label)
        layout.addWidget(status_card)

        log_card, log_body = self._create_content_card(
            "Live Log",
            "Detailed trace output for API calls, retry decisions, streaming chunks, and save events.",
        )
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setObjectName("logText")
        log_body.addWidget(self.log_text)
        layout.addWidget(log_card)

    def _build_footer(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("statusLabel")
        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 100)
        self.overall_progress.setValue(0)
        self.stream_metrics_label = QLabel("Streaming metrics: idle")
        self.stream_metrics_label.setObjectName("streamLabel")
        layout.addWidget(self.status_label)
        layout.addWidget(self.overall_progress, stretch=1)
        layout.addWidget(self.stream_metrics_label)
        return card

    def _create_button(self, text: str, handler, variant: str = "default") -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(handler)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(build_button_style(variant))
        return button

    def _create_scroll_page(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("panelScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        container.setObjectName("scrollPage")
        scroll.setWidget(container)
        return scroll

    def _create_nav_button(self, text: str, icon_type: QStyle.StandardPixmap) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("navButton")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def get_app_icon(self, icon_name: str, fallback: QStyle.StandardPixmap | None = None) -> QIcon:
        icon_path = get_icon_file_path(icon_name)
        if icon_path.is_file():
            icon = QIcon(str(icon_path))
            if not icon.isNull():
                return icon
        if fallback is not None:
            return self.style().standardIcon(fallback)
        return QIcon()

    def apply_app_icon(self, button: QPushButton, icon_name: str, fallback: QStyle.StandardPixmap | None = None) -> None:
        button.setIcon(self.get_app_icon(icon_name, fallback))
        button.setIconSize(QSize(16, 16))

    def _create_content_card(self, title: str, caption: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("subCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        caption_label = QLabel(caption)
        caption_label.setObjectName("cardCaption")
        caption_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(caption_label)
        return card, layout

    def _get_status_chip_style(self, status: str) -> str:
        palette = {
            STATUS_QUEUED: ("#0f172a", "rgba(100, 116, 139, 0.16)"),
            STATUS_RUNNING: ("#1d4ed8", "rgba(37, 99, 235, 0.14)"),
            STATUS_DONE: ("#15803d", "rgba(21, 128, 61, 0.14)"),
            STATUS_FAILED: ("#b42318", "rgba(180, 35, 24, 0.14)"),
            STATUS_CANCELLED: ("#b54708", "rgba(181, 71, 8, 0.14)"),
        }
        foreground, background = palette.get(status, ("#0f172a", "rgba(37, 99, 235, 0.1)"))
        return (
            f"color: {foreground}; background: {background}; border-radius: 999px; "
            "padding: 6px 10px; font-size: 11px; font-weight: 700;"
        )

    def get_file_icon(self, suffix: str):
        suffix = suffix.lower()
        if suffix == ".pdf":
            return self.get_app_icon("file-pdf", QStyle.StandardPixmap.SP_FileIcon)
        if suffix in {".doc", ".docx"}:
            return self.get_app_icon("file-doc", QStyle.StandardPixmap.SP_FileLinkIcon)
        if suffix in {".ppt", ".pptx"}:
            return self.get_app_icon("file-ppt", QStyle.StandardPixmap.SP_ComputerIcon)
        return self.get_app_icon("config-file", QStyle.StandardPixmap.SP_FileIcon)

    def get_animatedProgress(self) -> int:
        return self._progress_value

    def set_animatedProgress(self, value: int) -> None:
        self._progress_value = value
        if hasattr(self, "overall_progress"):
            self.overall_progress.setValue(value)

    animatedProgress = Property(int, get_animatedProgress, set_animatedProgress)

    def _create_meta_value_label(self, word_wrap: bool = False) -> QLabel:
        label = QLabel("-")
        label.setObjectName("metaValue")
        label.setWordWrap(word_wrap)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def apply_standard_icon(self, button: QPushButton, icon_type: QStyle.StandardPixmap) -> None:
        button.setIcon(self.style().standardIcon(icon_type))
        button.setIconSize(QSize(16, 16))

    def _create_browse_row(self, text: str, browse_command):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        edit = QLineEdit(text)
        browse = self._create_button("Browse", browse_command)
        self.apply_app_icon(browse, "open-output", QStyle.StandardPixmap.SP_DirOpenIcon)
        layout.addWidget(edit, stretch=1)
        layout.addWidget(browse)
        return container, edit, browse

    def switch_panel(self, index: int, title: str, caption: str, animate: bool = True) -> None:
        self.page_stack.setCurrentIndex(index)
        self.panel_title_label.setText(title)
        self.panel_caption_label.setText(caption)
        self.workspace_hint_label.setText(f"Focused on {title.lower()}")

    def update_queue_empty_state(self, animate: bool = True) -> None:
        target_index = 0 if not self.jobs else 1
        if self.queue_stack.currentIndex() != target_index:
            self.queue_stack.setCurrentIndex(target_index)

    def apply_queue_filter(self, *_args) -> None:
        filter_text = self.queue_filter_combo.currentText() if hasattr(self, "queue_filter_combo") else "All jobs"
        visible_count = 0
        for job_id, item in self.job_items.items():
            job = self.jobs.get(job_id)
            if job is None:
                continue
            matches = filter_text == "All jobs" or job.status == filter_text
            item.setHidden(not matches)
            if matches:
                visible_count += 1
        if hasattr(self, "queue_metrics_label"):
            self.queue_metrics_label.setText(f"{visible_count} shown / {len(self.jobs)} total")

    def get_primary_job_for_details(self) -> ConversionJob | None:
        selected_ids = self.selected_job_ids()
        if selected_ids:
            selected_job = self.jobs.get(selected_ids[0])
            if selected_job is not None:
                return selected_job
        for status in (STATUS_RUNNING, STATUS_FAILED, STATUS_QUEUED, STATUS_DONE, STATUS_CANCELLED):
            for job in self.jobs.values():
                if job.status == status:
                    return job
        return None

    def update_details_panel(self) -> None:
        if not hasattr(self, "detail_file_value"):
            return
        job = self.get_primary_job_for_details()
        if job is None:
            self.detail_file_value.setText("No file selected")
            self.detail_status_chip.setText("Idle")
            self.detail_status_chip.setStyleSheet(self._get_status_chip_style("Idle"))
            self.detail_stage_value.setText("Waiting for input")
            self.detail_tokens_value.setText("0")
            self.detail_output_value.setText("Run a conversion or select a queued file to inspect output details.")
            self.detail_message_value.setText("The details area will explain the selected job, including failures and generated markdown.")
            self.raw_preview.setPlainText("Preview unavailable until an output file exists.")
            self.rendered_preview.setMarkdown("Preview unavailable until an output file exists.")
            self.open_source_button.setEnabled(False)
            self.open_result_button.setEnabled(False)
            self.retry_selected_button.setEnabled(False)
            return

        self.detail_file_value.setText(job.input_path.name)
        self.detail_status_chip.setText(job.status)
        self.detail_status_chip.setStyleSheet(self._get_status_chip_style(job.status))
        self.detail_stage_value.setText(job.stage or job.message or "-")
        self.detail_tokens_value.setText(str(job.output_tokens) if job.output_tokens else "0")
        self.detail_output_value.setText(str(job.output_path) if job.output_path else "Not assigned")
        self.detail_message_value.setText(job.error or job.message or "No additional detail")

        preview_text = "Preview unavailable until an output file exists."
        if job.output_path and job.output_path.is_file():
            try:
                preview_text = job.output_path.read_text(encoding="utf-8")[:1200].strip() or "Output file is empty."
            except OSError as exc:
                preview_text = f"Could not read output preview: {exc}"
        self.raw_preview.setPlainText(preview_text)
        self.rendered_preview.setMarkdown(preview_text)

        self.open_source_button.setEnabled(job.input_path.exists())
        self.open_result_button.setEnabled(bool(job.output_path))
        self.retry_selected_button.setEnabled(job.status in {STATUS_FAILED, STATUS_CANCELLED})

    def refresh_guidance_panel(self) -> None:
        if not hasattr(self, "setup_checklist_label"):
            return
        api_ready = bool(self.api_key_edit.text().strip() or os.environ.get("ARK_API_KEY", "").strip())
        model_ready = bool(self.model_combo.currentText().strip())
        queue_ready = bool(self.jobs)
        output_ready = bool(self.output_dir_edit[1].text().strip())
        checklist_lines = [
            f"[{'done' if api_ready else 'todo'}] Add an API key.",
            f"[{'done' if model_ready else 'todo'}] Confirm the model you want to test.",
            f"[{'done' if queue_ready else 'todo'}] Add at least one PDF or Office file.",
            f"[{'done' if output_ready else 'optional'}] Choose a dedicated output folder, or leave it empty to save beside the source.",
            "[next] Run Preflight before starting a large batch.",
        ]
        self.setup_checklist_label.setText("\n".join(checklist_lines))

        if hasattr(self, "processing_note_label"):
            note_lines = [
                f"Current overwrite mode: {self.overwrite_combo.currentText()}",
                f"Workers: {self.max_concurrency_edit.text().strip() or '4'} | Pages/request: {self.pages_per_request_edit.text().strip() or '4'} | Render DPI: {self.render_dpi_edit.text().strip() or '160'}",
                "Office inputs still depend on Microsoft Office COM or LibreOffice on the host machine.",
            ]
            self.processing_note_label.setText("\n".join(note_lines))

    def refresh_runtime_surfaces(self) -> None:
        running = sum(1 for job in self.jobs.values() if job.status == STATUS_RUNNING)
        failed = sum(1 for job in self.jobs.values() if job.status == STATUS_FAILED)
        queued = sum(1 for job in self.jobs.values() if job.status == STATUS_QUEUED)
        self.workspace_hint_label.setText(f"{running} running | {failed} failed | {queued} queued")
        if hasattr(self, "activity_summary_label"):
            focus_job = self.get_primary_job_for_details()
            focus_text = "No active or selected job."
            if focus_job is not None:
                focus_text = (
                    f"Focus: {focus_job.input_path.name}\n"
                    f"Status: {focus_job.status}\n"
                    f"Stage: {focus_job.stage}\n"
                    f"Message: {focus_job.error or focus_job.message or 'No additional detail'}"
                )
            self.activity_summary_label.setText(
                f"Queue health: {queued} queued, {running} running, {failed} failed.\n{focus_text}"
            )

    def open_selected_source(self) -> None:
        job = self.get_primary_job_for_details()
        if job is not None and job.input_path.exists():
            open_path(job.input_path)

    def open_selected_output_file(self) -> None:
        job = self.get_primary_job_for_details()
        if job is None or job.output_path is None:
            return
        target = job.output_path if job.output_path.exists() else job.output_path.parent
        if target.exists():
            open_path(target)

    def retry_selected_jobs(self) -> None:
        selected_ids = self.selected_job_ids()
        if not selected_ids:
            QMessageBox.information(self, "Retry selected", "Select one or more failed jobs to retry.")
            return
        retry_jobs = [self.jobs[job_id] for job_id in selected_ids if self.jobs[job_id].status in {STATUS_FAILED, STATUS_CANCELLED}]
        if not retry_jobs:
            QMessageBox.information(self, "Retry selected", "The selected jobs are not in a failed or cancelled state.")
            return
        for job in retry_jobs:
            job.status = STATUS_QUEUED
            job.stage = "Waiting"
            job.message = "Ready"
            job.progress = 0
            job.error = ""
            job.output_tokens = 0
            job.token_rate = 0.0
            job.stream_chunks.clear()
            self.update_job_row(job)
        self.start_processing(jobs_to_run=retry_jobs)

    def build_config_from_current_fields(self) -> dict:
        return {
            "config_version": CONFIG_VERSION,
            "api_key": self.api_key_edit.text().strip(),
            "api_url": self.api_url_edit.text().strip(),
            "model": self.model_combo.currentText().strip(),
            "known_models": self.available_models,
            "output_dir": self.output_dir_edit[1].text().strip(),
            "style_reference": self.style_reference_edit[1].text().strip(),
            "pages_per_request": self.pages_per_request_edit.text().strip(),
            "max_concurrency": self.max_concurrency_edit.text().strip(),
            "render_dpi": self.render_dpi_edit.text().strip(),
            "page_text_limit": self.page_text_limit_edit.text().strip(),
            "timeout": self.timeout_edit.text().strip(),
            "chunk_cache_dir": self.chunk_cache_edit[1].text().strip(),
            "overwrite_mode": self.overwrite_combo.currentText().strip() or "rename",
            "stream": self.stream_check.isChecked(),
            "auto_crop_images": self.auto_crop_check.isChecked(),
        }

    def save_config_from_current_fields(self, silent: bool = False) -> bool:
        try:
            write_config_file(self.config_path, {**CONFIG_DEFAULTS, **self.build_config_from_current_fields()})
        except OSError as exc:
            if not silent:
                self.append_log(f"Could not save config to {self.config_path}: {exc}")
                QMessageBox.critical(self, "Config save failed", str(exc))
            return False
        if not silent:
            self.append_log(f"Saved config to {self.config_path}")
        return True

    def report_config_status(self) -> None:
        if self.config_load_error:
            self.append_log(f"Config warning: {self.config_load_error}")
        elif self.config_path.is_file():
            self.append_log(f"Loaded config from {self.config_path}")
        else:
            self.append_log(f"Created config at {self.config_path}")
        self.update_model_choices(self.available_models, self.model_combo.currentText())
        self.save_config_from_current_fields(silent=True)
        self.append_log(f"Ready. Add or drop {SUPPORTED_INPUT_LABEL} files to start.")

    def add_files_from_dialog(self) -> None:
        selected, _ = QFileDialog.getOpenFileNames(
            self,
            "Select supported files",
            "",
            "Supported files (*.pdf *.doc *.docx *.ppt *.pptx);;PDF files (*.pdf);;Word documents (*.doc *.docx);;PowerPoint presentations (*.ppt *.pptx)",
        )
        self.add_files(Path(path) for path in selected)

    def select_output_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select output folder")
        if selected:
            self.output_dir_edit[1].setText(selected)
            self.update_all_output_paths()

    def select_style_reference(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(self, "Select style reference Markdown", "", "Markdown files (*.md);;All files (*.*)")
        if selected:
            self.style_reference_edit[1].setText(selected)

    def select_chunk_cache_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select chunk cache folder")
        if selected:
            self.chunk_cache_edit[1].setText(selected)

    def add_files(self, paths: Iterable[Path]) -> None:
        known_paths = {job.input_path.resolve() for job in self.jobs.values()}
        added_count = 0
        ignored_count = 0
        for path in paths:
            candidate = Path(path).expanduser()
            if not is_supported_input_path(candidate) or candidate.resolve() in known_paths:
                ignored_count += 1
                continue
            job_id = f"job-{self.next_job_number:04d}"
            self.next_job_number += 1
            job = ConversionJob(job_id=job_id, input_path=candidate, output_path=self.resolve_output_path(candidate))
            self.jobs[job_id] = job
            item = QTreeWidgetItem(self.job_values(job))
            item.setData(0, Qt.ItemDataRole.UserRole, job_id)
            self.apply_status_style(item, job.status)
            self.queue_tree.addTopLevelItem(item)
            self.job_items[job_id] = item
            known_paths.add(candidate.resolve())
            added_count += 1
        if added_count:
            self.append_log(f"Added {added_count} supported file(s).")
        if ignored_count:
            self.append_log(f"Ignored {ignored_count} duplicate or invalid item(s).")
        self.refresh_summary()

    def remove_selected_jobs(self) -> None:
        if self.is_processing:
            return
        selected = self.selected_job_ids()
        for job_id in selected:
            self.jobs.pop(job_id, None)
            item = self.job_items.pop(job_id, None)
            if item is not None:
                index = self.queue_tree.indexOfTopLevelItem(item)
                if index >= 0:
                    self.queue_tree.takeTopLevelItem(index)
        if selected:
            self.append_log(f"Removed {len(selected)} job(s).")
        self.refresh_summary()

    def clear_jobs(self) -> None:
        if self.is_processing:
            return
        self.jobs.clear()
        self.job_items.clear()
        self.queue_tree.clear()
        self.overall_progress.setValue(0)
        self.status_label.setText("Ready")
        self.stream_metrics_label.setText("Streaming metrics: idle")
        self.refresh_summary()

    def retry_failed_jobs(self) -> None:
        failed_jobs = [job for job in self.jobs.values() if job.status in {STATUS_FAILED, STATUS_CANCELLED}]
        if not failed_jobs:
            QMessageBox.information(self, "Retry failed", "There are no failed or cancelled jobs to retry.")
            return
        for job in failed_jobs:
            job.status = STATUS_QUEUED
            job.stage = "Waiting"
            job.message = "Ready"
            job.progress = 0
            job.error = ""
            job.output_tokens = 0
            job.token_rate = 0.0
            job.stream_chunks.clear()
            self.update_job_row(job)
        self.start_processing(jobs_to_run=failed_jobs)

    def append_log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.appendPlainText(f"[{timestamp}] {message.rstrip()}")

    def append_log_threadsafe(self, message: str) -> None:
        self.signals.log_message.emit(message)

    def get_integer(self, label: str, raw_value: str, minimum: int) -> int:
        try:
            value = int(raw_value)
        except ValueError as exc:
            raise ValueError(f"{label} must be an integer.") from exc
        if value < minimum:
            raise ValueError(f"{label} must be at least {minimum}.")
        return value

    def collect_api_connection_settings(self) -> dict:
        api_key = self.api_key_edit.text().strip() or os.environ.get("ARK_API_KEY", "").strip()
        if not api_key:
            raise ValueError("API key is required. Enter it in the GUI or set ARK_API_KEY.")
        api_url = self.api_url_edit.text().strip() or DEFAULT_API_URL
        if not api_url.startswith(("http://", "https://")):
            raise ValueError("API URL must start with http:// or https://.")
        timeout = self.get_integer("Timeout", self.timeout_edit.text().strip(), 1)
        return {
            "api_key": api_key,
            "api_url": api_url,
            "timeout": timeout,
        }

    def collect_settings(self) -> dict:
        connection_settings = self.collect_api_connection_settings()
        output_dir_raw = self.output_dir_edit[1].text().strip()
        output_dir = Path(output_dir_raw).expanduser() if output_dir_raw else None
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
        style_reference = self.style_reference_edit[1].text().strip()
        if style_reference and not Path(style_reference).is_file():
            raise ValueError("Style reference file was not found.")
        chunk_cache_raw = self.chunk_cache_edit[1].text().strip()
        chunk_cache_dir = Path(chunk_cache_raw).expanduser() if chunk_cache_raw else None
        if chunk_cache_dir is not None:
            chunk_cache_dir.mkdir(parents=True, exist_ok=True)
        overwrite_mode = self.overwrite_combo.currentText().strip() or "rename"
        if overwrite_mode not in {"rename", "overwrite", "fail"}:
            raise ValueError("Existing output must be rename, overwrite, or fail.")
        model = self.model_combo.currentText().strip() or DEFAULT_MODEL
        if not model:
            raise ValueError("Model is required.")
        return {
            **connection_settings,
            "model": model,
            "output_dir": output_dir,
            "style_reference": style_reference,
            "pages_per_request": self.get_integer("Pages/request", self.pages_per_request_edit.text().strip(), 1),
            "max_concurrency": self.get_integer("Workers", self.max_concurrency_edit.text().strip(), 1),
            "render_dpi": self.get_integer("Render DPI", self.render_dpi_edit.text().strip(), 1),
            "page_text_limit": self.get_integer("Text limit", self.page_text_limit_edit.text().strip(), 0),
            "chunk_cache_dir": str(chunk_cache_dir) if chunk_cache_dir else "",
            "overwrite_mode": overwrite_mode,
            "stream": self.stream_check.isChecked(),
            "auto_crop_images": self.auto_crop_check.isChecked(),
        }

    def run_preflight(self, settings: dict | None = None) -> list[str]:
        messages: list[str] = []
        settings = settings or self.collect_settings()
        messages.append("API settings look complete.")
        if settings["output_dir"] is None:
            messages.append("Output Markdown will be written next to each source file.")
        else:
            messages.append(f"Output folder is ready: {settings['output_dir']}")
        if settings["chunk_cache_dir"]:
            messages.append(f"Chunk cache is ready: {settings['chunk_cache_dir']}")
        office_inputs = [job for job in self.jobs.values() if job.input_path.suffix.lower() != ".pdf"]
        if office_inputs:
            if sys.platform.startswith("win"):
                messages.append("Office inputs require Microsoft Office COM or LibreOffice on this machine.")
            elif find_soffice_executable() is None:
                messages.append(get_office_conversion_help_text())
            else:
                messages.append(f"LibreOffice was found for Office document conversion: {find_soffice_executable()}")
        return messages

    def run_preflight_dialog(self) -> None:
        try:
            messages = self.run_preflight()
        except Exception as exc:
            QMessageBox.critical(self, "Preflight failed", str(exc))
            return
        QMessageBox.information(self, "Preflight", "\n".join(messages))

    def resolve_output_path(self, input_path: Path, output_dir: Path | None = None) -> Path:
        if output_dir is None:
            raw_output_dir = self.output_dir_edit[1].text().strip()
            output_dir = Path(raw_output_dir).expanduser() if raw_output_dir else None
        if output_dir is None:
            return input_path.with_suffix(".md")
        return output_dir / f"{input_path.stem}.md"

    def update_all_output_paths(self) -> None:
        output_dir_raw = self.output_dir_edit[1].text().strip()
        output_dir = Path(output_dir_raw).expanduser() if output_dir_raw else None
        for job in self.jobs.values():
            if job.status in {STATUS_QUEUED, STATUS_FAILED, STATUS_CANCELLED}:
                job.output_path = self.resolve_output_path(job.input_path, output_dir)
                self.update_job_row(job)

    def start_processing(self, jobs_to_run: list[ConversionJob] | None = None) -> None:
        if self.is_processing:
            return
        run_jobs = jobs_to_run or [job for job in self.jobs.values() if job.status in {STATUS_QUEUED, STATUS_FAILED, STATUS_CANCELLED}]
        if not run_jobs:
            QMessageBox.information(self, "No work", "Add at least one supported file or retry failed jobs.")
            return
        try:
            settings = self.collect_settings()
            self.run_preflight(settings)
        except Exception as exc:
            QMessageBox.critical(self, "Invalid settings", str(exc))
            return
        self.save_config_from_current_fields(silent=True)
        output_dir = settings["output_dir"]
        for job in run_jobs:
            job.output_path = self.resolve_output_path(job.input_path, output_dir)
            job.status = STATUS_QUEUED
            job.progress = 0
            job.stage = "Waiting"
            job.message = "Ready"
            job.error = ""
            job.output_tokens = 0
            job.token_rate = 0.0
            job.stream_chunks.clear()
            self.update_job_row(job)
        self.cancel_event.clear()
        self.is_processing = True
        self.set_controls_for_processing(True)
        self.append_log(f"Starting batch for {len(run_jobs)} job(s).")
        worker = threading.Thread(target=self.process_jobs, args=(list(run_jobs), settings), daemon=True)
        worker.start()

    def process_jobs(self, jobs_to_run: list[ConversionJob], settings: dict) -> None:
        completed = 0
        failed = 0
        cancelled = 0
        total_jobs = len(jobs_to_run)
        for index, job in enumerate(jobs_to_run, start=1):
            if self.cancel_event.is_set():
                job.status = STATUS_CANCELLED
                job.stage = "Cancelled"
                job.message = "Batch cancelled"
                self.signals.job_refresh.emit(job.job_id)
                cancelled += 1
                continue
            self.signals.status_changed.emit(f"Processing {index}/{total_jobs}: {job.input_path.name}")
            try:
                self.process_single_job(job, settings)
                completed += 1
            except ConversionCancelled as exc:
                cancelled += 1
                self.mark_job_failed(job, STATUS_CANCELLED, str(exc))
            except Exception as exc:
                failed += 1
                self.mark_job_failed(job, STATUS_FAILED, str(exc))
            self.signals.overall_progress.emit(index, total_jobs)
        self.signals.batch_finished.emit(completed, failed, cancelled)

    def process_single_job(self, job: ConversionJob, settings: dict) -> None:
        job.status = STATUS_RUNNING
        job.started_at = time.perf_counter()
        job.finished_at = None
        job.stage = "Starting"
        job.progress = 1
        self.signals.job_refresh.emit(job.job_id)
        self.append_log_threadsafe(f"{job.input_path.name}: starting")
        options = ConversionOptions(
            input_path=job.input_path,
            output_path=job.output_path,
            api_url=settings["api_url"],
            api_key=settings["api_key"],
            model=settings["model"],
            pages_per_request=settings["pages_per_request"],
            max_concurrency=settings["max_concurrency"],
            render_dpi=settings["render_dpi"],
            page_text_limit=settings["page_text_limit"],
            style_reference_path=settings["style_reference"],
            timeout=settings["timeout"],
            stream=settings["stream"],
            auto_crop_images=settings["auto_crop_images"],
            chunk_cache_dir=settings["chunk_cache_dir"],
            overwrite_mode=settings["overwrite_mode"],
        )
        convert_pdf_to_markdown(
            options,
            logger=lambda message: self.append_log_threadsafe(f"{job.input_path.name}: {message}"),
            stream_progress_callback=lambda chunk_index, total_chunks, start_page, end_page, progress: self.signals.stream_progress.emit(
                job.job_id,
                chunk_index,
                total_chunks,
                start_page,
                end_page,
                progress,
            ),
            progress_callback=lambda progress: self.signals.conversion_progress.emit(job.job_id, progress),
            cancel_callback=self.cancel_event.is_set,
        )
        job.status = STATUS_DONE
        job.stage = "Done"
        job.message = "Completed"
        job.progress = 100
        job.finished_at = time.perf_counter()
        self.signals.job_refresh.emit(job.job_id)

    def mark_job_failed(self, job: ConversionJob, status: str, message: str) -> None:
        job.status = status
        job.stage = status
        job.message = message
        job.error = message
        job.finished_at = time.perf_counter()
        self.append_log_threadsafe(f"{job.input_path.name}: {status.lower()} - {message}")
        self.signals.job_refresh.emit(job.job_id)

    def update_conversion_progress(self, job_id: str, progress: ConversionProgress) -> None:
        job = self.jobs.get(job_id)
        if job is None:
            return
        job.stage = progress.stage.title()
        job.message = progress.message
        if progress.stage == "validate":
            job.progress = max(job.progress, 3)
        elif progress.stage == "prepare":
            job.progress = max(job.progress, 8)
        elif progress.stage == "render":
            job.progress = max(job.progress, self.scale_progress(progress.current, progress.total, 10, 35))
        elif progress.stage == "chunk":
            job.progress = max(job.progress, self.scale_progress(progress.current, progress.total, 35, 85))
        elif progress.stage == "merge":
            job.progress = max(job.progress, 90)
        elif progress.stage == "save":
            job.progress = max(job.progress, 95)
        elif progress.stage == "done":
            job.progress = 100
            saved_prefix = "Saved Markdown to "
            if progress.message.startswith(saved_prefix):
                job.output_path = Path(progress.message[len(saved_prefix):])
        self.update_job_row(job)

    def update_stream_metrics(
        self,
        job_id: str,
        chunk_index: int,
        total_chunks: int,
        start_page: int,
        end_page: int,
        progress: StreamProgress,
    ) -> None:
        job = self.jobs.get(job_id)
        if job is None:
            return
        job.stream_chunks[chunk_index] = progress
        job.output_tokens = sum(item.output_tokens for item in job.stream_chunks.values())
        job.token_rate = sum(item.tokens_per_second for item in job.stream_chunks.values())
        completed_chunks = sum(1 for item in job.stream_chunks.values() if item.is_final)
        self.stream_metrics_label.setText(
            f"{job.input_path.name}: {job.output_tokens} tok | {job.token_rate:.1f} tok/s | chunks {completed_chunks}/{total_chunks}"
        )
        if progress.is_final:
            self.append_log(
                f"{job.input_path.name}: chunk {chunk_index}/{total_chunks} pages {start_page}-{end_page} "
                f"streamed {progress.output_tokens} tokens at {progress.tokens_per_second:.1f} tok/s"
            )
        self.update_job_row(job)

    def scale_progress(self, current: int, total: int, start: int, end: int) -> int:
        if total <= 0:
            return start
        return min(end, start + round((end - start) * current / total))

    def update_job_row(self, job: ConversionJob) -> None:
        item = self.job_items.get(job.job_id)
        if item is None:
            return
        for index, value in enumerate(self.job_values(job)):
            item.setText(index, value)
        item.setIcon(0, self.get_file_icon(job.input_path.suffix))
        self.apply_status_style(item, job.status)
        self.refresh_summary()

    def job_values(self, job: ConversionJob) -> list[str]:
        output = str(job.output_path) if job.output_path else ""
        tokens = str(job.output_tokens) if job.output_tokens else ""
        return [job.input_path.name, job.file_type, job.status, f"{job.progress}%", job.stage, tokens, output]

    def apply_status_style(self, item: QTreeWidgetItem, status: str) -> None:
        color_map = {
            STATUS_QUEUED: QColor("#64748b"),
            STATUS_RUNNING: QColor("#1d4ed8"),
            STATUS_DONE: QColor("#15803d"),
            STATUS_FAILED: QColor("#b42318"),
            STATUS_CANCELLED: QColor("#b54708"),
        }
        brush_color = color_map.get(status, QColor("#0f172a"))
        for column in range(self.queue_tree.columnCount()):
            item.setForeground(column, brush_color)

    def selected_job_ids(self) -> list[str]:
        job_ids: list[str] = []
        for item in self.queue_tree.selectedItems():
            job_id = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(job_id, str):
                job_ids.append(job_id)
        return job_ids

    def on_job_refresh(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if job is not None:
            self.update_job_row(job)

    def refresh_summary(self) -> None:
        queued = sum(1 for job in self.jobs.values() if job.status == STATUS_QUEUED)
        running = sum(1 for job in self.jobs.values() if job.status == STATUS_RUNNING)
        done = sum(1 for job in self.jobs.values() if job.status == STATUS_DONE)
        failed = sum(1 for job in self.jobs.values() if job.status == STATUS_FAILED)
        cancelled = sum(1 for job in self.jobs.values() if job.status == STATUS_CANCELLED)
        self.summary_label.setText(f"{queued} queued | {running} running | {done} done | {failed} failed | {cancelled} cancelled")
        if hasattr(self, "queue_stack"):
            self.update_queue_empty_state()
        self.apply_queue_filter()
        self.refresh_guidance_panel()
        self.refresh_runtime_surfaces()
        self.update_details_panel()

    def update_overall_progress(self, completed_jobs: int, total_jobs: int) -> None:
        value = 0 if total_jobs <= 0 else round(completed_jobs * 100 / total_jobs)
        if self._progress_animation.state() == QPropertyAnimation.State.Running:
            self._progress_animation.stop()
        self._progress_animation.setStartValue(self._progress_value)
        self._progress_animation.setEndValue(value)
        self._progress_animation.start()

    def finish_processing(self, completed: int, failed: int, cancelled: int) -> None:
        self.is_processing = False
        self.set_controls_for_processing(False)
        self.refresh_summary()
        if cancelled:
            self.status_label.setText(f"Cancelled after {completed} completed, {failed} failed")
        elif failed:
            self.status_label.setText(f"Completed with {failed} failure(s)")
            QMessageBox.warning(self, "Batch completed with failures", f"{completed} completed, {failed} failed.")
        else:
            self.status_label.setText(f"Completed {completed} file(s)")
            QMessageBox.information(self, "Batch completed", f"Generated Markdown for {completed} file(s).")
        self.append_log(f"Batch finished: {completed} completed, {failed} failed, {cancelled} cancelled.")

    def set_controls_for_processing(self, running: bool) -> None:
        enabled = not running
        for widget in (
            self.add_button,
            self.remove_button,
            self.clear_button,
            self.retry_button,
            self.test_api_button,
            self.preflight_button,
            self.fetch_models_button,
            self.test_model_button,
            self.process_button,
            self.save_settings_button,
        ):
            widget.setEnabled(enabled)
        self.cancel_button.setEnabled(running)

    def cancel_processing(self) -> None:
        if not self.is_processing:
            return
        self.cancel_event.set()
        self.status_label.setText("Cancelling after current API request finishes ...")
        self.append_log("Cancellation requested.")

    def fetch_models(self) -> None:
        try:
            connection_settings = self.collect_api_connection_settings()
        except Exception as exc:
            QMessageBox.critical(self, "Invalid settings", str(exc))
            return
        self.fetch_models_button.setEnabled(False)
        self.status_label.setText("Fetching model list ...")
        self.append_log("Fetching model list from the configured API endpoint ...")
        threading.Thread(target=self.run_fetch_models, args=(connection_settings,), daemon=True).start()

    def run_fetch_models(self, connection_settings: dict) -> None:
        try:
            models = list_available_models(
                api_url=connection_settings["api_url"],
                api_key=connection_settings["api_key"],
                timeout=connection_settings["timeout"],
            )
        except Exception as exc:
            self.signals.models_fetched.emit(False, str(exc), [])
            return
        self.signals.models_fetched.emit(True, f"Loaded {len(models)} models.", models)

    def finish_fetch_models(self, success: bool, message: str, models: list[str]) -> None:
        self.fetch_models_button.setEnabled(True)
        if success:
            self.update_model_choices(models, self.model_combo.currentText())
            self.save_config_from_current_fields(silent=True)
            self.status_label.setText("Model list updated")
            self.append_log(message)
            return

        self.status_label.setText("Model list fetch failed")
        self.model_status_label.setText("Models: fetch failed, keep manual entry")
        self.append_log(f"Model list fetch failed: {message}")
        QMessageBox.critical(self, "Fetch models failed", message)

    def test_selected_model(self) -> None:
        try:
            settings = self.collect_settings()
        except Exception as exc:
            QMessageBox.critical(self, "Invalid settings", str(exc))
            return
        self.test_api_button.setEnabled(False)
        self.test_model_button.setEnabled(False)
        self.status_label.setText(f"Testing model {settings['model']} ...")
        threading.Thread(target=self.run_model_test, args=(settings,), daemon=True).start()

    def test_api(self) -> None:
        self.test_selected_model()

    def run_model_test(self, settings: dict) -> None:
        started_at = time.perf_counter()
        try:
            result = call_responses_api(
                api_url=settings["api_url"],
                api_key=settings["api_key"],
                model=settings["model"],
                content=[{"type": "input_text", "text": "Reply with a short JSON object containing status and one sentence summary."}],
                timeout=settings["timeout"],
                stream=False,
            )
        except Exception as exc:
            self.signals.model_test_finished.emit(False, settings["model"], str(exc), 0.0)
            return
        elapsed_seconds = time.perf_counter() - started_at
        self.signals.model_test_finished.emit(True, settings["model"], result[:400], elapsed_seconds)

    def finish_model_test(self, success: bool, model_name: str, message: str, elapsed_seconds: float) -> None:
        self.test_api_button.setEnabled(not self.is_processing)
        self.test_model_button.setEnabled(not self.is_processing)
        if success:
            self.status_label.setText(f"Model test succeeded: {model_name}")
            self.append_log(f"Model test succeeded for {model_name} in {elapsed_seconds:.2f}s: {message}")
            QMessageBox.information(self, "Model test", f"Model: {model_name}\nLatency: {elapsed_seconds:.2f}s\n\nResponse:\n{message}")
        else:
            self.status_label.setText(f"Model test failed: {model_name}")
            self.append_log(f"Model test failed for {model_name}: {message}")
            QMessageBox.critical(self, "Model test failed", message)

    def open_config(self) -> None:
        self.save_config_from_current_fields(silent=True)
        open_path(self.config_path)

    def open_selected_output(self) -> None:
        selected = self.selected_job_ids()
        if selected:
            job = self.jobs.get(selected[0])
            if job is not None and job.output_path is not None:
                target = job.output_path if job.output_path.exists() else job.output_path.parent
                if target.exists():
                    open_path(target)
                    return
        output_dir_raw = self.output_dir_edit[1].text().strip()
        fallback = Path(output_dir_raw).expanduser() if output_dir_raw else get_application_directory()
        if fallback.exists():
            open_path(fallback)

    def closeEvent(self, event) -> None:
        if self.is_processing:
            result = QMessageBox.question(
                self,
                "Cancel batch",
                "A batch is running. Cancel it after the current request finishes?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if result == QMessageBox.StandardButton.Yes:
                self.cancel_processing()
            event.ignore()
            return
        self.save_config_from_current_fields(silent=True)
        event.accept()

    def run(self) -> None:
        self.show()


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("PDF2MD Workbench")
    apply_stylesheet(app, theme=THEME_NAME, extra={"density_scale": "0"})
    window = MarkdownConverterApp()
    window.run()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()