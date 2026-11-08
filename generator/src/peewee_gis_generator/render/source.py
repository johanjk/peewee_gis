"""Python source layout for the rendered stubs, matching ``ruff format`` and ruff's docstring rules."""

import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

LINE_LENGTH = 120
METHOD_INDENT = " " * 4
BODY_INDENT = " " * 8


def escape(text: str) -> str:
    """Safe inside a ``\"\"\"`` docstring."""
    return text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')


def sentence(text: str) -> str:
    """End with terminal punctuation (pydocstyle D415)."""
    text = text.rstrip()
    return text if text.endswith((".", "?", "!")) else f"{text}."


def wrap(text: str, indent: str = BODY_INDENT, line_length: int = LINE_LENGTH) -> list[str]:
    """Re-flow ``text`` (paragraphs separated by blank lines) to fit ``line_length`` at ``indent``.

    Words are never broken, so a long URL may stay over the limit on a line of its own,
    which E501 allows.
    """
    width = line_length - len(indent)
    lines: list[str] = []
    for paragraph in text.split("\n\n"):
        words = " ".join(paragraph.split())
        if not words:
            continue
        if lines:
            lines.append("")
        lines.extend(
            textwrap.wrap(words, width=width, break_long_words=False, break_on_hyphens=False) or [words],
        )
    return lines


def reference(label: str, url: str, indent: str) -> list[str]:
    """``label: url`` on one line if it fits, else the URL on the next line."""
    line = f"{label}: {url}"
    if len(indent) + len(line) <= LINE_LENGTH:
        return [line]
    return [f"{label}:", f"    {url}"]


def docstring(summary: str, body: Sequence[str], indent: str = BODY_INDENT) -> str:
    """A docstring with a one line summary; ``body`` lines are relative to ``indent``.

    A ``"name: text"`` summary too long for one line is split: ``name.`` stays the
    summary and ``text`` becomes the first body paragraph.
    """
    first = sentence(summary)
    lines = list(body)
    if len(indent) + 3 + len(first) > LINE_LENGTH:
        head, _, rest = first.partition(": ")
        lines = [*wrap(rest or first, indent), "", *lines]
        first = sentence(head)
    out = [f'{indent}"""{escape(first)}']
    if lines:
        out.append("")
        out.extend(f"{indent}{escape(line)}" if line else "" for line in lines)
    out.append(f'{indent}"""')
    return "\n".join(out)


def signature(name: str, params: Sequence[str], returns: str, indent: str = METHOD_INDENT) -> str:
    """``def name(params) -> returns:`` laid out like ``ruff format``.

    One line if it fits, else one parameter per line with a trailing comma (which
    ``ruff format`` keeps, and COM812 asks for).
    """
    one_line = f"{indent}def {name}({', '.join(params)}) -> {returns}:"
    if len(one_line) <= LINE_LENGTH:
        return one_line
    inner = indent + " " * 4
    lines = "\n".join(f"{inner}{p}," for p in params)
    return f"{indent}def {name}(\n{lines}\n{indent}) -> {returns}:"
