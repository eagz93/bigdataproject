"""
Genera las gráficas de soporte del informe a partir de los resultados
(parquet/CSV) producidos por los notebooks. No requiere Spark: usa pandas +
pyarrow. Las figuras se guardan en `informe/img/`.

Ejecutar con:
    python generar_graficas.py
"""
from __future__ import annotations

import glob
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
PARQUET = os.path.join(ROOT, "data", "parquet")
DATA = os.path.join(ROOT, "data")
IMG = os.path.join(ROOT, "informe", "img")
os.makedirs(IMG, exist_ok=True)

VERDE = "#00704A"
AZUL = "#1f77b4"
ROJO = "#d62728"
NARANJA = "#ff7f0e"
plt.rcParams.update({"figure.dpi": 110, "font.size": 10, "axes.grid": True,
                     "grid.alpha": 0.3, "axes.axisbelow": True})


def guardar(fig, nombre: str) -> None:
    ruta = os.path.join(IMG, nombre)
    fig.tight_layout()
    fig.savefig(ruta, bbox_inches="tight")
    plt.close(fig)
    print("  +", os.path.relpath(ruta, ROOT))


def leer_csv_spark(carpeta: str) -> pd.DataFrame:
    arch = glob.glob(os.path.join(carpeta, "part-*.csv"))
    return pd.read_csv(arch[0]) if arch else pd.DataFrame()


def fig_modelos() -> None:
    ruta = os.path.join(DATA, "metricas_modelos.csv")
    df = pd.read_csv(ruta)
    abrev = {"LinearRegression": "LinearReg.", "RandomForest": "RandomForest",
             "GBT": "GBT", "BLEND (mezcla)": "BLEND"}
    modelos = [abrev.get(m, m) for m in df["modelo"]]
    rmse = df["rmse"].tolist()
    r2 = df["r2"].tolist()
    x = range(len(modelos))
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.2))
    colores = [AZUL] * (len(modelos) - 1) + [VERDE]
    a1.bar(x, rmse, color=colores)
    a1.set_xticks(list(x)); a1.set_xticklabels(modelos)
    a1.set_ylabel("RMSE (unidades)"); a1.set_title("Error de pronóstico (menor es mejor)")
    for i, v in enumerate(rmse):
        a1.text(i, v + 0.05, f"{v:.2f}", ha="center", fontsize=9)
    a2.bar(x, r2, color=colores)
    a2.set_xticks(list(x)); a2.set_xticklabels(modelos)
    lo = max(0.0, min(r2) - 0.05)
    a2.set_ylabel("R²"); a2.set_ylim(lo, 1.0); a2.set_title("Varianza explicada (mayor es mejor)")
    for i, v in enumerate(r2):
        a2.text(i, v + 0.004, f"{v:.3f}", ha="center", fontsize=9)
    guardar(fig, "fig01_comparacion_modelos.png")


def fig_importancia() -> None:
    ruta = os.path.join(DATA, "importancia_variables.csv")
    df = pd.read_csv(ruta).sort_values("importancia")
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.barh(df["feature"], df["importancia"], color=VERDE)
    ax.set_xlabel("Importancia relativa")
    ax.set_title("Importancia de variables (Random Forest)")
    guardar(fig, "fig02_importancia_variables.png")


def fig_series() -> None:
    dl = pd.read_parquet(os.path.join(PARQUET, "demanda_larga"))
    n_sem = int(dl["semana"].max())
    top = (dl.groupby("SKU")["demanda"].sum().sort_values(ascending=False)
           .head(4).index.tolist())
    fig, ax = plt.subplots(figsize=(11, 4.5))
    for sku in top:
        s = dl[dl["SKU"] == sku].sort_values("semana")
        ax.plot(s["semana"], s["demanda"], label=str(sku), linewidth=1.4)
    ax.set_xlabel(f"Semana (1–{n_sem})"); ax.set_ylabel("Demanda (unidades)")
    ax.set_title("Demanda semanal histórica — Top 4 SKUs")
    ax.legend(title="SKU", fontsize=8)
    guardar(fig, "fig03_demanda_series.png")


def fig_segmentos() -> None:
    seg = pd.read_parquet(os.path.join(PARQUET, "segmentos_sku"))
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.6))
    for nombre, grupo in seg.groupby("segmento"):
        a1.scatter(grupo["mean_d"], grupo["cv"], alpha=0.6, s=22, label=nombre)
        a2.scatter(grupo["ADI"], grupo["mean_d"], alpha=0.6, s=22, label=nombre)
    a1.set_xscale("symlog"); a1.set_xlabel("Demanda media semanal")
    a1.set_ylabel("Coef. de variación"); a1.set_title("Demanda vs. volatilidad")
    a1.legend(fontsize=7)
    a2.set_yscale("symlog"); a2.set_xlabel("ADI (intermitencia)")
    a2.set_ylabel("Demanda media"); a2.set_title("Intermitencia vs. demanda")
    a2.legend(fontsize=7)
    guardar(fig, "fig04_segmentos.png")


def fig_tipologia() -> None:
    seg = pd.read_parquet(os.path.join(PARQUET, "segmentos_sku"))
    conteo = seg["tipologia"].value_counts()
    fig, ax = plt.subplots(figsize=(7, 4.2))
    colores = {"Intermittent": AZUL, "Lumpy": ROJO, "Smooth": VERDE, "Erratic": NARANJA}
    ax.bar(conteo.index, conteo.values,
           color=[colores.get(t, "gray") for t in conteo.index])
    for i, v in enumerate(conteo.values):
        ax.text(i, v + 2, str(v), ha="center")
    ax.set_ylabel("# SKUs"); ax.set_title("Tipología de demanda (Syntetos–Boylan)")
    guardar(fig, "fig05_tipologia.png")


def fig_plan() -> None:
    plan = leer_csv_spark(os.path.join(ROOT, "data", "plan_reabastecimiento_csv"))
    if plan.empty:
        plan = pd.read_parquet(os.path.join(PARQUET, "plan_reabastecimiento"))
    pedir = plan[plan["pedir_ahora"] == 1].copy()

    por_seg = pedir.groupby("segmento")["valor_pedido_usd"].sum().sort_values()
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.barh(por_seg.index, por_seg.values, color=VERDE)
    for i, v in enumerate(por_seg.values):
        ax.text(v, i, f" ${v:,.0f}", va="center", fontsize=9)
    ax.set_xlabel("Valor del pedido (USD)")
    ax.set_title("Valor a pedir por segmento")
    guardar(fig, "fig06_plan_por_segmento.png")

    top = pedir.sort_values("valor_pedido_usd", ascending=False).head(12)
    etiquetas = (top["DESCRIPCION"].astype(str).str.slice(0, 32) + " (" + top["SKU"].astype(str) + ")")
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh(etiquetas, top["valor_pedido_usd"], color=AZUL)
    ax.invert_yaxis()
    ax.set_xlabel("Valor del pedido (USD)")
    ax.set_title("Top 12 SKUs por valor de pedido")
    guardar(fig, "fig07_plan_top_skus.png")


def fig_inventario() -> None:
    plan = leer_csv_spark(os.path.join(ROOT, "data", "plan_reabastecimiento_csv"))
    if plan.empty:
        plan = pd.read_parquet(os.path.join(PARQUET, "plan_reabastecimiento"))
    pedir = (plan[plan["pedir_ahora"] == 1]
             .sort_values("valor_pedido_usd", ascending=False).head(12))
    y = range(len(pedir))
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh([i + 0.2 for i in y], pedir["ROP"], height=0.4, color=ROJO, label="Punto de reorden (ROP)")
    ax.barh([i - 0.2 for i in y], pedir["IP"], height=0.4, color=VERDE, label="Posición de inventario (IP)")
    ax.set_yticks(list(y))
    ax.set_yticklabels(pedir["SKU"].astype(str))
    ax.invert_yaxis()
    ax.set_xlabel("Unidades")
    ax.set_title("Inventario por debajo del punto de reorden (Top 12 por valor)")
    ax.legend()
    guardar(fig, "fig08_inventario_vs_rop.png")


if __name__ == "__main__":
    print("Generando gráficas en informe/img/ ...")
    fig_modelos()
    fig_importancia()
    fig_series()
    fig_segmentos()
    fig_tipologia()
    fig_plan()
    fig_inventario()
    print("Listo.")
