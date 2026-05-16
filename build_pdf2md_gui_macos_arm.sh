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
python -m pip install --upgrade pip certifi pyinstaller PyMuPDF tkinterdnd2
python -m compileall pdf_to_formatted_markdown.py pdf_to_formatted_markdown_gui.py
python -m PyInstaller --noconfirm --clean pdf2md-gui.spec

mkdir -p dist
APP_PATH="dist/pdf2md-gui.app"
DMG_NAME="pdf2md-gui-macos-arm64.dmg"
DMG_PATH="dist/$DMG_NAME"
DMG_STAGING_DIR="dist/dmg-staging"

if [[ ! -d "$APP_PATH" ]]; then
  echo "Build did not produce $APP_PATH" >&2
  exit 1
fi

cp pdf2md.config "$APP_PATH/Contents/MacOS/pdf2md.config"

rm -rf "$DMG_STAGING_DIR"
mkdir -p "$DMG_STAGING_DIR"
cp -R "$APP_PATH" "$DMG_STAGING_DIR/"
ln -s /Applications "$DMG_STAGING_DIR/Applications"
rm -f "$DMG_PATH"
hdiutil create \
  -volname "PDF2MD Workbench" \
  -srcfolder "$DMG_STAGING_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

du -sh "$APP_PATH" 2>/dev/null || true
ls -lh "$APP_PATH" "$DMG_PATH"