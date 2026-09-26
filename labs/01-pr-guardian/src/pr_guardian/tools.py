"""Read-only tool layer.

Security is enforced here, in deterministic Python — not in the prompt:

- Every read resolves to a real path (symlinks followed) and must stay inside
  fixtures/cases/<case_id>/ of the case this run was started for.
- There is no write, shell, or network capability anywhere in this module.
- Reads and search results are size-capped to bound context and cost.
- Evaluator-only files (ground truth) are invisible to the agent.

Plain functions (read_diff, read_file, ...) hold the logic and are unit-testable
without a model. The *_tool wrappers are what the agent actually sees.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from agents import RunContextWrapper, function_tool

LAB_ROOT = Path(__file__).resolve().parents[2]
CASES_ROOT = LAB_ROOT / "fixtures" / "cases"

DIFF_FILE = "diff.patch"
TEST_RESULTS_FILE = "test-results.txt"
# Human ground truth for evals. The reviewer must never see the expected answer.
HIDDEN_FILES = frozenset({"case-notes.md"})

MAX_FILE_BYTES = 64_000
MAX_QUERY_CHARS = 200
MAX_SEARCH_MATCHES = 50

_CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class ToolAccessError(ValueError):
    """Raised when a tool call falls outside the allowed boundary."""


@dataclass(frozen=True)
class ReviewContext:
    """Run-scoped context set by our code, not by the model."""

    case_id: str


# --- path boundary ---------------------------------------------------------


def resolve_case_dir(case_id: str) -> Path:
    if not _CASE_ID_RE.fullmatch(case_id):
        raise ToolAccessError(f"Invalid case_id: {case_id!r}")
    case_dir = (CASES_ROOT / case_id).resolve()
    if not case_dir.is_relative_to(CASES_ROOT.resolve()) or not case_dir.is_dir():
        raise ToolAccessError(f"Unknown case_id: {case_id!r}")
    return case_dir


def resolve_case_path(case_id: str, relative_path: str) -> Path:
    case_dir = resolve_case_dir(case_id)
    if not relative_path or Path(relative_path).is_absolute():
        raise ToolAccessError("relative_path must be a non-empty relative path")
    target = (case_dir / relative_path).resolve()
    if not target.is_relative_to(case_dir):
        raise ToolAccessError(f"Path escapes the case directory: {relative_path!r}")
    if target.name in HIDDEN_FILES:
        raise ToolAccessError(f"File not available: {relative_path!r}")
    if not target.is_file():
        raise ToolAccessError(f"File not found: {relative_path!r}")
    return target


def _read_text(path: Path) -> str:
    with path.open("rb") as fh:
        data = fh.read(MAX_FILE_BYTES + 1)
    text = data[:MAX_FILE_BYTES].decode("utf-8", errors="replace")
    if len(data) > MAX_FILE_BYTES:
        text += f"\n[truncated at {MAX_FILE_BYTES} bytes]"
    return text


# --- deterministic tool logic ----------------------------------------------


def read_diff(case_id: str) -> str:
    return _read_text(resolve_case_path(case_id, DIFF_FILE))


def read_file(case_id: str, relative_path: str) -> str:
    return _read_text(resolve_case_path(case_id, relative_path))


def get_test_results(case_id: str) -> str:
    return _read_text(resolve_case_path(case_id, TEST_RESULTS_FILE))


def search_repository(case_id: str, query: str) -> str:
    """Case-insensitive literal substring search (no regex: avoids ReDoS)."""
    if not query or len(query) > MAX_QUERY_CHARS:
        raise ToolAccessError(f"query must be 1-{MAX_QUERY_CHARS} characters")
    case_dir = resolve_case_dir(case_id)
    needle = query.lower()
    matches: list[str] = []
    for path in sorted(case_dir.rglob("*")):
        rel = path.relative_to(case_dir).as_posix()
        try:
            path = resolve_case_path(case_id, rel)
        except ToolAccessError:
            continue  # directories, hidden files, symlinks pointing outside
        for lineno, line in enumerate(_read_text(path).splitlines(), start=1):
            if needle in line.lower():
                matches.append(f"{rel}:{lineno}: {line.strip()[:300]}")
                if len(matches) >= MAX_SEARCH_MATCHES:
                    matches.append(f"[stopped after {MAX_SEARCH_MATCHES} matches]")
                    return "\n".join(matches)
    return "\n".join(matches) if matches else "No matches."


# --- agent-facing wrappers -------------------------------------------------


def _check_scope(ctx: RunContextWrapper[ReviewContext], case_id: str) -> None:
    # The model supplies case_id, but it may only read the case our code chose.
    if case_id != ctx.context.case_id:
        raise ToolAccessError(f"case_id {case_id!r} is outside this review's scope")


def _untrusted(source: str, content: str) -> str:
    # Labelling is a prompt-level hint only; the real boundary is the code above.
    content = content.replace("</untrusted_repository_data", "<\\/untrusted_repository_data")
    return (
        f'<untrusted_repository_data source="{source}">\n'
        f"{content}\n"
        "</untrusted_repository_data>"
    )


@function_tool(name_override="read_diff")
def read_diff_tool(ctx: RunContextWrapper[ReviewContext], case_id: str) -> str:
    """Return the unified diff for the pull request under review.

    Args:
        case_id: The case identifier given in the review request.
    """
    _check_scope(ctx, case_id)
    return _untrusted(DIFF_FILE, read_diff(case_id))


@function_tool(name_override="read_file")
def read_file_tool(
    ctx: RunContextWrapper[ReviewContext], case_id: str, relative_path: str
) -> str:
    """Return the contents of one file from the repository snapshot (read-only).

    Args:
        case_id: The case identifier given in the review request.
        relative_path: File path relative to the repository root, e.g. "src/app.py".
    """
    _check_scope(ctx, case_id)
    return _untrusted(relative_path, read_file(case_id, relative_path))


@function_tool(name_override="search_repository")
def search_repository_tool(
    ctx: RunContextWrapper[ReviewContext], case_id: str, query: str
) -> str:
    """Find lines containing a literal, case-insensitive text query.

    Returns "path:line: text" matches.

    Args:
        case_id: The case identifier given in the review request.
        query: Literal text to search for (not a regex).
    """
    _check_scope(ctx, case_id)
    return _untrusted(f"search:{query}", search_repository(case_id, query))


@function_tool(name_override="get_test_results")
def get_test_results_tool(ctx: RunContextWrapper[ReviewContext], case_id: str) -> str:
    """Return the recorded test-run output for the pull request.

    Args:
        case_id: The case identifier given in the review request.
    """
    _check_scope(ctx, case_id)
    return _untrusted(TEST_RESULTS_FILE, get_test_results(case_id))


REVIEW_TOOLS = [read_diff_tool, read_file_tool, search_repository_tool, get_test_results_tool]
