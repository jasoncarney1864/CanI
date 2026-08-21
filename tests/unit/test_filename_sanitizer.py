"""Filename sanitizer for the original-document download's Content-Disposition header
(docs/21 §2.2)."""

from docs_api_app.filenames import FALLBACK_FILENAME, MAX_FILENAME_LENGTH, sanitize_filename


def test_plain_title_is_unchanged():
    assert sanitize_filename("HOA Agreement 2026") == "HOA Agreement 2026"


def test_forbidden_path_characters_are_stripped():
    assert sanitize_filename('a/b\\c:d*e?f"g<h>i|j') == "abcdefghij"


def test_control_characters_are_stripped():
    assert sanitize_filename("title\x00with\x1fcontrol\x7fchars") == "titlewithcontrolchars"


def test_whitespace_is_collapsed_and_trimmed():
    assert sanitize_filename("  too   many\t\tspaces  ") == "too many spaces"


def test_length_is_capped():
    result = sanitize_filename("x" * 500)
    assert len(result) == MAX_FILENAME_LENGTH


def test_empty_title_falls_back():
    assert sanitize_filename("") == FALLBACK_FILENAME


def test_all_forbidden_title_falls_back():
    assert sanitize_filename("///:::???") == FALLBACK_FILENAME


def test_unicode_title_is_preserved():
    assert sanitize_filename("Contrat de bail — résumé") == "Contrat de bail — résumé"
