"""
dashboard/app.py — Streamlit dashboard for job-search-agent

View scored job matches, filter by score/location, click through to the
posting URL, and mark postings as applied — all from a browser, including
on your phone once this is deployed.

Run locally with:
    streamlit run dashboard/app.py
"""

import os
import re
import hashlib
import textwrap
import html
import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

st.set_page_config(page_title="Job Search Dashboard", layout="wide")

# --- Custom styling — dark, card-based, job-board feel ---
st.markdown("""
<style>
    .stApp { background: #121212; }
    .block-container { padding-top: 1.6rem; max-width: 900px; }

    .job-card {
        background: #1C1C1C;
        border: 1px solid #2E2E2E;
        border-radius: 8px;
        padding: 1rem 1.2rem;
        margin-bottom: 0.8rem;
    }
    .job-card:hover { border-color: #444444; }

    .card-header { display: flex; align-items: flex-start; gap: 0.7rem; }

    .avatar {
        width: 44px; height: 44px; min-width: 44px;
        border-radius: 6px;
        display: flex; align-items: center; justify-content: center;
        font-weight: 700; font-size: 1.05rem; color: #0F0F0F;
    }

    .header-text { flex: 1; min-width: 0; }

    .job-title {
        font-size: 1.02rem;
        font-weight: 600;
        color: #F2F2F0;
        line-height: 1.3;
        margin-bottom: 0.1rem;
    }
    .company-name {
        font-size: 0.88rem;
        color: #B8B8B5;
        margin-bottom: 0.15rem;
    }
    .job-meta {
        font-size: 0.78rem;
        color: #8A8A87;
    }

    .match-pill {
        display: inline-block;
        font-weight: 700;
        font-size: 0.78rem;
        padding: 0.2rem 0.6rem;
        border-radius: 20px;
        white-space: nowrap;
    }
    .score-high   { background: #1E3B2A; color: #4ADE80; }
    .score-mid    { background: #35331E; color: #D9C25A; }
    .score-low    { background: #3A2323; color: #E08787; }

    .chip-row { margin-top: 0.65rem; }
    .chip {
        display: inline-block;
        font-size: 0.75rem;
        padding: 0.18rem 0.55rem;
        border-radius: 20px;
        margin-right: 0.35rem;
        margin-bottom: 0.35rem;
    }
    .chip-match { background: #1E3B2A; color: #4ADE80; }
    .chip-gap   { background: #2A2A2A; color: #9A9A97; }

    .summary-text {
        font-size: 0.87rem;
        color: #C4C4C0;
        line-height: 1.5;
        margin-top: 0.6rem;
    }

    a.view-job-link {
        color: #4ADE80;
        font-weight: 600;
        font-size: 0.85rem;
        text-decoration: none;
    }
    a.view-job-link:hover { text-decoration: underline; }

    .stats-row {
        display: flex;
        flex-direction: row;
        justify-content: space-between;
        gap: 0.5rem;
        margin-top: 0.4rem;
    }
    .stat-item {
        flex: 1;
        text-align: center;
        min-width: 0;
    }
    .stat-value {
        font-size: 1.6rem;
        font-weight: 700;
        color: #F2F2F0;
        line-height: 1.1;
    }
    .stat-label {
        font-size: 0.72rem;
        color: #8A8A87;
        margin-top: 0.15rem;
    }
    @media (max-width: 640px) {
        .stat-value { font-size: 1.25rem; }
        .stat-label { font-size: 0.65rem; }
    }

    /* Mobile */
    @media (max-width: 640px) {
        .block-container { padding-left: 0.7rem; padding-right: 0.7rem; }
        .job-card { padding: 0.85rem 0.9rem; }
        div[data-testid="stButton"] > button {
            width: 100%;
            padding-top: 0.5rem;
            padding-bottom: 0.5rem;
        }
    }
</style>
""", unsafe_allow_html=True)


AVATAR_COLORS = ["#4ADE80", "#8A8A87", "#6EE7A8", "#5A5A57", "#34D399", "#A8A8A5"]


def avatar_color(company: str) -> str:
    """Deterministic color per company, so the same company always gets the same avatar color."""
    idx = int(hashlib.md5(company.encode()).hexdigest(), 16) % len(AVATAR_COLORS)
    return AVATAR_COLORS[idx]


def get_connection():
    if not DATABASE_URL:
        st.error("DATABASE_URL not found. Set it in .env locally, or in Streamlit Cloud's Secrets.")
        st.stop()
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def fetch_matches(min_score: int, location_search: str, status_filter: str,
                   search_text: str, sort_by: str):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            query = """
                SELECT id, company, job_title, match_score, location_tag,
                       contact_name, job_location, work_arrangement,
                       role_overview, key_responsibilities, key_requirements,
                       posting_url, status, summary,
                       matched_qualifications, skill_gaps, job_posting_text, created_at
                FROM job_matches
                WHERE match_score >= %s
            """
            params = [min_score]

            if location_search:
                query += " AND job_location ILIKE %s"
                params.append(f"%{location_search}%")

            if status_filter != "All":
                query += " AND status = %s"
                params.append(status_filter)

            if search_text:
                query += " AND (company ILIKE %s OR job_title ILIKE %s)"
                like_term = f"%{search_text}%"
                params.extend([like_term, like_term])

            if sort_by == "Newest first":
                query += " ORDER BY created_at DESC"
            else:
                query += " ORDER BY match_score DESC, created_at DESC"

            cur.execute(query, params)
            return cur.fetchall()
    finally:
        conn.close()


def fetch_status_counts():
    """Counts across ALL matches, ignoring current filters — for the summary bar."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT status, COUNT(*) as count
                FROM job_matches
                GROUP BY status;
            """)
            rows = cur.fetchall()
            counts = {"not_applied": 0, "applied": 0, "skipped": 0}
            for row in rows:
                counts[row["status"]] = row["count"]
            return counts
    finally:
        conn.close()


def update_status(match_id: int, new_status: str):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE job_matches SET status = %s WHERE id = %s;",
                (new_status, match_id),
            )
        conn.commit()
    finally:
        conn.close()


def clean_title(title: str) -> str:
    """Strip stray markdown bold markers the scoring agent sometimes leaves in titles."""
    return re.sub(r"\*\*", "", title).strip()


def score_class(score: int) -> str:
    if score >= 75:
        return "score-high"
    if score >= 60:
        return "score-mid"
    return "score-low"


def location_display(m: dict) -> str:
    """
    Show the actual job location and work arrangement when available (postings
    scored after this feature was added). Falls back to the preference-based
    label for older rows that don't have this data yet.
    """
    job_location = m.get("job_location")
    work_arrangement = m.get("work_arrangement")

    if not job_location and not work_arrangement:
        # Old row, scored before this feature existed — fall back
        return {"preferred": "Preferred location", "excludes": "Not preferred",
                "unclear": "Location unclear"}.get(m.get("location_tag"), "Location unclear")

    parts = []
    if job_location:
        parts.append(job_location)
    if work_arrangement and work_arrangement != "unspecified":
        parts.append(work_arrangement.capitalize())
    return " · ".join(parts) if parts else "Location unclear"


# --- UI ---
st.title("Job Search Dashboard")

# Stats summary — reflects ALL matches regardless of current filters
counts = fetch_status_counts()
total = sum(counts.values())

stats_html = textwrap.dedent(f"""
<div class="stats-row">
<div class="stat-item"><div class="stat-value">{total}</div><div class="stat-label">Total</div></div>
<div class="stat-item"><div class="stat-value">{counts['applied']}</div><div class="stat-label">Applied</div></div>
<div class="stat-item"><div class="stat-value">{counts['skipped']}</div><div class="stat-label">Skipped</div></div>
<div class="stat-item"><div class="stat-value">{counts['not_applied']}</div><div class="stat-label">Pending</div></div>
</div>
""").strip()
st.markdown(stats_html, unsafe_allow_html=True)

st.divider()

with st.expander("Search & filters", expanded=False):
    search_text = st.text_input("Search company or title", placeholder="e.g. agoda, financial analyst")
    filter_row = st.columns(4)
    with filter_row[0]:
        min_score = st.slider("Minimum match score", 0, 100, 65, step=5)
    with filter_row[1]:
        location_search = st.text_input("Location", placeholder="e.g. Miami, Remote")
    with filter_row[2]:
        status_filter = st.selectbox("Status", ["All", "not_applied", "applied", "skipped"])
    with filter_row[3]:
        sort_by = st.selectbox("Sort by", ["Score (high to low)", "Newest first"])

matches = fetch_matches(min_score, location_search, status_filter, search_text, sort_by)
st.caption(f"{len(matches)} matches")

def clean_posting_text(text: str, max_chars: int = 1400) -> str:
    """
    Prepare the raw posting text for the About This Role display.

    Handles two cases:
    - New, clean data (structure-preserving strip_html from the pipeline):
      already has paragraph breaks/bullets/bold — just trim to length.
    - Old data scored before that fix existed: may still contain raw HTML
      tags. Defensively strip any leftover tags so it's at least readable,
      even though full structure can't be recovered without re-scoring.
    """
    if not text:
        return "No role description available."
    text = text.strip()

    # Decode HTML entities FIRST — the stored data has tags encoded as
    # &lt;div&gt; rather than literal <div>, so the raw text never contains
    # actual "<"/">" characters. Browsers auto-decode entities when
    # displaying text, which is why raw tags were visible on screen even
    # though this check below was technically correct against the raw string.
    text = html.unescape(text)

    # Defensive: strip any (now-decoded) HTML tags from pre-fix data
    if "<" in text and ">" in text:
        text = re.sub(r"<[^>]+>", " ", text)
        text = " ".join(text.split())

    # No truncation — this content is already behind a collapsed expander,
    # so the user has already opted in to seeing full detail by clicking it.
    return text


def split_into_sections(text: str) -> list:
    """
    Split posting text into (heading, body) sections using bold-only lines
    (e.g. "**About Agoda**") as section headers — this structure comes from
    strip_html()'s conversion of <strong>/<p> tags. Postings without any
    bold-only header lines are returned as a single unheaded section.
    """
    lines = text.split("\n")
    sections = []
    current_heading = None
    current_body = []

    heading_pattern = re.compile(r"^\*\*(.+?)\*\*:?$")

    for line in lines:
        stripped = line.strip()
        match = heading_pattern.match(stripped)
        if match and len(stripped) < 80:
            if current_body or current_heading:
                sections.append((current_heading, "\n".join(current_body).strip()))
            current_heading = match.group(1)
            current_body = []
        else:
            if stripped:
                current_body.append(stripped)

    if current_body or current_heading:
        sections.append((current_heading, "\n".join(current_body).strip()))

    if not sections:
        return [(None, text)]
    return sections


for m in matches:
    title = clean_title(m["job_title"])
    badge_class = score_class(m["match_score"])
    initial = (m["company"] or "?")[0].upper()
    color = avatar_color(m["company"] or "")

    matched_quals = (m.get("matched_qualifications") or [])[:4]
    gaps = (m.get("skill_gaps") or [])[:3]

    match_chips = "".join(f'<span class="chip chip-match">✓ {q}</span>' for q in matched_quals)
    gap_chips = "".join(f'<span class="chip chip-gap">{g}</span>' for g in gaps)

    contact_line = f' &nbsp;·&nbsp; Contact mentioned: {m["contact_name"]}' if m["contact_name"] else ""

    # NOTE: no leading whitespace on these lines — Markdown treats 4+ spaces of
    # indentation as a code block, which breaks HTML rendering. Building this
    # left-justified (or via textwrap.dedent) avoids that.
    card_html = textwrap.dedent(f"""
    <div class="job-card">
    <div class="card-header">
    <div class="avatar" style="background:{color};">{initial}</div>
    <div class="header-text">
    <div class="job-title">{title}</div>
    <div class="company-name">{m['company']}</div>
    <div class="job-meta">{location_display(m)} &nbsp;·&nbsp; {m['status'].replace('_', ' ')}{contact_line}</div>
    </div>
    <span class="match-pill {badge_class}">{m['match_score']}% match</span>
    </div>
    </div>
    """).strip()

    with st.container():
        st.markdown(card_html, unsafe_allow_html=True)

        with st.expander("About this role"):
            has_clean_data = bool(m.get("role_overview") or m.get("key_responsibilities") or m.get("key_requirements"))

            if has_clean_data:
                if m.get("role_overview"):
                    st.markdown(m["role_overview"])

                responsibilities = m.get("key_responsibilities") or []
                if responsibilities:
                    st.markdown("##### Key Responsibilities")
                    for item in responsibilities:
                        st.markdown(f"- {item}")

                requirements = m.get("key_requirements") or []
                if requirements:
                    st.markdown("##### Requirements")
                    for item in requirements:
                        st.markdown(f"- {item}")
            else:
                # Old row, scored before this feature existed — fall back to
                # the raw posting text, split on whatever structure survived.
                st.caption("This posting was scored before summarized role details existed — showing raw text instead.")
                cleaned = clean_posting_text(m.get("job_posting_text", ""))
                for heading, body in split_into_sections(cleaned):
                    if heading:
                        st.markdown(f"##### {heading}")
                    if body:
                        st.markdown(body)

        with st.expander("Why this could be a fit", expanded=True):
            if match_chips or gap_chips:
                st.markdown(f'<div class="chip-row">{match_chips}{gap_chips}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="summary-text">{m["summary"] or ""}</div>', unsafe_allow_html=True)

        link_col, applied_col, skip_col, reset_col = st.columns([3, 1, 1, 1])
        with link_col:
            if m['posting_url']:
                st.markdown(f'<a class="view-job-link" href="{m["posting_url"]}" target="_blank">View job posting →</a>',
                            unsafe_allow_html=True)
        with applied_col:
            if m['status'] != 'applied':
                if st.button("Mark applied", key=f"applied_{m['id']}"):
                    update_status(m['id'], 'applied')
                    st.rerun()
        with skip_col:
            if m['status'] != 'skipped':
                if st.button("Skip", key=f"skip_{m['id']}"):
                    update_status(m['id'], 'skipped')
                    st.rerun()
        with reset_col:
            if m['status'] != 'not_applied':
                if st.button("Reset", key=f"reset_{m['id']}"):
                    update_status(m['id'], 'not_applied')
                    st.rerun()

