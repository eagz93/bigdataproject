# ==============================================================================
# Dockerfile.app — Dashboard Streamlit (Python 3.12-slim)
# ==============================================================================
# Imagen ligera: solo pandas + streamlit + openpyxl (sin PySpark/Java).
# Lee el plan de compras desde el volumen compartido 'data_compartida'
# (generado por el contenedor spark_etl) y persiste movimientos en su propio
# volumen nombrado 'movimientos_data'.
# ==============================================================================

# Pinned a Bookworm (Debian 12) para consistencia con el contenedor spark_etl.
FROM python:3.12-slim-bookworm

# ------------------------------------------------------------------------------
# Sistema: curl para el health-check de Streamlit.
# ------------------------------------------------------------------------------
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------------------------
# Seguridad: usuario sin privilegios de root.
# ------------------------------------------------------------------------------
RUN groupadd -r appuser \
    && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# ------------------------------------------------------------------------------
# Dependencias Python (capa cacheada).
# ------------------------------------------------------------------------------
COPY requirements-app.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-app.txt

# ------------------------------------------------------------------------------
# Código de la aplicación y configuración de Streamlit.
# ------------------------------------------------------------------------------
COPY app.py ./
COPY .streamlit/ ./.streamlit/

# ------------------------------------------------------------------------------
# Directorios de datos (el contenido llega vía volúmenes Docker en compose).
# Se crean vacíos para que los puntos de montaje existan en la imagen.
# ------------------------------------------------------------------------------
RUN mkdir -p \
        data/plan_reabastecimiento_csv \
        data/segmentos_sku_csv \
        data/movimientos \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8501

# ------------------------------------------------------------------------------
# Health-check: /_stcore/health devuelve 200 cuando Streamlit está listo.
# ------------------------------------------------------------------------------
HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["python", "-m", "streamlit", "run", "app.py", \
            "--server.port=8501", \
            "--server.address=0.0.0.0"]
