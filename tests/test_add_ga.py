import os

import pytest

import add_ga

HTML = "<!doctype html><html><head><title>x</title></head><body></body></html>"


@pytest.fixture
def index(tmp_path):
    path = tmp_path / "index.html"
    path.write_text(HTML)
    return path


def test_without_id_file_is_untouched(index):
    assert add_ga.inject(index, None).startswith("skipped")
    assert index.read_text() == HTML


def test_valid_id_is_injected_once(index):
    assert add_ga.inject(index, "G-ABC123") == "injected"
    assert add_ga.inject(index, "G-ABC123") == "already present"
    html = index.read_text()
    assert html.count("googletagmanager.com/gtag/js?id=G-ABC123") == 1
    assert html.index("<head>") < html.index("gtag.js") < html.index("<title>")


@pytest.mark.parametrize("bad", ["UA-123", "G-abc", "G-1'; alert(1)//"])
def test_invalid_id_is_rejected(index, bad):
    with pytest.raises(ValueError, match="invalid"):
        add_ga.inject(index, bad)
    assert index.read_text() == HTML


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_unwritable_index_logs_error_and_exits_zero(index, monkeypatch, capsys):
    index.chmod(0o444)
    monkeypatch.setattr(add_ga, "streamlit_index", lambda: index)
    monkeypatch.setenv("GA_MEASUREMENT_ID", "G-ABC123")
    assert add_ga.main() == 0
    assert "ERROR" in capsys.readouterr().err
