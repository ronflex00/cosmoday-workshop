FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt \
    && groupadd --gid 10001 sentinel \
    && useradd --uid 10001 --gid sentinel --no-create-home sentinel \
    && mkdir -p /app/data \
    && chown sentinel:sentinel /app/data

COPY app ./app
USER 10001:10001
EXPOSE 8000
# One process: live state and WebSocket clients are local to this process.
CMD ["python", "-m", "app.main"]
