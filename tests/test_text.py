from app.text import escape_markdown


def test_link_syntax_is_neutralized():
    escaped = escape_markdown("[click](http://evil.example)")
    assert "](" not in escaped.replace("\\]\\(", "")
    assert escaped == r"\[click\]\(http\://evil\.example\)"


def test_plain_titles_keep_their_letters():
    assert escape_markdown("C++ developer").replace("\\", "") == "C++ developer"
