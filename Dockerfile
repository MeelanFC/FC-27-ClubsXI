# Alpine is safe here because the collector uses the Python standard library
# only. No compiled packages, so there is nothing for musl to break.
FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    CLUBSXI_DB=/data/clubsxi.sqlite3 \
    CLUBSXI_REPORT=/data/report.txt \
    CLUBSXI_POLL_MINUTES=30 \
    TZ=UTC

WORKDIR /app
COPY src/ /app/src/

RUN addgroup -g 1000 clubsxi \
    && adduser -D -u 1000 -G clubsxi clubsxi \
    && mkdir -p /data \
    && chown -R clubsxi:clubsxi /data /app
USER clubsxi

VOLUME ["/data"]

COPY --chown=clubsxi:clubsxi docker/healthcheck.py /app/healthcheck.py
HEALTHCHECK --interval=5m --timeout=20s --start-period=3m --retries=3 \
    CMD ["python", "/app/healthcheck.py"]

CMD ["python", "-m", "clubsxi", "run"]
