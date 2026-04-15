# OpenGUI 迁移部署指南（面向 OpenClaw / NanoClaw / 其他 Claw 宿主）

本指南面向这样一种场景：

- 你希望把 `opengui` 单独迁移到 `openclaw`、`nanoclaw` 或其他 `*claw` 宿主中
- 你希望不同宿主使用一套尽量统一的 GUI 配置
- 你希望通过最少代码接入，就让宿主快速获得 GUI 操控能力

这份文档不重复介绍 OpenGUI 的基础 CLI 用法，重点解释宿主如何嵌入、配置、运行，以及如何决定是否接入任务结束后的总结、评测、技能沉淀等后处理能力。

## 1. 迁移目标

建议把 OpenGUI 拆成两层来迁移：

1. `opengui` 本体
   - `GuiAgent`
   - 各种 backend
   - `TrajectoryRecorder`
   - `Observation`
   - 技能检索与执行模块

2. 宿主适配层
   - 把宿主自己的 LLM Provider 适配成 OpenGUI 期望的接口
   - 把宿主自己的配置映射到 OpenGUI 的统一配置
   - 把 GUI 结果包装成宿主工具返回值
   - 决定是否在任务结束后执行后处理

如果你只迁移第 1 层，你会得到“能跑 GUI”的能力。

如果你同时补齐第 2 层，你才会得到“好接入、可配置、可观测、可沉淀”的工程化能力。

## 2. 推荐的统一配置模型

建议所有 `*claw` 宿主统一使用下面这份 `gui` 配置，不要每个宿主各自设计一套。

```json
{
  "gui": {
    "backend": "local",
    "provider": "openai",
    "model": "gpt-4.1",
    "agentProfile": "default",
    "artifactsDir": "gui_runs",
    "maxSteps": 15,
    "embeddingModel": null,
    "skillThreshold": 0.6,
    "enableSkillExecution": false,
    "background": false,
    "displayNum": null,
    "displayWidth": 1280,
    "displayHeight": 720,
    "enablePostRunSummary": true,
    "enableEvaluation": false,
    "evaluation": {
      "judgeModel": "qwen3-vl-plus",
      "apiKey": "",
      "apiBase": "https://dashscope.aliyuncs.com/compatible-mode/v1"
    },
    "adb": {
      "serial": null
    },
    "ios": {
      "wdaUrl": "http://localhost:8100"
    },
    "hdc": {
      "serial": null
    }
  }
}
```

说明：

- `backend`
  - `adb` / `ios` / `hdc` / `local` / `dry-run`
- `provider` / `model`
  - 指向宿主自己的 LLM 配置，不要求 OpenGUI 自己管理多提供商
- `agentProfile`
  - 统一映射到 OpenGUI 的 `agent_profile`
- `artifactsDir`
  - GUI 运行产物目录，建议固定为 workspace 下相对路径
- `enablePostRunSummary`
  - 宿主层开关，控制是否在 GUI 任务结束后读取轨迹并做总结
- `enableEvaluation`
  - 宿主层开关，控制是否跑额外评测

建议把它视为“宿主统一契约”，而不是某一个 claw 的私有配置。

## 3. OpenGUI 本体最小依赖

宿主最少需要接入这几类能力：

### 3.1 LLM 适配

`GuiAgent` 需要一个满足 OpenGUI LLM 协议的对象，最小能力是：

- 接收 `messages`
- 可选接收 `tools`
- 返回：
  - `content`
  - `tool_calls`
  - `raw`
  - `usage`

如果宿主已经有自己的 Provider，推荐像 nanobot 一样写一层适配器，而不是改 OpenGUI 本体。

可参考：

- [nanobot/agent/gui_adapter.py](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/agent/gui_adapter.py)

### 3.2 Backend 选择

宿主至少要负责把统一配置里的 `backend` 映射到具体 backend 类：

- `adb` -> `opengui.backends.adb.AdbBackend`
- `ios` -> `opengui.backends.ios_wda.WdaBackend`
- `hdc` -> `opengui.backends.hdc.HdcBackend`
- `local` -> `opengui.backends.desktop.LocalDesktopBackend`
- `dry-run` -> `opengui.backends.dry_run.DryRunBackend`

可参考：

- [nanobot/agent/tools/gui.py](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/agent/tools/gui.py)
- [opengui/cli.py](/Users/jinli/Documents/Personal/nanobot_fork/opengui/cli.py)

### 3.3 轨迹记录

建议每次 GUI 任务都创建一个新的 run 目录，并启用：

- `TrajectoryRecorder`
- 截图目录
- `trace.jsonl`

这样宿主后面才能做：

- 成功/失败总结
- 最新界面状态回读
- 评测
- 轨迹调试
- 技能抽取

## 4. 最小嵌入方式

最小落地方案推荐使用“宿主工具包装器”模式，而不是直接在宿主主循环里散落调用 OpenGUI。

也就是在宿主中定义一个类似 `gui_task` 的工具：

- 输入：自然语言 GUI 任务
- 输出：结构化 JSON 结果

推荐输出结构：

```json
{
  "success": true,
  "summary": "Task completed after 3 step(s).",
  "model_summary": "Opened Settings and enabled Wi-Fi.",
  "trace_path": "/workspace/gui_runs/2026-04-07_120000/trace.jsonl",
  "steps_taken": 3,
  "error": null,
  "post_run_state": {
    "trace_read": true,
    "latest_screenshot_path": "/workspace/gui_runs/2026-04-07_120000/screenshots/step_002.png",
    "last_action": {
      "action_type": "done",
      "status": "success"
    },
    "last_action_summary": "Wi-Fi is enabled",
    "last_foreground_app": "Settings",
    "platform": "android",
    "screen_resolution": "1080x2400",
    "current_state": "Task completed after 3 step(s). Latest visible app: Settings. Screen resolution: 1080x2400.",
    "completion_assessment": "completed"
  }
}
```

这份返回值有两个作用：

1. 宿主主 agent 可以直接基于它回复用户
2. 前端或日志系统可以直接消费它

## 5. 推荐的宿主实现结构

建议在 `openclaw` / `nanoclaw` 里保持下面的模块边界：

### 5.1 `gui_adapter.py`

负责：

- 把宿主 Provider 包装成 OpenGUI LLM 接口
- 可选包装 embedding 接口

### 5.2 `gui_config.py`

负责：

- 定义统一 `GuiConfig`
- 兼容 `snake_case` 和 `camelCase`
- 做配置合法性校验

最低建议校验：

- `background=true` 时只允许 `backend=local`
- `backend=ios` 时必须提供 `wdaUrl`
- `backend=adb` / `hdc` 时设备发现失败要返回可读错误

### 5.3 `tools/gui.py`

负责：

- 选 backend
- 创建 run 目录
- 初始化 `TrajectoryRecorder`
- 创建 `GuiAgent`
- 执行任务
- 返回标准 JSON
- 可选执行任务结束后的后处理

### 5.4 `runtime/gui_postprocess.py`

建议把后处理单独拆文件，避免和主执行逻辑耦合太重。

后处理可以包含：

- 轨迹总结
- 成功/失败状态摘要
- 评测
- 技能抽取

## 6. 最短 Python 接入示例

下面这个示例适合先在任意 `*claw` 宿主里打通最短链路。

```python
from pathlib import Path

from opengui.agent import GuiAgent
from opengui.backends.desktop import LocalDesktopBackend
from opengui.trajectory.recorder import TrajectoryRecorder


class HostLLMAdapter:
    def __init__(self, provider, model: str) -> None:
        self._provider = provider
        self._model = model

    async def chat(self, messages, tools=None, tool_choice=None):
        resp = await self._provider.chat_with_retry(
            messages=messages,
            tools=tools,
            model=self._model,
            tool_choice=tool_choice,
        )
        return resp


async def run_gui_task(provider, model: str, workspace: Path, task: str) -> dict:
    run_dir = workspace / "gui_runs" / "demo_run"
    run_dir.mkdir(parents=True, exist_ok=True)

    llm = HostLLMAdapter(provider, model)
    backend = LocalDesktopBackend()
    recorder = TrajectoryRecorder(output_dir=run_dir, task=task, platform=backend.platform)

    agent = GuiAgent(
        llm=llm,
        backend=backend,
        trajectory_recorder=recorder,
        model=model,
        artifacts_root=run_dir,
        max_steps=15,
    )

    result = await agent.run(task)
    return {
        "success": result.success,
        "summary": result.summary,
        "model_summary": result.model_summary,
        "trace_path": result.trace_path,
        "steps_taken": result.steps_taken,
        "error": result.error,
    }
```

如果这段先跑通，说明宿主已经具备最基础的 GUI 能力。

## 7. 统一配置到 OpenGUI 的映射关系

建议所有 claw 使用同一套映射表：

| 宿主统一字段 | OpenGUI 内部字段 | 说明 |
|---|---|---|
| `gui.backend` | backend builder | 选择设备/桌面 backend |
| `gui.model` | `GuiAgent(..., model=...)` | GUI 执行模型 |
| `gui.agentProfile` | `agent_profile` | 非原生 tool-calling 模型时使用 |
| `gui.maxSteps` | `max_steps` | GUI 最大步数 |
| `gui.artifactsDir` | run root | 截图和轨迹输出目录 |
| `gui.embeddingModel` | embedding adapter | 可选技能检索 |
| `gui.skillThreshold` | `skill_threshold` | 技能召回阈值 |
| `gui.enableSkillExecution` | skill executor wiring | 是否启用技能执行 |
| `gui.background` | background runtime | 本地桌面隔离运行 |
| `gui.displayWidth` | display manager width | 虚拟显示宽度 |
| `gui.displayHeight` | display manager height | 虚拟显示高度 |
| `gui.evaluation.*` | post-run evaluation | 成功后评测 |

## 8. 推荐的任务结束后处理策略

你需要先决定宿主想要哪一种级别。

### 8.1 级别 A：只运行，不做后处理

特点：

- 接入最快
- 只返回 `success / summary / trace_path`
- 宿主不读取轨迹，不做总结

适合：

- 先把 GUI 跑起来
- 仅内部调试

### 8.2 级别 B：读取最新轨迹，给主 agent 可用状态

特点：

- GUI 任务结束后读取最后一步
- 提取：
  - 最新截图
  - 最后动作
  - 当前前台 app
  - 当前分辨率
  - 当前状态摘要

适合：

- `openclaw` / `nanoclaw` 主 agent 要面向用户回复“是否完成、现在停在哪”

这是最推荐的默认级别。

### 8.3 级别 C：完整后处理

在级别 B 基础上再加入：

- `TrajectorySummarizer`
- 评测
- 技能沉淀

适合：

- 长期演进
- 需要训练数据、回放、质量追踪

## 9. 如何把“任务结束总结”做成宿主可选能力

建议不要把总结逻辑硬编码在 `opengui` 本体里，而是在宿主中做开关：

```python
if gui_config.enable_post_run_summary:
    post_run_state = build_post_run_state(trace_path, result)
else:
    post_run_state = None
```

推荐拆成两部分：

1. 轻量状态回读
   - 直接解析最后一步轨迹
   - 不依赖额外 LLM

2. 自然语言总结
   - 调 `TrajectorySummarizer`
   - 依赖额外 LLM token

这样设计的好处是：

- 默认就能给主 agent 足够信息
- 需要省 token 时仍能工作
- 不同 claw 可以按产品需求决定是否启用 LLM 总结

## 10. OpenClaw / NanoClaw 推荐目录结构

建议两个宿主尽量保持同构：

```text
<claw>/
  agent/
    gui_adapter.py
    tools/
      gui.py
  config/
    gui_schema.py
  runtime/
    gui_postprocess.py
  opengui_vendor/        # 可选：vendor 方式引入
```

或者：

```text
<claw>/
  integrations/
    opengui/
      adapter.py
      config.py
      tool.py
      postprocess.py
```

建议不要把 OpenGUI 的宿主接入代码散在多个业务目录中。

## 11. 两种部署方式

### 11.1 方式一：作为 Python 依赖直接引用

适合：

- `openclaw` 和 `nanoclaw` 都是 Python 宿主
- 希望共享同一套 OpenGUI 代码

推荐：

```bash
uv pip install -e .
```

或把 OpenGUI 作为 monorepo 内的可编辑依赖。

### 11.2 方式二：Vendor 代码到宿主仓库

适合：

- 不同 claw 需要各自裁剪
- 需要独立发布

注意：

- 只 vendor `opengui/` 本体还不够
- 还需要把宿主适配层一并落地

## 12. 快速上线检查清单

建议按这个顺序检查：

1. `dry-run` 是否跑通
2. 本地 `local` backend 是否可截图
3. Android / iOS / HDC 的设备连通性是否正常
4. run 目录下是否产生截图和 `trace.jsonl`
5. 宿主是否能把 JSON 结果返回给主 agent
6. 主 agent 是否能基于 `post_run_state` 回复用户
7. 是否需要启用背景运行
8. 是否需要启用评测和技能沉淀

## 13. 推荐的默认上线顺序

建议不要一次性把所有高级能力都迁过去。

### 第一阶段

- `dry-run`
- `local`
- 基础 `gui_task`
- 结构化结果输出

### 第二阶段

- `adb` / `ios` / `hdc`
- `post_run_state`
- 主 agent 状态回复

### 第三阶段

- background mode
- skill execution
- trajectory summary
- evaluation
- shortcut promotion

## 14. 常见坑

### 14.1 只迁移 `GuiAgent`，没迁移宿主适配层

结果：

- 能跑，但很难配置
- 宿主拿不到标准化结果
- 主 agent 很难知道执行完后的界面状态

### 14.2 直接把宿主 Provider 塞给 OpenGUI

结果：

- tool call 格式不兼容
- 返回对象字段对不上

建议始终写一层 adapter。

### 14.3 只看 `result.summary`，不读轨迹

结果：

- 用户问“完成了吗？现在在哪个页面？”时，宿主回答不稳

建议至少实现级别 B 的轻量状态回读。

### 14.4 把后处理硬绑在 OpenGUI 本体

结果：

- 不同 claw 很难按需裁剪
- token 成本不好控

建议把后处理设计成宿主策略。

## 15. 最小建议结论

如果你现在要把 OpenGUI 快速迁到 `openclaw` / `nanoclaw`：

1. 先统一 `gui` 配置字段
2. 写宿主自己的 `LLMAdapter`
3. 写一个标准 `gui_task` 包装器
4. 默认启用“轻量 post_run_state”，先不要强绑 LLM 总结
5. 把 `TrajectorySummarizer`、评测、技能沉淀做成可选开关

这样你会得到一套：

- 各 claw 配置一致
- 宿主代码结构一致
- GUI 能力可快速上线
- 后续可逐步增强

## 16. 相关代码参考

- [opengui/agent.py](/Users/jinli/Documents/Personal/nanobot_fork/opengui/agent.py)
- [opengui/cli.py](/Users/jinli/Documents/Personal/nanobot_fork/opengui/cli.py)
- [opengui/trajectory/recorder.py](/Users/jinli/Documents/Personal/nanobot_fork/opengui/trajectory/recorder.py)
- [opengui/trajectory/summarizer.py](/Users/jinli/Documents/Personal/nanobot_fork/opengui/trajectory/summarizer.py)
- [nanobot/agent/gui_adapter.py](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/agent/gui_adapter.py)
- [nanobot/agent/tools/gui.py](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/agent/tools/gui.py)
- [nanobot/config/schema.py](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/config/schema.py)

如果你后面准备正式迁到 `openclaw`，最推荐的下一步不是继续改文档，而是直接在宿主中先落一个最小 `gui_task`，用 `dry-run` 和 `local` 两个 backend 验证统一配置和返回结构。
