#!/bin/sh
set -e

if [ ! -d "${JAVA_HOME:-}" ]; then
    _java_real=$(readlink -f "$(command -v java)" 2>/dev/null || echo "")
    if [ -n "$_java_real" ]; then
        export JAVA_HOME=$(dirname "$(dirname "$_java_real")")
        echo "[entrypoint] JAVA_HOME auto-detectado: $JAVA_HOME"
    else
        echo "[entrypoint] ERROR: 'java' no encontrado en PATH" >&2
        exit 1
    fi
fi

export PATH="${JAVA_HOME}/bin:${PATH}"
export PYSPARK_PYTHON=python3
export PYSPARK_DRIVER_PYTHON=python3

echo "[entrypoint] JAVA_HOME  : ${JAVA_HOME}"
echo "[entrypoint] $(java -version 2>&1 | head -1)"
echo "[entrypoint] Python     : $(python3 --version)"
echo "[entrypoint] PySpark    : $(python3 -c 'import pyspark; print(pyspark.__version__)')"
echo "[entrypoint] Iniciando  : $*"
echo "---"

exec "$@"
