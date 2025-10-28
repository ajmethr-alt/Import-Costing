# app.py - Multi-line costing with freight + clearing allocation, per-unit local charges, formatted output
import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

st.set_page_config(layout="wide", page_title="Import Cost Calculator - Allocations")

st.title("Import Cost Calculator — Freight & Clearing allocation, per-unit local charges")

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

# ---------- Load tariff ----------
uploaded_wb = st.sidebar.file_uploader("Upload workbook (optional) - TariffTable sheet will be used", type=["xlsx","xls"])
wb_source = uploaded_wb if uploaded_wb is not None else DEFAULT_WB
tariff_df = load_tariff(wb_source)
product_types = list(tariff_df['Product Type'].dropna().unique())
st.sidebar.subheader("Tariff preview")
st.sidebar.dataframe(tariff_df.head(8))

# ---------- Session defaults ----------
def default_row():
    return {
        "Product Type":"", "HS Code":"", "Qty":1, "Unit ExWorks":0.0,
        "Manual Freight":0.0, "Freight Override":False, "FreightAlloc":0.0,
        "Installation_per_unit":0.0, "Handling_per_unit":0.0, "Protection_per_unit":0.0,
        "Other Local":0.0, "Contingency %":0.03, "Desired Margin":0.20
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

# ---------- Global shipment / allocation settings ----------
st.sidebar.header("Shipment & allocation (global)")
num_containers = st.sidebar.number_input("Number of containers", min_value=0, value=1, step=1)
freight_per_container = st.sidebar.number_input("Freight per container (foreign currency)", min_value=0.0, value=2500.0, format="%.2f")
total_freight_override = st.sidebar.number_input("Total freight (override, foreign) - leave 0 to use containers calc", min_value=0.0, value=0.0, format="%.2f")
# NEW: Clearing per consignment (LKR)
total_clearing = st.sidebar.number_input("Total clearing (LKR) - per consignment", min_value=0.0, value=0.0, format="%.2f")
# defaults for per-unit local charges (editable per-row)
st.sidebar.subheader("Per-unit local charge defaults (LKR/unit)")
installation_per_unit_default = st.sidebar.number_input("Installation per unit (LKR)", min_value=0.0, value=0.0, format="%.2f")
handling_per_unit_default = st.sidebar.number_input("Handling per unit (LKR)", min_value=0.0, value=0.0, format="%.2f")
protection_per_unit_default = st.sidebar.number_input("Protection per unit (LKR)", min_value=0.0, value=0.0, format="%.2f")

insurance_rate_global = st.sidebar.number_input("Default insurance rate (decimal)", value=0.003, format="%.6f")
fx_rate = st.sidebar.number_input("FX Rate (LKR per foreign unit)", value=307.0, format="%.4f")
st.sidebar.caption("Allocate freight & clearing by exworks-weighted ratio. Handling/installation/protection are per unit (qty * per_unit).")

# ---------- Allocate freight & clearing ----------
if st.sidebar.button("Allocate freight & clearing"):
    total_freight = total_freight_override if total_freight_override>0 else (num_containers * freight_per_container)
    # compute exworks per row
    exvals = np.array([float(r.get("Qty",0))*float(r.get("Unit ExWorks",0.0)) for r in st.session_state.products], dtype=float)
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
        # allocate clearing (total_clearing is in LKR) by same ratio, convert to LKR allocation
        if total_clearing > 0:
            sum_ex_total = exvals.sum()
            if sum_ex_total <= 0:
                # equal split if no exworks values
                per_cl = total_clearing / max(len(st.session_state.products),1)
                for r in st.session_state.products:
                    r["ClearingAlloc"] = per_cl
            else:
                for idx, r in enumerate(st.session_state.products):
                    ex = float(r.get("Qty",0))*float(r.get("Unit ExWorks",0.0))
                    r["ClearingAlloc"] = (ex / sum_ex_total) * total_clearing
        else:
            # ensure field exists (zero)
            for r in st.session_state.products:
                r["ClearingAlloc"] = float(r.get("ClearingAlloc",0.0))
        st.session_state.allocated = True
        st.sidebar.success("Freight and clearing allocated. Review row FreightAlloc & ClearingAlloc values.")

# ---------- Editable rows UI ----------
st.header("Enter product lines")
st.caption("Choose Product Type and enter Qty & Unit ExWorks. Per-unit local charges default to sidebar values; change per row if needed.")

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
    # manual freight override
    manual_flag = cols[4].checkbox("Override freight", value=bool(row.get("Freight Override",False)), key=f"ovr_{i}")
    manual_val = cols[5].number_input("Manual Freight", value=float(row.get("Manual Freight",0.0)), key=f"mf_{i}", format="%.2f")
    # Clearing allocation display (LKR)
    clearing_alloc = float(row.get("ClearingAlloc",0.0))
    cols[6].metric("ClearingAlloc (LKR)", f"{clearing_alloc:,.2f}")

    # per-unit local charge inputs (defaults from sidebar)
    cols2 = st.columns([1,1,1,1,1,1])
    inst_pu = cols2[0].number_input("Installation per unit (LKR)", value=float(row.get("Installation_per_unit", installation_per_unit_default)), key=f"instpu_{i}", format="%.2f")
    hand_pu = cols2[1].number_input("Handling per unit (LKR)", value=float(row.get("Handling_per_unit", handling_per_unit_default)), key=f"handpu_{i}", format="%.2f")
    prot_pu = cols2[2].number_input("Protection per unit (LKR)", value=float(row.get("Protection_per_unit", protection_per_unit_default)), key=f"protpu_{i}", format="%.2f")
    other_local = cols2[3].number_input("Other Local (LKR)", value=float(row.get("Other Local",0.0)), key=f"other_{i}", format="%.2f")
    contpct = cols2[4].number_input("Contingency %", value=float(row.get("Contingency %",0.03)), key=f"cont_{i}", format="%.4f")
    mrg = cols2[5].number_input("Desired margin", value=float(row.get("Desired Margin",0.20)), key=f"mrg_{i}", format="%.4f")

    # Row action buttons
    actc = st.columns([0.5,0.5])[1]
    with actc:
        if st.button("Delete", key=f"del_{i}"):
            st.session_state.products.pop(i)
            st.experimental_rerun()
        if st.button("Insert below", key=f"insrow_{i}"):
            st.session_state.products.insert(i+1, default_row())
            st.experimental_rerun()

    # write back row values
    st.session_state.products[i] = {
        "Product Type": pt,
        "HS Code": hs_val,
        "Qty": int(qty),
        "Unit ExWorks": float(ux),
        "Manual Freight": float(manual_val),
        "Freight Override": bool(manual_flag),
        "FreightAlloc": float(fr_alloc),
        "ClearingAlloc": float(clearing_alloc),
        "Installation_per_unit": float(inst_pu),
        "Handling_per_unit": float(hand_pu),
        "Protection_per_unit": float(prot_pu),
        "Other Local": float(other_local),
        "Contingency %": float(contpct),
        "Desired Margin": float(mrg),
        "Insurance Rate": float(row.get("Insurance Rate", insurance_rate_global))
    }
    st.markdown("---")

# ---------- Compute rows ----------
def compute_rows(df_in, tariff, fx_rate):
    df = pd.DataFrame(df_in).copy()
    # ensure columns exist
    expected = ["Product Type","HS Code","Qty","Unit ExWorks","FreightAlloc","Manual Freight","Freight Override","ClearingAlloc",
                "Installation_per_unit","Handling_per_unit","Protection_per_unit","Other Local","Contingency %","Desired Margin","Insurance Rate"]
    for c in expected:
        if c not in df.columns:
            df[c] = 0.0
    # numeric convert
    num_cols = [c for c in expected if c not in ["Product Type","HS Code"]]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
    # effective freight (use manual if override)
    df["Freight_effective"] = np.where(df["Freight Override"], df["Manual Freight"], df["FreightAlloc"])
    # merge tariffs
    merged = df.merge(tariff, how="left", left_on="Product Type", right_on="Product Type", suffixes=("","_tariff"))
    merged["HS Code"] = merged["HS Code"].fillna(merged.get("HS Code_tariff",""))
    for rate_col in ["Duty %","PAL %","CESS %","Excise %","SSCL %","VAT %"]:
        merged[rate_col] = pd.to_numeric(merged.get(rate_col,0.0), errors='coerce').fillna(0.0)
    # totals for per-unit charges
    merged["Installation_total_LKR"] = merged["Installation_per_unit"] * merged["Qty"]
    merged["Handling_total_LKR"] = merged["Handling_per_unit"] * merged["Qty"]
    merged["Protection_total_LKR"] = merged["Protection_per_unit"] * merged["Qty"]
    # Local charges sum (note: ClearingAlloc already in LKR)
    merged["Total_Local_charges"] = merged[["Installation_total_LKR","Handling_total_LKR","Protection_total_LKR","Other Local"]].sum(axis=1)
    # foreign calculations
    merged["Total ExWorks_foreign"] = merged["Qty"] * merged["Unit ExWorks"]
    merged["Insurance_foreign"] = (merged["Total ExWorks_foreign"] + merged["Freight_effective"]) * merged["Insurance Rate"]
    merged["CIF_foreign"] = merged["Total ExWorks_foreign"] + merged["Freight_effective"] + merged["Insurance_foreign"]
    # Duties
    merged["Duty_foreign"] = merged["Duty %"] * merged["CIF_foreign"]
    merged["PAL_foreign"]  = merged["PAL %"] * merged["CIF_foreign"]
    merged["CESS_foreign"] = merged["CESS %"] * merged["CIF_foreign"]
    # Excise/SSCL/VAT per your formula
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
    # Convert to LKR
    for col in ["CIF","Duty","PAL","CESS","Excise","SSCL","VAT"]:
        merged[f"{col}_LKR"] = merged[f"{col}_foreign"] * fx_rate
    # Contingency in LKR = contingency % * exworks_foreign * fx_rate
    merged["Contingency_LKR"] = merged["Contingency %"] * merged["Total ExWorks_foreign"] * fx_rate
    # Total landed (include ClearingAlloc in LKR)
    merged["Total_Landed_LKR"] = merged[["CIF_LKR","Duty_LKR","PAL_LKR","CESS_LKR","Excise_LKR","SSCL_LKR","VAT_LKR"]].sum(axis=1) \
                                + merged["Total_Local_charges"] + merged["ClearingAlloc"] + merged["Contingency_LKR"]
    merged["Cost_per_unit_LKR"] = merged["Total_Landed_LKR"] / merged["Qty"].replace(0,1)
    merged["Price_markup"] = merged["Cost_per_unit_LKR"] * (1 + merged["Desired Margin"])
    merged["Price_margin_style"] = merged["Cost_per_unit_LKR"] / (1 - merged["Desired Margin"].replace(0, np.nan))
    return merged

# ---------- Compute button ----------
if st.sidebar.button("Compute landed costs for rows"):
    # if not allocated, perform default allocation automatically (so user doesn't forget)
    if not st.session_state.allocated:
        st.sidebar.info("Allocating freight & clearing using current settings (auto).")
        # call allocation logic quickly
        total_freight = total_freight_override if total_freight_override>0 else (num_containers * freight_per_container)
        exvals = np.array([float(r.get("Qty",0))*float(r.get("Unit ExWorks",0.0)) for r in st.session_state.products], dtype=float)
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
                    r["ClearingAlloc"] = per_cl
            else:
                for idx, r in enumerate(st.session_state.products):
                    ex = float(r.get("Qty",0))*float(r.get("Unit ExWorks",0.0))
                    r["ClearingAlloc"] = (ex / sum_ex_total) * total_clearing
        st.session_state.allocated = True

    df_products = pd.DataFrame(st.session_state.products)
    results = compute_rows(df_products, tariff_df, fx_rate)
    st.session_state.results = results
    st.success(f"Computed {len(results)} rows.")

# ---------- Show results & formatted display ----------
if "results" in st.session_state:
    st.header("Results")
    # columns to show in numeric raw form for download
    download_cols = ["Product Type","HS Code","Qty","Unit ExWorks","Freight_effective","ClearingAlloc","CIF_LKR","Duty_LKR","PAL_LKR","CESS_LKR","Excise_LKR","SSCL_LKR","VAT_LKR","Installation_total_LKR","Handling_total_LKR","Protection_total_LKR","Total_Local_charges","Contingency_LKR","Total_Landed_LKR","Cost_per_unit_LKR","Price_markup","Price_margin_style"]
    present = [c for c in download_cols if c in st.session_state.results.columns]
    # prepare a formatted dataframe for display (commas & 2 decimals)
    disp = st.session_state.results[present].copy()
    for c in disp.columns:
        if c not in ["Product Type","HS Code","Qty"]:
            disp[c] = disp[c].apply(lambda x: f"{x:,.2f}")
    st.dataframe(disp.reset_index(drop=True), use_container_width=True)

    # downloads (raw numbers)
    csv = st.session_state.results[present].to_csv(index=False).encode('utf-8')
    st.download_button("Download results CSV", data=csv, file_name="costing_results.csv")

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        st.session_state.results.to_excel(writer, index=False, sheet_name="FullResults")
    st.download_button("Download full Excel", data=output.getvalue(), file_name="full_costing.xlsx")

st.caption("Tip: Enter exworks and quantities, set containers & freight per container and total clearing, click 'Allocate freight & clearing', then compute landed costs.")
