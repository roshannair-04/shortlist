"""Live job listings (JSearch: aggregates LinkedIn, Indeed, Glassdoor, Naukri and company
career pages), skill-demand trends across those listings, and scraping a job description
from a pasted URL."""
import ipaddress
import json
import os
import socket
import time
from collections import Counter
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.analysis import extract_skills, scale
from app.embed import embed

JSEARCH = "https://jsearch.p.rapidapi.com/search"
NINJA = "https://api.openwebninja.com/jsearch/search-v2"  # same JSearch API, sold directly (has a free plan)


def _endpoint():
    if os.getenv("OPENWEBNINJA_API_KEY"):
        return NINJA, {"x-api-key": os.environ["OPENWEBNINJA_API_KEY"]}
    return JSEARCH, {"x-rapidapi-key": os.environ["RAPIDAPI_KEY"], "x-rapidapi-host": "jsearch.p.rapidapi.com"}


def configured() -> bool:
    return bool(os.getenv("OPENWEBNINJA_API_KEY") or os.getenv("RAPIDAPI_KEY"))
COUNTRIES = {"in": "India", "us": "United States", "gb": "United Kingdom", "ca": "Canada",
             "de": "Germany", "sg": "Singapore", "ae": "United Arab Emirates", "au": "Australia"}
_cache: dict = {}  # ponytail: in-process cache, resets on redeploy. Saves the free 200 req/month quota.
CACHE_SECONDS = 6 * 3600


def linkedin_search_url(role: str, location: str) -> str:
    return (f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(role)}"
            f"&location={quote_plus(location)}&f_TPR=r604800")


def _jsearch(query: str, country: str, date_posted: str) -> list[dict]:
    key = (query.lower(), country, date_posted)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    url, headers = _endpoint()
    r = requests.get(
        url,
        params={"query": query, "page": 1, "num_pages": 1, "country": country, "date_posted": date_posted},
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    data = r.json().get("data") or []
    if isinstance(data, dict):  # search-v2 may nest the list, e.g. {"data": {"jobs": [...]}}
        data = data.get("jobs") or data.get("data") or []
    _cache[key] = (time.time(), data)
    return data


def find_jobs(resume_vec, skills: list[str], roles: list[str], country: str, city: str,
              date_posted: str = "month") -> dict:
    where = ", ".join(x for x in (city, COUNTRIES.get(country, "")) if x)
    out = {
        "configured": configured(),
        "linkedin": [{"role": r, "url": linkedin_search_url(r, where)} for r in roles[:3]],
        "jobs": [],
        "trends": [],
    }
    if not out["configured"] or not roles:
        return out

    raw = _jsearch(f"{roles[0]} jobs in {where}", country, date_posted)
    if len(raw) < 6 and len(roles) > 1:
        raw += _jsearch(f"{roles[1]} jobs in {where}", country, date_posted)
    raw = list({j.get("job_id") or j.get("job_apply_link"): j for j in raw}.values())
    if not raw:
        return out

    have = set(skills)
    texts = [f"{j.get('job_title', '')}. {(j.get('job_description') or '')[:1200]}" for j in raw]
    sims = embed(texts) @ resume_vec
    demand = Counter()
    for j, sim in zip(raw, sims):
        js = extract_skills(f"{j.get('job_title', '')}\n{j.get('job_description') or ''}")
        demand.update(js)
        overlap = sum(s in have for s in js) / len(js) if js else 0
        place = ", ".join(x for x in (j.get("job_city"), j.get("job_state"), j.get("job_country")) if x)
        out["jobs"].append({
            "title": j.get("job_title"),
            "company": j.get("employer_name"),
            "logo": j.get("employer_logo"),
            "location": "Remote" if j.get("job_is_remote") else place,
            "type": (j.get("job_employment_type") or "").replace("FULLTIME", "Full-time")
                    .replace("PARTTIME", "Part-time").replace("INTERN", "Internship").replace("CONTRACTOR", "Contract"),
            "posted": j.get("job_posted_at_datetime_utc"),
            "source": j.get("job_publisher"),
            "url": j.get("job_apply_link"),
            "fit": round(100 * (0.5 * overlap + 0.5 * scale(float(sim)))),
            "matched": [s for s in js if s in have],
            "missing": [s for s in js if s not in have][:5],
            "description": (j.get("job_description") or "")[:4000],
        })
    out["jobs"].sort(key=lambda j: -j["fit"])
    out["trends"] = [{"skill": s, "count": n, "have": s in have} for s, n in demand.most_common(12)]
    out["sample"] = len(raw)
    return out


# ---------- job description from URL ----------

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _check_public(url: str) -> None:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("Paste a full http(s) link to the job posting.")
    # ponytail: resolve-then-fetch has a DNS-rebinding gap; fine for a public read-only fetch.
    for info in socket.getaddrinfo(p.hostname, None):
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError("That address isn't a public website.")


def _get(url: str) -> requests.Response:
    for _ in range(4):  # follow redirects by hand so every hop passes the public-address check
        _check_public(url)
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en"}, timeout=15,
                         allow_redirects=False, stream=True)
        if r.is_redirect:
            url = urljoin(url, r.headers["location"])
            continue
        r.raise_for_status()
        r._content = r.raw.read(3_000_000, decode_content=True)  # cap page size at 3 MB
        r._content_consumed = True
        return r
    raise ValueError("Too many redirects.")


def _text(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text("\n", strip=True)


def scrape_job(url: str) -> dict:
    try:
        r = _get(url)
    except requests.RequestException:
        raise ValueError("Couldn't open that page. Some sites (LinkedIn included) block automated "
                         "reads; paste the description instead.")
    soup = BeautifulSoup(r.text, "html.parser")

    # 1. schema.org JobPosting: LinkedIn, Greenhouse, Lever, Workday, Naukri and most ATSs embed it.
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data])
        for d in items:
            if isinstance(d, dict) and d.get("@type") == "JobPosting" and d.get("description"):
                org = d.get("hiringOrganization") or {}
                return {"title": d.get("title", ""), "company": org.get("name", "") if isinstance(org, dict) else "",
                        "description": _text(d["description"])[:8000]}

    # 2. Fallback: the biggest description-like block on the page.
    for bad in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        bad.decompose()
    blocks = soup.select(".show-more-less-html__markup, [class*=description], [id*=description], "
                         "[class*=job-details], article, main") or [soup.body or soup]
    text = max((b.get_text("\n", strip=True) for b in blocks), key=len)
    if len(text) < 200:
        raise ValueError("Couldn't find a job description on that page; paste it instead.")
    title = soup.title.get_text(strip=True) if soup.title else ""
    return {"title": title, "company": "", "description": text[:8000]}
