import pandas as pd
import os

files = [
    "e:/Sajeewa/BOQ - A017..xlsx",
    "e:/Sajeewa/master plan.xlsx",
    "e:/Sajeewa/Rate Breakdown.xlsx"
]

for file_path in files:
    print(f"\n{'='*20}\nAnalyzing: {os.path.basename(file_path)}\n{'='*20}")
    try:
        if not os.path.exists(file_path):
            print(f"File not found: {file_path}")
            continue
        
        xl = pd.ExcelFile(file_path)
        print(f"Sheet Names: {xl.sheet_names}")
        
        for sheet in xl.sheet_names[:2]: # Check first 2 sheets
            print(f"\n  --- Sheet: {sheet} ---")
            df = xl.parse(sheet, nrows=5)
            print(f"  Columns: {list(df.columns)}")
            print(f"  Preview:\n{df.head(3).to_string()}")
            
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
