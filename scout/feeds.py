import html
import re
from urllib.parse import urlparse

import httpx

from .models import Source


def plain(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", value, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def safe_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Job link must be a public HTTPS URL")
    return value


def workplace(value: str) -> str:
    value = (value or "").lower()
    if "hybrid" in value:
        return "hybrid"
    if "remote" in value:
        return "remote"
    if "on-site" in value or "onsite" in value:
        return "onsite"
    return "unknown"


def normalize(source: Source, payload) -> list[dict]:
    provider = source.provider
    rows = payload if provider == "lever" else payload["jobs"]
    if not isinstance(rows, list):
        raise ValueError("Job feed did not return a list")
    jobs = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Job feed contains an invalid listing")
        if provider == "greenhouse":
            jid, title = str(row["id"]), row["title"]
            location = (row.get("location") or {}).get("name") or "Not specified"
            description, url = plain(row.get("content", "")), row["absolute_url"]
            arrangement, published, salary = workplace(location), None, ""
        elif provider == "lever":
            jid, title = row["id"], row["text"]
            location = (row.get("categories") or {}).get("location") or "Not specified"
            sections = " ".join(
                f"{s.get('text', '')} {s.get('content', '')}" for s in (row.get("lists") or [])
            )
            description = plain(
                f"{row.get('descriptionPlain') or row.get('description', '')} "
                f"{sections} {row.get('additionalPlain', '')}"
            )
            url = row["hostedUrl"]
            arrangement = workplace((row.get("workplaceType") or "") + " " + location)
            published, salary = None, ""
            pay = row.get("salaryRange") or {}
            if pay.get("min") is not None and pay.get("max") is not None:
                salary = (
                    f"{pay.get('currency', '')} {pay['min']:,.0f}–{pay['max']:,.0f} "
                    f"{pay.get('interval', '')}"
                ).strip()
        else:
            if row.get("isListed") is False:
                continue
            url, title = row["jobUrl"], row["title"]
            jid = url.rstrip("/").split("/")[-1]
            location = row.get("location") or "Not specified"
            description = plain(row.get("descriptionPlain") or row.get("descriptionHtml", ""))
            arrangement = (
                "remote" if row.get("isRemote") else workplace(row.get("workplaceType", ""))
            )
            published = row.get("publishedAt")
            salary = (row.get("compensation") or {}).get("compensationTierSummary", "") or ""
        jobs.append(
            {
                "external_id": str(jid),
                "title": title,
                "company": source.company,
                "location": location,
                "description": description[:60000],
                "url": safe_url(url),
                "workplace": arrangement,
                "published": published,
                "salary": salary,
            }
        )
    return jobs


async def fetch_source(source: Source, client: httpx.AsyncClient) -> list[dict]:
    urls = {
        "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{source.board}/jobs?content=true",
        "lever": f"https://api.lever.co/v0/postings/{source.board}?mode=json",
        "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{source.board}?includeCompensation=true",
    }
    response = await client.get(urls[source.provider])
    response.raise_for_status()
    return normalize(source, response.json())


def source_from_url(url: str) -> Source | None:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    providers = {
        "boards.greenhouse.io": "greenhouse",
        "job-boards.greenhouse.io": "greenhouse",
        "jobs.lever.co": "lever",
        "jobs.ashbyhq.com": "ashby",
    }
    if parsed.scheme != "https" or parsed.hostname not in providers or not parts:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]+", parts[0]):
        return None
    return Source(provider=providers[parsed.hostname], board=parts[0], company=parts[0])


async def discover(profile, key: str, client: httpx.AsyncClient) -> list[Source]:
    role = " OR ".join(profile.roles[:3]) or "software engineer"
    locations = " OR ".join(profile.locations[:3])
    response = await client.post(
        "https://api.tavily.com/search",
        json={
            "api_key": key,
            "query": f"({role}) jobs {locations}",
            "include_domains": [
                "boards.greenhouse.io",
                "job-boards.greenhouse.io",
                "jobs.lever.co",
                "jobs.ashbyhq.com",
            ],
            "max_results": 12,
            "search_depth": "basic",
        },
    )
    response.raise_for_status()
    found = {}
    for result in response.json()["results"]:
        source = source_from_url(result["url"])
        if source:
            found[(source.provider, source.board)] = source
    return list(found.values())
