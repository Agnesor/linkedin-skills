"""Build the Parquet files the app reads from the Kaggle "1.3M LinkedIn Jobs & Skills (2024)" CSVs.

Source: https://www.kaggle.com/datasets/asaniczka/1-3m-linkedin-jobs-and-skills-2024
(ODC Attribution License 1.0). Only ``linkedin_job_postings.csv`` and ``job_skills.csv`` are used.

Output schema (all files zstd-compressed Parquet):

``postings.parquet``
    ``pid`` INTEGER, ``title_norm`` VARCHAR (lower-cased, whitespace-collapsed job title),
    ``country`` VARCHAR, ``level`` VARCHAR, ``job_type`` VARCHAR.
    One row per unique posting that has at least one skill after rare skills are dropped.
    This set is the denominator for every percentage the app shows. Reposts of the same job
    (equal normalized title, company and location) collapse into one row represented by
    the repost with the smallest ``job_link``; only that repost's skills are kept, because
    merging the NER output of all reposts would add their extraction noise together.
``skills.parquet``
    ``sid`` INTEGER, ``skill`` VARCHAR (the most common spelling of the normalized skill).
``posting_skills.parquet``
    ``pid`` INTEGER, ``sid`` INTEGER. Unique pairs, sorted by ``pid``.

``manifest.json`` records row counts, byte sizes and sha256 of each file plus the source
and its license. It never contains local paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb

POSTING_COLUMNS = {
    "job_link",
    "job_title",
    "company",
    "job_location",
    "search_country",
    "job_level",
    "job_type",
}
SKILL_COLUMNS = {"job_link", "job_skills"}
OUTPUT_FILES = ("postings", "skills", "posting_skills")
SOURCE = {
    "dataset": "asaniczka/1-3m-linkedin-jobs-and-skills-2024",
    "url": "https://www.kaggle.com/datasets/asaniczka/1-3m-linkedin-jobs-and-skills-2024",
    "license": "ODC-By-1.0",
    "author": "asaniczka",
}


class InputError(Exception):
    """Raised when an input CSV is missing or does not have the expected columns."""


def read_header(path: Path) -> set[str]:
    if not path.is_file():
        raise InputError(f"{path}: file not found")
    try:
        con = duckdb.connect()
        rel = con.sql(f"SELECT * FROM read_csv('{path.as_posix()}', header=true) LIMIT 0")
        return set(rel.columns)
    except duckdb.Error as exc:
        raise InputError(f"{path}: cannot parse CSV header ({exc})") from exc


def check_columns(path: Path, required: set[str]) -> None:
    missing = required - read_header(path)
    if missing:
        raise InputError(f"{path}: missing columns {sorted(missing)}")


def check_unique_links(con: duckdb.DuckDBPyConnection, table: str, path: Path) -> None:
    # Every join below is keyed by job_link; a duplicate would silently double-count skills.
    total, unique = con.execute(
        f"SELECT count(*), count(DISTINCT job_link) FROM {table}"
    ).fetchone()
    if total != unique:
        raise InputError(f"{path}: {total - unique} duplicate job_link values")


def build(postings_csv: Path, skills_csv: Path, out_dir: Path, min_skill_freq: int) -> dict:
    check_columns(postings_csv, POSTING_COLUMNS)
    check_columns(skills_csv, SKILL_COLUMNS)
    out_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute(
        f"""
        CREATE TABLE raw_postings AS
        SELECT job_link,
               lower(trim(regexp_replace(job_title, '\\s+', ' ', 'g'))) AS title_norm,
               lower(trim(regexp_replace(company, '\\s+', ' ', 'g'))) AS company_key,
               lower(trim(regexp_replace(job_location, '\\s+', ' ', 'g'))) AS location_key,
               search_country AS country,
               job_level AS level,
               job_type
        FROM read_csv('{postings_csv.as_posix()}', header=true, all_varchar=true)
        WHERE job_title IS NOT NULL AND trim(job_title) <> ''
        """
    )
    check_unique_links(con, "raw_postings", postings_csv)
    report("raw postings", con, "raw_postings")

    con.execute(
        f"""
        CREATE TABLE raw_skills AS
        SELECT job_link, job_skills
        FROM read_csv('{skills_csv.as_posix()}', header=true, all_varchar=true)
        """
    )
    check_unique_links(con, "raw_skills", skills_csv)
    con.execute(
        """
        CREATE TABLE raw_pairs AS
        SELECT DISTINCT s.job_link,
               lower(trim(x)) AS skill_key,
               trim(x) AS spelling
        FROM raw_skills s,
             unnest(string_split(s.job_skills, ',')) t(x)
        WHERE trim(x) <> ''
        """
    )
    report("raw posting-skill pairs", con, "raw_pairs")

    # Reposts of the same job (same title, company and location) would inflate counts.
    con.execute(
        """
        CREATE TABLE unique_postings AS
        SELECT min(p.job_link) AS job_link, p.title_norm, p.company_key, p.location_key,
               arg_min(p.country, p.job_link) AS country, arg_min(p.level, p.job_link) AS level,
               arg_min(p.job_type, p.job_link) AS job_type
        FROM raw_postings p
        WHERE p.job_link IN (SELECT job_link FROM raw_pairs)
        GROUP BY p.title_norm, p.company_key, p.location_key
        """
    )
    report("unique postings with skills", con, "unique_postings")

    con.execute(
        """
        CREATE TABLE pairs AS
        SELECT u.job_link, r.skill_key, r.spelling
        FROM unique_postings u JOIN raw_pairs r USING (job_link)
        """
    )
    con.execute(
        """
        CREATE TABLE skill_freq AS
        SELECT skill_key, count(DISTINCT job_link) AS n
        FROM pairs GROUP BY skill_key HAVING count(DISTINCT job_link) >= ?
        """,
        [min_skill_freq],
    )
    report(f"skills with frequency >= {min_skill_freq}", con, "skill_freq")

    con.execute(
        """
        CREATE TABLE skills AS
        WITH spellings AS (
            SELECT skill_key, spelling, count(*) AS c
            FROM pairs WHERE skill_key IN (SELECT skill_key FROM skill_freq)
            GROUP BY skill_key, spelling
        )
        SELECT row_number() OVER (ORDER BY skill_key)::INTEGER AS sid, skill_key,
               first(spelling ORDER BY c DESC, spelling) AS skill
        FROM spellings GROUP BY skill_key
        """
    )
    con.execute(
        """
        CREATE TABLE kept_pairs AS
        SELECT DISTINCT p.job_link, s.sid
        FROM pairs p JOIN skills s USING (skill_key)
        """
    )
    con.execute(
        """
        CREATE TABLE postings AS
        SELECT row_number() OVER (ORDER BY u.job_link)::INTEGER AS pid, u.job_link,
               u.title_norm, u.country, u.level, u.job_type
        FROM unique_postings u
        WHERE u.job_link IN (SELECT job_link FROM kept_pairs)
        """
    )
    report("final postings", con, "postings")
    con.execute(
        """
        CREATE TABLE posting_skills AS
        SELECT p.pid, k.sid FROM kept_pairs k JOIN postings p USING (job_link)
        ORDER BY p.pid, k.sid
        """
    )
    report("final posting-skill pairs", con, "posting_skills")

    exports = {
        "postings": "SELECT pid, title_norm, country, level, job_type FROM postings ORDER BY pid",
        "skills": "SELECT sid, skill FROM skills ORDER BY sid",
        "posting_skills": "SELECT pid, sid FROM posting_skills",
    }
    files = {}
    for name, query in exports.items():
        target = out_dir / f"{name}.parquet"
        con.execute(f"COPY ({query}) TO '{target.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
        rows = con.execute(f"SELECT count(*) FROM ({query})").fetchone()[0]
        files[target.name] = {
            "rows": rows,
            "bytes": target.stat().st_size,
            "sha256": sha256(target),
        }
        print(f"wrote {target.name}: {rows} rows, {target.stat().st_size / 2**20:.1f} MiB")

    manifest = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "min_skill_frequency": min_skill_freq,
        "source": SOURCE,
        "files": files,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def report(label: str, con: duckdb.DuckDBPyConnection, table: str) -> None:
    print(f"{label}: {con.execute(f'SELECT count(*) FROM {table}').fetchone()[0]}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--postings", type=Path, required=True, help="linkedin_job_postings.csv")
    parser.add_argument("--skills", type=Path, required=True, help="job_skills.csv")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument(
        "--min-skill-freq",
        type=int,
        default=2,
        help="drop skills seen in fewer postings than this (NER noise)",
    )
    args = parser.parse_args(argv)
    try:
        build(args.postings, args.skills, args.out, args.min_skill_freq)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except duckdb.Error as exc:
        # Malformed rows past DuckDB's header sniffing sample surface only during the build.
        print(f"error: cannot process input CSVs: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
