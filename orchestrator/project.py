"""Project mode: the files the agents may change in an existing project, and applying a run.

    python -m orchestrator --task-file task.md \\
        --edit app/main.py --edit static/chat.html --context tests/test_api.py
    python -m orchestrator --apply orchestrator_runs/<run>

A project-mode run never writes to the project: it saves the agents' files, a diff
and a manifest in its run folder. Applying is a separate command, run after a person
has read the diff. It copies an approved run's files into the project, runs the
tests, and puts the original files back if the tests fail.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path

from .agents import BACKEND, FRONTEND

# The file type decides which agent owns a file.
OWNERS = {".py": BACKEND, ".html": FRONTEND, ".css": FRONTEND, ".js": FRONTEND}
MAX_EDIT_FILES = 8
MAX_FILE_BYTES = 200 * 1024
MANIFEST = "manifest.json"
FINAL_FILES = "final/files"
APPROVED = "approved"


class ProjectError(Exception):
    """A project-mode input that can't be used. The message names the path and the problem."""


@dataclass(frozen=True)
class EditFile:
    """A project file the agents may change or create."""

    path: str  # relative to the project, with forward slashes
    owner: str  # BACKEND or FRONTEND
    original: str | None  # its text when the run started (line endings as "\n"); None if it did not exist
    sha256: str | None  # of its bytes when the run started; None if it did not exist


@dataclass(frozen=True)
class Project:
    root: Path
    edits: list[EditFile]
    context: list[tuple[str, str]]  # (path, text): read-only files every agent receives

    def paths_of(self, owner: str) -> list[str]:
        return [f.path for f in self.edits if f.owner == owner]


def load_project(root: Path, edit_paths: list[str], context_paths: list[str], out_dir: Path) -> Project:
    """Check every --edit and --context path and read the files. Raises ProjectError."""
    root = root.resolve()
    if len(edit_paths) > MAX_EDIT_FILES:
        raise ProjectError(f"at most {MAX_EDIT_FILES} --edit paths are allowed (got {len(edit_paths)})")

    edits: list[EditFile] = []
    for raw in edit_paths:
        relative, full = _check_path(root, raw, out_dir, "--edit")
        if any(f.path == relative for f in edits):
            raise ProjectError(f"--edit {raw}: is given twice")
        owner = OWNERS.get(full.suffix.lower())
        if owner is None:
            raise ProjectError(f"--edit {raw}: has an unsupported file type; use .py, .html, .css or .js")
        if not full.parent.is_dir():
            raise ProjectError(f"--edit {raw}: is in a folder that does not exist")
        if full.exists():
            data = _read_small_file(full, raw, "--edit")
            edits.append(EditFile(relative, owner, _text(data, raw, "--edit"), sha256(data)))
        else:
            edits.append(EditFile(relative, owner, None, None))

    context: list[tuple[str, str]] = []
    for raw in context_paths:
        relative, full = _check_path(root, raw, out_dir, "--context")
        if any(f.path == relative for f in edits):
            raise ProjectError(f"--context {raw}: is also given with --edit")
        if any(path == relative for path, _ in context):
            raise ProjectError(f"--context {raw}: is given twice")
        if not full.exists():
            raise ProjectError(f"--context {raw}: does not exist")
        context.append((relative, _text(_read_small_file(full, raw, "--context"), raw, "--context")))
    return Project(root, edits, context)


def _check_path(root: Path, raw: str, out_dir: Path, option: str) -> tuple[str, Path]:
    """The path relative to the project (forward slashes) and in full, or ProjectError."""
    candidate = Path(raw)
    if not raw.strip():
        raise ProjectError(f"{option}: the path is empty")
    if candidate.is_absolute() or candidate.drive or raw.startswith(("/", "\\")):
        raise ProjectError(f"{option} {raw}: use a path relative to the project folder")
    full = (root / candidate).resolve()  # resolves ".." and links
    try:
        relative = full.relative_to(root)
    except ValueError:
        raise ProjectError(f"{option} {raw}: is outside the project folder") from None
    if not relative.parts:
        raise ProjectError(f"{option} {raw}: is not a file")
    if relative.parts[0] == ".git":
        raise ProjectError(f"{option} {raw}: is inside .git/")
    runs = (root / out_dir).resolve()
    if full == runs or runs in full.parents:
        raise ProjectError(f"{option} {raw}: is inside the run output folder")
    if full.name.startswith(".env"):
        raise ProjectError(f"{option} {raw}: .env files are not allowed")
    return relative.as_posix(), full


def _read_small_file(full: Path, raw: str, option: str) -> bytes:
    if not full.is_file():
        raise ProjectError(f"{option} {raw}: is not a file")
    if full.stat().st_size > MAX_FILE_BYTES:
        raise ProjectError(f"{option} {raw}: is larger than {MAX_FILE_BYTES // 1024} KB")
    return full.read_bytes()


def _text(data: bytes, raw: str, option: str) -> str:
    try:
        return data.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError:
        raise ProjectError(f"{option} {raw}: is not UTF-8 text") from None


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_diff(path: str, before: str | None, after: str | None) -> str:
    """A unified diff of one file, as `git diff` would show it. Empty when nothing changed."""
    lines = unified_diff(
        (before or "").splitlines(keepends=True),
        (after or "").splitlines(keepends=True),
        f"a/{path}" if before is not None else "/dev/null",
        f"b/{path}" if after is not None else "/dev/null",
    )
    return "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines)


def line_counts(before: str | None, after: str | None) -> tuple[int, int]:
    """Lines (added, removed) between two versions of a file."""
    added = removed = 0
    for line in unified_diff((before or "").splitlines(), (after or "").splitlines(), lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def manifest_data(project: Project, task: str, outcome: str, rounds: int) -> dict:
    """What manifest.json records: enough to check, at apply time, that the project hasn't moved on."""
    return {
        "mode": "project",
        "project": str(project.root),
        "task": task,
        "outcome": outcome,
        "rounds": rounds,
        "files": [
            {"path": f.path, "owner": f.owner, "existed": f.original is not None, "sha256": f.sha256}
            for f in project.edits
        ],
        "context": [path for path, _ in project.context],
    }


# --- Apply ---------------------------------------------------------------------------


def apply_run(run_folder: Path, root: Path, run_tests: Callable[[], int], log: Callable[[str, str], None]) -> int:
    """Copy an approved run's final files into the project, then keep them only if the tests pass.

    `run_tests` runs the project's tests and returns their exit status. `log(label, text)`
    writes one progress line. Raises ProjectError, having written nothing, when the run
    can't be applied. Returns the exit status: 0 applied, 1 tests failed and the files
    were restored.
    """
    root = root.resolve()
    manifest = _read_manifest(run_folder)
    if manifest.get("outcome") != APPROVED:
        raise ProjectError(f"only approved runs can be applied; this run's outcome is {manifest.get('outcome')!r}")
    if Path(manifest["project"]).resolve() != root:
        raise ProjectError(f"this run belongs to the project at {manifest['project']}; run --apply from there")
    log("apply", f"{run_folder} (approved) -> {root}")

    # Check every file before writing any: each must still be as it was when the run started.
    changed = []
    plans = []  # (path, full path, bytes now or None, text the run ends with or None)
    for entry in manifest["files"]:
        path = entry["path"]
        full = root / path
        current = full.read_bytes() if full.is_file() else None
        if (sha256(current) if current is not None else None) != entry["sha256"]:
            changed.append(path)
        final = run_folder / FINAL_FILES / path
        new_text = final.read_text(encoding="utf-8") if final.is_file() else None
        if new_text is not None and not full.parent.is_dir():
            raise ProjectError(f"{path}: its folder no longer exists")
        plans.append((path, full, current, new_text))
    if changed:
        raise ProjectError(
            "changed since the run: " + ", ".join(changed) + ". Run the orchestrator again, or apply the diff by hand."
        )
    log("check", f"{len(plans)} files unchanged since the run")

    writes = []  # (path, full path, bytes before or None, bytes to write)
    for path, full, current, new_text in plans:
        if new_text is None:
            continue  # the run did not create this file
        if current is not None and b"\r\n" in current:
            new_text = new_text.replace("\n", "\r\n")  # keep the file's line endings
        data = new_text.encode("utf-8")
        if data != current:
            writes.append((path, full, current, data))
    if not writes:
        log("result", "nothing to apply: the run's files equal the project's")
        return 0

    summary = ", ".join(
        f"{'changed' if before is not None else 'created'} {path}" for path, _, before, _ in writes
    )
    passed = False
    try:
        for _, full, _, data in writes:
            full.write_bytes(data)
        log("write", summary)
        log("test", "python -m pytest -q")
        passed = run_tests() == 0
    finally:
        # Restore on failing tests and on any interruption, such as Ctrl+C.
        if not passed:
            for _, full, before, _ in writes:
                if before is None:
                    full.unlink(missing_ok=True)
                else:
                    full.write_bytes(before)
    if passed:
        log("decide", "tests passed -> keep the changes")
        log("result", f"applied: {summary} | review with git diff, then commit")
        return 0
    log("decide", "tests failed -> restore the project")
    log("result", f"restored every file; the run's files stay in {run_folder / FINAL_FILES}")
    return 1


def _read_manifest(run_folder: Path) -> dict:
    try:
        manifest = json.loads((run_folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ProjectError(f"{run_folder} is not a project-mode run folder (no readable {MANIFEST})") from None
    if not isinstance(manifest, dict) or manifest.get("mode") != "project":
        raise ProjectError(f"{run_folder} is not a project-mode run folder")
    return manifest
