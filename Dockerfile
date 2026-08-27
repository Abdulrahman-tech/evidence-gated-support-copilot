FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SUPPORT_COPILOT_KNOWLEDGE_PATH=/app/data/kubernetes/knowledge.json

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY data/kubernetes/knowledge.json ./data/kubernetes/knowledge.json

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"

CMD ["uvicorn", "support_copilot.api:create_app_from_env", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
