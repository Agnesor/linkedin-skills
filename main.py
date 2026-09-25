"""LinkedIn Skill Stats: the skills employers ask for most, by job title."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

from app import data
from app.excel import safe_filename, to_excel
from app.search import Filters, QueryError, normalize_query
from app.text import escape_markdown

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("linkedin_skills")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
REPO_URL = "https://github.com/Agnesor/linkedin-skills"
DATASET_URL = "https://www.kaggle.com/datasets/asaniczka/1-3m-linkedin-jobs-and-skills-2024"
TOP_CHART = 20

st.set_page_config(page_title="LinkedIn Skill Stats", page_icon="📊", layout="centered")


@st.cache_resource(show_spinner=False)
def get_connection() -> duckdb.DuckDBPyConnection:
    return data.connect(DATA_DIR)


@st.cache_data(show_spinner=False)
def get_filter_options() -> dict[str, list[tuple[str, int]]]:
    return data.filter_options(get_connection())


@st.cache_data(show_spinner=False)
def get_total_postings() -> int:
    return data.total_postings(get_connection())


# Exceptions are not cached by st.cache_data, so a transient failure is retried next time.
@st.cache_data(show_spinner=False, ttl=3600, max_entries=500)
def run_search(terms: tuple[str, ...], filters: Filters) -> data.SearchResult:
    return data.search(get_connection(), terms, filters)


def pills(label: str, options: list[tuple[str, int]], key: str) -> list[str]:
    counts = dict(options)
    return st.pills(
        label,
        list(counts),
        selection_mode="multi",
        format_func=lambda value: f"{value} · {counts[value]:,}",
        key=key,
        help="Leave empty to include all.",
    )


def render_header(total: int) -> None:
    st.title("LinkedIn Skill Stats")
    st.markdown(
        "Find the skills employers ask for most for a job title, based on "
        f"**{total:,}** unique LinkedIn job postings from January 2024."
    )
    with st.expander("How does it work?"):
        st.markdown(
            f"""
The data comes from the [1.3M LinkedIn Jobs & Skills (2024)]({DATASET_URL}) dataset by
[asaniczka](https://www.kaggle.com/asaniczka) (ODC-By 1.0): mid-senior and associate postings
from the United States, the United Kingdom, Canada and Australia, with skills extracted from
each job description by Named Entity Recognition. Reposts of the same job are counted once.

Every word of your query must appear in the job title as a whole word, in any order, so
`QA` does not match "aqua" and `C++` or `.NET` work as expected. The table shows, for the
matched postings, how many list each skill and what share of the matched postings that is.
"""
        )


COUNT_COLUMN = {"Postings": st.column_config.NumberColumn(format="localized")}


def skills_chart(top: pd.DataFrame) -> alt.Chart:
    return (
        alt.Chart(top)
        .mark_bar()
        .encode(
            x=alt.X("Percentage:Q", title="% of matched postings"),
            y=alt.Y("Skill:N", sort="-x", title=None, axis=alt.Axis(labelLimit=240)),
            tooltip=["Skill", alt.Tooltip("Postings:Q", format=","), "Percentage"],
        )
    )


def render_results(query: str, result: data.SearchResult) -> None:
    shown = escape_markdown(query)
    if result.matched == 0:
        st.info(f"No postings match “{shown}”. Try fewer words or remove a filter.")
        return
    st.subheader(f"{result.matched:,} postings match “{shown}”")

    st.altair_chart(skills_chart(result.skills.head(TOP_CHART)), width="stretch")

    st.dataframe(
        result.skills,
        hide_index=True,
        width="stretch",
        column_config={
            **COUNT_COLUMN,
            "Percentage": st.column_config.NumberColumn("% of matched", format="%.1f%%"),
        },
    )
    st.download_button(
        "Download as Excel",
        data=lambda: to_excel(result.skills),
        file_name=safe_filename(query),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        on_click="ignore",
    )

    st.markdown("**Matched postings by country and level**")
    left, right = st.columns(2)
    for column, table in ((left, result.by_country), (right, result.by_level)):
        column.dataframe(table, hide_index=True, width="stretch", column_config=COUNT_COLUMN)


def render_footer() -> None:
    st.divider()
    st.markdown(
        "Feedback or ideas? Email [ilia.reutov.tech@gmail.com](mailto:ilia.reutov.tech@gmail.com) "
        f"or open an issue on [GitHub]({REPO_URL}).  \n"
        "Made by [Ilia Reutov](https://www.linkedin.com/in/ilia-reutov/). "
        "You can [buy me a coffee](https://www.buymeacoffee.com/Ilia_reutov) "
        "if you find this tool helpful!"
    )


def main() -> None:
    try:
        options = get_filter_options()
        total = get_total_postings()
    except data.DataError as exc:
        logger.error("data unavailable: %s", exc)
        st.error("The dataset is not available right now. Please try again later.")
        st.stop()

    render_header(total)

    with st.form("search"):
        query = st.text_input(
            "Job title",
            placeholder="Product manager",
            help="Examples: Product manager, Data scientist, QA engineer, C++ developer",
            max_chars=100,
        )
        countries = pills("Country", options["country"], "countries")
        levels = pills("Level", options["level"], "levels")
        job_types = pills("Workplace", options["job_type"], "job_types")
        submitted = st.form_submit_button("Search", type="primary")

    if submitted:
        try:
            terms = normalize_query(query)
            filters = Filters.of(countries, levels, job_types)
            with st.spinner("Searching…"):
                st.session_state.result = (query.strip(), run_search(terms, filters))
        except QueryError as exc:
            st.warning(str(exc))
        except duckdb.Error:
            logger.exception("search failed for %r", query)
            st.error("The search failed. Please try again in a moment.")

    if "result" in st.session_state:
        render_results(*st.session_state.result)

    render_footer()


main()
