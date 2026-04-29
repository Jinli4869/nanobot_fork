# Quick Task 260324-k9r Summary

**Description:** 修复 GUI skill 提取与存储分桶：统一 `gui_skills` 根目录，并在提取/入库/过滤边界规范化 app 标识。  
**Date:** 2026-03-24  
**Status:** completed

## Result

`GuiSubagentTool` 现在始终把 `SkillLibrary` 指向统一的 `workspace/gui_skills` 根目录，`SkillLibrary` 与 `SkillExtractor` 会把同一 app 的大小写、空白和常见 Android 名称别名稳定归一到同一个 bucket。

## Implementation

核心改动：

- [`gui.py`](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/agent/tools/gui.py)
  - `GuiSubagentTool` 不再预先把 `platform` 拼进 `store_dir`
  - 改为复用统一的 `gui_skills` 根目录 helper
- [`normalization.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/skills/normalization.py)
  - 新增共享 app normalization 逻辑
  - 覆盖空白、大小写、slug 化，以及 Android 常见别名到包名的稳定映射
- [`extractor.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/skills/extractor.py)
  - LLM 提取后的 `skill.app` 在返回前先规范化
- [`library.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/skills/library.py)
  - `add` / `add_or_merge` / `update` / `load_all` / `list_all` / `search` 全部走统一 app normalization
  - 冲突检测、持久化分桶、reload 后过滤都基于规范化后的 app 标识

## Test Coverage

新增和更新的回归测试位于：

- [`test_opengui_p1_skills.py`](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p1_skills.py)
  - app alias 过滤命中同一 bucket
  - 同 app 的自然语言名和包名会在 `add_or_merge()` 后落到同一规范化 bucket
  - reload 后 `list_all()` 仍能按规范化 app 返回同一组技能
- [`test_opengui_p3_nanobot.py`](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p3_nanobot.py)
  - GUI 自动提取后的 skill 会落到统一 `gui_skills/<platform>/<normalized-app>/skills.json`
  - 修正了现有 result payload 断言以匹配 `model_summary` 字段

验证命令：

```bash
uv run pytest tests/test_opengui_p1_skills.py tests/test_opengui_p3_nanobot.py -q
uv run python -m py_compile opengui/skills/library.py opengui/skills/extractor.py nanobot/agent/tools/gui.py
```

验证结果：

- `41 passed`
- `py_compile` 成功

## Task Commits

1. `2a1bc34` `fix(quick-260324-k9r): unify gui skill store root`
2. `0e5ef97` `fix(quick-260324-k9r): normalize gui skill app buckets`
3. `4639dcb` `test(quick-260324-k9r): lock gui skill bucket regressions`

## Deviations

### [Rule 3 - Blocking] 更新过期的 GUI tool result 断言

- **Found during:** Task 3 verification
- **Issue:** `tests/test_opengui_p3_nanobot.py` 仍断言旧的 result key 集合，遗漏现有的 `model_summary`
- **Fix:** 将断言调整为当前返回结构，避免计划要求的整文件验证被无关旧断言阻塞

## Outcome

同一平台、同一应用的 GUI skills 现在会稳定落在同一 `gui_skills` bucket，`SkillLibrary.add_or_merge()`、`list_all()` 和 reload 后的管理路径重新指向同一组技能。
