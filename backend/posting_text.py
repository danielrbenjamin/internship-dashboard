import html
import re

from bs4 import BeautifulSoup
from markdownify import markdownify

TAGS = re.compile(r"</?(?:p|div|span|ul|ol|li|br|hr|h[1-6]|b|strong|em|i|a|section|article|table|blockquote|script|style)(?:\s|/?>)", re.IGNORECASE)


def posting_markdown(value):
    value = value or ""
    for _ in range(3):
        if TAGS.search(value):
            break
        decoded = html.unescape(value)
        if decoded == value:
            break
        value = decoded
    if not TAGS.search(value):
        return value.strip()[:40000]
    soup = BeautifulSoup(value, "html.parser")
    for node in soup.select("script,style,iframe,img"):
        node.decompose()
    return markdownify(str(soup), heading_style="ATX", bullets="-", escape_underscores=False).strip()[:40000]
