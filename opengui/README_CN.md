# OpenGUI

OpenGUI 是一个基于视觉的 GUI 自动化引擎。它对当前屏幕截图，交由大模型决定下一步操作，执行后再次截图，如此循环直到任务完成。支持 Android（通过 ADB）、iOS（通过 WebDriverAgent）、鸿蒙 OS（通过 HDC）、桌面端（macOS / Linux / Windows）以及 dry-run 测试模式。

OpenGUI 有两种使用方式：

- **独立 CLI** — 直接运行 `opengui` 命令，搭配 YAML 配置文件
- **nanobot GUI 子智能体** — OpenGUI 作为工具内嵌于 nanobot，可通过任意 nanobot 渠道（TUI、Gateway、MCP 等）调用

---

## 目录

1. [安装](#安装)
2. [独立 CLI](#独立-cli)
   - [配置文件](#配置文件-homeopengui-configyaml)
   - [命令行参数](#命令行参数)
   - [使用示例](#使用示例)
   - [各平台注意事项](#各平台注意事项)
3. [nanobot 集成](#nanobot-集成)
   - [启动 nanobot](#启动-nanobot)
   - [nanobot config.json](#nanobot-configjson)
   - [gui 配置项说明](#gui-配置项说明)
   - [切换后端](#切换后端)
   - [各平台配置示例](#各平台配置示例)
4. [Planner / Router 路由集成](#planner--router-路由集成)
5. [App 列表初始化](#app-列表初始化)
6. [记忆库](#记忆库)
7. [后端](#后端)
8. [技能系统](#技能系统)

---

## 安装

```bash
# 正式版
pip install nanobot-ai

# 源码开发版
pip install -e .

# 推荐：使用 uv
uv tool install nanobot-ai
```

各平台依赖会自动安装。macOS 需要 `pyobjc` 无障碍访问组件，已随包附带，无需额外操作。

**iOS 后端**需额外安装 `facebook-wda`：

```bash
pip install facebook-wda
```

---

## 独立 CLI

`opengui` 命令可在无需启动 nanobot 的情况下独立执行 GUI 任务。

### 配置文件（`~/.opengui/config.yaml`）

CLI 默认读取 `~/.opengui/config.yaml`，可通过 `--config <路径>` 覆盖。

**最简配置（阿里云百炼/通义 DashScope）：**

```yaml
provider:
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  model: "qwen3.5-plus"
  api_key: "sk-..."          # 在 console.aliyun.com 创建 API Key
```

**完整配置（含所有选项）：**

```yaml
# 大模型提供商（必填）
# DashScope OpenAI 兼容端点
provider:
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  model: "qwen3.5-plus"
  api_key: "sk-..."

# Embedding 提供商（可选）
# 不填则技能检索降级为 BM25 关键词匹配
embedding:
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  model: "text-embedding-v4"
  api_key: "sk-..."          # 不填则使用 provider.api_key

# ADB 配置（仅 Android 后端需要）
adb:
  serial: null               # null = 自动选择第一台连接的设备
  adb_path: "adb"            # adb 可执行文件路径，不在 $PATH 中时需填写

# iOS / WebDriverAgent 配置（仅 iOS 后端需要）
ios:
  wda_url: "http://localhost:8100"   # WDA 服务器地址

# HDC 配置（仅鸿蒙 OS 后端需要）
hdc:
  serial: null               # null = 自动选择第一台连接的设备
  hdc_path: "hdc"            # hdc 可执行文件路径，不在 $PATH 中时需填写

# 执行步数限制
max_steps: 15

# 持久化存储路径（默认值如下）
memory_dir: "~/.opengui/memory"
skills_dir: "~/.opengui/skills"

# 无头虚拟显示（仅 Linux；需安装 Xvfb）
background: false
background_config:
  display_num: 99
  width: 1280
  height: 720
```

> **获取 DashScope API Key：** 登录[阿里云控制台](https://dashscope.console.aliyun.com/) → API Key 管理 → 创建 API Key。

### 命令行参数

```
opengui [任务描述] [选项]

位置参数：
  任务描述                  任务描述文本（也可用 --task 传入）

选项：
  --task TEXT             任务描述（与位置参数等效）
  --backend {adb,ios,hdc,local,dry-run}
                          执行后端（默认：local）
  --dry-run               等同于 --backend dry-run
  --agent-profile {default,general_e2e,qwen3vl,mai_ui,gelab,seed}
                          GUI 专用模型的 prompt / action profile
  --config PATH           配置文件路径（默认：~/.opengui/config.yaml）
  --refresh-apps          强制重新获取并缓存已安装 App 列表
  --background            使用 Xvfb 虚拟显示运行（仅 Linux）
  --require-isolation     若无法使用隔离后端则报错退出
  --target-app-class {classic-win32,uwp,directx,gpu-heavy,electron-gpu}
                          Windows 应用类型提示（用于后台隔离截图）
  --display-num INT       Xvfb 显示编号（默认：99）
  --width INT             虚拟显示宽度，像素（默认：1280）
  --height INT            虚拟显示高度，像素（默认：720）
  --json                  以 JSON 格式输出结果
```

### 使用示例

```bash
# 控制本地桌面（默认）
opengui "打开浏览器，访问 github.com"

# 通过 ADB 控制 Android 设备
opengui --backend adb "打开设置，开启 Wi-Fi"

# 通过 WebDriverAgent 控制 iOS 设备
opengui --backend ios "打开设置，查看 iOS 版本"

# 通过 HDC 控制鸿蒙 OS 设备
opengui --backend hdc "打开设置，开启蓝牙"

# 在 Linux CI 上无头运行
opengui --backend local --background "对桌面截图"

# Dry-run 模式（不执行真实操作，用于测试配置）
opengui --dry-run "点击保存按钮"

# 使用非默认 GUI profile
opengui --backend adb --agent-profile qwen3vl "打开设置，开启 Wi-Fi"

# 强制刷新 App 列表后执行任务
opengui --backend adb --refresh-apps "打开微信"

# 使用自定义配置文件
opengui --config ~/my-config.yaml "打开计算器"
```

### 支持的 GUI agent profile

当你的 GUI 模型不是原生 OpenAI tool-calling，而是要求特定 prompt / action 格式时，就需要显式指定 profile。

| Profile | 适用场景 | 期望的动作格式 |
|---------|----------|----------------|
| `default` | 原生 OpenAI-style tool calling | 原生 `computer_use` tool call |
| `general_e2e` | MobileWorld `general_e2e` / `planner_executor` 风格 agent | 纯文本里的 `Action: { ... }` JSON |
| `qwen3vl` | Qwen3VL 风格 GUI agent | `<tool_call>...</tool_call>` JSON 块 |
| `mai_ui` | MAI-UI 风格 GUI agent | `<tool_call>...</tool_call>` JSON 块 |
| `gelab` | Gelab 风格 GUI agent | 推理后输出 tab 分隔动作行 |
| `seed` | Seed GUI XML 风格 agent | `<tool_call>` 内的 XML-like function block |

说明：

- 优先使用上表中的 canonical profile 名称。
- `planner_executor` 在配置驱动的路径里会被当作 `general_e2e` 的别名处理，但 CLI 参数请直接写 `general_e2e`。
- 如果不填写 profile，OpenGUI 默认使用 `default`，也就是原生 tool calling。

### 在独立 OpenGUI 中设置 profile

临时执行时，可以直接通过 CLI 指定：

```bash
opengui --backend adb --agent-profile qwen3vl "打开设置，开启 Wi-Fi"
```

如果你会长期使用同一种 profile，建议写进 `~/.opengui/config.yaml`：

```yaml
provider:
  base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
  model: qwen-vl-max
  api_key: ${DASHSCOPE_API_KEY}

agent_profile: qwen3vl
adb:
  serial: emulator-5554
```

### 各平台注意事项

| 平台 | 后端 | 说明 |
|------|------|------|
| macOS | `local` | 需要无障碍权限：**系统设置 → 隐私与安全性 → 辅助功能** → 添加你的终端应用 |
| Linux | `local` | 建议安装 `xdotool` 和 `xclip`；CI 无头环境请加 `--background` |
| Windows | `local` | 对不响应标准输入的应用（游戏、DirectX）使用 `--target-app-class` 提示 |
| Android | `adb` | 安装 [ADBKeyboard](https://github.com/senzhk/ADBKeyboard)：`adb shell ime set com.android.adbkeyboard/.AdbIME` |
| iOS | `ios` | 需在设备上运行 WebDriverAgent；安装 `pip install facebook-wda` |
| 鸿蒙 OS | `hdc` | 需将 HDC（华为设备连接器）加入 `$PATH`；设备上须启动 UITest 服务 |

---

## nanobot 集成

使用 nanobot 时，OpenGUI 作为 `gui` 子智能体工具运行。主智能体可将"打开浏览器登录"等任务自动委托给 OpenGUI 执行。

### 启动 nanobot

nanobot 提供两个入口点：

**交互式 TUI / Gateway（API 网关）：**

```bash
nanobot                          # 启动交互式 TUI 对话
nanobot gateway                  # 仅启动 API 网关（0.0.0.0:18790）
```

**独立 Web UI 后端：**

```bash
nanobot-tui                      # 在 http://127.0.0.1:18791 提供 Web 界面
```

两个命令均支持 `--config` 参数：

```bash
nanobot --config ~/my-config.json
nanobot-tui --config ~/my-config.json
```

默认配置路径：`~/.nanobot/config.json`

### nanobot config.json

nanobot 读取单个 JSON 配置文件，所有字段同时支持 `camelCase` 和 `snake_case`。

**最简配置（DashScope）：**

```json
{
  "providers": {
    "dashscope": {
      "apiKey": "sk-..."
    }
  },
  "agents": {
    "defaults": {
      "model": "qwen3.5-plus"
    }
  }
}
```

**完整配置（主 agent 用 DashScope，GUI agent 用 OpenRouter）：**

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot/workspace",
      "model": "qwen3.5-plus",
      "provider": "auto",
      "maxTokens": 8192,
      "temperature": 0.1,
      "maxToolIterations": 40
    }
  },

  "providers": {
    "dashscope": {
      "apiKey": "sk-..."
    },
    "openrouter": {
      "apiKey": "sk-or-...",
      "apiBase": "https://openrouter.ai/api/v1"
    }
  },

  "gateway": {
    "host": "0.0.0.0",
    "port": 18790
  },

  "tui": {
    "host": "127.0.0.1",
    "port": 18791,
    "logLevel": "info"
  },

  "gui": {
    "backend": "adb",
    "model": "openrouter/qwen/qwen2.5-vl-72b-instruct",
    "provider": "openrouter",
    "agentProfile": "qwen3vl",
    "adb": { "serial": null },
    "maxSteps": 20,
    "embeddingModel": "text-embedding-v4",
    "skillThreshold": 0.6,
    "enableSkillExecution": true,
    "evaluation": {
      "enabled": true,
      "judgeModel": "qwen3-vl-plus",
      "apiKey": "sk-judge-...",
      "apiBase": "https://dashscope.aliyuncs.com/compatible-mode/v1"
    }
  }
}
```

> **关于 `embeddingModel`：** 填写后，nanobot 使用 DashScope Embedding 接口进行语义技能检索。不填则降级为 BM25 关键词匹配。
>
> **关于 `gui.model` / `gui.provider`：** 这是仅对 GUI 任务生效的覆盖项。不填写时，GUI 子智能体会继承 `agents.defaults.model` 和 `agents.defaults.provider`。
>
> **关于 `gui.agentProfile`：** 当 GUI 模型使用非默认的 prompt / action 契约时，请在这里指定 profile。当前支持 `default`、`general_e2e`、`qwen3vl`、`mai_ui`、`gelab`、`seed`。
>
> **关于 `gui.evaluation.judgeModel`：** 这个模型只用于 GUI 任务结束后的可选评测，不会影响真正执行 GUI 操作的模型。

### 在 nanobot `config.json` 中设置 profile

当 OpenGUI 通过 nanobot 的 `gui` 工具运行时，请把 profile 配到 `gui.agentProfile`：

```json
{
  "gui": {
    "backend": "adb",
    "model": "openrouter/qwen/qwen2.5-vl-72b-instruct",
    "provider": "openrouter",
    "agentProfile": "qwen3vl"
  }
}
```

说明：

- JSON 里请使用 camelCase 的 `agentProfile`。
- 在 Python 代码或内部配置对象里，也可以使用 `agent_profile`。
- 对于配置文件，`planner_executor` 也会被接受并归一化为 `general_e2e`，但文档和 CLI 推荐直接使用 canonical 名称。

### 如何为 GUI 任务单独指定 provider / model

现在主 agent 与 GUI 子智能体可以分别选择运行时模型：

- `agents.defaults.model` / `agents.defaults.provider`
  主 agent 使用，负责对话、规划、工具编排和非 GUI 工作
- `gui.model` / `gui.provider`
  只对 `gui_task` 生效
- `gui.evaluation.judgeModel`
  只对任务后评测生效

典型配置如下：

```json
{
  "agents": {
    "defaults": {
      "model": "qwen3.5-plus",
      "provider": "dashscope"
    }
  },
  "providers": {
    "dashscope": {
      "apiKey": "sk-main-..."
    },
    "openrouter": {
      "apiKey": "sk-or-...",
      "apiBase": "https://openrouter.ai/api/v1"
    }
  },
  "gui": {
    "backend": "local",
    "model": "openrouter/qwen/qwen2.5-vl-72b-instruct",
    "provider": "openrouter"
  }
}
```

在这个例子里：

- 主 agent 仍然使用 `qwen3.5-plus`
- GUI 任务改用 `openrouter/qwen/qwen2.5-vl-72b-instruct`
- `gui.provider` 指向的 provider 必须已经在顶层 `providers` 中配置好

如果不写 `gui.provider`，nanobot 会沿用与主 agent 相同的 provider 解析逻辑，并尝试根据 `gui.model` 自动推断 provider。

### 可选的 GUI evaluation

如果你希望每次成功的 GUI 任务结束后都自动做一次评测，可以开启 `gui.evaluation`：

```json
{
  "gui": {
    "backend": "adb",
    "evaluation": {
      "enabled": true,
      "judgeModel": "qwen3-vl-plus",
      "apiKey": "sk-judge-...",
      "apiBase": "https://dashscope.aliyuncs.com/compatible-mode/v1"
    }
  }
}
```

行为说明：

- 只有成功完成且生成了 `trace.jsonl` 的 GUI 任务才会触发评测
- 评测走后台 postprocessing，不会阻塞主 GUI 任务返回
- 评测结果会以 `evaluation.json` 写在同一次 GUI run 的目录下
- 如果 `apiKey` 为空，nanobot 会回退到环境变量 `OPENAI_API_KEY`
- `judgeModel` 可以和主 agent、GUI agent 分别使用不同的模型，只要 `apiBase` 与 `apiKey` 指向兼容的 OpenAI-style 接口即可

### gui 配置项说明

`gui` 节激活 GUI 子智能体工具。不填则 nanobot 不具备 GUI 能力。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `backend` | `"adb"` \| `"ios"` \| `"hdc"` \| `"local"` \| `"dry-run"` | `"adb"` | 执行后端 |
| `model` | `string \| null` | `null` | 仅用于 GUI 任务的模型覆盖；不填时继承 `agents.defaults.model` |
| `provider` | `string \| null` | `null` | 仅用于 GUI 任务的 provider 覆盖；不填时沿用主 agent 的 provider 解析逻辑 |
| `agentProfile` | `string \| null` | `null` | GUI 专用模型的 prompt / action profile；不填时默认走原生 tool-calling |
| `adb.serial` | `string \| null` | `null` | ADB 设备序列号；`null` = 自动检测 |
| `ios.wdaUrl` | `string` | `"http://localhost:8100"` | WebDriverAgent 服务器地址 |
| `hdc.serial` | `string \| null` | `null` | HDC 设备序列号；`null` = 自动检测 |
| `artifactsDir` | `string` | `"gui_runs"` | 截图和运行日志目录（相对于 workspace） |
| `maxSteps` | `int` | `15` | 单次任务最大操作步数 |
| `embeddingModel` | `string \| null` | `null` | 语义技能检索的 Embedding 模型（如 `"text-embedding-v4"`） |
| `skillThreshold` | `float` | `0.6` | 技能复用的最低相似度阈值 |
| `background` | `bool` | `false` | 使用虚拟显示隔离运行（仅 Linux；需 `backend: "local"`） |
| `displayNum` | `int \| null` | `null` | Xvfb 显示编号 |
| `displayWidth` | `int` | `1280` | 虚拟显示宽度，像素 |
| `displayHeight` | `int` | `720` | 虚拟显示高度，像素 |
| `enableSkillExecution` | `bool` | `false` | 开启技能回放（详见[技能系统](#技能系统)） |
| `evaluation.enabled` | `bool` | `false` | 是否对成功的 GUI 任务执行任务后评测 |
| `evaluation.judgeModel` | `string` | `"qwen3-vl-plus"` | 仅用于评测的 judge 模型 |
| `evaluation.apiKey` | `string` | `""` | judge 接口的 API Key；为空时回退到 `OPENAI_API_KEY` |
| `evaluation.apiBase` | `string \| null` | `"https://dashscope.aliyuncs.com/compatible-mode/v1"` | judge 接口的 OpenAI-compatible base URL |

### 切换后端

修改 `gui` 节中的 `backend` 字段即可切换设备类型：

```json
"gui": { "backend": "adb"      }   // Android 设备（ADB）
"gui": { "backend": "ios"      }   // iOS 设备（WebDriverAgent）
"gui": { "backend": "hdc"      }   // 鸿蒙 OS 设备（HDC）
"gui": { "backend": "local"    }   // 本地桌面（macOS / Linux / Windows）
"gui": { "backend": "dry-run"  }   // 测试模式，不执行真实操作
```

在独立 CLI 中使用 `--backend` 参数：

```bash
opengui --backend adb     "..."    # Android
opengui --backend ios     "..."    # iOS
opengui --backend hdc     "..."    # 鸿蒙 OS
opengui --backend local   "..."    # 桌面
opengui --backend dry-run "..."    # 测试
```

### 各平台配置示例

#### macOS — 本地桌面

```json
{
  "providers": {
    "dashscope": { "apiKey": "sk-..." }
  },
  "agents": {
    "defaults": { "model": "qwen3.5-plus" }
  },
  "gui": {
    "backend": "local",
    "maxSteps": 20,
    "embeddingModel": "text-embedding-v4",
    "enableSkillExecution": true
  }
}
```

> **需要无障碍权限。**
> 前往**系统设置 → 隐私与安全性 → 辅助功能**，将运行 nanobot 的终端应用（Terminal、iTerm2 等）加入白名单。

#### Linux — 本地桌面（有界面或无头 CI）

```json
{
  "providers": {
    "dashscope": { "apiKey": "sk-..." }
  },
  "agents": {
    "defaults": { "model": "qwen3.5-plus" }
  },
  "gui": {
    "backend": "local",
    "background": true,
    "displayNum": 99,
    "displayWidth": 1920,
    "displayHeight": 1080
  }
}
```

> 先安装必要系统依赖：
> ```bash
> sudo apt install xvfb xdotool xclip
> ```
>
> 若已有真实显示器，将 `"background"` 设为 `false` 即可。

#### Windows — 本地桌面

```json
{
  "providers": {
    "dashscope": { "apiKey": "sk-..." }
  },
  "agents": {
    "defaults": { "model": "qwen3.5-plus" }
  },
  "gui": {
    "backend": "local",
    "maxSteps": 15,
    "embeddingModel": "text-embedding-v4",
    "enableSkillExecution": true
  }
}
```

> 对于 GPU 加速或 DirectX 应用，可通过 `opengui` CLI 的 `--target-app-class directx`（或 `gpu-heavy`、`electron-gpu`、`uwp`）提示后端处理方式。此选项暂未在 nanobot config.json 中开放。

#### Android — ADB

```json
{
  "providers": {
    "dashscope": { "apiKey": "sk-..." }
  },
  "agents": {
    "defaults": { "model": "qwen3.5-plus" }
  },
  "gui": {
    "backend": "adb",
    "adb": { "serial": null },
    "maxSteps": 20,
    "embeddingModel": "text-embedding-v4",
    "enableSkillExecution": true
  }
}
```

> **Android 配置步骤：**
> 1. 开启 USB 调试：**设置 → 开发者选项 → USB 调试**
> 2. USB 连接手机，在手机上确认授权弹窗
> 3. 安装 ADBKeyboard（用于文字输入）：`adb install ADBKeyboard.apk`
> 4. 激活输入法：`adb shell ime set com.android.adbkeyboard/.AdbIME`
> 5. 验证连接：`adb devices` — 应显示你的设备序列号

连接多台设备时，通过 `serial` 指定目标：

```json
"adb": { "serial": "R3CN70BAYER" }
```

运行 `adb devices` 查看所有可用序列号。

#### iOS — WebDriverAgent

```json
{
  "providers": {
    "dashscope": { "apiKey": "sk-..." }
  },
  "agents": {
    "defaults": { "model": "qwen3.5-plus" }
  },
  "gui": {
    "backend": "ios",
    "ios": { "wdaUrl": "http://localhost:8100" },
    "maxSteps": 20,
    "embeddingModel": "text-embedding-v4",
    "enableSkillExecution": true
  }
}
```

> **iOS 配置步骤：**
> 1. 安装 Python 客户端：`pip install facebook-wda`
> 2. 通过 Xcode 将 [WebDriverAgent](https://github.com/appium/WebDriverAgent) 构建并部署到设备
> 3. 启动 WDA 服务器（Xcode Test Runner 或 `xcodebuild test-without-building`），默认监听 `8100` 端口
> 4. 通过 USB 转发端口：`iproxy 8100 8100`（来自 `libimobiledevice`）
> 5. 验证服务可达：`curl http://localhost:8100/status`
>
> 如果 WDA 监听不同的主机或端口，相应修改 `wdaUrl`。

#### 鸿蒙 OS — HDC

```json
{
  "providers": {
    "dashscope": { "apiKey": "sk-..." }
  },
  "agents": {
    "defaults": { "model": "qwen3.5-plus" }
  },
  "gui": {
    "backend": "hdc",
    "hdc": { "serial": null },
    "maxSteps": 20,
    "embeddingModel": "text-embedding-v4",
    "enableSkillExecution": true
  }
}
```

> **鸿蒙 OS 配置步骤：**
> 1. 开启开发者模式：**设置 → 关于手机 → 连续点击版本号 7 次**
> 2. 开启 USB 调试：**设置 → 开发者选项 → USB 调试**
> 3. USB 连接手机，在手机上确认授权弹窗
> 4. 安装 HDC 工具（DevEco Studio SDK 附带）：确保 `hdc` 在 `$PATH` 中
> 5. 验证连接：`hdc list targets` — 应显示你的设备序列号
>
> UITest 框架（`uitest` 服务）必须在设备上运行。鸿蒙 OS 3.1+ 在开启 USB 调试后会自动启动该服务。

连接多台设备时，通过 `serial` 指定目标：

```json
"hdc": { "serial": "FMR0223C13000649" }
```

运行 `hdc list targets` 查看所有可用序列号。

---

## Planner / Router 路由集成

nanobot 将多步骤任务分解为计划时，需要为每个 GUI 子任务分配正确的路由标识（route sentinel）。OpenGUI 针对每种后端暴露一个路由哨兵，planner 用它来生成类型正确的计划节点。

### 路由哨兵对照表

| 后端 | 路由哨兵 | 生效条件 |
|------|---------|---------|
| `local` 或 `dry-run` | `gui.desktop` | 默认；本地桌面控制 |
| `adb` | `gui.adb` | Android 设备（ADB） |
| `ios` | `gui.ios` | iOS 设备（WebDriverAgent） |
| `hdc` | `gui.hdc` | 鸿蒙 OS 设备（HDC） |

活跃哨兵由配置中的 `gui.backend` 字段决定：

```
"backend": "adb"   →  planner 生成  route_id = "gui.adb"
"backend": "ios"   →  planner 生成  route_id = "gui.ios"
"backend": "hdc"   →  planner 生成  route_id = "gui.hdc"
"backend": "local" →  planner 生成  route_id = "gui.desktop"
```

Router 将 `gui.desktop`、`gui.adb`、`gui.ios`、`gui.hdc` 均分发到同一个 GUI 子智能体工具——路由哨兵的意义在于让 planner（以及查看计划 trace 的开发者）能清晰看到每个子任务所指向的物理设备。

### Planner 如何感知当前后端

规划阶段，nanobot 通过 `PlanningContext` 的 `active_gui_route` 字段将当前后端告知 planner。Planner 指令会向 LLM 说明：

> *"当前 GUI 后端为 'gui.hdc'，所有 GUI 子任务必须使用 route_id='gui.hdc'，不得使用 'gui.desktop' 或其他 GUI 路由标识。"*

因此，当你在 Android 手机、iPhone 和鸿蒙设备之间切换时，planner 会自动生成正确的 route_id，无需任何手动干预。

### 能力目录（Capability Catalog）

Planner 看到的能力目录摘要也会随后端动态变化：

| `gui.backend` | Planner 看到的摘要 |
|---------------|-------------------|
| `adb` | "使用 GUI 子智能体操作已连接的 Android 设备上的应用" |
| `ios` | "使用 GUI 子智能体操作已连接的 iOS 设备上的应用" |
| `hdc` | "使用 GUI 子智能体操作已连接的鸿蒙 OS 设备上的应用" |
| `local` | "使用 GUI 子智能体操作本地桌面上的应用" |

---

## App 列表初始化

OpenGUI 会缓存已安装的 App 列表，方便智能体了解目标设备或桌面上有哪些应用可用。缓存位于 `~/.opengui/apps/`，格式为 JSON 字符串数组。

**各平台缓存文件路径：**

| 平台 | 缓存文件 |
|------|---------|
| Android（默认设备） | `~/.opengui/apps/android_default.json` |
| Android（指定序列号） | `~/.opengui/apps/android_R3CN70BAYER.json` |
| iOS | `~/.opengui/apps/ios_default.json` |
| 鸿蒙 OS（默认设备） | `~/.opengui/apps/harmonyos_default.json` |
| 鸿蒙 OS（指定序列号） | `~/.opengui/apps/harmonyos_FMR0223C13000649.json` |
| macOS | `~/.opengui/apps/macos.json` |
| Linux | `~/.opengui/apps/linux.json` |
| Windows | `~/.opengui/apps/windows.json` |

### 自动生成

首次运行时会自动获取 App 列表并缓存，后续直接读取缓存（速度更快）。强制刷新：

```bash
opengui --refresh-apps --backend adb "打开微信"
opengui --refresh-apps --backend ios "打开设置"
opengui --refresh-apps --backend hdc "打开设置"
```

### 手动初始化

可直接编辑缓存文件。格式为 JSON 字符串数组。

**Android**（`~/.opengui/apps/android_default.json`）：

```json
[
  "com.tencent.mm",
  "com.eg.android.AlipayGphone",
  "com.taobao.taobao",
  "com.android.settings",
  "com.android.chrome",
  "tv.danmaku.bili",
  "com.ss.android.ugc.aweme"
]
```

> Android 填写**包名**（Package Name）。查询方式：
> ```bash
> adb shell pm list packages -3      # 仅列出第三方应用
> adb shell pm list packages          # 列出所有应用
> ```

**iOS**（`~/.opengui/apps/ios_default.json`）：

```json
[
  "com.apple.Preferences",
  "com.apple.mobilesafari",
  "com.tencent.xin",
  "com.alipay.iphoneclient",
  "com.ss.iphone.ugc.Aweme"
]
```

> iOS 填写 **Bundle ID**。查询方式：
> ```bash
> ideviceinstaller -l          # 需安装 libimobiledevice
> ```

**鸿蒙 OS**（`~/.opengui/apps/harmonyos_default.json`）：

```json
[
  "com.huawei.settings",
  "com.huawei.browser",
  "com.tencent.mm",
  "com.eg.android.AlipayGphone",
  "com.ss.android.ugc.aweme"
]
```

> 鸿蒙 OS 填写 **Bundle Name**（应用包名）。查询方式：
> ```bash
> hdc shell bm dump -a          # 列出所有已安装包
> ```

**macOS**（`~/.opengui/apps/macos.json`）：

```json
[
  "Safari",
  "Google Chrome",
  "Firefox",
  "Finder",
  "Terminal",
  "Visual Studio Code",
  "Slack",
  "Notion"
]
```

> macOS 填写 `.app` 包的**名称**（去掉 `.app` 后缀），即 `/Applications` 或 `~/Applications` 中的应用名。

**Linux**（`~/.opengui/apps/linux.json`）：

```json
[
  "firefox",
  "google-chrome",
  "code",
  "gnome-terminal",
  "nautilus",
  "gedit",
  "slack"
]
```

> Linux 填写 `/usr/share/applications/` 下 `.desktop` 文件的文件名（去掉 `.desktop`）。查询方式：
> ```bash
> ls /usr/share/applications/*.desktop | xargs -I{} basename {} .desktop
> ```

**Windows**（`~/.opengui/apps/windows.json`）：

```json
[
  "Microsoft Edge",
  "Google Chrome",
  "File Explorer",
  "Notepad",
  "Visual Studio Code",
  "Slack"
]
```

> Windows 填写应用的可读名称，OpenGUI 用它来查找并定位窗口。

---

## 记忆库

OpenGUI 在 `~/.opengui/memory/` 下维护一个持久化知识库（CLI 和 nanobot 共用同一路径）。记忆条目教会智能体如何在你的操作系统环境中导航、与特定应用交互、识别图标，以及遵守你设定的行为策略。

### 记忆类型

| 类型 | 文件 | 用途 |
|------|------|------|
| `os` | `os_guide.md` | 通用 OS 导航技巧（如任务栏用法、快捷键等） |
| `app` | `app_guide.md` | 特定应用的交互指南（如某个 App 的菜单结构） |
| `icon` | `icon_guide.md` | 图标与视觉元素识别提示（如自定义图标的外观描述） |
| `policy` | `policy.md` | 智能体行为策略（如"删除前必须确认"） |

### 文件格式

每个文件由若干 Markdown `##` 节组成，每节对应一条记忆条目：

```markdown
## {标题 — 内容第一行，最多 72 字符}
id: {UUID}
type: {os|app|icon|policy}
platform: {android|ios|harmonyos|macos|linux|windows|dry-run}
app: {包名或应用名，非特定应用时留空}
tags: {逗号分隔的标签，可为空}
created_at: {Unix 时间戳（浮点数）}
access_count: {整数}

{正文 — 自由文本，描述智能体需要了解的内容}
```

### 示例

#### OS 导航 — macOS 系统操作（`os_guide.md`）

```markdown
## 调度中心可通过 Ctrl+上箭头或三指上滑打开
id: 3a7f2c1e-0001-4b2d-a100-000000000001
type: os
platform: macos
app:
tags: 导航, 快捷键
created_at: 1711468800.0
access_count: 0

调度中心可通过 Ctrl+上箭头或触控板三指上滑打开，可查看所有窗口和空间。
切换空间：三指左右滑动，或按 Ctrl+左/右箭头。
```

#### 应用指南 — Android 微信（`app_guide.md`）

```markdown
## 微信聊天列表在第一个 Tab；点右上角编辑图标开始新会话
id: 3a7f2c1e-0002-4b2d-a100-000000000002
type: app
platform: android
app: com.tencent.mm
tags: 微信, 聊天
created_at: 1711468800.0
access_count: 0

微信聊天列表在底部导航第一个 Tab。右上角铅笔图标可发起新对话。
顶部搜索栏可搜索联系人和消息。长按对话可置顶、静音或删除。
```

#### 应用指南 — 鸿蒙 OS 设置（`app_guide.md`）

```markdown
## 鸿蒙 OS 设置采用卡片式布局；下拉可调出搜索框
id: 3a7f2c1e-0005-4b2d-a100-000000000005
type: app
platform: harmonyos
app: com.huawei.settings
tags: 设置, 导航
created_at: 1711468800.0
access_count: 0

鸿蒙 OS 设置以大卡片形式展示选项。在列表任意位置下拉可显示搜索框。
Wi-Fi 在"WLAN"下，蓝牙在"蓝牙"下，应用权限在"应用 → 权限管理"下。
```

#### 图标识别 — 飞书图标（`icon_guide.md`）

```markdown
## 飞书图标是白底上蓝色翅膀形状
id: 3a7f2c1e-0003-4b2d-a100-000000000003
type: icon
platform: android
app: com.ss.android.lark
tags: 图标, 飞书
created_at: 1711468800.0
access_count: 0

飞书（Lark）图标为白底蓝色翅膀或鸟形图案，可能显示为"飞书"或"Lark"（取决于语言设置）。
不要与 Twitter/X 的蓝色鸟图标混淆，两者形状相近但飞书更亮。
```

#### 策略 — 安全操作规范（`policy.md`）

```markdown
## 发送消息或完成购买前必须征得用户确认
id: 3a7f2c1e-0004-4b2d-a100-000000000004
type: policy
platform: android
app:
tags: 安全, 确认
created_at: 1711468800.0
access_count: 0

在发送任何消息、提交任何表单或完成任何购买之前，必须暂停并请用户确认。
不得自主执行任何不可撤销的操作。
```

### 编辑记忆

可直接编辑 `~/.opengui/memory/` 下的 Markdown 文件来增删改条目。规则：

- 每个条目以 `## ` 开头，后接简短标题（≤ 72 字符）
- `id:`、`type:`、`platform:` 三个元数据字段**必填**；其余字段可选但建议填写
- `id` 必须是 UUID，生成方式：`python -c "import uuid; print(uuid.uuid4())"`
- `type` 必须是以下之一：`os`、`app`、`icon`、`policy`
- `platform` 必须是以下之一：`android`、`ios`、`harmonyos`、`macos`、`linux`、`windows`、`dry-run`
- 元数据块与正文之间用**空行**分隔
- 同一文件中多个条目以 `##` 标题分隔

删除条目：直接从文件中移除对应的整个 `##` 节即可。

---

## 后端

| 后端 | 支持平台 | 说明 |
|------|---------|------|
| `local` | macOS / Linux / Windows | 控制运行 nanobot/opengui 的本机桌面 |
| `adb` | Android（USB 或网络 ADB） | 控制已连接的 Android 设备或模拟器 |
| `ios` | iOS（USB 或 Wi-Fi，通过 WebDriverAgent） | 通过 WDA HTTP 服务控制已连接的 iPhone 或 iPad |
| `hdc` | 鸿蒙 OS（USB 或网络 HDC） | 通过 `hdc` CLI 和 UITest 框架控制已连接的鸿蒙设备 |
| `dry-run` | 任意平台 | 测试模式 — 不执行真实操作；截图返回 1×1 透明 PNG |

---

## 技能系统

OpenGUI 从成功的任务中学习。每次任务完成后，系统会提取一个可复用的**技能**——带参数的具名步骤序列——并存入技能库。下次执行相似任务时，系统先在技能库中检索；若匹配度超过 `skillThreshold`，则直接回放技能，无需从头探索。

**技能存储路径：**

| 模式 | 路径 |
|------|------|
| CLI（opengui） | `~/.opengui/skills/<platform>/` |
| nanobot | `<workspace>/gui_skills/<platform>/` |

### 开启技能执行

技能**学习**（提取）始终开启。技能**执行**（回放）需手动开启：

```json
"gui": {
  "enableSkillExecution": true,
  "skillThreshold": 0.6,
  "embeddingModel": "text-embedding-v4"
}
```

`enableSkillExecution: false`（默认）时，技能仍会被提取和存储，但不会被回放。可先被动积累技能库，再开启回放。

### 调整 `skillThreshold`

| 值 | 行为 |
|----|------|
| `1.0` | 仅精确匹配时触发回放 |
| `0.6` | 默认值；匹配语义相似任务 |
| `0.3` | 激进复用；可能对相关度较低的任务也触发 |

多次失败的技能会被自动清除（在 5 次以上尝试后置信度降至 0.3 以下）。
