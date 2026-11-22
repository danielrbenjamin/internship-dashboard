import asyncio
import re
from html import unescape
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

SEARCH_URL = "https://api.exa.ai/search"
UBC = re.compile(r"\b(?:UBC|(?:the )?University of British Columbia)\b", re.IGNORECASE)
ROLE_WORDS = {
    "engineer",
    "engineering",
    "intern",
    "internship",
    "student",
    "co",
    "op",
    "team",
    "the",
    "and",
    "summer",
    "fall",
    "winter",
    "spring",
    "autumn",
}


def plain(value):
    if not isinstance(value, str):
        return ""
    return " ".join(unescape(re.sub(r"<[^>]+>", "", value)).split())


def rank_profiles(results, company, team):
    profiles = {}
    employer = re.compile(r"(?<!\w)" + re.escape(company) + r"(?!\w)", re.IGNORECASE)
    team_words = set(re.findall(r"[a-z]+", team.casefold())) - ROLE_WORDS
    for row in results:
        if not isinstance(row, dict) or not isinstance(row.get("url"), str):
            continue
        try:
            url = urlsplit(row["url"])
        except (KeyError, ValueError):
            continue
        if url.scheme != "https" or not re.fullmatch(r"(?:[a-z]{2,3}\.)?linkedin\.com", url.netloc.lower()):
            continue
        if not re.fullmatch(r"/in/[\w%-]+/?", url.path):
            continue
        title = re.sub(r"\s*\|\s*LinkedIn.*$", "", plain(row.get("title", "")), flags=re.IGNORECASE)
        highlights = row.get("highlights")
        excerpts = [plain(value) for value in highlights[:6]] if isinstance(highlights, list) else []
        evidence = " ".join([title, *excerpts])
        snippet = next((excerpt for excerpt in excerpts if excerpt), "")
        if len(snippet) > 320:
            snippet = snippet[:317].rsplit(" ", 1)[0] + "…"
        name = re.split(r"\s+[-–—|]\s+", title, maxsplit=1)[0]
        if not name or len(name) > 100:
            continue
        key = url.path.rstrip("/")
        candidate = profiles.setdefault(
            key,
            {
                "name": name,
                "url": "https://www.linkedin.com" + key,
                "headline": title,
                "snippet": snippet,
                "team_match": False,
                "ubc": False,
                "employer_match": False,
            },
        )
        candidate["employer_match"] |= bool(employer.search(evidence))
        team_match = bool(team_words and team_words <= set(re.findall(r"\w+", evidence.casefold())))
        ubc_match = bool(UBC.search(evidence))
        candidate["team_match"] |= team_match
        candidate["ubc"] |= ubc_match
        if (ubc_match or team_match) and snippet:
            candidate["snippet"] = snippet
    return sorted(
        (p for p in profiles.values() if p["employer_match"]),
        key=lambda p: (p["team_match"] + p["ubc"], p["team_match"]),
        reverse=True,
    )[:25]


async def search_people(api_key, company, team):
    if not company:
        raise HTTPException(422, "Enter an employer to search for.")
    if not api_key.strip():
        raise HTTPException(
            503, "Add EXA_API_KEY to .env to enable in-page LinkedIn search."
        )
    base = f"LinkedIn profiles for people who currently work at {company}"
    team_phrase = f" in roles related to {team}" if team else ""
    queries = [base + team_phrase, base + " and attended the University of British Columbia (UBC)"]
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:

        async def fetch(query):
            response = await client.post(
                SEARCH_URL,
                headers={"x-api-key": api_key.strip()},
                json={"query": query, "category": "people", "type": "lite", "numResults": 12,
                      "includeDomains": ["linkedin.com"], "contents": {"highlights": True}},
            )
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("results") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                raise TypeError("Unexpected Exa response")
            return rows

        responses = await asyncio.gather(*(fetch(query) for query in queries), return_exceptions=True)
    successful = [response for response in responses if isinstance(response, list)]
    if not successful:
        codes = {result.response.status_code for result in responses if isinstance(result, httpx.HTTPStatusError)}
        if 429 in codes:
            raise HTTPException(429, "The search provider is rate limiting requests. Try again shortly.")
        if codes & {401, 403}:
            raise HTTPException(502, "Exa refused the search. Check the server's EXA_API_KEY.")
        if 402 in codes:
            raise HTTPException(502, "Exa requires available search credits.")
        raise HTTPException(502, "Public profile search is temporarily unavailable.")
    people = rank_profiles((row for batch in successful for row in batch), company, team)
    return {"people": people, "partial": len(successful) < len(responses)}
