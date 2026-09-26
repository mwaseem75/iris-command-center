# -----------------------------------------------------------------------------
# IRIS Command Center — FastAPI backend image.
#
# Built by docker-compose.yml's `backend` service. Configuration comes
# entirely from environment variables set there (see app/config.py); no
# .env file is copied into the image (see .dockerignore).
# -----------------------------------------------------------------------------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app

RUN useradd --create-home --uid 10001 commandcenter
USER commandcenter

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
