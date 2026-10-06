"""Groq chat completions (OpenAI-compatible). Returns None when GROQ_API_KEY isn't set,
so every caller has a non-LLM fallback."""
import json
import os

import requests

URL = "https://api.groq.com/openai/v1/chat/completions"


def chat_json(system: str, user: str, max_tokens: int = 1500) -> dict | None:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return None
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
        "temperature": 0.4,
        "max_completion_tokens": max_tokens,
    }
    if model.startswith("openai/gpt-oss"):
        body["reasoning_effort"] = "low"
    r = requests.post(URL, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=45)
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])


REVIEW_PROMPT = """You are a senior technical recruiter in India reviewing a student's resume.
Be specific and honest; refer to actual content from the resume. No generic advice.
Never invent experience the candidate does not have.
Return JSON: {"summary": "2 sentences on how this resume reads to a recruiter",
"strengths": ["3 short points"],
"improvements": ["4 concrete, prioritised fixes"],
"rewrites": [{"before": "an existing weak bullet, verbatim", "after": "a stronger version using action verb + what + measurable result; keep facts, mark guessed numbers as [X]"}] (2 to 3 items)}"""


def review(resume_text: str, job_description: str, analysis: dict) -> dict | None:
    user = (
        f"RESUME:\n{resume_text[:9000]}\n\n"
        f"TARGET JOB DESCRIPTION:\n{job_description[:4000] or '(none given; review for the best-fit role)'}\n\n"
        f"AUTOMATED FINDINGS: best-fit role {analysis.get('top_role')}; "
        f"missing skills {analysis.get('missing')}; ATS score {analysis.get('ats')}/100."
    )
    return chat_json(REVIEW_PROMPT, user)
