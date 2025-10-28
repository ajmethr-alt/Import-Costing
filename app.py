# app.py - multi-line costing version
import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

st.set_page_config(layout="wide", page_title="Import Cost Calculator - Multi-line")

st.title("Import Cost Calculator — Multi-line / Batch")

# ---------------- Tariff loading ----------------
DEFAULT_WB = "Tariff_and_Costing.xlsx"
uploaded_wb = st.sidebar.file_uploader("Upload workbook (optional)", type=["xlsx","xls"])
wb_source = uploaded_wb if uploaded_wb is not None else DEFAULT_WB

@st.cache_data
def load_tariff(wb_path):
    try:
        df = pd.read_excel(wb_path, sheet_name="TariffTable")
    except Exception as e:
        st.error(f"Failed reading TariffTable: {e}")
        return pd.DataFrame(columns=['Product Type','HS Code','Duty %','PAL %','CESS %','Excise %','SSCL %','VAT %'])
    # Normalize names:
    df.columns = [str(c).strip() for c in df.columns]
    # Try mapping common header variants
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

tariff_df = load_tariff(wb_source)
st.sidebar.subheader("Tariff preview")
st.sidebar.dataframe(tariff_df.head(8))

# ---------------- Input: either upload batch OR edit table ----------------
st.header("1. Provide product lines (batch upload OR edit here)")

colA, colB = st.columns(2)
with colA:
    uploaded = st.file_uploader("Upload product rows (Excel/CSV) - one product per row", type=["xlsx","xls","csv"])
    st.write("OR use the editable grid on the right to add lines manually.")

# Default blank template for manual entry
template = pd.DataFrame([{
    "Product Type":"", "HS Code":"", "Qty":1, "Unit ExWorks":0.0, "Freight":0.0, "Insurance Rate":0.003,
    "Installation":0.0, "Contingency %":0.03, "Clearing":0.0, "Handling":0.0, "Protection":0.0, "Other Local":0.0,
    "Desired Margin":0.20
}])

# Load uploaded or use template
if uploaded is not None:
    try:
        if uploaded.name.lower().endswith('.csv'):
            df_products = pd.read_csv(uploaded)
        else:
            # try first sheet or named sheet
            df_products = pd.read_excel(uploaded, sheet_name=0)
    except Exception as e:
        st.error("Failed to read uploaded product file: " + str(e))
        df_products = template.copy()
else:
    df_products = template.copy()

# Ensure columns present
for col in template.columns:
    if col not in df_products.columns:
        df_products[col] = template[col]

# Editable table (streamlit's experimental_data_editor or data_editor)
st.subheader("Editable product lines")
edited = st.data_editor(df_products, num_rows="dynamic", use_container_width=True)

# ---------------- Global / FX settings ----------------
st.sidebar.header("Global settings")
fx_rate = st.sidebar.number_input("FX Rate (LKR per unit)", value=307.0, format="%.4f")
incoterm = st.sidebar.selectbox("Default Incoterm", ["CIF","EXW"])

# ---------------- Compute per-row ----------------
def compute_rows(df_in, tariff, fx_rate):
    df = df_in.copy()
    # normalize column names
    df = df.rename(columns=lambda x: str(x).strip())
    # Ensure numeric types
    numeric_cols = ["Qty","Unit ExWorks","Freight","Insurance Rate","Installation","Contingency %","Clearing","Handling","Protection","Other Local","Desired Margin"]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
        else:
            df[c] = 0.0

    # Merge tariff rates by Product Type (prefer exact match)
    merged = df.merge(tariff, how="left", left_on="Product Type", right_on="Product Type", suffixes=("","_tariff"))
    # If HS Code blank in input, use tariff HS Code
    merged["HS Code"] = merged["HS Code"].fillna(merged["HS Code_tariff"])
    # Fill NA rates with 0
    for rate_col in ["Duty %","PAL %","CESS %","Excise %","SSCL %","VAT %"]:
        merged[rate_col] = pd.to_numeric(merged[rate_col], errors='coerce').fillna(0.0)

    # Basic currencies (foreign)
    merged["Total ExWorks_foreign"] = merged["Qty"] * merged["Unit ExWorks"]
    merged["Insurance_foreign"] = (merged["Total ExWorks_foreign"] + merged["Freight"]) * merged["Insurance Rate"]
    merged["CIF_foreign"] = merged["Total ExWorks_foreign"] + merged["Freight"] + merged["Insurance_foreign"]

    # Duties (foreign)
    merged["Duty_foreign"] = merged["Duty %"] * merged["CIF_foreign"]
    merged["PAL_foreign"]  = merged["PAL %"] * merged["CIF_foreign"]
    merged["CESS_foreign"] = merged["CESS %"] * merged["CIF_foreign"]

    # Excise (your formula)
    merged["Excise_foreign"] = 0.0
    mask_exc = merged["Excise %"] > 0
    merged.loc[mask_exc, "Excise_foreign"] = merged.loc[mask_exc].apply(
        lambda r: r["Excise %"] * ((r["CIF_foreign"] * 1.15) + r["Duty_foreign"] + r["PAL_foreign"] + r["CESS_foreign"]), axis=1
    )

    # SSCL
    merged["SSCL_foreign"] = 0.0
    mask_sscl = merged["SSCL %"] > 0
    merged.loc[mask_sscl, "SSCL_foreign"] = merged.loc[mask_sscl].apply(
        lambda r: r["SSCL %"] * ((r["CIF_foreign"] * 1.10) + r["Duty_foreign"] + r["PAL_foreign"] + r["CESS_foreign"] + r["Excise_foreign"]), axis=1
    )

    # VAT
    merged["VAT_foreign"] = merged.apply(
        lambda r: r["VAT %"] * ((r["CIF_foreign"] * 1.15) + r["Duty_foreign"] + r["PAL_foreign"] + r["CESS_foreign"] + r["Excise_foreign"] + r["SSCL_foreign"])
        if r["VAT %"]>0 else 0.0, axis=1
    )

    # Convert necessary items to LKR
    for c in ["CIF_foreign","Duty_foreign","PAL_foreign","CESS_foreign","Excise_foreign","SSCL_foreign","VAT_foreign"]:
        merged[c.replace("_foreign","_LKR")] = merged[c] * fx_rate

    # Local charges already in LKR
    merged["Total_Local_charges"] = merged[["Installation","Clearing","Handling","Protection","Other Local"]].sum(axis=1)

    # Contingency: percent of exworks (foreign) converted to LKR
    merged["Contingency_LKR"] = merged["Contingency %"] * merged["Total ExWorks_foreign"] * fx_rate

    # Total landed
    merged["Total_Landed_LKR"] = merged[["CIF_LKR","Duty_LKR","PAL_LKR","CESS_LKR","Excise_LKR","SSCL_LKR","VAT_LKR"]].sum(axis=1) \
                                + merged["Total_Local_charges"] + merged["Contingency_LKR"]

    merged["Cost_per_unit_LKR"] = merged["Total_Landed_LKR"] / merged["Qty"].replace(0,1)
    # Prices
    merged["Price_markup"] = merged["Cost_per_unit_LKR"] * (1 + merged["Desired Margin"])
    merged["Price_margin_style"] = merged["Cost_per_unit_LKR"] / (1 - merged["Desired Margin"].replace(0, np.nan))

    # tidy columns to show
    out_cols = ["Product Type","HS Code","Qty","Unit ExWorks","Freight","CIF_foreign",
                "Duty %","PAL %","CESS %","Excise %","SSCL %","VAT %",
                "CIF_LKR","Duty_LKR","PAL_LKR","CESS_LKR","Excise_LKR","SSCL_LKR","VAT_LKR",
                "Total_Local_charges","Contingency_LKR","Total_Landed_LKR","Cost_per_unit_LKR","Price_markup","Price_margin_style"]
    # keep any that exist
    cols_present = [c for c in out_cols if c in merged.columns]
    return merged, merged[cols_present]

merged_df, result_df = compute_rows(edited, tariff_df, fx_rate)

st.header("Results")
st.dataframe(result_df, use_container_width=True)

# Download CSV
def to_csv_bytes(df):
    return df.to_csv(index=False).encode('utf-8')

st.download_button("Download results CSV", data=to_csv_bytes(result_df), file_name="costing_results.csv")

# Optionally export full excel
if st.button("Download full Excel (with all intermediate cols)"):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        merged_df.to_excel(writer, index=False, sheet_name="Results")
    st.download_button("Download Excel file", data=output.getvalue(), file_name="full_costing.xlsx")

