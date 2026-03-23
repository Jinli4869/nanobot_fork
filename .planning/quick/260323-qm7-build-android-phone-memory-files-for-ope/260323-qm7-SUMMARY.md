---
phase: quick-260323-qm7
plan: 01
subsystem: opengui-memory
tags: [memory, android, mobile, chinese-apps, icon-guide, policy]
dependency_graph:
  requires: []
  provides: [android-os-memory, android-app-memory, icon-guide, policy]
  affects: [opengui-memory-store, opengui-agent-context]
tech_stack:
  added: []
  patterns: [H2-section-markdown-memory-format]
key_files:
  created:
    - /Users/jinli/.opengui/memory/icon_guide.md
    - /Users/jinli/.opengui/memory/policy.md
  modified:
    - /Users/jinli/.opengui/memory/os_guide.md
    - /Users/jinli/.opengui/memory/app_guide.md
decisions:
  - "H2 sub-headings inside entry content must be replaced with plain text or lower-level headings to avoid MemoryStore parser splitting them as separate sections"
  - "tmp_ files contain entries already suitable for Android platform; converted 2 existing Android entries from tmp_os_guide.md alongside adding 15 new Android entries"
  - "Chinese app entries use platform: android (not universal) because the apps are primarily used on Android phones"
  - "通用 (generic) app guide entries use platform: universal since they apply to all platforms"
metrics:
  duration: 10
  completed_date: "2026-03-23"
---

# Quick Task 260323-qm7: Build Android Phone Memory Files for OpenGUI

**One-liner:** 86-entry parseable memory store covering 17 Android OS operations, 35 Android app guides (15 Chinese apps), 10 icon semantics, and 8 safety policies — migrated from tmp_ files and extended with comprehensive new content.

## What Was Built

Four fully-formatted memory files parseable by `MemoryStore._parse_section()`, containing:

| File | Entries | Highlights |
|------|---------|-----------|
| `os_guide.md` | 30 | 17 Android + 5 Windows + 4 iPhone + 4 macOS OS guide entries |
| `app_guide.md` | 38 | 35 Android + 2 universal + 1 macOS/browser app guide entries |
| `icon_guide.md` | 10 | New file: gear, magnifier, three-dots, paper-plane, arrow, house, bell, plus, avatar, trash |
| `policy.md` | 8 | New file: no-payment, no-permissions, no-auto-send, no-delete-data, no-modify-security, no-unclear-popup, high-risk-confirm, search-first |

**Total: 86 entries, 0 parse failures, 0 duplicates, 0 empty-content entries.**

## Tasks Completed

### Task 1: Create icon_guide.md, policy.md, and update os_guide.md
- Converted 10 icon entries from `tmp_icon_guide.md` into proper MemoryStore format with `type: icon`, `platform: universal` metadata
- Converted 8 policy entries from `tmp_policy.md` into proper MemoryStore format with `type: policy`, `platform: universal` metadata
- Preserved existing macOS shortcuts entry in `os_guide.md` (with content H2 sub-heading fixed — see Deviations)
- Added 13 entries from `tmp_os_guide.md` (5 Windows, 4 iPhone, 2 macOS, 2 Android)
- Added 15 new Android OS guide entries: quick-settings, system-settings, app-permissions, screenshot, split-screen, gesture-navigation, storage, battery, developer-options, accessibility, accounts, about-phone, install-uninstall, power, screen-record

### Task 2: Add Android app guide entries to app_guide.md
- Preserved existing browser hotkeys entry (with content H2 sub-heading fixed — see Deviations)
- Converted 12 entries from `tmp_app_guide.md` (2 generic, 3 Gaode Maps, 3 Meituan, 4 Xiaohongshu)
- Added 25 new Android app guide entries covering: WeChat (6 entries), Alipay (3), Taobao (3), Douyin (3), Baidu Maps (2), 12306 (2), Didi (1), Meituan Waimai (1), Bilibili (2), Ele.me (1), Pinduoduo (1)

### Task 3: Full store parse validation
- All 86 entries load and parse without errors
- Zero duplicate entry IDs
- Zero entries with empty content
- All platform values in expected set (macos, windows, ios, android, universal)
- Type values match file expectations (os/app/icon/policy)
- tmp_ files confirmed to have all content migrated; not deleted (per plan)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed H2 sub-headings inside entry content**

- **Found during:** Task 3 validation
- **Issue:** The existing `os_guide.md` macOS entry contained `## MacOS-快捷键` in its content body, and the `app_guide.md` browser entry contained `## browser-hotkeys` in its content body. The MemoryStore parser splits files on `^## ` (multiline regex), so these internal H2 headings were being split into separate malformed sections, causing the parent entries to have empty `content` fields.
- **Fix:** Replaced `## MacOS-快捷键` with `macOS 快捷键列表：` (plain text) and `## browser-hotkeys` with `浏览器快捷键列表：` (plain text). Content semantics fully preserved.
- **Files modified:** `/Users/jinli/.opengui/memory/os_guide.md`, `/Users/jinli/.opengui/memory/app_guide.md`
- **Commit:** 3608ed9

## Self-Check

Verifying claims:

- icon_guide.md exists with 10 entries: PASS (verified by MemoryStore: 10 icon entries)
- policy.md exists with 8 entries: PASS (verified by MemoryStore: 8 policy entries)
- os_guide.md has 30 entries (17 Android): PASS
- app_guide.md has 38 entries (35 Android): PASS
- Total 86 entries, 0 duplicates, 0 empty content: PASS
- All assertions in Task 1, Task 2, Task 3 verify scripts: PASS

## Self-Check: PASSED
