# Build context is the REPO ROOT, not this directory — see docker-compose.yml
# (`build: {context: ., dockerfile: services/api/Dockerfile}`) and the note in
# app/__init__.py. app/parsing.py imports grp_calculator.py directly, which
# lives at the repo root, so the image has to preserve the same relative
# path between the two that the repo has on disk.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /repo

RUN addgroup --system app && adduser --system --ingroup app app

COPY grp_calculator.py ./grp_calculator.py
COPY services/api/requirements.txt ./services/api/requirements.txt
RUN python -m pip install --upgrade pip && python -m pip install -r services/api/requirements.txt

COPY services/api/app ./services/api/app

USER app

WORKDIR /repo/services/api

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
