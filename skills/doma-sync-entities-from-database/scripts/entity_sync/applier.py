"""Stale-safe, byte-preserving application of entity synchronization plans."""
from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .model import SourceSpan
from .planner import (
    PLAN_FORMAT_VERSION,
    SNAPSHOT_PATH,
    Edit,
    Finding,
    MergePlan,
    PlanInputError,
    _finding_id,
    contains_sensitive,
    load_plan,
    result_state,
)


class ApplyError(RuntimeError):
    """Raised when a prepared source update cannot be completed."""


class UnsafeProjectError(ApplyError):
    """Raised before writing when the project is not a safe apply target."""


class StalePlanError(ApplyError):
    """Raised before writing when any planned input has changed."""


@dataclass(frozen=True)
class ApplyResult:
    state: str
    applied: tuple[str, ...]
    pending_review: tuple[str, ...]
    blocked: tuple[str, ...]


@dataclass(frozen=True)
class _Prepared:
    target: Path
    temporary: Path
    create: bool


def apply_plan(
    project_root: Path | str,
    plan: MergePlan | Path | str,
    approvals: Iterable[str] = (),
) -> ApplyResult:
    """Apply SAFE edits and exactly approved review edits after all preflight checks."""
    root = _project_root(project_root)
    merge_plan = load_plan(plan) if isinstance(plan, (str, Path)) else plan
    _validate_plan_object(merge_plan)
    approved = frozenset(approvals)
    review_by_id = {
        finding.finding_id: finding
        for finding in merge_plan.findings
        if finding.status == "REVIEW_REQUIRED" and finding.edits
    }
    unknown = approved - set(review_by_id)
    if unknown:
        raise PlanInputError("approval ID is unknown or not an executable review proposal")

    _verify_hashes(root, merge_plan)
    _verify_git(root)

    selected = tuple(
        finding for finding in merge_plan.findings
        if finding.edits and (
            finding.status == "SAFE"
            or (finding.status == "REVIEW_REQUIRED" and finding.finding_id in approved)
        )
    )
    edits_by_path: dict[str, list[Edit]] = {}
    roots_by_path: dict[str, str] = {}
    finding_ids_by_path: dict[str, set[str]] = {}
    for finding in selected:
        existing_root = finding.database.get("existing_root")
        if not isinstance(existing_root, str):
            raise PlanInputError("executable finding has no existing source root")
        for edit in finding.edits:
            if edit.path != finding.path:
                raise PlanInputError("finding edit path does not match its proposal path")
            prior_root = roots_by_path.setdefault(edit.path, existing_root)
            if prior_root != existing_root:
                raise PlanInputError("one target is assigned to multiple source roots")
            edits_by_path.setdefault(edit.path, []).append(edit)
            finding_ids_by_path.setdefault(edit.path, set()).add(finding.finding_id)

    prepared: list[_Prepared] = []
    try:
        for path in sorted(edits_by_path):
            target = _safe_target(root, path, roots_by_path[path])
            edits = _dedupe(edits_by_path[path])
            new_bytes, create, mode = _prepare_content(target, edits)
            if contains_sensitive(new_bytes):
                raise PlanInputError("planned source contains credential-like content")
            temporary = _write_temporary(root, roots_by_path[path], target, new_bytes, mode)
            prepared.append(_Prepared(target, temporary, create))
    except BaseException:
        _remove_temporaries(prepared)
        raise

    try:
        for item in prepared:
            if item.create:
                item.target.parent.mkdir(parents=True, exist_ok=True)
                _reject_symlink_components(root, item.target.parent)
            os.replace(str(item.temporary), str(item.target))
    except OSError as exception:
        _remove_temporaries(prepared)
        raise ApplyError("atomic source replacement failed") from exception

    applied_ids = tuple(sorted({
        finding_id for path in edits_by_path for finding_id in finding_ids_by_path[path]
    }))
    pending = tuple(
        finding.finding_id for finding in merge_plan.findings
        if finding.status == "REVIEW_REQUIRED" and finding.finding_id not in approved
    )
    blocked = tuple(
        finding.finding_id for finding in merge_plan.findings if finding.status == "BLOCKED"
    )
    return ApplyResult(result_state(merge_plan, approved), applied_ids, pending, blocked)


def _validate_plan_object(plan: MergePlan) -> None:
    if plan.format_version != PLAN_FORMAT_VERSION or plan.project_root != ".":
        raise PlanInputError("unsupported merge plan")
    if len(plan.schema_snapshot_sha256) != 64:
        raise PlanInputError("invalid schema snapshot hash")
    source_paths = {path for path, _ in plan.source_hashes}
    ids: set[str] = set()
    for finding in plan.findings:
        expected = _finding_id(
            finding.status, finding.kind, finding.table, finding.column, finding.path
        )
        if finding.finding_id != expected or finding.finding_id in ids:
            raise PlanInputError("invalid or duplicate finding ID")
        ids.add(finding.finding_id)
        if finding.status == "BLOCKED" and finding.edits:
            raise PlanInputError("blocked finding contains executable edits")
        if any(edit.kind != "create" and edit.path not in source_paths for edit in finding.edits):
            raise PlanInputError("source edit target was not hashed during planning")


def _verify_hashes(root: Path, plan: MergePlan) -> None:
    snapshot = _safe_existing(root, SNAPSHOT_PATH)
    if _sha(snapshot.read_bytes()) != plan.schema_snapshot_sha256:
        raise StalePlanError("schema snapshot changed after planning")
    for path, expected in plan.source_hashes + plan.generated_hashes:
        target = _safe_existing(root, path)
        try:
            actual = _sha(target.read_bytes())
        except OSError as exception:
            raise StalePlanError("planned input cannot be read") from exception
        if actual != expected:
            raise StalePlanError("planned input changed after planning")
    for finding in plan.findings:
        for edit in finding.edits:
            if edit.kind == "create":
                target = _normalized(root, edit.path)
                _reject_symlink_components(root, target, allow_missing=True)
                if target.exists() or target.is_symlink():
                    raise StalePlanError("planned create target now exists")


def _verify_git(root: Path) -> None:
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"], cwd=root,
            text=True, capture_output=True, check=False,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            raise UnsafeProjectError("project root is not a Git worktree")
        status_result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no", "--", "."],
            cwd=root, text=True, capture_output=True, check=False,
        )
    except OSError as exception:
        raise UnsafeProjectError("Git status could not be verified") from exception
    if status_result.returncode != 0 or status_result.stdout:
        raise UnsafeProjectError("tracked project state is not clean")


def _prepare_content(target: Path, edits: Sequence[Edit]) -> tuple[bytes, bool, int]:
    creates = [edit for edit in edits if edit.kind == "create"]
    if creates:
        if len(edits) != 1 or len(creates) != 1 or creates[0].span is not None:
            raise PlanInputError("create target must have exactly one create edit")
        if target.exists() or target.is_symlink():
            raise StalePlanError("create target exists")
        return creates[0].text.encode("utf-8"), True, 0o644
    if not target.is_file() or target.is_symlink():
        raise UnsafeProjectError("source target is not a regular file")
    raw = target.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    payload = raw[3:] if bom else raw
    try:
        source = payload.decode("utf-8")
    except UnicodeDecodeError as exception:
        raise StalePlanError("source encoding changed after planning") from exception
    ordered = _validate_and_order_edits(edits, len(source))
    updated = source
    for edit in ordered:
        if edit.span is None:
            raise PlanInputError("non-create edit has no source span")
        updated = updated[:edit.span.start] + edit.text + updated[edit.span.end:]
    encoded = updated.encode("utf-8")
    if bom:
        encoded = b"\xef\xbb\xbf" + encoded
    mode = stat.S_IMODE(target.stat().st_mode)
    return encoded, False, mode


def _validate_and_order_edits(edits: Sequence[Edit], source_length: int) -> tuple[Edit, ...]:
    for edit in edits:
        if edit.kind not in {"insert", "replace", "delete"} or edit.span is None:
            raise PlanInputError("invalid source edit")
        if edit.span.start < 0 or edit.span.end < edit.span.start or edit.span.end > source_length:
            raise StalePlanError("planned source span is outside the decoded source")
        if edit.kind == "insert" and edit.span.start != edit.span.end:
            raise PlanInputError("insert edit must use an empty source span")
        if edit.kind in {"replace", "delete"} and edit.span.start == edit.span.end:
            raise PlanInputError("replace/delete edit must use a non-empty source span")
    for index, left in enumerate(edits):
        assert left.span is not None
        for right in edits[index + 1:]:
            assert right.span is not None
            if left.span.start == left.span.end == right.span.start == right.span.end:
                continue
            if left.span.start == left.span.end:
                if right.span.start <= left.span.start <= right.span.end:
                    raise PlanInputError("source edits overlap or interact")
            elif right.span.start == right.span.end:
                if left.span.start <= right.span.start <= left.span.end:
                    raise PlanInputError("source edits overlap or interact")
            elif max(left.span.start, right.span.start) < min(left.span.end, right.span.end):
                raise PlanInputError("source edits overlap")
    return tuple(sorted(
        edits,
        key=lambda item: (
            item.span.start if item.span else -1,
            item.span.end if item.span else -1,
            item.text,
        ),
        reverse=True,
    ))


def _write_temporary(
    root: Path,
    source_root_text: str,
    target: Path,
    content: bytes,
    mode: int,
) -> Path:
    source_root = _normalized(root, source_root_text)
    _reject_symlink_components(root, source_root)
    directory = target.parent if target.parent.is_dir() else source_root
    descriptor = -1
    temporary_name = ""
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=".doma-entity-", suffix=".tmp", dir=directory)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_name, mode)
        return Path(temporary_name)
    except OSError as exception:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
        raise ApplyError("source update preparation failed") from exception


def _safe_target(root: Path, path: str, source_root_text: str) -> Path:
    target = _normalized(root, path)
    source_root = _normalized(root, source_root_text)
    if not _contains(source_root, target):
        raise UnsafeProjectError("source edit is outside its existing root")
    _reject_symlink_components(root, target, allow_missing=True)
    return target


def _safe_existing(root: Path, path: str) -> Path:
    target = _normalized(root, path)
    _reject_symlink_components(root, target)
    if not target.is_file() or target.is_symlink():
        raise StalePlanError("planned input is missing or unsafe")
    return target


def _normalized(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise PlanInputError("invalid project-relative path")
    relative = Path(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise PlanInputError("invalid project-relative path")
    target = Path(os.path.abspath(str(root / relative)))
    if not _contains(root, target):
        raise UnsafeProjectError("planned path escapes project root")
    return target


def _project_root(value: Path | str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = Path.cwd() / path
    if path.is_symlink() or not path.is_dir():
        raise UnsafeProjectError("project root is not a real directory")
    return path.resolve()


def _reject_symlink_components(root: Path, path: Path, allow_missing: bool = False) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exception:
        raise UnsafeProjectError("path escapes project root") from exception
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise UnsafeProjectError("path traverses a symbolic link")
        if allow_missing and not current.exists():
            break


def _contains(parent: Path, child: Path) -> bool:
    try:
        return os.path.commonpath((str(parent), str(child))) == str(parent)
    except ValueError:
        return False


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _dedupe(edits: Sequence[Edit]) -> tuple[Edit, ...]:
    result: list[Edit] = []
    for edit in edits:
        if edit not in result:
            result.append(edit)
    return tuple(result)


def _remove_temporaries(prepared: Sequence[_Prepared]) -> None:
    for item in prepared:
        try:
            item.temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
