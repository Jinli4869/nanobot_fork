---
name: android-deeplink-prober
description: Probe Android app deep links with adb and dumpsys, then return a compact summary of viable URIs, partial matches, and next candidates for the main agent.
metadata: {"nanobot":{"emoji":"🔗","os":["darwin","linux"],"requires":{"bins":["adb","python3"]}}}
---

# Android Deep Link Prober

Use this skill when a task needs to reach an Android app state quickly through `adb`, especially when the route is likely a deep link or web/app link.

## Best fit

- The user gives a task like "open search with keyword", "jump to note detail", or "see whether this app exposes an app link".
- You know the package name, or can discover it from surrounding context.
- You want fast exploration without dumping raw `adb` noise back into the main thread.

## Workflow

1. Gather:
   - package name
   - task goal in one short phrase
   - optional device serial
   - optional known schemes, hosts, or seed URIs
2. Run the helper in `fast` mode first.
3. If fast mode finds only partial matches or browser fallbacks, rerun in `investigate` mode.
4. Return only the structured findings:
   - viable URIs
   - partial matches
   - invalid candidates
   - next 3-5 tries
   - whether `dumpsys` suggests app-link/domain issues

## Helper script

Primary entrypoint:

```bash
python3 nanobot/skills/android-deeplink-prober/scripts/probe_deeplinks.py \
  --package com.example.app \
  --task "open search with keyword" \
  --mode fast \
  --no-exec
```

Run against a device:

```bash
python3 nanobot/skills/android-deeplink-prober/scripts/probe_deeplinks.py \
  --package com.example.app \
  --task "open search with keyword" \
  --serial emulator-5554 \
  --mode fast
```

Investigate with known seeds:

```bash
python3 nanobot/skills/android-deeplink-prober/scripts/probe_deeplinks.py \
  --package com.example.app \
  --task "open note detail" \
  --mode investigate \
  --scheme appname \
  --host example.com \
  --candidate-uri 'appname://note/123' \
  --candidate-uri 'https://example.com/note/123'
```

## Output contract

Prefer `--format json` when another agent or tool will consume the result. The helper emits:

- `inputs`: normalized task and seed data
- `probes`: candidate URI checks with command, status, and short evidence
- `system_checks`: `dumpsys` commands and any notable findings
- `summary`: best candidates, partial matches, invalid candidates, and recommended next tries

## Modes

- `fast`: small, high-probability candidate set. Use this by default to reach a useful app state quickly.
- `investigate`: broader candidate expansion plus deeper `dumpsys` guidance. Use when fast mode stalls.

## Agent guidance

- Start with `--no-exec` if you only need candidate generation or are unsure a device is connected.
- Avoid pasting long shell output into the conversation. Summarize with the helper's `summary`.
- Treat `http/https` results separately from custom schemes. Browser fallback often means app-link verification or domain approval is missing, not that the path is wrong.
- If you need deeper Android routing guidance, read [references/android-deeplink-method.md](references/android-deeplink-method.md).
