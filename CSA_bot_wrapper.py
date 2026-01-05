import pandas as pd
from CSA import CSA
import os

def run_csa_analysis_for_bot(pairs):
    """
    Run CSA analysis for given pairs.
    Returns summary string and Excel file path.
    """
    if not pairs:
        pairs = ["BTC-USD", "ETH-USD"]  # default fallback

    csa = CSA(pairs)
    csa.run()  # generates CSA_Hourly_24_Report.xlsx

    report_path = "CSA_Hourly_24_Report.xlsx"
    if not os.path.exists(report_path):
        raise FileNotFoundError("CSA report not found.")

    # Load the final dataframe
    df = pd.read_excel(report_path)
    last_row = df.iloc[-1]

    # Build simplified summary
    summary = (
        f"📊 CSA 24H Human-Like Confluence Analysis\n\n"
        f"🕒 Session: {last_row['session']}\n"
        f"📈 Breakout Direction: {last_row['breakout direction']}\n"
        f"📐 Breakout Strength: {last_row['breakout strength']}\n"
        f"💧 Liquidity Transfer: {last_row['liquidity transfer']}\n"
        f"🎯 CSA Confidence: {last_row['CSA Confidence']}\n"
        f"🔔 Signal: {last_row['Signal']}"
    )

    return summary, report_path
