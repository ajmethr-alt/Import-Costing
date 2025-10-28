# app.py - Multi-line entry with Product Type dropdown and freight allocation
import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

st.set_page_config(layout="wide", page_title="Import Cost Calculator - Freight Alloc")

st.title("Import Cost Calculator — Freight allocation per consignment")

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

# ---------- Session state: product rows and freight ----------
def default_row():
    return {
        "Product Type":"", "HS Code":"", "Qty":1, "Unit ExWorks":0.0,
        "Manual Freight":0.0, "Freight Override":False,
        "Insurance Rate":0.003, "Installation":0.0, "Contingency %":0.03,
        "Clearing":0.0, "Handling":0.0, "Protection":0.0, "Other Local":0.0,
        "Desired Margin":0.20, "FreightAlloc":0.0
    }

if "products" not in st.session_state:
    st.session_state.products = [default_row()]

if "allocated" not in st.session_state:
    st.session_state.allocated = False

# ---------- Controls ----------
st.sidebar.header("Table controls")
add_n = st.sidebar.number_input("Add N blank rows", min_value=1, max_value=100, value=1, step=1)
if st.sidebar.button("Add blank rows"):
    for _ in range(add_n):
        st.session_state.products.append(default_row())
    st.experimental_rerun()

if st.sidebar.button("Clear all rows"):
    st.session_state.products = [default_row()]
    st.session_state.allocated = False
    st.experimental_rerun()

if st.sidebar.button("Duplicate last row"):
    st.session_state.products.append(st.session_state.products[-1].copy())
    st.experimental_rerun()

# ---------- Global shipment / freight settings ----------
st.sidebar.header("Shipment & freight (global)")
num_containers = st.sidebar.number_input("Number of containers", min_value=0, value=1, step=1)
freight_per_container = st.sidebar.number_input("Freight per container (foreign currency)", min_value=0.0, value=2500.0, step=1.0, format="%.2f")
total_freight_override = st.sidebar.number_input("Total freight (override, foreign) - leave 0 to use containers calc", min_value=0.0, value=0.0, format="%.2f")
insurance_rate_global = st.sidebar.number_input("Default insurance rate (decimal)", value=0.003, format="%.6f")
fx_rate = st.sidebar.number_input("FX Rate (LKR per foreign unit)", value=307.0, format="%.4f")
st.sidebar.caption("Use 'Allocate freight' to distribute total freight across rows based on exworks value. You can manually override per-row freight if needed.")

# Button to allocate freight
if st.sidebar.button("Allocate freight"):
    total_freight = total_freight_override if total_freight_override>0 else (num_containers * freight_per_container)
    exvals = [float(r.get("Qty",0)) * float(r.get("Unit ExWorks",0.0)) for r in st.session_state.products]
    exvals = np.array(exvals, dtype=float)
    manual_flags = np.array([bool(r.get("Freight Override", False)) for r in st.session_state.products])
    manual_values = np.array([float(r.get("Manual Freight",0.0)) for r in st.session_state.products])
    manual_sum = manual_values[manual_flags].sum() if manual_flags.any() else 0.0
    remaining = total_freight - manual_sum
    if remaining < -1e-6:
        st.sidebar.error("Manual freight overrides exceed total freight. Reduce manual freight or increase total freight.")
    else:
        non_mask = ~manual_flags
        if non_mask.sum() == 0:
            for idx, r in enumerate(st.session_state.products):
                r["FreightAlloc"] = float(r.get("Manual Freight",0.0))
        else:
            sum_ex_non = exvals[non_mask].sum()
            if sum_ex_non <= 0:
                per = remaining / non_mask.sum() if non_mask.sum()>0 else 0.0
                for idx, r in enumerate(st.session_state.products):
                    if manual_flags[idx]:
                        r["FreightAlloc"] = float(r.get("Manual Freight",0.0))
                    else:
                        r["FreightAlloc"] = float(per)
            else:
                ratios = exvals[non_mask] / sum_ex_non
                j = 0
                for idx, r in enumerate(st.session_state.products):
                    if manual_flags[idx]:
                        r["FreightAlloc"] = float(r.get("Manual Freight",0.0))
                    else:
                        r["FreightAlloc"] = float(ratios[j] * remaining)
                        j += 1
        st.session_state.allocated = True
        st.sidebar.success("Freight allocated. Review the FreightAlloc column in each row.")

# ---------- Editable rows ----------
st.header("Enter product lines")
st.caption("Select Product Type, enter Qty and ExWorks, then allocate freight in the sidebar.")

for i, row in enumerate(st.session_state.products):
    st.markdown(f"**Row {i+1}**")
    cols = st.columns([2,1,1,1,1,1,0.6])
    pt = cols[0].selectbox("Product Type", options=[""] + product_types,
        index=(0 if row.get("Product Type","")=="" else (product_types.index(row["Product Type"])+1) if row.get("Product Type","") in product_types else 0), key=f"pt_{i}")
    hs_val = row.get("HS Code","")
    if pt and pt!="":
        match = tariff_df[tariff_df["Product Type"]==pt]
        if not match.empty:
            hs_val = str(match.iloc[0]["HS Code"])
    qty = cols[1].number_input("Qty", value=float(row.get("Qty",1)), min_value=0.0, step=1.0, format="%.0f", key=f"qty_{i}")
    ux = cols[2].number_input("Unit ExWorks", value=float(row.get("Unit ExWorks",0.0)), key=f"ux_{i}", format="%.2f")
    fr_alloc = row.get("FreightAlloc",0.0)
    cols[3].metric("FreightAlloc (foreign)", f"{fr_alloc:,.2f}")
    manual_flag = cols[4].checkbox("Override freight", value=bool(row.get("Freight Override",False)), key=f"ovr_{i}")
    manual_val = cols[5].number_input("Manual Freight", value=float(row.get("Manual Freight",0.0)), key=f"mf_{i}", format="%.2f")

    cols2 = st.columns([1,1,1,1,1,1])
    inst = cols2[0].number_input("Installation (LKR)", value=float(row.get("Installation",0.0)), key=f"inst_{i}", format="%.2f")
    contpct = cols2[1].number_input("Contingency %", value=float(row.get("Contingency %",0.03)), key=f"cont_{i}", format="%.4f")
    clear = cols2[2].number_input("Clearing (LKR)", value=float(row.get("Clearing",0.0)), key=f"clear_{i}", format="%.2f")
    hand = cols2[3].number_input("Handling (LKR)", value=float(row.get("Handling",0.0)), key=f"hand_{i}", format="%.2f")
    prot = cols2[4].number_input("Protection (LKR)", value=float(row.get("Protection",0.0)), key=f"prot_{i}", format="%.2f")
    mrg = cols2[5].number_input("Desired margin", value=float(row.get("Desired Margin",0.20)), key=f"mrg_{i}", format="%.4f")

    st.session_state.products[i] = {
        "Product Type": pt,
        "HS Code": hs_val,
        "Qty": int(qty),
        "Unit ExWorks": float(ux),
        "Manual Freight": float(manual_val),
        "Freight Override": bool(manual_flag),
        "Insurance Rate": float(row.get("Insurance Rate", insurance_rate_global)),
        "Installation": float(inst),
        "Contingency %": float(contpct),
        "Clearing": float(clear),
        "Handling": float(hand),
        "Protection": float(prot),
        "Other Local": float(row.get("Other Local",0.0)),
        "Desired Margin": float(mrg),
        "FreightAlloc": float(fr_alloc)
    }
    st.markdown("---")

# ---------- Compute landed costs ----------
def compute_rows(df_in, tariff, fx_rate):
    df = pd.DataFrame(df_in).copy()
    df["Freight_effective"] = np.where(df["Freight Override"], df["Manual Freight"], df["FreightAlloc"])
    merged = df.merge(tariff, how="left", on="Product Type", suffixes=("","_tariff"))
    for rate_col in ["Duty %","PAL %","CESS %","Excise %","SSCL %","VAT %"]:
        merged[rate_col] = pd.to_numeric(merged.get(rate_col,0.0), errors='coerce').fillna(0.0)
    merged["Total ExWorks_foreign"] = merged["Qty"] * merged["Unit ExWorks"]
    merged["Insurance_foreign"] = (merged["Total ExWorks_foreign"] + merged["Freight_effective"]) * merged["Insurance Rate"]
    merged["CIF_foreign"] = merged["Total ExWorks_foreign"] + merged["Freight_effective"] + merged["Insurance_foreign"]
    merged["Duty_foreign"] = merged["Duty %"] * merged["CIF_foreign"]
    merged["PAL_foreign"]  = merged["PAL %"] * merged["CIF_foreign"]
    merged["CESS_foreign"] = merged["CESS %"] * merged["CIF_foreign"]
    merged["Excise_foreign"] = merged["Excise %"] * ((merged["CIF_foreign"]*1.15) + merged["Duty_foreign"] + merged["PAL_foreign"] + merged["CESS_foreign"])
    merged["SSCL_foreign"] = merged["SSCL %"] * ((merged["CIF_foreign"]*1.10) + merged["Duty_foreign"] + merged["PAL_foreign"] + merged["CESS_foreign"] + merged["Excise_foreign"])
    merged["VAT_foreign"] = merged["VAT %"] * ((merged["CIF_foreign"]*1.15) + merged["Duty_foreign"] + merged["PAL_foreign"] + merged["CESS_foreign"] + merged["Excise_foreign"] + merged["SSCL_foreign"])
    for col in ["CIF","Duty","PAL","CESS","Excise","SSCL","VAT"]:
        merged[f"{col}_LKR"] = merged[f"{col}_foreign"] * fx_rate
    merged["Total_Local_charges"] = merged[["Installation","Clearing","Handling","Protection","Other Local"]].sum(axis=1)
    merged["Contingency_LKR"] = merged["Contingency %"] * merged["Total ExWorks_foreign"] * fx_rate
    merged["Total_Landed_LKR"] = merged[["CIF_LKR","Duty_LKR","PAL_LKR","CESS_LKR","Excise_LKR","SSCL_LKR","VAT_LKR"]].sum(axis=1) + merged["Total_Local_charges"] + merged["Contingency_LKR"]
    merged["Cost_per_unit_LKR"] = merged["Total_Landed_LKR"] / merged["Qty"].replace(0,1)
    merged["Price_markup"] = merged["Cost_per_unit_LKR"] * (1 + merged["Desired Margin"])
    merged["Price_margin_style"] = merged["Cost_per_unit_LKR"] / (1 - merged["Desired Margin"].replace(0, np.nan))
    return merged

if st.sidebar.button("Compute landed costs for rows"):
    df_products = pd.DataFrame(st.session_state.products)
    results = compute_rows(df_products, tariff_df, fx_rate)
    st.session_state.results = results
    st.success(f"Computed {len(results)} rows.")

# ---------- Show results & downloads ----------
if "results" in st.session_state:
    st.header("Results")
    show_cols = ["Product Type","HS Code","Qty","Unit ExWorks","Freight_effective","CIF_LKR","Duty_LKR","PAL_LKR","CESS_LKR","Excise_LKR","SSCL_LKR","VAT_LKR","Total_Local_charges","Contingency_LKR","Total_Landed_LKR","Cost_per_unit_LKR","Price_markup","Price_margin_style"]
    st.dataframe(st.session_state.results[show_cols], use_container_width=True)

    csv = st.session_state.results[show_cols].to_csv(index=False).encode('utf-8')
    st.download_button("Download results CSV", data=csv, file_name="costing_results.csv")

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        st.session_state.results.to_excel(writer, index=False, sheet_name="FullResults")
    st.download_button("Download full Excel", data=output.getvalue(), file_name="full_costing.xlsx")

st.caption("Tip: Enter exworks and quantities, set containers & freight per container, click 'Allocate freight', then compute landed costs.")


