---
created: 2026-03-20T02:44:44.490Z
title: Background GUI execution with user intervention handoff
area: agent
files:
  - opengui/agent.py
  - opengui/backends/desktop.py
  - opengui/backends/adb.py
  - opengui/action.py
  - opengui/trajectory/recorder.py
  - opengui/interfaces.py
---

## Problem

当前 GUI 自动化操作在前台执行，占用用户的屏幕和交互焦点。用户希望 GUI 操作能在后台独立运行（类似新建一个虚拟桌面/窗口），仅在需要用户介入的场景（如支付、验证码、登录等）时通知用户，用户确认后再跳转到对应窗口/桌面进行操作。

核心需求：
1. **后台执行**：在独立的窗口/虚拟桌面中运行 GUI 自动化，不干扰用户当前工作
2. **用户介入通知**：识别需要人工操作的场景（支付、验证、登录等），主动通知用户
3. **窗口切换**：用户同意后，切换到自动化所在的窗口/桌面，完成人工操作后切回
4. **跨平台可行性**：需调研 macOS、Windows、Linux、Android 上的实现方案差异

## Feasibility Research (completed 2026-03-20)

### 结论：四平台均可行，各有最佳方案

| 平台 | 推荐方案 | 可行性 | 成熟度 | 限制 |
|------|---------|--------|--------|------|
| **macOS** | CGVirtualDisplay (macOS 13+) | 完全可行 | 半公开API | 需 Screen Recording 权限；旧版需 HDMI dummy plug |
| **Windows** | CreateDesktop (Win32 API) | 完全可行 | 稳定 (NT至今) | 无 DWM 合成，UWP/DirectX 应用渲染受限 |
| **Windows (备选)** | RDP Loopback | 完全可行 | 稳定 | 需 Pro+；并发会话需 RDP Wrapper |
| **Linux** | Xvfb + xdotool | 完全可行 | 生产级 | 无 GPU 加速；Wayland 工具链不成熟 |
| **Android** | ADB (天然后台) | 完全可行 | 生产级 | 介入时需用户解锁设备 |

---

### macOS: CGVirtualDisplay

**原理：** macOS 13+ 提供 `CGVirtualDisplay` API，可编程创建虚拟显示器（系统级真实显示器），WindowServer 会完整渲染该显示器上的窗口。

**工作流程：**
1. 创建 1920x1080 虚拟显示器
2. 将目标应用窗口移动到虚拟显示器 (`CGSMoveWindowToManagedSpace`)
3. 通过 `mss` (选择虚拟显示器索引) 或 `screencapture -D N` 截图
4. 通过 `CGEventPost` 发送输入事件（坐标偏移至虚拟显示器的全局坐标）

**关键点：**
- 虚拟显示器是 macOS 的"真实"显示器 → 窗口完整渲染、输入事件正常路由
- 用户物理屏幕完全不受影响
- 需要 Accessibility 权限 (输入事件) + Screen Recording 权限 (截图)
- 不需要禁用 SIP
- 备选：HDMI dummy plug ($5-10) 适用于旧版 macOS

**对 codebase 的影响：**
- `backends/desktop.py` 的 `observe()` 需支持指定显示器索引 (`sct.monitors[N]`)
- `execute()` 的坐标系需要偏移到虚拟显示器的全局坐标原点

**排除的方案：**
- Spaces API：私有 API + 非活动 Space 上事件不路由 → 不可行
- 窗口隐藏/离屏：macOS 不渲染隐藏窗口 → 截图为空 → 不可行

---

### Windows: CreateDesktop (Hidden Desktop)

**原理：** Win32 的 `CreateDesktop` API 创建独立的桌面对象，拥有独立的窗口层级、输入队列和显示面。

**工作流程：**
1. `CreateDesktop("AutomationDesktop")` 创建隐藏桌面
2. `CreateProcess` 时指定 `STARTUPINFO.lpDesktop = "WinSta0\\AutomationDesktop"`
3. 自动化线程通过 `SetThreadDesktop` 附加到隐藏桌面
4. 在该线程上调用 `SendInput` → 事件路由到隐藏桌面的输入队列
5. 截图通过 `PrintWindow` 或 `BitBlt` (线程附加后 `GetDC(NULL)`)

**关键点：**
- 用户桌面完全不受影响（不调用 `SwitchDesktop`）
- 所有 Windows 版本均支持（Home/Pro/Enterprise）
- 无需管理员权限
- **限制：** 无 DWM 合成 → UWP、DirectX、GPU 加速的 Electron 应用可能渲染异常

**备选 - RDP Loopback：**
- 完整 DWM/GPU 支持，所有应用类型正常
- 需 Pro+ 版 + RDP Wrapper
- 资源开销较大 (200-500+ MB)

---

### Linux: Xvfb + xdotool

**原理：** Xvfb 是 X11 协议的纯内存实现，创建完全独立的虚拟屏幕。

**工作流程：**
1. `Xvfb :99 -screen 0 1920x1080x24 &`
2. `DISPLAY=:99 target-app &`
3. `DISPLAY=:99 xdotool mousemove/click/type ...`
4. `DISPLAY=:99 import -window root screenshot.png`

**关键点：**
- CI/CD 系统的黄金标准方案（Jenkins, GitHub Actions, Selenium 等）
- 用户桌面完全隔离（不同 DISPLAY 编号，零串扰）
- 可选 VNC 层实时观察 (`x11vnc -display :99`)
- Docker 容器化部署成熟
- **限制：** 无 GPU 加速；Wayland 不成熟

---

### Android: ADB 天然后台

**原理：** Android 的 ADB 后端天然支持后台操作——所有 `adb shell` 命令在主机上执行，不占用主机屏幕。GUI 操作发生在 Android 设备/模拟器上。

**工作流程（已有实现基础）：**
1. `adb shell screencap -p` → 截图（设备屏幕）
2. `adb shell input tap x y` → 点击
3. `adb shell input text "..."` → 输入
4. `adb shell input swipe ...` → 滑动

**后台模式细节：**

| 场景 | 方案 | 用户干扰 |
|------|------|---------|
| 物理设备（屏幕亮着） | 操作在设备上执行，主机不受影响 | 设备屏幕会显示操作过程 |
| 物理设备（屏幕关闭） | `adb shell input keyevent KEYCODE_WAKEUP` 唤醒 → 操作 → 可选熄屏 | 设备需解锁；部分操作在锁屏下受限 |
| Android 模拟器 | 模拟器窗口可最小化/后台运行 | 无干扰 |
| 模拟器 headless 模式 | `emulator -no-window -no-audio` | 完全无干扰 |
| scrcpy 镜像 | 主机窗口实时镜像设备屏幕，可用于观察 | 可选观察 |

**用户介入 Handoff 特殊性：**
- 需要介入时，发送通知到主机 + 可选 `scrcpy` 弹出镜像窗口
- 用户在物理设备上操作（或通过 scrcpy 在主机操作）
- 介入完成后 agent 重新 `observe()` 继续

**已有 codebase 支持：**
- `backends/adb.py` 已实现完整的 ADB 后端
- `observe()` 使用 `adb shell screencap`
- `execute()` 使用 `adb shell input`
- 天然满足"后台执行"需求，主要需要补充介入检测和通知机制

---

### 用户介入检测与通知机制

#### 检测策略（推荐分层方案）

**Layer 1 - LLM 分类（主要）：**
- 扩展 `action_type` 枚举，增加 `request_intervention`
- 系统 prompt 指示模型在检测到支付/验证码/登录时调用此 action
- 零额外推理开销（模型已在分析每帧截图）
- 集成点：`_run_step()` 中 `action_type == "done"` 同级处理

**Layer 2 - 确定性策略门控（辅助）：**
- `InterventionPolicy` 协议，在 `backend.execute()` 前拦截检查
- 规则：密码字段 input_text、支付确认按钮、OTP 输入等

**Layer 3 - 视觉模式识别（补充）：**
- CAPTCHA 检测（reCAPTCHA/hCaptcha 模板匹配）
- 登录表单检测（OCR 识别 "Sign In"/"Log In"）

**Layer 4 - 超时/不确定性检测：**
- 重复动作检测（连续 2-3 次相同 action_summary）
- 屏幕无变化检测（感知哈希比较连续截图）

#### 通知机制

| 层级 | 方案 | 覆盖平台 |
|------|------|---------|
| 终端 | `print("\a")` + 文本输出 | 全平台 |
| 桌面通知 | `desktop-notifier` (支持操作按钮, async) | macOS/Windows/Linux |
| 远程/无头 | Webhook 回调 (Slack/Discord/HTTP) | 全平台 |

#### 窗口切换 Handoff

**桌面平台：**
- 暂停时记录当前前台应用 (已有 `_query_foreground_app()`)
- 介入时切换到自动化窗口/桌面 → 用户操作 → 切回
- 恢复时 `observe()` 获取最新截图 → 继续步骤循环

**Android 平台：**
- 暂停时发送主机桌面通知
- 可选弹出 scrcpy 窗口让用户在主机上操作设备
- 或提示用户直接在物理设备上操作
- 恢复时重新 `adb shell screencap` 获取最新状态

#### 安全要求

- Agent 永远不自动填充密码/支付信息
- 人工介入期间停止截图（防止凭证泄露）
- 扩展 `_scrub_for_log` 过滤敏感 `input_text` 内容
- 所有介入事件记录到 trajectory (`record_event("intervention_requested", ...)`)
- 每次介入需用户显式确认，超时不自动恢复（fail-safe）

---

## Implementation Roadmap

### Phase 1: 后台执行基础设施
- 新建 `opengui/backends/virtual_display.py`
- 实现 `VirtualDisplayManager` 协议 + macOS/Windows/Linux 实现
- `DesktopBackend` 增加 `background_mode` 参数
- Android: 模拟器 headless 模式支持 (`emulator -no-window`)

### Phase 2: 介入检测
- `action.py` 增加 `request_intervention` action type
- `prompts/system.py` 增加介入检测指令
- `agent.py` `_run_step()` 处理介入暂停逻辑
- `InterventionPolicy` 确定性策略层

### Phase 3: 通知与 Handoff
- `opengui/notification.py` — 跨平台通知
- `InterventionHandler` 协议 (interfaces.py)
- 窗口焦点保存/恢复（桌面）/ scrcpy 弹出（Android）
- trajectory 记录介入事件

### Phase 4: 安全加固
- 截图 redaction / 介入期间暂停截图
- 凭证相关 action 强制拦截
- 审计日志完善
