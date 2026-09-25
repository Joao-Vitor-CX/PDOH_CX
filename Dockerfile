FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY bracell/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

RUN groupadd --gid 10001 pdoh_cx \
    && useradd --uid 10001 --gid pdoh_cx --create-home --home-dir /home/pdoh_cx pdoh_cx

COPY --chown=pdoh_cx:pdoh_cx bracell/ /app/
COPY --chown=pdoh_cx:pdoh_cx shared/ /app/shared/

RUN mkdir -p /app/logs /app/outputs \
    && chown -R pdoh_cx:pdoh_cx /app /home/pdoh_cx

USER 10001:10001

CMD ["python", "-m", "src.healthcheck", "--wait"]
