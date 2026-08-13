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
    _expected_finding_id,
    build_plan,
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
    source_roots = _canonical_planning_request(root, merge_plan)
    _verify_hashes(root, merge_plan)
    _verify_canonical_plan(root, merge_plan, source_roots)
    approved = frozenset(approvals)
    review_by_id = {
        finding.finding_id: finding
        for finding in merge_plan.findings
        if finding.status == "REVIEW_REQUIRED" and finding.edits
    }
    unknown = approved - set(review_by_id)
    if unknown:
        raise PlanInputError("approval ID is unknown or not an executable review proposal")

    selected = tuple(
        finding for finding in merge_plan.findings
        if finding.edits and (
            finding.status == "SAFE"
            or (finding.status == "REVIEW_REQUIRED" and finding.finding_id in approved)
        )
    )
    _verify_git(root, selected)
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
    if plan.language not in {"auto", "java", "kotlin"}:
        raise PlanInputError("invalid merge plan language")
    if len(plan.schema_snapshot_sha256) != 64:
        raise PlanInputError("invalid schema snapshot hash")
    _validate_hash_pairs(plan.source_hashes, "source")
    _validate_hash_pairs(plan.generated_hashes, "generated")
    source_paths = {path for path, _ in plan.source_hashes}
    generated_paths = {path for path, _ in plan.generated_hashes}
    ids: set[str] = set()
    for finding in plan.findings:
        expected = _expected_finding_id(finding)
        if finding.finding_id != expected or finding.finding_id in ids:
            raise PlanInputError("invalid or duplicate finding ID")
        ids.add(finding.finding_id)
        if finding.status == "BLOCKED" and finding.edits:
            raise PlanInputError("blocked finding contains executable edits")
        if any(edit.path != finding.path for edit in finding.edits):
            raise PlanInputError("finding edit path does not match its proposal path")
        if any(edit.kind != "create" and edit.path not in source_paths for edit in finding.edits):
            raise PlanInputError("source edit target was not hashed during planning")
        creates = [edit for edit in finding.edits if edit.kind == "create"]
        if creates:
            if len(finding.edits) != 1 or len(creates) != 1:
                raise PlanInputError("create proposal must contain exactly one create edit")
            generated_path = finding.database.get("generated_path")
            if not isinstance(generated_path, str) or generated_path not in generated_paths:
                raise PlanInputError("create proposal has no exact generated candidate hash")


def _validate_hash_pairs(pairs: Sequence[tuple[str, str]], name: str) -> None:
    if tuple(sorted(pairs)) != tuple(pairs) or len({path for path, _ in pairs}) != len(pairs):
        raise PlanInputError(name + " hashes must be unique and sorted")
    for path, digest in pairs:
        _normalized_plan_path(path)
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise PlanInputError("invalid " + name + " SHA-256")


def _canonical_planning_request(
    root: Path,
    plan: MergePlan,
) -> tuple[Path, ...]:
    _strict_subdirectory(root, "build/doma-codegen/generated", "generated root")
    generated_root_text = "build/doma-codegen/generated"
    supported = {
        "src/main/java": root / "src/main/java",
        "src/main/kotlin": root / "src/main/kotlin",
    }
    selected_roots: set[str] = set()
    generated_languages: set[str] = set()
    source_languages: set[str] = set()

    for path, _ in plan.generated_hashes:
        if not _plan_path_below(path, generated_root_text):
            raise UnsafeProjectError("planned generated input is outside the managed root")
        generated_languages.add(_source_language(path))
    for path, _ in plan.source_hashes:
        source_root = next(
            (name for name in supported if _plan_path_below(path, name)), None
        )
        if source_root is None:
            raise UnsafeProjectError("planned source input is outside supported source roots")
        selected_roots.add(source_root)
        source_languages.add(_source_language(path))

    for finding in plan.findings:
        existing_root = finding.database.get("existing_root")
        if existing_root is not None:
            if not isinstance(existing_root, str) or existing_root not in supported:
                raise UnsafeProjectError("proposal selects an unsupported existing source root")
            selected_roots.add(existing_root)
        source_root_values = finding.database.get("source_roots")
        if source_root_values is not None:
            if not isinstance(source_root_values, list) or any(
                not isinstance(item, str) or item not in supported
                for item in source_root_values
            ):
                raise UnsafeProjectError("proposal contains unsupported source-root choices")
            selected_roots.update(source_root_values)
        finding_generated_root = finding.database.get("generated_root")
        if (
            finding_generated_root is not None
            and finding_generated_root != generated_root_text
        ):
            raise UnsafeProjectError("proposal selects a non-managed generated root")
        generated_path = finding.database.get("generated_path")
        if generated_path is not None and (
            not isinstance(generated_path, str)
            or not _plan_path_below(generated_path, generated_root_text)
        ):
            raise UnsafeProjectError("proposal generated path is outside the managed root")

    comparison_languages = (
        {plan.language}
        if plan.language != "auto"
        else generated_languages | source_languages
    )
    for language in comparison_languages:
        selected_roots.add("src/main/" + language)
    if not selected_roots:
        selected_roots.update(
            name for name, path in supported.items() if path.is_dir() and not path.is_symlink()
        )
    source_roots = tuple(
        _strict_subdirectory(root, name, "existing source root")
        for name in ("src/main/java", "src/main/kotlin")
        if name in selected_roots
    )
    if not source_roots:
        raise UnsafeProjectError("no supported canonical source root was discovered")
    return source_roots


def _verify_canonical_plan(
    root: Path,
    plan: MergePlan,
    source_roots: Sequence[Path],
) -> None:
    generated_root = root / "build/doma-codegen/generated"
    matches: list[str] = []
    for language in ("java", "kotlin", "auto"):
        try:
            expected = build_plan(
                root,
                root / SNAPSHOT_PATH,
                generated_root,
                tuple(source_roots),
                language,
            )
        except PlanInputError:
            continue
        if plan == expected:
            matches.append(language)
    if len(matches) != 1:
        raise PlanInputError("merge plan does not match the current canonical proposal")


def _plan_path_below(path: str, root: str) -> bool:
    relative = Path(path)
    try:
        remainder = relative.relative_to(root)
    except ValueError:
        return False
    return remainder != Path(".")


def _source_language(path: str) -> str:
    suffix = Path(path).suffix
    if suffix == ".java":
        return "java"
    if suffix == ".kt":
        return "kotlin"
    raise UnsafeProjectError("planned source input has an unsupported language")


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
                _verify_create_binding(root, plan, finding, edit)


def _verify_create_binding(root: Path, plan: MergePlan, finding: Finding, edit: Edit) -> None:
    existing_root_text = finding.database.get("existing_root")
    generated_root_text = finding.database.get("generated_root")
    generated_path_text = finding.database.get("generated_path")
    if not all(isinstance(item, str) for item in (
        existing_root_text, generated_root_text, generated_path_text
    )):
        raise PlanInputError("create proposal is missing validated roots")
    assert isinstance(existing_root_text, str)
    assert isinstance(generated_root_text, str)
    assert isinstance(generated_path_text, str)
    source_root = _strict_source_root(root, existing_root_text)
    generated_root = _strict_subdirectory(root, generated_root_text, "generated root")
    target = _normalized(root, edit.path)
    generated_path = _safe_existing(root, generated_path_text)
    if not _contains(source_root, target) or target == source_root:
        raise UnsafeProjectError("create target is outside its validated source root")
    if not _contains(generated_root, generated_path) or generated_path == generated_root:
        raise UnsafeProjectError("generated candidate is outside its validated root")
    if target.relative_to(source_root) != generated_path.relative_to(generated_root):
        raise PlanInputError("create target does not match the generated candidate path")
    _reject_symlink_components(root, target, allow_missing=True)
    if target.exists() or target.is_symlink():
        raise StalePlanError("planned create target now exists")
    if generated_path.read_bytes() != edit.text.encode("utf-8"):
        raise PlanInputError("create content is not the exact hashed generated candidate")


def _verify_git(root: Path, selected: Sequence[Finding]) -> None:
    pathspecs = {
        edit.path
        for finding in selected
        for edit in finding.edits
    }
    existing_targets = {
        edit.path
        for finding in selected
        for edit in finding.edits
        if edit.kind != "create"
    }
    pathspecs.update(
        path.name for path in (root / "build.gradle.kts", root / "build.gradle")
        if path.is_file() and not path.is_symlink()
    )
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"], cwd=root,
            text=True, capture_output=True, check=False,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            raise UnsafeProjectError("project root is not a Git worktree")
        for path in sorted(existing_targets):
            tracked = subprocess.run(
                ["git", "ls-files", "--error-unmatch", "--", path],
                cwd=root, text=True, capture_output=True, check=False,
            )
            if tracked.returncode != 0:
                raise UnsafeProjectError("existing source target is not tracked by Git")
        status_result = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all", "--", *sorted(pathspecs)],
            cwd=root, text=True, capture_output=True, check=False,
        )
    except OSError as exception:
        raise UnsafeProjectError("Git status could not be verified") from exception
    if status_result.returncode != 0 or status_result.stdout:
        raise UnsafeProjectError("selected project targets are not clean")


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
    source_root = _strict_source_root(root, source_root_text)
    if not _contains(source_root, target):
        raise UnsafeProjectError("source edit is outside its existing root")
    _reject_symlink_components(root, target, allow_missing=True)
    return target


def _strict_source_root(root: Path, value: str) -> Path:
    return _strict_subdirectory(root, value, "existing source root")


def _strict_subdirectory(root: Path, value: str, label: str) -> Path:
    if value in {"", "."}:
        raise UnsafeProjectError(label + " must be a strict project subdirectory")
    path = _normalized(root, value)
    _reject_symlink_components(root, path)
    if path == root or not path.is_dir() or path.is_symlink():
        raise UnsafeProjectError(label + " is not an existing real directory")
    return path


def _normalized_plan_path(value: str) -> None:
    if not isinstance(value, str) or not value or "\\" in value:
        raise PlanInputError("invalid project-relative path")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PlanInputError("invalid project-relative path")


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
