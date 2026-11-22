from backend.posting_text import posting_markdown


def test_stored_html_and_new_markdown():
    html = "&amp;lt;h3&amp;gt;Responsibilities&amp;lt;/h3&amp;gt;&amp;lt;ul&amp;gt;&amp;lt;li&amp;gt;Design hardware&amp;lt;/li&amp;gt;&amp;lt;/ul&amp;gt;"
    assert posting_markdown(html) == "### Responsibilities\n\n- Design hardware"
    markdown = "## Skills\n\n- **CAD**\n- C++"
    assert posting_markdown(markdown) == markdown
