import pandas as pd
import numpy as np
import yfinance as yf
from fredapi import Fred
import warnings
warnings.filterwarnings("ignore")

# ============================================================
# CONFIG
# ============================================================

FRED_API_KEY = "614b0cd9163b5ee908608e732781cb5e"
fred = Fred(api_key=FRED_API_KEY)

START_DATE = "2015-01-01"
NO_TRADE_THRESHOLD = 0.55   # minimum confluence to issue signal

# ============================================================
# 1. DATA ENGINE
# ============================================================

class IMADataEngine:
    def __init__(self):
        self.data = None

    def download_yf(self, symbol):
        return yf.download(symbol, start=START_DATE, auto_adjust=True)["Close"].squeeze()

    def load_all(self):
        print("📡 Fetching price data...")

        # Crypto
        btc   = self.download_yf("BTC-USD")
        eth   = self.download_yf("ETH-USD")

        # Equities / Vol
        sp500  = self.download_yf("^GSPC")
        nasdaq = self.download_yf("^IXIC")
        vix    = self.download_yf("^VIX")

        # FX
        dxy     = self.download_yf("DX=F")
        eurusd  = self.download_yf("EURUSD=X")

        # Commodities
        gold    = self.download_yf("GC=F")
        oil     = self.download_yf("CL=F")
        copper  = self.download_yf("HG=F")

        print("📡 Fetching FRED macro data...")

        # Rates & credit (FRED)
        us10y = fred.get_series("DGS10")       # 10Y Treasury
        us02y = fred.get_series("DGS2")        # 2Y Treasury
        fed   = fred.get_series("FEDFUNDS")
        cpi   = fred.get_series("CPIAUCSL")
        hy_oas = fred.get_series("BAMLH0A0HYM2")  # HY OAS

        macro = {
            "US10Y": us10y,
            "US02Y": us02y,
            "FedFunds": fed,
            "CPI": cpi,
            "HY_OAS": hy_oas
        }

        # Align macro to BTC timeline
        for k in macro:
            macro["CPI"] = macro["CPI"].shift(2)       # conservative
            macro["FedFunds"] = macro["FedFunds"].shift(1)

        data = pd.concat([
            btc, eth, sp500, nasdaq, vix,
            dxy, eurusd,
            gold, oil, copper,
            macro["US10Y"], macro["US02Y"],
            macro["FedFunds"], macro["CPI"], macro["HY_OAS"]
        ], axis=1)

        data.columns = [
            "BTC","ETH","SP500","NASDAQ","VIX",
            "DXY","EURUSD",
            "Gold","Oil","Copper",
            "US10Y","US02Y",
            "FedFunds","CPI","HY_OAS"
        ]

        data = data.ffill()

        self.data = data
        return data

# ============================================================
# 2. INDICATOR ENGINE
# ============================================================

class IMAIndicatorEngine:
    def __init__(self, data):
        self.df = data.copy()

    def zscore(self, s, window=26):
        mean = s.rolling(window).mean()
        std = s.rolling(window).std()
        std = std.replace(0, np.nan)
        return (s - mean) / std

    def compute(self):
        df = self.df
        returns = df.pct_change()

        print("📊 Computing indicators...")

        # -------------------------
        # Yield Curve
        # -------------------------
        df["YieldCurve"] = df["US10Y"] - df["US02Y"]

        # -------------------------
        # Credit Stress (real)
        # -------------------------
        df["CreditStress"] = self.zscore(df["HY_OAS"])

        # -------------------------
        # Inflation
        # -------------------------
        df["InflationYoY"] = df["CPI"].pct_change(12) * 100

        # -------------------------
        # Fed Policy Direction
        # -------------------------
        df["Fed_Delta"] = df["FedFunds"].diff(26)

        df["Macro_Stance"] = np.where(
            df["Fed_Delta"] < 0, 1,
            np.where(df["Fed_Delta"] > 0, -1, 0)
        )

        # -------------------------
        # Risk Regime (z-score based)
        # -------------------------
        risk_components = (
            -self.zscore(df["VIX"]) +
            -self.zscore(df["DXY"]) +
             self.zscore(returns["NASDAQ"])
        )

        df["Risk_Score"] = risk_components.rolling(4).mean()

        # -------------------------
        # BTC Correlation CHANGE
        # -------------------------
        corr_nasdaq = returns["BTC"].rolling(12).corr(returns["NASDAQ"])
        corr_dxy    = returns["BTC"].rolling(12).corr(returns["DXY"])

        df["Corr_BTC_NASDAQ_Change"] = corr_nasdaq.diff(4).rolling(3).mean()
        df["Corr_BTC_DXY_Change"]    = corr_dxy.diff(4)

        # -------------------------
        # Liquidity Composite
        # -------------------------
        df["Liquidity"] = (
            -self.zscore(df["DXY"]) +
             self.zscore(returns["SP500"]) -
             self.zscore(df["HY_OAS"])
        ).rolling(4).mean()

        # -------------------------
        # BTC Trend (reduced weight later)
        # -------------------------
        df["BTC_Trend"] = np.where(
            df["BTC"] > df["BTC"].rolling(8).mean(), 1, -1
        )

        return df

# ============================================================
# 3. SCORING ENGINE
# ============================================================

class IMAScoringEngine:
    def __init__(self, df):
        self.df = df.copy()

    def score_row(self, r):
        scores = {
            "Bullish": 0.0,
            "Bearish": 0.0
        }

        # -------------------------
        # 1. Risk Score (0.30)
        # -------------------------
        if r["Risk_Score"] > 0.5:
            scores["Bullish"] += 0.30
        elif r["Risk_Score"] < -0.5:
            scores["Bearish"] += 0.30

        # -------------------------
        # 2. Liquidity (0.25)
        # -------------------------
        if r["Liquidity"] > 0.5:
            scores["Bullish"] += 0.25
        elif r["Liquidity"] < -0.5:
            scores["Bearish"] += 0.25
        # -------------------------
        # 3. Credit Stress (0.15)
        # -------------------------
        if r["CreditStress"] > 0.5:
            scores["Bearish"] += 0.15
        elif r["CreditStress"] <= -0.2:
            scores["Bullish"] += 0.15

        # -------------------------
        # 4. Correlation BTC–NASDAQ (±0.10)
        # -------------------------
        if r["Corr_BTC_NASDAQ_Change"] < 0:
            scores["Bullish"] += 0.10
        elif r["Corr_BTC_NASDAQ_Change"] > 0:
            scores["Bearish"] += 0.10

        # -------------------------
        # 5. Macro Stance (Fed direction ±0.10)
        # -------------------------
        if r["Macro_Stance"] == 1:
            scores["Bullish"] += 0.10
        elif r["Macro_Stance"] == -1:
            scores["Bearish"] += 0.10

        # -------------------------
        # 6. BTC Trend (Price confirmation ±0.10)
        # -------------------------
        if r["BTC_Trend"] == 1:
            scores["Bullish"] += 0.10
        elif r["BTC_Trend"] == -1:
            scores["Bearish"] += 0.10

        # -------------------------
        # Final decision
        # -------------------------
        bias = max(scores, key=scores.get)
        confluence = scores[bias]

        if confluence < NO_TRADE_THRESHOLD:
            signal = "NoTrade"
        else:
            signal = bias

        return confluence, signal

    def run(self):
        confs, sigs = [], []

        for _, row in self.df.iterrows():
            c, s = self.score_row(row)
            confs.append(c)
            sigs.append(s)

        self.df["IMA Confidence"] = confs
        self.df["Signal"] = sigs
        return self.df

# ============================================================
# 4. REPORT
# ============================================================

class IMAReport:
    def __init__(self, df):
        self.df = df

    def generate(self):
        weekly = self.df.tail(12)

        print("\n=== WEEKLY IMA REPORT ===")
        print(weekly[[
            "BTC","SP500","DXY","US10Y","VIX",
            "Risk_Score","YieldCurve","CreditStress",
            "Liquidity","BTC_Trend",
            "IMA Confidence","Signal"
        ]])

        file_name = "IMA_Weekly_Report.xlsx"

        with pd.ExcelWriter(file_name, engine="xlsxwriter") as writer:
            # 🔑 KEY FIX: name the index column
            weekly.to_excel(
                writer,
                sheet_name="IMA_Report",
                index_label="Timestamp"
            )

            workbook  = writer.book
            worksheet = writer.sheets["IMA_Report"]

            # --- Formats ---
            percent_fmt = workbook.add_format({"num_format": "0.0%"})
            date_fmt    = workbook.add_format({"num_format": "yyyy-mm-dd"})

            # --- Auto-fit index column FIRST ---
            worksheet.set_column(0, 0, 20, date_fmt)

            # --- Auto-fit data columns ---
            for i, col in enumerate(weekly.columns):
                max_len = max(
                    weekly[col].astype(str).map(len).max(),
                    len(col)
                ) + 2
                worksheet.set_column(i + 1, i + 1, max_len)

            # --- Apply % format LAST (so it sticks) ---
            conf_col = weekly.columns.get_loc("IMA Confidence") + 1
            worksheet.set_column(conf_col, conf_col, 16, percent_fmt)

        print("✅ Report saved:", file_name)


def run_ima_analysis_for_bot():
    """
    Runs IMA analysis and returns:
    - summary text
    - path to Excel report
    """

    # Run pipeline
    data = IMADataEngine().load_all()
    data = data.resample("W-FRI").last()
    df_ind = IMAIndicatorEngine(data).compute()
    df_scored = IMAScoringEngine(df_ind).run()

    # Generate report
    report = IMAReport(df_scored)
    report.generate()

    # --- Build Telegram-friendly summary ---
    last = df_scored.iloc[-1]

    summary = (
        "📊 *IMA Weekly Crypto Analysis*\n\n"
        f"🟠 BTC Price: `{last['BTC']:.2f}`\n"
        f"📈 Risk Score: `{last['Risk_Score']:.2f}`\n"
        f"💧 Liquidity: `{last['Liquidity']:.2f}`\n"
        f"🏦 Yield Curve: `{last['YieldCurve']:.2f}`\n"
        f"🔥 Credit Stress: `{last['CreditStress']:.2f}`\n\n"
        f"🎯 *Signal:* `{last['Signal']}`\n"
        f"📐 *Confidence:* `{last['IMA Confidence']:.0%}`"
    )

    return summary, "IMA_Weekly_Report.xlsx"

# ============================================================
# RUN
# ============================================================

class IMA:
    def run(self):
        # 1. Load data
        data = IMADataEngine().load_all()

        # 2. Weekly frequency (Friday close)
        data = data.resample("W-FRI").last()

        # 3. Indicators
        df_ind = IMAIndicatorEngine(data).compute()

        # 4. Scoring
        df_scored = IMAScoringEngine(df_ind).run()

        # 5. Report
        IMAReport(df_scored).generate()

if __name__ == "__main__":
    IMA().run()
