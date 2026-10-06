"""Find recruiters / HR contacts for a company, from three public sources:
1. the job description itself (names and emails it mentions),
2. Hunter.io's directory of publicly listed work emails (department = HR),
3. the company's own careers / contact pages.
LinkedIn is not scraped (against its terms, and it blocks servers); the user gets
ready-made LinkedIn and Google searches to open in their own browser instead."""
import os
import re
import time
from urllib.parse import quote_plus, urlparse

import requests

from app.jobs import _get
from app.llm import chat_json

HUNTER = "https://api.hunter.io/v2/domain-search"
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PERSONAL_MAIL = {"gmail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "rediffmail.com",
                 "icloud.com", "proton.me", "protonmail.com", "live.com"}
_cache: dict = {}  # ponytail: in-process, resets on redeploy; saves Hunter's ~50 free searches/month
CACHE_SECONDS = 7 * 86400


def hunter_configured() -> bool:
    return bool(os.getenv("HUNTER_API_KEY"))


def clean_domain(text: str) -> str:
    text = (text or "").strip().lower()
    if not text:
        return ""
    host = urlparse(text if "//" in text else "//" + text).hostname or ""
    host = host.removeprefix("www.")
    return host if re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", host) else ""


EXTRACT_PROMPT = """From this job posting, extract only what is written in it. Never guess.
Return JSON: {"company": "hiring company name, or empty",
"website": "company website domain if written, or empty",
"contacts": [{"name": "...", "position": "...", "email": "..."}]}
A contact is a recruiter, HR person or hiring manager the posting names or tells candidates to contact. Leave fields empty when not stated."""


def from_job_description(jd: str) -> dict:
    """Company + contacts named in the JD. Regex always runs; Groq adds names when configured."""
    found = {"company": "", "website": "", "contacts": []}
    try:
        found.update(chat_json(EXTRACT_PROMPT, jd[:8000], max_tokens=600) or {})
    except Exception:
        pass
    contacts = [c for c in found.get("contacts") or [] if isinstance(c, dict) and (c.get("name") or c.get("email"))]
    known = {(c.get("email") or "").lower() for c in contacts}
    contacts += [{"name": "", "position": "", "email": e} for e in dict.fromkeys(EMAIL.findall(jd)) if e.lower() not in known]
    found["contacts"] = [{"name": str(c.get("name") or "").strip(), "position": str(c.get("position") or "").strip(),
                          "email": str(c.get("email") or "").strip().lower(), "source": "Job description"}
                         for c in contacts[:6]]
    return found


def _hunter(company: str, domain: str, **extra) -> dict:
    key = (company.lower(), domain, tuple(sorted(extra.items())))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    params = {"api_key": os.environ["HUNTER_API_KEY"], "limit": 10, **extra}
    params.update({"domain": domain} if domain else {"company": company})
    r = requests.get(HUNTER, params=params, timeout=20)
    if r.status_code == 404 or (r.status_code == 400 and "company" in r.text.lower()):
        data = {}  # Hunter couldn't resolve this company name
    else:
        r.raise_for_status()
        data = r.json().get("data") or {}
    _cache[key] = (time.time(), data)
    return data


def _hunter_contacts(data: dict) -> list[dict]:
    out = []
    for e in data.get("emails") or []:
        name = " ".join(x for x in (e.get("first_name"), e.get("last_name")) if x)
        out.append({"name": name, "position": e.get("position") or ("Shared inbox" if e.get("type") == "generic" else ""),
                    "email": e.get("value", ""), "source": "Hunter.io", "confidence": e.get("confidence"),
                    "linkedin": e.get("linkedin") or ""})
    return sorted(out, key=lambda c: -(c.get("confidence") or 0))


def _site_emails(domain: str) -> list[dict]:
    """careers@ / hr@ / jobs@ style addresses published on the company's own pages."""
    seen, out = set(), []
    for path in ("/careers", "/contact"):
        try:
            html = _get(f"https://{domain}{path}").text
        except Exception:
            continue
        for e in EMAIL.findall(html):
            e = e.lower()
            if e.endswith("@" + domain) and e not in seen and not re.search(r"\.(png|jpe?g|svg|webp)$", e):
                seen.add(e)
                out.append({"name": "", "position": "Listed on " + domain + path, "email": e, "source": "Company website"})
    return out[:5]


def search_links(company: str) -> list[dict]:
    q = lambda s: quote_plus(s)
    return [
        {"label": "Recruiters on LinkedIn",
         "url": f"https://www.linkedin.com/search/results/people/?keywords={q(company + ' recruiter')}"},
        {"label": "Talent acquisition on LinkedIn",
         "url": f"https://www.linkedin.com/search/results/people/?keywords={q(company + ' talent acquisition')}"},
        {"label": "Google search",
         "url": "https://www.google.com/search?q=" + q(f'site:linkedin.com/in "{company}" (recruiter OR "talent acquisition" OR HR)')},
    ]


def find_contacts(company: str, domain: str, jd: str) -> dict:
    jd_info = from_job_description(jd) if jd.strip() else {"contacts": []}
    company = company.strip() or jd_info.get("company", "")
    domain = clean_domain(domain) or clean_domain(jd_info.get("website", ""))
    if not domain:  # a work email in the JD tells us the company domain
        work = [c["email"].split("@")[1] for c in jd_info["contacts"] if "@" in c["email"]]
        domain = next((d for d in work if d not in PERSONAL_MAIL), "")

    contacts, pattern = list(jd_info["contacts"]), ""
    if hunter_configured() and (company or domain):
        data = _hunter(company, domain, department="hr")
        if not data.get("emails"):
            data = _hunter(company, domain or data.get("domain", ""), type="generic") or data
        domain = domain or data.get("domain") or ""
        company = company or data.get("organization") or ""
        pattern = data.get("pattern") or ""
        contacts += _hunter_contacts(data)
    if domain and not any(c["source"] != "Job description" for c in contacts):
        contacts += _site_emails(domain)

    # Fill in emails for people the JD names without one, using the company's email pattern.
    if pattern and domain:
        for c in contacts:
            parts = c["name"].lower().split()
            if not c["email"] and len(parts) >= 2:
                c["email"] = (pattern.replace("{first}", parts[0]).replace("{last}", parts[-1])
                              .replace("{f}", parts[0][0]).replace("{l}", parts[-1][0]) + "@" + domain)
                c["source"] += ", email guessed from company pattern"

    unique = {}
    for c in contacts:
        unique.setdefault(c["email"] or c["name"], c)
    return {
        "company": company,
        "domain": domain,
        "contacts": list(unique.values())[:12],
        "links": search_links(company) if company else [],
        "hunter": hunter_configured(),
    }
