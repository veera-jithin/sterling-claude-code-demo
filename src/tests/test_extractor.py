"""
Unit tests for HtmlExtractor.

Tests each behaviour of the HTML stripping and rendering pipeline in isolation.
No external calls — HtmlExtractor has no dependencies beyond beautifulsoup4.
"""

import pytest
from extractor import HtmlExtractor


@pytest.fixture
def extractor() -> HtmlExtractor:
    return HtmlExtractor()


# ---------------------------------------------------------------------------
# Noise removal
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_strips_style_tag(extractor):
    html = "<html><style>body { color: red; }</style><p>Hello</p></html>"
    result = extractor.extract(html)
    assert "color" not in result
    assert "Hello" in result


@pytest.mark.unit
def test_strips_script_tag(extractor):
    html = "<html><script>alert('xss')</script><p>Content</p></html>"
    result = extractor.extract(html)
    assert "alert" not in result
    assert "Content" in result


@pytest.mark.unit
def test_strips_head_tag(extractor):
    html = "<html><head><title>Page Title</title></head><body><p>Body</p></body></html>"
    result = extractor.extract(html)
    assert "Page Title" not in result
    assert "Body" in result


@pytest.mark.unit
def test_removes_style_attribute(extractor):
    html = '<p style="color:red; font-size:12px">Text</p>'
    result = extractor.extract(html)
    assert "color:red" not in result
    assert "Text" in result


@pytest.mark.unit
def test_removes_class_attribute(extractor):
    html = '<p class="MsoNormal">Text</p>'
    result = extractor.extract(html)
    assert "MsoNormal" not in result
    assert "Text" in result


@pytest.mark.unit
def test_removes_multiple_presentational_attributes(extractor):
    html = '<table width="100%" bgcolor="#ffffff" cellpadding="5"><tr><td>Data</td></tr></table>'
    result = extractor.extract(html)
    assert 'width="100%"' not in result
    assert 'bgcolor' not in result
    assert 'cellpadding' not in result
    assert "Data" in result


# ---------------------------------------------------------------------------
# Table preservation
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_preserves_table_tag(extractor):
    html = "<p>Before</p><table><tr><td>Lot</td><td>42</td></tr></table><p>After</p>"
    result = extractor.extract(html)
    assert "<table>" in result
    assert "<tr>" in result
    assert "<td>Lot</td>" in result
    assert "<td>42</td>" in result


@pytest.mark.unit
def test_preserves_nested_table_structure(extractor):
    html = """
    <table>
      <tr><td>Builder</td><td>Lennar</td></tr>
      <tr><td>Lot</td><td>7</td></tr>
      <tr><td>Block</td><td>3</td></tr>
    </table>
    """
    result = extractor.extract(html)
    assert "<table>" in result
    assert "Builder" in result
    assert "Lennar" in result
    assert "Lot" in result


@pytest.mark.unit
def test_table_surrounded_by_plain_text(extractor):
    html = "<p>Address details:</p><table><tr><td>Street</td><td>123 Main</td></tr></table><p>End</p>"
    result = extractor.extract(html)
    assert "Address details:" in result
    assert "<table>" in result
    assert "End" in result


# ---------------------------------------------------------------------------
# Block element to newline conversion
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_p_tag_becomes_newline(extractor):
    html = "<p>First</p><p>Second</p>"
    result = extractor.extract(html)
    assert "First" in result
    assert "Second" in result
    assert "\n" in result


@pytest.mark.unit
def test_div_tag_becomes_newline(extractor):
    html = "<div>Line one</div><div>Line two</div>"
    result = extractor.extract(html)
    assert "Line one" in result
    assert "Line two" in result
    assert result.index("Line one") < result.index("Line two")


@pytest.mark.unit
def test_br_tag_becomes_newline(extractor):
    html = "First<br>Second"
    result = extractor.extract(html)
    assert "First" in result
    assert "Second" in result
    assert "\n" in result


@pytest.mark.unit
def test_heading_tags_become_newlines(extractor):
    for tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        html = f"<{tag}>Title</{tag}><p>Body</p>"
        result = extractor.extract(html)
        assert "Title" in result
        assert "Body" in result


# ---------------------------------------------------------------------------
# List items
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_li_gets_bullet_prefix(extractor):
    html = "<ul><li>Item one</li><li>Item two</li></ul>"
    result = extractor.extract(html)
    assert "- Item one" in result
    assert "- Item two" in result


@pytest.mark.unit
def test_dt_dd_get_bullet_prefix(extractor):
    html = "<dl><dt>Term</dt><dd>Definition</dd></dl>"
    result = extractor.extract(html)
    assert "- Term" in result
    assert "- Definition" in result


# ---------------------------------------------------------------------------
# Whitespace normalisation
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_collapses_multiple_spaces(extractor):
    html = "<p>Too    many    spaces</p>"
    result = extractor.extract(html)
    assert "Too    many" not in result
    assert "Too many spaces" in result


@pytest.mark.unit
def test_limits_consecutive_newlines_to_two(extractor):
    html = "<p>A</p><p></p><p></p><p></p><p>B</p>"
    result = extractor.extract(html)
    assert "\n\n\n" not in result


@pytest.mark.unit
def test_strips_leading_and_trailing_whitespace(extractor):
    html = "   <p>Content</p>   "
    result = extractor.extract(html)
    assert result == result.strip()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_plain_text_passthrough(extractor):
    # Non-HTML input should be returned as-is (whitespace normalised)
    result = extractor.extract("Just plain text")
    assert result == "Just plain text"


@pytest.mark.unit
def test_empty_string_returns_empty(extractor):
    assert extractor.extract("") == ""


@pytest.mark.unit
def test_only_noise_returns_empty(extractor):
    html = "<style>body { margin: 0; }</style><script>var x = 1;</script>"
    result = extractor.extract(html)
    assert result == ""


@pytest.mark.unit
def test_preserves_href_attribute_in_anchor(extractor):
    # href is not in _STYLE_ATTRIBUTES — should be kept
    html = '<a href="https://example.com">Link</a>'
    result = extractor.extract(html)
    assert "Link" in result
