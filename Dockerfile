
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r appuser \
    && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

COPY requirements-app.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-app.txt

COPY app.py auth_utils.py movement_import.py operations_store.py ./
COPY .streamlit/config.toml ./.streamlit/config.toml

RUN printf '[users]\n' > .streamlit/secrets.toml

RUN mkdir -p \
        data/plan_reabastecimiento_csv \
        data/segmentos_sku_csv \
        data/movimientos \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["python", "-m", "streamlit", "run", "app.py", \
            "--server.port=8501", \
            "--server.address=0.0.0.0"]
