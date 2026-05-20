<div align="center">

# PDF2MD Workbench

<p align="center">
  面向 Responses API 的桌面批处理工作台，用于将 PDF、DOC、DOCX、PPT、PPTX 转换为高质量 Markdown。
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
<summary>PDF2MD Workbench — 面向 API 工作流的队列式 Markdown 转换桌面工具</summary>

将 PDF 与 Office 文档转换为更干净、更适合下游使用的 Markdown，并提供桌面 GUI、批处理、重试、缓存、模型发现与发布打包能力。

**核心流程**

- 将 `PDF`、`DOC`、`DOCX`、`PPT`、`PPTX` 文件拖入队列批量处理
- 先在本地把 Office 文件转换为 PDF，再交给 Responses API 生成 Markdown
- 在桌面端查看每个文件的状态、进度、流式指标、错误与输出路径

**桌面体验**

- 提供队列视图、失败重试、取消、预检、打开输出、打开配置
- 支持从配置的 API 端点拉取模型列表并测试模型
- 支持 chunk cache、覆盖策略、流式输出、渲染参数、参考样式等设置

**打包能力**

- Windows 单文件 `.exe`
- macOS Apple Silicon `.app` + 可拖拽安装 `.dmg`
- GitHub Actions 构建与按 tag 自动发布 release

</details>

# 项目简介

PDF2MD Workbench 是一个桌面 GUI，用于通过 Responses API 将 `PDF`、`DOC`、`DOCX`、`PPT`、`PPTX` 转换为更适合阅读、发布和下游处理的 Markdown。

这个项目更强调最终 Markdown 的输出质量，而不是本地原生解析覆盖面。它面向那些更关心数学公式格式、逻辑表格结构和长文内容重组质量的工作流，适合 LLM、RAG、知识整理与技术文档生产场景。

相较于 MinerU 这类偏“本地原生解析”的工具，PDF2MD Workbench 的定位是 API-first 的输出工作台。它更关注公式较多、表格逻辑较强的内容在最终 Markdown 结果中的呈现质量与可控性，而不是宣称更广泛的离线原生理解能力。

应用当前采用两阶段流程：

1. 先在本地把 Office 文件转换成 PDF。
2. 再把 PDF 页面与提取文本发送到配置好的 Responses API，最终重组为 Markdown。

# 主要特性

- 支持 `PDF`、`DOC`、`DOCX`、`PPT`、`PPTX` 输入
- 队列式桌面 GUI，支持拖拽与批处理
- 每个文件都有独立进度、状态、token 指标、重试与取消能力
- 支持从 API 基础地址自动发现可用模型
- 支持在正式批处理前测试当前模型
- 支持 chunk cache 以便重试和恢复
- 支持 `rename`、`overwrite`、`fail` 三种输出冲突策略
- 支持页面图像自动裁边
- 支持 Windows 单文件打包与 macOS arm64 DMG 打包
- 支持 GitHub Actions 自动构建与 release 发布

# 平台支持

| 平台 | 源码运行 | 发布产物 | Office 转 PDF 依赖 |
|------|----------|----------|--------------------|
| Windows | 支持 | `pdf2md-gui.exe` | Microsoft Office 或 LibreOffice |
| macOS arm64 | 支持 | `pdf2md-gui-macos-arm64.dmg` | LibreOffice |
| Linux | 支持 | 当前无预编译发布 | LibreOffice |

说明：

- 纯 PDF 输入不依赖 Office 转换软件
- `DOC`、`DOCX`、`PPT`、`PPTX` 需要本地 Office-to-PDF 后端
- macOS 打包版会主动检查常见 LibreOffice 路径，因为 Finder 启动的应用通常拿不到 shell 的 `PATH`

# 快速开始

## 下载发布版

当前 release 提供：

- Windows: `pdf2md-gui-windows-x64.zip`
- macOS Apple Silicon: `pdf2md-gui-macos-arm64.dmg`

下载地址： [GitHub Releases](https://github.com/Purestreams/pdf2md-workbench/releases)

## 从源码运行

安装依赖：

```bash
python -m pip install -r requirements.txt
```

启动 GUI：

```bash
python pdf_to_formatted_markdown_gui.py
```

## 典型使用流程

1. 启动应用。
2. 填写 API URL 与 API Token。
3. 点击 `Fetch Models` 拉取远端模型列表。
4. 点击 `Test Model` 验证当前模型可用。
5. 拖入文件或通过文件选择器添加任务。
6. 如有需要，先执行 `Preflight` 预检。
7. 开始批处理，并在队列与日志页中查看进度。

# Office 转换依赖

Office 文件在发送给 API 之前，需要先在本地转换为 PDF。

## Windows

- 支持 Microsoft Office COM 或 LibreOffice
- LibreOffice 下载地址： https://www.libreoffice.org/download/download-libreoffice/
- 常见 LibreOffice 路径： `C:\Program Files\LibreOffice\program\soffice.exe`

## macOS

- `DOC`、`DOCX`、`PPT`、`PPTX` 需要 LibreOffice
- 下载地址： https://www.libreoffice.org/download/download-libreoffice/
- Homebrew 安装：

```bash
brew install --cask libreoffice
```

- 应用会检查这些常见路径：
  - `/Applications/LibreOffice.app/Contents/MacOS/soffice`
  - `~/Applications/LibreOffice.app/Contents/MacOS/soffice`
  - `/opt/homebrew/bin/soffice`
  - `/usr/local/bin/soffice`

如果 LibreOffice 安装在别处，可以设置 `PDF2MD_SOFFICE_PATH` 指向完整 `soffice` 路径。

## Linux

- 需要 LibreOffice
- 请确保 `soffice` 在 `PATH` 中，或设置 `PDF2MD_SOFFICE_PATH`

# 本地构建

## Windows

```powershell
.\build_pdf2md_gui.ps1
```

输出：

- `dist/pdf2md-gui.exe`

## macOS Apple Silicon

```bash
chmod +x ./build_pdf2md_gui_macos_arm.sh
./build_pdf2md_gui_macos_arm.sh
```

输出：

- `dist/pdf2md-gui.app`
- `dist/pdf2md-gui-macos-arm64.dmg`

DMG 中包含 `.app` 与 `Applications` 快捷方式，符合标准 macOS 拖拽安装流程。

# GitHub Actions 与 Release

仓库中的 workflow 会在以下场景构建：

- push 到 `main`
- push 版本 tag，例如 `v0.2.3`
- 手动触发 workflow_dispatch

当前 CI 产物：

- Windows 单文件执行包
- macOS Apple Silicon DMG

当推送 tag 时，GitHub Actions 会自动发布 GitHub Release。

# 配置文件

应用使用 `pdf2md.config` 保存设置。

配置位置：

- Windows 源码版与打包版： `%APPDATA%\PDF2MD Workbench\pdf2md.config`
- macOS 源码版与打包版： `~/Library/Application Support/PDF2MD Workbench/pdf2md.config`

如果旧版配置文件仍在脚本或可执行文件旁边，应用会在首次启动时自动迁移到用户目录。

主要配置项包括：

- API URL
- API Token
- 当前模型与缓存的模型列表
- 输出目录
- 参考样式路径
- chunk cache 目录
- 覆盖策略
- 渲染与流式选项

安全说明：

- 如果你在 GUI 中保存 API key，它会以明文形式写入配置文件
- 也可以把 GUI 里的 key 留空，通过环境变量 `ARK_API_KEY` 提供

# 环境变量

- `ARK_API_KEY`: 可选 API Token 覆盖
- `PDF2MD_SOFFICE_PATH`: 手动指定 `soffice` 路径

# 仓库结构

- `pdf_to_formatted_markdown_gui.py`: 桌面 GUI 应用
- `pdf_to_formatted_markdown.py`: 转换管线与 API 逻辑
- `pdf2md-gui.spec`: PyInstaller 打包配置
- `build_pdf2md_gui.ps1`: Windows 构建脚本
- `build_pdf2md_gui_macos_arm.sh`: macOS arm64 构建脚本
- `.github/workflows/build-pdf2md-gui.yml`: CI 与 release workflow

# 常见问题

## Office 文件在转换前就失败

请先在 GUI 中执行 `Preflight`，确认应用能找到 Microsoft Office 或 LibreOffice。

## macOS 找不到 LibreOffice

如果你的安装路径不在标准位置，请设置 `PDF2MD_SOFFICE_PATH`。

## API 调用失败或模型列表为空

请检查 API URL、Token、timeout 与当前模型，并在批处理前先执行 `Test Model`。

## 输出 Markdown 被意外覆盖

请把设置中的 overwrite 策略改成 `rename` 或 `fail`。

# License

本项目遵循仓库当前公开发布的 license 与 release 条款。如果你希望 GitHub 在仓库头部明确展示许可证，请补充顶层 `LICENSE` 文件并在此处链接。