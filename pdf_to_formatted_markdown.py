from __future__ import annotations

import argparse
import base64
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Sequence
from urllib.parse import urlparse, urlunparse
from urllib import error, request

try:
    import certifi
except ImportError:
    certifi = None

try:
    import fitz
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: PyMuPDF. Install with: .\\.venv\\Scripts\\python.exe -m pip install PyMuPDF"
    ) from exc


DEFAULT_API_URL = "https://ark.ap-southeast.bytepluses.com/api/v3/responses"
DEFAULT_MODEL = "seed-2-0-pro-260328"
BACKGROUND_DIFF_THRESHOLD = 12
BACKGROUND_DOMINANCE_RATIO = 0.6
BACKGROUND_QUANTIZATION = 8
MIN_CROP_MARGIN_PIXELS = 12
CROP_PADDING_PIXELS = 12
ESTIMATED_CHARS_PER_TOKEN = 4.0
STREAM_PROGRESS_INTERVAL_SECONDS = 0.5
SUPPORTED_INPUT_SUFFIXES = (".pdf", ".doc", ".docx", ".ppt", ".pptx")
WORD_EXPORT_FORMAT_PDF = 17
POWERPOINT_SAVE_AS_PDF = 32
MACOS_SOFFICE_PATHS = (
    Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
    Path.home() / "Applications/LibreOffice.app/Contents/MacOS/soffice",
    Path("/opt/homebrew/bin/soffice"),
    Path("/usr/local/bin/soffice"),
)
WINDOWS_SOFFICE_PATHS = (
    Path("C:/Program Files/LibreOffice/program/soffice.exe"),
    Path("C:/Program Files (x86)/LibreOffice/program/soffice.exe"),
)


@dataclass
class PageArtifact:
    page_number: int
    image_path: Path
    extracted_text: str


@dataclass
class StreamProgress:
    output_tokens: int
    tokens_per_second: float
    elapsed_seconds: float
    is_final: bool = False


@dataclass
class ConversionProgress:
    stage: str
    message: str
    current: int = 0
    total: int = 0


class ConversionCancelled(RuntimeError):
    pass


@dataclass
class ConversionOptions:
    input_path: Path
    output_path: Optional[Path]
    api_url: str = DEFAULT_API_URL
    api_key: str = ""
    model: str = DEFAULT_MODEL
    pages_per_request: int = 4
    render_dpi: int = 160
    page_text_limit: int = 0
    style_reference_path: str = ""
    artifact_dir: str = ""
    timeout: int = 300
    stream: bool = True
    auto_crop_images: bool = True
    max_concurrency: int = 4
    chunk_cache_dir: str = ""
    overwrite_mode: str = "overwrite"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a PDF, DOC, DOCX, PPT, or PPTX into reformatted Markdown via the Responses API."
    )
    parser.add_argument("--input", required=True, help="Input PDF, DOC, DOCX, PPT, or PPTX path")
    parser.add_argument(
        "--output",
        default="",
        help="Output Markdown path. Use '-' to print Markdown to stdout.",
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"Responses API URL. Defaults to {DEFAULT_API_URL}",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("ARK_API_KEY", ""),
        help="API key. Defaults to ARK_API_KEY from the environment.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Model name. Defaults to {DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--pages-per-request",
        type=int,
        default=4,
        help="Number of PDF pages to send per Responses API call.",
    )
    parser.add_argument(
        "--render-dpi",
        type=int,
        default=160,
        help="Render DPI for page screenshots.",
    )
    parser.add_argument(
        "--page-text-limit",
        type=int,
        default=0,
        help="Optional character cap per page for extracted text. 0 keeps all text.",
    )
    parser.add_argument(
        "--style-reference",
        default="",
        help="Optional Markdown file whose writing style should be mirrored.",
    )
    parser.add_argument(
        "--artifact-dir",
        default="",
        help="Optional directory to keep rendered page screenshots.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=4,
        help="Maximum number of concurrent Responses API calls per document.",
    )
    parser.add_argument(
        "--chunk-cache-dir",
        default="",
        help="Optional directory used to cache per-chunk Markdown outputs for retry/resume workflows.",
    )
    parser.add_argument(
        "--overwrite-mode",
        choices=("overwrite", "rename", "fail"),
        default="overwrite",
        help="How to handle an existing output Markdown file.",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable streaming and wait for the full response body.",
    )
    parser.add_argument(
        "--no-auto-crop",
        action="store_true",
        help="Keep full-page screenshots instead of cropping uniform blank margins.",
    )
    return parser.parse_args()


def log(message: str) -> None:
    print(message, file=sys.stderr)


def validate_input_document(input_path: Path) -> Path:
    if not input_path.is_file():
        raise SystemExit(f"Input file not found: {input_path}")
    if input_path.suffix.lower() not in SUPPORTED_INPUT_SUFFIXES:
        supported = ", ".join(SUPPORTED_INPUT_SUFFIXES)
        raise SystemExit(f"Input file must be one of {supported}: {input_path}")
    return input_path


def resolve_output_path(input_path: Path, output_arg: str) -> Optional[Path]:
    if output_arg == "-":
        return None
    if output_arg:
        return Path(output_arg)
    return input_path.with_suffix(".md")


def derive_models_api_url(api_url: str) -> str:
    parsed = urlparse(api_url)
    path = parsed.path.rstrip("/")
    known_suffixes = (
        "/responses",
        "/chat/completions",
        "/completions",
        "/messages",
    )

    for suffix in known_suffixes:
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break

    if not path.endswith("/models"):
        path = f"{path}/models" if path else "/models"

    return urlunparse(parsed._replace(path=path, params="", query="", fragment=""))


def extract_model_ids(payload: dict) -> list[str]:
    candidates = payload.get("data")
    if candidates is None:
        candidates = payload.get("models")

    model_ids: list[str] = []
    if isinstance(candidates, list):
        for item in candidates:
            if isinstance(item, dict):
                model_id = item.get("id") or item.get("model") or item.get("name")
            else:
                model_id = item

            if isinstance(model_id, str) and model_id.strip():
                model_ids.append(model_id.strip())

    if not model_ids:
        for key in ("id", "model", "name"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                model_ids.append(value.strip())

    return sorted(set(model_ids), key=str.casefold)


def create_ssl_context() -> ssl.SSLContext:
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def list_available_models(api_url: str, api_key: str, timeout: int) -> list[str]:
    models_url = derive_models_api_url(api_url)
    ssl_context = create_ssl_context()
    req = request.Request(
        models_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "ark-beta-mcp": "true",
        },
        method="GET",
    )

    try:
        with request.urlopen(req, timeout=timeout, context=ssl_context) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Model list request failed ({exc.code}): {body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Model list request failed: {exc.reason}") from exc

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Model list endpoint did not return JSON: {body[:300]}") from exc

    model_ids = extract_model_ids(payload)
    if not model_ids:
        raise RuntimeError(f"Model list endpoint returned no models: {body[:500]}")
    return model_ids


def ensure_api_key(api_key: str) -> str:
    api_key = api_key.strip()
    if not api_key:
        raise SystemExit("Missing API key. Pass --api-key or set ARK_API_KEY.")
    return api_key


def raise_if_cancelled(cancel_callback: Optional[Callable[[], bool]]) -> None:
    if cancel_callback is not None and cancel_callback():
        raise ConversionCancelled("Conversion cancelled by user.")


def report_conversion_progress(
    progress_callback: Optional[Callable[[ConversionProgress], None]],
    stage: str,
    message: str,
    current: int = 0,
    total: int = 0,
) -> None:
    if progress_callback is not None:
        progress_callback(ConversionProgress(stage=stage, message=message, current=current, total=total))


def make_non_conflicting_path(output_path: Path) -> Path:
    if not output_path.exists():
        return output_path

    for index in range(1, 1000):
        candidate = output_path.with_name(f"{output_path.stem}_{index}{output_path.suffix}")
        if not candidate.exists():
            return candidate

    raise RuntimeError(f"Unable to find a non-conflicting output path for {output_path}")


def resolve_output_conflict(output_path: Optional[Path], overwrite_mode: str) -> Optional[Path]:
    if output_path is None:
        return None

    normalized_mode = overwrite_mode.strip().lower() or "overwrite"
    if normalized_mode == "overwrite" or not output_path.exists():
        return output_path
    if normalized_mode == "rename":
        return make_non_conflicting_path(output_path)
    if normalized_mode == "fail":
        raise RuntimeError(f"Output file already exists: {output_path}")
    raise RuntimeError(f"Unsupported overwrite mode: {overwrite_mode}")


def build_chunk_cache_directory(input_path: Path, cache_root: str) -> Optional[Path]:
    if not cache_root:
        return None

    fingerprint_source = f"{input_path.resolve()}|{input_path.stat().st_size}|{input_path.stat().st_mtime_ns}"
    fingerprint = hashlib.sha256(fingerprint_source.encode("utf-8", errors="ignore")).hexdigest()[:16]
    cache_dir = Path(cache_root) / f"{input_path.stem}_{fingerprint}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_chunk_cache_path(cache_dir: Optional[Path], chunk_index: int, start_page: int, end_page: int) -> Optional[Path]:
    if cache_dir is None:
        return None
    return cache_dir / f"chunk_{chunk_index:03d}_pages_{start_page:03d}_{end_page:03d}.md"


def get_subprocess_run_kwargs() -> dict:
    if sys.platform != "win32":
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


def run_subprocess(command: Sequence[str], timeout: int, error_context: str) -> None:
    try:
        completed = subprocess.run(
            list(command),
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            **get_subprocess_run_kwargs(),
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"{error_context}: executable not found.") from exc
    except subprocess.CalledProcessError as exc:
        stdout = exc.stdout.strip()
        stderr = exc.stderr.strip()
        details = stderr or stdout or f"Exit code {exc.returncode}"
        raise RuntimeError(f"{error_context}: {details}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{error_context}: timed out after {timeout} seconds.") from exc

    if completed.stderr.strip():
        return


def find_soffice_executable() -> Optional[str]:
    override_candidates = [
        os.environ.get("PDF2MD_SOFFICE_PATH", "").strip(),
        os.environ.get("SOFFICE_PATH", "").strip(),
        os.environ.get("LIBREOFFICE_PATH", "").strip(),
    ]
    for override in override_candidates:
        if override and Path(override).is_file():
            return override

    for executable_name in ("soffice", "libreoffice"):
        soffice = shutil.which(executable_name)
        if soffice:
            return soffice

    common_paths = list(WINDOWS_SOFFICE_PATHS)
    if sys.platform == "darwin":
        common_paths = [*MACOS_SOFFICE_PATHS, *common_paths]

    for candidate in common_paths:
        if candidate.is_file():
            return str(candidate)
    return None


def get_office_conversion_help_text() -> str:
    if sys.platform == "darwin":
        return (
            "LibreOffice is required for DOC, DOCX, PPT, and PPTX conversion on macOS. "
            "Install it from https://www.libreoffice.org/download/download-libreoffice/ or with Homebrew using 'brew install --cask libreoffice'. "
            "Common executable paths are /Applications/LibreOffice.app/Contents/MacOS/soffice and /opt/homebrew/bin/soffice. "
            "If your install is elsewhere, set PDF2MD_SOFFICE_PATH to the full soffice path."
        )
    if sys.platform.startswith("win"):
        return (
            "LibreOffice or Microsoft Office is required for DOC, DOCX, PPT, and PPTX conversion on Windows. "
            "Install LibreOffice from https://www.libreoffice.org/download/download-libreoffice/ and make sure soffice.exe is available, "
            "usually under C:\\Program Files\\LibreOffice\\program\\soffice.exe. "
            "If LibreOffice is installed elsewhere, set PDF2MD_SOFFICE_PATH to that soffice.exe path."
        )
    return (
        "Install LibreOffice for DOC, DOCX, PPT, and PPTX conversion and ensure soffice is on PATH, "
        "or set PDF2MD_SOFFICE_PATH to the executable."
    )


def convert_with_soffice(input_path: Path, output_pdf_path: Path, timeout: int) -> None:
    soffice = find_soffice_executable()
    if soffice is None:
        raise RuntimeError(f"LibreOffice soffice was not found. {get_office_conversion_help_text()}")

    soffice_output_path = output_pdf_path.parent / f"{input_path.stem}.pdf"
    soffice_output_path.unlink(missing_ok=True)
    output_pdf_path.unlink(missing_ok=True)
    run_subprocess(
        [
            soffice,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_pdf_path.parent),
            str(input_path),
        ],
        timeout=timeout,
        error_context=f"LibreOffice PDF conversion failed for {input_path.name}",
    )
    if not soffice_output_path.is_file():
        raise RuntimeError(f"LibreOffice did not produce {output_pdf_path.name}.")
    soffice_output_path.replace(output_pdf_path)


def build_office_conversion_script(suffix: str) -> str:
    if suffix in {".doc", ".docx"}:
        return f"""
param([string]$InputPath, [string]$OutputPath)
$ErrorActionPreference = 'Stop'
$InputPath = [System.IO.Path]::GetFullPath($InputPath)
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$app = New-Object -ComObject Word.Application
try {{
    $app.Visible = $false
    $app.DisplayAlerts = 0
    $document = $app.Documents.Open($InputPath, $false, $true)
    try {{
        $document.ExportAsFixedFormat($OutputPath, {WORD_EXPORT_FORMAT_PDF})
    }} finally {{
        $document.Close([ref]0)
    }}
}} finally {{
    $app.Quit()
}}
""".strip()

    if suffix in {".ppt", ".pptx"}:
        return f"""
param([string]$InputPath, [string]$OutputPath)
$ErrorActionPreference = 'Stop'
$InputPath = [System.IO.Path]::GetFullPath($InputPath)
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$app = New-Object -ComObject PowerPoint.Application
try {{
    $presentation = $app.Presentations.Open($InputPath, $true, $false, $false)
    try {{
        $presentation.SaveAs($OutputPath, {POWERPOINT_SAVE_AS_PDF})
    }} finally {{
        $presentation.Close()
    }}
}} finally {{
    $app.Quit()
}}
""".strip()

    raise RuntimeError(f"Unsupported Office conversion suffix: {suffix}")


def convert_with_microsoft_office(input_path: Path, output_pdf_path: Path, timeout: int) -> None:
    if os.name != "nt":
        raise RuntimeError("Microsoft Office COM automation is only available on Windows.")

    output_pdf_path.unlink(missing_ok=True)
    script = build_office_conversion_script(input_path.suffix.lower())
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", delete=False, encoding="utf-8") as script_file:
        script_file.write(script)
        script_path = Path(script_file.name)

    try:
        run_subprocess(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-STA",
                "-File",
                str(script_path),
                "-InputPath",
                str(input_path),
                "-OutputPath",
                str(output_pdf_path),
            ],
            timeout=timeout,
            error_context=f"Microsoft Office PDF conversion failed for {input_path.name}",
        )
    finally:
        script_path.unlink(missing_ok=True)

    if not output_pdf_path.is_file():
        raise RuntimeError(f"Microsoft Office did not produce {output_pdf_path.name}.")


def prepare_pdf_input(
    input_path: Path,
    working_dir: Path,
    timeout: int,
    logger: Callable[[str], None],
) -> Path:
    if input_path.suffix.lower() == ".pdf":
        return input_path

    output_pdf_path = working_dir / f"{input_path.stem}_converted.pdf"
    logger(f"Converting {input_path.name} to PDF before processing ...")

    conversion_errors: List[str] = []
    for backend_name, converter in (
        ("Microsoft Office", convert_with_microsoft_office),
        ("LibreOffice", convert_with_soffice),
    ):
        try:
            converter(input_path, output_pdf_path, timeout)
            logger(f"Converted {input_path.name} to PDF using {backend_name}.")
            return output_pdf_path
        except RuntimeError as exc:
            conversion_errors.append(str(exc))

    details = " | ".join(conversion_errors)
    raise RuntimeError(
        f"Unable to convert {input_path.name} to PDF. {get_office_conversion_help_text()} {details}"
    )


def load_style_reference(path: str) -> str:
    if not path:
        return ""
    ref_path = Path(path)
    if not ref_path.is_file():
        raise SystemExit(f"Style reference not found: {ref_path}")
    return ref_path.read_text(encoding="utf-8").strip()


def build_conversion_instructions(style_reference: str) -> str:
    lines = [
        "Convert the provided PDF content into clean, publication-ready Markdown.",
        "Output only the fully reformatted markdown.",
        "Preserve the original answers, logic, and calculations. Do not change the meaning unless fixing an obvious formatting issue.",
        "Format mathematical expressions cleanly.",
        "Use inline math for short expressions.",
        "Use display math blocks for key formulas, derivations, and final calculations.",
        "Put important equations on their own lines using $$ ... $$.",
        "Use a direct academic tone with clear spacing between paragraphs and equations.",
        "Use short explanatory lead-ins before calculations when useful.",
        "Keep heading levels consistent and preserve the original question order.",
        "For short-answer questions, start with the direct answer such as False. or **5 GHz band**., then follow with a concise explanation.",
        "Use numbered lists only when the original content is naturally list-based.",
        "Remove decorative separators unless they are needed for meaning.",
        "Keep spacing consistent and avoid mixed bullet formatting on a single line.",
        "If the extracted text is incomplete or noisy, use it only as supporting context.",
        "If the screenshot and extracted text disagree, trust the screenshot.",
    ]
    if style_reference:
        lines.extend(
            [
                "",
                "Mirror the writing style of this reference Markdown where it does not conflict with the PDF content:",
                style_reference,
            ]
        )
    return "\n".join(lines).strip()


def sanitize_extracted_text(text: str, limit: int) -> str:
    cleaned = text.replace("\x00", "").strip()
    if limit > 0 and len(cleaned) > limit:
        return cleaned[:limit].rstrip() + "\n\n[Truncated extracted text due to page-text-limit.]"
    return cleaned


def quantize_color(color: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple((channel // BACKGROUND_QUANTIZATION) * BACKGROUND_QUANTIZATION for channel in color)


def get_pixel_rgb(samples: memoryview, stride: int, channels: int, x: int, y: int) -> tuple[int, int, int]:
    offset = y * stride + x * channels
    if channels == 1:
        value = samples[offset]
        return value, value, value
    return samples[offset], samples[offset + 1], samples[offset + 2]


def estimate_uniform_background_color(pixmap: fitz.Pixmap) -> Optional[tuple[int, int, int]]:
    width = pixmap.width
    height = pixmap.height
    if width == 0 or height == 0:
        return None

    samples = memoryview(pixmap.samples)
    x_step = max(1, width // 120)
    y_step = max(1, height // 120)
    border_colors: List[tuple[int, int, int]] = []

    for x in range(0, width, x_step):
        border_colors.append(quantize_color(get_pixel_rgb(samples, pixmap.stride, pixmap.n, x, 0)))
        if height > 1:
            border_colors.append(quantize_color(get_pixel_rgb(samples, pixmap.stride, pixmap.n, x, height - 1)))

    for y in range(0, height, y_step):
        border_colors.append(quantize_color(get_pixel_rgb(samples, pixmap.stride, pixmap.n, 0, y)))
        if width > 1:
            border_colors.append(quantize_color(get_pixel_rgb(samples, pixmap.stride, pixmap.n, width - 1, y)))

    if not border_colors:
        return None

    background_color, count = Counter(border_colors).most_common(1)[0]
    if count / len(border_colors) < BACKGROUND_DOMINANCE_RATIO:
        return None
    return background_color


def pixel_differs_from_background(
    samples: memoryview,
    stride: int,
    channels: int,
    x: int,
    y: int,
    background_color: tuple[int, int, int],
) -> bool:
    offset = y * stride + x * channels
    if channels == 1:
        return abs(samples[offset] - background_color[0]) > BACKGROUND_DIFF_THRESHOLD
    return (
        abs(samples[offset] - background_color[0]) > BACKGROUND_DIFF_THRESHOLD
        or abs(samples[offset + 1] - background_color[1]) > BACKGROUND_DIFF_THRESHOLD
        or abs(samples[offset + 2] - background_color[2]) > BACKGROUND_DIFF_THRESHOLD
    )


def row_has_content(
    samples: memoryview,
    width: int,
    stride: int,
    channels: int,
    y: int,
    background_color: tuple[int, int, int],
) -> bool:
    for x in range(width):
        if pixel_differs_from_background(samples, stride, channels, x, y, background_color):
            return True
    return False


def column_has_content(
    samples: memoryview,
    height: int,
    stride: int,
    channels: int,
    x: int,
    top: int,
    bottom: int,
    background_color: tuple[int, int, int],
) -> bool:
    for y in range(top, bottom + 1):
        if pixel_differs_from_background(samples, stride, channels, x, y, background_color):
            return True
    return False


def detect_content_bbox(pixmap: fitz.Pixmap) -> Optional[tuple[int, int, int, int]]:
    background_color = estimate_uniform_background_color(pixmap)
    if background_color is None:
        return None

    width = pixmap.width
    height = pixmap.height
    samples = memoryview(pixmap.samples)
    stride = pixmap.stride
    channels = pixmap.n

    top = next(
        (y for y in range(height) if row_has_content(samples, width, stride, channels, y, background_color)),
        None,
    )
    if top is None:
        return None

    bottom = next(
        (y for y in range(height - 1, -1, -1) if row_has_content(samples, width, stride, channels, y, background_color)),
        None,
    )
    if bottom is None:
        return None

    left = next(
        (x for x in range(width) if column_has_content(samples, height, stride, channels, x, top, bottom, background_color)),
        None,
    )
    right = next(
        (x for x in range(width - 1, -1, -1) if column_has_content(samples, height, stride, channels, x, top, bottom, background_color)),
        None,
    )
    if left is None or right is None:
        return None

    minimum_margin = max(MIN_CROP_MARGIN_PIXELS, int(min(width, height) * 0.01))
    margins = (top, left, height - 1 - bottom, width - 1 - right)
    if max(margins) < minimum_margin:
        return None

    padding = max(CROP_PADDING_PIXELS, int(min(width, height) * 0.01))
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(width - 1, right + padding)
    bottom = min(height - 1, bottom + padding)

    if left == 0 and top == 0 and right == width - 1 and bottom == height - 1:
        return None
    return left, top, right, bottom


def maybe_crop_pixmap(page: fitz.Page, pixmap: fitz.Pixmap, matrix: fitz.Matrix, zoom: float) -> fitz.Pixmap:
    content_bbox = detect_content_bbox(pixmap)
    if content_bbox is None:
        return pixmap

    left, top, right, bottom = content_bbox
    clip_rect = fitz.Rect(
        left / zoom,
        top / zoom,
        (right + 1) / zoom,
        (bottom + 1) / zoom,
    )
    return page.get_pixmap(matrix=matrix, clip=clip_rect, alpha=False)


def render_pdf_pages(
    pdf_path: Path,
    image_dir: Path,
    render_dpi: int,
    page_text_limit: int,
    auto_crop_images: bool,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> List[PageArtifact]:
    zoom = render_dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    artifacts: List[PageArtifact] = []

    with fitz.open(pdf_path) as document:
        if document.page_count == 0:
            raise SystemExit(f"The PDF has no pages: {pdf_path}")

        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            if auto_crop_images:
                pixmap = maybe_crop_pixmap(page, pixmap, matrix, zoom)
            image_path = image_dir / f"page_{page_index + 1:03d}.png"
            pixmap.save(image_path)
            extracted_text = sanitize_extracted_text(page.get_text("text"), page_text_limit)
            artifacts.append(
                PageArtifact(
                    page_number=page_index + 1,
                    image_path=image_path,
                    extracted_text=extracted_text,
                )
            )
            if progress_callback is not None:
                progress_callback(page_index + 1, document.page_count)

    return artifacts


def chunked(items: Sequence[PageArtifact], size: int) -> Iterator[Sequence[PageArtifact]]:
    if size <= 0:
        raise SystemExit("--pages-per-request must be greater than 0.")
    for start in range(0, len(items), size):
        yield items[start:start + size]


def image_to_data_url(image_path: Path) -> str:
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def build_chunk_content(
    pdf_name: str,
    instructions: str,
    pages: Sequence[PageArtifact],
) -> List[dict]:
    start_page = pages[0].page_number
    end_page = pages[-1].page_number
    content: List[dict] = [
        {
            "type": "input_text",
            "text": (
                f"Source PDF: {pdf_name}\n"
                f"Pages in this chunk: {start_page}-{end_page}\n\n"
                f"{instructions}"
            ),
        }
    ]

    for page in pages:
        extracted_text = page.extracted_text or "[No extractable text found on this page.]"
        content.append(
            {
                "type": "input_text",
                "text": f"Page {page.page_number} extracted text:\n{extracted_text}",
            }
        )
        content.append(
            {
                "type": "input_image",
                "image_url": image_to_data_url(page.image_path),
            }
        )

    return content


def extract_output_text_from_response(payload: dict) -> str:
    output_text = str(payload.get("output_text", "")).strip()
    if output_text:
        return output_text

    texts: List[str] = []
    for item in payload.get("output") or []:
        for content in item.get("content") or []:
            if content.get("type") == "output_text":
                text = str(content.get("text", ""))
                if text:
                    texts.append(text)
    return "".join(texts).strip()


def extract_output_token_count_from_response(payload: dict) -> Optional[int]:
    usage = payload.get("usage") or {}
    if isinstance(usage, dict):
        for key in ("output_tokens", "completion_tokens"):
            value = usage.get(key)
            if isinstance(value, int) and value > 0:
                return value
    return None


def estimate_token_count_from_char_count(char_count: int) -> int:
    if char_count <= 0:
        return 0
    return max(1, round(char_count / ESTIMATED_CHARS_PER_TOKEN))


def iter_sse_events(response_obj) -> Iterator[tuple[str, str]]:
    event_name = ""
    data_lines: List[str] = []

    for raw_line in response_obj:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line:
            if data_lines:
                yield event_name, "\n".join(data_lines)
                event_name = ""
                data_lines = []
            continue
        if line.startswith(":"):
            continue

        field, _, value = line.partition(":")
        value = value.lstrip()
        if field == "event":
            event_name = value
        elif field == "data":
            data_lines.append(value)

    if data_lines:
        yield event_name, "\n".join(data_lines)


def create_responses_payload(model: str, content: List[dict], stream: bool) -> dict:
    return {
        "model": model,
        "stream": stream,
        "input": [
            {
                "role": "user",
                "content": content,
            }
        ],
    }


def call_responses_api(
    api_url: str,
    api_key: str,
    model: str,
    content: List[dict],
    timeout: int,
    stream: bool,
    stream_progress_callback: Optional[Callable[[StreamProgress], None]] = None,
) -> str:
    payload = create_responses_payload(model=model, content=content, stream=stream)
    ssl_context = create_ssl_context()
    req = request.Request(
        api_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "ark-beta-mcp": "true",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout, context=ssl_context) as resp:
            if not stream:
                body = resp.read().decode("utf-8", errors="replace")
                data = json.loads(body)
                text = extract_output_text_from_response(data)
                if not text:
                    raise ValueError(f"Empty response text returned: {body[:1000]}")
                return text

            delta_parts: List[str] = []
            completed_response: Optional[dict] = None
            streamed_char_count = 0
            stream_started_at = time.perf_counter()
            last_progress_report_at = 0.0

            def report_stream_progress(force: bool = False, is_final: bool = False, output_tokens: Optional[int] = None) -> None:
                nonlocal last_progress_report_at
                if stream_progress_callback is None:
                    return

                now = time.perf_counter()
                if not force and now - last_progress_report_at < STREAM_PROGRESS_INTERVAL_SECONDS:
                    return

                elapsed_seconds = max(now - stream_started_at, 1e-6)
                token_count = output_tokens if output_tokens is not None else estimate_token_count_from_char_count(streamed_char_count)
                stream_progress_callback(
                    StreamProgress(
                        output_tokens=token_count,
                        tokens_per_second=token_count / elapsed_seconds if token_count > 0 else 0.0,
                        elapsed_seconds=elapsed_seconds,
                        is_final=is_final,
                    )
                )
                last_progress_report_at = now

            for _, data_blob in iter_sse_events(resp):
                if not data_blob or data_blob == "[DONE]":
                    continue

                event = json.loads(data_blob)
                event_type = str(event.get("type", ""))

                if event_type == "response.output_text.delta":
                    delta = str(event.get("delta", ""))
                    if delta:
                        delta_parts.append(delta)
                        streamed_char_count += len(delta)
                        report_stream_progress()
                elif event_type == "response.completed":
                    completed_response = event.get("response") or {}
                elif event_type == "response.error":
                    raise ValueError(json.dumps(event, ensure_ascii=False))

            text = "".join(delta_parts).strip()
            if text:
                final_output_tokens = extract_output_token_count_from_response(completed_response or {})
                if final_output_tokens is None:
                    final_output_tokens = estimate_token_count_from_char_count(len(text))
                report_stream_progress(force=True, is_final=True, output_tokens=final_output_tokens)
                return text

            if completed_response:
                text = extract_output_text_from_response(completed_response)
                if text:
                    final_output_tokens = extract_output_token_count_from_response(completed_response)
                    if final_output_tokens is None:
                        final_output_tokens = estimate_token_count_from_char_count(len(text))
                    report_stream_progress(force=True, is_final=True, output_tokens=final_output_tokens)
                    return text

            raise ValueError("Streaming completed without any output text.")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Responses API request failed ({exc.code}): {body}") from exc


def build_merge_content(
    pdf_name: str,
    instructions: str,
    chunk_outputs: Sequence[str],
) -> List[dict]:
    pieces = [
        {
            "type": "input_text",
            "text": (
                f"Source PDF: {pdf_name}\n\n"
                "The following Markdown chunks were produced from consecutive page ranges of the same PDF. "
                "Merge them into one clean final document. Remove obvious chunk-boundary duplication, keep the original order, and output only the final markdown.\n\n"
                f"{instructions}"
            ),
        }
    ]

    for index, chunk_output in enumerate(chunk_outputs, start=1):
        pieces.append(
            {
                "type": "input_text",
                "text": f"Chunk {index} markdown:\n{chunk_output}",
            }
        )
    return pieces


def write_markdown(output_path: Optional[Path], markdown_text: str, overwrite_mode: str = "overwrite") -> Optional[Path]:
    normalized = markdown_text.strip() + "\n"
    if output_path is None:
        sys.stdout.write(normalized)
        return None
    final_output_path = resolve_output_conflict(output_path, overwrite_mode)
    if final_output_path is None:
        return None
    final_output_path.parent.mkdir(parents=True, exist_ok=True)
    final_output_path.write_text(normalized, encoding="utf-8")
    return final_output_path


def maybe_prepare_artifact_dir(input_path: Path, artifact_dir_arg: str):
    if artifact_dir_arg:
        artifact_dir = Path(artifact_dir_arg)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        return artifact_dir, None

    temp_dir = tempfile.TemporaryDirectory(prefix=f"{input_path.stem}_pages_")
    return Path(temp_dir.name), temp_dir


def ensure_positive_integer(value: int, flag_name: str) -> int:
    if value <= 0:
        raise SystemExit(f"{flag_name} must be greater than 0.")
    return value


def build_options_from_args(args: argparse.Namespace) -> ConversionOptions:
    input_path = validate_input_document(Path(args.input))
    return ConversionOptions(
        input_path=input_path,
        output_path=resolve_output_path(input_path, args.output),
        api_url=args.api_url,
        api_key=args.api_key,
        model=args.model,
        pages_per_request=args.pages_per_request,
        render_dpi=args.render_dpi,
        page_text_limit=args.page_text_limit,
        style_reference_path=args.style_reference,
        artifact_dir=args.artifact_dir,
        timeout=args.timeout,
        stream=not args.no_stream,
        auto_crop_images=not args.no_auto_crop,
        max_concurrency=args.max_concurrency,
        chunk_cache_dir=args.chunk_cache_dir,
        overwrite_mode=args.overwrite_mode,
    )


def convert_pdf_to_markdown(
    options: ConversionOptions,
    logger: Callable[[str], None] = log,
    stream_progress_callback: Optional[Callable[[int, int, int, int, StreamProgress], None]] = None,
    progress_callback: Optional[Callable[[ConversionProgress], None]] = None,
    cancel_callback: Optional[Callable[[], bool]] = None,
) -> str:
    raise_if_cancelled(cancel_callback)
    report_conversion_progress(progress_callback, "validate", "Validating input and settings")
    input_path = validate_input_document(Path(options.input_path))
    api_key = ensure_api_key(options.api_key)
    style_reference = load_style_reference(options.style_reference_path)
    instructions = build_conversion_instructions(style_reference)
    max_concurrency = ensure_positive_integer(options.max_concurrency, "--max-concurrency")
    chunk_cache_dir = build_chunk_cache_directory(input_path, options.chunk_cache_dir)

    image_dir, temp_dir = maybe_prepare_artifact_dir(input_path, options.artifact_dir)
    try:
        raise_if_cancelled(cancel_callback)
        report_conversion_progress(progress_callback, "prepare", f"Preparing {input_path.name}")
        source_pdf_path = prepare_pdf_input(
            input_path=input_path,
            working_dir=image_dir,
            timeout=options.timeout,
            logger=logger,
        )

        raise_if_cancelled(cancel_callback)
        logger(f"Rendering PDF pages from {source_pdf_path} ...")
        report_conversion_progress(progress_callback, "render", f"Rendering pages from {source_pdf_path.name}")
        page_artifacts = render_pdf_pages(
            pdf_path=source_pdf_path,
            image_dir=image_dir,
            render_dpi=options.render_dpi,
            page_text_limit=options.page_text_limit,
            auto_crop_images=options.auto_crop_images,
            progress_callback=lambda current, total: report_conversion_progress(
                progress_callback,
                "render",
                f"Rendered page {current}/{total}",
                current,
                total,
            ),
        )

        raise_if_cancelled(cancel_callback)
        page_chunks = list(chunked(page_artifacts, options.pages_per_request))
        chunk_outputs: List[str] = [""] * len(page_chunks)

        if len(page_chunks) > 1:
            logger(
                f"Calling Responses API for {len(page_chunks)} chunks with up to "
                f"{min(max_concurrency, len(page_chunks))} concurrent worker(s) ..."
            )

        def process_chunk(chunk_index: int, pages: Sequence[PageArtifact]) -> tuple[int, str]:
            raise_if_cancelled(cancel_callback)
            start_page = pages[0].page_number
            end_page = pages[-1].page_number
            cache_path = get_chunk_cache_path(chunk_cache_dir, chunk_index, start_page, end_page)
            if cache_path is not None and cache_path.is_file():
                logger(f"Using cached Markdown for chunk {chunk_index}/{len(page_chunks)}.")
                report_conversion_progress(
                    progress_callback,
                    "chunk",
                    f"Loaded cached chunk {chunk_index}/{len(page_chunks)}",
                    chunk_index,
                    len(page_chunks),
                )
                return chunk_index - 1, cache_path.read_text(encoding="utf-8")

            logger(
                f"Calling Responses API for chunk {chunk_index}/{len(page_chunks)} "
                f"(pages {start_page}-{end_page}) ..."
            )
            report_conversion_progress(
                progress_callback,
                "chunk",
                f"Calling API for chunk {chunk_index}/{len(page_chunks)}",
                chunk_index,
                len(page_chunks),
            )

            def handle_stream_progress(progress: StreamProgress) -> None:
                if stream_progress_callback is not None:
                    stream_progress_callback(chunk_index, len(page_chunks), start_page, end_page, progress)

            content = build_chunk_content(
                pdf_name=input_path.name,
                instructions=instructions,
                pages=pages,
            )
            chunk_output = call_responses_api(
                api_url=options.api_url,
                api_key=api_key,
                model=options.model,
                content=content,
                timeout=options.timeout,
                stream=options.stream,
                stream_progress_callback=handle_stream_progress if options.stream else None,
            )
            if cache_path is not None:
                cache_path.write_text(chunk_output.strip() + "\n", encoding="utf-8")
            logger(f"Completed chunk {chunk_index}/{len(page_chunks)}.")
            report_conversion_progress(
                progress_callback,
                "chunk",
                f"Completed chunk {chunk_index}/{len(page_chunks)}",
                chunk_index,
                len(page_chunks),
            )
            return chunk_index - 1, chunk_output

        if len(page_chunks) <= 1 or max_concurrency == 1:
            for chunk_index, pages in enumerate(page_chunks, start=1):
                raise_if_cancelled(cancel_callback)
                output_index, chunk_output = process_chunk(chunk_index, pages)
                chunk_outputs[output_index] = chunk_output
        else:
            with ThreadPoolExecutor(max_workers=min(max_concurrency, len(page_chunks))) as executor:
                futures = [
                    executor.submit(process_chunk, chunk_index, pages)
                    for chunk_index, pages in enumerate(page_chunks, start=1)
                ]
                for future in as_completed(futures):
                    raise_if_cancelled(cancel_callback)
                    output_index, chunk_output = future.result()
                    chunk_outputs[output_index] = chunk_output

        raise_if_cancelled(cancel_callback)
        if len(chunk_outputs) == 1:
            final_markdown = chunk_outputs[0]
        else:
            logger("Merging chunk outputs into the final Markdown document ...")
            report_conversion_progress(progress_callback, "merge", "Merging chunk outputs", 1, 1)
            merge_content = build_merge_content(
                pdf_name=input_path.name,
                instructions=instructions,
                chunk_outputs=chunk_outputs,
            )
            final_markdown = call_responses_api(
                api_url=options.api_url,
                api_key=api_key,
                model=options.model,
                content=merge_content,
                timeout=options.timeout,
                stream=options.stream,
            )

        raise_if_cancelled(cancel_callback)
        report_conversion_progress(progress_callback, "save", "Saving Markdown", 1, 1)
        final_output_path = write_markdown(options.output_path, final_markdown, options.overwrite_mode)
        if final_output_path is not None:
            logger(f"Saved Markdown to {final_output_path}")
            report_conversion_progress(progress_callback, "done", f"Saved Markdown to {final_output_path}", 1, 1)
        else:
            report_conversion_progress(progress_callback, "done", "Markdown written to stdout", 1, 1)
        return final_markdown
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def main() -> None:
    args = parse_args()
    convert_pdf_to_markdown(build_options_from_args(args))


if __name__ == "__main__":
    main()