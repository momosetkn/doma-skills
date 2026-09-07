#!/usr/bin/env python3
"""Plan and safely apply database-authoritative Doma entity synchronization."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from entity_sync.applier import ApplyError, StalePlanError, UnsafeProjectError, apply_plan
from entity_sync.planner import (
    PlanInputError,
    build_plan,
    load_plan,
    plan_json,
    render_diff,
    result_state,
)


EXIT = {
    "SUCCESS": 0,
    "PENDING_REVIEW": 2,
    "BLOCKED": 3,
}


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise PlanInputError("invalid command-line input")


def parser() -> argparse.ArgumentParser:
    root = Parser(prog="compare-and-merge-entities.py")
    commands = root.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--project-root", required=True)
    plan.add_argument("--schema-snapshot", required=True)
    plan.add_argument("--generated-dir", required=True)
    plan.add_argument("--existing-root", action="append", required=True)
    plan.add_argument("--language", choices=("java", "kotlin", "auto"), default="auto")
    plan.add_argument("--output-plan", required=True)
    plan.add_argument("--output-diff", required=True)
    apply = commands.add_parser("apply")
    apply.add_argument("--project-root", required=True)
    apply.add_argument("--plan", required=True)
    apply.add_argument("--approve", action="append", default=[])
    return root


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        if args.command == "plan":
            merge_plan = build_plan(
                args.project_root,
                args.schema_snapshot,
                args.generated_dir,
                tuple(args.existing_root),
                args.language,
            )
            _write_output(args.project_root, args.output_plan, plan_json(merge_plan))
            _write_output(args.project_root, args.output_diff, render_diff(merge_plan))
            state = result_state(merge_plan)
            print(state)
            return EXIT[state]
        merge_plan = load_plan(args.plan)
        result = apply_plan(args.project_root, merge_plan, approvals=args.approve)
        print(result.state)
        return EXIT[result.state]
    except PlanInputError:
        print("entity merge: invalid input", file=sys.stderr)
        return 64
    except UnsafeProjectError:
        print("entity merge: unsafe project state", file=sys.stderr)
        return 65
    except StalePlanError:
        print("entity merge: stale plan", file=sys.stderr)
        return 66
    except (ApplyError, OSError):
        print("entity merge: operation failed", file=sys.stderr)
        return 1
    except Exception:
        # Parser, filesystem, and JSON exception strings may contain source or credential values.
        print("entity merge: operation failed", file=sys.stderr)
        return 1


def _write_output(project_root: str, output: str, text: str) -> None:
    root = Path(project_root)
    if not root.is_absolute():
        root = Path.cwd() / root
    root = root.resolve()
    target = Path(output)
    if not target.is_absolute():
        target = root / target
    target = Path(os.path.abspath(str(target)))
    allowed = root / "build/doma-codegen"
    if os.path.commonpath((str(allowed), str(target))) != str(allowed):
        raise PlanInputError("output must stay inside build/doma-codegen")
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise PlanInputError("output must not traverse symbolic links")
        if not current.exists():
            break
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".entity-merge-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
