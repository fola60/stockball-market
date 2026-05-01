FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/worker/pyproject.toml ./
COPY services/worker/app ./app

RUN pip install --no-cache-dir .

CMD ["stockball-worker", "worker"]
