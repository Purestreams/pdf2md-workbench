from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Iterable

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
)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: tkinterdnd2. Install with: .\\.venv\\Scripts\\python.exe -m pip install tkinterdnd2"
    ) from exc


CONFIG_FILE_NAME = "pdf2md.config"
CONFIG_VERSION = 2
SUPPORTED_INPUT_LABEL = "PDF, DOC, DOCX, PPT, or PPTX"
CONFIG_DEFAULTS = {
    "config_version": CONFIG_VERSION,
    "api_key": "",
    "api_url": DEFAULT_API_URL,
    "model": DEFAULT_MODEL,
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


def get_application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_config_path() -> Path:
    return get_application_directory() / CONFIG_FILE_NAME


def load_config_file(config_path: Path) -> tuple[dict, str | None]:
    if not config_path.is_file():
        return dict(CONFIG_DEFAULTS), None

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return dict(CONFIG_DEFAULTS), f"Could not read {config_path.name}: {exc}"

    if not isinstance(payload, dict):
        return dict(CONFIG_DEFAULTS), f"Ignored {config_path.name}: expected a JSON object."

    config_data = {**CONFIG_DEFAULTS, **payload, "config_version": CONFIG_VERSION}
    return config_data, None


def write_config_file(config_path: Path, config_data: dict) -> None:
    config_path.write_text(json.dumps(config_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_supported_input_path(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_INPUT_SUFFIXES


def parse_drop_files(widget: tk.Misc, data: str) -> list[Path]:
    paths: list[Path] = []
    for item in widget.tk.splitlist(data):
        candidate = Path(item.strip().strip("{}")).expanduser()
        if is_supported_input_path(candidate):
            paths.append(candidate)
    return paths


def open_path(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
        return
    subprocess.Popen(["xdg-open", str(path)])


class MarkdownConverterApp:
    def __init__(self) -> None:
        self.root = TkinterDnD.Tk()
        self.root.title("PDF2MD Workbench")
        self.root.geometry("1240x780")
        self.root.minsize(1040, 680)
        self.root.protocol("WM_DELETE_WINDOW", self.handle_close)

        self.config_path = get_config_path()
        self.config_data, self.config_load_error = load_config_file(self.config_path)
        self.jobs: dict[str, ConversionJob] = {}
        self.next_job_number = 1
        self.is_processing = False
        self.cancel_event = threading.Event()

        self.api_key_var = tk.StringVar(value=self.get_config_string("api_key", os.environ.get("ARK_API_KEY", "")))
        self.api_url_var = tk.StringVar(value=self.get_config_string("api_url", DEFAULT_API_URL))
        self.model_var = tk.StringVar(value=self.get_config_string("model", DEFAULT_MODEL))
        self.output_dir_var = tk.StringVar(value=self.get_config_string("output_dir", ""))
        self.style_reference_var = tk.StringVar(value=self.get_config_string("style_reference", ""))
        self.pages_per_request_var = tk.StringVar(value=self.get_config_string("pages_per_request", "4"))
        self.max_concurrency_var = tk.StringVar(value=self.get_config_string("max_concurrency", "4"))
        self.render_dpi_var = tk.StringVar(value=self.get_config_string("render_dpi", "160"))
        self.page_text_limit_var = tk.StringVar(value=self.get_config_string("page_text_limit", "0"))
        self.timeout_var = tk.StringVar(value=self.get_config_string("timeout", "300"))
        self.chunk_cache_dir_var = tk.StringVar(value=self.get_config_string("chunk_cache_dir", ""))
        self.overwrite_mode_var = tk.StringVar(value=self.get_config_string("overwrite_mode", "rename"))
        self.stream_var = tk.BooleanVar(value=self.get_config_bool("stream", True))
        self.auto_crop_var = tk.BooleanVar(value=self.get_config_bool("auto_crop_images", True))
        self.status_var = tk.StringVar(value="Ready")
        self.summary_var = tk.StringVar(value="0 queued | 0 running | 0 done | 0 failed | 0 cancelled")
        self.stream_metrics_var = tk.StringVar(value="Streaming metrics: idle")

        self._configure_style()
        self._build_ui()
        self._register_drop_targets()
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

    def _configure_style(self) -> None:
        self.colors = {
            "bg": "#f6f7f9",
            "panel": "#ffffff",
            "panel_alt": "#f1f5f9",
            "text": "#1f2933",
            "muted": "#667085",
            "accent": "#2563eb",
            "accent_dark": "#1d4ed8",
            "success": "#15803d",
            "warning": "#b54708",
            "danger": "#b42318",
            "log_bg": "#111827",
            "log_fg": "#f8fafc",
        }
        self.root.configure(background=self.colors["bg"])

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Root.TFrame", background=self.colors["bg"])
        style.configure("Panel.TFrame", background=self.colors["panel"])
        style.configure("Title.TLabel", background=self.colors["bg"], foreground=self.colors["text"], font=("Segoe UI Semibold", 18))
        style.configure("Subtitle.TLabel", background=self.colors["bg"], foreground=self.colors["muted"], font=("Segoe UI", 10))
        style.configure("PanelTitle.TLabel", background=self.colors["panel"], foreground=self.colors["text"], font=("Segoe UI Semibold", 11))
        style.configure("Body.TLabel", background=self.colors["panel"], foreground=self.colors["text"], font=("Segoe UI", 10))
        style.configure("Status.TLabel", background=self.colors["bg"], foreground=self.colors["muted"], font=("Segoe UI", 9))
        style.configure("Accent.TButton", foreground="#ffffff", background=self.colors["accent"], font=("Segoe UI Semibold", 10), borderwidth=0)
        style.map("Accent.TButton", background=[("active", self.colors["accent_dark"]), ("disabled", "#94a3b8")])
        style.configure("Danger.TButton", foreground="#ffffff", background=self.colors["danger"], font=("Segoe UI Semibold", 10), borderwidth=0)
        style.map("Danger.TButton", background=[("active", "#912018"), ("disabled", "#f1a7a0")])
        style.configure("Treeview", background=self.colors["panel"], fieldbackground=self.colors["panel"], foreground=self.colors["text"], rowheight=30, borderwidth=0)
        style.configure("Treeview.Heading", background=self.colors["panel_alt"], foreground=self.colors["text"], font=("Segoe UI Semibold", 9), relief="flat")
        style.configure("TNotebook", background=self.colors["panel"], borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 8), font=("Segoe UI", 9))
        style.configure("Horizontal.TProgressbar", troughcolor="#e5e7eb", background=self.colors["accent"], borderwidth=0)

    def _build_ui(self) -> None:
        root_frame = ttk.Frame(self.root, padding=18, style="Root.TFrame")
        root_frame.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        root_frame.columnconfigure(0, weight=1)
        root_frame.rowconfigure(2, weight=1)

        self._build_header(root_frame)
        self._build_toolbar(root_frame)
        self._build_workspace(root_frame)
        self._build_footer(root_frame)

    def _build_header(self, parent: ttk.Frame) -> None:
        header = ttk.Frame(parent, style="Root.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="PDF2MD Workbench", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Batch convert PDFs and Office documents into formatted Markdown with queue status, retry, cache, and streaming metrics.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(header, textvariable=self.summary_var, style="Subtitle.TLabel").grid(row=0, column=1, sticky="e")

    def _build_toolbar(self, parent: ttk.Frame) -> None:
        toolbar = ttk.Frame(parent, style="Root.TFrame")
        toolbar.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        toolbar.columnconfigure(9, weight=1)

        self.add_button = ttk.Button(toolbar, text="Add Files", command=self.add_files_from_dialog)
        self.add_button.grid(row=0, column=0, padx=(0, 8))
        self.remove_button = ttk.Button(toolbar, text="Remove", command=self.remove_selected_jobs)
        self.remove_button.grid(row=0, column=1, padx=(0, 8))
        self.clear_button = ttk.Button(toolbar, text="Clear", command=self.clear_jobs)
        self.clear_button.grid(row=0, column=2, padx=(0, 16))
        self.retry_button = ttk.Button(toolbar, text="Retry Failed", command=self.retry_failed_jobs)
        self.retry_button.grid(row=0, column=3, padx=(0, 8))
        self.open_output_button = ttk.Button(toolbar, text="Open Output", command=self.open_selected_output)
        self.open_output_button.grid(row=0, column=4, padx=(0, 8))
        self.open_config_button = ttk.Button(toolbar, text="Open Config", command=self.open_config)
        self.open_config_button.grid(row=0, column=5, padx=(0, 16))
        self.test_api_button = ttk.Button(toolbar, text="Test API", command=self.test_api)
        self.test_api_button.grid(row=0, column=6, padx=(0, 8))
        self.preflight_button = ttk.Button(toolbar, text="Preflight", command=self.run_preflight_dialog)
        self.preflight_button.grid(row=0, column=7, padx=(0, 16))
        self.cancel_button = ttk.Button(toolbar, text="Cancel", command=self.cancel_processing, style="Danger.TButton", state="disabled")
        self.cancel_button.grid(row=0, column=10, padx=(0, 8), sticky="e")
        self.process_button = ttk.Button(toolbar, text="Process Queue", command=self.start_processing, style="Accent.TButton")
        self.process_button.grid(row=0, column=11, sticky="e")

    def _build_workspace(self, parent: ttk.Frame) -> None:
        workspace = ttk.PanedWindow(parent, orient="horizontal")
        workspace.grid(row=2, column=0, sticky="nsew")

        queue_panel = ttk.Frame(workspace, padding=12, style="Panel.TFrame")
        queue_panel.columnconfigure(0, weight=1)
        queue_panel.rowconfigure(2, weight=1)
        workspace.add(queue_panel, weight=3)

        ttk.Label(queue_panel, text="Queue", style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.drop_label = tk.Label(
            queue_panel,
            text="Drop PDF, DOC, DOCX, PPT, or PPTX files here",
            bg="#eef2ff",
            fg=self.colors["accent_dark"],
            font=("Segoe UI Semibold", 11),
            relief="solid",
            bd=1,
            padx=12,
            pady=14,
        )
        self.drop_label.grid(row=1, column=0, sticky="ew", pady=(10, 12))

        queue_frame = ttk.Frame(queue_panel, style="Panel.TFrame")
        queue_frame.grid(row=2, column=0, sticky="nsew")
        queue_frame.columnconfigure(0, weight=1)
        queue_frame.rowconfigure(0, weight=1)

        columns = ("type", "status", "progress", "stage", "tokens", "output")
        self.queue_tree = ttk.Treeview(queue_frame, columns=columns, show="tree headings", selectmode="extended")
        self.queue_tree.heading("#0", text="File")
        self.queue_tree.heading("type", text="Type")
        self.queue_tree.heading("status", text="Status")
        self.queue_tree.heading("progress", text="Progress")
        self.queue_tree.heading("stage", text="Stage")
        self.queue_tree.heading("tokens", text="Tokens")
        self.queue_tree.heading("output", text="Output")
        self.queue_tree.column("#0", width=260, minwidth=180, stretch=True)
        self.queue_tree.column("type", width=58, anchor="center", stretch=False)
        self.queue_tree.column("status", width=92, anchor="center", stretch=False)
        self.queue_tree.column("progress", width=90, anchor="center", stretch=False)
        self.queue_tree.column("stage", width=150, minwidth=110, stretch=True)
        self.queue_tree.column("tokens", width=86, anchor="e", stretch=False)
        self.queue_tree.column("output", width=260, minwidth=180, stretch=True)
        self.queue_tree.grid(row=0, column=0, sticky="nsew")
        self.queue_tree.tag_configure(STATUS_QUEUED, foreground=self.colors["muted"])
        self.queue_tree.tag_configure(STATUS_RUNNING, foreground=self.colors["accent_dark"])
        self.queue_tree.tag_configure(STATUS_DONE, foreground=self.colors["success"])
        self.queue_tree.tag_configure(STATUS_FAILED, foreground=self.colors["danger"])
        self.queue_tree.tag_configure(STATUS_CANCELLED, foreground=self.colors["warning"])

        queue_scrollbar = ttk.Scrollbar(queue_frame, orient="vertical", command=self.queue_tree.yview)
        queue_scrollbar.grid(row=0, column=1, sticky="ns")
        self.queue_tree.configure(yscrollcommand=queue_scrollbar.set)

        side_panel = ttk.Frame(workspace, padding=12, style="Panel.TFrame")
        side_panel.columnconfigure(0, weight=1)
        side_panel.rowconfigure(0, weight=1)
        workspace.add(side_panel, weight=2)

        notebook = ttk.Notebook(side_panel)
        notebook.grid(row=0, column=0, sticky="nsew")
        self.settings_tab = ttk.Frame(notebook, padding=12, style="Panel.TFrame")
        self.advanced_tab = ttk.Frame(notebook, padding=12, style="Panel.TFrame")
        self.log_tab = ttk.Frame(notebook, padding=12, style="Panel.TFrame")
        notebook.add(self.settings_tab, text="Settings")
        notebook.add(self.advanced_tab, text="Advanced")
        notebook.add(self.log_tab, text="Log")
        self._build_settings_tab()
        self._build_advanced_tab()
        self._build_log_tab()

    def _build_settings_tab(self) -> None:
        self.settings_tab.columnconfigure(1, weight=1)
        self._add_labeled_entry(self.settings_tab, 0, "API key", self.api_key_var, show="*")
        self._add_labeled_entry(self.settings_tab, 1, "API URL", self.api_url_var)
        self._add_labeled_entry(self.settings_tab, 2, "Model", self.model_var)
        self._add_labeled_entry(self.settings_tab, 3, "Output folder", self.output_dir_var, browse_command=self.select_output_dir)
        self._add_labeled_entry(self.settings_tab, 4, "Style reference", self.style_reference_var, browse_command=self.select_style_reference)
        ttk.Label(self.settings_tab, text="Existing output", style="Body.TLabel").grid(row=5, column=0, sticky="w", padx=(0, 10), pady=(12, 0))
        overwrite_combo = ttk.Combobox(self.settings_tab, textvariable=self.overwrite_mode_var, values=("rename", "overwrite", "fail"), state="readonly", width=16)
        overwrite_combo.grid(row=5, column=1, sticky="w", pady=(12, 0))
        self.stream_check = ttk.Checkbutton(self.settings_tab, text="Use streaming responses", variable=self.stream_var)
        self.stream_check.grid(row=6, column=0, columnspan=3, sticky="w", pady=(16, 0))
        self.auto_save_button = ttk.Button(self.settings_tab, text="Save Settings", command=lambda: self.save_config_from_current_fields())
        self.auto_save_button.grid(row=7, column=0, sticky="w", pady=(18, 0))

    def _build_advanced_tab(self) -> None:
        self.advanced_tab.columnconfigure(1, weight=1)
        self._add_labeled_entry(self.advanced_tab, 0, "Pages/request", self.pages_per_request_var)
        self._add_labeled_entry(self.advanced_tab, 1, "Workers", self.max_concurrency_var)
        self._add_labeled_entry(self.advanced_tab, 2, "Render DPI", self.render_dpi_var)
        self._add_labeled_entry(self.advanced_tab, 3, "Text limit", self.page_text_limit_var)
        self._add_labeled_entry(self.advanced_tab, 4, "Timeout (s)", self.timeout_var)
        self._add_labeled_entry(self.advanced_tab, 5, "Chunk cache", self.chunk_cache_dir_var, browse_command=self.select_chunk_cache_dir)
        self.auto_crop_check = ttk.Checkbutton(self.advanced_tab, text="Auto-crop rendered page images", variable=self.auto_crop_var)
        self.auto_crop_check.grid(row=6, column=0, columnspan=3, sticky="w", pady=(16, 0))

    def _build_log_tab(self) -> None:
        self.log_tab.columnconfigure(0, weight=1)
        self.log_tab.rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            self.log_tab,
            bg=self.colors["log_bg"],
            fg=self.colors["log_fg"],
            insertbackground=self.colors["log_fg"],
            font=("Consolas", 10),
            relief="flat",
            state="disabled",
            wrap="word",
            padx=10,
            pady=10,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(self.log_tab, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _build_footer(self, parent: ttk.Frame) -> None:
        footer = ttk.Frame(parent, style="Root.TFrame")
        footer.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        footer.columnconfigure(1, weight=1)
        ttk.Label(footer, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=0, sticky="w")
        self.overall_progress = ttk.Progressbar(footer, mode="determinate", maximum=100)
        self.overall_progress.grid(row=0, column=1, sticky="ew", padx=14)
        ttk.Label(footer, textvariable=self.stream_metrics_var, style="Status.TLabel").grid(row=0, column=2, sticky="e")

    def _add_labeled_entry(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        browse_command=None,
        show: str | None = None,
    ) -> None:
        ttk.Label(parent, text=label, style="Body.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 10), pady=(0 if row == 0 else 10, 0))
        entry = ttk.Entry(parent, textvariable=variable, show=show or "")
        entry.grid(row=row, column=1, sticky="ew", pady=(0 if row == 0 else 10, 0))
        if browse_command is not None:
            ttk.Button(parent, text="Browse", command=browse_command).grid(row=row, column=2, sticky="e", padx=(8, 0), pady=(0 if row == 0 else 10, 0))

    def _register_drop_targets(self) -> None:
        for widget in (self.root, self.drop_label, self.queue_tree):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self.handle_drop)

    def build_config_from_current_fields(self) -> dict:
        return {
            "config_version": CONFIG_VERSION,
            "api_key": self.api_key_var.get().strip(),
            "api_url": self.api_url_var.get().strip(),
            "model": self.model_var.get().strip(),
            "output_dir": self.output_dir_var.get().strip(),
            "style_reference": self.style_reference_var.get().strip(),
            "pages_per_request": self.pages_per_request_var.get().strip(),
            "max_concurrency": self.max_concurrency_var.get().strip(),
            "render_dpi": self.render_dpi_var.get().strip(),
            "page_text_limit": self.page_text_limit_var.get().strip(),
            "timeout": self.timeout_var.get().strip(),
            "chunk_cache_dir": self.chunk_cache_dir_var.get().strip(),
            "overwrite_mode": self.overwrite_mode_var.get().strip() or "rename",
            "stream": self.stream_var.get(),
            "auto_crop_images": self.auto_crop_var.get(),
        }

    def save_config_from_current_fields(self, silent: bool = False) -> bool:
        try:
            write_config_file(self.config_path, {**CONFIG_DEFAULTS, **self.build_config_from_current_fields()})
        except OSError as exc:
            if not silent:
                self.append_log(f"Could not save config to {self.config_path}: {exc}")
                messagebox.showerror("Config save failed", str(exc))
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
        self.save_config_from_current_fields(silent=True)
        self.append_log(f"Ready. Add or drop {SUPPORTED_INPUT_LABEL} files to start.")

    def add_files_from_dialog(self) -> None:
        selected = filedialog.askopenfilenames(
            title="Select supported files",
            filetypes=[
                ("Supported files", "*.pdf *.doc *.docx *.ppt *.pptx"),
                ("PDF files", "*.pdf"),
                ("Word documents", "*.doc *.docx"),
                ("PowerPoint presentations", "*.ppt *.pptx"),
            ],
        )
        self.add_files(Path(path) for path in selected)

    def select_output_dir(self) -> None:
        selected = filedialog.askdirectory(title="Select output folder")
        if selected:
            self.output_dir_var.set(selected)
            self.update_all_output_paths()

    def select_style_reference(self) -> None:
        selected = filedialog.askopenfilename(title="Select style reference Markdown", filetypes=[("Markdown files", "*.md"), ("All files", "*.*")])
        if selected:
            self.style_reference_var.set(selected)

    def select_chunk_cache_dir(self) -> None:
        selected = filedialog.askdirectory(title="Select chunk cache folder")
        if selected:
            self.chunk_cache_dir_var.set(selected)

    def handle_drop(self, event) -> None:
        dropped_files = parse_drop_files(self.root, event.data)
        if not dropped_files:
            self.append_log("Ignored drop with no supported files.")
            return
        self.add_files(dropped_files)

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
            self.queue_tree.insert("", tk.END, iid=job_id, text=candidate.name, values=self.job_values(job), tags=(job.status,))
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
        selected = self.queue_tree.selection()
        for job_id in selected:
            self.jobs.pop(job_id, None)
            self.queue_tree.delete(job_id)
        if selected:
            self.append_log(f"Removed {len(selected)} job(s).")
        self.refresh_summary()

    def clear_jobs(self) -> None:
        if self.is_processing:
            return
        self.jobs.clear()
        for item in self.queue_tree.get_children():
            self.queue_tree.delete(item)
        self.overall_progress.configure(value=0)
        self.status_var.set("Ready")
        self.stream_metrics_var.set("Streaming metrics: idle")
        self.refresh_summary()

    def retry_failed_jobs(self) -> None:
        failed_jobs = [job for job in self.jobs.values() if job.status in {STATUS_FAILED, STATUS_CANCELLED}]
        if not failed_jobs:
            messagebox.showinfo("Retry failed", "There are no failed or cancelled jobs to retry.")
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
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, f"[{timestamp}] {message.rstrip()}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def append_log_threadsafe(self, message: str) -> None:
        self.root.after(0, self.append_log, message)

    def get_integer(self, label: str, raw_value: str, minimum: int) -> int:
        try:
            value = int(raw_value)
        except ValueError as exc:
            raise ValueError(f"{label} must be an integer.") from exc
        if value < minimum:
            raise ValueError(f"{label} must be at least {minimum}.")
        return value

    def collect_settings(self) -> dict:
        api_key = self.api_key_var.get().strip() or os.environ.get("ARK_API_KEY", "").strip()
        if not api_key:
            raise ValueError("API key is required. Enter it in the GUI or set ARK_API_KEY.")
        api_url = self.api_url_var.get().strip() or DEFAULT_API_URL
        if not api_url.startswith(("http://", "https://")):
            raise ValueError("API URL must start with http:// or https://.")
        output_dir_raw = self.output_dir_var.get().strip()
        output_dir = Path(output_dir_raw).expanduser() if output_dir_raw else None
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
        style_reference = self.style_reference_var.get().strip()
        if style_reference and not Path(style_reference).is_file():
            raise ValueError("Style reference file was not found.")
        chunk_cache_raw = self.chunk_cache_dir_var.get().strip()
        chunk_cache_dir = Path(chunk_cache_raw).expanduser() if chunk_cache_raw else None
        if chunk_cache_dir is not None:
            chunk_cache_dir.mkdir(parents=True, exist_ok=True)
        overwrite_mode = self.overwrite_mode_var.get().strip() or "rename"
        if overwrite_mode not in {"rename", "overwrite", "fail"}:
            raise ValueError("Existing output must be rename, overwrite, or fail.")
        return {
            "api_key": api_key,
            "api_url": api_url,
            "model": self.model_var.get().strip() or DEFAULT_MODEL,
            "output_dir": output_dir,
            "style_reference": style_reference,
            "pages_per_request": self.get_integer("Pages/request", self.pages_per_request_var.get().strip(), 1),
            "max_concurrency": self.get_integer("Workers", self.max_concurrency_var.get().strip(), 1),
            "render_dpi": self.get_integer("Render DPI", self.render_dpi_var.get().strip(), 1),
            "page_text_limit": self.get_integer("Text limit", self.page_text_limit_var.get().strip(), 0),
            "timeout": self.get_integer("Timeout", self.timeout_var.get().strip(), 1),
            "chunk_cache_dir": str(chunk_cache_dir) if chunk_cache_dir else "",
            "overwrite_mode": overwrite_mode,
            "stream": self.stream_var.get(),
            "auto_crop_images": self.auto_crop_var.get(),
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
                messages.append("LibreOffice was not found; Office inputs may fail on this platform.")
            else:
                messages.append("LibreOffice was found for Office document conversion.")
        return messages

    def run_preflight_dialog(self) -> None:
        try:
            messages = self.run_preflight()
        except Exception as exc:
            messagebox.showerror("Preflight failed", str(exc))
            return
        messagebox.showinfo("Preflight", "\n".join(messages))

    def resolve_output_path(self, input_path: Path, output_dir: Path | None = None) -> Path:
        if output_dir is None:
            raw_output_dir = self.output_dir_var.get().strip()
            output_dir = Path(raw_output_dir).expanduser() if raw_output_dir else None
        if output_dir is None:
            return input_path.with_suffix(".md")
        return output_dir / f"{input_path.stem}.md"

    def update_all_output_paths(self) -> None:
        output_dir_raw = self.output_dir_var.get().strip()
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
            messagebox.showinfo("No work", "Add at least one supported file or retry failed jobs.")
            return
        try:
            settings = self.collect_settings()
            self.run_preflight(settings)
        except Exception as exc:
            messagebox.showerror("Invalid settings", str(exc))
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
                self.root.after(0, self.update_job_row, job)
                cancelled += 1
                continue
            self.root.after(0, self.status_var.set, f"Processing {index}/{total_jobs}: {job.input_path.name}")
            try:
                self.process_single_job(job, settings)
                completed += 1
            except ConversionCancelled as exc:
                cancelled += 1
                self.mark_job_failed(job, STATUS_CANCELLED, str(exc))
            except Exception as exc:
                failed += 1
                self.mark_job_failed(job, STATUS_FAILED, str(exc))
            self.root.after(0, self.update_overall_progress, index, total_jobs)
        self.root.after(0, self.finish_processing, completed, failed, cancelled)

    def process_single_job(self, job: ConversionJob, settings: dict) -> None:
        job.status = STATUS_RUNNING
        job.started_at = time.perf_counter()
        job.finished_at = None
        job.stage = "Starting"
        job.progress = 1
        self.root.after(0, self.update_job_row, job)
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
            stream_progress_callback=lambda chunk_index, total_chunks, start_page, end_page, progress: self.root.after(
                0,
                self.update_stream_metrics,
                job.job_id,
                chunk_index,
                total_chunks,
                start_page,
                end_page,
                progress,
            ),
            progress_callback=lambda progress: self.root.after(0, self.update_conversion_progress, job.job_id, progress),
            cancel_callback=self.cancel_event.is_set,
        )
        job.status = STATUS_DONE
        job.stage = "Done"
        job.message = "Completed"
        job.progress = 100
        job.finished_at = time.perf_counter()
        self.root.after(0, self.update_job_row, job)

    def mark_job_failed(self, job: ConversionJob, status: str, message: str) -> None:
        job.status = status
        job.stage = status
        job.message = message
        job.error = message
        job.finished_at = time.perf_counter()
        self.append_log_threadsafe(f"{job.input_path.name}: {status.lower()} - {message}")
        self.root.after(0, self.update_job_row, job)

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
        self.stream_metrics_var.set(
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
        if not self.queue_tree.exists(job.job_id):
            return
        self.queue_tree.item(job.job_id, text=job.input_path.name, values=self.job_values(job), tags=(job.status,))
        self.refresh_summary()

    def job_values(self, job: ConversionJob) -> tuple[str, str, str, str, str, str]:
        output = str(job.output_path) if job.output_path else ""
        tokens = str(job.output_tokens) if job.output_tokens else ""
        return (job.file_type, job.status, f"{job.progress}%", job.stage, tokens, output)

    def refresh_summary(self) -> None:
        queued = sum(1 for job in self.jobs.values() if job.status == STATUS_QUEUED)
        running = sum(1 for job in self.jobs.values() if job.status == STATUS_RUNNING)
        done = sum(1 for job in self.jobs.values() if job.status == STATUS_DONE)
        failed = sum(1 for job in self.jobs.values() if job.status == STATUS_FAILED)
        cancelled = sum(1 for job in self.jobs.values() if job.status == STATUS_CANCELLED)
        self.summary_var.set(f"{queued} queued | {running} running | {done} done | {failed} failed | {cancelled} cancelled")

    def update_overall_progress(self, completed_jobs: int, total_jobs: int) -> None:
        value = 0 if total_jobs <= 0 else round(completed_jobs * 100 / total_jobs)
        self.overall_progress.configure(value=value)

    def finish_processing(self, completed: int, failed: int, cancelled: int) -> None:
        self.is_processing = False
        self.set_controls_for_processing(False)
        self.refresh_summary()
        if cancelled:
            self.status_var.set(f"Cancelled after {completed} completed, {failed} failed")
        elif failed:
            self.status_var.set(f"Completed with {failed} failure(s)")
            messagebox.showwarning("Batch completed with failures", f"{completed} completed, {failed} failed.")
        else:
            self.status_var.set(f"Completed {completed} file(s)")
            messagebox.showinfo("Batch completed", f"Generated Markdown for {completed} file(s).")
        self.append_log(f"Batch finished: {completed} completed, {failed} failed, {cancelled} cancelled.")

    def set_controls_for_processing(self, running: bool) -> None:
        normal_state = "disabled" if running else "normal"
        self.add_button.configure(state=normal_state)
        self.remove_button.configure(state=normal_state)
        self.clear_button.configure(state=normal_state)
        self.retry_button.configure(state=normal_state)
        self.test_api_button.configure(state=normal_state)
        self.preflight_button.configure(state=normal_state)
        self.process_button.configure(state="disabled" if running else "normal")
        self.cancel_button.configure(state="normal" if running else "disabled")

    def cancel_processing(self) -> None:
        if not self.is_processing:
            return
        self.cancel_event.set()
        self.status_var.set("Cancelling after current API request finishes ...")
        self.append_log("Cancellation requested.")

    def test_api(self) -> None:
        try:
            settings = self.collect_settings()
        except Exception as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return
        self.test_api_button.configure(state="disabled")
        self.status_var.set("Testing API ...")
        threading.Thread(target=self.run_api_test, args=(settings,), daemon=True).start()

    def run_api_test(self, settings: dict) -> None:
        try:
            result = call_responses_api(
                api_url=settings["api_url"],
                api_key=settings["api_key"],
                model=settings["model"],
                content=[{"type": "input_text", "text": "Reply with the single word OK."}],
                timeout=settings["timeout"],
                stream=False,
            )
        except Exception as exc:
            self.root.after(0, self.finish_api_test, False, str(exc))
            return
        self.root.after(0, self.finish_api_test, True, result[:200])

    def finish_api_test(self, success: bool, message: str) -> None:
        self.test_api_button.configure(state="normal" if not self.is_processing else "disabled")
        if success:
            self.status_var.set("API test succeeded")
            self.append_log(f"API test succeeded: {message}")
            messagebox.showinfo("API test", f"API responded: {message}")
        else:
            self.status_var.set("API test failed")
            self.append_log(f"API test failed: {message}")
            messagebox.showerror("API test failed", message)

    def open_config(self) -> None:
        self.save_config_from_current_fields(silent=True)
        open_path(self.config_path)

    def open_selected_output(self) -> None:
        selected = self.queue_tree.selection()
        if selected:
            job = self.jobs.get(selected[0])
            if job is not None and job.output_path is not None:
                target = job.output_path if job.output_path.exists() else job.output_path.parent
                if target.exists():
                    open_path(target)
                    return
        output_dir_raw = self.output_dir_var.get().strip()
        fallback = Path(output_dir_raw).expanduser() if output_dir_raw else get_application_directory()
        if fallback.exists():
            open_path(fallback)

    def handle_close(self) -> None:
        if self.is_processing:
            if messagebox.askyesno("Cancel batch", "A batch is running. Cancel it after the current request finishes?"):
                self.cancel_processing()
            return
        self.save_config_from_current_fields(silent=True)
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = MarkdownConverterApp()
    app.run()


if __name__ == "__main__":
    main()