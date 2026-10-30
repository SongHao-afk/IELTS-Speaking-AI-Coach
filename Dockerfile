FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

# Only core dependencies are required: Groq is accessed through httpx.
# Build fails if requirements cannot be installed or are incompatible.
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip check

COPY app/ ./app/
COPY web/ ./web/
COPY run.py ./run.py

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data
USER appuser
ENV APP_DATA_DIR=/data
EXPOSE 8000

# Bind 0.0.0.0 only inside the container. Compose publishes localhost on the host.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
