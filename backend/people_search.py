import asyncio
import re
from html import unescape
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
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
    return " ".join(unescape(re.sub(r"<[^>]+>", "", value)).split())


def rank_profiles(results, company, team):
    profiles = {}
    employer = re.compile(r"(?<!\w)" + re.escape(company) + r"(?!\w)", re.IGNORECASE)
    team_words = set(re.findall(r"[a-z]+", team.casefold())) - ROLE_WORDS
    for row in results:
        try:
            url = urlsplit(row["url"])
        except (KeyError, ValueError):
            continue
        if url.scheme != "https" or not re.fullmatch(r"(?:[a-z]{2,3}\.)?linkedin\.com", url.netloc.lower()):
            continue
        if not re.fullmatch(r"/in/[\w%-]+/?", url.path):
            continue
        title = re.sub(r"\s*\|\s*LinkedIn.*$", "", plain(row.get("title", "")), flags=re.IGNORECASE)
        snippet = plain(row.get("description", ""))
        evidence = " ".join([title, snippet, *(plain(s) for s in row.get("extra_snippets", []))])
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
    if not api_key:
        raise HTTPException(
            503, "Set BRAVE_SEARCH_API_KEY in the dashboard environment to search public LinkedIn profiles."
        )
    company_term = company.replace('"', "")
    team_term = " ".join(word for word in re.findall(r"[a-z]+", team.casefold()) if word not in ROLE_WORDS)
    base = f'site:linkedin.com/in "{company_term}"'
    queries = [base, f'{base} ("University of British Columbia" OR UBC)']
    if team_term:
        queries.insert(0, f"{base} {team_term}")
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:

        async def fetch(query):
            response = await client.get(
                SEARCH_URL,
                headers={"X-Subscription-Token": api_key},
                params={
                    "q": query,
                    "count": 12,
                    "country": "CA",
                    "extra_snippets": "true",
                    "text_decorations": "false",
                },
            )
            response.raise_for_status()
            return response.json().get("web", {}).get("results", [])

        responses = await asyncio.gather(*(fetch(query) for query in queries), return_exceptions=True)
    successful = [response for response in responses if isinstance(response, list)]
    if not successful:
        rate_limited = any(
            isinstance(response, httpx.HTTPStatusError) and response.response.status_code == 429
            for response in responses
        )
        if rate_limited:
            raise HTTPException(429, "The search provider is rate limiting requests. Try again shortly.")
        raise HTTPException(
            502, "Public profile search is unavailable. Check the Brave Search API key and try again."
        )
    people = rank_profiles((row for batch in successful for row in batch), company, team)
    return {"people": people, "partial": len(successful) < len(responses)}
