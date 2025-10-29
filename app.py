# app.py — Costing tool with: Protection (per unit), multi-row controls,
# consignment allocations (Freight, Clearing LKR, Unloading as Foreign or LKR),
# weightage ratios, safe rerun, and formatted outputs.

import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
from datetime import datetime
import json

st.set_page_config(page_title="Import Cost Calculator (JAT)", page_icon="🧾", layout="wide")

# ------------------------ Helpers ------------------------
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
    try: return f"{x:,.2f}"
    except: return x

def excel_bytes(sheets: dict):
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name[:31], index=False)
    return out.getvalue()

# ------------------------ Load tariff ------------------------
uploaded = st.sidebar.file_uploader("Upload workbook (optional) — uses sheet 'TariffTable'", type=["xlsx","xls"])
tariff_df = load_tariff(uploaded if uploaded else DEFAULT_WB)
product_types = list(tariff_df['Product Type'].dropna().unique())
st.sidebar.subheader("Tariff preview")
st.sidebar.dataframe(tariff_df.head(8), use_container_width=True)

# ------------------------ Session defaults ------------------------
def default_row():
    return {
        "Product Type":"", "HS Code":"", "Qty":1, "Unit ExWorks":0.0,
        "Manual Freight":0.0, "Freight Override":False, "FreightAlloc":0.0,
        "ClearingAlloc":0.0,
        "UnloadingAlloc":0.0,         # foreign allocation (if unloading in foreign)
        "UnloadingAlloc_LKR":0.0,     # LKR allocation (if unloading in LKR OR converted from foreign)
        "Installation_per_unit":0.0, "Handling_per_unit":0.0, "Protection_per_unit":0.0,
        "Other Local":0.0, "Contingency %":0.03, "Desired Margin":0.20, "Insurance Rate":0.003
    }

ss = st.session_state
if "products" not in ss: ss.products = [default_row()]
if "allocated" not in ss: ss.allocated = False
if "_do_rerun" not in ss: ss._do_rerun = False

# ------------------------ Header ------------------------
st.markdown("<h1 style='margin:0'>Import Cost Calculator</h1>", unsafe_allow_html=True)
st.caption("Multi-line costing with freight, clearing & unloading allocation; per-unit local charges; and tariff-based duties.")

with st.expander("How to use (quick)"):
    st.markdown("""
**Step 1.** Enter product lines (select *Product Type* to auto-fill HS & tariffs).  
**Step 2.** In the sidebar, set containers and consignment charges → click **Allocate consignment costs**.  
**Step 3.** Click **Compute landed costs**. Download CSV/Excel if needed.
""")

# ------------------------ Sidebar controls ------------------------
st.sidebar.header("Row controls")
add_n = st.sidebar.number_input("Add N blank rows", min_value=1, max_value=200, value=1, step=1)
if st.sidebar.button("Add blank rows"):
    for _ in range(add_n): ss.products.append(default_row())
    try: st.experimental_rerun()
    except Exception: ss._do_rerun = True; st.stop()

if st.sidebar.button("Duplicate last row"):
    ss.products.append(ss.products[-1].copy())
    try: st.experimental_rerun()
    except Exception: ss._do_rerun = True; st.stop()

if st.sidebar.button("Clear all rows"):
    ss.products = [default_row()]
    ss.allocated = False
    try: st.experimental_rerun()
    except Exception: ss._do_rerun = True; st.stop()

st.sidebar.header("Shipment & consignment")
cols = st.sidebar.columns(2)
num_cont = cols[0].number_input("Containers", min_value=0, value=1, step=1)
fx_rate = cols[1].number_input("FX Rate (LKR per foreign)", value=307.0, format="%.4f")

freight_per_container = st.sidebar.number_input("Freight per container (foreign)", min_value=0.0, value=2500.0, format="%.2f")
total_clearing_lkr = st.sidebar.number_input("Total clearing (LKR)", min_value=0.0, value=0.0, format="%.2f")

un_mode = st.sidebar.selectbox("Unloading currency", ["Foreign (per container)", "LKR (total)"])
if un_mode == "Foreign (per container)":
    unloading_per_container_foreign = st.sidebar.number_input("Unloading per container (foreign)", min_value=0.0, value=0.0, format="%.2f")
    total_unloading_foreign = num_cont * unloading_per_container_foreign
    total_unloading_lkr = None
else:
    total_unloading_lkr = st.sidebar.number_input("Total unloading (LKR)", min_value=0.0, value=0.0, format="%.2f")
    total_unloading_foreign = None

ins_rate_global = st.sidebar.number_input("Default insurance rate (decimal)", value=0.003, format="%.6f")

if st.sidebar.button("Allocate consignment costs"):
    exvals = np.array([float(r.get("Qty",0)) * float(r.get("Unit ExWorks",0.0)) for r in ss.products], dtype=float)
    sum_ex = float(exvals.sum())
    # Freight allocation with manual overrides (foreign)
    total_freight = num_cont * freight_per_container
    manual_flags = np.array([bool(r.get("Freight Override", False)) for r in ss.products])
    manual_vals  = np.array([float(r.get("Manual Freight",0.0)) for r in ss.products])
    manual_sum = manual_vals[manual_flags].sum() if manual_flags.any() else 0.0
    remaining = total_freight - manual_sum

    if remaining < -1e-6:
        st.sidebar.error("Manual freight overrides exceed total freight.")
    else:
        non_mask = ~manual_flags
        if non_mask.sum() == 0:
            for r in ss.products:
                r["FreightAlloc"] = float(r.get("Manual Freight",0.0))
        else:
            if sum_ex <= 0:
                per = remaining / non_mask.sum() if non_mask.sum() > 0 else 0.0
                for idx, r in enumerate(ss.products):
                    r["FreightAlloc"] = float(r.get("Manual Freight",0.0)) if manual_flags[idx] else float(per)
            else:
                ratios = exvals / sum_ex
                for idx, r in enumerate(ss.products):
                    r["FreightAlloc"] = float(r.get("Manual Freight",0.0)) if manual_flags[idx] else float(ratios[idx] * remaining)

    # Clearing allocation (LKR)
    for idx, r in enumerate(ss.products):
        share = (exvals[idx] / sum_ex) if sum_ex > 0 else (1.0/len(ss.products))
        r["ClearingAlloc"] = float(share * total_clearing_lkr) if total_clearing_lkr > 0 else 0.0

    # Unloading allocation (foreign or LKR)
    if un_mode == "Foreign (per container)":
        for idx, r in enumerate(ss.products):
            share = (exvals[idx] / sum_ex) if sum_ex > 0 else (1.0/len(ss.products))
            r["UnloadingAlloc"] = float(share * total_unloading_foreign) if (total_unloading_foreign and total_unloading_foreign > 0) else 0.0
            r["UnloadingAlloc_LKR"] = 0.0  # will be computed from foreign later
    else:
        for idx, r in enumerate(ss.products):
            share = (exvals[idx] / sum_ex) if sum_ex > 0 else (1.0/len(ss.products))
            r["UnloadingAlloc_LKR"] = float(share * total_unloading_lkr) if (total_unloading_lkr and total_unloading_lkr > 0) else 0.0
            r["UnloadingAlloc"] = 0.0

    # apply global insurance rate default to rows that kept default
    for r in ss.products:
        if float(r.get("Insurance Rate", 0.003)) == 0.003:
            r["Insurance Rate"] = float(ins_rate_global)

    ss.allocated = True
    st.sidebar.success("Consignment costs allocated.")

# ------------------------ Product entry table ------------------------
st.header("Enter product lines")
st.caption("Select Product Type → enter Qty & Unit ExWorks. Per-unit local charges are in LKR.")

for i, row in enumerate(ss.products):
    st.markdown(f"**Row {i+1}**")
    c1, c2, c3, c4, c5, c6, c7 = st.columns([2,1,1,1,1,1,1.2])
    pt = c1.selectbox("Product Type", [""] + product_types,
                      index=(product_types.index(row["Product Type"])+1) if row["Product Type"] in product_types else 0,
                      key=f"pt_{i}")
    # auto HS from tariff
    hs = row.get("HS Code","")
    if pt:
        m = tariff_df[tariff_df["Product Type"]==pt]
        if not m.empty: hs = str(m.iloc[0]["HS Code"])
    qty = c2.number_input("Qty", value=float(row.get("Qty",1)), min_value=0.0, step=1.0, format="%.0f", key=f"qty_{i}")
    ux  = c3.number_input("Unit ExWorks", value=float(row.get("Unit ExWorks",0.0)), format="%.2f", key=f"ux_{i}")
    inst_pu = c4.number_input("Installation /unit (LKR)", value=float(row.get("Installation_per_unit",0.0)), format="%.2f", key=f"inst_{i}")
    hand_pu = c5.number_input("Handling /unit (LKR)", value=float(row.get("Handling_per_unit",0.0)), format="%.2f", key=f"hand_{i}")
    prot_pu = c6.number_input("Protection /unit (LKR)", value=float(row.get("Protection_per_unit",0.0)), format="%.2f", key=f"prot_{i}")
    c7.metric("FreightAlloc (foreign)", f"{float(row.get('FreightAlloc',0.0)):,.2f}")

    c8, c9, c10 = st.columns([1,1,1.6])
    other = c8.number_input("Other Local (LKR)", value=float(row.get("Other Local",0.0)), format="%.2f", key=f"ol_{i}")
    cont = c9.number_input("Contingency %", value=float(row.get("Contingency %",0.03)), format="%.4f", key=f"cont_{i}")
    margin = c10.number_input("Desired margin", value=float(row.get("Desired Margin",0.20)), format="%.4f", key=f"mrg_{i}")

    c11, c12, c13, c14 = st.columns([1.2,1.2,1.2,1])
    c11.metric("ClearingAlloc (LKR)", f"{float(row.get('ClearingAlloc',0.0)):,.2f}")
    if un_mode == "Foreign (per container)":
        c12.metric("UnloadingAlloc (foreign)", f"{float(row.get('UnloadingAlloc',0.0)):,.2f}")
    else:
        c12.metric("UnloadingAlloc (LKR)", f"{float(row.get('UnloadingAlloc_LKR',0.0)):,.2f}")
    # Manual freight override toggle
    ovr = c13.checkbox("Override freight", value=bool(row.get("Freight Override", False)), key=f"ovr_{i}")
    mf  = c13.number_input("Manual Freight", value=float(row.get("Manual Freight",0.0)), format="%.2f", key=f"mf_{i}")
    # row actions
    with c14:
        if st.button("Delete", key=f"del_{i}"):
            ss.products.pop(i); ss._do_rerun = True
        if st.button("Insert ↓", key=f"ins_{i}"):
            ss.products.insert(i+1, default_row()); ss._do_rerun = True

    # write back
    ss.products[i] = {
        "Product Type": pt, "HS Code": hs, "Qty": int(qty), "Unit ExWorks": float(ux),
        "Installation_per_unit": float(inst_pu), "Handling_per_unit": float(hand_pu), "Protection_per_unit": float(prot_pu),
        "Other Local": float(other), "Contingency %": float(cont), "Desired Margin": float(margin),
        "FreightAlloc": float(row.get("FreightAlloc",0.0)), "ClearingAlloc": float(row.get("ClearingAlloc",0.0)),
        "UnloadingAlloc": float(row.get("UnloadingAlloc",0.0)), "UnloadingAlloc_LKR": float(row.get("UnloadingAlloc_LKR",0.0)),
        "Freight Override": bool(ovr), "Manual Freight": float(mf),
        "Insurance Rate": float(row.get("Insurance Rate", ins_rate_global))
    }
    st.markdown("---")

# deferred safe rerun
if ss._do_rerun:
    ss._do_rerun = False
    try: st.experimental_rerun()
    except Exception: st.stop()

# ------------------------ Computation ------------------------
def compute_rows(df_in, tariff, fx_rate, unloading_mode_foreign: bool):
    df = pd.DataFrame(df_in).copy()
    # effective freight (use manual if override)
    df["Freight_effective"] = np.where(df["Freight Override"], df["Manual Freight"], df["FreightAlloc"])
    # merge tariffs
    merged = df.merge(tariff, how="left", on="Product Type", suffixes=("","_t"))
    merged["HS Code"] = merged["HS Code"].fillna(merged.get("HS Code_t",""))
    # numeric tariff columns
    for col in ["Duty %","PAL %","CESS %","Excise %","SSCL %","VAT %"]:
        merged[col] = pd.to_numeric(merged.get(col,0.0), errors="coerce").fillna(0.0)

    # exworks, weights
    merged["Total ExWorks_foreign"] = merged["Qty"] * merged["Unit ExWorks"]
    sum_ex = float(merged["Total ExWorks_foreign"].sum())
    if sum_ex == 0 or np.isclose(sum_ex, 0.0):
        merged["ExworksWeight"] = 0.0
    else:
        merged["ExworksWeight"] = merged["Total ExWorks_foreign"] / sum_ex

    # unloading handling
    if unloading_mode_foreign:
        merged["Unloading_foreign"] = merged["UnloadingAlloc"]
        merged["Unloading_LKR"] = merged["UnloadingAlloc"] * fx_rate
    else:
        merged["Unloading_foreign"] = 0.0
        merged["Unloading_LKR"] = merged["UnloadingAlloc_LKR"]

    # insurance & CIF (foreign)
    merged["Insurance_foreign"] = (merged["Total ExWorks_foreign"] + merged["Freight_effective"] + merged["Unloading_foreign"]) * merged["Insurance Rate"]
    merged["CIF_foreign"] = merged["Total ExWorks_foreign"] + merged["Freight_effective"] + merged["Unloading_foreign"] + merged["Insurance_foreign"]

    # duties on foreign base
    merged["Duty_foreign"] = merged["Duty %"] * merged["CIF_foreign"]
    merged["PAL_foreign"]  = merged["PAL %"]  * merged["CIF_foreign"]
    merged["CESS_foreign"] = merged["CESS %"] * merged["CIF_foreign"]
    merged["Excise_foreign"] = 0.0
    mask_exc = merged["Excise %"] > 0
    merged.loc[mask_exc, "Excise_foreign"] = merged.loc[mask_exc].apply(
        lambda r: r["Excise %"] * ((r["CIF_foreign"]*1.15) + r["Duty_foreign"] + r["PAL_foreign"] + r["CESS_foreign"]), axis=1
    )
    merged["SSCL_foreign"] = 0.0
    mask_ss = merged["SSCL %"] > 0
    merged.loc[mask_ss, "SSCL_foreign"] = merged.loc[mask_ss].apply(
        lambda r: r["SSCL %"] * ((r["CIF_foreign"]*1.10) + r["Duty_foreign"] + r["PAL_foreign"] + r["CESS_foreign"] + r["Excise_foreign"]), axis=1
    )
    merged["VAT_foreign"] = merged.apply(
        lambda r: r["VAT %"] * ((r["CIF_foreign"]*1.15) + r["Duty_foreign"] + r["PAL_foreign"] + r["CESS_foreign"] + r["Excise_foreign"] + r["SSCL_foreign"]) if r["VAT %"]>0 else 0.0,
        axis=1
    )

    # convert foreign → LKR
    for base in ["CIF","Duty","PAL","CESS","Excise","SSCL","VAT"]:
        merged[f"{base}_LKR"] = merged[f"{base}_foreign"] * fx_rate

    # local totals (per-unit in LKR)
    merged["Installation_total_LKR"] = merged["Installation_per_unit"] * merged["Qty"]
    merged["Handling_total_LKR"]    = merged["Handling_per_unit"]    * merged["Qty"]
    merged["Protection_total_LKR"]  = merged["Protection_per_unit"]  * merged["Qty"]
    merged["Total_Local_charges"]   = merged[["Installation_total_LKR","Handling_total_LKR","Protection_total_LKR","Other Local"]].sum(axis=1)

    # contingency (LKR) based on exworks foreign
    merged["Contingency_LKR"] = merged["Contingency %"] * merged["Total ExWorks_foreign"] * fx_rate

    # total landed (include clearing LKR + unloading LKR)
    merged["Total_Landed_LKR"] = merged[["CIF_LKR","Duty_LKR","PAL_LKR","CESS_LKR","Excise_LKR","SSCL_LKR","VAT_LKR"]].sum(axis=1) \
                               + merged["ClearingAlloc"] + merged["Unloading_LKR"] + merged["Total_Local_charges"] + merged["Contingency_LKR"]

    merged["Cost_per_unit_LKR"] = merged["Total_Landed_LKR"] / merged["Qty"].replace(0,1)
    merged["Price_markup"] = merged["Cost_per_unit_LKR"] * (1 + merged["Desired Margin"])
    merged["Price_margin_style"] = merged["Cost_per_unit_LKR"] / (1 - merged["Desired Margin"].replace(0, np.nan))

    return merged

# ------------------------ Compute & Display ------------------------
if st.sidebar.button("Compute landed costs"):
    unloading_foreign_mode = (un_mode == "Foreign (per container)")
    df_in = pd.DataFrame(ss.products)
    res = compute_rows(df_in, tariff_df, fx_rate, unloading_foreign_mode)
    ss.results = res
    st.success("Landed cost calculated successfully")

if "results" in ss:
    res = ss.results.copy()
    st.header("Results")

    # Summary cards
    c1,c2,c3,c4 = st.columns(4)
    total_freight = res["Freight_effective"].sum() if "Freight_effective" in res else 0.0
    total_unload_lkr = res["Unloading_LKR"].sum() if "Unloading_LKR" in res else 0.0
    total_clearing = res["ClearingAlloc"].sum() if "ClearingAlloc" in res else 0.0
    total_landed = res["Total_Landed_LKR"].sum() if "Total_Landed_LKR" in res else 0.0
    c1.metric("Total Freight (foreign)", format_num(total_freight))
    c2.metric("Total Unloading (LKR)", format_num(total_unload_lkr))
    c3.metric("Total Clearing (LKR)", format_num(total_clearing))
    c4.metric("Total Landed (LKR)", format_num(total_landed))

    show_cols = [
        "Product Type","HS Code","Qty","Unit ExWorks",
        "ExworksWeight",
        "Freight_effective","Unloading_foreign","Unloading_LKR","ClearingAlloc",
        "CIF_LKR","Duty_LKR","PAL_LKR","CESS_LKR","Excise_LKR","SSCL_LKR","VAT_LKR",
        "Installation_total_LKR","Handling_total_LKR","Protection_total_LKR",
        "Total_Local_charges","Contingency_LKR",
        "Total_Landed_LKR","Cost_per_unit_LKR","Price_markup","Price_margin_style"
    ]
    show_cols = [c for c in show_cols if c in res.columns]
    disp = res[show_cols].copy()
    for c in disp.columns:
        if c not in ["Product Type","HS Code","Qty"]:
            disp[c] = disp[c].apply(format_num)
    st.dataframe(disp, use_container_width=True)

    # Downloads (raw numeric)
    csv = res[show_cols].to_csv(index=False).encode("utf-8")
    st.download_button("Download results CSV", data=csv, file_name="costing_results.csv")
    xbytes = excel_bytes({"Results": res, "Inputs": pd.DataFrame(ss.products), "Tariff": tariff_df})
    st.download_button("Download report (Excel)", data=xbytes, file_name=f"costing_report_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.xlsx")


