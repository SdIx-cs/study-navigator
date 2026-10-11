# Production Dockerfile for Study Navigator (DevCamp Scale Pillar)
# Built for Google Cloud Run and Google Cloud Agent Runtime.
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY study_agent/ ./study_agent/
COPY backend/ ./backend/

# Cloud Run injects PORT; default to 8000 for local container testing
ENV PORT=8000
ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Start production uvicorn server binding to all interfaces
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]
