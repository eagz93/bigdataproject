# ============================================================================
# Dockerfile — Starbucks Plan de Compras (Streamlit)
# ============================================================================
# Imagen ligera: solo pandas + streamlit (sin PySpark/Java).
# Los notebooks se ejecutan en el host; el contenedor únicamente sirve el
# dashboard y persiste los movimientos a través de un volumen Docker.
# ============================================================================

FROM python:3.12-slim

# --------------------------------------------------------------------------
# Sistema: instalar curl (health check) y limpiar caché de apt.
# --------------------------------------------------------------------------
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# --------------------------------------------------------------------------
# Seguridad: usuario sin privilegios de root.
# --------------------------------------------------------------------------
RUN groupadd -r appuser \
    && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# --------------------------------------------------------------------------
# Dependencias Python (capa cacheada; solo se reconstruye si el archivo cambia).
# --------------------------------------------------------------------------
COPY requirements-app.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-app.txt

# --------------------------------------------------------------------------
# Código de la aplicación y configuración de Streamlit.
# --------------------------------------------------------------------------
COPY app.py ./
COPY .streamlit/ ./.streamlit/

# --------------------------------------------------------------------------
# Directorios de datos (el contenido llega vía volúmenes Docker en compose).
# Se crean vacíos para que los puntos de montaje existan en la imagen.
# --------------------------------------------------------------------------
RUN mkdir -p \
        data/plan_reabastecimiento_csv \
        data/segmentos_sku_csv \
        data/movimientos \
    && chown -R appuser:appuser /app

# --------------------------------------------------------------------------
# Cambiar al usuario sin privilegios antes de ejecutar.
# --------------------------------------------------------------------------
USER appuser

EXPOSE 8501

# --------------------------------------------------------------------------
# Health check: el endpoint /_stcore/health devuelve 200 cuando Streamlit
# está listo para servir peticiones.
# --------------------------------------------------------------------------
HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# --------------------------------------------------------------------------
# Punto de entrada: las flags de servidor sobreescriben config.toml si se
# necesita ajuste dinámico vía variables de entorno.
# --------------------------------------------------------------------------
ENTRYPOINT ["python", "-m", "streamlit", "run", "app.py", \
            "--server.port=8501", \
            "--server.address=0.0.0.0"]
