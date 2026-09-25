import csv
from pathlib import Path

import pytest

from scripts.build_dataset import build

POSTINGS = [
    # job_link, title, company, location, country, level, job_type
    ("p1", "Senior C++ Developer", "A", "Austin", "United States", "Mid senior", "Onsite"),
    ("p2", "C# / .NET Developer", "B", "London", "United Kingdom", "Mid senior", "Hybrid"),
    ("p3", "QA Engineer", "C", "Toronto", "Canada", "Associate", "Remote"),
    ("p4", "Aquatics Coordinator", "D", "Sydney", "Australia", "Associate", "Onsite"),
    ("p5", "Product Manager", "E", "London", "United Kingdom", "Mid senior", "Onsite"),
    ("p6", "Manager, Product Marketing", "F", "Leeds", "United Kingdom", "Associate", "Onsite"),
    ("p7", "Data Scientist", "G", "Boston", "United States", "Mid senior", "Remote"),
    ("p8", "Data Engineer", "H", "Boston", "United States", "Mid senior", "Onsite"),
]
SKILLS = {
    "p1": "C++, Linux, Communication",
    "p2": "C#, .NET, Communication",
    "p3": "Testing, Communication",
    "p4": "Swimming, Communication",
    "p5": "Product Management, Communication, Roadmaps",
    "p6": "Marketing, Communication, Product Management",
    "p7": "Python, SQL, Communication",
    "p8": "Python, SQL, Linux",
}


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("dataset")
    postings = root / "postings.csv"
    with postings.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "job_link",
                "job_title",
                "company",
                "job_location",
                "search_country",
                "job_level",
                "job_type",
            ]
        )
        writer.writerows(POSTINGS)
    skills = root / "skills.csv"
    with skills.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["job_link", "job_skills"])
        writer.writerows(SKILLS.items())
    out = root / "build"
    build(postings, skills, out, min_skill_freq=1)
    return out
