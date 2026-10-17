# Analítica de abastecimiento — Starbucks Costa Rica

El proyecto prepara un pronóstico semanal, perfiles descriptivos de rotación y un plan de reabastecimiento para apoyar la revisión humana del catálogo. La recomendación considera 13 semanas de tránsito, 4 semanas de revisión, existencias, mercancía en tránsito y restricciones logísticas. No genera órdenes automáticas ni demuestra por sí sola ahorros o mejoras del nivel de servicio.

## Ejecución local

1. Instala Python 3.12 o posterior, Java 17 y las dependencias de `requirements.txt`.
2. Coloca **`Analisis CR 44.xlsx`** y **`Analisis CR 30.xlsx`** en `source_data/`.
3. Ejecuta `python train_model.py`. El pipeline valida ambos libros, genera los datos, ejecuta los cuatro notebooks y actualiza los artefactos. Falla si un paso falla y solo considera exitosa una corrida que crea `data/plan_reabastecimiento_csv/_SUCCESS`.
4. Inicia la aplicación después de configurar el acceso (siguiente sección).

```powershell
python -m pip install -r requirements.txt
python train_model.py
python -m streamlit run app.py
```

Para regenerar únicamente las figuras desde los resultados existentes, ejecuta `python generar_graficas.py`.

## Acceso y datos operativos

La aplicación requiere usuarios configurados. Para crear cuentas locales con contraseñas aleatorias y hashes PBKDF2, genera el archivo de usuarios y guarda las contraseñas fuera del repositorio:

```powershell
python setup_users.py --credentials-file "$env:USERPROFILE\local-app-credentials.txt"
```

El comando crea `admin`, `planner`, `warehouse` y `viewer` en `.streamlit/users.local.toml`. Muestra solo un mensaje de éxito: las contraseñas quedan en el archivo externo indicado. El bootstrap no reemplaza archivos existentes; conserva ese archivo de credenciales en una ubicación privada y no lo compartas ni lo subas al repositorio. La aplicación local carga el archivo de usuarios; Docker lo monta como solo lectura en `secrets.toml`.

La aplicación usa SQLite para inventario, movimientos, aprobaciones, métricas del piloto y auditoría. Permite registrar movimientos en la interfaz e importar CSV/Excel con las columnas `SKU` y `consumo` o `recibido`; la columna `semana` es opcional. La importación valida SKU, semanas y cantidades, reemplaza de forma atómica los movimientos del tipo y las semanas incluidos, y registra deltas en la auditoría. Por defecto, la base se guarda en `data/movimientos/operations.sqlite3`; configura una ubicación persistente y copias de seguridad antes de un despliegue real.

## Estructura y entregables

| Ruta | Contenido |
|---|---|
| `notebooks/` | Ingeniería de datos, pronóstico, segmentación, política de reorden y escenarios gerenciales (`01`–`05`). |
| `extract_data.py`, `train_model.py` | Extracción y orquestación secuencial del pipeline. |
| `app.py`, `operations_store.py`, `auth_utils.py` | Prototipo operativo, persistencia SQLite y autenticación. |
| `data/` | Datos preparados, métricas, figuras y plan generado; regenerable desde las fuentes. |
| `informe/informe_sistematizacion_starbucks_revisado.md` | Fuente del reporte completo revisado. |
| `REPORTE_COMPLETO_EIN_G4 (1).docx` | Documento completo disponible en este checkout; no se encontró la versión PDF. |
| `reporte-ejecutivo-starbucks.docx` | Documento ejecutivo disponible en este checkout; no se encontró la versión PDF. |
| Presentación de defensa | El PDF mencionado en versiones anteriores del README no está presente en este checkout. |

La exposición grupal tiene un máximo de 15 minutos. Después, cada integrante responde tres preguntas y dispone de hasta dos minutos por pregunta.

## Entrega final y manuales

El [índice de entrega final](informe/ENTREGA_FINAL.md) reúne los cinco cuadernos, conclusiones y manuales. Consulte también las [conclusiones de negocio y técnicas](informe/CONCLUSIONES_NEGOCIO_TECNICAS.md), el [manual de usuario](informe/MANUAL_USUARIO.md) y el [manual técnico de infraestructura y Docker](informe/MANUAL_TECNICO_DOCKER.md). Las capturas de pantalla quedan pendientes de incorporación por la persona usuaria.

## Horario y despliegue

El scheduler usa `America/Costa_Rica` y programa el pipeline los lunes a las 21:00, previo a la revisión del martes a las 08:00. `docker-compose.yml` monta `source_data/` en modo lectura y comparte las salidas mediante volúmenes persistentes. Con `PIPELINE_RUN_ON_STARTUP=auto` (predeterminado), un marcador `data/plan_reabastecimiento_csv/_SUCCESS` existente evita repetir el entrenamiento al reiniciar.

### Arranque local con Docker Desktop

```powershell
docker --context desktop-linux compose config --quiet
docker --context desktop-linux compose up -d --build
docker --context desktop-linux compose ps
curl.exe -f http://localhost:8501/_stcore/health
```

Antes del primer arranque, ejecuta una vez el comando de bootstrap de la sección **Acceso y datos operativos** y confirma que `.streamlit\users.local.toml` sea un archivo. El Compose lo requiere como montaje de solo lectura y no crea accidentalmente un directorio si falta. El puerto de la aplicación queda limitado a `127.0.0.1:8501`; los secretos del host siguen excluidos de la imagen y del contexto de construcción.

Para una comprobación **sin entrenamiento inicial**, establece `$env:PIPELINE_RUN_ON_STARTUP = "false"` antes del arranque y ejecuta `Remove-Item Env:PIPELINE_RUN_ON_STARTUP` al terminar. Esto no desactiva la ejecución programada del lunes. Si no existe un plan exitoso, Spark seguirá sin estar saludable hasta generarlo; el proceso del scheduler puede estar funcionando aunque ese control de datos falle.

No reemplaces ni borres una carpeta `.streamlit\secrets.toml` creada accidentalmente por Docker: el bootstrap la deja intacta. Si existe un archivo `secrets.toml` real con cuentas, el comando también se detiene para evitar sustituir esa configuración. El archivo local `users.local.toml` es el origen dedicado para nuevas cuentas; Compose lo enlaza directamente, con `create_host_path: false`. Vuelve a ejecutar `docker compose up -d --build` al desplegar cambios. No uses `docker compose down -v`: eliminaría los datos persistentes.

El endpoint de salud confirma el servidor HTTP, **no** la autenticación ni la disponibilidad del plan. Para probar autenticación sin usuarios reales, usa `streamlit.testing.v1.AppTest.from_file("app.py")`, inyecta `test.secrets["users"]` con un hash generado por `auth_utils.hash_password()` y un rol `viewer`, y establece `MOVEMENTS_DIR` en un directorio de pruebas del proyecto antes de ejecutar `test.run()`. Comprueba que una contraseña incorrecta no autentica, que la correcta presenta el plan y que no aparecen excepciones. Esta prueba requiere un plan local existente, no usa los secretos reales y debe conservar la base operativa fuera de su directorio aislado.

## Verificación

```powershell
python -m unittest discover -s tests -v
python -m py_compile app.py auth_utils.py operations_store.py extract_data.py train_model.py scheduler.py
```

La prueba del pipeline y sus métricas corresponden a la fecha de los artefactos en `data/`; antes de presentar cifras, vuelve a ejecutar `train_model.py` y confirma el marcador `_SUCCESS`.
