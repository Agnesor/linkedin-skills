"""Read-only access to the Parquet files built by ``scripts/build_dataset.py``.

The app keeps one in-memory DuckDB connection with views over the Parquet files and runs
every query on its own cursor, because a DuckDB connection is not safe to share between the
threads Streamlit uses for concurrent sessions.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from app.search import MAX_SKILLS, Filters, build_where

logger = logging.getLogger("linkedin_skills")

SCHEMA = {
    "postings": {"pid", "title_norm", "country", "level", "job_type"},
    "skills": {"sid", "skill"},
    "posting_skills": {"pid", "sid"},
}
MEMORY_LIMIT = "400MB"
THREADS = 2


class DataError(Exception):
    """The data directory is missing files or their schema does not match."""


@dataclass(frozen=True)
class SearchResult:
    matched: int
    skills: pd.DataFrame
    by_country: pd.DataFrame
    by_level: pd.DataFrame


def connect(data_dir: Path) -> duckdb.DuckDBPyConnection:
    """Open DuckDB with a view per Parquet file, after checking files and columns."""
    con = duckdb.connect()
    con.execute(f"SET memory_limit = '{MEMORY_LIMIT}'")
    con.execute(f"SET threads = {THREADS}")
    for name, columns in SCHEMA.items():
        path = data_dir / f"{name}.parquet"
        if not path.is_file():
            raise DataError(f"{path} not found; run scripts/fetch_data.sh or build the dataset")
        try:
            con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{path.as_posix()}')")
            actual = {row[0] for row in con.execute(f"DESCRIBE {name}").fetchall()}
        except duckdb.Error as exc:
            raise DataError(f"{path} is not a readable Parquet file: {exc}") from exc
        if not columns <= actual:
            raise DataError(f"{path} lacks columns {sorted(columns - actual)}")
    return con


def filter_options(con: duckdb.DuckDBPyConnection) -> dict[str, list[tuple[str, int]]]:
    """Distinct values with posting counts for each filter, most common first."""
    cur = con.cursor()
    return {
        column: cur.execute(
            f"SELECT {column}, count(*) FROM postings WHERE {column} IS NOT NULL "
            f"GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
        for column in ("country", "level", "job_type")
    }


def total_postings(con: duckdb.DuckDBPyConnection) -> int:
    return con.cursor().execute("SELECT count(*) FROM postings").fetchone()[0]


def breakdown(cur: duckdb.DuckDBPyConnection, column: str, label: str) -> pd.DataFrame:
    return cur.execute(
        f"SELECT {column} AS {label}, count(*) AS Postings FROM matched GROUP BY 1 ORDER BY 2 DESC"
    ).df()


def search(
    con: duckdb.DuckDBPyConnection, terms: tuple[str, ...], filters: Filters
) -> SearchResult:
    """Skills of postings matching ``terms`` and ``filters``.

    ``Percentage`` is the share of matched postings that list the skill, so it never
    exceeds 100: ``posting_skills`` holds unique (posting, skill) pairs.
    """
    where, params = build_where(terms, filters)
    started = time.perf_counter()
    cur = con.cursor()
    cur.execute(
        f"CREATE TEMP TABLE matched AS SELECT pid, country, level FROM postings WHERE {where}",
        params,
    )
    try:
        matched = cur.execute("SELECT count(*) FROM matched").fetchone()[0]
        skills = cur.execute(
            """
            WITH top AS (
                SELECT sid, count(*) AS n
                FROM posting_skills JOIN matched USING (pid)
                GROUP BY sid ORDER BY n DESC, sid LIMIT ?
            )
            SELECT s.skill AS Skill, top.n AS Postings
            FROM top JOIN skills s USING (sid)
            ORDER BY Postings DESC, Skill
            """,
            [MAX_SKILLS],
        ).df()
        by_country = breakdown(cur, "country", "Country")
        by_level = breakdown(cur, "level", "Level")
    finally:
        cur.execute("DROP TABLE matched")
    skills["Percentage"] = (skills["Postings"] * 100 / matched).round(1) if matched else []
    logger.info(
        "search terms=%s filters=%s matched=%d ms=%d",
        " ".join(terms),
        filters,
        matched,
        (time.perf_counter() - started) * 1000,
    )
    return SearchResult(matched, skills, by_country, by_level)
