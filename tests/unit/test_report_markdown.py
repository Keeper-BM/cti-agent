import pytest

from backend.reports.markdown import link, text


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "file:///C:/secrets",
        "https://user:pass@example.com",
        "data:text/html,evil",
        None,
    ],
)
def test_links_only_use_safe_web_destinations(value):
    assert "](" not in link("source", value)


def test_markdown_text_and_url_cannot_escape_their_container():
    value = text("a|b\n# title [label](evil) <script> x\u202e y")
    assert "\\|" in value and "\\#" in value and "\n" not in value
    assert "<script>" not in value and "\u202e" not in value
    url = link("safe", "https://example.com/path(a)?q=%20")
    assert "path%28a%29" in url
