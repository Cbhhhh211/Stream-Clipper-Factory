FROM python:3.11-slim

# Install ffmpeg and yt-dlp system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY services/requirements.txt /app/services/requirements.txt
RUN pip install --no-cache-dir -r services/requirements.txt

# Copy project code
COPY stream_clipper/ /app/stream_clipper/
COPY services/ /app/services/

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8000
