"""
sources.py — Sourcing agent

Pulls job postings from public Greenhouse and Lever job board APIs,
filters them against your target keywords, and dedupes against
what's already in the database before anything gets sent to the
(expensive) scoring agent.

No auth required for these endpoints — they're the same public boards
companies embed on their careers pages.
"""

import requests

# --- Config: companies to pull from ---
# Find the slug from the company's careers page URL, e.g.
# boards.greenhouse.io/stripe  -> slug is "stripe"
# jobs.lever.co/netflix        -> slug is "netflix"
GREENHOUSE_COMPANIES = [
    "agoda",
    "esri",
    "justworks",
]

LEVER_COMPANIES = [
    "allegiantair",
    "rover",
]

# Keywords to match against job titles — case-insensitive substring match.
# Keep this list tight; it's the cheap filter that keeps you from scoring
# every posting a company has open.
TARGET_TITLE_KEYWORDS = [
    "financial analyst",
    "data analyst",
    "business analyst",
    "finance",
    "analytics",
]


def _title_matches(title: str) -> bool:
    title_lower = title.lower()
    return any(keyword in title_lower for keyword in TARGET_TITLE_KEYWORDS)


def fetch_greenhouse_postings(company_slug: str) -> list[dict]:
    """Pull all open postings for a company from Greenhouse's public API."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs?content=true"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    postings = []
    for job in data.get("jobs", []):
        title = job.get("title", "")
        if not _title_matches(title):
            continue
        postings.append({
            "company": company_slug,
            "job_title": title,
            "text": job.get("content", ""),  # HTML — strip tags before scoring if needed
            "source": "greenhouse",
            "external_id": str(job.get("id")),
            "url": job.get("absolute_url", ""),
            "location_tag": tag_location(job.get("content", "") + " " + title),
        })
    return postings


def fetch_lever_postings(company_slug: str) -> list[dict]:
    """Pull all open postings for a company from Lever's public API."""
    url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    postings = []
    for job in data:
        title = job.get("text", "")
        if not _title_matches(title):
            continue
        description = job.get("descriptionPlain") or job.get("description", "")
        postings.append({
            "company": company_slug,
            "job_title": title,
            "text": description,
            "source": "lever",
            "external_id": str(job.get("id")),
            "url": job.get("hostedUrl", ""),
            "location_tag": tag_location(description + " " + title),
        })
    return postings


def fetch_all_postings() -> list[dict]:
    """Pull postings from every configured Greenhouse and Lever company."""
    all_postings = []

    for slug in GREENHOUSE_COMPANIES:
        try:
            all_postings.extend(fetch_greenhouse_postings(slug))
        except requests.RequestException as e:
            print(f"  Greenhouse fetch failed for '{slug}': {e}")

    for slug in LEVER_COMPANIES:
        try:
            all_postings.extend(fetch_lever_postings(slug))
        except requests.RequestException as e:
            print(f"  Lever fetch failed for '{slug}': {e}")

    print(f"Sourcing agent found {len(all_postings)} matching postings "
          f"across {len(GREENHOUSE_COMPANIES) + len(LEVER_COMPANIES)} companies.")
    return all_postings


# Locations you're open to. Add city names, "remote", state abbreviations, etc.
# Keep it lowercase — matching is case-insensitive.
PREFERRED_LOCATIONS = [
    "miami",
    "new york",
    "chicago",
    "boston",
    "washington, dc",
    "washington dc",
    "texas",
    "tennessee",
    "atlanta",
    "orlando",
    "remote",
]

# Locations/signals that mean "probably not" — relocation requirements you don't want,
# specific cities/countries that are dealbreakers, etc.
EXCLUDED_LOCATIONS = [
    # no hard passes right now
]


def tag_location(posting_text: str) -> str:
    """
    Lightweight rule-based location tagger — no LLM call, just keyword matching
    against the posting text. Returns one of: 'preferred', 'excludes', 'unclear'.
    """
    text_lower = posting_text.lower()

    if any(loc in text_lower for loc in EXCLUDED_LOCATIONS):
        return "excludes"

    if any(loc in text_lower for loc in PREFERRED_LOCATIONS):
        return "preferred"

    return "unclear"


def dedupe_against_db(postings: list[dict], already_scored_ids: set[str]) -> list[dict]:
    """
    Filter out postings whose (source, external_id) combo has already been scored.
    `already_scored_ids` should be a set of "source:external_id" strings pulled from the DB.
    """
    fresh = []
    for p in postings:
        key = f"{p['source']}:{p['external_id']}"
        if key not in already_scored_ids:
            fresh.append(p)
    skipped = len(postings) - len(fresh)
    if skipped:
        print(f"Skipped {skipped} postings already in the database.")
    return fresh
