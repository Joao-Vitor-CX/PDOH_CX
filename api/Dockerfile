FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && groupadd --gid 10002 consulta \
    && useradd --uid 10002 --gid consulta --create-home consulta
COPY api/__init__.py /app/api/__init__.py
COPY api/app /app/api/app
COPY shared /app/shared
USER 10002:10002
CMD ["python", "-m", "uvicorn", "api.app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS validation
USER root
RUN pip install --no-cache-dir httpx==0.28.1
COPY api/scripts/validate_live.py /app/api/scripts/validate_live.py
USER 10002:10002
CMD ["python", "/app/api/scripts/validate_live.py", "--output", "/reports/api-validation.json"]
