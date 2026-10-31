"""
analytics.py
------------
Calculations used by the dashboard. Pure pandas (no Streamlit), so every
function can be tested on its own.

All data comes from the SQLite table 'machine_readings', which is filled by
the Python machine simulator. Nothing here is real factory data.

Severity levels and maintenance advice are DEMONSTRATION rules. They are not
validated industrial limits, they are not predictive maintenance, and a
warning does not prove that a machine will fail.
"""

import pandas as pd

SEVERITY_ORDER = ["Critical", "High", "Medium"]
CRITICAL_RATIO = 1.15      # value is 15% or more above the limit
HIGH_RATIO = 1.07          # value is 7% or more above the limit
WATCH_RATIO = 0.85         # value is within 15% of the limit

HEALTH_LABEL = {
    "Normal": "🟢 Normal",
    "Watch": "🟡 Watch",
    "Warning": "🟠 Warning",
    "Maintenance": "🔵 Maintenance",
}
SEVERITY_ICON = {"Critical": "🔴 Critical", "High": "🟠 High", "Medium": "🟡 Medium"}

ALERT_COLUMNS = ["timestamp", "machine", "severity", "trigger",
                 "temperature", "vibration", "message", "recommendation"]

RECOMMENDATIONS = {
    "Temperature": "Check cooling, lubrication and airflow. Confirm the temperature reading.",
    "Vibration": "Inspect bearings, mounting bolts and alignment. Look for loose parts.",
    "Temperature + Vibration": "Plan a full inspection of cooling, bearings and alignment "
                               "at the next safe stop.",
}
SEVERITY_PREFIX = {"Critical": "Prioritise: ", "High": "Plan soon: ", "Medium": "Keep watching: "}


# ------------------------------------------------------------------
# Cleaning
# ------------------------------------------------------------------
def clean_readings(df):
    """Valid timestamps, numeric columns, sorted oldest to newest."""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
    out = out.dropna(subset=["timestamp"])
    for col in ("temperature", "vibration", "pressure", "units_produced"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.sort_values("timestamp").reset_index(drop=True)


# ------------------------------------------------------------------
# Alerts (rule based)
# ------------------------------------------------------------------
def _severity(ratio):
    if ratio >= CRITICAL_RATIO:
        return "Critical"
    if ratio >= HIGH_RATIO:
        return "High"
    return "Medium"


def compute_alerts(df, temp_thr, vib_thr):
    """
    Saved readings whose temperature or vibration is above the demo thresholds.
    Readings taken during Maintenance are ignored (the machine was stopped).
    """
    empty = pd.DataFrame(columns=ALERT_COLUMNS)
    data = clean_readings(df)
    if data.empty or temp_thr <= 0 or vib_thr <= 0:
        return empty

    data = data[data["status"] != "Maintenance"]
    t_ratio = data["temperature"] / temp_thr
    v_ratio = data["vibration"] / vib_thr
    mask = (t_ratio > 1) | (v_ratio > 1)
    data = data[mask].copy()
    if data.empty:
        return empty

    t_ratio, v_ratio = t_ratio[mask], v_ratio[mask]
    ratio = pd.concat([t_ratio, v_ratio], axis=1).max(axis=1)

    data["severity"] = ratio.apply(_severity)
    t_over, v_over = t_ratio > 1, v_ratio > 1
    data["trigger"] = [
        "Temperature + Vibration" if t and v else "Temperature" if t else "Vibration"
        for t, v in zip(t_over, v_over)
    ]

    messages, advice = [], []
    for (_, row), t, v in zip(data.iterrows(), t_over, v_over):
        parts = []
        if t:
            parts.append(f"temperature {row['temperature']:.1f} is above {temp_thr:g}")
        if v:
            parts.append(f"vibration {row['vibration']:.2f} is above {vib_thr:g}")
        messages.append(" and ".join(parts))
        advice.append(SEVERITY_PREFIX[row["severity"]] + RECOMMENDATIONS[row["trigger"]])
    data["message"] = messages
    data["recommendation"] = advice

    return data[ALERT_COLUMNS].sort_values("timestamp", ascending=False).reset_index(drop=True)


def alert_summary(alerts):
    """Number of alerts per machine and severity."""
    if alerts is None or alerts.empty:
        return pd.DataFrame(columns=["Machine"] + SEVERITY_ORDER + ["Total"])
    table = pd.crosstab(alerts["machine"], alerts["severity"])
    table = table.reindex(columns=SEVERITY_ORDER, fill_value=0)
    table["Total"] = table.sum(axis=1)
    table.index.name = "Machine"
    return table.reset_index()


# ------------------------------------------------------------------
# Health, KPIs and summaries
# ------------------------------------------------------------------
def machine_health(status, temperature, vibration, temp_thr, vib_thr):
    """Normal / Watch / Warning / Maintenance for ONE reading (demo rule)."""
    if status == "Maintenance":
        return "Maintenance"
    ratio = max(temperature / temp_thr, vibration / vib_thr)
    if ratio > 1:
        return "Warning"
    if ratio >= WATCH_RATIO:
        return "Watch"
    return "Normal"


def health_table(latest, profiles, temp_thr, vib_thr):
    """One row per machine from the latest saved readings."""
    if latest is None or latest.empty:
        return pd.DataFrame()
    rows = []
    for _, r in latest.iterrows():
        health = machine_health(r["status"], r["temperature"], r["vibration"],
                                temp_thr, vib_thr)
        rows.append({
            "Machine": r["machine"],
            "Stage": profiles.get(r["machine"], {}).get("stage", "-"),
            "Health": HEALTH_LABEL[health],
            "Temperature": round(float(r["temperature"]), 1),
            "Vibration": round(float(r["vibration"]), 2),
            "Pressure": round(float(r["pressure"]), 2),
            "Last reading": r["timestamp"],
        })
    return pd.DataFrame(rows)


def kpis(df, temp_thr, vib_thr):
    """Headline numbers for the Overview page. Returns None if there is no data."""
    data = clean_readings(df)
    if data.empty:
        return None
    active = data[data["status"] != "Maintenance"]
    alerts = compute_alerts(data, temp_thr, vib_thr)
    return {
        "machines": int(data["machine"].nunique()),
        "readings": int(len(data)),
        "units": int(data["units_produced"].fillna(0).sum()),
        "alerts": int(len(alerts)),
        "alert_rate": (len(alerts) / len(active) * 100) if len(active) else 0.0,
        "availability": len(active) / len(data) * 100,
        "avg_temp": float(data["temperature"].mean()),
        "first": data["timestamp"].min(),
        "last": data["timestamp"].max(),
    }


def status_counts(df):
    data = clean_readings(df)
    counts = {"Running": 0, "Warning": 0, "Maintenance": 0}
    if not data.empty:
        for status, n in data["status"].value_counts().items():
            counts[status] = int(n)
    return counts


def production_by_stage(df, profiles):
    data = clean_readings(df)
    if data.empty:
        return pd.DataFrame(columns=["stage", "units"])
    per_machine = data.groupby("machine")["units_produced"].sum()
    out = pd.DataFrame({"machine": per_machine.index, "units": per_machine.values})
    out["stage"] = out["machine"].map(lambda m: profiles.get(m, {}).get("stage", "Unknown"))
    return out.groupby("stage", as_index=False)["units"].sum()


def production_summary(df, profiles):
    """Units per machine (sum of the saved samples)."""
    data = clean_readings(df)
    if data.empty:
        return pd.DataFrame()
    g = data.groupby("machine")["units_produced"]
    out = pd.DataFrame({
        "Machine": g.size().index,
        "Stage": [profiles.get(m, {}).get("stage", "-") for m in g.size().index],
        "Saved readings": g.size().values,
        "Units (saved samples)": g.sum().astype(int).values,
        "Average units per reading": g.mean().round(1).values,
    })
    return out


def summary_stats(df):
    """Min / max / average of every sensor, per machine."""
    data = clean_readings(df)
    if data.empty:
        return pd.DataFrame()
    out = data.groupby("machine").agg(**{
        "Readings": ("machine", "size"),
        "Avg temp": ("temperature", "mean"),
        "Min temp": ("temperature", "min"),
        "Max temp": ("temperature", "max"),
        "Avg vibration": ("vibration", "mean"),
        "Min vibration": ("vibration", "min"),
        "Max vibration": ("vibration", "max"),
        "Avg pressure": ("pressure", "mean"),
        "Units (saved samples)": ("units_produced", "sum"),
        "Warning readings": ("status", lambda s: int((s == "Warning").sum())),
        "Maintenance readings": ("status", lambda s: int((s == "Maintenance").sum())),
    })
    out = out.round(2)
    out.index.name = "Machine"
    return out.reset_index()


def trend_wide(df, column, max_points=1500):
    """Time on the rows, one column per machine (ready for st.line_chart)."""
    data = clean_readings(df)
    if data.empty or column not in data.columns:
        return pd.DataFrame()
    wide = data.pivot_table(index="timestamp", columns="machine",
                            values=column, aggfunc="mean").sort_index()
    if len(wide) > max_points:
        wide = wide.iloc[::(len(wide) // max_points) + 1]
    wide.columns.name = None
    return wide