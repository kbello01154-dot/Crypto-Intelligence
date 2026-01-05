# ============================================================
# CSA_HumanLike_Confluence_24H_SessionVol_v4.py
# 24-Hour Rolling Hourly Report with Human-like Scoring,
# Session-Based Volatility, Conditional Liquidity & Correlation
# ============================================================

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import yfinance as yf
import sys
from itertools import combinations

# ============================================================
# MARKET DATA ENGINE
# ============================================================
class MarketData:
    def __init__(self, pairs, timeframe='1h'):
        self.pairs = pairs
        self.timeframe = timeframe
        self.data = {}

    def download_ohlcv(self):
        for pair in self.pairs:
            yf_symbol = pair.replace("USDT", "-USD") if pair.endswith("USDT") else pair
            for attempt in range(5):
                try:
                    df = yf.download(
                        yf_symbol,
                        period="60d",
                        interval=self.timeframe,
                        auto_adjust=False
                    )
                    if df.empty:
                        raise ValueError("Empty dataframe returned")
                    df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
                    df.columns = ['open', 'high', 'low', 'close', 'volume']
                    df = df.reset_index()
                    df.rename(columns={df.columns[0]: 'timestamp'}, inplace=True)
                    self.data[pair] = df
                    print(f"[INFO] Downloaded {len(df)} rows for {pair}")
                    break
                except Exception as e:
                    print(f"[ERROR] Attempt {attempt+1} failed for {pair}: {e}")
                    if attempt == 4:
                        print(f"[FATAL] Giving up on {pair} after 5 failures.")
                    else:
                        print("[INFO] Retrying...")

# ============================================================
# SESSION ENGINE
# ============================================================
class SessionEngine:
    def __init__(self):
        self.sessions = {
            'Asia': ('00:00', '09:00'),
            'London': ('08:00', '17:00'),
            'New York': ('13:00', '22:00')
        }

    def detect_session(self, timestamp):
        utc_time = timestamp.time()
        for session, (start_str, end_str) in self.sessions.items():
            start = datetime.strptime(start_str, '%H:%M').time()
            end = datetime.strptime(end_str, '%H:%M').time()
            if start <= utc_time < end:
                return session
        return 'Unknown'

# ============================================================
# CORRELATION ENGINE
# ============================================================
class CorrelationEngine:
    def __init__(self, data):
        self.data = data

    def compute_correlation(self):
        closes = pd.DataFrame({pair: df['close'] for pair, df in self.data.items()})
        corr_matrix = closes.corr()
        pairwise_corrs = {}
        for a, b in combinations(closes.columns, 2):
            pairwise_corrs[f"corr_{a}_{b}"] = corr_matrix.loc[a, b]
        return pairwise_corrs

# ============================================================
# ACG HUMAN-LIKE CONFLUENCE MODEL
# ============================================================
class ACGModel:
    def __init__(self, data, sessions, pairwise_corrs):
        self.data = data
        self.sessions = sessions
        self.pairwise_corrs = pairwise_corrs

    # -------------------------
    # Session Weight (fixed values)
    # -------------------------
    def compute_session_weight(self):
        weight_map = {'Asia': 0, 'London': 0.15, 'New York': 0.15, 'Unknown': 0}
        first_pair = list(self.data.keys())[0]
        df = self.data[first_pair].copy()
        if df.empty:
            return 'Unknown', 0, pd.Timestamp.now()
        df['session'] = df['timestamp'].apply(self.sessions.detect_session)
        df['session_weight'] = df['session'].map(weight_map)
        latest = df.iloc[-1]
        return latest['session'], latest['session_weight'], latest['timestamp']

    # -------------------------
    # Liquidity Transfer
    # -------------------------
    def compute_liquidity_transfer(self):
        first_pair = list(self.data.keys())[0]
        df = self.data[first_pair].copy()
        if df.empty:
            return 0
        
        df['hour'] = df['timestamp'].dt.hour
        asia_mask = df['hour'].between(0, 8)
        
        df['asia_high'] = np.nan
        df['asia_low'] = np.nan
        
        df.loc[asia_mask, 'asia_high'] = df.loc[asia_mask, 'high'].rolling(9, min_periods=1).max()
        df.loc[asia_mask, 'asia_low'] = df.loc[asia_mask, 'low'].rolling(9, min_periods=1).min()
        
        df['asia_high'] = df['asia_high'].ffill()
        df['asia_low'] = df['asia_low'].ffill()
        
        london_break_up = df['high'] - df['asia_high']
        london_break_down = df['asia_low'] - df['low']
        
        df['liquidity_transfer'] = np.maximum(london_break_up, london_break_down)
        
        rolling_range = df['high'].rolling(24, min_periods=1).max() - \
                        df['low'].rolling(24, min_periods=1).min()
        
        df['liquidity_transfer_scaled'] = df['liquidity_transfer'] / (rolling_range + 1e-9)
        
        return df['liquidity_transfer_scaled']

    # -------------------------
    # Session Breakout Strength
    # -------------------------
    def compute_session_breakout(self):
        first_pair = list(self.data.keys())[0]
        df = self.data[first_pair].copy()
        if df.empty:
            return None, 0, None, None

        df['session'] = df['timestamp'].apply(self.sessions.detect_session)
        df['date'] = df['timestamp'].dt.date
        df['session_id'] = df['date'].astype(str) + "_" + df['session']
        df = df[df['session'] != "Unknown"]

        session_blocks = df.groupby('session_id')
        if len(session_blocks) < 2:
            return None, 0, None, None

        last_two = list(session_blocks)[-2:]
        prev_session_id, prev_df = last_two[0]
        curr_session_id, curr_df = last_two[1]

        prev_high = prev_df['high'].max()
        prev_low = prev_df['low'].min()
        prev_range = (prev_high - prev_low) + 1e-9

        curr_high = curr_df['high'].max()
        curr_low = curr_df['low'].min()

        if curr_high > prev_high:
            direction = "UP"
            strength = (curr_high - prev_high) / prev_range
        elif curr_low < prev_low:
            direction = "DOWN"
            strength = -(prev_low - curr_low) / prev_range
        else:
            direction = "NONE"
            strength = 0.0

        strength = float(np.clip(strength, -1.0, 1.0))
        return direction, strength, prev_high, prev_low

    # -------------------------
    # Session-based Volatility
    # -------------------------
    def compute_session_volatility(self, df_full):
        df = df_full.copy()
        df['range'] = df['high'] - df['low']
        df['session'] = df['timestamp'].apply(self.sessions.detect_session)
        df['date'] = df['timestamp'].dt.date
        df['session_id'] = df['date'].astype(str) + "_" + df['session']

        session_vols = []
        session_groups = df.groupby('session_id')

        for session_id, session_df in session_groups:
            date_str, session_name = session_id.split('_')
            prev_date = (pd.to_datetime(date_str) - pd.Timedelta(days=1)).date()
            prev_session_id = f"{prev_date}_{session_name}"

            if prev_session_id in session_groups.groups:
                prev_session_df = session_groups.get_group(prev_session_id)
                prev_avg_range = prev_session_df['range'].mean() + 1e-9
            else:
                prev_avg_range = 1.0

            session_vol = session_df['range'] / prev_avg_range
            session_vol = session_vol.clip(0.3, 2.0)
            session_vols.append(session_vol)

        df['session_volatility'] = pd.concat(session_vols).sort_index()
        return df['session_volatility']

    # -------------------------
    # Human-Like Confluence Scoring
    # -------------------------
    def compute_human_like_confluence(self, session, breakout_strength, breakout_direction,
                                      session_volatility, liquidity_transfer, pair_corrs):

        bull = 0.0
        bear = 0.0
        neutral = 0.0

        # --- Session bonus ---
        session_bonus = 0.15 if session in ["London", "New York"] else 0.0
        if breakout_direction == "UP":
            bull += session_bonus
        elif breakout_direction == "DOWN":
            bear += session_bonus
        else:
            neutral += session_bonus

        # --- Breakout base effect ---
        if breakout_direction == "UP":
            bull += 0.10
        elif breakout_direction == "DOWN":
            bear += 0.10
        else:
            neutral += 0.10

        # --- Breakout strength ---
        if breakout_strength > 0.6:
            bull += 0.10
        elif breakout_strength < -0.6:
            bear += 0.10
        else:
            neutral += 0.05

        # --- Volatility modifier ---
        if session_volatility > 1.20:
            if breakout_direction == "UP":
                bull += 0.30
            elif breakout_direction == "DOWN":
                bear += 0.30
        elif session_volatility < 0.80:
            neutral += 0.30

        # --- Liquidity Transfer ------------------------
        liq = liquidity_transfer

        # --- CORRELATION ENGINE (Corrected) ------------

        corr = 0.0
        for key, corr_value in pair_corrs.items():
            if abs(corr_value) > 0.7:

                # POSITIVE CORRELATION → SAME direction
                if corr_value > 0:

                    if breakout_direction == "UP":
                        corr = max(corr, corr_value)      # bullish confirmation

                    elif breakout_direction == "DOWN":
                        corr = max(corr, corr_value)      # bearish confirmation

                # NEGATIVE CORRELATION → OPPOSITE direction
                elif corr_value < 0:

                    if breakout_direction == "UP":
                        corr = max(corr, abs(corr_value))  # inverse = bearish
                        bear += corr * 0.15
                        continue

                    elif breakout_direction == "DOWN":
                        corr = max(corr, abs(corr_value))  # inverse = bullish
                        bull += corr * 0.15
                        continue

        # --- Apply correlation-weight for SAME direction only ---
        if breakout_direction == "UP":
            bull += liq * 0.2 + corr * 0.15

        elif breakout_direction == "DOWN":
            bear += liq * 0.2 + corr * 0.15

        else:
            neutral += (liq + corr) * 0.35

        # --- Final Score Output ---
        scores = {"Bullish": bull, "Bearish": bear, "No-Trade": neutral}
        signal = max(scores, key=scores.get)
        final_value = scores[signal]

        return final_value, signal

# ============================================================
# CSA MAIN CLASS
# ============================================================
class CSA:
    def __init__(self, pairs):
        self.market = MarketData(pairs)
        self.session_engine = SessionEngine()
        self.pairs = pairs

    def run(self):
        # Download OHLCV data
        self.market.download_ohlcv()

        first_pair = list(self.market.data.keys())[0]
        df_base = self.market.data[first_pair].copy()

        total_rows = len(df_base)
        if total_rows < 1:
            print("[ERROR] No data available to process.")
            return

        report_rows = []

        for i in range(max(24, total_rows) - 24, total_rows):
            df_window = df_base.iloc[:i+1].copy()
            if df_window.empty:
                continue

            # Session volatility (causal)
            acg_window_data = {first_pair: df_window}
            acg_window = ACGModel(acg_window_data, self.session_engine, {})
            session_vol_series = acg_window.compute_session_volatility(df_window)
            df_window['session_volatility'] = session_vol_series.values
            current_vol = df_window['session_volatility'].iloc[-1]

            # Liquidity Transfer
            liq_series = acg_window.compute_liquidity_transfer()
            liquidity_transfer = liq_series.iloc[-1]
            df_window['liquidity_transfer_scaled'] = liq_series
            liq_median_24h = df_window['liquidity_transfer_scaled'].rolling(24, min_periods=1).median().iloc[-1]
            liq_for_confluence = liquidity_transfer if liquidity_transfer >= liq_median_24h else 0

            # Session & Breakout
            session, session_weight, timestamp = acg_window.compute_session_weight()
            breakout_dir, breakout_strength, prev_high, prev_low = acg_window.compute_session_breakout()

            # Correlations
            corr_window = {p: self.market.data[p].iloc[:i+1].copy() for p in self.pairs}
            pair_corrs = CorrelationEngine(corr_window).compute_correlation()

            # Human-like confluence
            acg_confluence, signal = acg_window.compute_human_like_confluence(
                session,
                breakout_strength,
                breakout_dir,
                current_vol,
                liq_for_confluence,
                pair_corrs
            )

            # Save row
            row_data = {
                "timestamp": timestamp,
                "session": session,
                "session weight": session_weight,
                "breakout direction": breakout_dir,
                "breakout strength": breakout_strength,
                "previous session_high": prev_high,
                "previous session_low": prev_low,
                "liquidity transfer": liquidity_transfer,
                "session volatility": current_vol,
                "CSA Confidence": acg_confluence,
                "Signal": signal
            }
            row_data.update(pair_corrs)
            report_rows.append(row_data)

        # Final report
        df_final = pd.DataFrame(report_rows)

        # Format numeric columns
        df_final['session weight'] = df_final['session weight'].apply(lambda x: f"{x*100:.0f}%" if pd.notnull(x) else x)
        df_final['breakout strength'] = df_final['breakout strength'].apply(lambda x: f"{x*100:.1f}%" if pd.notnull(x) else x)
        # Corrected session volatility format as "current% / 200%"
        df_final['session volatility'] = df_final['session volatility'].apply(lambda x: f"{x*100:.1f}% / 200%" if pd.notnull(x) else x)
        df_final['CSA Confidence'] = df_final['CSA Confidence'].apply(lambda x: f"{x*100:.1f}%" if pd.notnull(x) else x)

        # Correlation columns to percentages
        corr_cols = [col for col in df_final.columns if col.startswith('corr_')]
        for col in corr_cols:
            df_final[col] = df_final[col].apply(lambda x: f"{x*100:.1f}%" if pd.notnull(x) else x)

        # Format liquidity transfer and previous session high/low
        df_final['liquidity transfer'] = df_final['liquidity transfer'].apply(lambda x: f"{x:.2f}" if pd.notnull(x) else x)
        df_final['previous session_high'] = df_final['previous session_high'].apply(lambda x: f"{x:.2f}" if pd.notnull(x) else x)
        df_final['previous session_low'] = df_final['previous session_low'].apply(lambda x: f"{x:.2f}" if pd.notnull(x) else x)

        # Remove timezone info
        df_final['timestamp'] = df_final['timestamp'].dt.tz_localize(None)

        # Write Excel with auto column width
        with pd.ExcelWriter("CSA_Hourly_24_Report.xlsx", engine='xlsxwriter') as writer:
            df_final.to_excel(writer, index=False, sheet_name='Report')
            worksheet = writer.sheets['Report']
            for i, col in enumerate(df_final.columns):
                max_len = max(df_final[col].astype(str).map(len).max(), len(col)) + 2
                worksheet.set_column(i, i, max_len)

        print(f"[INFO] 24-hour hourly report saved → CSA_Hourly_24_Report.xlsx with formatted numbers")

# ============================================================
# RUN
# ============================================================
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python CSA.py BTC-USD ETH-USD SOL-USD ...")
        sys.exit(1)
    pairs = sys.argv[1:]
    csa = CSA(pairs)
    csa.run()
