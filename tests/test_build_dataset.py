import csv
import json
from pathlib import Path

import duckdb
import pytest

from scripts.build_dataset import build, main

POSTING_HEADER = [
    "job_link",
    "job_title",
    "company",
    "job_location",
    "search_country",
    "job_level",
    "job_type",
    "first_seen",
]


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_ALL)
        writer.writerow(header)
        writer.writerows(rows)
    return path


@pytest.fixture
def inputs(tmp_path: Path) -> tuple[Path, Path]:
    postings = write_csv(
        tmp_path / "postings.csv",
        POSTING_HEADER,
        [
            ["l1", "Data  Scientist", "Acme", "London", "UK", "Mid senior", "Onsite", "x"],
            # Repost of l1: same title, company and location.
            ["l2", "data scientist", "ACME", "london", "UK", "Mid senior", "Onsite", "x"],
            ["l3", "QA Engineer", "Beta", "Austin, TX", "US", "Associate", "Remote", "x"],
            ["l4", "Nurse", "Gamma", "Toronto", "Canada", "Mid senior", "Onsite", "x"],
            # No skills row at all.
            ["l5", "Chef", "Delta", "Sydney", "Australia", "Associate", "Onsite", "x"],
        ],
    )
    skills = write_csv(
        tmp_path / "skills.csv",
        ["job_link", "job_skills"],
        [
            ["l1", "Python, SQL, python, Rare Skill"],
            ["l2", "Python, SQL"],
            ["l3", "python, Selenium, SQL"],
            # Only a skill that appears once: the posting disappears after the rare-skill cut.
            ["l4", "Patient Care"],
        ],
    )
    return postings, skills


def load(out: Path, name: str) -> list[tuple]:
    return duckdb.sql(f"SELECT * FROM '{out / name}.parquet' ORDER BY ALL").fetchall()


def test_build_normalizes_dedupes_and_filters(inputs, tmp_path):
    postings_csv, skills_csv = inputs
    out = tmp_path / "build"
    build(postings_csv, skills_csv, out, min_skill_freq=2)

    postings = load(out, "postings")
    assert [row[1] for row in postings] == ["data scientist", "qa engineer"]

    skills = {row[1] for row in load(out, "skills")}
    # "python" is the most common spelling across postings (2 vs 1).
    assert skills == {"python", "SQL"}

    pairs = load(out, "posting_skills")
    assert len(pairs) == len(set(pairs)) == 4


def test_manifest_matches_files_and_has_no_local_paths(inputs, tmp_path):
    postings_csv, skills_csv = inputs
    out = tmp_path / "build"
    manifest = build(postings_csv, skills_csv, out, min_skill_freq=2)

    stored = json.loads((out / "manifest.json").read_text())
    assert stored["files"] == manifest["files"]
    assert set(stored["files"]) == {"postings.parquet", "skills.parquet", "posting_skills.parquet"}
    assert str(tmp_path) not in (out / "manifest.json").read_text()
    assert stored["source"]["license"] == "ODC-By-1.0"


def test_missing_columns_exit_code_2(tmp_path, capsys):
    bad = write_csv(tmp_path / "bad.csv", ["job_link", "title"], [["l1", "x"]])
    skills = write_csv(tmp_path / "skills.csv", ["job_link", "job_skills"], [["l1", "a"]])
    code = main(["--postings", str(bad), "--skills", str(skills), "--out", str(tmp_path / "o")])
    assert code == 2
    assert "missing columns" in capsys.readouterr().err


def test_missing_file_exit_code_2(tmp_path, capsys):
    code = main(
        [
            "--postings",
            str(tmp_path / "nope.csv"),
            "--skills",
            str(tmp_path / "nope2.csv"),
            "--out",
            str(tmp_path / "o"),
        ]
    )
    assert code == 2
    assert "file not found" in capsys.readouterr().err


def test_repost_keeps_only_representative_skills(tmp_path):
    postings = write_csv(
        tmp_path / "postings.csv",
        POSTING_HEADER,
        [
            ["a1", "Analyst", "Acme  Corp", "Leeds", "UK", "Associate", "Onsite", "x"],
            # Repost with extra whitespace in company: same job, collapsed into a1.
            ["a2", "Analyst", "acme corp", "Leeds", "UK", "Associate", "Onsite", "x"],
            ["b1", "Analyst", "Other", "York", "UK", "Associate", "Onsite", "x"],
        ],
    )
    skills = write_csv(
        tmp_path / "skills.csv",
        ["job_link", "job_skills"],
        [["a1", "Excel, SQL"], ["a2", "Excel, Tableau"], ["b1", "Excel, SQL, Tableau"]],
    )
    out = tmp_path / "build"
    build(postings, skills, out, min_skill_freq=1)

    assert len(load(out, "postings")) == 2
    rows = duckdb.sql(
        f"SELECT s.skill, count(*) FROM '{out}/posting_skills.parquet' ps "
        f"JOIN '{out}/skills.parquet' s USING (sid) GROUP BY 1 ORDER BY 1"
    ).fetchall()
    # a2's Tableau is dropped with the repost; only b1 contributes it.
    assert rows == [("Excel", 2), ("SQL", 2), ("Tableau", 1)]


def test_duplicate_job_link_exit_code_2(tmp_path, capsys):
    postings = write_csv(
        tmp_path / "postings.csv",
        POSTING_HEADER,
        [
            ["l1", "A", "C", "L", "UK", "Associate", "Onsite", "x"],
            ["l1", "B", "C", "L", "UK", "Associate", "Onsite", "x"],
        ],
    )
    skills = write_csv(tmp_path / "skills.csv", ["job_link", "job_skills"], [["l1", "a"]])
    code = main(
        ["--postings", str(postings), "--skills", str(skills), "--out", str(tmp_path / "o")]
    )
    assert code == 2
    assert "duplicate job_link" in capsys.readouterr().err


def test_malformed_row_after_sniff_sample_exit_code_2(tmp_path, capsys):
    rows = [[f"l{i}", "T", "C", "L", "UK", "Associate", "Onsite", "x"] for i in range(30_000)]
    postings = write_csv(tmp_path / "postings.csv", POSTING_HEADER, rows)
    with postings.open("a") as fh:
        fh.write('"broken","row"\n')
    skills = write_csv(tmp_path / "skills.csv", ["job_link", "job_skills"], [["l1", "a"]])
    code = main(
        ["--postings", str(postings), "--skills", str(skills), "--out", str(tmp_path / "o")]
    )
    assert code == 2
    assert "cannot process input CSVs" in capsys.readouterr().err
