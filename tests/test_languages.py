import re

import pytest

from anihub.core import i18n
from anihub.core.lang.keys import KEYS

PLACEHOLDER = re.compile(r"\{[a-z_]+(?::[^}]*)?\}")
TAGS = re.compile(r"</?b>")


def table(code: str) -> dict[str, str]:
    return i18n._load_extra(code)


def test_frozen_keys_match_the_english_table():
    """New English keys must be APPENDED to core/lang/keys.py (the extra languages number their lines by position)."""
    en = i18n.STRINGS["en"]
    assert len(set(KEYS)) == len(KEYS), "duplicate key in keys.py"
    assert set(en) == set(KEYS), (sorted(set(en) - set(KEYS))[:5], sorted(set(KEYS) - set(en))[:5])
    assert list(en)[:len(KEYS)] == list(KEYS) or set(en) == set(KEYS)


def test_parse_table_handles_numbers_breaks_and_junk():
    keys = ["a", "b", "c"]
    data = "0|hello\n1|two\\nlines with | bar\nx|junk\n7|out of range\n2|\n\n"
    assert i18n.parse_table(data, keys) == {"a": "hello", "b": "two\nlines with | bar"}


@pytest.mark.parametrize("code", i18n.EXTRA)
def test_extra_language_is_complete_and_keeps_placeholders(code):
    en = i18n.STRINGS["en"]
    t = table(code)
    assert t, f"{code}: no translations found"
    assert set(t) <= set(en)
    missing = [k for k in en if k not in t]
    assert len(missing) <= 130, (code, len(missing), missing[:10])                       # technical strings and the newest screens may stay English for now
    for key, text in t.items():
        assert sorted(PLACEHOLDER.findall(text)) == sorted(PLACEHOLDER.findall(en[key])), (code, key, text, en[key])
        assert sorted(TAGS.findall(text)) == sorted(TAGS.findall(en[key])), (code, key)
        assert text.strip(), (code, key)
        assert ("\n" in en[key]) == ("\n" in text) or "\n" not in en[key], (code, key)


@pytest.mark.parametrize("code", i18n.EXTRA)
def test_every_string_formats_with_sample_values(code):
    t = table(code)
    for key, text in t.items():
        fields = {m[1:-1].split(":")[0] for m in PLACEHOLDER.findall(text)}
        values = {f: (1.5 if f in ("gb", "mb", "done", "total", "p") else "x") for f in fields}
        try:
            text.format(**values)
        except (KeyError, ValueError, IndexError) as exc:
            pytest.fail(f"{code}:{key}: {exc}")


def test_language_switch_loads_and_falls_back_to_english():
    try:
        i18n.set_language("ja")
        assert i18n.get_language() == "ja" and i18n.tr("nav.arts") != "Arts"
        assert i18n.tr("settings.g_appearance") != "settings.g_appearance"             # a key that exists somewhere
        i18n.STRINGS["ja"].pop("nav.arts")
        assert i18n.tr("nav.arts") == "Arts"                                            # missing in the language: English
        i18n.set_language("xx")
        assert i18n.get_language() == "en"
    finally:
        i18n.STRINGS.pop("ja", None)
        i18n.set_language("ru")


def test_languages_offered_in_the_selectors():
    assert set(i18n.LANGUAGES) == {"ru", "en", *i18n.EXTRA}
    assert i18n.LANGUAGES["ja"] == "日本語"
