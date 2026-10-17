from gmail_helpers import _personalize

R = {"first_name": "Sarah", "last_name": "Lee"}


def test_replaces_first_name():
    assert _personalize("Hi {first_name},", R) == "Hi Sarah,"


def test_variants_and_case():
    assert _personalize("{{ First_Name }} {LAST NAME} / {full_name}", R) == "Sarah Lee / Sarah Lee"


def test_missing_first_name_falls_back():
    assert _personalize("Hi {first_name},", {"first_name": "", "last_name": ""}) == "Hi there,"


def test_unrelated_braces_untouched():
    assert _personalize("Use {code} now, {first_name}", R) == "Use {code} now, Sarah"
