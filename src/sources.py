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
from html.parser import HTMLParser
import html


class _StructuredHTMLExtractor(HTMLParser):
    """
    HTML-to-text converter that preserves basic structure — paragraph breaks,
    bullet points, and bold text — instead of flattening everything into one
    unbroken blob. Produces lightweight Markdown-ish output:
      - <p>, <div>, <br> become paragraph/line breaks
      - <li> becomes a "- " bullet line
      - <strong>/<b> gets wrapped in ** ** so it still reads as emphasis
    """
    BLOCK_TAGS = {"p", "div", "br", "h1", "h2", "h3", "h4"}
    BOLD_TAGS = {"strong", "b"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self.in_bold = False
        self.in_li = False

    def handle_starttag(self, tag, attrs):
        if tag == "li":
            self.in_li = True
            self.parts.append("\n- ")
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in self.BOLD_TAGS:
            self.in_bold = True
            self.parts.append("**")

    def handle_endtag(self, tag):
        if tag == "li":
            self.in_li = False
        elif tag in self.BOLD_TAGS:
            self.in_bold = False
            self.parts.append("**")

    def handle_data(self, data):
        self.parts.append(data)

    def get_text(self):
        return "".join(self.parts)


def strip_html(raw_html: str) -> str:
    """
    Convert Greenhouse posting HTML into lightweight, structure-preserving text
    before sending to the scoring agent and storing in the database. Cuts token
    usage versus raw HTML while keeping paragraphs/bullets/bold intact, so the
    dashboard's "About this role" section can actually render it readably
    instead of one flat wall of text.
    """
    if not raw_html:
        return ""
    # Decode HTML entities FIRST — some sources return tags entity-encoded
    # (e.g. "&lt;div&gt;" instead of literal "<div>"), which the parser would
    # otherwise treat as inert text rather than real structure to preserve.
    raw_html = html.unescape(raw_html)
    parser = _StructuredHTMLExtractor()
    try:
        parser.feed(raw_html)
        text = parser.get_text()
    except Exception:
        # If parsing fails for any reason, fall back to the raw text rather than crash
        return raw_html

    # Collapse runs of blank lines/spaces left behind by nested tags, but keep
    # genuine paragraph breaks (double newlines) and bullet lines intact.
    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if line]
    return "\n".join(lines)

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

# Workday companies — each entry is (tenant, site, wd_server).
# You have to find these manually per company (see fetch_workday_postings
# docstring for how). Example entries left commented as a template.
WORKDAY_COMPANIES = [
    # ("companytenant", "ExternalCareerSite", "wd5"),
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
        raw_content = job.get("content", "")
        clean_content = strip_html(raw_content)
        postings.append({
            "company": company_slug,
            "job_title": title,
            "text": clean_content,
            "source": "greenhouse",
            "external_id": str(job.get("id")),
            "url": job.get("absolute_url", ""),
            "location_tag": tag_location(clean_content + " " + title),
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
    """Pull postings from every configured Greenhouse, Lever, and Workday company."""
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

    for tenant, site, wd_server in WORKDAY_COMPANIES:
        try:
            all_postings.extend(fetch_workday_postings(tenant, site, wd_server))
        except requests.RequestException as e:
            print(f"  Workday fetch failed for '{tenant}': {e}")

    total_companies = len(GREENHOUSE_COMPANIES) + len(LEVER_COMPANIES) + len(WORKDAY_COMPANIES)
    print(f"Sourcing agent found {len(all_postings)} matching postings "
          f"across {total_companies} companies.")
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


def fetch_workday_postings(tenant: str, site: str, wd_server: str = "wd1") -> list[dict]:
    """
    Pull open postings from a company's Workday CXS endpoint.

    Unlike Greenhouse/Lever, this isn't an officially documented public API —
    it's the internal endpoint Workday's own careers-page frontend calls. It
    generally works fine for light, personal-scale use, but each company needs
    manual setup:

    1. Visit the company's careers page (usually {tenant}.myworkdayjobs.com or
       similar) and open browser dev tools -> Network tab.
    2. Look for a request to a URL containing "/wday/cxs/{tenant}/{site}/jobs".
    3. The subdomain before ".wd#.myworkdayjobs.com" is your `tenant`.
    4. The "wd#" part (wd1, wd3, wd5, etc.) is your `wd_server` — varies per company.
    5. The path segment after the tenant in that URL is your `site`.

    Only returns title, location, and the posting's detail-page URL — NOT the
    full description. Workday requires a second request per job to get full
    text, which isn't done here by default to keep this cheap/fast; add it
    later if you want full-description scoring for Workday postings too.
    """
    url = f"https://{tenant}.{wd_server}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Accept-Language": "en-US",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"https://{tenant}.{wd_server}.myworkdayjobs.com/en-US/{site}",
    }

    postings = []
    offset = 0
    limit = 20

    while True:
        payload = {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": ""}
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        job_postings = data.get("jobPostings", [])
        if not job_postings:
            break

        for job in job_postings:
            title = job.get("title", "")
            if not _title_matches(title):
                continue
            external_path = job.get("externalPath", "")
            location_text = job.get("locationsText", "")
            postings.append({
                "company": tenant,
                "job_title": title,
                # No full description available without a second request —
                # use title + location as a lightweight stand-in for now.
                "text": f"{title} — {location_text}",
                "source": "workday",
                "external_id": external_path or title,
                "url": f"https://{tenant}.{wd_server}.myworkdayjobs.com/en-US/{site}{external_path}",
                "location_tag": tag_location(location_text + " " + title),
            })

        offset += limit
        total = data.get("total", 0)
        if offset >= total:
            break

    return postings


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
