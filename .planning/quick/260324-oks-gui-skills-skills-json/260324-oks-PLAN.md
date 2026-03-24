# Quick Task 260324-oks Plan

**Description:** 简化 `gui_skills` 目录结构为每个平台单一 `skills.json` 聚合文件。  
**Date:** 2026-03-24  
**Mode:** quick

## Objective

把 GUI skills 的持久化结构从 `gui_skills/<platform>/<app>/skills.json` 改为 `gui_skills/<platform>/skills.json`，减少不必要的目录层级，让同平台技能天然聚合到一个 JSON 文件中，方便检索、浏览和后续管理。

## Constraints

- 保持 `SkillLibrary` 现有检索、过滤、合并语义不变。
- 兼容已有历史技能目录，不能因为新结构导致旧技能读不出来。
- 新写入路径应能顺带清理同平台的旧版子目录 `skills.json`，避免继续残留多一级目录。

## Tasks

1. 调整 `SkillLibrary` 持久化策略
   - 将平台内技能统一写到 `gui_skills/<platform>/skills.json`
   - `add` / `add_or_merge` / `update` / `remove` 都切到平台级落盘

2. 保留旧结构兼容读取
   - 在没有平台级聚合文件时，继续读取旧版 `gui_skills/<platform>/<app>/skills.json`
   - 若平台级文件已存在，则优先使用聚合文件，避免被过期子目录覆盖

3. 更新测试并验证
   - 调整现有路径断言到平台级文件
   - 增加旧目录兼容加载回归测试
   - 运行针对 `SkillLibrary` 与 `GuiSubagentTool` 的验证

## Verification

- `uv run pytest tests/test_opengui_p1_skills.py tests/test_opengui_p3_nanobot.py -q`
- `uv run python -m py_compile opengui/skills/library.py nanobot/agent/tools/gui.py opengui/skills/extractor.py`
