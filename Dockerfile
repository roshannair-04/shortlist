FROM python:3.12-slim

# MALLOC_ARENA_MAX / OMP_NUM_THREADS keep per-thread memory overhead low on the 512 MB instance.
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 FASTEMBED_CACHE=/app/.models MALLOC_ARENA_MAX=2 OMP_NUM_THREADS=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake the embedding model into the image so cold starts don't download it.
COPY app/__init__.py app/embed.py app/
RUN python -m app.embed

COPY . .

# Embed the private faculty list (a Render secret file) at build time, so cold starts
# load it instantly instead of spending minutes on the free tier's CPU. No-op without it.
RUN --mount=type=secret,id=professors_csv,dst=/etc/secrets/professors.csv,required=false \
    PROFESSORS_CSV=/etc/secrets/professors.csv python -m app.outreach

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
