"""Quick inspection of the Excel workbook structure to plan CSV extraction."""
import pandas as pd

XL = "Analisis CR 44.xlsx"
SHEETS = ["Sheet1", "Historico", "Inf", "BIO", "Refuerzo campañas", "Base revision"]

for sheet in SHEETS:
    print("=" * 80)
    print(f"SHEET: {sheet!r}")
    print("=" * 80)
    try:
        df = pd.read_excel(XL, sheet_name=sheet, nrows=6)
        print(f"shape (first 6 rows read): {df.shape}")
        print(f"columns ({len(df.columns)}):")
        print(list(df.columns))
        print("--- head ---")
        with pd.option_context("display.max_columns", None, "display.width", 200):
            print(df.head(5))
    except Exception as e:
        print(f"ERROR reading sheet: {e}")
    print()
