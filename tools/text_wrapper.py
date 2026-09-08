"""Dialogue text wrapper complying with PS1 hardware layout constraints."""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

# Ensure patch_repo is available for localization modules
REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_REPO = REPO_ROOT / "patch_repo"
if str(PATCH_REPO) not in sys.path:
    sys.path.insert(0, str(PATCH_REPO))

from localization.script import ScriptError, parse_target


def _break_long_word(word: str, max_chars: int) -> list[str]:
    """Break a word longer than max_chars into hyphenated chunks of length <= max_chars."""
    if len(word) <= max_chars:
        return [word]

    # If word has internal hyphens, preserve hyphen boundaries where possible
    if "-" in word:
        parts = word.split("-")
        chunks: list[str] = []
        current = ""
        for i, p in enumerate(parts):
            suffix = "-" if i < len(parts) - 1 else ""
            part_with_hyphen = p + suffix
            if len(part_with_hyphen) > max_chars:
                # Sub-part is itself longer than max_chars, mechanically slice it
                rem = part_with_hyphen
                while len(rem) > max_chars:
                    chunk = rem[: max_chars - 1] + "-"
                    if current:
                        chunks.append(current)
                        current = ""
                    chunks.append(chunk)
                    rem = rem[max_chars - 1 :]
                if rem:
                    current = rem
            elif not current:
                current = part_with_hyphen
            elif len(current) + len(part_with_hyphen) <= max_chars:
                current += part_with_hyphen
            else:
                chunks.append(current)
                current = part_with_hyphen
        if current:
            chunks.append(current)
        return chunks

    # No internal hyphens: mechanically slice with '-' suffix
    chunks = []
    rem = word
    while len(rem) > max_chars:
        chunk = rem[: max_chars - 1] + "-"
        chunks.append(chunk)
        rem = rem[max_chars - 1 :]
    if rem:
        chunks.append(rem)
    return chunks


def wrap_dialogue(
    text: str,
    allow_continuation: bool = True,
    max_chars_per_line: int = 15,
    max_lines_per_page: int = 3,
) -> str:
    """Format Russian dialogue text complying with PS1 hardware layout limits.

    - Normalizes text with NFC, strips \\r.
    - Word-wraps text so every line length <= max_chars_per_line (15).
    - Breaks words > max_chars_per_line with hyphens.
    - Formats into pages of 1 to max_lines_per_page lines (joined with \\n).
    - If allow_continuation=True, joins pages with \\f.
    - If allow_continuation=False, limits output to 1 page (<= 3 lines),
      truncating with '...' on the last line if necessary.
    - Validates output with parse_target.
    """
    if not text or not text.strip():
        return ""

    # Normalize NFC and strip carriage returns
    text = unicodedata.normalize("NFC", text.replace("\r", ""))

    # Normalize heart emojis / special glyphs to font-supported equivalents
    text = text.replace("\u2764\ufe0f", "♥").replace("\u2764", "♥").replace("\ufe0f", "")
    text = text.replace("⁉", "!?").replace("–", "-")

    # Unescape escaped characters from Ren'Py strings
    text = text.replace('\\"', '"').replace("\\n", " ")

    # Collapse multiple whitespace characters into single spaces
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""

    words = text.split(" ")

    # Split any words exceeding max_chars_per_line
    tokens: list[str] = []
    for word in words:
        if len(word) <= max_chars_per_line:
            tokens.append(word)
        else:
            tokens.extend(_break_long_word(word, max_chars_per_line))

    # Pack tokens into lines of <= max_chars_per_line
    lines: list[str] = []
    current_line = ""
    for token in tokens:
        if not current_line:
            current_line = token
        elif len(current_line) + 1 + len(token) <= max_chars_per_line:
            current_line += " " + token
        else:
            lines.append(current_line)
            current_line = token
    if current_line:
        lines.append(current_line)

    # Format into pages
    if not allow_continuation:
        # At most 1 page of at most max_lines_per_page lines
        if len(lines) > max_lines_per_page:
            kept_lines = lines[: max_lines_per_page - 1]
            last_line = lines[max_lines_per_page - 1]
            ellipsis = "..."
            max_prefix = max_chars_per_line - len(ellipsis)

            if len(last_line) <= max_prefix:
                truncated_last = last_line.rstrip(" ,.!?—") + ellipsis
            else:
                w_list = last_line.split()
                cand = ""
                for w in w_list:
                    test = (cand + " " + w).strip() if cand else w
                    if len(test) <= max_prefix:
                        cand = test
                    else:
                        break
                if cand:
                    truncated_last = cand.rstrip(" ,.!?—") + ellipsis
                else:
                    truncated_last = last_line[:max_prefix].rstrip(" ,.!?—") + ellipsis

            if not truncated_last:
                truncated_last = ellipsis
            kept_lines.append(truncated_last)
            lines = kept_lines

        result = "\n".join(lines)
    else:
        pages: list[str] = []
        for i in range(0, len(lines), max_lines_per_page):
            pages.append("\n".join(lines[i : i + max_lines_per_page]))
        result = "\f".join(pages)

    result = unicodedata.normalize("NFC", result)

    # Validate output against PS1 parser constraints
    delimiter = 0x00FD if allow_continuation else 0x00FF
    parse_target(result, delimiter, "wrap_dialogue")
    return result
