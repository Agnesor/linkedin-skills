import re

import pytest

from app.search import (
    MAX_QUERY_CHARS,
    MAX_TERMS,
    Filters,
    QueryError,
    build_where,
    normalize_query,
    term_pattern,
)


def test_normalize_query_is_order_and_case_insensitive():
    assert normalize_query("  Product   MANAGER ") == normalize_query("manager product")
    assert normalize_query("QA qa") == ("qa",)


@pytest.mark.parametrize(
    "raw, message",
    [
        ("   ", "Enter a job title"),
        ("x" * (MAX_QUERY_CHARS + 1), "too long"),
        (" ".join(f"w{i}" for i in range(MAX_TERMS + 1)), "at most"),
    ],
)
def test_normalize_query_rejects(raw, message):
    with pytest.raises(QueryError, match=message):
        normalize_query(raw)


@pytest.mark.parametrize(
    "term, title, expected",
    [
        ("c++", "senior c++ developer", True),
        ("c++", "c++/java engineer", True),
        ("c#", "c# / .net developer", True),
        (".net", "c# / .net developer", True),
        ("qa", "qa engineer", True),
        ("qa", "aquatics coordinator", False),
        ("coo", "cook", False),
        ("coo", "coo, operations", True),
        ("data", "big-data engineer", True),
    ],
)
def test_term_pattern_whole_words(term, title, expected):
    # RE2 and Python agree on these constructs, so Python's re is a faithful stand-in here.
    assert bool(re.search(term_pattern(term), title)) is expected


def test_term_pattern_escapes_wildcards_and_regex():
    assert re.search(term_pattern("a_b"), "axb") is None
    assert re.search(term_pattern("100%"), "100x") is None
    assert re.search(term_pattern("(x)"), "x") is None


def test_build_where_parameterizes_everything():
    where, params = build_where(("qa",), Filters.of(countries=["Canada"], job_types=["Remote"]))
    assert "qa" not in where and "Canada" not in where
    assert params == ["qa", term_pattern("qa"), "Canada", "Remote"]


def test_filters_are_sorted_for_cache_keys():
    assert Filters.of(countries=["b", "a"]) == Filters.of(countries=["a", "b"])
