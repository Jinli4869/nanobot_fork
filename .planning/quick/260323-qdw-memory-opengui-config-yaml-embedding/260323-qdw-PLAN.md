# Quick Task 260323-qdw Plan

**Description:** 检查现有 memory 相关代码改动是否必要并处理提交，然后修复 `~/.opengui/config.yaml` 的 embedding 兼容问题。  
**Date:** 2026-03-23  
**Mode:** quick

## Objective

先审查当前未提交的 memory 相关代码改动，判断哪些需要保留并提交、哪些应回退；随后修复宿主机 `~/.opengui/config.yaml` 中的 embedding 模型配置，让 OpenGUI 标准 memory 路径不再因为不兼容模型名而失败。

## Constraints

- 不触碰无关未提交内容，特别是不处理 `TEST.ipynb`。
- 代码改动只有在验证后确认有价值时才保留提交。
- `~/.opengui/config.yaml` 位于仓库外，修复时只做最小修改。

## Tasks

1. 审查并验证现有 memory 改动
   - 检查 `opengui/agent.py`、`tests/test_opengui_p2_memory.py`、`scripts/probe_opengui_memory.py`
   - 运行针对性测试与基础语法校验
   - 判断哪些改动应保留、哪些应回退

2. 处理代码改动
   - 将确认必要的 memory 可观测性改动单独提交
   - 保持其余工作区内容不受影响

3. 修复并验证 embedding 配置
   - 检查 `~/.opengui/config.yaml`
   - 将不兼容的 embedding model 改为官方文本 embedding 模型
   - 验证旧错误消失，并补做一次最小 embedding API 调用确认配置可用

## Verification

- `uv run pytest tests/test_opengui_p2_memory.py -q`
- `uv run python -m py_compile scripts/probe_opengui_memory.py opengui/agent.py tests/test_opengui_p2_memory.py`
- 真实 embedding 调用返回向量 shape，而不是 `Unsupported model 'qwen3-vl-embedding'`

## Deliverables

- `260323-qdw-PLAN.md`
- `260323-qdw-SUMMARY.md`
- 更新 `.planning/STATE.md`
