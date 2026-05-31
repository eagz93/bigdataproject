# Optimización de la cadena de suministro · Starbucks Costa Rica

Proyecto de Big Data (PySpark) que pronostica la demanda, segmenta el catálogo y
genera un **plan de compras** (cuánto y cuándo pedir) sobre 174 semanas de datos
reales (fusión de `Analisis CR 44.xlsx` + `Analisis CR 30.xlsx`, 2023-W1 →
2026-W18). Incluye una **interfaz interactiva** con módulos para registrar el
consumo semanal y confirmar recepciones, y un **informe** con gráficas.

## Requisitos
- Python 3.13, JDK 17
- `pip install -r requirements.txt`

## Cómo ejecutar
```powershell
python -m pip install -r requirements.txt
python extract_data.py                 # extrae los datos del Excel a Parquet
# Ejecutar en orden (reiniciar kernel entre notebooks):
#   notebooks/01_ingenieria_datos.ipynb
#   notebooks/02_pronostico_demanda.ipynb
#   notebooks/03_segmentacion.ipynb
#   notebooks/04_reorder_policy.ipynb
python generar_graficas.py             # genera las figuras del informe (informe/img)
python -m streamlit run app.py         # abre la interfaz del plan de compras
```

## Estructura
- `notebooks/` — pipeline (ingeniería de datos, pronóstico, segmentación, reorden).
- `app.py` — dashboard Streamlit en 3 pestañas: plan de compras (KPIs, filtros,
  descarga CSV), **consumo semanal** (recalcula el pedido) y **confirmar
  recepción** (mueve tránsito a existencias).
- `generar_graficas.py` — genera las 8 figuras de soporte del informe.
- `INFORME.md` — informe completo alineado a la rúbrica.
- `data/` — Parquet y CSV de salida (incl. `plan_reabastecimiento_csv` y
  `movimientos/` con el consumo y las recepciones registradas).

## Salidas clave
- **Pronóstico:** ensamble con $R^2 \approx 0.905$ (mezcla) y $0.92$ (mejor
  modelo) a 13 semanas, con **variables externas** (clima, promociones, precio)
  e hiperparámetros ajustados por **validación cruzada temporal**.
- **Segmentación:** KMeans $k=5$ + tipología Syntetos–Boylan.
- **Plan de compras:** 260 de 436 SKUs a pedir ahora (~$130 074), con nivel de
  servicio diferenciado por segmento y redondeo a cajas completas.
