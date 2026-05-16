#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This build must run on macOS. PyInstaller cannot cross-build macOS apps from Windows or Linux." >&2
  exit 1
fi

if [[ "$(uname -m)" != "arm64" ]]; then
  echo "This script is intended for Apple Silicon arm64 hosts." >&2
  exit 1
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv-macos-arm}"

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip pyinstaller PyMuPDF tkinterdnd2
python -m compileall pdf_to_formatted_markdown.py pdf_to_formatted_markdown_gui.py
python -m PyInstaller --noconfirm --clean pdf2md-gui.spec

mkdir -p dist
cp pdf2md.config dist/pdf2md.config

if [[ ! -d "dist/pdf2md-gui.app" && ! -f "dist/pdf2md-gui" ]]; then
  echo "Build did not produce dist/pdf2md-gui.app or dist/pdf2md-gui" >&2
  exit 1
fi

du -sh dist/pdf2md-gui.app 2>/dev/null || true
ls -lh dist/pdf2md-gui* dist/pdf2md.config