# app.py - Multi-line entry with Product Type dropdown per row
import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

st.set_page_config(layout="wide", page_title="Import Cost Calculator - Dropdown Product Type")

st.title("Import Cost Calculator — Dropdown Product Type")

# ---------- Helpers ----------
DEFAULT_WB = "Tariff_and_Costing.xlsx"

@st.cache_data
def load_tariff(path_or_file):
    try:
        df = pd.read_excel(path_or_file, sheet_name="TariffTable")
    except Exception:
        cols = ['Product Type','HS Code','Duty %','PAL %','CESS %','Excise %','SSCL %','VAT %']
        return pd.DataFrame(columns=cols)
    df.columns = [str(c).strip() for c in df.columns]
    # map common header variants
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
product_types = list(tariff_df['Product Type'].dropna().unique())
st.sidebar.subheader("Tariff preview (first rows)")
st.sidebar.dataframe(tariff_df.head(8))

# ---------- Session state: product rows ----------
def default_row():
    return {
        "Product Type":"", "HS Code":"", "Qty":1, "Unit ExWorks":0.0, "Freight":0.0, "Insurance Rate":0.003,
        "Installation":0.0, "Contingency %":0.03, "Clearing":0.0, "Handling":0.0, "Protection":0.0, "Other Local":0.0,
        "Desired Margin":0.20
    }

if "products" not in st.session_state:
    st.session_state.products = [default_row()]

# ---------- Controls ----------
st.sidebar.header("Table controls")
add_n = st.sidebar.number_input("Add N blank rows", min_value=1, max_value=100, value=1, step=1)
if st.sidebar.button("Add blank rows"):
    for _ in range(add_n):
        st.session_state.products.append(default_row())
    st.experimental_rerun()

if st.sidebar.button("Clear all rows"):
    st.session_state.products = [default_row()]
    st.experimental_rerun()

if st.sidebar.button("Duplicate last row"):
    st.session_state.products.append(st.session_state.products[-1].copy())
    st.experimental_rerun()

# ---------- Render rows as inputs (one row per horizontal block) ----------
st.header("Enter product lines (choose Product Type from dropdown)")
st.caption("Choose Product Type from dropdown to auto-fill HS & tariffs (if present in TariffTable). Edit other values as needed.")

# UI for each row
for i, row in enumerate(st.session_state.products):
    st.markdown(f"**Row {i}**")
    cols = st.columns([2,1,1,1,1,1,1])
    # Product Type dropdown
    pt = cols[0].selectbox("Product Type", options=[""] + product_types, index=(0 if row.get("Product Type","")=="" else (product_types.index(row["Product Type"])+1) if row.get("Product Type","") in product_types else 0), key=f"pt_{i}")
    # If selected, fetch HS & rates from tariff
    hs_val = row.get("HS Code","")
    if pt and pt != "":
        match = tariff_df[tariff_df["Product Type"]==pt]
        if not match.empty:
            hs_val = str(match.iloc[0]["HS Code"])
    # Other inputs
    qty = cols[1].number_input("Qty", value=float(row.get("Qty",1)), min_value=0.0, step=1.0, format="%.0f", key=f"qty_{i}")
    ux = cols[2].number_input("Unit ExWorks", value=float(row.get("Unit ExWorks",0.0)), key=f"ux_{i}", format="%.2f")
    fr = cols[3].number_input("Freight", value=float(row.get("Freight",0.0)), key=f"fr_{i}", format="%.2f")
    ins = cols[4].number_input("Insurance rate", value=float(row.get("Insurance Rate",0.003)), key=f"ins_{i}", format="%.6f")
    # small action buttons for the row (delete / move)
    action_col = cols[6]
    with action_col:
        if st.button("Delete", key=f"del_{i}"):
            st.session_state.products.pop(i)
            st.experimental_rerun()
        if st.button("Insert below", key=f"insrow_{i}"):
            st.session_state.products.insert(i+1, default_row())
            st.experimental_rerun()

    # Second line for local charges (compact)
    cols2 = st.columns([1,1,1,1,1,1])
    inst = cols2[0].number_input("Installation (LKR)", value=float(row.get("Installation",0.0)), key=f"inst_{i}", format="%.2f")
    contpct = cols2[1].number_input("Contingency %", value=float(row.get("Contingency %",0.03)), key=f"cont_{i}", format="%.4f")
    clear = cols2[2].number_input("Clearing (LKR)", value=float(row.get("Clearing",0.0)), key=f"clear_{i}", format="%.2f")
    hand = cols2[3].number_input("Handling (LKR)", value=float(row.get("Handling",0.0)), key=f"hand_{i}", format="%.2f")
    prot = cols2[4].number_input("Protection (LKR)", value=float(row.get("Protection",0.0)), key=f"prot_{i}", format="%.2f")
    mrg = cols2[5].number_input("Desired margin", value=float(row.get("Desired Margin",0.20)), key=f"mrg_{i}", format="%.4f")

    # write back into session row
    st.session_state.products[i] = {
        "Product Type": pt,
        "HS Code": hs_val,
        "Qty": int(qty),
        "Unit ExWorks": float(ux),
        "Freight": float(fr),
        "Insurance Rate": float(ins),
        "Installation": float(inst),
        "Contingency %": float(contpct),
        "Clearing": float(clear),
        "Handling": float(hand),
        "Protection": float(prot),
        "Other Local": float(row.get("Other Local",0.0)),
        "Desired Margin": float(mrg)
    }
    st.markdown("---")

# ---------- Global FX and compute ----------
st.sidebar.header("Global settings")
fx_rate = st.sidebar.number_input("FX Rate (LKR per foreign unit)", value=307.0, format="%.4f")
if st.sidebar.button("Compute landed costs for rows"):
    # convert session rows to DataFrame and compute
    df_products = pd.DataFrame(st.session_state.products)
    # reuse compute logic (similar to previous app)
    def compute_rows(df_in, tariff, fx_rate):
        df = df_in.copy()
        expected_cols = ["Product Type","HS Code","Qty","Unit ExWorks","Freight","Insurance Rate",
                         "Installation","Contingency %","Clearing","Handling","Protection","Other Local","Desired Margin"]
        for c in expected_cols:
            if c not in df.columns:
                df[c] = 0
        num_cols = ["Qty","Unit ExWorks","Freight","Insurance Rate","Installation","Contingency %","Clearing","Handling","Protection","Other Local","Desired Margin"]
        for c in num_cols:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
        merged = df.merge(tariff, how="left", left_on="Product Type", right_on="Product Type", suffixes=("","_tariff"))
        merged["HS Code"] = merged["HS Code"].fillna(merged.get("HS Code_tariff",""))
        for rate_col in ["Duty %","PAL %","CESS %","Excise %","SSCL %","VAT %"]:
            merged[rate_col] = pd.to_numeric(merged.get(rate_col,0.0), errors='coerce').fillna(0.0)
        merged["Total ExWorks_foreign"] = merged["Qty"] * merged["Unit ExWorks"]
        merged["Insurance_foreign"] = (merged["Total ExWorks_foreign"] + merged["Freight"]) * merged["Insurance Rate"]
        merged["CIF_foreign"] = merged["Total ExWorks_foreign"] + merged["Freight"] + merged["Insurance_foreign"]
        merged["Duty_foreign"] = merged["Duty %"] * merged["CIF_foreign"]
        merged["PAL_foreign"]  = merged["PAL %"] * merged["CIF_foreign"]
        merged["CESS_foreign"] = merged["CESS %"] * merged["CIF_foreign"]
        # Excise
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
            lambda r: r["VAT %"] * ((r["CIF_foreign"] * 1.15) + r["Duty_foreign"] + r["PAL_foreign"] + r["CESS_foreign"] + r["Excise_foreign"] + r["SSCL_foreign"]) if r["VAT %"]>0 else 0.0, axis=1
        )
        # Convert to LKR
        for col in ["CIF","Duty","PAL","CESS","Excise","SSCL","VAT"]:
            merged[f"{col}_LKR"] = merged[f"{col}_foreign"] * fx_rate if f"{col}_foreign" in merged.columns else 0.0
        merged["Total_Local_charges"] = merged[["Installation","Clearing","Handling","Protection","Other Local"]].sum(axis=1)
        merged["Contingency_LKR"] = merged["Contingency %"] * merged["Total ExWorks_foreign"] * fx_rate
        merged["Total_Landed_LKR"] = merged[["CIF_LKR","Duty_LKR","PAL_LKR","CESS_LKR","Excise_LKR","SSCL_LKR","VAT_LKR"]].sum(axis=1) + merged["Total_Local_charges"] + merged["Contingency_LKR"]
        merged["Cost_per_unit_LKR"] = merged["Total_Landed_LKR"] / merged["Qty"].replace(0,1)
        merged["Price_markup"] = merged["Cost_per_unit_LKR"] * (1 + merged["Desired Margin"])
        merged["Price_margin_style"] = merged["Cost_per_unit_LKR"] / (1 - merged["Desired Margin"].replace(0, np.nan))
        return merged

    results = compute_rows(df_products, tariff_df, fx_rate)
    st.session_state.results = results
    st.success(f"Computed {len(results)} rows.")

# ---------- Show results & downloads ----------
if "results" in st.session_state:
    st.header("Results")
    show_cols = ["Product Type","HS Code","Qty","Unit ExWorks","CIF_LKR","Duty_LKR","PAL_LKR","CESS_LKR","Excise_LKR","SSCL_LKR","VAT_LKR","Total_Local_charges","Contingency_LKR","Total_Landed_LKR","Cost_per_unit_LKR","Price_markup","Price_margin_style"]
    show_cols = [c for c in show_cols if c in st.session_state.results.columns]
    st.dataframe(st.session_state.results[show_cols].reset_index(drop=True), use_container_width=True)

    csv = st.session_state.results[show_cols].to_csv(index=False).encode('utf-8')
    st.download_button("Download results CSV", data=csv, file_name="costing_results.csv")

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        st.session_state.results.to_excel(writer, index=False, sheet_name="FullResults")
    st.download_button("Download full Excel", data=output.getvalue(), file_name="full_costing.xlsx")

st.caption("Tip: Add rows in the left sidebar, choose Product Type from dropdown to auto-populate tariffs, then click 'Compute landed costs for rows'.")

