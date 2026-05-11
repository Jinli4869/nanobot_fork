"""
opengui.skills.code_graph_cli
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Standalone CLI for exporting, checking, and compiling code graph source.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Sequence

from opengui.skills.code_first import (
    CANONICAL_CODE_FILENAME,
    CodeSkillExtractor,
    CodeSkillLibrary,
    CodeSkillRepository,
    repair_code_contracts_from_trace,
)
from opengui.skills.code_graph import (
    compile_code_graph,
    compile_code_skills,
    export_graph_to_code,
    export_skill_library_to_code,
    export_skills_to_code,
    render_code_tree,
)
from opengui.skills.code_graph_projection import project_graph_code_from_trace
from opengui.skills.graph import SkillGraphStore


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "export-skills":
        library = CodeSkillLibrary(store_dir=Path(args.store_dir).expanduser())
        source = export_skill_library_to_code(
            library,
            platform=args.platform,
            app=args.app,
        )
        _write_text(args.out, source)
        return 0
    if args.command == "export-graph":
        store = SkillGraphStore(store_dir=Path(args.store_dir).expanduser())
        source = export_graph_to_code(
            store,
            platform=args.platform,
            app=args.app,
        )
        _write_text(args.out, source)
        return 0
    if args.command == "check":
        source = Path(args.source).expanduser().read_text(encoding="utf-8")
        errors = _check_source(source)
        if errors:
            for error in errors:
                print(error)
            return 1
        return 0
    if args.command in {"compile", "compile-graph"}:
        source = Path(args.source).expanduser().read_text(encoding="utf-8")
        store = SkillGraphStore(store_dir=Path(args.store_dir).expanduser())
        result = asyncio.run(compile_code_graph(source, store))
        if result.errors:
            for error in result.errors:
                print(error)
            return 1
        return 0
    if args.command == "tree":
        source = Path(args.source).expanduser().read_text(encoding="utf-8")
        print(render_code_tree(source, format=args.format))
        return 0
    if args.command == "extract":
        return asyncio.run(_extract_to_code(args))
    if args.command == "migrate-json":
        return asyncio.run(_migrate_json_to_code(args))
    parser.error(f"unknown command: {args.command}")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m opengui.skills.code_graph_cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_skills = subparsers.add_parser("export-skills")
    _add_store_filter_args(export_skills)
    export_skills.add_argument("--out", required=True)

    export_graph = subparsers.add_parser("export-graph")
    _add_store_filter_args(export_graph)
    export_graph.add_argument("--out", required=True)

    check = subparsers.add_parser("check")
    check.add_argument("source")

    compile_graph = subparsers.add_parser("compile-graph")
    compile_graph.add_argument("source")
    compile_graph.add_argument("--store-dir", required=True)

    compile_source = subparsers.add_parser("compile")
    compile_source.add_argument("source")
    compile_source.add_argument("--store", "--store-dir", dest="store_dir", required=True)

    tree = subparsers.add_parser("tree")
    tree.add_argument("source")
    tree.add_argument("--format", choices=("text", "mermaid"), default="text")

    extract = subparsers.add_parser("extract")
    extract.add_argument("--trace", required=True)
    extract.add_argument("--out", required=True)
    extract.add_argument("--config")
    extract.add_argument("--platform")
    outcome = extract.add_mutually_exclusive_group()
    outcome.add_argument("--success", action="store_true")
    outcome.add_argument("--failed", action="store_true")

    migrate = subparsers.add_parser("migrate-json")
    _add_store_filter_args(migrate)
    return parser


def _add_store_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--store-dir", required=True)
    parser.add_argument("--platform")
    parser.add_argument("--app")


def _check_source(source: str) -> list[str]:
    errors: list[str] = []
    errors.extend(compile_code_skills(source).errors)
    with tempfile.TemporaryDirectory() as tmp_dir:
        graph_store = SkillGraphStore(store_dir=Path(tmp_dir))
        graph_result = asyncio.run(compile_code_graph(source, graph_store))
    errors.extend(graph_result.errors)
    return list(dict.fromkeys(errors))


def _write_text(path: str, content: str) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


async def _extract_to_code(args: argparse.Namespace) -> int:
    from opengui.cli import DEFAULT_CONFIG_PATH, OpenAICompatibleLLMProvider, load_config

    config_path = Path(args.config).expanduser() if args.config else DEFAULT_CONFIG_PATH
    config = load_config(config_path)
    provider = OpenAICompatibleLLMProvider(
        base_url=config.provider.base_url,
        model=config.provider.model,
        api_key=config.provider.api_key,
    )
    trace_path = Path(args.trace).expanduser()
    out_path = Path(args.out).expanduser()
    is_success = bool(args.success) if args.success or args.failed else _trace_success(trace_path)
    extractor = CodeSkillExtractor(llm=provider)
    repository = CodeSkillRepository(out_path.parent)
    feedback: str | None = None
    errors: list[str] = []

    for _ in range(2):
        extraction = await extractor.extract_from_file(
            trace_path,
            is_success=is_success,
            platform=args.platform,
            feedback=feedback,
        )
        if extraction is None:
            print("no candidate")
            return 1
        repair = repair_code_contracts_from_trace(extraction.python_code, trace_path)
        projection = project_graph_code_from_trace(repair.source, trace_path)
        update = repository.add_code(projection.source)
        if not update.errors:
            if out_path.name != CANONICAL_CODE_FILENAME:
                _write_text(str(out_path), update.source)
            print(str(out_path if out_path.name != CANONICAL_CODE_FILENAME else update.source_path))
            return 0
        errors = list(update.errors)
        feedback = "\n".join(errors)

    for error in errors:
        print(error)
    return 1


async def _migrate_json_to_code(args: argparse.Namespace) -> int:
    store_dir = Path(args.store_dir).expanduser()
    library = _legacy_skill_library(store_dir)
    skills = library.list_all(platform=args.platform, app=args.app)
    if not skills:
        print("no legacy skills")
        return 1

    repository = CodeSkillRepository(store_dir)
    update = repository.add_code(export_skills_to_code(skills))
    if update.errors:
        for error in update.errors:
            print(error)
        return 1

    graph = SkillGraphStore(store_dir=store_dir)
    for skill in update.skills:
        if args.platform and skill.platform != args.platform:
            continue
        if args.app and skill.app != args.app:
            continue
        await graph.ingest_skill(skill)

    migrated_files = []
    if args.app is None:
        migrated_files = _mark_legacy_json_sources(store_dir, platform=args.platform)
    _write_migration_manifest(
        store_dir,
        source_path=update.source_path,
        migrated_files=migrated_files,
        skill_ids=[skill.skill_id for skill in skills],
        filtered=bool(args.platform or args.app),
    )
    print(str(update.source_path))
    return 0


def _legacy_skill_library(store_dir: Path) -> Any:
    from opengui.skills.legacy_json import SkillLibrary as LegacySkillLibrary

    return LegacySkillLibrary(store_dir=store_dir)


def _mark_legacy_json_sources(store_dir: Path, *, platform: str | None = None) -> list[str]:
    files = _legacy_skill_json_files(store_dir, platform=platform)
    migrated: list[str] = []
    for source in files:
        target = _legacy_target_path(source)
        os.replace(source, target)
        embeddings = source.with_name("embeddings.npy")
        if embeddings.exists():
            os.replace(embeddings, _legacy_target_path(embeddings))
        migrated.append(str(target))
    return migrated


def _legacy_skill_json_files(store_dir: Path, *, platform: str | None = None) -> list[Path]:
    if platform:
        candidates = [store_dir / platform / "skills.json"]
    else:
        candidates = sorted(store_dir.glob("*/skills.json"))
    return [path for path in candidates if path.is_file()]


def _legacy_target_path(source: Path) -> Path:
    if source.suffix:
        base = source.with_name(f"{source.stem}.legacy{source.suffix}")
    else:
        base = source.with_name(f"{source.name}.legacy")
    target = base
    index = 2
    while target.exists():
        if source.suffix:
            target = source.with_name(f"{source.stem}.legacy.{index}{source.suffix}")
        else:
            target = source.with_name(f"{source.name}.legacy.{index}")
        index += 1
    return target


def _write_migration_manifest(
    store_dir: Path,
    *,
    source_path: Path,
    migrated_files: list[str],
    skill_ids: list[str],
    filtered: bool,
) -> None:
    manifest = {
        "version": 1,
        "timestamp": int(time.time()),
        "canonical_source": str(source_path),
        "legacy_files": migrated_files,
        "skill_ids": skill_ids,
        "filtered": filtered,
    }
    _write_text(str(store_dir / "legacy_json_migration.json"), json.dumps(manifest, ensure_ascii=False, indent=2))


def _trace_success(trace_path: Path) -> bool:
    try:
        lines = trace_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except Exception:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            return bool(event.get("success") or event.get("status") == "succeeded")
    return False


if __name__ == "__main__":
    raise SystemExit(main())
