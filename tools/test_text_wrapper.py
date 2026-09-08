"""Unit tests for the PS1 dialogue text wrapper."""

from __future__ import annotations

import unicodedata
import pytest

from tools.text_wrapper import wrap_dialogue
from patch_repo.localization.script import parse_target, ScriptError


class TestTextWrapper:
    """Test suite verifying PS1 hardware text layout compliance."""

    def test_short_string(self) -> None:
        """Short strings under 15 characters should remain on a single line."""
        text = "Привет!"
        result = wrap_dialogue(text, allow_continuation=True)
        assert result == "Привет!"
        assert len(result) <= 15
        assert "\n" not in result
        assert "\f" not in result
        parsed = parse_target(result, 0x00FD, "test_short_string")
        assert parsed == [["Привет!"]]

    def test_exactly_15_char_line(self) -> None:
        """A string of exactly 15 characters must fit on one line without splitting."""
        text = "123456789012345"
        result = wrap_dialogue(text, allow_continuation=True)
        assert result == "123456789012345"
        assert len(result) == 15
        assert "\n" not in result
        assert "\f" not in result
        parsed = parse_target(result, 0x00FD, "test_exactly_15_char_line")
        assert parsed == [["123456789012345"]]

    def test_multiline_word_wrapping(self) -> None:
        """Words should wrap naturally across lines without breaking words when possible."""
        text = "Лина Инверс и Гаури"
        result = wrap_dialogue(text, allow_continuation=True)
        lines = result.split("\n")
        assert len(lines) == 2
        assert lines[0] == "Лина Инверс и"
        assert lines[1] == "Гаури"
        for line in lines:
            assert len(line) <= 15
        parsed = parse_target(result, 0x00FD, "test_multiline_word_wrapping")
        assert parsed == [["Лина Инверс и", "Гаури"]]

    def test_page_breaks_with_form_feed(self) -> None:
        """When text exceeds 3 lines and allow_continuation=True, pages are joined by \\f."""
        text = "Раз два три четыре пять шесть семь восемь девять десять"
        result = wrap_dialogue(text, allow_continuation=True)
        assert "\f" in result
        pages = result.split("\f")
        assert len(pages) >= 2
        for page_idx, page in enumerate(pages):
            lines = page.split("\n")
            assert 1 <= len(lines) <= 3
            for line_idx, line in enumerate(lines):
                assert 1 <= len(line) <= 15
        parsed = parse_target(result, 0x00FD, "test_page_breaks_with_form_feed")
        assert len(parsed) == len(pages)

    def test_non_continuable_truncation(self) -> None:
        """When allow_continuation=False and text exceeds 3 lines, output is limited to 1 page (<=3 lines) with '...'."""
        text = "Первая строка очень длинная и вторая строка тоже длинная и третья строка и четвёртая"
        result = wrap_dialogue(text, allow_continuation=False)
        assert "\f" not in result
        lines = result.split("\n")
        assert 1 <= len(lines) <= 3
        assert lines[-1].endswith("...")
        for line in lines:
            assert 1 <= len(line) <= 15
        parsed = parse_target(result, 0x00FF, "test_non_continuable_truncation")
        assert len(parsed) == 1
        assert len(parsed[0]) <= 3

    def test_long_word_hyphenation(self) -> None:
        """Words longer than 15 chars must be split with a hyphen so no line exceeds 15 chars."""
        # 16 chars: 14 + '-' on line 1, 2 on line 2
        text = "1234567890123456"
        result = wrap_dialogue(text, allow_continuation=True)
        lines = result.split("\n")
        assert len(lines) == 2
        assert lines[0] == "12345678901234-"
        assert lines[1] == "56"
        for line in lines:
            assert len(line) <= 15
        parse_target(result, 0x00FD, "test_long_word_hyphenation")

        # 20 chars
        word20 = "АБВГДЕЖЗИЙКЛМНОПРСТУ"
        result20 = wrap_dialogue(word20, allow_continuation=True)
        lines20 = result20.split("\n")
        assert len(lines20) == 2
        assert lines20[0] == "АБВГДЕЖЗИЙКЛМН-"
        assert lines20[1] == "ОПРСТУ"
        for line in lines20:
            assert len(line) <= 15
        parse_target(result20, 0x00FD, "test_long_word_hyphenation_20")

        # Long hyphenated word
        hyphen_word = "О-хо-хо-хо-хо-хо-хо"
        result_hyphen = wrap_dialogue(hyphen_word, allow_continuation=True)
        for page in result_hyphen.split("\f"):
            for line in page.split("\n"):
                assert len(line) <= 15
        parse_target(result_hyphen, 0x00FD, "test_long_word_hyphen_word")

    def test_nfc_normalization(self) -> None:
        """Text provided in NFD (decomposed Unicode) must be converted to NFC."""
        # 'й' decomposed is 'и' + combining breve U+0306
        # 'й' and 'ё' decomposed into combining characters in NFD
        nfd_text = unicodedata.normalize("NFD", "Пойдём, Лина!")
        assert unicodedata.normalize("NFC", nfd_text) != nfd_text
        assert len(nfd_text) > len("Пойдём, Лина!")

        result = wrap_dialogue(nfd_text, allow_continuation=True)
        assert unicodedata.normalize("NFC", result) == result
        parse_target(result, 0x00FD, "test_nfc_normalization")

    def test_empty_string_handling(self) -> None:
        """Empty or whitespace-only strings should return empty string."""
        assert wrap_dialogue("") == ""
        assert wrap_dialogue("   ") == ""
        assert wrap_dialogue("\n\t") == ""
