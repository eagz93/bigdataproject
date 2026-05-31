"""
Extracción, FUSIÓN y limpieza de los libros de Starbucks Costa Rica.

Se combinan DOS exportes del mismo tablero, tomados en momentos distintos:

  - 'Analisis CR 44.xlsx'  -> hoja 'Sheet1'   (encabezado en fila 1)
        Serie continua W1..S31-25  (2023 W1  ->  2025 W31)  = 135 semanas.
  - 'Analisis CR 30.xlsx'  -> hoja 'Analisis' (encabezado en fila 11)
        Serie continua W45..S19-26 (2023 W45 ->  2026 W19)  = 131 semanas,
        además del snapshot ACTUAL de inventario (EXIST W11 / Transito).

Ambas series comparten un solape (2023 W45 .. 2025 W31) en el que los valores
coinciden en ~99.6 %, lo que permite alinearlas por POSICIÓN y empalmarlas en un
único histórico semanal CONTINUO:

      semanas 1..44    ->  desde CR 44   (la parte antigua que CR 30 ya no trae)
      semanas 45..N    ->  desde CR 30   (la parte reciente, hasta la fecha)

La última semana del CR 30 (S19-26) viene vacía (aún sin cerrar) y se descarta.
El resultado es un catálogo limpio y estructurado en data/:
  - historico_semanal.csv   (serie wk1..wkN + snapshot de inventario/tránsito)
  - semanas_calendario.csv  (mapa wk_idx -> año / semana ISO / etiqueta)
  - inf.csv, bio.csv, refuerzo_campanas.csv (maestro de producto)

Ejecutar una sola vez:  python extract_data.py
"""
import os
import numpy as np
import pandas as pd

XL_OLD = "Analisis CR 44.xlsx"   # histórico antiguo (W1..W31-25)
XL_NEW = "Analisis CR 30.xlsx"   # histórico reciente + inventario actual
OUT_DIR = "data"
os.makedirs(OUT_DIR, exist_ok=True)


def save(df: pd.DataFrame, name: str) -> None:
    """Guarda un DataFrame como CSV UTF-8 y reporta su tamaño."""
    path = os.path.join(OUT_DIR, name)
    df.to_csv(path, index=False, encoding="utf-8")
    print(f"  -> {path}  ({df.shape[0]} filas x {df.shape[1]} columnas)")


def _col_index(cols, target: str) -> int:
    """Índice de la primera columna cuyo nombre (sin espacios) == target."""
    for i, c in enumerate(cols):
        if str(c).strip() == target:
            return i
    raise KeyError(f"No se encontró la columna '{target}'")


def _week_block(cols, start_label: str):
    """Devuelve la lista de columnas semanales: desde start_label hasta el
    marcador 'Prom  Real' (excluido). El bloque viene en orden cronológico."""
    s = _col_index(cols, start_label)
    end = next(
        i for i, c in enumerate(cols)
        if i >= s
        and str(c).strip().lower().startswith("prom")
        and "real" in str(c).strip().lower()
    )
    return cols[s:end]


def _weekly_wide(df: pd.DataFrame, week_cols, anchor: int) -> pd.DataFrame:
    """Convierte el bloque semanal de un libro en formato ancho con índice SKU
    y columnas canónicas wk{anchor}..wk{anchor+len-1} (numéricas, NaN->0)."""
    df = df[df["SKU"].notna()].copy()
    df["SKU"] = df["SKU"].astype(str).str.strip()
    sub = df[["SKU"] + list(week_cols)].copy()
    rename = {c: f"wk{anchor + i}" for i, c in enumerate(week_cols)}
    sub = sub.rename(columns=rename)
    wk_names = list(rename.values())
    for c in wk_names:
        sub[c] = pd.to_numeric(sub[c], errors="coerce").fillna(0.0)
    # Si un SKU aparece duplicado, conservamos la suma (mismo producto, filas partidas).
    sub = sub.groupby("SKU", as_index=True)[wk_names].sum()
    return sub


# ---------------------------------------------------------------------------
# 1) HISTÓRICO SEMANAL FUSIONADO
# ---------------------------------------------------------------------------
print("[1] Fusionando histórico semanal de ambos libros...")

# --- 1a. Libro antiguo (CR 44, hoja Sheet1) -> ancla canónica en la semana 1.
old = pd.read_excel(XL_OLD, sheet_name="Sheet1")
old_weeks = _week_block(list(old.columns), "W1")
old_wide = _weekly_wide(old, old_weeks, anchor=1)
print(f"    CR 44: {len(old_weeks)} semanas (wk1..wk{len(old_weeks)})")

# --- 1b. Libro nuevo (CR 30, hoja Analisis, encabezado en la fila 11).
new = pd.read_excel(XL_NEW, sheet_name="Analisis", header=10)
new_weeks = _week_block(list(new.columns), "45")
ANCHOR_NEW = 45  # la columna '45' equivale a la semana canónica 45.
new_wide = _weekly_wide(new, new_weeks, anchor=ANCHOR_NEW)
new_last = ANCHOR_NEW + len(new_weeks) - 1
print(f"    CR 30: {len(new_weeks)} semanas (wk{ANCHOR_NEW}..wk{new_last})")

# --- 1c. Empalme: CR44 manda en 1..44; CR30 manda en 45..N (dato más reciente).
n_total = new_last
all_skus = sorted(set(old_wide.index) | set(new_wide.index))
wide = pd.DataFrame(index=pd.Index(all_skus, name="SKU"))
for k in range(1, n_total + 1):
    col = f"wk{k}"
    if k < ANCHOR_NEW:                       # 1..44  -> CR 44
        src = old_wide[col].reindex(all_skus) if col in old_wide.columns else None
    else:                                    # 45..N  -> CR 30 (relleno con CR 44)
        src = new_wide[col].reindex(all_skus) if col in new_wide.columns else None
        if col in old_wide.columns:
            base = old_wide[col].reindex(all_skus)
            src = base if src is None else src.fillna(base)
    wide[col] = src if src is not None else 0.0
wide = wide.fillna(0.0)

# --- 1d. Descartar semanas finales vacías (la última del CR 30 aún sin cerrar).
week_cols = [f"wk{k}" for k in range(1, n_total + 1)]
while week_cols and wide[week_cols[-1]].sum() == 0:
    print(f"    (descartada {week_cols[-1]}: semana sin movimiento / sin cerrar)")
    wide = wide.drop(columns=[week_cols[-1]])
    week_cols = week_cols[:-1]
n_total = len(week_cols)
print(f"    Histórico continuo final: {n_total} semanas para {len(all_skus)} SKUs.")

# --- 1e. Snapshot ACTUAL de inventario / dimensión (desde CR 30; relleno CR 44).
def _snapshot(df_new, df_old):
    cols = {
        "DESCRIPCION": "DESCRIPCION",
        "PROVEEDOR": "PROVEEDOR",
        "Prom Ajust": "PROM_AJUST",
        "EXIST W11": "EXIST_W11",
        "Transito": "TRANSITO",
        "UND ALM": "UND_ALM",
        "UND DET": "UND_DET",
    }
    def grab(df):
        df = df[df["SKU"].notna()].copy()
        df["SKU"] = df["SKU"].astype(str).str.strip()
        present = {k: v for k, v in cols.items() if k in df.columns}
        out = df[["SKU"] + list(present.keys())].rename(columns=present)
        return out.drop_duplicates("SKU").set_index("SKU")
    snap = grab(df_new).reindex(all_skus)
    snap_old = grab(df_old).reindex(all_skus)
    # Rellenar huecos (SKUs sólo en CR 44) con el snapshot antiguo.
    snap = snap.combine_first(snap_old)
    for c in ["PROM_AJUST", "EXIST_W11", "TRANSITO", "UND_ALM", "UND_DET"]:
        if c in snap.columns:
            snap[c] = pd.to_numeric(snap[c], errors="coerce").fillna(0.0)
    return snap

snap = _snapshot(new, old)

hist = snap.join(wide, how="right").reset_index()
# Orden de columnas: dimensión + snapshot + serie semanal.
front = [c for c in ["SKU", "DESCRIPCION", "PROVEEDOR", "PROM_AJUST",
                     "EXIST_W11", "TRANSITO", "UND_ALM", "UND_DET"] if c in hist.columns]
hist = hist[front + week_cols]
save(hist, "historico_semanal.csv")


# ---------------------------------------------------------------------------
# 2) CALENDARIO DE SEMANAS  (mapa wk_idx -> año / semana ISO / etiqueta)
#    Semana 1 = 2023 W1. Se asume un calendario de 52 semanas por año.
# ---------------------------------------------------------------------------
print("[2] Generando calendario de semanas...")
cal_rows = []
for k in range(1, n_total + 1):
    anio = 2023 + (k - 1) // 52
    sem = (k - 1) % 52 + 1
    cal_rows.append({"wk_idx": k, "anio": anio, "semana": sem,
                     "etiqueta": f"{anio}-W{sem:02d}"})
cal = pd.DataFrame(cal_rows)
save(cal, "semanas_calendario.csv")


# ---------------------------------------------------------------------------
# 3) INFORMACIÓN DE PRODUCTO (hoja 'Inf' del libro NUEVO, CR 30)
# ---------------------------------------------------------------------------
print("[3] Procesando información de producto (Inf)...")
inf = pd.read_excel(XL_NEW, sheet_name="Inf")
inf = inf.rename(
    columns={
        "$": "COSTO_UNITARIO",
        "CS/Pal": "CS_POR_PALLET",
        "Total Shelf Life": "VIDA_UTIL",
        "WCS": "WCS",
        "GW": "PESO_BRUTO",
        "Cub": "CUBICAJE",
        "Fac": "FACTOR",
    }
)
inf_cols = [
    "SKU", "DESCRIPCION", "FACTOR", "PESO_BRUTO", "WCS", "CUBICAJE",
    "CS_POR_PALLET", "COSTO_UNITARIO", "Stack", "UND ALM", "UND DET", "VIDA_UTIL",
]
inf = inf[[c for c in inf_cols if c in inf.columns]].copy()
inf = inf.rename(columns={"UND ALM": "UND_ALM", "UND DET": "UND_DET", "Stack": "STACK"})
inf = inf[inf["SKU"].notna()].copy()
inf["SKU"] = inf["SKU"].astype(str).str.strip()
inf = inf.drop_duplicates("SKU")
save(inf, "inf.csv")


# ---------------------------------------------------------------------------
# 4) CLASIFICACIÓN DE SOSTENIBILIDAD (hoja 'BIO', encabezado desplazado).
# ---------------------------------------------------------------------------
print("[4] Procesando clasificación de sostenibilidad (BIO)...")
bio = pd.read_excel(XL_OLD, sheet_name="BIO", header=4)
bio = bio.loc[:, ~bio.columns.astype(str).str.startswith("Unnamed")]
bio = bio.rename(
    columns={
        "Sustanaible": "SOSTENIBLE",
        "STATUS": "STATUS",
        "UOM": "UOM",
        "CLASI": "CLASI",
        "ITEM": "SKU",
        "DESCRIPCION": "DESCRIPCION",
        "UND ALM": "UND_ALM",
        "UND DET": "UND_DET",
    }
)
bio = bio[bio["SKU"].notna()].copy()
bio["SKU"] = bio["SKU"].astype(str).str.strip()
keep_bio = [c for c in ["SKU", "DESCRIPCION", "CLASI", "STATUS", "SOSTENIBLE", "UOM", "UND_ALM", "UND_DET"] if c in bio.columns]
save(bio[keep_bio].drop_duplicates("SKU"), "bio.csv")


# ---------------------------------------------------------------------------
# 5) REFUERZO DE CAMPAÑAS (bandera estacional 'es_campana').
# ---------------------------------------------------------------------------
print("[5] Procesando refuerzo de campañas...")
camp = pd.read_excel(XL_OLD, sheet_name="Refuerzo campañas")
camp = camp.rename(
    columns={
        "DESCRIPCIÓN": "DESCRIPCION",
        "TEMPORADA": "TEMPORADA",
        "Launch date": "LAUNCH_DATE",
        "End Date": "END_DATE",
        "CASE COUNT": "CASE_COUNT",
        "EA": "EA",
        "CS": "CS",
    }
)
camp_cols = [c for c in ["SKU", "DESCRIPCION", "TEMPORADA", "LAUNCH_DATE", "END_DATE", "EA", "CASE_COUNT", "CS"] if c in camp.columns]
camp = camp[camp_cols].copy()
camp = camp[camp["SKU"].notna()].copy()
camp["SKU"] = camp["SKU"].astype(str).str.strip()
save(camp.drop_duplicates("SKU"), "refuerzo_campanas.csv")

print(f"\nExtracción completada: histórico continuo de {n_total} semanas "
      f"({len(all_skus)} SKUs). Archivos limpios en 'data/'.")
