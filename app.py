import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
import json
from datetime import datetime

st.set_page_config(layout="wide", page_title="Import Cost Calculator (JAT)", page_icon="🧾")

# ----------------- UI Header / Branding -----------------
st.markdown("<h1 style='margin-bottom:0.1rem'>Import Cost Calculator</h1>", unsafe_allow_html=True)
st.markdown("<div style='color:gray;margin-top:0;padding-bottom:0.5rem'>JAT - Project costing & landed import calculations</div>", unsafe_allow_html=True)

# ----------------- Helpers -----------------
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

def format_num(x):
    try:
        return f"{x:,.2f}"
    except:
        return x

def json_download_button(data, filename):
    b = json.dumps(data, default=str).encode('utf-8')
    st.download_button("Save session (download JSON)", data=b, file_name=filename, mime="application/json")

def excel_download_bytes(sheets_dict):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, df in sheets_dict.items():
            df.to_excel(writer, sheet_name=name[:30], index=False)
    return output.getvalue()

# ----------------- Load tariff -----------------
uploaded_wb = st.sidebar.file_uploader("Upload workbook (optional)", type=["xlsx","xls"])
wb_source = uploaded_wb if uploaded_wb is not None else DEFAULT_WB
tariff_df = load_tariff(wb_source)
product_types = list(tariff_df['Product Type'].dropna().unique())
st.sidebar.subheader("Tariff preview")
st.sidebar.dataframe(tariff_df.head(8))

# ----------------- Session defaults -----------------
def default_row():
    return {
        "Product Type":"", "HS Code":"", "Qty":1, "Unit ExWorks":0.0,
        "Manual Freight":0.0, "Freight Override":False, "FreightAlloc":0.0,
        "ClearingAlloc":0.0, "UnloadingAlloc":0.0,
        "Installation_per_unit":0.0, "Handling_per_unit":0.0, "Protection_per_unit":0.0,
        "Other Local":0.0, "Contingency %":0.03, "Desired Margin":0.20, "Insurance Rate":0.003
    }

if "products" not in st.session_state:
    st.session_state.products = [default_row()]
if "allocated" not in st.session_state:
    st.session_state.allocated = False
if "_do_rerun" not in st.session_state:
    st.session_state["_do_rerun"] = False

# ----------------- Sidebar Inputs -----------------
st.sidebar.header("Shipment & allocation")
num_containers = st.sidebar.number_input("Containers", min_value=0, value=1)
freight_per_container = st.sidebar.number_input("Freight per container (foreign)", min_value=0.0, value=2500.0)
unloading_per_container = st.sidebar.number_input("Unloading per container (foreign)", min_value=0.0, value=0.0)
total_clearing = st.sidebar.number_input("Total clearing (LKR)", min_value=0.0, value=0.0)
fx_rate = st.sidebar.number_input("FX Rate (LKR per foreign unit)", value=307.0, format="%.4f")

# ----------------- Freight/Clearing Allocation -----------------
if st.sidebar.button("Allocate freight, clearing, unloading"):
    total_freight = num_containers * freight_per_container
    total_unloading = num_containers * unloading_per_container
    exvals = np.array([float(r.get("Qty",0)) * float(r.get("Unit ExWorks",0.0)) for r in st.session_state.products])
    sum_ex = exvals.sum()

    for i, r in enumerate(st.session_state.products):
        ex = float(r.get("Qty",0)) * float(r.get("Unit ExWorks",0.0))
        r["FreightAlloc"] = (ex / sum_ex) * total_freight if sum_ex else 0.0
        r["ClearingAlloc"] = (ex / sum_ex) * total_clearing if sum_ex else 0.0
        r["UnloadingAlloc"] = (ex / sum_ex) * total_unloading if sum_ex else 0.0

    st.session_state.allocated = True
    st.sidebar.success("Freight, clearing, unloading allocated")

# ----------------- Product Table -----------------
st.header("Enter product lines")
for i, row in enumerate(st.session_state.products):
    cols = st.columns([2,1,1,1,1])
    pt = cols[0].selectbox(f"Product Type {i+1}", [""] + product_types, index=product_types.index(row["Product Type"])+1 if row["Product Type"] in product_types else 0, key=f"pt_{i}")
    qty = cols[1].number_input("Qty", value=float(row["Qty"]), min_value=0.0, step=1.0, key=f"qty_{i}")
    ux = cols[2].number_input("Unit ExWorks", value=float(row["Unit ExWorks"]), key=f"ux_{i}", format="%.2f")
    inst = cols[3].number_input("Installation (per unit LKR)", value=float(row["Installation_per_unit"]), key=f"inst_{i}", format="%.2f")
    hand = cols[4].number_input("Handling (per unit LKR)", value=float(row["Handling_per_unit"]), key=f"hand_{i}", format="%.2f")

    st.session_state.products[i]["Product Type"] = pt
    st.session_state.products[i]["Qty"] = qty
    st.session_state.products[i]["Unit ExWorks"] = ux
    st.session_state.products[i]["Installation_per_unit"] = inst
    st.session_state.products[i]["Handling_per_unit"] = hand

# ----------------- Compute -----------------
def compute_rows(df_in, tariff, fx_rate):
    df = pd.DataFrame(df_in).copy()
    merged = df.merge(tariff, how="left", on="Product Type")
    merged["Total ExWorks_foreign"] = merged["Qty"] * merged["Unit ExWorks"]
    sum_ex = merged["Total ExWorks_foreign"].sum()
    if sum_ex == 0 or np.isclose(sum_ex, 0.0):
        merged["ExworksWeight"] = 0.0
    else:
        merged["ExworksWeight"] = merged["Total ExWorks_foreign"] / float(sum_ex)
    merged["CIF_foreign"] = merged["Total ExWorks_foreign"] + merged["FreightAlloc"] + merged["UnloadingAlloc"]
    merged["CIF_LKR"] = merged["CIF_foreign"] * fx_rate
    merged["Total_Landed_LKR"] = merged["CIF_LKR"] + merged["ClearingAlloc"] + (merged["Installation_per_unit"] * merged["Qty"]) + (merged["Handling_per_unit"] * merged["Qty"])
    merged["Cost_per_unit_LKR"] = merged["Total_Landed_LKR"] / merged["Qty"].replace(0,1)
    return merged

if st.sidebar.button("Compute landed costs"):
    df_products = pd.DataFrame(st.session_state.products)
    st.session_state.results = compute_rows(df_products, tariff_df, fx_rate)
    st.success("Landed cost calculated successfully")

# ----------------- Results -----------------
if "results" in st.session_state:
    st.header("Results")
    res = st.session_state.results.copy()
    for c in res.columns:
        if c not in ["Product Type","HS Code"]:
            res[c] = res[c].apply(lambda x: format_num(x))
    st.dataframe(res, use_container_width=True)

