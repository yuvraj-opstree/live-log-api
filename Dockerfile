FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1 \
    LOG_INTERVAL_MIN=0.1 \
    LOG_INTERVAL_MAX=1.0 \
    CRASH_PROBABILITY=0.004 \
    LOG_TIMESTAMP=0

WORKDIR /app
COPY app.py /app/app.py
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && adduser -D -u 10001 logger

USER logger
ENTRYPOINT ["/entrypoint.sh"]
