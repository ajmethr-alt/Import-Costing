import streamlit as st
import pandas as pd
import numpy as np
from pathlib import Path

st.set_page_config(layout="wide", page_title="Import Cost Calculator (Sri Lanka)")

st.title("Import Cost Calculator — (Preloaded with your workbook)")

# Default workbook path (bundled) - place your workbook in same folder and name it Tariff_and_Costing.xlsx
DEFAULT_WB = "Tariff_and_Costing.xlsx"

st.sidebar.header("Workbook & Tariff Table")
uploaded = st.sidebar.file_uploader("Upload your workbook (optional, will override bundled file)", type=['xlsx','xls'])
wb_path = None
if uploaded is not None:
    wb_path = uploaded
    st.sidebar.success("Uploaded workbook will be used for this session.")
else:
    wb_path = DEFAULT_WB
    st.sidebar.info(f"Using bundled workbook: {DEFAULT_WB}")

# Load tariff table from workbook
def load_tariff(wb):
    try:
        df = pd.read_excel(wb, sheet_name='TariffTable')
        # normalize headers
        df.columns = [str(c).strip() for c in df.columns]
        expected = ['Product Type','HS Code','Duty %','PAL %','CESS %','Excise %','SSCL %','VAT %']
        # Try to map if headers differ
        if not all(x in df.columns for x in expected):
            mapping = {}
            for c in df.columns:
                lc = c.lower()
                if 'product' in lc and 'type' in lc:
                    mapping[c] = 'Product Type'
                elif 'hs' in lc:
                    mapping[c] = 'HS Code'
                elif 'duty' in lc:
                    mapping[c] = 'Duty %'
                elif 'pal' in lc or 'port' in lc:
                    mapping[c] = 'PAL %'
                elif 'cess' in lc:
                    mapping[c] = 'CESS %'
                elif 'excise' in lc:
                    mapping[c] = 'Excise %'
                elif 'sscl' in lc or 'social' in lc:
                    mapping[c] = 'SSCL %'
                elif 'vat' in lc:
                    mapping[c] = 'VAT %'
            df = df.rename(columns=mapping)
        # fill missing columns
        for col in expected:
            if col not in df.columns:
                df[col] = 0.0
        return df[expected]
    except Exception as e:
        st.error(f"Failed to load TariffTable from workbook: {e}")
        return pd.DataFrame(columns=['Product Type','HS Code','Duty %','PAL %','CESS %','Excise %','SSCL %','VAT %'])

tariff_df = load_tariff(wb_path)

st.sidebar.subheader("Tariff preview (first 10 rows)")
st.sidebar.dataframe(tariff_df.head(10))

# ---- Input form ----
st.header("Input per product line")
col1, col2 = st.columns([2,3])

with col1:
    product_type = st.selectbox("Product Type", options=tariff_df["Product Type"].unique())
    if product_type and product_type in list(tariff_df["Product Type"].values):
        hs_row = tariff_df[tariff_df["Product Type"] == product_type].iloc[0]
        st.write("HS Code:", hs_row["HS Code"])
        st.write("Duty %:", float(hs_row["Duty %"]))
        st.write("PAL %:", float(hs_row["PAL %"]))
        st.write("CESS %:", float(hs_row["CESS %"]))
        st.write("Excise %:", float(hs_row.get("Excise %", 0.0)))
        st.write("SSCL %:", float(hs_row["SSCL %"]))
        st.write("VAT %:", float(hs_row["VAT %"]))
    else:
        hs_row = {c:0 for c in ['HS Code','Duty %','PAL %','CESS %','Excise %','SSCL %','VAT %']}

with col2:
    qty = st.number_input("Quantity (units)", value=1, min_value=1)
    unit_exworks = st.number_input("Unit Ex-Works (foreign currency)", value=100.0, format="%.2f")
    freight_total = st.number_input("Freight attributable to this line (foreign currency) - optional", value=0.0, format="%.2f")
    insurance_rate = st.number_input("Insurance rate (decimal, default 0.003 = 0.3%)", value=0.003, format="%.6f")
    incoterm = st.selectbox("Incoterm (affects duty base)", ["CIF","EXW"])
    fx_rate = st.number_input("Exchange rate (LKR per foreign unit) — FX", value=307.0, format="%.4f")
    # local charges
    st.subheader("Local charges (LKR)")
    installation = st.number_input("Installation (LKR)", value=0.0, format="%.2f")
    contingency_pct = st.number_input("Contingency % (decimal, e.g. 0.03)", value=0.03, format="%.4f")
    clearing = st.number_input("Clearing (LKR)", value=0.0, format="%.2f")
    handling = st.number_input("Handling (LKR)", value=0.0, format="%.2f")
    protection = st.number_input("Protection (LKR)", value=0.0, format="%.2f")
    other_local = st.number_input("Other local charges (LKR)", value=0.0, format="%.2f")
    desired_margin = st.number_input("Desired margin (decimal, e.g. 0.20)", value=0.20, format="%.4f")

# ---- Core calculations ----
st.header("Calculated results")

total_exworks_foreign = qty * unit_exworks
insurance_amount_foreign = (total_exworks_foreign + freight_total) * insurance_rate
CIF_foreign = total_exworks_foreign + freight_total + insurance_amount_foreign

duty_pct = float(hs_row["Duty %"])
pal_pct = float(hs_row["PAL %"])
cess_pct = float(hs_row["CESS %"])
excise_pct = float(hs_row.get("Excise %", 0.0))
sscl_pct = float(hs_row["SSCL %"])
vat_pct = float(hs_row["VAT %"])

duty_foreign = duty_pct * CIF_foreign
pal_foreign  = pal_pct * CIF_foreign
cess_foreign = cess_pct * CIF_foreign

excise_foreign = 0.0
if excise_pct and excise_pct > 0:
    excise_foreign = excise_pct * ((CIF_foreign * 1.15) + duty_foreign + pal_foreign + cess_foreign)

sscl_foreign = 0.0
if sscl_pct and sscl_pct > 0:
    sscl_foreign = sscl_pct * ((CIF_foreign * 1.10) + duty_foreign + pal_foreign + cess_foreign + excise_foreign)

vat_foreign = 0.0
if vat_pct and vat_pct > 0:
    vat_foreign = vat_pct * ((CIF_foreign * 1.15) + duty_foreign + pal_foreign + cess_foreign + excise_foreign + sscl_foreign)

CIF_LKR = CIF_foreign * fx_rate
duty_LKR = duty_foreign * fx_rate
pal_LKR = pal_foreign * fx_rate
cess_LKR = cess_foreign * fx_rate
excise_LKR = excise_foreign * fx_rate
sscl_LKR = sscl_foreign * fx_rate
vat_LKR = vat_foreign * fx_rate

total_local_charges = installation + clearing + handling + protection + other_local
contingency_LKR = contingency_pct * total_exworks_foreign * fx_rate

total_landed_LKR = CIF_LKR + duty_LKR + pal_LKR + cess_LKR + excise_LKR + sscl_LKR + vat_LKR + total_local_charges + contingency_LKR

cost_per_unit_LKR = total_landed_LKR / qty

price_markup = cost_per_unit_LKR * (1 + desired_margin)
price_margin_style = cost_per_unit_LKR / (1 - desired_margin)

st.subheader("Foreign currency (per line)")
st.write(f"Total Ex-Works (foreign): {total_exworks_foreign:,.2f}")
st.write(f"Freight (foreign): {freight_total:,.2f}")
st.write(f"Insurance (foreign): {insurance_amount_foreign:,.2f}")
st.write(f"CIF (foreign): {CIF_foreign:,.2f}")

st.subheader("Duties/levies (foreign currency)")
st.write(f"Duty: {duty_foreign:,.2f}")
st.write(f"PAL: {pal_foreign:,.2f}")
st.write(f"CESS: {cess_foreign:,.2f}")
st.write(f"Excise: {excise_foreign:,.2f}")
st.write(f"SSCL: {sscl_foreign:,.2f}")
st.write(f"VAT: {vat_foreign:,.2f}")

st.subheader("Converted to LKR / Local charges")
st.write(f"CIF (LKR): {CIF_LKR:,.2f}")
st.write(f"Duty (LKR): {duty_LKR:,.2f}")
st.write(f"PAL (LKR): {pal_LKR:,.2f}")
st.write(f"CESS (LKR): {cess_LKR:,.2f}")
st.write(f"Excise (LKR): {excise_LKR:,.2f}")
st.write(f"SSCL (LKR): {sscl_LKR:,.2f}")
st.write(f"VAT (LKR): {vat_LKR:,.2f}")
st.write(f"Contingency (LKR): {contingency_LKR:,.2f}")
st.write(f"Other local charges total (LKR): {total_local_charges:,.2f}")

st.subheader("Totals & Pricing")
st.write(f"Total Landed Cost (LKR): {total_landed_LKR:,.2f}")
st.write(f"Cost per unit (LKR): {cost_per_unit_LKR:,.2f}")
st.write(f"Price per unit (markup on cost): {price_markup:,.2f}")
st.write(f"Price per unit (margin of selling price): {price_margin_style:,.2f}")

if st.button("Export result to CSV"):
    out = {
        "Product Type":[product_type],
        "HS Code":[hs_row["HS Code"]],
        "Qty":[qty],
        "Unit Exworks":[unit_exworks],
        "Total Exworks (foreign)":[total_exworks_foreign],
        "CIF (foreign)":[CIF_foreign],
        "Total Landed (LKR)":[total_landed_LKR],
        "Cost per unit (LKR)":[cost_per_unit_LKR],
        "Price_markup":[price_markup],
        "Price_margin_style":[price_margin_style]
    }
    df_out = pd.DataFrame(out)
    st.download_button("Download CSV", data=df_out.to_csv(index=False), file_name="costing_result.csv")
