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
# Built from your actual job search tracker (Tiers 1-3): FP&A/Finance, Revenue
# Management, Supply Chain/Product, and Data Analyst tracks.
TARGET_TITLE_KEYWORDS = [
    # Finance / FP&A
    "financial analyst",
    "fp&a",
    "fp & a",
    "finance analyst",
    "financial planning",
    "engagement finance",
    "sales finance",
    "gtm finance",
    "portfolio analyst",
    "portfolio/asset",
    "asset management analyst",
    "capital planning",
    "healthcare strategy analyst",
    "strategy/finance",
    "credit analyst",
    "treasury analyst",

    # Revenue Management / Pricing (careful: excludes actuarial "Pricing Analyst" below)
    "revenue analyst",
    "revenue management analyst",
    "rm analyst",
    "inventory analyst",

    # Supply Chain / Product
    "supply chain analyst",
    "demand planning",
    "supply planning",
    "s&op analyst",
    "category analyst",
    "category pricing",
    "merchandise planning",
    "assortment analyst",

    # Data / BI
    "data analyst",
    "business analyst",
    "bi analyst",
    "business intelligence analyst",
    "analytics analyst",
    "insight analyst",
    "analytics engineer",
]

# Titles to exclude even if they match a keyword above — two categories:
# 1. Seniority/leadership tiers you're not targeting
# 2. Specific title families that share words but are a different career track
#    (e.g. "Pricing Analyst" alone, outside revenue management, is usually the
#    actuarial track requiring SOA/CAS exams — not a fit per your own notes)
EXCLUDED_TITLE_SIGNALS = [
    "director",
    " vp ",
    " vp,",
    " vp-",
    "vice president",
    "head of",
    "staff ",
    "principal ",
    # Note: "senior manager" specifically excluded, but plain "senior financial analyst"
    # and "lead analyst"/"lead financial analyst" are fine — those stay individual-contributor.
    "senior manager",
]


def _title_matches(title: str) -> bool:
    title_lower = title.lower()
    if any(signal in title_lower for signal in EXCLUDED_TITLE_SIGNALS):
        return False
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


# Locations you're open to — where you live, and anywhere you'd be willing to relocate to.
# Add city names, "remote", state abbreviations, etc. Matching is case-insensitive.
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
    # add any other cities/regions you'd genuinely relocate to
]

# Specific locations you do NOT want, regardless of whether relocation is offered.
# You mentioned no hard-pass locations right now — leave empty unless that changes.
EXCLUDED_LOCATIONS = [
    # no hard passes currently
]


def tag_location(posting_text: str) -> str:
    """
    Lightweight rule-based location tagger — no LLM call, just keyword matching
    against the posting text. Returns one of: 'preferred', 'excludes', 'unclear'.

    Only keys off actual place names, not the word "relocation" itself — a posting
    that offers relocation to a place you like (or already live in) should NOT be excluded.
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
