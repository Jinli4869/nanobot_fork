---
created: 2026-03-20T02:44:44.490Z
title: Background GUI execution with user intervention handoff
area: agent
files:
  - opengui/agent.py
---

## Problem

当前 GUI 自动化操作在前台执行，占用用户的屏幕和交互焦点。用户希望 GUI 操作能在后台独立运行（类似新建一个虚拟桌面/窗口），仅在需要用户介入的场景（如支付、验证码、登录等）时通知用户，用户确认后再跳转到对应窗口/桌面进行操作。

核心需求：
1. **后台执行**：在独立的窗口/虚拟桌面中运行 GUI 自动化，不干扰用户当前工作
2. **用户介入通知**：识别需要人工操作的场景（支付、验证、登录等），主动通知用户
3. **窗口切换**：用户同意后，切换到自动化所在的窗口/桌面，完成人工操作后切回
4. **跨平台可行性**：需调研 macOS、Windows、Linux 上的实现方案差异

## Solution

需要调研以下方向：

**macOS**:
- Mission Control / Spaces API（虚拟桌面）
- 隐藏窗口 / offscreen rendering
- AppleScript / Accessibility API 控制桌面切换

**Windows**:
- Virtual Desktop API (Windows 10+)
- 隐藏桌面 / Session 0 isolation
- UI Automation in background sessions

**Linux**:
- Xvfb (X Virtual Framebuffer) — 最成熟的方案
- 多 X session / VNC-based approach
- Wayland compositor isolation

**通用方案**:
- Headless browser + VNC viewer for web scenarios
- Docker container with virtual display
- Remote desktop protocol based isolation

**用户介入机制**:
- Agent 识别支付/验证/登录等场景的 classifier
- 系统通知 API（跨平台）
- 窗口焦点切换 API
