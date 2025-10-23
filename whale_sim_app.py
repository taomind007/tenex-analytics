import math
import numpy as np
import pandas as pd
import streamlit as st

import bittensor as bt

DAILY_BLOCKS = 7200
MINER_EMISSION_SHARE = 0.41
BUYBACK_START_TAO = 20.0
BUYBACK_INCREMENT_PER_DAY = 0.5

DEFAULT_SUBNET = 67
DEFAULT_NETWORK = "finney"

@st.cache_data(show_spinner=False)
def fetch_reserves(network: str = DEFAULT_NETWORK, subnet_id: int = DEFAULT_SUBNET) -> tuple[float, float]:
    subtensor = bt.subtensor(network=network)
    subnet = subtensor.subnet(subnet_id)
    tao_in = float(subnet.tao_in)
    alpha_in = float(subnet.alpha_in)
    return max(1.0, tao_in), max(1.0, alpha_in)

def amm_swap_xy(x_reserve: float, y_reserve: float, dx: float) -> tuple[float, float, float]:
    if dx <= 0:
        return 0.0, x_reserve, y_reserve
    k = x_reserve * y_reserve
    new_x = x_reserve + dx
    new_y = k / new_x
    dy_out = y_reserve - new_y
    return dy_out, new_x, new_y

def simulate(days: int,
             tao_reserve_init: float,
             alpha_reserve_init: float,
             whale_daily_buy_tao: float,
             buy_days: int,
             include_buyback: bool) -> pd.DataFrame:
    records = []
    tao_r = float(tao_reserve_init)
    alpha_r = float(alpha_reserve_init)
    whale_alpha_holdings = 0.0
    whale_tao_spent_cum = 0.0

    for d in range(days):
        price = tao_r / alpha_r

        in_buy_phase = (whale_daily_buy_tao > 0 and d < max(0, buy_days))
        if in_buy_phase:
            dy, tao_r, alpha_r = amm_swap_xy(tao_r, alpha_r, whale_daily_buy_tao)
            whale_alpha_holdings += dy
            whale_tao_spent_cum += whale_daily_buy_tao

            counter_alpha_sell = 0.25 * whale_daily_buy_tao / max(price, 1e-12)
            if counter_alpha_sell > 0:
                dy_out, new_alpha_r, new_tao_r = amm_swap_xy(alpha_r, tao_r, counter_alpha_sell)
                alpha_r = new_alpha_r
                tao_r = new_tao_r

        buyback_tao = BUYBACK_START_TAO + BUYBACK_INCREMENT_PER_DAY * d
        if include_buyback and buyback_tao > 0:
            dy_buyback, tao_r, alpha_r = amm_swap_xy(tao_r, alpha_r, buyback_tao)

        emission_factor = 0.5 if d >= 60 else 1.0
        alpha_r += float(DAILY_BLOCKS) * emission_factor
        tao_r += float(DAILY_BLOCKS) * price * emission_factor

        dynamic_burn = max(0.5 - 0.01 * d, 0.3)
        miner_alpha_sell = float(DAILY_BLOCKS) * MINER_EMISSION_SHARE * dynamic_burn
        if miner_alpha_sell > 0:
            dy_out, new_alpha_r, new_tao_r = amm_swap_xy(alpha_r, tao_r, miner_alpha_sell)
            alpha_r = new_alpha_r
            tao_r = new_tao_r

        if whale_alpha_holdings > 0:
            k_val = alpha_r * tao_r
            new_alpha_tmp = alpha_r + whale_alpha_holdings
            new_tao_tmp = k_val / max(new_alpha_tmp, 1e-12)
            whale_tao_value = max(tao_r - new_tao_tmp, 0.0)
        else:
            whale_tao_value = 0.0

        records.append({
            "day": d,
            "price": tao_r / alpha_r,
            "tao_reserve": tao_r,
            "alpha_reserve": alpha_r,
            "whale_alpha": whale_alpha_holdings,
            "whale_tao_spent": whale_tao_spent_cum,
            "whale_tao_value": whale_tao_value
        })

    return pd.DataFrame.from_records(records)


st.set_page_config(page_title="Whale Simulation", layout="wide")
st.title("Whale actions simulation")

with st.sidebar:
    tao0, alpha0 = fetch_reserves()

    st.header("Simulation params")
    days = st.slider("Days", 1, 180, 120, 1)

    st.subheader("Whale actions (DCA)")
    whale_daily_buy_tao = st.number_input("Whale daily buy (TAO)", min_value=0.0, value=300.0, step=5.0, format="%.0f")
    buy_days = st.number_input("Buy over N days", min_value=0, max_value=365, value=10, step=1)
    include_buyback = st.checkbox("With protocol buyback", value=True)

df = simulate(
    days=days,
    tao_reserve_init=tao0,
    alpha_reserve_init=alpha0,
    whale_daily_buy_tao=whale_daily_buy_tao,
    buy_days=buy_days,
    include_buyback=include_buyback
)

st.subheader("Summary")
col1, col2, col3, col4 = st.columns(4)

orig_tao_spent = buy_days * whale_daily_buy_tao
buy_end_day = int(max(0, buy_days) - 1)
def _amm_value(alpha_amount: float, alpha_res: float, tao_res: float) -> float:
    if alpha_amount <= 0:
        return 0.0
    k = alpha_res * tao_res
    new_alpha = alpha_res + alpha_amount
    new_tao = k / max(new_alpha, 1e-12)
    dy_out = tao_res - new_tao
    return max(dy_out, 0.0)

if 0 <= buy_end_day < len(df):
    alpha_bought = float(df.loc[df.day == buy_end_day, "whale_alpha"].values[0])
    alpha_res_end = float(df.loc[df.day == buy_end_day, "alpha_reserve"].values[0])
    tao_res_end = float(df.loc[df.day == buy_end_day, "tao_reserve"].values[0])
    value_at_end = _amm_value(alpha_bought, alpha_res_end, tao_res_end)
    day_30 = min(len(df) - 1, buy_end_day + 30)
    day_60 = min(len(df) - 1, buy_end_day + 60)
    alpha_res_30 = float(df.loc[df.day == day_30, "alpha_reserve"].values[0])
    tao_res_30 = float(df.loc[df.day == day_30, "tao_reserve"].values[0])
    alpha_res_60 = float(df.loc[df.day == day_60, "alpha_reserve"].values[0])
    tao_res_60 = float(df.loc[df.day == day_60, "tao_reserve"].values[0])
    value_30 = _amm_value(alpha_bought, alpha_res_30, tao_res_30)
    value_60 = _amm_value(alpha_bought, alpha_res_60, tao_res_60)
    day_120 = min(len(df) - 1, buy_end_day + 120)
    alpha_res_120 = float(df.loc[df.day == day_120, "alpha_reserve"].values[0])
    tao_res_120 = float(df.loc[df.day == day_120, "tao_reserve"].values[0])
    value_120 = _amm_value(alpha_bought, alpha_res_120, tao_res_120)
else:
    value_at_end = 0.0
    value_30 = 0.0
    value_60 = 0.0
    value_120 = 0.0

row2c1, row2c2, row2c3, row2c4, row2c5 = st.columns(5)
row2c1.metric("Original TAO spent", f"{orig_tao_spent:.0f} τ")
row2c2.metric("Value at buy end", f"{value_at_end:.0f} τ")
row2c3.metric("Value after 30 days", f"{value_30:.0f} τ")
row2c4.metric("Value after 60 days", f"{value_60:.0f} τ")
row2c5.metric("Value after 120 days", f"{value_120:.0f} τ")

st.subheader("Charts")
st.line_chart(df.set_index("day")["price"], height=220)

st.subheader("Raw data")
display_df = df.drop(columns=["whale_alpha"]) if "whale_alpha" in df.columns else df
st.dataframe(display_df, use_container_width=True)
