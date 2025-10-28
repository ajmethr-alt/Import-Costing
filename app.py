# app.py
import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

st.set_page_config(layout="wide", page_title="Import Cost Calculator - Live multi-line")

st.title("Import Cost Calculator — Live multi-line entry")

# ---------- Helpers ----------
DEFAULT_WB = "Tariff_and_Costing.xlsx"

@st.cache_data
def load_tariff(path_or_file):
    try:
        df = pd.read_excel(path_or_file, sheet_name="TariffTable")
    except Exception:
        # return empty shaped df if not found
        cols = ['Product Type','HS Code','Duty %','PAL %','CESS %','Excise %','SSCL %','VAT %']
        return pd.DataFrame(columns=cols)
    df.columns = [str(c).strip() for c in df.columns]
    # attempt simple mapping if headers differ
    mapping = {}
    for c in df.columns:
        lc = c.lower()
        if 'product' in lc and 'type' in lc: mapping[c] = 'Product Type'
        elif 'hs' in lc: mapping[c] = 'HS Code'
        elif 'duty' in lc: mapping[c] = 'Duty %'
        elif 'pal' in lc or 'port' in lc: mapping[c] = 'PAL %'
        elif 'cess' in lc: mapping[c] = 'CESS %'
        elif 'excise' in lc: mapping[c] = 'Excise %'
        elif 'sscl' in lc or 'social' in lc: mapping[c] = 'SSCL %'
        elif 'vat' in lc: mapping[c] = 'VAT %'
    df = df.rename(columns=mapping)
    expected = ['Product Type','HS Code','Duty %','PAL %','CESS %','Excise %','SSCL %','VAT %']
    for col in expected:
        if col not in df.columns:
            df[col] = 0.0
    return df[expected]

# ---------- Load tariff table ----------
uploaded_wb = st.sidebar.file_uploader("Upload workbook (optional) - TariffTable sheet will be used", type=["xlsx","xls"])
wb_source = uploaded_wb if uploaded_wb is not None else DEFAULT_WB
tariff_df = load_tariff(wb_source)
st.sidebar.subheader("Tariff preview (first 10 rows)")
st.sidebar.dataframe(tariff_df.head(10))

# ---------- Session state for product lines ----------
if "products" not in st.session_state:
    # default single blank row
    st.session_state.products = pd.DataFrame([{
        "Product Type":"", "HS Code":"", "Qty":1, "Unit ExWorks":0.0, "Freight":0.0, "Insurance Rate":0.003,
        "Installation":0.0, "Contingency %":0.03, "Clearing":0.0, "Handling":0.0, "Protection":0.0, "Other Local":0.0,
        "Desired Margin":0.20
    }])

def reset_products():
    st.session_state.products = pd.DataFrame([{
        "Product Type":"", "HS Code":"", "Qty":1, "Unit ExWorks":0.0, "Freight":0.0, "Insurance Rate":0.003,
        "Installation":0.0, "Contingency %":0.03, "Clearing":0.0, "Handling":0.0, "Protection":0.0, "Other Local":0.0,
        "Desired Margin":0.20
    }])

# ---------- Controls for adding/removing rows ----------
st.sidebar.header("Table controls")
add_n = st.sidebar.number_input("Add N blank rows", min_value=1, max_value=100, value=1, step=1)
if st.sidebar.button("Add blank rows"):
    df = st.session_state.products.copy()
    for _ in range(add_n):
        df = pd.concat([df, pd.DataFrame([{
            "Product Type":"", "HS Code":"", "Qty":1, "Unit ExWorks":0.0, "Freight":0.0, "Insurance Rate":0.003,
            "Installation":0.0, "Contingency %":0.03, "Clearing":0.0, "Handling":0.0, "Protection":0.0, "Other Local":0.0,
            "Desired Margin":0.20
        }])], ignore_index=True)
    st.session_state.products = df
    st.experimental_rerun()

if st.sidebar.button("Clear all rows"):
    reset_products()
    st.experimental_rerun()

if st.sidebar.button("Duplicate selected row"):
    # this duplicator expects the user to edit row index manually below before clicking
    idx = st.sidebar.number_input("Row index to duplicate (0-based)", min_value=0, value=0, step=1)
    df = st.session_state.products.copy()
    if 0 <= idx < len(df):
        row = df.iloc[[idx]].copy()
        df = pd.concat([df, row], ignore_index=True)
        st.session_state.products = df
        st.experimental_rerun()

# ---------- Editable grid ----------
st.header("Enter product lines (edit directly below)")
st.caption("Edit cells directly. Add blank rows from the left sidebar. Product Type should match TariffTable for automatic tariff lookup.")

edited_df = st.data_editor(st.session_state.products, num_rows="dynamic", use_container_width=True)

# Save edited back to session
st.session_state.products = edited_df.copy()

# ---------- Global FX and defaults ----------
st.sidebar.header("Global settings")
fx_rate = st.sidebar.number_input("FX Rate (LKR per foreign unit)", value=307.0, format="%.4f")
incoterm_default = st.sidebar.selectbox("Default Incoterm", ["CIF","EXW"])

# ---------- Compute function ----------
def compute_rows(df_in, tariff, fx_rate):
    df = df_in.copy()
    # ensure necessary columns
    expected_cols = ["Product Type","HS Code","Qty","Unit ExWorks","Freight","Insurance Rate",
                     "Installation","Contingency %","Clearing","Handling","Protection","Other Local","Desired Margin"]
    for c in expected_cols:
        if c not in df.columns:
            df[c] = 0
    # numeric conversions
    num_cols = ["Qty","Unit ExWorks","Freight","Insurance Rate","Installation","Contingency %","Clearing","Handling","Protection","Other Local","Desired Margin"]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    # merge tariff by product type
    merged = df.merge(tariff, how="left", left_on="Product Type", right_on="Product Type", suffixes=("","_tariff"))
    merged["HS Code"] = merged["HS Code"].fillna(merged.get("HS Code_tariff",""))
    for rate_col in ["Duty %","PAL %","CESS %","Excise %","SSCL %","VAT %"]:
        merged[rate_col] = pd.to_numeric(merged.get(rate_col,0.0), errors="coerce").fillna(0.0)
    # core foreign currency fields
    merged["Total ExWorks_foreign"] = merged["Qty"] * merged["Unit ExWorks"]
    merged["Insurance_foreign"] = (merged["Total ExWorks_foreign"] + merged["Freight"]) * merged["Insurance Rate"]
    merged["CIF_foreign"] = merged["Total ExWorks_foreign"] + merged["Freight"] + merged["Insurance_foreign"]
    # duties
    merged["Duty_foreign"] = merged["Duty %"] * merged["CIF_foreign"]
    merged["PAL_foreign"]  = merged["PAL %"] * merged["CIF_foreign"]
    merged["CESS_foreign"] = merged["CESS %"] * merged["CIF_foreign"]
    # excise, sscl, vat following your formulas
    merged["Excise_foreign"] = 0.0
    mask_exc = merged["Excise %"] > 0
    merged.loc[mask_exc, "Excise_foreign"] = merged.loc[mask_exc].apply(
        lambda r: r["Excise %"] * ((r["CIF_foreign"] * 1.15) + r["Duty_foreign"] + r["PAL_foreign"] + r["CESS_foreign"]), axis=1
    )
    merged["SSCL_foreign"] = 0.0
    mask_sscl = merged["SSCL %"] > 0
    merged.loc[mask_sscl, "SSCL_foreign"] = merged.loc[mask_sscl].apply(
        lambda r: r["SSCL %"] * ((r["CIF_foreign"] * 1.10) + r["Duty_foreign"] + r["PAL_foreign"] + r["CESS_foreign"] + r["Excise_foreign"]), axis=1
    )
    merged["VAT_foreign"] = merged.apply(
        lambda r: r["VAT %"] * ((r["CIF_foreign"] * 1.15) + r["Duty_foreign"] + r["PAL_foreign"] + r["CESS_foreign"] + r["Excise_foreign"] + r["SSCL_foreign"]) if r["VAT %"]>0 else 0.0, axis=1
    )
    # convert to LKR
    for col in ["CIF","Duty","PAL","CESS","Excise","SSCL","VAT"]:
        merged[f"{col}_LKR"] = merged[f"{col}_foreign"] * fx_rate if f"{col}_foreign" in merged.columns else 0.0
    # local charges & contingency
    merged["Total_Local_charges"] = merged[["Installation","Clearing","Handling","Protection","Other Local"]].sum(axis=1)
    merged["Contingency_LKR"] = merged["Contingency %"] * merged["Total ExWorks_foreign"] * fx_rate
    # total landed
    merged["Total_Landed_LKR"] = merged[["CIF_LKR","Duty_LKR","PAL_LKR","CESS_LKR","Excise_LKR","SSCL_LKR","VAT_LKR"]].sum(axis=1) + merged["Total_Local_charges"] + merged["Contingency_LKR"]
    merged["Cost_per_unit_LKR"] = merged["Total_Landed_LKR"] / merged["Qty"].replace(0,1)
    merged["Price_markup"] = merged["Cost_per_unit_LKR"] * (1 + merged["Desired Margin"])
    merged["Price_margin_style"] = merged["Cost_per_unit_LKR"] / (1 - merged["Desired Margin"].replace(0, np.nan))
    return merged

# ---------- Compute & show ----------
if st.button("Compute landed costs for rows"):
    merged = compute_rows(st.session_state.products, tariff_df, fx_rate)
    # store results to session so user can download or continue editing
    st.session_state.results = merged
    st.success(f"Computed {len(merged)} rows.")

if "results" in st.session_state:
    st.header("Results")
    # present a compact results table
    show_cols = ["Product Type","HS Code","Qty","Unit ExWorks","CIF_LKR","Duty_LKR","PAL_LKR","CESS_LKR","Excise_LKR","SSCL_LKR","VAT_LKR","Total_Local_charges","Contingency_LKR","Total_Landed_LKR","Cost_per_unit_LKR","Price_markup","Price_margin_style"]
    show_cols = [c for c in show_cols if c in st.session_state.results.columns]
    st.dataframe(st.session_state.results[show_cols].reset_index(drop=True), use_container_width=True)

    # downloads
    csv = st.session_state.results[show_cols].to_csv(index=False).encode('utf-8')
    st.download_button("Download results CSV", data=csv, file_name="costing_results.csv")

    # full excel
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        st.session_state.results.to_excel(writer, index=False, sheet_name="FullResults")
    st.download_button("Download full Excel", data=output.getvalue(), file_name="full_costing.xlsx")

st.write("") 
st.caption("Tip: Add rows in the left sidebar, fill Product Type exactly as in TariffTable to auto-populate tariffs, then click 'Compute landed costs for rows'.")

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        merged_df.to_excel(writer, index=False, sheet_name="Results")
    st.download_button("Download Excel file", data=output.getvalue(), file_name="full_costing.xlsx")

