FROM python:3.12-slim

# Install system deps: ffmpeg for video processing, libGL for OpenCV
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source (exclude secrets via .dockerignore)
COPY . .

# Run as non-root user for security
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app
USER appuser

# Cloud Run injects PORT env var (default 8080)
ENV PORT=8080
ENV ENVIRONMENT=production

EXPOSE 8080

# Use uvicorn directly for production (single worker; scale via Cloud Run instances)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT} --workers 1 --log-level info"]
