# Quick Task 260324-oks Summary

**Description:** 简化 `gui_skills` 目录结构为每个平台单一 `skills.json` 聚合文件。  
**Date:** 2026-03-24  
**Status:** completed

## Result

`SkillLibrary` 现在会把同一平台的全部 GUI skills 聚合写入 `gui_skills/<platform>/skills.json`，不再继续生成 `gui_skills/<platform>/<app>/skills.json` 这一层额外目录。

## Implementation

- [`library.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/skills/library.py)
  - 将持久化模型改为平台级聚合文件
  - 新增旧版 nested bucket 兼容读取逻辑
  - 新写入后会清理同平台残留的旧版 `*/skills.json`
- [`test_opengui_p1_skills.py`](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p1_skills.py)
  - 更新平台级存储断言
  - 新增 legacy nested bucket 读取回归测试
- [`test_opengui_p3_nanobot.py`](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p3_nanobot.py)
  - 更新 GUI 自动提取后的落盘路径断言

## Verification

- `uv run pytest tests/test_opengui_p1_skills.py tests/test_opengui_p3_nanobot.py -q`
  - 结果：`42 passed`
- `uv run python -m py_compile opengui/skills/library.py nanobot/agent/tools/gui.py opengui/skills/extractor.py`
  - 结果：通过

## Notes

- 代码已经保证后续写入会自动收敛到平台级 `skills.json`。
- 目前位于工作区外的已有历史目录（例如 `~/.nanobot/workspace/gui_skills/...`）如果想立即物理迁移，我可以再帮你单独执行一次迁移。
