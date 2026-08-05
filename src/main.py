"""
main.py — full pipeline: source postings automatically, score them,
supervise the scoring, save results to Postgres.

Usage:
    python src/main.py
"""

from db import init_db, save_match, get_top_matches, get_scored_keys
from matcher import extract_resume_text, score_multiple_postings
from sources import fetch_all_postings, dedupe_against_db

RESUME_PATH = "data/resume.pdf"  # put your resume PDF here


def main():
    init_db()

    resume_text = extract_resume_text(RESUME_PATH)
    print(f"Resume loaded — {len(resume_text)} characters extracted.\n")

    # --- Sourcing agent ---
    all_postings = fetch_all_postings()
    already_scored = get_scored_keys()
    postings = dedupe_against_db(all_postings, already_scored)

    if not postings:
        print("No new postings to score. Add company slugs in sources.py to pull more.")
        return

    # --- Scoring agent (supervised) ---
    scored = score_multiple_postings(resume_text, postings, supervised=True)

    print("\n" + "=" * 50)
    for posting in scored:
        result = posting["result"]
        verdict = result.get("_supervisor", {}).get("verdict", "n/a")
        print(f"{posting['company']} — {posting['job_title']}: {result['match_score']}/100 "
              f"[supervisor: {verdict}]")
        print(f"  {result['summary']}\n")

        save_match(
            company=posting["company"],
            job_title=posting["job_title"],
            job_posting_text=posting["text"],
            result=result,
            source=posting.get("source"),
            external_id=posting.get("external_id"),
            posting_url=posting.get("url"),
            location_tag=posting.get("location_tag"),
        )

    print("=" * 50)
    print("Top matches (score >= 65) saved so far:")
    for row in get_top_matches(limit=15, min_score=65):
        contact = f" | Contact: {row['contact_name']}" if row.get('contact_name') else ""
        print(f"  [{row['match_score']}] {row['company']} — {row['job_title']} "
              f"({row['location_tag']}, {row['status']}){contact}")
        print(f"      {row['posting_url']}")


if __name__ == "__main__":
    main()
