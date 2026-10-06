"""Cold outreach: match a resume to IIT/IIM faculty by research interest, and draft emails.

The faculty directory is private data. It's read from PROFESSORS_CSV (a Render secret
file in production) and is gitignored, so it never lands in the public repo."""
import csv
import os
import re
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.analysis import DATA, extract_skills, scale
from app.embed import embed
from app.llm import chat_json


def _path() -> Path:
    return Path(os.getenv("PROFESSORS_CSV") or DATA / "professors.csv")


@lru_cache
def rows() -> list[dict]:
    if not _path().exists():
        return []
    with open(_path(), newline="", encoding="utf-8") as f:
        out = list(csv.DictReader(f))
    for r in out:
        r["skills"] = extract_skills(r["interests"])
    return out


_lock = threading.Lock()


def vectors():
    with _lock:  # startup warm-up and the first request must not both embed 1,600 rows
        return _vectors()


@lru_cache
def _vectors():
    return embed([f"{r['interests'] or r['department']}. Department of {r['department']}" for r in rows()])


def institutes() -> list[str]:
    return sorted({r["institute"] for r in rows()})


def match_professors(resume_vec, skills: list[str], institute: str = "", limit: int = 12) -> list[dict]:
    if not rows():
        return []
    vecs = vectors()
    have = set(skills)
    shared = [[s for s in r["skills"] if s in have] for r in rows()]
    # Topic similarity, nudged up when their stated interests name skills you actually have.
    fit = np.array([0.75 * scale(float(sim), 0.1, 0.55) + 0.25 * min(len(sh), 2) / 2
                    for sim, sh in zip(vecs @ resume_vec, shared)])
    out = []
    for i in np.argsort(-fit):
        r = rows()[i]
        if institute and not r["institute"].startswith(institute):  # "IIT", "IIM" or a full name
            continue
        out.append({k: r[k] for k in ("name", "institute", "department", "interests", "email")}
                   | {"fit": round(100 * fit[i]), "shared": shared[i]})
        if len(out) >= limit:
            break
    return out


EMAIL_PROMPT = """You write cold emails for Indian students. Follow this structure, which comes from a template that gets replies:
1. Greeting using the recipient's name, plus one short pleasantry.
2. One sentence on who the sender is: name, year and degree, college (from the resume).
3. The ask, framed modestly: {ask}. Leave room for the recipient to suggest where the sender fits.
4. Why this recipient: one sentence linking their specific work ({why}) to the sender's projects. Use only the details given; never invent papers, products or facts.
5. Proof: two short bullet points ("- ") taken from the resume, keeping its real numbers.
6. One line of leadership or initiative only if the resume shows it.
7. Close: resume attached, LinkedIn/GitHub links from the resume, thanks, then the sender's name and phone number on separate lines.
Rules: body under 170 words, plain text, no em dashes, no "esteemed", no flattery, never invent anything. Subject: specific, at most 9 words.
Return JSON: {{"subject": "...", "body": "..."}}"""


def draft_email(resume_text: str, profile: dict, skills: list[str], recipient: dict, purpose: str) -> dict:
    if purpose == "research":
        ask = "a research internship or project under their guidance"
        why = f"their research areas: {recipient.get('interests') or recipient.get('department')}"
        who = f"{recipient.get('name')}, {recipient.get('department')}, {recipient.get('institute')}"
    else:
        ask = f"the {recipient.get('title') or 'open'} role, or any team where the sender's skills fit"
        why = f"the role's requirements: {(recipient.get('description') or '')[:1500]}"
        who = f"the hiring team at {recipient.get('company')}"
    try:
        out = chat_json(EMAIL_PROMPT.format(ask=ask, why=why),
                        f"RECIPIENT: {who}\n\nSENDER RESUME:\n{resume_text[:8000]}", max_tokens=1200)
    except Exception:
        out = None
    if out and out.get("body"):
        clean = lambda s: str(s).replace(" — ", ", ").replace("—", "-").strip()
        return {"subject": clean(out.get("subject", "")), "body": clean(out["body"]), "ai": True}
    return {**_template(profile, skills, recipient, purpose), "ai": False}


def _template(p: dict, skills: list[str], r: dict, purpose: str) -> dict:
    """No-LLM fallback: the cold-mail template with the blanks filled in."""
    name = p.get("name") or "[Your name]"
    top = ", ".join(skills[:4]) or "[your key skills]"
    links = "\n".join(p.get("links") or ["[LinkedIn]"])
    if purpose == "research":
        last = re.sub(r"^(prof\.?|dr\.?)\s*", "", r.get("name", ""), flags=re.I).split()[-1:] or [""]
        hello = f"Dear Prof. {last[0]},"
        area = (r.get("interests") or r.get("department") or "").split(",")[0].strip()
        ask = (f"I am writing to ask whether there is an opportunity to work on a research internship or project "
               f"under your guidance. Your work in {area} lines up closely with what I have been building.")
        subject = f"Research internship enquiry: {area}"[:70]
        org = r.get("institute", "")
    else:
        hello = f"Dear {r.get('company', '')} hiring team,"
        ask = (f"I am writing about the {r.get('title', 'open')} role, or any team where my skills would be useful. "
               f"The work described in the posting is close to what I have been building.")
        subject = f"Application: {r.get('title', 'open role')}"[:70]
        org = r.get("company", "")
    body = (f"{hello}\n\nI hope you are doing well. My name is {name}, and I am a student working mostly with {top}.\n\n"
            f"{ask}\n\n- [Your strongest project, with a number: accuracy, users, speed]\n"
            f"- [Your second project or internship, with its result]\n\n"
            f"I would value the chance to contribute to {org}. My resume is attached for your consideration.\n\n"
            f"{links}\n\nThank you for your time.\n{name}\n{p.get('phone') or '[Phone]'}")
    return {"subject": subject, "body": body}
