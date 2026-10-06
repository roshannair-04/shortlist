"""Run: pytest -q. Uses a fake embedder so it needs no model download."""
import hashlib
import json

import numpy as np

import app.analysis as A
import app.jobs as J


def fake_embed(texts):
    vecs = np.array([np.frombuffer(hashlib.sha256(t.encode()).digest(), dtype=np.uint8)[:16] for t in texts], float)
    return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


A.embed = J.embed = fake_embed

RESUME = """Asha Verma
asha.verma@gmail.com | +91 98765 43210 | linkedin.com/in/ashaverma
EDUCATION
B.Tech Computer Science, 2022 - 2026
EXPERIENCE
Built a FastAPI service in Python with PostgreSQL serving 12,000 daily users
Reduced Docker image size by 60% and cut deploy time from 9 to 3 minutes
PROJECTS
Real-time object detection with YOLOv8 and OpenCV at 30 FPS on a Jetson Nano
Research and development work; I excel at debugging. Go-to person for reviews.
SKILLS
Python, C++, SQL, Git, React
""" + "Extra filler line describing coursework and clubs in some detail. " * 30


def test_skills_are_exact_not_fuzzy():
    s = A.extract_skills(RESUME)
    assert {"Python", "C++", "SQL", "FastAPI", "PostgreSQL", "Docker", "YOLO", "OpenCV", "React"} <= set(s)
    # 'R&D', 'excel at', 'Go-to' and the linkedin URL must not produce skills
    assert not {"R", "C", "Excel", "Go", "Java"} & set(s)
    assert "GitHub" not in A.extract_skills("see github.com/asha")


def test_ats_is_deterministic_and_bounded():
    a, b = A.analyze(RESUME), A.analyze(RESUME)
    assert a["ats"] == b["ats"]
    assert 0 <= a["ats"]["score"] <= 100
    assert sum(c["max"] for c in a["ats"]["checks"]) == 100
    assert a["profile"]["email"] == "asha.verma@gmail.com" and a["profile"]["phone"]


def test_match_uses_job_skills():
    m = A.analyze(RESUME, "Backend Engineer: Python, FastAPI, Kubernetes, AWS")["match"]
    assert m["matched"] == ["Python", "FastAPI"] and set(m["missing"]) == {"Kubernetes", "AWS"}
    assert m["coverage"] == 50


def test_roles_only_reference_known_skills():
    known = {name for name, _ in A._skill_patterns()}
    roles = json.loads((A.DATA / "roles.json").read_text())
    assert all(s in known for skills in roles.values() for s in skills)


def test_jobs_ranked_and_trends_counted(monkeypatch):
    fake = [
        {"job_id": "1", "job_title": "ML Intern", "job_description": "Python, PyTorch, Docker", "employer_name": "A"},
        {"job_id": "2", "job_title": "CV Engineer", "job_description": "Python, OpenCV, YOLO, FastAPI", "employer_name": "B"},
    ]
    monkeypatch.setenv("RAPIDAPI_KEY", "x")
    monkeypatch.setattr(J, "_jsearch", lambda *a: fake)
    skills = A.extract_skills(RESUME)
    out = J.find_jobs(A.text_vector(RESUME, skills), skills, ["Computer Vision Engineer"], "in", "Pune")
    assert out["jobs"][0]["company"] == "B"
    assert {"skill": "Python", "count": 2, "have": True} in out["trends"]
    assert "Pune%2C+India" in out["linkedin"][0]["url"]


def test_contacts_merge_jd_hunter_and_guess(monkeypatch):
    import app.contacts as C

    jd = "Cvent is hiring an SDE intern in Gurugram. Questions? Write to campus.hiring@cvent.com."
    monkeypatch.setattr(C, "chat_json", lambda *a, **k: {"company": "Cvent", "website": "",
                        "contacts": [{"name": "Priya Sharma", "position": "Talent Acquisition", "email": ""}]})
    monkeypatch.setenv("HUNTER_API_KEY", "x")
    monkeypatch.setattr(C, "_hunter", lambda company, domain, **kw: {
        "domain": "cvent.com", "organization": "Cvent", "pattern": "{first}.{last}",
        "emails": [{"value": "a.rao@cvent.com", "first_name": "Anil", "last_name": "Rao", "position": "HR Manager", "confidence": 80},
                   {"value": "k.das@cvent.com", "first_name": "Kavya", "last_name": "Das", "position": "Recruiter", "confidence": 95}]})
    out = C.find_contacts("", "", jd)
    emails = [c["email"] for c in out["contacts"]]
    assert out["company"] == "Cvent" and out["domain"] == "cvent.com"
    assert "priya.sharma@cvent.com" in emails and "campus.hiring@cvent.com" in emails
    assert emails.index("k.das@cvent.com") < emails.index("a.rao@cvent.com")  # sorted by confidence
    assert "linkedin.com" in out["links"][0]["url"]
    assert C.clean_domain("https://www.Cvent.com/careers") == "cvent.com" and C.clean_domain("not a site") == ""
