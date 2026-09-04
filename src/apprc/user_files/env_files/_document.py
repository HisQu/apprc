"""Source-preserving edits for user-maintained dotenv documents."""

from __future__ import annotations

# == Standard Library ========================
import json
import re
from dataclasses import dataclass
from io import StringIO

# == 3rd Party ===============================
from dotenv.parser import Binding, parse_stream

_LEADING_BLANK_LINES = re.compile(
    r"((?:[^\S\r\n]*(?:\r\n|\r|\n))*)(.*)", re.DOTALL
)
_ASSIGNMENT_HEAD = re.compile(
    r"^(?P<indent>[^\S\r\n]*)"
    r"(?P<export>export[^\S\r\n]+)?"
    r"(?P<key>'[^']+'|[^=\#\s]+)"
    r"(?P<before_equals>[^\S\r\n]*)"
    r"(?:=(?P<after_equals>[^\S\r\n]*))?",
)
_LINE_ENDING = re.compile(r"\r\n|\r|\n")


@dataclass(frozen=True, slots=True)
class DotenvDocumentEdit:
    """Describe a transformed dotenv document.

    :param text: Complete text after the edit.
    :param matched_lines: Source line numbers containing active assignments.
    :param disabled_duplicate_lines: Later assignments commented out by set.
    """

    text: str
    matched_lines: tuple[int, ...]
    disabled_duplicate_lines: tuple[int, ...] = ()


def set_dotenv_document_value(
    text: str,
    *,
    env_key: str,
    value: str,
) -> DotenvDocumentEdit:
    """Set one key without rewriting unrelated dotenv text.

    The first active assignment remains active. Later assignments are
    commented out so the file has one authoritative value without discarding
    the user's original text.

    :param text: Existing dotenv text.
    :param env_key: Exact environment key to edit.
    :param value: Normalized value to quote and store.
    :return: Edited text and duplicate line information.
    """
    parts: list[str] = []
    matched_lines: list[int] = []
    duplicate_lines: list[int] = []
    for binding in parse_stream(StringIO(text)):
        if binding.error or binding.key != env_key:
            parts.append(binding.original.string)
            continue
        leading, assignment = _split_leading_blank_lines(binding)
        line = binding.original.line + _line_count(leading)
        matched_lines.append(line)
        parts.append(leading)
        if len(matched_lines) == 1:
            parts.append(
                _replace_assignment_value(
                    assignment,
                    value=value,
                )
            )
            continue
        duplicate_lines.append(line)
        parts.append(_comment_duplicate_assignment(assignment))

    if not matched_lines:
        ending = _preferred_line_ending(text)
        if text and not text.endswith(("\n", "\r")):
            parts.append(ending)
        parts.append(f"{env_key}={json.dumps(value)}{ending}")

    return DotenvDocumentEdit(
        text="".join(parts),
        matched_lines=tuple(matched_lines),
        disabled_duplicate_lines=tuple(duplicate_lines),
    )


def clear_dotenv_document_value(
    text: str,
    *,
    env_key: str,
) -> DotenvDocumentEdit:
    """Remove every active assignment for one key.

    :param text: Existing dotenv text.
    :param env_key: Exact environment key to remove.
    :return: Edited text and removed source line numbers.
    """
    parts: list[str] = []
    matched_lines: list[int] = []
    for binding in parse_stream(StringIO(text)):
        if binding.error or binding.key != env_key:
            parts.append(binding.original.string)
            continue
        leading, _assignment = _split_leading_blank_lines(binding)
        matched_lines.append(binding.original.line + _line_count(leading))
        parts.append(leading)
    return DotenvDocumentEdit(
        text="".join(parts),
        matched_lines=tuple(matched_lines),
    )


def _split_leading_blank_lines(binding: Binding) -> tuple[str, str]:
    """Separate parser-owned blank lines from an assignment.

    ``python-dotenv`` attaches blank lines before a binding to that binding.
    AppRC keeps those lines when it removes or comments out the assignment.

    :param binding: Parsed dotenv binding.
    :return: Leading blank text and the assignment block.
    """
    match = _LEADING_BLANK_LINES.fullmatch(binding.original.string)
    if match is None:
        return "", binding.original.string
    return match.group(1), match.group(2)


def _replace_assignment_value(assignment: str, *, value: str) -> str:
    """Replace one assignment value and retain its layout and comment.

    :param assignment: One active dotenv assignment block.
    :param value: Normalized value to store.
    :return: Single-line assignment with the original line ending.
    """
    ending = _terminal_line_ending(assignment)
    body = assignment[: -len(ending)] if ending else assignment
    match = _ASSIGNMENT_HEAD.match(body)
    if match is None:
        raise ValueError("Could not preserve the selected dotenv assignment.")
    comment = _inline_comment(body, start=match.end())
    export = match.group("export") or ""
    after_equals = match.group("after_equals") or ""
    return (
        f"{match.group('indent')}{export}{match.group('key')}"
        f"{match.group('before_equals')}={after_equals}{json.dumps(value)}"
        f"{comment}{ending}"
    )


def _inline_comment(text: str, *, start: int) -> str:
    """Return a trailing dotenv comment outside quoted value text.

    :param text: Assignment text without its terminal line ending.
    :param start: Character offset immediately after the assignment head.
    :return: Whitespace plus comment, or an empty string.
    """
    quote: str | None = None
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote is not None:
            escaped = True
            continue
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char == "#" and index > 0 and text[index - 1].isspace():
            comment_start = index - 1
            while comment_start > start and text[comment_start - 1] in {
                " ",
                "\t",
            }:
                comment_start -= 1
            return text[comment_start:]
    return ""


def _comment_duplicate_assignment(assignment: str) -> str:
    """Comment every physical line in one duplicate assignment.

    :param assignment: Active assignment block to disable.
    :return: Commented text that preserves the original assignment.
    """
    commented: list[str] = []
    for index, line in enumerate(assignment.splitlines(keepends=True)):
        content, ending = _without_terminal_line_ending(line)
        prefix = (
            "# AppRC disabled duplicate assignment: " if index == 0 else "# "
        )
        commented.append(f"{prefix}{content}{ending}")
    return "".join(commented)


def _without_terminal_line_ending(line: str) -> tuple[str, str]:
    """Split one physical line from its ending.

    :param line: Physical source line.
    :return: Content and its line ending.
    """
    ending = _terminal_line_ending(line)
    if not ending:
        return line, ""
    return line[: -len(ending)], ending


def _terminal_line_ending(text: str) -> str:
    """Return the line ending at the end of ``text``.

    :param text: Text to inspect.
    :return: Terminal CRLF, CR, LF, or an empty string.
    """
    if text.endswith("\r\n"):
        return "\r\n"
    if text.endswith("\n"):
        return "\n"
    if text.endswith("\r"):
        return "\r"
    return ""


def _preferred_line_ending(text: str) -> str:
    """Return the first existing line ending or LF for a new file.

    :param text: Existing document text.
    :return: Line ending to use for an appended assignment.
    """
    match = _LINE_ENDING.search(text)
    return match.group(0) if match is not None else "\n"


def _line_count(text: str) -> int:
    """Count physical line endings in source text.

    :param text: Source prefix.
    :return: Number of CRLF, CR, or LF endings.
    """
    return len(_LINE_ENDING.findall(text))
