# Image de production minimale pour l'application Conseil IA.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY agents ./agents
COPY app ./app

RUN pip install --no-cache-dir ".[providers]"

EXPOSE 8000

CMD ["python", "app/server.py"]
