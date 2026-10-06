import os
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import requests
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import analysis, jobs, llm, outreach

ROOT = Path(__file__).resolve().parent.parent
MAX_UPLOAD = 5 * 1024 * 1024


def _warm():
    analysis._roles()
    if outreach.rows():
        outreach.vectors()


@asynccontextmanager
async def lifespan(_):
    threading.Thread(target=_warm, daemon=True).start()  # embed roles + faculty off the request path
    yield


app = FastAPI(title="Shortlist", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")

_hits: dict = defaultdict(deque)


def rate_limit(request: Request, bucket: str, per_hour: int) -> None:
    # ponytail: per-process memory; fine for one Render instance. Use Redis if you scale out.
    h = request.headers  # Render sits behind Cloudflare, which sets the real client IP here
    ip = h.get("cf-connecting-ip") or h.get("true-client-ip") or request.client.host
    q, now = _hits[(bucket, ip)], time.time()
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= per_hour:
        raise HTTPException(429, "Too many requests from your network. Try again in a little while.")
    q.append(now)


def upstream(e: Exception, what: str):
    status = getattr(getattr(e, "response", None), "status_code", None)
    if status in (401, 403):
        return HTTPException(502, f"The {what} API key was rejected. Check it in your Render settings.")
    if status == 429:
        return HTTPException(502, f"The {what} quota is used up for now. Try again later.")
    return HTTPException(502, f"The {what} service didn't respond. Try again in a minute.")


@app.get("/")
def home():
    return FileResponse(ROOT / "frontend" / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "llm": bool(os.getenv("GROQ_API_KEY")), "jobs": jobs.configured(),
            "faculty": outreach.institutes()}


@app.post("/api/analyze")
def analyze(request: Request, resume: UploadFile = File(...), job_description: str = Form("", max_length=15000)):
    rate_limit(request, "analyze", 40)
    data = resume.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "That file is over 5 MB. Export a lighter PDF.")
    try:
        text = analysis.parse_resume(resume.filename or "", data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:
        raise HTTPException(400, "Couldn't open that file. Make sure it's a valid PDF or DOCX.")
    return {**analysis.analyze(text, job_description), "resume_text": text}


class ResumeIn(BaseModel):
    resume_text: str = Field(min_length=50, max_length=30000)


class ReviewIn(ResumeIn):
    job_description: str = Field("", max_length=15000)
    top_role: str = Field("", max_length=80)
    missing: list[str] = Field(default_factory=list, max_length=20)
    ats: int = 0


@app.post("/api/review")
def review(body: ReviewIn, request: Request):
    if not os.getenv("GROQ_API_KEY"):
        return {"configured": False}
    rate_limit(request, "llm", 30)
    try:
        out = llm.review(body.resume_text, body.job_description,
                         {"top_role": body.top_role, "missing": body.missing, "ats": body.ats})
    except (requests.RequestException, ValueError) as e:
        raise upstream(e, "Groq")
    return {"configured": True, **out}


class JobsIn(ResumeIn):
    roles: list[str] = Field(min_length=1, max_length=3)
    country: str = Field("in", pattern="^[a-z]{2}$")
    city: str = Field("", max_length=60)
    date_posted: Literal["all", "today", "3days", "week", "month"] = "month"


@app.post("/api/jobs")
def find_jobs(body: JobsIn, request: Request):
    rate_limit(request, "jobs", 20)
    skills = analysis.extract_skills(body.resume_text)
    vec = analysis.text_vector(body.resume_text, skills)
    roles = [r.strip()[:80] for r in body.roles if r.strip()]
    try:
        return jobs.find_jobs(vec, skills, roles, body.country, body.city.strip(), body.date_posted)
    except requests.RequestException as e:
        raise upstream(e, "JSearch")


class UrlIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


@app.post("/api/job-from-url")
def job_from_url(body: UrlIn, request: Request):
    rate_limit(request, "scrape", 30)
    try:
        return jobs.scrape_job(body.url.strip())
    except (ValueError, OSError) as e:
        raise HTTPException(400, str(e) if isinstance(e, ValueError) else "Couldn't reach that website.")


class FacultyIn(ResumeIn):
    institute: str = Field("", max_length=60)


@app.post("/api/faculty")
def faculty(body: FacultyIn, request: Request):
    rate_limit(request, "faculty", 40)
    skills = analysis.extract_skills(body.resume_text)
    vec = analysis.text_vector(body.resume_text, skills)
    return {"available": bool(outreach.institutes()), "institutes": outreach.institutes(),
            "matches": outreach.match_professors(vec, skills, body.institute)}


class Recipient(BaseModel):
    name: str = Field("", max_length=120)
    email: str = Field("", max_length=200)
    institute: str = Field("", max_length=120)
    department: str = Field("", max_length=200)
    interests: str = Field("", max_length=1500)
    company: str = Field("", max_length=200)
    title: str = Field("", max_length=200)
    description: str = Field("", max_length=4000)


class EmailIn(ResumeIn):
    purpose: Literal["research", "job"]
    recipient: Recipient


@app.post("/api/email")
def email(body: EmailIn, request: Request):
    rate_limit(request, "llm", 30)
    p = analysis.profile(body.resume_text)
    skills = analysis.extract_skills(body.resume_text)
    return outreach.draft_email(body.resume_text, p, skills, body.recipient.model_dump(), body.purpose)
