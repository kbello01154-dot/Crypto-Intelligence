import pandas as pd
import numpy as np
import yfinance as yf
import sys

# ============================================================
# ETF CONFIGURATION MAP
# ============================================================
ETF_MAP = {
    "BTC-USD": {
        "spot_etfs": ["IBIT", "FBTC", "GBTC", "BITB"],
        "flow_file": "data/btc_etf_flows.csv"
    },
    "ETH-USD": {
        "spot_etfs": ["ETHA", "ETHE"],
        "flow_file": "data/eth_etf_flows.csv"
    }
}

# ============================================================
# MARKET DATA ENGINE (DAILY)
# ============================================================
class MarketData:
    def __init__(self, symbols):
        self.symbols = symbols
        self.data = {}

    def download(self, start, end):
        for s in self.symbols:
            df = yf.download(
                s,
                start=start,
                end=end,
                interval="1d",
                auto_adjust=False
            )
            df = df[['Open','High','Low','Close','Volume']]
            df.columns = ['open','high','low','close','volume']
            df = df.reset_index()
            df.rename(columns={df.columns[0]: 'date'}, inplace=True)
            self.data[s] = df.dropna()

# ============================================================
# FLOW ENGINE (LOCAL CSV – SOURCE OF TRUTH)
# ============================================================
class LocalETFFlowEngine:
    def __init__(self, path):
        self.path = path

    def load(self):
        df = pd.read_csv(self.path)
        df.columns = [c.strip() for c in df.columns]

        date_col = [c for c in df.columns if "date" in c.lower()][0]
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.set_index(date_col).sort_index()

        for c in df.columns:
            df[c] = (
                df[c].astype(str)
                .str.replace(",", "", regex=False)
                .str.replace("–", "0", regex=False)
                .str.replace("-", "0", regex=False)
            )
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

        total_cols = [c for c in df.columns if "total" in c.lower()]
        df['NetFlow'] = df[total_cols[0]] if total_cols else df.sum(axis=1)

        return df[['NetFlow']]

# ============================================================
# FLOW ANALYTICS (SHORT-SAMPLE SAFE)
# ============================================================
class FlowAnalytics:
    @staticmethod
    def enrich(df):
        # Use ONLY available history
        df['FlowPersistence'] = df['NetFlow'].rolling(
            window=min(5, len(df)),
            min_periods=2
        ).sum()

        mean = df['FlowPersistence'].expanding().mean()
        std = df['FlowPersistence'].expanding().std().replace(0, 1e-9)

        df['FlowZ'] = (df['FlowPersistence'] - mean) / std

        df['FlowRegime'] = np.select(
            [
                df['FlowZ'] > 0.5,
                df['FlowZ'] < -0.5
            ],
            ["Accumulation", "Distribution"],
            default="Neutral"
        )

        return df

# ============================================================
# ETF STRUCTURE ENGINE (SHORT WINDOW)
# ============================================================
class ETFStructureEngine:
    def compute(self, df):
        nav = df['close'].rolling(
            window=min(3, len(df)),
            min_periods=1
        ).mean()

        premium = (df['close'] - nav) / nav
        stability = premium.expanding().std().fillna(0)

        return premium.clip(-0.05, 0.05), stability

# ============================================================
# LIQUIDITY ENGINE (RELATIVE ONLY)
# ============================================================
class LiquidityEngine:
    def compute(self, df):
        spread = (df['high'] - df['low']) / df['close']
        depth = df['volume'] / df['volume'].expanding().mean()

        raw_liquidity = depth / (spread + 1e-6)

        liq_norm = raw_liquidity / raw_liquidity.expanding().mean()
        liq_norm = liq_norm.clip(0, 3)

        trend = np.where(
            liq_norm > liq_norm.expanding().mean(),
            "Expanding",
            "Contracting"
        )

        return liq_norm, trend

# ============================================================
# MARKET REGIME CLASSIFIER (CONTEXT ONLY)
# ============================================================
class MarketRegimeEngine:
    def classify(
        self,
        flow_regime,
        rel_flow,
        premium,
        liquidity_trend
    ):
        if flow_regime == "Accumulation" and liquidity_trend == "Expanding":
            return "Risk-On"

        if flow_regime == "Distribution" and premium < 0:
            return "Risk-Off"

        if abs(rel_flow) > 1.0:
            return "Rotation"

        return "Neutral"

# ============================================================
# CONTROLLER
# ============================================================
class ETF_Market_Regime:
    def __init__(self, pair):
        if pair not in ETF_MAP:
            raise ValueError("Unsupported pair")

        self.pair = pair
        self.cfg = ETF_MAP[pair]
        self.market = MarketData(self.cfg['spot_etfs'])

    def run(self):
        # Load and enrich flows
        flows = FlowAnalytics.enrich(
            LocalETFFlowEngine(self.cfg['flow_file']).load()
        ).shift(1)  # T+1 alignment

        start = flows.index.min()
        end = flows.index.max() + pd.Timedelta(days=1)

        self.market.download(start, end)

        other = "ETH-USD" if self.pair == "BTC-USD" else "BTC-USD"
        other_flows = FlowAnalytics.enrich(
            LocalETFFlowEngine(ETF_MAP[other]['flow_file']).load()
        ).shift(1)

        base_etf = self.cfg['spot_etfs'][0]
        df = self.market.data[base_etf].copy()

        df = df.merge(flows, left_on='date', right_index=True, how='inner')
        df = df.merge(
            other_flows[['FlowZ']],
            left_on='date',
            right_index=True,
            how='left',
            suffixes=('', '_Other')
        )

        df.fillna(0, inplace=True)

        struct = ETFStructureEngine()
        liq = LiquidityEngine()
        regime_engine = MarketRegimeEngine()

        premium, prem_stab = struct.compute(df)
        liquidity, liq_trend = liq.compute(df)

        df['Premium'] = premium
        df['Liquidity'] = liquidity
        df['Liquidity_Trend'] = liq_trend
        df['Relative_Flow'] = df['FlowZ'] - df['FlowZ_Other']

        df['Market_Condition'] = [
            regime_engine.classify(
                df.iloc[i]['FlowRegime'],
                df.iloc[i]['Relative_Flow'],
                df.iloc[i]['Premium'],
                df.iloc[i]['Liquidity_Trend']
            )
            for i in range(len(df))
        ]

        out = df[
            [
                'date',
                'NetFlow',
                'FlowRegime',
                'Relative_Flow',
                'Premium',
                'Liquidity',
                'Liquidity_Trend',
                'Market_Condition'
            ]
        ]

        # -----------------------------
        # Excel output with auto-width
        # -----------------------------
        with pd.ExcelWriter(f"ETF_{self.pair}_Market_Regime.xlsx", engine='xlsxwriter') as writer:
            out.to_excel(writer, index=False, sheet_name='Market_Regime')
            workbook  = writer.book
            worksheet = writer.sheets['Market_Regime']

            # Auto-fit columns
            for i, col in enumerate(out.columns):
                max_len = max(
                    out[col].astype(str).map(len).max(),
                    len(col)
                ) + 2  # padding

                # Expand Column A by 20%
                if i == 0:
                    max_len = int(max_len * 1.5)
                worksheet.set_column(i, i, max_len)

            # Optional: format numeric columns nicely
            num_fmt = workbook.add_format({'num_format': '#,##0.00'})
            for col_name in ['NetFlow', 'Relative_Flow', 'Premium', 'Liquidity']:
                col_idx = out.columns.get_loc(col_name)
                worksheet.set_column(col_idx, col_idx, None, num_fmt)

        print(
            f"[INFO] Market regime report saved "
            f"(limited to {start.date()} → {end.date()})"
        )

def run_etf_analysis_for_bot():
    """
    Run ETF Market Regime analysis for both BTC-USD and ETH-USD.
    Returns a simplified summary string and the renamed Excel report path.
    """
    pairs = ["BTC-USD", "ETH-USD"]

    # Run both analyses
    for pair in pairs:
        etf = ETF_Market_Regime(pair)
        etf.run()  # Generates original Excel reports

    # Read BTC report for the simplified summary
    import pandas as pd
    report_path_original = "ETF_BTC-USD_Market_Regime.xlsx"
    df = pd.read_excel(report_path_original)

    # Pick the last row for summary
    last_row = df.iloc[-1]

    summary = (
        "📊 ETF Flow & Market Regime Analysis\n\n"
        f"💰 Net Flow: {last_row['NetFlow']}\n"
        f"📐 Flow Regime: {last_row['FlowRegime']}\n"
        f"🏷 Liquidity: {last_row['Liquidity']:.2f}\n"
        f"💧 LiquidityTrend: {last_row['Liquidity_Trend']}\n\n"
        f"🎯 Market Condition: {last_row['Market_Condition']}"
    )

    # Rename/move Excel file for bot
    import os, shutil
    new_file_name = "Crypto_ETF_Condition_BTC-ETH.xlsx"
    shutil.move(report_path_original, new_file_name)

    # Remove ETH report if exists
    eth_report = "ETF_ETH-USD_Market_Regime.xlsx"
    if os.path.exists(eth_report):
        os.remove(eth_report)

    return summary, new_file_name

# ============================================================
# RUN
# ============================================================
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python etf_market_regime_limited.py BTC-USD | ETH-USD")
        sys.exit(1)

    ETF_Market_Regime(sys.argv[1]).run()
