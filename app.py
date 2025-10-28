# app_patched.py - Patched version with safe rerun handling
# (Replace your app.py with this file if you want the patched version)
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

# Logo upload (optional)
logo_file = st.sidebar.file_uploader("Upload company logo (optional)", type=["png","jpg","jpeg","svg"])
if logo_file:
    st.image(logo_file, width=160)

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
uploaded_wb = st.sidebar.file_uploader("Upload workbook (optional) - TariffTable sheet will be used", type=["xlsx","xls"])
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
        "ClearingAlloc":0.0,
        "UnloadingAlloc":0.0,
        "Installation_per_unit":0.0, "Handling_per_unit":0.0, "Protection_per_unit":0.0,
        "Other Local":0.0, "Contingency %":0.03, "Desired Margin":0.20, "Insurance Rate":0.003
    }

if "products" not in st.session_state:
    st.session_state.products = [default_row()]
if "allocated" not in st.session_state:
    st.session_state.allocated = False
if "last_saved" not in st.session_state:
    st.session_state.last_saved = None

# initialize rerun flag
if "_do_rerun" not in st.session_state:
    st.session_state["_do_rerun"] = False

# ----------------- Top help / How to use -----------------
with st.expander("How to use (quick) — recommended workflow", expanded=False):
    st.markdown("""1. Enter product lines (add rows on left). Use the Product Type dropdown so tariffs are auto-applied.  
2. Enter Qty and Unit ExWorks (foreign currency).  
3. In sidebar, set containers, freight per container, unloading per container (foreign) and total clearing (LKR).  
4. Click **Allocate freight & clearing & unloading** to auto-distribute those consignment costs by exworks-weighted ratio.  
5. Optionally override freight per row checkbox+value.  
6. Click **Compute landed costs for rows** to calculate CIF, taxes, totals.  
7. Download CSV/Excel or Save session.""")

# ----------------- Sidebar: Controls & global inputs -----------------
st.sidebar.header("Table controls")
add_n = st.sidebar.number_input("Add N blank rows", min_value=1, max_value=200, value=1, step=1)
if st.sidebar.button("Add blank rows"):
    for _ in range(add_n):
        st.session_state.products.append(default_row())
    # safe rerun
    try:
        st.experimental_rerun()
    except Exception:
        st.session_state["_do_rerun"] = True
        st.stop()

if st.sidebar.button("Clear all rows"):
    st.session_state.products = [default_row()]
    st.session_state.allocated = False
    try:
        st.experimental_rerun()
    except Exception:
        st.session_state["_do_rerun"] = True
        st.stop()

if st.sidebar.button("Duplicate last row"):
    st.session_state.products.append(st.session_state.products[-1].copy())
    try:
        st.experimental_rerun()
    except Exception:
        st.session_state["_do_rerun"] = True
        st.stop()

# shipment & allocation parameters
st.sidebar.header("Shipment & allocation (global)")
num_containers = st.sidebar.number_input("Number of containers", min_value=0, value=1, step=1)
freight_per_container = st.sidebar.number_input("Freight per container (foreign currency)", min_value=0.0, value=2500.0, format="%.2f")
unloading_per_container = st.sidebar.number_input("Unloading per container (foreign currency)", min_value=0.0, value=0.0, format="%.2f")
total_freight_override = st.sidebar.number_input("Total freight (override, foreign) - 0 to use containers calc", min_value=0.0, value=0.0, format="%.2f")
total_clearing = st.sidebar.number_input("Total clearing (LKR) - per consignment", min_value=0.0, value=0.0, format="%.2f")
total_unloading_override = st.sidebar.number_input("Total unloading (override, foreign) - 0 to use containers calc", min_value=0.0, value=0.0, format="%.2f")
insurance_rate_global = st.sidebar.number_input("Default insurance rate (decimal)", value=0.003, format="%.6f")
fx_rate = st.sidebar.number_input("FX Rate (LKR per foreign unit)", value=307.0, format="%.4f")

# Simple password (not secure) for demo 'multi-user' gating (free version can't do real auth)
st.sidebar.header("Access / session")
password = st.sidebar.text_input("Simple access code (optional)", type="password")
if password:
    st.sidebar.info("This is client-side only — not secure for sensitive data.")

# Session save / load
st.sidebar.header("Session")
if st.sidebar.button("Restore last session in this browser"):
    if st.session_state.last_saved:
        st.session_state.products = st.session_state.last_saved.copy()
        try:
            st.experimental_rerun()
        except Exception:
            st.session_state["_do_rerun"] = True
            st.stop()
    else:
        st.sidebar.info("No previous session in this browser.")
if st.sidebar.button("Download current session"):
    payload = {"products": st.session_state.products, "meta": {"ts": str(datetime.utcnow()), "fx_rate": fx_rate}}
    json_download_button(payload, f"cost_session_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json")

uploaded_session = st.sidebar.file_uploader("Upload session file (.json) to restore", type=["json"])
if uploaded_session:
    try:
        d = json.load(uploaded_session)
        if "products" in d:
            st.session_state.products = d["products"]
            try:
                st.experimental_rerun()
            except Exception:
                st.session_state["_do_rerun"] = True
                st.stop()
            st.sidebar.success("Session loaded.")
        else:
            st.sidebar.error("Invalid session file.")
    except Exception as e:
        st.sidebar.error("Failed to load session: " + str(e))

# ----------------- Allocation Logic -----------------
if st.sidebar.button("Allocate freight & clearing & unloading"):
    # compute totals
    total_freight = total_freight_override if total_freight_override > 0 else (num_containers * freight_per_container)
    total_unloading = total_unloading_override if total_unloading_override > 0 else (num_containers * unloading_per_container)
    # compute exworks per row
    exvals = np.array([float(r.get("Qty",0)) * float(r.get("Unit ExWorks",0.0)) for r in st.session_state.products], dtype=float)
    manual_flags = np.array([bool(r.get("Freight Override", False)) for r in st.session_state.products])
    manual_values = np.array([float(r.get("Manual Freight",0.0)) for r in st.session_state.products])
    manual_sum = manual_values[manual_flags].sum() if manual_flags.any() else 0.0
    remaining = total_freight - manual_sum
    if remaining < -1e-6:
        st.sidebar.error("Manual freight overrides exceed total freight. Reduce manual freight or increase total freight.")
    else:
        non_mask = ~manual_flags
        # allocate freight
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
        # allocate clearing in LKR by exworks ratio
        if total_clearing > 0:
            sum_ex_total = exvals.sum()
            if sum_ex_total <= 0:
                per_cl = total_clearing / max(len(st.session_state.products),1)
                for r in st.session_state.products:
                    r["ClearingAlloc"] = float(per_cl)
            else:
                for idx, r in enumerate(st.session_state.products):
                    ex = float(r.get("Qty",0)) * float(r.get("Unit ExWorks",0.0))
                    r["ClearingAlloc"] = float((ex / sum_ex_total) * total_clearing)
        # allocate unloading (foreign) like freight, using same exworks ratio but stored in foreign
        if total_unloading > 0:
            sum_ex_total = exvals.sum()
            if sum_ex_total <= 0:
                per_un = total_unloading / max(len(st.session_state.products),1)
                for r in st.session_state.products:
                    r["UnloadingAlloc"] = float(per_un)
            else:
                for idx, r in enumerate(st.session_state.products):
                    ex = float(r.get("Qty",0)) * float(r.get("Unit ExWorks",0.0))
                    r["UnloadingAlloc"] = float((ex / sum_ex_total) * total_unloading)
        st.session_state.allocated = True
        st.sidebar.success("Freight, clearing and unloading allocated. Review allocations in each row.")

# ----------------- Editable rows (main page) -----------------
st.header("Enter product lines")
st.caption("Select Product Type and enter Qty & Unit ExWorks. Per-unit local charges and allocations shown per row.")

for i, row in enumerate(st.session_state.products):
    st.markdown(f"**Row {i+1}**")
    cols = st.columns([2,1,1,1,1,1,0.6])
    pt = cols[0].selectbox("Product Type", options=[""] + product_types,
            index=(0 if row.get("Product Type","")=="" else (product_types.index(row["Product Type"])+1) if row.get("Product Type","") in product_types else 0),
            key=f"pt_{i}")
    hs_val = row.get("HS Code","")
    if pt and pt!="":
        match = tariff_df[tariff_df["Product Type"]==pt]
        if not match.empty:
            hs_val = str(match.iloc[0]["HS Code"])
    qty = cols[1].number_input("Qty", value=float(row.get("Qty",1)), min_value=0.0, step=1.0, format="%.0f", key=f"qty_{i}")
    ux = cols[2].number_input("Unit ExWorks", value=float(row.get("Unit ExWorks",0.0)), key=f"ux_{i}", format="%.2f")
    # FreightAlloc (foreign) displayed, UnloadingAlloc (foreign), ClearingAlloc (LKR)
    fr_alloc = float(row.get("FreightAlloc",0.0))
    unload_alloc = float(row.get("UnloadingAlloc",0.0))
    clearing_alloc = float(row.get("ClearingAlloc",0.0))
    cols[3].metric("FreightAlloc (foreign)", f"{fr_alloc:,.2f}")
    cols[4].metric("UnloadingAlloc (foreign)", f"{unload_alloc:,.2f}")
    cols[5].metric("ClearingAlloc (LKR)", f"{clearing_alloc:,.2f}")
    # manual freight override
    manual_flag = cols[6].checkbox("Override freight", value=bool(row.get("Freight Override",False)), key=f"ovr_{i}")
    manual_val = cols[6].number_input("Manual Freight", value=float(row.get("Manual Freight",0.0)), key=f"mf_{i}", format="%.2f")

    # per-unit local charges on the row
    cols2 = st.columns([1,1,1,1,1,1])
    inst_pu = cols2[0].number_input("Installation per unit (LKR)", value=float(row.get("Installation_per_unit",0.0)), key=f"instpu_{i}", format="%.2f")
    hand_pu = cols2[1].number_input("Handling per unit (LKR)", value=float(row.get("Handling_per_unit",0.0)), key=f"handpu_{i}", format="%.2f")
    prot_pu = cols2[2].number_input("Protection per unit (LKR)", value=float(row.get("Protection_per_unit",0.0)), key=f"protpu_{i}", format="%.2f")
    other_local = cols2[3].number_input("Other Local (LKR)", value=float(row.get("Other Local",0.0)), key=f"other_{i}", format="%.2f")
    contpct = cols2[4].number_input("Contingency %", value=float(row.get("Contingency %",0.03)), key=f"cont_{i}", format="%.4f")
    mrg = cols2[5].number_input("Desired margin", value=float(row.get("Desired Margin",0.20)), key=f"mrg_{i}", format="%.4f")

    # action buttons (safe - set rerun flag instead of immediate rerun)
    actc = st.columns([0.5,0.5])[1]
    with actc:
        if st.button("Delete", key=f"del_{i}"):
            st.session_state.products.pop(i)
            st.session_state["_do_rerun"] = True
        if st.button("Insert below", key=f"insrow_{i}"):
            st.session_state.products.insert(i+1, default_row())
            st.session_state["_do_rerun"] = True

    # write back values
    st.session_state.products[i] = {
        "Product Type": pt,
        "HS Code": hs_val,
        "Qty": int(qty),
        "Unit ExWorks": float(ux),
        "Manual Freight": float(manual_val),
        "Freight Override": bool(manual_flag),
        "FreightAlloc": float(fr_alloc),
        "ClearingAlloc": float(clearing_alloc),
        "UnloadingAlloc": float(unload_alloc),
        "Installation_per_unit": float(inst_pu),
        "Handling_per_unit": float(hand_pu),
        "Protection_per_unit": float(prot_pu),
        "Other Local": float(other_local),
        "Contingency %": float(contpct),
        "Desired Margin": float(mrg),
        "Insurance Rate": float(row.get("Insurance Rate", insurance_rate_global))
    }
    st.markdown("---")

# perform deferred rerun if flagged
if st.session_state.get("_do_rerun", False):
    st.session_state["_do_rerun"] = False
    try:
        st.experimental_rerun()
    except Exception:
        st.stop()

# ----------------- Compute rows -----------------
def compute_rows(df_in, tariff, fx_rate):
    df = pd.DataFrame(df_in).copy()
    # ensure columns
    expected = ["Product Type","HS Code","Qty","Unit ExWorks","FreightAlloc","Manual Freight","Freight Override","ClearingAlloc","UnloadingAlloc",
                "Installation_per_unit","Handling_per_unit","Protection_per_unit","Other Local","Contingency %","Desired Margin","Insurance Rate"]
    for c in expected:
        if c not in df.columns:
            df[c] = 0.0
    # numeric convert
    num_cols = [c for c in expected if c not in ["Product Type","HS Code"]]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
    # effective freight = manual if override else freightalloc
    df["Freight_effective"] = np.where(df["Freight Override"], df["Manual Freight"], df["FreightAlloc"])
    # effective unloading (same): use UnloadingAlloc
    df["Unloading_effective"] = df["UnloadingAlloc"]
    # merge tariff
    merged = df.merge(tariff, how="left", left_on="Product Type", right_on="Product Type", suffixes=("","_tariff"))
    merged["HS Code"] = merged["HS Code"].fillna(merged.get("HS Code_tariff",""))
    # convert rates to numeric
    for rate_col in ["Duty %","PAL %","CESS %","Excise %","SSCL %","VAT %"]:
        merged[rate_col] = pd.to_numeric(merged.get(rate_col,0.0), errors='coerce').fillna(0.0)
    # Exworks foreign
    merged["Total ExWorks_foreign"] = merged["Qty"] * merged["Unit ExWorks"]
   sum_ex = merged["Total ExWorks_foreign"].sum()
# If sum_ex is zero (no exworks values) avoid division by zero — set weight to 0
if sum_ex == 0 or np.isclose(sum_ex, 0.0):
    merged["ExworksWeight"] = 0.0
else:
    merged["ExworksWeight"] = merged["Total ExWorks_foreign"] / float(sum_ex)

    # per-unit local -> totals (LKR)
    merged["Installation_total_LKR"] = merged["Installation_per_unit"] * merged["Qty"]
    merged["Handling_total_LKR"] = merged["Handling_per_unit"] * merged["Qty"]
    merged["Protection_total_LKR"] = merged["Protection_per_unit"] * merged["Qty"]
    merged["Total_Local_charges"] = merged[["Installation_total_LKR","Handling_total_LKR","Protection_total_LKR","Other Local"]].sum(axis=1)
    # Add ClearingAlloc already in LKR
    # Add Freight and Unloading in foreign currency to CIF
    # Use Freight_effective + Unloading_effective
    merged["Insurance_foreign"] = (merged["Total ExWorks_foreign"] + merged["Freight_effective"] + merged["Unloading_effective"]) * merged["Insurance Rate"]
    merged["CIF_foreign"] = merged["Total ExWorks_foreign"] + merged["Freight_effective"] + merged["Unloading_effective"] + merged["Insurance_foreign"]
    # duties
    merged["Duty_foreign"] = merged["Duty %"] * merged["CIF_foreign"]
    merged["PAL_foreign"]  = merged["PAL %"] * merged["CIF_foreign"]
    merged["CESS_foreign"] = merged["CESS %"] * merged["CIF_foreign"]
    # excise, sscl, vat per formulas
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
    # convert required foreign values to LKR
    for col in ["CIF","Duty","PAL","CESS","Excise","SSCL","VAT"]:
        merged[f"{col}_LKR"] = merged[f"{col}_foreign"] * fx_rate
    # Contingency in LKR
    merged["Contingency_LKR"] = merged["Contingency %"] * merged["Total ExWorks_foreign"] * fx_rate
    # Total landed LKR includes clearing allocation and local charges
    merged["Total_Landed_LKR"] = merged[["CIF_LKR","Duty_LKR","PAL_LKR","CESS_LKR","Excise_LKR","SSCL_LKR","VAT_LKR"]].sum(axis=1) + merged["Total_Local_charges"] + merged["ClearingAlloc"] + merged["Contingency_LKR"]
    merged["Cost_per_unit_LKR"] = merged["Total_Landed_LKR"] / merged["Qty"].replace(0,1)
    merged["Price_markup"] = merged["Cost_per_unit_LKR"] * (1 + merged["Desired Margin"])
    merged["Price_margin_style"] = merged["Cost_per_unit_LKR"] / (1 - merged["Desired Margin"].replace(0, np.nan))
    return merged

# ----------------- Compute button -----------------
if st.sidebar.button("Compute landed costs for rows"):
    # If allocations not done, auto-allocate (friendly)
    if not st.session_state.allocated:
        st.sidebar.info("Allocating freight / clearing / unloading automatically.")
        # perform allocation same code as allocate button (to avoid duplication, you could refactor)
        total_freight = total_freight_override if total_freight_override > 0 else (num_containers * freight_per_container)
        total_unloading = total_unloading_override if total_unloading_override > 0 else (num_containers * unloading_per_container)
        exvals = np.array([float(r.get("Qty",0)) * float(r.get("Unit ExWorks",0.0)) for r in st.session_state.products], dtype=float)
        manual_flags = np.array([bool(r.get("Freight Override", False)) for r in st.session_state.products])
        manual_values = np.array([float(r.get("Manual Freight",0.0)) for r in st.session_state.products])
        manual_sum = manual_values[manual_flags].sum() if manual_flags.any() else 0.0
        remaining = total_freight - manual_sum
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
        # clearing
        if total_clearing > 0:
            sum_ex_total = exvals.sum()
            if sum_ex_total <= 0:
                per_cl = total_clearing / max(len(st.session_state.products),1)
                for r in st.session_state.products:
                    r["ClearingAlloc"] = float(per_cl)
            else:
                for idx, r in enumerate(st.session_state.products):
                    ex = float(r.get("Qty",0)) * float(r.get("Unit ExWorks",0.0))
                    r["ClearingAlloc"] = float((ex / sum_ex_total) * total_clearing)
        # unloading
        if total_unloading > 0:
            sum_ex_total = exvals.sum()
            if sum_ex_total <= 0:
                per_un = total_unloading / max(len(st.session_state.products),1)
                for r in st.session_state.products:
                    r["UnloadingAlloc"] = float(per_un)
            else:
                for idx, r in enumerate(st.session_state.products):
                    ex = float(r.get("Qty",0)) * float(r.get("Unit ExWorks",0.0))
                    r["UnloadingAlloc"] = float((ex / sum_ex_total) * total_unloading)
        st.session_state.allocated = True

    df_products = pd.DataFrame(st.session_state.products)
    results = compute_rows(df_products, tariff_df, fx_rate)
    st.session_state.results = results
    st.session_state.last_saved = st.session_state.products.copy()
    st.success(f"Computed {len(results)} rows.")

# ----------------- Show results, summary and downloads -----------------
if "results" in st.session_state:
    st.header("Results & summary")
    res = st.session_state.results.copy()
    # Summary cards
    total_freight_used = res["Freight_effective"].sum() if "Freight_effective" in res.columns else 0.0
    total_unloading_used = res["Unloading_effective"].sum() if "Unloading_effective" in res.columns else 0.0
    total_clearing_used = res["ClearingAlloc"].sum() if "ClearingAlloc" in res.columns else 0.0
    total_landed = res["Total_Landed_LKR"].sum()
    avg_cost_unit = res["Cost_per_unit_LKR"].mean() if "Cost_per_unit_LKR" in res.columns else 0.0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Freight (foreign)", format_num(total_freight_used))
    c2.metric("Total Unloading (foreign)", format_num(total_unloading_used))
    c3.metric("Total Clearing (LKR)", format_num(total_clearing_used))
    c4.metric("Total Landed (LKR)", format_num(total_landed))

    # prepare display table (friendly formatting)
    present_cols = ["Product Type","HS Code","Qty","Unit ExWorks","ExworksWeight","Freight_effective","Unloading_effective","ClearingAlloc","CIF_LKR","Duty_LKR","PAL_LKR","CESS_LKR","Excise_LKR","SSCL_LKR","VAT_LKR","Installation_total_LKR","Handling_total_LKR","Protection_total_LKR","Total_Local_charges","Contingency_LKR","Total_Landed_LKR","Cost_per_unit_LKR","Price_markup","Price_margin_style"]
    present = [c for c in present_cols if c in res.columns]
    disp = res[present].copy()
    # apply friendly formatting to numeric columns
    for c in disp.columns:
        if c not in ["Product Type","HS Code","Qty"]:
            disp[c] = disp[c].apply(lambda x: format_num(x))
    st.dataframe(disp.reset_index(drop=True), use_container_width=True)

    # downloads - raw numeric CSV
    csv = res[present].to_csv(index=False).encode('utf-8')
    st.download_button("Download results CSV (raw numbers)", data=csv, file_name="costing_results.csv")

    # export Excel with summary, inputs, results
    if st.button("Download report (Excel)"):
        # Build sheets
        meta = pd.DataFrame([{"Generated": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"), "FX": fx_rate, "Total Landed (LKR)": total_landed}])
        inputs = pd.DataFrame(st.session_state.products)
        # raw results already in res
        sheets = {"Summary": meta, "Inputs": inputs, "Results": res}
        b = excel_download_bytes(sheets)
        st.download_button("Download Excel file", data=b, file_name=f"costing_report_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.xlsx")

st.caption("Tip: Save session to continue later. Use the dropdown to avoid typos. If you want per-row clearing overrides, tell me and I'll add it.")
