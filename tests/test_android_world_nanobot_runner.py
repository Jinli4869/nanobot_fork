from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_runner_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_android_world_nanobot.py"
    spec = importlib.util.spec_from_file_location("run_android_world_nanobot", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_route_classification_uses_android_world_families_and_adb_allowlist():
    runner = _load_runner_module()

    assert runner._classify_route("SystemWifiTurnOn", registry_family="android") == "adb"
    assert runner._classify_route("OpenAppTaskEval", registry_family="android") == "adb"
    assert runner._classify_route("NotesIsTodo", registry_family="information_retrieval") == "gui"
    assert runner._classify_route("ContactsAddContact", registry_family="android") == "gui"


def test_route_overrides_can_reclassify_one_task():
    runner = _load_runner_module()
    overrides = runner._route_overrides({"routes": {"adb": ["ContactsAddContact"]}})

    assert runner._classify_route("ContactsAddContact", registry_family="android", overrides=overrides) == "adb"


def test_route_overrides_can_opt_into_info_route():
    runner = _load_runner_module()
    overrides = runner._route_overrides({"routes": {"info": ["NotesIsTodo"]}})

    assert runner._classify_route("NotesIsTodo", registry_family="information_retrieval", overrides=overrides) == "info"


def test_max_steps_uses_android_world_complexity_by_default():
    runner = _load_runner_module()

    class Task:
        complexity = 2.5

    assert runner._max_steps_for_task(
        Task(),
        None,
        mode="complexity",
        steps_per_complexity=10,
        optimal_multiplier=1.5,
        override=None,
    ) == 25


def test_max_steps_can_use_metadata_optimal_steps():
    runner = _load_runner_module()
    item = runner.RegistryItem(
        name="ContactsAddContact",
        route="gui",
        registry_family="android",
        optimal_steps=5,
    )

    assert runner._max_steps_for_task(
        object(),
        item,
        mode="optimal",
        steps_per_complexity=10,
        optimal_multiplier=1.5,
        override=None,
    ) == 8
