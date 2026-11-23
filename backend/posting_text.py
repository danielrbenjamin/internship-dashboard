import html
import re

from bs4 import BeautifulSoup
from markdownify import markdownify

TAGS = re.compile(r"</?(?:p|div|span|ul|ol|li|br|hr|h[1-6]|b|strong|em|i|a|section|article|table|blockquote|script|style)(?:\s|/?>)", re.IGNORECASE)
US = r"(?:u\.?\s*s\.?|united states)"
US_PERSON = rf"{US}[\s-]+persons?\b"
REQUIRED = r"(?:must|shall|(?:is|are) required to)"
US_PERSON_RESTRICTION = re.compile(
    rf"\b(?<!not )(?<!doesnt )(?:{REQUIRED} (?:be|qualify as|be classified as)|requires?|requiring|"
    rf"restricted to|limited to|only(?: to)?(?: individuals who are(?: classified as)?)?) (?:an? )?{US_PERSON}"
    rf"|\b{US_PERSON}(?: status)? (?:(?:is|are) )?(?:required|only)\b",
    re.IGNORECASE,
)
EXPORT_CONTEXT = r"\b(?:itar|ear|export[\s-]+controls?)\b"
EXPORT_CITIZEN_RESTRICTION = re.compile(
    rf"{EXPORT_CONTEXT}[^!?;]{{0,140}}?\b{REQUIRED} be (?:an? )?{US} (?:citizens?|nationals?)\b"
    rf"|\b{REQUIRED} be (?:an? )?{US} (?:citizens?|nationals?)\b[^!?;]{{0,140}}?{EXPORT_CONTEXT}",
    re.IGNORECASE,
)
EXPORT_AUTHORIZATION_ALTERNATIVE = re.compile(
    r"\b(?:or|alternatively)\b[^.!?;]{0,120}\b(?:authorization|authorisation|licen[cs]e|exemption)\b",
    re.IGNORECASE,
)


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


def requires_us_person(description):
    if not re.search(r"\b(?:persons?|citizens?|nationals?)\b", description or "", re.IGNORECASE):
        return False
    text = " ".join(re.sub(r"[*_`'\"“”‘’]", "", posting_markdown(description)).split())
    text = re.sub(r"\bu\.\s*s\.(?=\s)", "US", text, flags=re.IGNORECASE)
    return any(
        not EXPORT_AUTHORIZATION_ALTERNATIVE.search(text[match.start():match.end() + 150])
        for rule in (US_PERSON_RESTRICTION, EXPORT_CITIZEN_RESTRICTION)
        for match in rule.finditer(text)
    )
