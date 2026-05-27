from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from opengui.skills.deeplink import AppShortcutProfile, DeepIntent, DeepLink


def _load_validator_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "validate_shortcut_cache.py"
    spec = importlib.util.spec_from_file_location("validate_shortcut_cache", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validator = _load_validator_module()


def test_candidate_records_prioritize_search_and_skip_risky() -> None:
    profile = AppShortcutProfile(
        package="tv.danmaku.bili",
        deep_links=(
            DeepLink(
                uri_template="bilibili://bilipay/bcoin/recharge",
                scheme="bilibili",
                host="bilipay",
                path="/bcoin/recharge",
                component="tv.danmaku.bili/.Router",
                description="pay route",
            ),
            DeepLink(
                uri_template="bilibili://search",
                scheme="bilibili",
                host="search",
                path=None,
                component="tv.danmaku.bili/.Router",
                description="search route",
            ),
        ),
        deep_intents=(
            DeepIntent(
                action="android.intent.action.SEARCH",
                component="tv.danmaku.bili/.SearchActivity",
                description="search intent",
            ),
        ),
    )

    records = validator.candidate_records(profile, include_risky=False)

    assert [record.kind for record in records] == ["deeplink", "intent"]
    assert records[0].uri_template == "bilibili://search"


def test_candidate_records_do_not_treat_livehome_as_home_route() -> None:
    profile = AppShortcutProfile(
        package="tv.danmaku.bili",
        deep_links=(
            DeepLink(
                uri_template="bilibili://search",
                scheme="bilibili",
                host="search",
                path=None,
                component="tv.danmaku.bili/.Router",
                description="search route",
            ),
        ),
        deep_intents=(
            DeepIntent(
                action="android.intent.action.SEARCH",
                component="tv.danmaku.bili/com.bilibili.bililive.videoliveplayer.ui.live.home.LiveHomeActivity",
                description="live search",
            ),
        ),
    )

    records = validator.candidate_records(profile, include_risky=False)

    assert records[0].kind == "deeplink"
    assert records[0].uri_template == "bilibili://search"


def test_build_probe_plans_generates_search_plan_for_youtube() -> None:
    profile = AppShortcutProfile(
        package="com.google.android.youtube",
        deep_links=(),
        deep_intents=(
            DeepIntent(
                action="android.intent.action.SEARCH",
                component="com.google.android.youtube/.ResultsActivity",
                description="YouTube search",
            ),
        ),
    )
    args = SimpleNamespace(task="", query="", include_risky=False, max_candidates=8, max_try=6)

    plans = validator.build_probe_plans(profile, args)

    assert plans[0].capability == "search"
    assert plans[0].query == "Never Gonna Give You Up"
    assert "YouTube 搜索" in plans[0].task
    assert plans[0].candidate_limit == 8
    assert plans[0].variant_limit == 6


def test_build_probe_plans_uses_bilibili_default_query() -> None:
    profile = AppShortcutProfile(
        package="tv.danmaku.bili",
        deep_links=(
            DeepLink(
                uri_template="bilibili://search",
                scheme="bilibili",
                host="search",
                path=None,
                component="tv.danmaku.bili/.Router",
                description="search route",
            ),
        ),
    )
    args = SimpleNamespace(task="", query="", include_risky=False, max_candidates=5, max_try=4)

    plans = validator.build_probe_plans(profile, args)

    assert plans[0].capability == "search"
    assert plans[0].query == "敢杀我的马"


def test_build_probe_plans_manual_override_keeps_user_payload() -> None:
    profile = AppShortcutProfile(
        package="com.google.android.youtube",
        deep_intents=(
            DeepIntent(
                action="android.intent.action.SEARCH",
                component="com.google.android.youtube/.ResultsActivity",
                description="search",
            ),
        ),
    )
    args = SimpleNamespace(
        task="验证 YouTube 自定义搜索",
        query="lofi hip hop",
        include_risky=False,
        max_candidates=3,
        max_try=2,
    )

    plans = validator.build_probe_plans(profile, args)

    assert plans == [
        validator.ProbePlan(
            capability="manual",
            task="验证 YouTube 自定义搜索",
            query="lofi hip hop",
            candidate_limit=3,
            variant_limit=2,
        )
    ]


def test_search_probe_plan_filters_account_linking_candidate() -> None:
    plan = validator.ProbePlan(
        capability="search",
        task="验证 YouTube 搜索",
        query="Never Gonna Give You Up",
        candidate_limit=8,
        variant_limit=6,
    )
    account_linking = validator.Candidate(
        index=0,
        kind="deeplink",
        package="com.google.android.youtube",
        description="account linking",
        uri_template="vnd.youtube.gdi:",
        component="com.google.android.youtube/.AccountLinkingActivity",
    )
    search = validator.Candidate(
        index=1,
        kind="intent",
        package="com.google.android.youtube",
        description="search",
        action="android.intent.action.SEARCH",
        component="com.google.android.youtube/.ResultsActivity",
    )

    assert validator.candidate_matches_plan(account_linking, plan) is False
    assert validator.candidate_matches_plan(search, plan) is True


def test_open_page_probe_plan_does_not_duplicate_search_candidates() -> None:
    plan = validator.ProbePlan(
        capability="open_page",
        task="验证 YouTube 页面",
        query="",
        candidate_limit=8,
        variant_limit=6,
    )
    search_play = validator.Candidate(
        index=1,
        kind="intent",
        package="com.google.android.youtube",
        description="play from search",
        action="android.media.action.MEDIA_PLAY_FROM_SEARCH",
        component="com.google.android.youtube/.MediaSearchActivity",
    )
    watch = validator.Candidate(
        index=2,
        kind="deeplink",
        package="com.google.android.youtube",
        description="watch video",
        uri_template="vnd.youtube:",
        component="com.google.android.youtube/.UrlActivity",
    )

    assert validator.candidate_matches_plan(search_play, plan) is False
    assert validator.candidate_matches_plan(watch, plan) is True


def test_deeplink_variants_include_encoded_chinese_query() -> None:
    candidate = validator.Candidate(
        index=0,
        kind="deeplink",
        package="tv.danmaku.bili",
        description="search",
        uri_template="bilibili://search",
        component="tv.danmaku.bili/.Router",
    )

    variants = validator.variants_for_deeplink(candidate, query="敢杀我的马", max_try=6)

    assert variants[0].label == "raw_package"
    assert variants[1].label == "raw_component"
    assert any("%E6%95%A2%E6%9D%80%E6%88%91%E7%9A%84%E9%A9%AC" in (variant.uri or "") for variant in variants)
    assert all(variant.package == "tv.danmaku.bili" for variant in variants)


def test_deeplink_variants_plus_encoding_with_space() -> None:
    candidate = validator.Candidate(
        index=0,
        kind="deeplink",
        package="tv.danmaku.bili",
        description="search",
        uri_template="bilibili://search",
        component="tv.danmaku.bili/.Router",
    )

    variants = validator.variants_for_deeplink(candidate, query="phone 壳", max_try=12)

    assert any("phone+%E5%A3%B3" in (variant.uri or "") for variant in variants)


def test_intent_variants_include_query_extras() -> None:
    candidate = validator.Candidate(
        index=1,
        kind="intent",
        package="tv.danmaku.bili",
        description="search",
        action="android.intent.action.SEARCH",
        component="tv.danmaku.bili/.SearchActivity",
    )

    variants = validator.variants_for_intent(candidate, query="敢杀我的马", max_try=5)

    assert variants[0].label == "component_no_extra"
    assert any(("query", "敢杀我的马") in variant.extras for variant in variants)
    assert any(variant.component is None for variant in variants)


def test_parse_json_object_accepts_fenced_json() -> None:
    parsed = validator.parse_json_object(
        """```json
        {"usable": true, "status": "page_validated", "description": "B站搜索视频"}
        ```"""
    )

    assert parsed["usable"] is True
    assert parsed["description"] == "B站搜索视频"


def test_result_to_validation_record_for_intent() -> None:
    candidate = validator.Candidate(
        index=1,
        kind="intent",
        package="tv.danmaku.bili",
        description="search",
        action="android.intent.action.SEARCH",
        component="tv.danmaku.bili/.SearchActivity",
    )
    result = validator.ProbeResult(
        candidate=candidate,
        status="page_validated",
        description="B站搜索视频",
        parameters=["query"],
        best_variant={
            "label": "component_extra_query",
            "kind": "intent",
            "package": "tv.danmaku.bili",
            "action": "android.intent.action.SEARCH",
            "component": "tv.danmaku.bili/.SearchActivity",
            "extras": [["query", "{{query}}"]],
        },
    )

    record = validator.result_to_validation_record(result)

    assert record == {
        "package": "tv.danmaku.bili",
        "kind": "intent",
        "status": "page_validated",
        "description": "B站搜索视频",
        "parameters": ["query"],
        "valid_state": "B站搜索视频",
        "intent_action": "android.intent.action.SEARCH",
        "extras": [["query", "{{query}}"]],
        "component": "tv.danmaku.bili/.SearchActivity",
    }


def test_result_to_validation_record_templates_query_payload() -> None:
    candidate = validator.Candidate(
        index=1,
        kind="intent",
        package="tv.danmaku.bili",
        description="search",
        action="android.intent.action.SEARCH",
        component="tv.danmaku.bili/.SearchActivity",
    )
    result = validator.ProbeResult(
        candidate=candidate,
        status="page_validated",
        description="B站搜索视频",
        parameters=["query=敢杀我的马"],
        best_variant={
            "label": "component_extra_query",
            "kind": "intent",
            "package": "tv.danmaku.bili",
            "action": "android.intent.action.SEARCH",
            "component": "tv.danmaku.bili/.SearchActivity",
            "extras": [["query", "敢杀我的马"]],
        },
    )

    record = validator.result_to_validation_record(result, query="敢杀我的马")

    assert record["parameters"] == ["query"]
    assert record["extras"] == [["query", "{{query}}"]]


def test_result_to_validation_record_drops_unused_query_parameter() -> None:
    candidate = validator.Candidate(
        index=0,
        kind="deeplink",
        package="tv.danmaku.bili",
        description="search",
        uri_template="bilibili://search",
    )
    result = validator.ProbeResult(
        candidate=candidate,
        status="page_validated",
        description="打开B站搜索页",
        parameters=["query=敢杀我的马"],
        best_variant={
            "label": "raw_package",
            "kind": "deeplink",
            "package": "tv.danmaku.bili",
            "uri": "bilibili://search",
        },
    )

    record = validator.result_to_validation_record(result, query="敢杀我的马")

    assert record["parameters"] == []
    assert record["uri_template"] == "bilibili://search"


def test_write_sidecar_records_probe_plan(tmp_path: Path) -> None:
    profile = AppShortcutProfile(package="tv.danmaku.bili")
    plan = validator.ProbePlan(
        capability="search",
        task="验证 B站搜索",
        query="敢杀我的马",
        candidate_limit=5,
        variant_limit=4,
    )
    result = validator.ProbeResult(
        candidate=validator.Candidate(
            index=0,
            kind="deeplink",
            package="tv.danmaku.bili",
            description="search",
            uri_template="bilibili://search",
        ),
        status="page_validated",
        description="B站搜索视频",
        parameters=["query"],
        best_variant={
            "label": "keyword_raw",
            "kind": "deeplink",
            "package": "tv.danmaku.bili",
            "uri": "bilibili://search?keyword=敢杀我的马",
        },
        probe_plan=validator.probe_plan_to_dict(plan),
    )
    args = SimpleNamespace(
        serial="emulator-5554",
        cache=Path("shortcut_cache/tv.danmaku.bili.json"),
        task="",
        query="",
        execute=True,
        llm_model="qwen-vl-plus",
    )
    path = tmp_path / "sidecar.json"

    validator.write_sidecar(
        path=path,
        profile=profile,
        args=args,
        results=[result],
        promotions=[],
        probe_plans=[plan],
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["probe_plans"] == [validator.probe_plan_to_dict(plan)]
    assert data["results"][0]["probe_plan"] == validator.probe_plan_to_dict(plan)
    assert data["results"][0]["validation_record"]["uri_template"] == "bilibili://search?keyword={{query}}"


def test_launch_variant_skips_evidence_capture_when_disabled(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    class FakeAdb:
        def run(self, *args, timeout=10.0):
            calls.append(" ".join(args))
            return 0, "Status: ok", False

    monkeypatch.setattr(validator, "foreground_activity", lambda adb: "tv.danmaku.bili/.SearchActivity")
    monkeypatch.setattr(validator, "capture_screenshot", lambda adb, path: (_ for _ in ()).throw(AssertionError("screenshot")))
    monkeypatch.setattr(validator, "capture_ui_tree", lambda adb: (_ for _ in ()).throw(AssertionError("ui tree")))

    result = validator.launch_variant(
        FakeAdb(),
        validator.Variant(
            label="raw",
            kind="deeplink",
            package="tv.danmaku.bili",
            uri="bilibili://search",
        ),
        artifacts_dir=tmp_path,
        index=1,
        capture_evidence=False,
        settle_seconds=0,
    )

    assert result["target_package"] is True
    assert result["screenshot_path"] is None
    assert result["ui_tree"] == ""
    assert len(calls) == 2


def test_validate_candidate_breaks_after_launchable_without_verifier(monkeypatch, tmp_path: Path) -> None:
    candidate = validator.Candidate(
        index=0,
        kind="deeplink",
        package="tv.danmaku.bili",
        description="search",
        uri_template="bilibili://search",
    )
    args = SimpleNamespace(
        query="敢杀我的马",
        max_try=5,
        execute=True,
        llm_base_url="",
        llm_model="",
    )
    launched: list[str] = []

    monkeypatch.setattr(validator, "resolve_variant", lambda adb, variant: {"ok": True})

    def fake_launch(adb, variant, *, artifacts_dir, index, capture_evidence=False, settle_seconds=2.0):
        launched.append(variant.label)
        assert capture_evidence is False
        return {"target_package": True, "foreground": "tv.danmaku.bili/.SearchActivity"}

    monkeypatch.setattr(validator, "launch_variant", fake_launch)

    result = validator.validate_candidate(object(), candidate, args=args, artifacts_dir=tmp_path)

    assert result.status == "launchable"
    assert launched == ["raw_package"]


def test_verify_with_llm_returns_verifier_error_on_api_exception(monkeypatch) -> None:
    class FailingCompletions:
        def create(self, **kwargs):
            raise RuntimeError("rate limit")

    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FailingCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=Client))

    verdict = validator.verify_with_llm(
        base_url="http://example.test/v1",
        model="test",
        api_key="test",
        temperature=0.0,
        task="test",
        candidate=validator.Candidate(index=0, kind="deeplink", package="pkg", description="desc"),
        variant=validator.Variant(label="raw", kind="deeplink", package="pkg", uri="x://y"),
        launch={"foreground": "pkg/.A"},
    )

    assert verdict["usable"] is False
    assert verdict["status"] == "verifier_error"
