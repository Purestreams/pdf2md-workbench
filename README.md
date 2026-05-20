<div align="center">

# PDF2MD Workbench

<p align="center">
  Desktop batch conversion workbench for turning PDF, DOC, DOCX, PPT, and PPTX files into formatted Markdown through the Responses API.
</p>

[English](README.md) | [简体中文](README_zh-CN.md)

[![Release](https://img.shields.io/github/v/release/Purestreams/pdf2md-workbench)](https://github.com/Purestreams/pdf2md-workbench/releases)
[![Build](https://img.shields.io/github/actions/workflow/status/Purestreams/pdf2md-workbench/build-pdf2md-gui.yml?branch=main&label=build)](https://github.com/Purestreams/pdf2md-workbench/actions/workflows/build-pdf2md-gui.yml)
[![Stars](https://img.shields.io/github/stars/Purestreams/pdf2md-workbench.svg)](https://github.com/Purestreams/pdf2md-workbench)
[![Issues](https://img.shields.io/github/issues-raw/Purestreams/pdf2md-workbench)](https://github.com/Purestreams/pdf2md-workbench/issues)

<p align="center">
  <a href="https://github.com/Purestreams/pdf2md-workbench/releases">Releases</a> ·
  <a href="https://github.com/Purestreams/pdf2md-workbench/actions/workflows/build-pdf2md-gui.yml">GitHub Actions</a> ·
  <a href="https://github.com/Purestreams/pdf2md-workbench/issues">Issues</a>
</p>

</div>

<img width="1518" height="838" alt="PDF2MD Workbench screenshot" src="https://github.com/user-attachments/assets/093ad210-09bc-4a73-b42f-79ffa6b5b416" />

<details>
<summary>PDF2MD Workbench — Queue-based desktop Markdown conversion for API-driven workflows</summary>

Converts PDF and Office documents into cleaned Markdown with a desktop GUI designed for batch processing, retries, caching, model discovery, and release packaging.

**Core workflow**

- Drag in `PDF`, `DOC`, `DOCX`, `PPT`, or `PPTX` files and process them as a queue
- Convert Office files to PDF first, then send content through the Responses API
- Review per-file status, progress, stream metrics, errors, and output paths

**Desktop experience**

- Queue view with retry, cancel, preflight checks, output opening, and config opening
- Built-in model list fetching and test request support for the configured endpoint
- Settings for chunk cache, overwrite strategy, streaming, rendering, and style reference

**Packaging**

- Windows single-file `.exe`
- macOS Apple Silicon `.app` bundled inside a drag-to-Applications `.dmg`
- GitHub Actions build and tag-driven release publishing

</details>

# Project Introduction

PDF2MD Workbench is a desktop GUI for converting `PDF`, `DOC`, `DOCX`, `PPT`, and `PPTX` files into publication-style Markdown through a Responses API endpoint.

It is built for teams who care less about raw document parsing breadth and more about the quality of the final Markdown output: cleaner mathematical formulas, more logically coherent tables, and more controllable long-form restructuring for downstream LLM, RAG, and publishing workflows.

Compared with native local parsers such as MinerU, PDF2MD Workbench is positioned as an API-first output workbench. Its emphasis is not broad offline document understanding, but higher-fidelity final Markdown generation for formula-heavy and logic-sensitive content.

The application uses a two-stage workflow:

1. Office files are converted to PDF locally.
2. PDF pages and extracted text are sent to the configured Responses API and reassembled into Markdown.

# Key Features

- Support for `PDF`, `DOC`, `DOCX`, `PPT`, and `PPTX` inputs
- Queue-based desktop GUI with drag-and-drop and batch processing
- Per-file progress, status, token metrics, retry, and cancellation
- Model catalog fetch from the configured API base URL
- Test request for the selected model before a batch starts
- Chunk cache support for retry and resume workflows
- Output conflict handling with `rename`, `overwrite`, and `fail` modes
- Optional image auto-cropping for cleaner page renders
- Windows single-file packaging and macOS arm64 DMG packaging
- GitHub Actions builds for Windows and macOS releases

# Platform Matrix

| Platform | Source Run | Release Artifact | Office Conversion Requirement |
|----------|------------|------------------|-------------------------------|
| Windows | Yes | `pdf2md-gui.exe` | Microsoft Office or LibreOffice |
| macOS arm64 | Yes | `pdf2md-gui-macos-arm64.dmg` | LibreOffice |
| Linux | Yes | No packaged artifact currently | LibreOffice |

Notes:

- PDF input works without Office conversion software.
- `DOC`, `DOCX`, `PPT`, and `PPTX` require a local Office-to-PDF backend.
- On macOS, the packaged app checks common LibreOffice paths because Finder-launched apps often do not inherit your shell `PATH`.

# Quick Start

## Download a Release

Prebuilt artifacts are published on tagged releases:

- Windows: `pdf2md-gui-windows-x64.zip`
- macOS Apple Silicon: `pdf2md-gui-macos-arm64.dmg`

Download them from the [GitHub Releases page](https://github.com/Purestreams/pdf2md-workbench/releases).

## Run From Source

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Launch the GUI:

```bash
python pdf_to_formatted_markdown_gui.py
```

## Typical Workflow

1. Launch the app.
2. Enter the API URL and API token.
3. Click `Fetch Models` to load the remote model list.
4. Click `Test Model` to verify the selected model.
5. Drag in files or add them through the file picker.
6. Run `Preflight` if you want a quick environment check.
7. Start the batch and monitor progress in the queue and log tabs.

# Office Conversion Requirements

Office files are converted locally before they are sent to the API.

## Windows

- Supported backends: Microsoft Office COM automation or LibreOffice
- LibreOffice download: https://www.libreoffice.org/download/download-libreoffice/
- Common LibreOffice path: `C:\Program Files\LibreOffice\program\soffice.exe`

## macOS

- LibreOffice is required for `DOC`, `DOCX`, `PPT`, and `PPTX`
- Download from: https://www.libreoffice.org/download/download-libreoffice/
- Homebrew option:

```bash
brew install --cask libreoffice
```

- Common paths checked by the app:
  - `/Applications/LibreOffice.app/Contents/MacOS/soffice`
  - `~/Applications/LibreOffice.app/Contents/MacOS/soffice`
  - `/opt/homebrew/bin/soffice`
  - `/usr/local/bin/soffice`

If LibreOffice is installed elsewhere, set `PDF2MD_SOFFICE_PATH` to the full `soffice` path.

## Linux

- LibreOffice is required
- Ensure `soffice` is available on `PATH`, or set `PDF2MD_SOFFICE_PATH`

# Build Locally

## Windows

```powershell
.\build_pdf2md_gui.ps1
```

Outputs:

- `dist/pdf2md-gui.exe`
- `dist/pdf2md.config`

## macOS Apple Silicon

```bash
chmod +x ./build_pdf2md_gui_macos_arm.sh
./build_pdf2md_gui_macos_arm.sh
```

Outputs:

- `dist/pdf2md-gui.app`
- `dist/pdf2md-gui-macos-arm64.dmg`

The DMG contains the `.app` plus an `Applications` shortcut for the normal drag-to-install macOS flow.

# GitHub Actions and Releases

The repository includes a workflow that builds on:

- pushes to `main`
- version tags such as `v0.2.3`
- manual workflow dispatch

Current CI outputs:

- Windows single-file executable archive
- macOS Apple Silicon DMG

When a tag is pushed, GitHub Actions publishes a GitHub Release automatically.

# Configuration

The app stores settings in `pdf2md.config`.

Config location:

- Windows source and packaged builds: next to the script or executable
- macOS packaged builds: `~/Library/Application Support/PDF2MD Workbench/pdf2md.config`

Stored settings include:

- API URL
- API token
- selected model and cached known models
- output directory
- style reference path
- chunk cache directory
- overwrite mode
- render and streaming options

Security note:

- If you save the API key in the GUI, it is stored in plaintext in the config file.
- You can leave the field empty and provide `ARK_API_KEY` through the environment instead.

# Environment Variables

- `ARK_API_KEY`: optional API token override
- `PDF2MD_SOFFICE_PATH`: explicit path to `soffice` when it is not discoverable automatically

# Repository Layout

- `pdf_to_formatted_markdown_gui.py`: desktop GUI application
- `pdf_to_formatted_markdown.py`: conversion pipeline and API logic
- `pdf2md-gui.spec`: PyInstaller spec
- `build_pdf2md_gui.ps1`: Windows build script
- `build_pdf2md_gui_macos_arm.sh`: macOS arm64 build script
- `.github/workflows/build-pdf2md-gui.yml`: CI and release workflow

# Troubleshooting

## Office files fail before conversion starts

Run `Preflight` in the GUI and confirm that the app can find Microsoft Office or LibreOffice.

## macOS app cannot find LibreOffice

Set `PDF2MD_SOFFICE_PATH` to the full `soffice` path if your installation is outside the standard locations.

## API calls fail or model fetching is empty

Check the API URL, token, timeout, and selected model, then use `Test Model` before starting a full batch.

## Existing Markdown files are being overwritten unexpectedly

Set the overwrite strategy to `rename` or `fail` in the settings tab.

# License

This project follows the repository's current published license and release terms. If you want GitHub to surface the license explicitly in the repository header, add a top-level `LICENSE` file and link it here.

