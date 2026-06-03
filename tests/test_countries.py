"""The country data module: a static ISO-3166-1 alpha-2 list backing the Settings flag
picker and the player-strip flag. Codes are unique 2-letter uppercase, the list is sorted
by display name, flags are derived from the code as regional-indicator emoji (no assets),
and the lookups normalize/case-fold and reject unknown codes so render-time never receives
a bogus regional-indicator pair."""

from chessshootout.infra import countries


def test_list_is_substantial():
    assert len(countries.COUNTRIES) > 200


def test_codes_are_unique_two_letter_uppercase():
    codes = [code for code, _ in countries.COUNTRIES]
    assert len(codes) == len(set(codes))
    for code in codes:
        assert len(code) == 2 and code.isalpha() and code.isupper()


def test_names_are_unique():
    names = [name for _, name in countries.COUNTRIES]
    assert len(names) == len(set(names))


def test_list_is_sorted_by_name():
    folded = [countries.fold(name) for _, name in countries.COUNTRIES]
    assert folded == sorted(folded)


def test_codes_frozenset_matches_list():
    assert countries.CODES == frozenset(code for code, _ in countries.COUNTRIES)


def test_flag_emoji_us_is_regional_indicator_pair():
    assert countries.flag_emoji("US") == "\U0001F1FA\U0001F1F8"


def test_flag_emoji_is_case_insensitive():
    assert countries.flag_emoji("ro") == countries.flag_emoji("RO")
    assert countries.flag_emoji(" ro ") == countries.flag_emoji("RO")


def test_flag_emoji_romania():
    assert countries.flag_emoji("RO") == "\U0001F1F7\U0001F1F4"


def test_flag_emoji_empty_for_blank():
    assert countries.flag_emoji("") == ""
    assert countries.flag_emoji(None) == ""


def test_flag_emoji_empty_for_unknown_code():
    assert "XX" not in countries.CODES
    assert countries.flag_emoji("XX") == ""


def test_name_for_known_and_unknown():
    assert countries.name_for("RO") == "Romania"
    assert countries.name_for("us") == "United States"
    assert countries.name_for("XX") == ""
    assert countries.name_for("") == ""


def test_normalize_folds_and_rejects():
    assert countries.normalize(" us ") == "US"
    assert countries.normalize("usa") == ""
    assert countries.normalize("") == ""


def test_random_code_is_always_a_known_code():
    for _ in range(50):
        assert countries.random_code() in countries.CODES
