#!/usr/bin/env python3
"""Unified CLI entrypoint (`seo-os`) and JSON Schema validator for SEO Growth OS."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import jsonschema

SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def validate_json_against_schema(payload: Any, schema_name: str) -> tuple[bool, list[str]]:
    """Validates a JSON payload against schemas/<schema_name>."""
    schema_path = SKILL_ROOT / "schemas" / schema_name
    if not schema_path.exists():
        return False, [f"Missing schema: {schema_path}"]
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)
    errors = [f"{'.'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in validator.iter_errors(payload)]
    return len(errors) == 0, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Unified CLI for improve-seo-with-data (seo-os).")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("collect", "train", "score", "plan", "verify", "evaluate", "rewarm", "gate", "audit", "doctor"):
        sub.add_parser(name, help=f"Run {name} stage")

    val = sub.add_parser("validate-schema", help="Validate JSON artifact against schemas/*.json")
    val.add_argument("--file", default="", help="JSON file to validate")
    val.add_argument("--schema", default="", choices=["", "seo-action.schema.json", "data-source-manifest.schema.json"])
    val.add_argument("--queue", default="", help="Action queue file validated against seo-action.schema.json")
    val.add_argument("--manifest", default="", help="Observability manifest file validated against data-source-manifest.schema.json")

    # Stage flags are deliberately not declared here: the delegated script
    # owns their parser. Parse the command, then forward every unknown flag.
    args, unknown = parser.parse_known_args(argv)
    if args.command != "validate-schema":
        args.extra = list(unknown)
    if args.command == "validate-schema":
        targets: list[tuple[str, str]] = []
        if args.file and args.schema:
            targets.append((args.file, args.schema))
        if args.queue:
            targets.append((args.queue, "seo-action.schema.json"))
        if args.manifest:
            targets.append((args.manifest, "data-source-manifest.schema.json"))
        if not targets:
            print("[FAIL] Provide --file + --schema, or --queue / --manifest")
            return 2
        all_ok = True
        for fpath, sname in targets:
            payload = json.loads(Path(fpath).read_text(encoding="utf-8"))
            ok, errors = validate_json_against_schema(payload, sname)
            if not ok:
                all_ok = False
                for err in errors:
                    print(f"[FAIL] {fpath} ({sname}): {err}")
            else:
                print(f"[OK] {fpath} matches schemas/{sname}")
        return 0 if all_ok else 1

    dispatch = {
        "collect": "collect_features",
        "train": "train_ranker",
        "score": "score_backlog",
        "plan": "growth_loop",
        "verify": "verify_technical_seo",
        "evaluate": "evaluate_experiments",
        "rewarm": "improve_seo_rewarm",
        "gate": "run_wave_gate",
        "audit": "run_audit",
        "doctor": "verify_mcp",
    }
    mod = __import__(dispatch[args.command])
    extra = list(args.extra)
    if extra and extra[0] == "--":
        extra = extra[1:]
    if dispatch[args.command] in ("run_wave_gate", "run_audit", "verify_mcp"):
        sys.argv = [dispatch[args.command], *extra]
        res = mod.main()
        return int(res or 0)
    if dispatch[args.command] == "growth_loop":
        # growth_loop owns a subcommand parser (plan/record/complete/...).
        extra = [args.command, *extra]
    return int(mod.main(extra) or 0)


if __name__ == "__main__":
    sys.exit(main())
