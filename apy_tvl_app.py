import math
import numpy as np
import streamlit as st

import bittensor as bt

def _format_percent_from_decimal(value: float, decimals: int = 4) -> str:
    s = f"{value * 100:.{decimals}f}".rstrip("0").rstrip(".")
    return s + "%"

def _format_percent_value(value: float, decimals: int = 2) -> str:
    s = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return s + "%"

DAILY_BLOCKS = 7200
MINER_EMISSION_SHARE = 0.41
EPOCHS_PER_DAY = 20
BASE_TRADING_FEE = 0.003
BASE_BORROWING_FEE = 0.00005
KINK = 0.8
SLOPE1 = 0.00015
SLOPE2 = 0.0008
LP_FEE_SHARE = 0.875
TRADING_FEE_SHARE = 0.3
BORROWING_FEE_SHARE = 0.35

DEFAULT_SUBNET = 67
DEFAULT_NETWORK = "finney"

@st.cache_data(show_spinner=False)
def fetch_price(network: str = DEFAULT_NETWORK, subnet_id: int = DEFAULT_SUBNET) -> float:
    subtensor = bt.subtensor(network=network)
    subnet = subtensor.subnet(subnet_id)
    tao_in = float(subnet.tao_in)
    alpha_in = float(subnet.alpha_in)
    if alpha_in == 0:
        return 1.0
    return tao_in / alpha_in

def compute_daily_rewards(
    tvl: float,
    turnover_rate: float,
    utilization_rate: float,
    price: float,
    burn_percentage: float,
) -> tuple[float, float, float]:
    daily_lp_trading_fee_reward = (
        tvl * turnover_rate * BASE_TRADING_FEE * 2 * TRADING_FEE_SHARE * LP_FEE_SHARE
    )
    borrow_rate_component = (
        BASE_BORROWING_FEE + (utilization_rate * SLOPE1) / KINK
        if utilization_rate <= KINK
        else BASE_BORROWING_FEE + SLOPE1 + ((utilization_rate - KINK) * SLOPE2) / (1.0 - KINK)
    )
    daily_lp_borrowing_fee_reward = (
        tvl * utilization_rate * borrow_rate_component * BORROWING_FEE_SHARE * LP_FEE_SHARE * EPOCHS_PER_DAY
    )

    lp_emission_share_effective = max(0.0, min(1.0, 1.0 - (burn_percentage / 100.0)))
    daily_miner_emission = price * DAILY_BLOCKS * MINER_EMISSION_SHARE * lp_emission_share_effective

    daily_lp_fee_reward = daily_lp_trading_fee_reward + daily_lp_borrowing_fee_reward
    daily_lp_reward = daily_lp_fee_reward + daily_miner_emission
    return daily_lp_trading_fee_reward, daily_lp_borrowing_fee_reward, daily_lp_reward

def compute_apr_apy(daily_reward: float, tvl: float) -> tuple[float, float]:
    if tvl <= 0:
        return 0.0, 0.0
    apr = (daily_reward / tvl) * 365.0
    apy = (1.0 + daily_reward / tvl) ** 365.0 - 1.0
    return apr, apy


st.set_page_config(page_title="APY vs TVL Explorer", layout="centered")
st.title("APY vs TVL Explorer")
st.caption("Interactively explore APY across TVL with turnover and utilization controls.")

base_price = fetch_price()

with st.sidebar:
    st.header("Simulation params")
    price_input = st.slider(
        "Alpha price", 0.0, 0.1, min(max(base_price, 0.0), 0.1), 0.0001, format="%.4f"
    )
    burn_percentage = st.slider("Burn percentage", 0.0, 100.0, 0.0, 0.1, format="%.1f%%")
    turnover_rate = st.slider("Turnover rate (per day)", 0.0, 5.0, 1.0, 0.1)
    utilization_rate = st.slider("Utilization rate", 0.0, 1.0, 0.5, 0.01)

    st.subheader("TVL Range")
    min_tvl = st.number_input("Min TVL", min_value=1.0, value=5_000.0, step=1_000.0, format="%.0f")
    max_tvl = st.number_input("Max TVL", min_value=min_tvl + 1.0, value=100_000.0, step=10_000.0, format="%.0f")
    points = st.slider("Resolution (points)", 50, 500, 100, 10)

if min_tvl <= 0:
    min_tvl = 1.0
tvl_values = np.linspace(min_tvl, max_tvl, points)

apy_values = []
apr_values = []
for tvl in tvl_values:
    _, _, daily_reward = compute_daily_rewards(
        tvl=tvl,
        turnover_rate=turnover_rate,
        utilization_rate=utilization_rate,
        price=price_input,
        burn_percentage=burn_percentage,
    )
    apr, apy = compute_apr_apy(daily_reward, tvl)
    apr_values.append(apr)
    apy_values.append(apy)

st.subheader("APY vs TVL")
chart_data = {
    "TVL": tvl_values,
    "APY": np.array(apy_values) * 100.0,
    "APR": np.array(apr_values) * 100.0,
}

st.line_chart(chart_data, x="TVL", y=["APY", "APR"])

st.subheader("Point inspection")
inspect_tvl = st.number_input("Inspect TVL", min_value=float(min_tvl), max_value=float(max_tvl), value=float(min_tvl), step=max(1.0, (max_tvl - min_tvl) / 100.0), format="%.0f")
trading_fee_r_point, borrowing_fee_r_point, daily_reward_point = compute_daily_rewards(
    tvl=inspect_tvl,
    turnover_rate=turnover_rate,
    utilization_rate=utilization_rate,
    price=price_input,
    burn_percentage=burn_percentage,
)
apr_point, apy_point = compute_apr_apy(daily_reward_point, inspect_tvl)
daily_fee_reward_point = trading_fee_r_point + borrowing_fee_r_point
daily_miner_emission_point = price_input * DAILY_BLOCKS * MINER_EMISSION_SHARE * max(0.0, min(1.0, 1.0 - burn_percentage / 100.0))

row1_col1, row1_col2 = st.columns(2)
row1_col1.metric("APR", f"{apr_point*100:.2f}%")
row1_col2.metric("APY", f"{apy_point*100:.2f}%")

row2_col1, row2_col2, row2_col3 = st.columns(3)
row2_col1.metric("Total Daily Reward", f"{daily_reward_point:.2f} τ")
row2_col2.metric("Daily miner emission", f"{daily_miner_emission_point:.2f} τ")
row2_col3.metric("Daily fee reward", f"{daily_fee_reward_point:.2f} τ")

st.subheader("Constants")
st.markdown(
    f"- `base_trading_fee`: {_format_percent_from_decimal(BASE_TRADING_FEE)}\n"
    f"- `base_borrowing_fee`: {_format_percent_from_decimal(BASE_BORROWING_FEE)}\n"
    f"- `kink`: {_format_percent_from_decimal(KINK, 2)} utilization\n"
    f"- `slope1`: {_format_percent_from_decimal(SLOPE1)}\n"
    f"- `slope2`: {_format_percent_from_decimal(SLOPE2)}\n"
    f"- `lp_fee_share`: {_format_percent_from_decimal(LP_FEE_SHARE, 2)}\n"
    f"- `trading_fee_share`: {_format_percent_from_decimal(TRADING_FEE_SHARE, 2)}\n"
    f"- `borrowing_fee_share`: {_format_percent_from_decimal(BORROWING_FEE_SHARE, 2)}"
)
