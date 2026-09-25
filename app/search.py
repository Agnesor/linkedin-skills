"""Query normalization and SQL building for the skills search.

A query matches a posting when every query word appears in the posting's normalized title as
a whole word. "Whole word" means the word is not glued to another letter or digit, so ``qa``
does not match ``aqua`` and ``c++``, ``c#`` or ``.net`` still match: a plain regex ``\\b``
fails on those because ``+``, ``#`` and ``.`` are not word characters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_QUERY_CHARS = 100
MAX_TERMS = 8
MAX_SKILLS = 1000


class QueryError(ValueError):
    """Raised for a query the app refuses to run; the message is shown to the user."""


@dataclass(frozen=True)
class Filters:
    """Selected filter values; an empty tuple means "no filter"."""

    countries: tuple[str, ...] = field(default_factory=tuple)
    levels: tuple[str, ...] = field(default_factory=tuple)
    job_types: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def of(cls, countries=(), levels=(), job_types=()) -> Filters:
        """Build filters with sorted values so equal selections share one cache entry."""
        return cls(tuple(sorted(countries)), tuple(sorted(levels)), tuple(sorted(job_types)))


def normalize_query(raw: str) -> tuple[str, ...]:
    """Return the query's unique lower-cased words, sorted; order does not change matches."""
    text = " ".join(raw.split()).lower()
    if not text:
        raise QueryError("Enter a job title to search for.")
    if len(text) > MAX_QUERY_CHARS:
        raise QueryError(f"The query is too long: keep it under {MAX_QUERY_CHARS} characters.")
    terms = tuple(sorted(set(text.split(" "))))
    if len(terms) > MAX_TERMS:
        raise QueryError(f"Use at most {MAX_TERMS} words.")
    return terms


def term_pattern(term: str) -> str:
    """RE2 pattern that matches ``term`` as a whole word in a lower-cased title."""
    return f"(^|[^a-z0-9]){re.escape(term)}($|[^a-z0-9])"


def build_where(terms: tuple[str, ...], filters: Filters) -> tuple[str, list]:
    """SQL condition over ``postings`` plus its positional parameters.

    ``contains`` is a cheap pre-filter; the regex then enforces whole-word matching.
    """
    if not terms:
        raise QueryError("Enter a job title to search for.")
    conditions: list[str] = []
    params: list = []
    for term in terms:
        conditions.append("(contains(title_norm, ?) AND regexp_matches(title_norm, ?))")
        params.extend([term, term_pattern(term)])
    for column, values in (
        ("country", filters.countries),
        ("level", filters.levels),
        ("job_type", filters.job_types),
    ):
        if values:
            placeholders = ", ".join("?" for _ in values)
            conditions.append(f"{column} IN ({placeholders})")
            params.extend(values)
    return " AND ".join(conditions), params
