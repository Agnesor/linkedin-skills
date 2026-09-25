from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pandas as pd
import pytest

from app.data import DataError, connect, filter_options, search, total_postings
from app.excel import safe_filename, to_excel
from app.search import Filters, normalize_query


@pytest.fixture(scope="module")
def con(data_dir):
    return connect(data_dir)


def skills_of(result) -> dict[str, float]:
    return dict(zip(result.skills["Skill"], result.skills["Percentage"], strict=True))


def test_search_matches_whole_words(con):
    assert search(con, normalize_query("qa"), Filters()).matched == 1
    assert search(con, normalize_query("c++"), Filters()).matched == 1
    assert search(con, normalize_query(".net"), Filters()).matched == 1


def test_search_words_in_any_order(con):
    result = search(con, normalize_query("product manager"), Filters())
    assert result.matched == 2
    assert skills_of(result)["Product Management"] == 100.0
    assert skills_of(result)["Roadmaps"] == 50.0


def test_percentages_never_exceed_100(con):
    result = search(con, normalize_query("data"), Filters())
    assert result.matched == 2
    assert result.skills["Percentage"].max() <= 100
    assert skills_of(result)["Python"] == 100.0


def test_filters_and_breakdowns(con):
    result = search(con, normalize_query("data"), Filters.of(job_types=["Remote"]))
    assert result.matched == 1
    assert result.by_country.to_dict("records") == [{"Country": "United States", "Postings": 1}]
    assert result.by_level.to_dict("records") == [{"Level": "Mid senior", "Postings": 1}]


def test_no_match_returns_empty_tables(con):
    result = search(con, normalize_query("astronaut"), Filters())
    assert result.matched == 0
    assert result.skills.empty


def test_filter_options_and_total(con):
    options = filter_options(con)
    assert dict(options["country"])["United Kingdom"] == 3
    assert total_postings(con) == 8


def test_concurrent_searches_use_separate_cursors(con):
    queries = ["qa", "data", "product manager", "c++"] * 5
    with ThreadPoolExecutor(max_workers=8) as pool:
        matched = list(
            pool.map(lambda q: search(con, normalize_query(q), Filters()).matched, queries)
        )
    assert matched == [1, 2, 2, 1] * 5


def test_connect_reports_missing_and_broken_files(tmp_path, data_dir):
    with pytest.raises(DataError, match="not found"):
        connect(tmp_path)
    for name in ("postings", "skills", "posting_skills"):
        target = tmp_path / f"{name}.parquet"
        target.write_bytes((data_dir / f"{name}.parquet").read_bytes())
    (tmp_path / "skills.parquet").write_bytes(b"not parquet")
    with pytest.raises(DataError, match="not a readable Parquet"):
        connect(tmp_path)


def test_excel_matches_table(con):
    result = search(con, normalize_query("data"), Filters())
    exported = pd.read_excel(BytesIO(to_excel(result.skills)))
    pd.testing.assert_frame_equal(exported, result.skills, check_dtype=False)


@pytest.mark.parametrize(
    "query, expected",
    [
        ("Product manager", "Product_manager_skills.xlsx"),
        ("C++ / .NET: dev?", "C_NET_dev_skills.xlsx"),
        ("///", "skills_skills.xlsx"),
    ],
)
def test_safe_filename(query, expected):
    assert safe_filename(query) == expected
