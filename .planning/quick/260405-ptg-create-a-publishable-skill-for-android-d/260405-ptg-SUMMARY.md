# Quick Task 260405-ptg Summary

## Outcome

Created a publishable built-in skill at `nanobot/skills/android-deeplink-prober` for quickly probing Android deep links with `adb` and `dumpsys` while keeping the main agent payload compact.

The skill now provides:

- A concise `SKILL.md` that tells the agent when to use fast vs investigate probing.
- A deterministic helper script, `scripts/probe_deeplinks.py`, that:
  - derives candidate URIs from package name, task wording, and optional seeds
  - supports `fast` and `investigate` modes
  - can run in `--no-exec` dry-run mode when no device is attached
  - emits structured JSON or compact text summaries instead of raw shell noise
- A reference file, `references/android-deeplink-method.md`, that keeps the heavier routing heuristics out of the main skill body.

## Main-Agent Fit

This version is tuned to reduce main-agent burden:

- The agent can ask for a task like "open search with keyword" and get back a small candidate set immediately.
- `fast` mode prioritizes a short list of high-probability custom schemes plus a few `https` candidates when hosts are known.
- `investigate` mode expands coverage and surfaces the `dumpsys` commands needed for route and domain-policy analysis.
- The helper returns a distilled `summary` section with:
  - `best_candidates`
  - `partial_matches`
  - `invalid_candidates`
  - `next_tries`

## Verification

Passed:

```bash
PYTHONPYCACHEPREFIX=/tmp/nanobot_pycache python3 -m py_compile nanobot/skills/android-deeplink-prober/scripts/probe_deeplinks.py
python3 nanobot/skills/android-deeplink-prober/scripts/probe_deeplinks.py --package com.example.search --task "open search with keyword" --mode fast --host example.com --no-exec --format json
python3 nanobot/skills/android-deeplink-prober/scripts/probe_deeplinks.py --package com.example.notes --task "open note detail" --mode investigate --scheme notes --host notes.example.com --candidate-uri 'notes://note/123' --no-exec --format text
```

Notable behavior confirmed:

- Dry-run mode produces candidate `adb am start` commands and `dumpsys` follow-ups without requiring a device.
- `fast` mode now reserves room for explicit web-link candidates so known hosts are not crowded out by custom-scheme guesses.
- `investigate` mode includes both custom-scheme and `https` candidates when explicit seeds are present.
