import os
import re
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
cur = conn.cursor()
cur.execute("""
    SELECT id, company, job_title, job_posting_text
    FROM job_matches
    WHERE company = 'agoda' AND job_title LIKE '%Lead Analyst%'
    ORDER BY match_score DESC
    LIMIT 1;
""")
row = cur.fetchone()
conn.close()

if not row:
    print("No matching row found.")
else:
    raw = row["job_posting_text"] or ""
    print("=== RAW FIRST 200 CHARS ===")
    print(repr(raw[:200]))
    print()
    print("=== LENGTH ===", len(raw))
    print()
    print("=== CONTAINS '<' ===", "<" in raw)
    print("=== CONTAINS '>' ===", ">" in raw)
    print()

    text = raw.strip()
    if "<" in text and ">" in text:
        text = re.sub(r"<[^>]+>", " ", text)
        text = text.replace("&nbsp;", " ")
        text = " ".join(text.split())

    print("=== AFTER STRIP, FIRST 200 CHARS ===")
    print(repr(text[:200]))
