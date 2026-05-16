# PDF2MD Workbench

PDF2MD Workbench is a desktop GUI for converting PDF, DOC, DOCX, PPT, and PPTX files into formatted Markdown through the Responses API.

It includes:

- A queue-based desktop GUI with drag-and-drop
- Batch processing with per-file status, progress, retry, and cancel
- Streaming token metrics during conversion
- Fetching the available model list directly from the configured API endpoint
- Testing the currently selected model before running a batch
- Optional chunk caching for resume and retry workflows
- Windows single-file packaging and macOS Apple Silicon app-plus-DMG packaging
- GitHub Actions builds for Windows and macOS ARM

## Main Files

- `pdf_to_formatted_markdown_gui.py`: desktop GUI application
- `pdf_to_formatted_markdown.py`: conversion pipeline and API workflow
- `pdf2md.config`: app config stored next to the executable on Windows and inside the macOS app bundle
- `pdf2md-gui.spec`: PyInstaller spec
- `build_pdf2md_gui.ps1`: local Windows build script
- `build_pdf2md_gui_macos_arm.sh`: local macOS ARM build script
- `.github/workflows/build-pdf2md-gui.yml`: CI build workflow

## Requirements

- Python 3.12 or newer recommended
- Windows:
  - Microsoft Office or LibreOffice for DOC, DOCX, PPT, PPTX to PDF conversion
- macOS / Linux:
  - LibreOffice for DOC, DOCX, PPT, PPTX to PDF conversion

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

## Run Locally

```bash
python pdf_to_formatted_markdown_gui.py
```

At first launch the app creates `pdf2md.config` if it does not exist.

After entering the API URL and token, use `Fetch Models` in the settings panel to load the remote model catalog, then use `Test Model` to verify the selected model before processing documents.

## Build Locally

### Windows

```powershell
.\build_pdf2md_gui.ps1
```

This produces:

- `dist/pdf2md-gui.exe`
- `dist/pdf2md.config`

### macOS Apple Silicon

```bash
chmod +x ./build_pdf2md_gui_macos_arm.sh
./build_pdf2md_gui_macos_arm.sh
```

This must run on an actual macOS arm64 machine. PyInstaller does not cross-build macOS apps from Windows.

This produces:

- `dist/pdf2md-gui.app`
- `dist/pdf2md-gui-macos-arm64.dmg`

The DMG contains the `.app` bundle plus an `Applications` shortcut so the app can be dragged into `/Applications` in the standard macOS install flow.

## GitHub Actions

The repository includes an Actions workflow that builds:

- Windows single-file exe on `windows-latest`
- macOS ARM DMG on `macos-14`

The workflow runs on:

- pushes to `main`
- version tags like `v1.0.0`
- manual dispatch

Build outputs are uploaded as workflow artifacts.

When you push a tag such as `v1.0.0`, the workflow also creates a GitHub Release automatically and uploads:

- `pdf2md-gui-windows-x64.zip`
- `pdf2md-gui-macos-arm64.dmg`

## Config

`pdf2md.config` stores:

- API URL and model
- cached model list fetched from the remote API
- output folder
- style reference path
- chunk cache directory
- overwrite strategy
- streaming and auto-crop settings

The `api_key` field is stored in plaintext if you save it in the GUI. You can also leave it blank and provide `ARK_API_KEY` through the environment.
