import time
from datetime import datetime

import pandas as pd
import streamlit as st

from machine_simulator import MachineSimulator, MACHINE_PROFILES
from database import (
    create_table,
    save_readings,
    get_readings,
    get_latest_readings,
    get_reading_count,
)
from auth import create_users_table, verify_user, add_user, list_users, ROLES
import analytics as an
from styles import (
    apply_styles, banner, masthead, demo_strip, section_title, kpi_card,
    live_badge, machine_card, progress_bar, event_feed, segment_bar,
    advice_card, wide_bars, colors_for,
    MACHINE_COLORS, STAGE_COLORS, STATUS_COLORS,
)

# set_page_config must be the first Streamlit command
st.set_page_config(page_title="Production Monitoring System",
                   page_icon="🏭", layout="wide")

create_table()
create_users_table()
apply_styles()

MAX_FAILED_ATTEMPTS = 5
LOCK_SECONDS = 60
SOURCE_LABEL = "Simulated (demo)"

NAV_OVERVIEW = "📊 Overview"
NAV_LIVE = "📡 Live Monitoring"
NAV_HISTORY = "📈 Machine History"
NAV_ALERTS = "🚨 Alerts & Maintenance"
NAV_REPORTS = "🧾 Reports"
NAV_USERS = "👥 User Management"
NAV_SAMPLE = "🗂️ Sample Dashboard (original)"
NAV_ABOUT = "ℹ️ About & Method"

# ------------------------------------------------------------------
# Session state (values that must survive Streamlit reruns)
# ------------------------------------------------------------------
defaults = {
    "authenticated": False,
    "username": None,
    "role": None,
    "failed_attempts": 0,
    "locked_until": 0.0,
    "monitoring": False,
    "latest_df": None,
    "prev_df": None,
    "buffer": None,
    "tick_count": 0,
    "session_units": {},
    "events": [],
    "last_save_ts": 0.0,
    "last_saved_text": "Nothing saved in this session yet.",
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value
if "sim" not in st.session_state:
    st.session_state.sim = MachineSimulator()


# ------------------------------------------------------------------
# Login page
# ------------------------------------------------------------------
def show_login():
    st.markdown(
        '<div class="login-brand"><span class="brand-mark">H</span>'
        '<div class="brand-copy"><strong>HMS MEDICAL SYSTEMS</strong>'
        '<span>Production operations</span></div>'
        '<span class="environment-pill">SIMULATED SYSTEM</span></div>',
        unsafe_allow_html=True,
    )

    visual, form_column = st.columns([1.08, 0.92], gap="large",
                                     vertical_alignment="center")
    with visual:
        st.markdown(
            f'<section class="login-visual">'
            f'<div class="login-visual-top"><span class="login-kicker">'
            f'MEDICAL MANUFACTURING / CHENNAI</span></div>'
            f'<div><h1>Production,<br>in focus.</h1>'
            f'<p>A single view of machine health, output, and shift activity '
            f'for your production floor.</p></div>'
            f'<div class="login-visual-bottom"><div class="login-stat">'
            f'<strong>{len(MACHINE_PROFILES)} monitored assets</strong>'
            f'<span>SYNTHETIC DEMONSTRATION DATA</span></div>'
            f'<div class="login-signal" aria-hidden="true"></div></div>'
            f'</section>',
            unsafe_allow_html=True,
        )

    with form_column:
        st.markdown(
            '<div class="login-form-wrap"><div class="eyebrow">SECURE ACCESS</div>'
            '<h2>Welcome back</h2>'
            '<p>Sign in to open the production monitoring workspace.</p></div>',
            unsafe_allow_html=True,
        )
        remaining = st.session_state.locked_until - time.time()
        if remaining > 0:
            st.error(f"Too many failed attempts. "
                     f"Try again in {int(remaining) + 1} seconds.")

        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary")

        if submitted and remaining <= 0:
            role = verify_user(username, password)
            if role:
                st.session_state.authenticated = True
                st.session_state.username = username.strip().lower()
                st.session_state.role = role
                st.session_state.failed_attempts = 0
                st.rerun()
            else:
                st.session_state.failed_attempts += 1
                if st.session_state.failed_attempts >= MAX_FAILED_ATTEMPTS:
                    st.session_state.locked_until = time.time() + LOCK_SECONDS
                    st.session_state.failed_attempts = 0
                    st.error(f"Too many failed attempts. "
                             f"Locked for {LOCK_SECONDS} seconds.")
                else:
                    st.error("Incorrect username or password.")

        with st.expander("Demo accounts"):
            st.table(pd.DataFrame({
                "Username": ["admin", "supervisor"],
                "Password": ["Admin@123", "Super@123"],
                "Role": ["Admin", "Supervisor"],
            }))
            st.caption("Demo accounts are created automatically. "
                       "Change or remove them before any real use.")


def logout():
    st.session_state.authenticated = False
    st.session_state.username = None
    st.session_state.role = None
    st.session_state.monitoring = False


# ------------------------------------------------------------------
# Login gate: nothing below runs unless the user is signed in
# ------------------------------------------------------------------
if not st.session_state.authenticated:
    show_login()
    st.stop()

is_admin = st.session_state.role == "Admin"


# ------------------------------------------------------------------
# Sidebar: brand, user, navigation and settings
# ------------------------------------------------------------------
st.sidebar.markdown(
    '<div class="side-brand"><b>🏭 Production Monitor</b>'
    '<span>HMS Medical Systems · Chennai</span>'
    '<div class="side-pill">DEMO MODE · SIMULATED DATA</div></div>',
    unsafe_allow_html=True,
)
st.sidebar.markdown(
    f'<div class="user-box">👤 <b>{st.session_state.username}</b><br>'
    f'<small>Role: {st.session_state.role}</small></div>',
    unsafe_allow_html=True,
)
st.sidebar.button("Sign out", on_click=logout)

pages = [NAV_OVERVIEW, NAV_LIVE, NAV_HISTORY, NAV_ALERTS, NAV_REPORTS]
if is_admin:
    pages.append(NAV_USERS)
pages += [NAV_SAMPLE, NAV_ABOUT]

st.sidebar.caption("MENU")
page = st.sidebar.radio("Navigation", pages, label_visibility="collapsed")

with st.sidebar.expander("Monitoring settings", expanded=False):
    st.selectbox("Screen refresh interval (seconds)", [2, 5, 10, 15],
                 index=1, key="refresh_interval")
    st.toggle("Pop-up alerts for new warnings", value=True, key="toast_alerts")
    st.number_input("Database logging interval (seconds)", min_value=5,
                    max_value=3600, value=30, step=5, key="log_interval",
                    disabled=not is_admin,
                    help="Readings are shown every refresh, but saved to the "
                         "database only this often.")
    st.number_input("Temperature warning threshold (demo)", value=82.0,
                    step=0.5, key="temp_threshold", disabled=not is_admin)
    st.number_input("Vibration warning threshold (demo)", value=3.8,
                    step=0.1, key="vib_threshold", disabled=not is_admin)
    st.number_input("Production target per machine (demo, this session)",
                    min_value=50, max_value=100000, value=500, step=50,
                    key="unit_target", disabled=not is_admin,
                    help="A configurable demonstration target, not a real "
                         "production plan.")
    if not is_admin:
        st.caption("🔒 Only an Admin can change thresholds, logging and targets.")
    st.caption("Thresholds are demonstration values, not validated "
               "industrial safety limits.")

with st.sidebar.expander("Saved data export"):
    export_df = get_readings(limit=5000)
    st.caption(f"Latest {len(export_df):,} saved readings (up to 5,000).")
    st.download_button(
        "Download CSV",
        data=export_df.to_csv(index=False).encode("utf-8"),
        file_name="production-readings.csv",
        mime="text/csv",
        disabled=export_df.empty,
    )
    if export_df.empty:
        st.caption("Start monitoring to create readings for export.")


# ------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------
def thresholds():
    return float(st.session_state.temp_threshold), float(st.session_state.vib_threshold)


def start_monitoring():
    st.session_state.monitoring = True
    st.session_state.last_save_ts = 0.0     # save the first reading straight away


def stop_monitoring():
    st.session_state.monitoring = False


def reset_session():
    """Clear the in-memory live data (the database is NOT touched)."""
    st.session_state.latest_df = None
    st.session_state.prev_df = None
    st.session_state.buffer = None
    st.session_state.tick_count = 0
    st.session_state.session_units = {}
    st.session_state.events = []


def warning_reason(row):
    reasons = []
    if row["Temperature"] > st.session_state.temp_threshold:
        reasons.append(f"temperature {row['Temperature']:.1f} is above "
                       f"{st.session_state.temp_threshold}")
    if row["Vibration"] > st.session_state.vib_threshold:
        reasons.append(f"vibration {row['Vibration']:.2f} is above "
                       f"{st.session_state.vib_threshold}")
    return " and ".join(reasons)


def record_events(prev_df, df, tick_time):
    """Add an event whenever a machine's status changes. Returns the new events."""
    if prev_df is None:
        return []
    old_status = dict(zip(prev_df["Machine"], prev_df["Status"]))
    stamp = tick_time.strftime("%H:%M:%S")
    new_events = []
    for _, row in df.iterrows():
        old = old_status.get(row["Machine"])
        new = row["Status"]
        if old is None or old == new:
            continue
        if new == "Warning":
            level, text = "warning", f"{old} → Warning ({warning_reason(row)})"
        elif new == "Maintenance":
            level, text = "info", f"{old} → Maintenance started"
        elif new == "Running" and old == "Maintenance":
            level, text = "ok", "Maintenance finished, machine running again"
        else:
            level, text = "ok", f"{old} → {new}"
        new_events.append({"time": stamp, "machine": row["Machine"],
                           "text": text, "level": level})
    st.session_state.events = (new_events + st.session_state.events)[:50]
    return new_events


def tick():
    """Generate one new set of simulated readings; save to DB only when due."""
    sim = st.session_state.sim
    sim.temp_threshold = st.session_state.temp_threshold
    sim.vib_threshold = st.session_state.vib_threshold

    prev = st.session_state.latest_df
    df = sim.next_readings()
    tick_time = df["Timestamp"].max()

    st.session_state.prev_df = prev
    st.session_state.latest_df = df
    st.session_state.tick_count += 1

    # Live buffer (in memory only) used for the trend charts
    buffered = df.assign(Time=tick_time)
    if st.session_state.buffer is None:
        st.session_state.buffer = buffered
    else:
        st.session_state.buffer = pd.concat(
            [st.session_state.buffer, buffered], ignore_index=True
        ).tail(400)

    # Running total of simulated units for this session
    totals = st.session_state.session_units
    for _, row in df.iterrows():
        totals[row["Machine"]] = totals.get(row["Machine"], 0) + int(row["Units Produced"])

    new_events = record_events(prev, df, tick_time)
    if st.session_state.toast_alerts:
        for event in new_events:
            if event["level"] == "warning":
                st.toast(f"{event['machine']} entered Warning (demo rule)", icon="⚠️")

    # Controlled database saving
    now = time.time()
    if now - st.session_state.last_save_ts >= st.session_state.log_interval:
        saved = save_readings(df)
        st.session_state.last_save_ts = now
        st.session_state.last_saved_text = (
            f"Last saved {saved} new rows at {time.strftime('%H:%M:%S')}."
        )


def delta_info(change, higher_is_better, decimals=0):
    """Text and good/bad flag for the arrow under a KPI card."""
    if change is None:
        return None, None
    if abs(change) < 0.5 * 10 ** (-decimals):
        return "no change", None
    arrow = "▲" if change > 0 else "▼"
    return f"{arrow} {abs(change):.{decimals}f}", (change > 0) == higher_is_better


def load_saved(limit=50000):
    """All saved readings (cleaned), oldest first. Empty DataFrame if none."""
    return an.clean_readings(get_readings(limit=limit))


def date_controls(df, key):
    """Date range picker. Returns (start, end) or None if incomplete."""
    min_d = df["timestamp"].min().date()
    max_d = df["timestamp"].max().date()
    picked = st.date_input("Date range", value=(min_d, max_d),
                           min_value=min_d, max_value=max_d,
                           key=f"{key}_{min_d}_{max_d}")
    if isinstance(picked, (tuple, list)) and len(picked) == 2:
        return picked[0], picked[1]
    st.info("Pick both a start date and an end date.")
    return None


def filter_range(df, start, end, machine=None):
    day = df["timestamp"].dt.date
    out = df[(day >= start) & (day <= end)]
    if machine and machine != "All machines":
        out = out[out["machine"] == machine]
    return out


def with_source(df):
    """Add a column that labels exported data as simulated."""
    out = df.copy()
    out["data_source"] = SOURCE_LABEL
    return out


def csv_bytes(df):
    return with_source(df).to_csv(index=False).encode("utf-8")


def empty_state(message):
    st.info(message)


def line_chart_for(wide, color_map=MACHINE_COLORS):
    if wide.empty:
        st.caption("No data for this selection.")
        return
    st.line_chart(wide, color=colors_for(wide.columns, color_map))


# ------------------------------------------------------------------
# Page: Overview (from SAVED readings)
# ------------------------------------------------------------------
def show_overview():
    masthead("HMS / PLANT OVERVIEW", "Production overview",
             "Summary of machine readings saved in the database",
             [("SIMULATED DATA", True), (f"{len(MACHINE_PROFILES)} ASSETS", False)])
    demo_strip("Every number on this page is calculated from readings saved in SQLite. "
               "The readings are produced by a simulator, not by real factory machines.")

    data = load_saved(20000)
    if data.empty:
        empty_state("No saved readings yet. Open **Live Monitoring** and press "
                    "**Start**. A reading is saved every "
                    f"{st.session_state.log_interval} seconds.")
        return

    t_thr, v_thr = thresholds()
    k = an.kpis(data, t_thr, v_thr)

    cards = [
        kpi_card("Machines monitored", k["machines"], "distinct machines in the data",
                 "blue", "🏭"),
        kpi_card("Saved readings", f"{k['readings']:,}", "rows in the database",
                 "violet", "🗄️"),
        kpi_card("Units (saved samples)", f"{k['units']:,}",
                 "sum of units in saved rows", "cyan", "📦"),
        kpi_card("Alert readings", f"{k['alerts']:,}",
                 f"{k['alert_rate']:.1f}% of active readings", "amber", "⚠️"),
        kpi_card("Availability", f"{k['availability']:.1f}%",
                 "readings not in Maintenance", "green", "⏱️"),
        kpi_card("Average temperature", f"{k['avg_temp']:.1f}", "all saved readings",
                 "rose", "🌡️"),
    ]
    for col, card in zip(st.columns(6), cards):
        col.markdown(card, unsafe_allow_html=True)
    st.caption(f"Data from {k['first']} to {k['last']} · calculated metrics · "
               "units are the sum of saved samples, not total plant output.")

    left, right = st.columns([3, 2])
    with left:
        with st.container(border=True):
            st.markdown("**Production by stage** (units in saved samples)")
            stage_df = an.production_by_stage(data, MACHINE_PROFILES)
            wide, colors = wide_bars(stage_df, "stage", "units", STAGE_COLORS)
            st.bar_chart(wide, color=colors)
    with right:
        with st.container(border=True):
            st.markdown("**Status of saved readings**")
            st.markdown(segment_bar(an.status_counts(data), STATUS_COLORS),
                        unsafe_allow_html=True)
            st.caption("Share of saved readings in each status.")
            st.markdown("**Temperature trend** (saved readings)")
            line_chart_for(an.trend_wide(data, "temperature"))

    left, right = st.columns([3, 2])
    with left:
        with st.container(border=True):
            st.markdown("**Machine health: latest saved reading**")
            health = an.health_table(get_latest_readings(), MACHINE_PROFILES, t_thr, v_thr)
            if health.empty:
                st.caption("No data.")
            else:
                st.dataframe(health, hide_index=True)
            st.caption("Health is a demo rule: Warning above the threshold, "
                       "Watch within 15% of it.")
    with right:
        with st.container(border=True):
            st.markdown("**Recent alerts**")
            alerts = an.compute_alerts(data, t_thr, v_thr)
            if alerts.empty:
                st.success("No saved reading is above the demo thresholds.")
            else:
                recent = alerts.head(8).copy()
                recent["severity"] = recent["severity"].map(an.SEVERITY_ICON)
                recent["timestamp"] = recent["timestamp"].dt.strftime("%d %b %H:%M:%S")
                st.dataframe(recent[["timestamp", "machine", "severity", "trigger"]],
                             hide_index=True)

    with st.expander("How these numbers are calculated"):
        st.markdown(
            "- **Units (saved samples)** = sum of `units_produced` in saved rows. "
            "Only every logging interval is saved, so this is a sample, not total output.\n"
            "- **Availability** = saved readings not in Maintenance ÷ all saved readings.\n"
            "- **Alert reading** = a saved reading (not in Maintenance) whose temperature "
            "or vibration is above the current demo threshold.\n"
            "- **Thresholds and severity** are demonstration rules, not validated "
            "industrial limits."
        )


# ------------------------------------------------------------------
# Page: Live Monitoring
# ------------------------------------------------------------------
def show_live_monitoring():
    masthead("HMS / SHIFT MONITOR", "Live machine monitoring",
             "Machine health, output, and activity at a glance.",
             [("SIMULATED FEED", True), (f"{len(MACHINE_PROFILES)} ASSETS", False)])
    demo_strip("Readings are generated by a simulator; no factory sensors are connected.")

    b1, b2, b3, _ = st.columns([1, 1, 1.6, 3])
    b1.button("▶ Start", on_click=start_monitoring,
              disabled=st.session_state.monitoring)
    b2.button("⏹ Stop", on_click=stop_monitoring,
              disabled=not st.session_state.monitoring)
    b3.button("🗑 Reset live session", on_click=reset_session,
              help="Clears live charts, events and session totals. "
                   "Saved database records are not deleted.")

    run_every = int(st.session_state.refresh_interval) if st.session_state.monitoring else None

    # The fragment re-runs by itself every 'run_every' seconds.
    @st.fragment(run_every=run_every)
    def live_panel():
        top1, top2 = st.columns([4, 1])
        n = st.session_state.tick_count
        if st.session_state.monitoring:
            info = f" · reading #{n} · every {st.session_state.refresh_interval} s"
        else:
            info = f" · {n} readings in this session"
        top1.markdown(live_badge(st.session_state.monitoring, info),
                      unsafe_allow_html=True)
        manual = top2.button("🔄 Refresh now")

        if st.session_state.monitoring or manual:
            tick()

        df = st.session_state.latest_df
        prev = st.session_state.prev_df
        if df is None:
            st.info("No readings yet. Press **Start** or **Refresh now**.")
            return

        # ---- Summary cards, with change since the previous reading ----
        avg_t = df["Temperature"].mean()
        units_now = int(df["Units Produced"].sum())
        n_run = int((df["Status"] == "Running").sum())
        n_warn = int((df["Status"] == "Warning").sum())
        n_maint = int((df["Status"] == "Maintenance").sum())
        session_total = sum(st.session_state.session_units.values())

        ch_t = ch_u = ch_w = None
        if prev is not None:
            ch_t = avg_t - prev["Temperature"].mean()
            ch_u = units_now - int(prev["Units Produced"].sum())
            ch_w = n_warn - int((prev["Status"] == "Warning").sum())
        dt_text, dt_good = delta_info(ch_t, higher_is_better=False, decimals=1)
        du_text, du_good = delta_info(ch_u, higher_is_better=True)
        dw_text, dw_good = delta_info(ch_w, higher_is_better=False)

        cards = [
            kpi_card("Running", n_run, f"of {len(df)} machines", "green", "🟢"),
            kpi_card("Warning", n_warn, "above demo thresholds", "amber", "⚠️",
                     dw_text, dw_good),
            kpi_card("Maintenance", n_maint, "stopped", "indigo", "🔧"),
            kpi_card("Average temperature", f"{avg_t:.1f}", "all machines", "rose", "🌡️",
                     dt_text, dt_good),
            kpi_card("Units this interval", units_now, "all machines", "cyan", "📦",
                     du_text, du_good),
            kpi_card("Session units", f"{session_total:,}", "since start or reset",
                     "blue", "∑"),
        ]
        for col, card in zip(st.columns(6), cards):
            col.markdown(card, unsafe_allow_html=True)

        st.caption(f"Last update: {df['Timestamp'].max()} (simulated data) · "
                   "Arrows show change since the previous reading.")

        # ---- Machine cards ----
        section_title("Machine status")
        prev_rows = prev.set_index("Machine") if prev is not None else None
        cols = st.columns(len(df))
        for col, (_, row) in zip(cols, df.iterrows()):
            stage = MACHINE_PROFILES.get(row["Machine"], {}).get("stage", "")
            prev_row = None
            if prev_rows is not None and row["Machine"] in prev_rows.index:
                prev_row = prev_rows.loc[row["Machine"]]
            col.markdown(
                machine_card(row, stage,
                             st.session_state.temp_threshold,
                             st.session_state.vib_threshold,
                             prev=prev_row),
                unsafe_allow_html=True,
            )

        # Warnings (rule-based, NOT a failure prediction)
        warnings_df = df[df["Status"] == "Warning"]
        if warnings_df.empty:
            st.success("No machine is above the demonstration thresholds.")
        else:
            for _, row in warnings_df.iterrows():
                st.warning(f"{row['Machine']}: {warning_reason(row)}. "
                           "This is a rule-based demo warning, not proof of failure.")

        # ---- Live trend chart + event feed ----
        left, right = st.columns([2, 1])
        with left:
            with st.container(border=True):
                st.markdown("**Live trend: all machines**")
                metric = st.radio(
                    "Metric", ["Temperature", "Vibration", "Pressure", "Units Produced"],
                    horizontal=True, key="trend_metric", label_visibility="collapsed")
                buf = st.session_state.buffer
                pivot = buf.pivot_table(index="Time", columns="Machine",
                                        values=metric, aggfunc="mean")
                pivot.columns.name = None
                st.line_chart(pivot, color=colors_for(pivot.columns, MACHINE_COLORS))
                if metric == "Temperature":
                    st.caption(f"Demo warning threshold: "
                               f"{st.session_state.temp_threshold}")
                elif metric == "Vibration":
                    st.caption(f"Demo warning threshold: "
                               f"{st.session_state.vib_threshold}")
        with right:
            with st.container(border=True):
                st.markdown("**Live event feed**")
                st.markdown(event_feed(st.session_state.events),
                            unsafe_allow_html=True)
                st.caption("Live feed is session memory only. The full alert history "
                           "is on the Alerts & Maintenance page.")

        # ---- Production progress (simulated, session only) ----
        section_title("Production progress", "simulated, this session")
        target = int(st.session_state.unit_target)
        totals = st.session_state.session_units
        with st.container(border=True):
            all_units = sum(totals.values())
            st.markdown(progress_bar("All machines", all_units,
                                     target * len(MACHINE_PROFILES)),
                        unsafe_allow_html=True)
            p_cols = st.columns(len(MACHINE_PROFILES))
            for col, (machine, profile) in zip(p_cols, MACHINE_PROFILES.items()):
                col.markdown(
                    progress_bar(f"{machine} ({profile['stage']})",
                                 totals.get(machine, 0), target),
                    unsafe_allow_html=True)
            st.caption(f"Units are summed from simulated readings since the live "
                       f"session started or was reset. Target = {target} units per "
                       f"machine (configurable demo value).")

        # ---- Single machine detail ----
        section_title("Machine detail")
        machine = st.selectbox("Select machine", df["Machine"].tolist(),
                               key="detail_machine")
        detail = st.session_state.buffer
        detail = detail[detail["Machine"] == machine]
        color = MACHINE_COLORS.get(machine, "#2563eb")

        d1, d2, d3 = st.columns(3)
        for col, name in zip([d1, d2, d3], ["Temperature", "Vibration", "Pressure"]):
            with col.container(border=True):
                st.markdown(f"**{name}** (live buffer)")
                st.line_chart(detail, x="Timestamp", y=name, color=color)
        st.caption("Live charts show recent readings held in memory. "
                   "They reset when the app restarts. Saved history is in the "
                   "database.")

        st.divider()
        st.caption(
            f"Database: {get_reading_count()} readings saved in total. "
            f"Logging every {st.session_state.log_interval} s. "
            f"{st.session_state.last_saved_text}"
        )

    live_panel()


# ------------------------------------------------------------------
# Page: Machine History (from SAVED readings)
# ------------------------------------------------------------------
def show_history():
    masthead("HMS / HISTORY", "Machine history",
             "Trends and statistics from saved readings",
             [("RECORDED SIMULATED DATA", True)])

    data = load_saved()
    if data.empty:
        empty_state("No saved readings yet. Start **Live Monitoring** to create some.")
        return

    f1, f2 = st.columns([1, 2])
    machine = f1.selectbox("Machine", ["All machines"] + sorted(data["machine"].unique()),
                           key="hist_machine")
    with f2:
        picked = date_controls(data, "hist_range")
    if picked is None:
        return

    sub = filter_range(data, picked[0], picked[1], machine)
    if sub.empty:
        empty_state("No saved readings for this machine and date range.")
        return

    cards = [
        kpi_card("Readings", f"{len(sub):,}", "in this selection", "blue", "🗄️"),
        kpi_card("Avg temperature", f"{sub['temperature'].mean():.1f}",
                 f"max {sub['temperature'].max():.1f}", "rose", "🌡️"),
        kpi_card("Avg vibration", f"{sub['vibration'].mean():.2f}",
                 f"max {sub['vibration'].max():.2f}", "violet", "📳"),
        kpi_card("Avg pressure", f"{sub['pressure'].mean():.2f}",
                 f"max {sub['pressure'].max():.2f}", "cyan", "🧭"),
        kpi_card("Units (saved samples)", f"{int(sub['units_produced'].sum()):,}",
                 "sum of saved rows", "green", "📦"),
        kpi_card("Warning readings", int((sub["status"] == "Warning").sum()),
                 "stored status", "amber", "⚠️"),
    ]
    for col, card in zip(st.columns(6), cards):
        col.markdown(card, unsafe_allow_html=True)

    t_thr, v_thr = thresholds()
    tab1, tab2, tab3, tab4 = st.tabs(
        ["📈 Sensor trends", "🏭 Production", "🚦 Status history", "📋 Statistics & data"])

    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            with st.container(border=True):
                st.markdown("**Temperature**")
                line_chart_for(an.trend_wide(sub, "temperature"))
                st.caption(f"Demo warning threshold: {t_thr:g}")
        with c2:
            with st.container(border=True):
                st.markdown("**Vibration**")
                line_chart_for(an.trend_wide(sub, "vibration"))
                st.caption(f"Demo warning threshold: {v_thr:g}")
        with st.container(border=True):
            st.markdown("**Pressure**")
            line_chart_for(an.trend_wide(sub, "pressure"))

    with tab2:
        c1, c2 = st.columns(2)
        with c1:
            with st.container(border=True):
                st.markdown("**Units over time** (saved samples)")
                line_chart_for(an.trend_wide(sub, "units_produced"))
        with c2:
            with st.container(border=True):
                st.markdown("**Units by machine**")
                prod = an.production_summary(sub, MACHINE_PROFILES)
                wide, colors = wide_bars(prod, "Machine", "Units (saved samples)",
                                         MACHINE_COLORS)
                st.bar_chart(wide, color=colors)

    with tab3:
        c1, c2 = st.columns([3, 2])
        with c1:
            with st.container(border=True):
                st.markdown("**Readings per status, by machine**")
                table = pd.crosstab(sub["machine"], sub["status"])
                table.columns.name = None
                table.index.name = None
                st.bar_chart(table, color=colors_for(table.columns, STATUS_COLORS))
        with c2:
            with st.container(border=True):
                st.markdown("**Status share**")
                st.markdown(segment_bar(an.status_counts(sub), STATUS_COLORS),
                            unsafe_allow_html=True)

    with tab4:
        st.markdown("**Minimum, maximum and average per machine**")
        st.dataframe(an.summary_stats(sub), hide_index=True)
        st.markdown("**Saved readings** (newest first, first 500 rows shown)")
        shown = sub.sort_values("timestamp", ascending=False)
        st.dataframe(shown.head(500), hide_index=True)
        st.download_button("Download this selection (CSV)", data=csv_bytes(shown),
                           file_name="machine-history.csv", mime="text/csv")


# ------------------------------------------------------------------
# Page: Alerts & Maintenance (rule based, from SAVED readings)
# ------------------------------------------------------------------
def show_alerts():
    masthead("HMS / ALERTS", "Alerts & maintenance",
             "Rule-based warnings found in saved readings",
             [("DEMO RULES", True)])
    demo_strip("Alerts use demonstration thresholds. A warning is not proof of failure "
               "and this is not predictive maintenance.")

    data = load_saved()
    if data.empty:
        empty_state("No saved readings yet. Start **Live Monitoring** to create some.")
        return

    t_thr, v_thr = thresholds()
    all_alerts = an.compute_alerts(data, t_thr, v_thr)
    st.caption(f"Current rules: temperature above {t_thr:g} or vibration above {v_thr:g}. "
               "Severity: Medium = over the limit, High = 7% or more over, "
               "Critical = 15% or more over.")

    f1, f2, f3 = st.columns([1, 1.4, 2])
    machine = f1.selectbox("Machine", ["All machines"] + sorted(data["machine"].unique()),
                           key="alert_machine")
    severities = f2.multiselect("Severity", an.SEVERITY_ORDER, default=an.SEVERITY_ORDER,
                                key="alert_severity")
    with f3:
        picked = date_controls(data, "alert_range")
    if picked is None:
        return

    alerts = all_alerts
    if not alerts.empty:
        day = alerts["timestamp"].dt.date
        alerts = alerts[(day >= picked[0]) & (day <= picked[1])]
        if machine != "All machines":
            alerts = alerts[alerts["machine"] == machine]
        alerts = alerts[alerts["severity"].isin(severities)]

    counts = alerts["severity"].value_counts() if not alerts.empty else {}
    cards = [
        kpi_card("Total alerts", f"{len(alerts):,}", "in this selection", "blue", "🚨"),
        kpi_card("Critical", int(counts.get("Critical", 0)), "15%+ over limit", "rose", "🔴"),
        kpi_card("High", int(counts.get("High", 0)), "7%+ over limit", "orange", "🟠"),
        kpi_card("Medium", int(counts.get("Medium", 0)), "just over limit", "amber", "🟡"),
        kpi_card("Machines affected",
                 int(alerts["machine"].nunique()) if not alerts.empty else 0,
                 f"of {data['machine'].nunique()} monitored", "violet", "🏭"),
    ]
    for col, card in zip(st.columns(5), cards):
        col.markdown(card, unsafe_allow_html=True)

    if alerts.empty:
        st.success("No alerts match this selection.")
        return

    left, right = st.columns([2, 3])
    with left:
        with st.container(border=True):
            st.markdown("**Alerts per machine**")
            per_machine = alerts.groupby("machine").size().reset_index(name="alerts")
            wide, colors = wide_bars(per_machine, "machine", "alerts", MACHINE_COLORS)
            st.bar_chart(wide, color=colors)
    with right:
        with st.container(border=True):
            st.markdown("**Alert summary**")
            st.dataframe(an.alert_summary(alerts), hide_index=True)

    section_title("Maintenance recommendations", "predefined demo rules")
    latest = alerts.sort_values("timestamp").groupby("machine").tail(1)
    for _, row in latest.sort_values("machine").iterrows():
        n = int((alerts["machine"] == row["machine"]).sum())
        st.markdown(
            advice_card(row["machine"], row["severity"], row["trigger"], n,
                        row["timestamp"].strftime("%d %b %H:%M:%S"),
                        row["recommendation"]),
            unsafe_allow_html=True,
        )

    section_title("Alert history", "newest first")
    shown = alerts.copy()
    shown["severity"] = shown["severity"].map(an.SEVERITY_ICON)
    st.dataframe(shown.head(300), hide_index=True)
    st.caption("Showing up to 300 rows. Download for the full list.")
    st.download_button("Download alerts (CSV)", data=csv_bytes(alerts),
                       file_name="alerts.csv", mime="text/csv")

    maint = data[data["status"] == "Maintenance"]
    with st.expander("Maintenance periods recorded by the simulator"):
        if maint.empty:
            st.caption("No saved reading was taken during Maintenance.")
        else:
            st.dataframe(maint.groupby("machine").size()
                         .reset_index(name="Maintenance readings")
                         .rename(columns={"machine": "Machine"}), hide_index=True)


# ------------------------------------------------------------------
# Page: Reports
# ------------------------------------------------------------------
def show_reports():
    masthead("HMS / REPORTS", "Reports",
             "Summaries for a selected machine and date range",
             [("SIMULATED DATA", True)])
    demo_strip("Reports contain simulated readings saved in SQLite. Every CSV has a "
               "data_source column that says so.")

    data = load_saved()
    if data.empty:
        empty_state("No saved readings yet. Start **Live Monitoring** to create some.")
        return

    f1, f2 = st.columns([1, 2])
    machine = f1.selectbox("Machine", ["All machines"] + sorted(data["machine"].unique()),
                           key="report_machine")
    with f2:
        picked = date_controls(data, "report_range")
    if picked is None:
        return

    sub = filter_range(data, picked[0], picked[1], machine)
    if sub.empty:
        empty_state("No saved readings for this machine and date range.")
        return

    t_thr, v_thr = thresholds()
    alerts = an.compute_alerts(sub, t_thr, v_thr)

    st.markdown(
        f"**Report details:** generated {datetime.now():%d %b %Y %H:%M} · "
        f"{machine} · {picked[0]} to {picked[1]} · {len(sub):,} readings · "
        f"thresholds: temperature {t_thr:g}, vibration {v_thr:g} (demo)")

    tab1, tab2, tab3, tab4 = st.tabs(
        ["🏭 Production summary", "⚙️ Machine performance", "🚨 Alert summary", "🗄️ Raw readings"])

    with tab1:
        prod = an.production_summary(sub, MACHINE_PROFILES)
        st.dataframe(prod, hide_index=True)
        st.caption("Units are the sum of saved samples, not total plant output.")
        st.download_button("Download production summary (CSV)", data=csv_bytes(prod),
                           file_name="production-summary.csv", mime="text/csv")
    with tab2:
        perf = an.summary_stats(sub)
        st.dataframe(perf, hide_index=True)
        st.download_button("Download machine performance (CSV)", data=csv_bytes(perf),
                           file_name="machine-performance.csv", mime="text/csv")
    with tab3:
        summary = an.alert_summary(alerts)
        if summary.empty:
            st.success("No alerts in this selection.")
        else:
            st.dataframe(summary, hide_index=True)
            st.download_button("Download alert summary (CSV)", data=csv_bytes(summary),
                               file_name="alert-summary.csv", mime="text/csv")
    with tab4:
        raw = sub.sort_values("timestamp", ascending=False)
        st.dataframe(raw.head(500), hide_index=True)
        st.caption("Showing up to 500 rows. Download for all rows.")
        st.download_button("Download raw readings (CSV)", data=csv_bytes(raw),
                           file_name="readings.csv", mime="text/csv")

    st.caption("A formatted PDF report is planned as a future enhancement.")


# ------------------------------------------------------------------
# Page: your original dashboard (kept as it was)
# ------------------------------------------------------------------
def show_sample_dashboard():
    banner("Production Performance Monitoring System",
           "Original sample dashboard (hardcoded demonstration values)")

    st.info("Demo dashboard using sample data.")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Production", "850", "50")
    col2.metric("Target Production", "1000")
    col3.metric("Efficiency", "85%")
    col4.metric("Downtime", "45 min")

    st.divider()
    st.subheader("Production Summary")
    st.write("Today's production overview")

    stage_data = pd.DataFrame({
        "Stage": ["Cutting", "Assembly", "Quality Check", "Packaging"],
        "Units": [250, 300, 180, 120],
    })
    wide, colors = wide_bars(stage_data, "Stage", "Units", STAGE_COLORS)
    st.bar_chart(wide, color=colors)
    st.caption("Note: All figures are sample values for demonstration.")

    st.divider()
    st.subheader("Production Details")

    production_data = {
        "Machine": ["M001", "M002", "M003", "M004"],
        "Stage": ["Cutting", "Assembly", "Quality Check", "Packaging"],
        "Units Produced": [250, 300, 180, 120],
        "Status": ["Running", "Running", "Maintenance", "Running"],
    }

    st.subheader("Machine Status Monitoring")
    df = pd.DataFrame(production_data)

    st.write("Edit machine details below")
    edited_df = st.data_editor(df, num_rows="dynamic", key="sample_editor")

    st.write("Filter machines by status")
    status_filter = st.selectbox("Select status", ["All", "Running", "Maintenance"],
                                 key="sample_status_filter")

    if status_filter == "All":
        filtered_data = edited_df
    else:
        filtered_data = edited_df[edited_df["Status"] == status_filter]

    st.dataframe(filtered_data)

    st.write("Machine Status Summary")
    status_table = edited_df["Status"].value_counts()
    st.bar_chart(status_table)

    st.divider()
    st.subheader("Machine Sensor Monitoring")
    st.write("Simulated sensor readings")

    if st.button("Generate New Machine Readings"):
        sensor_df = st.session_state.sim.next_readings()
        saved = save_readings(sensor_df)
        st.session_state["sensor_df"] = sensor_df
        st.success(f"Machine readings saved successfully! ({saved} new rows)")

    if "sensor_df" in st.session_state:
        sensor_df = st.session_state["sensor_df"]
        st.dataframe(sensor_df)

        st.subheader("Temperature Monitoring")
        st.bar_chart(sensor_df, x="Machine", y="Temperature", color="#e11d48")

        st.subheader("Machine Alerts")
        alerts = sensor_df[sensor_df["Status"] == "Warning"]
        if not alerts.empty:
            st.warning("Some machines require attention.")
            st.dataframe(alerts)
        else:
            st.success("All simulated machines are running normally.")

    st.divider()
    st.subheader("Machine Reading History")

    history_df = get_readings(limit=200)
    if not history_df.empty:
        st.write("Latest 200 saved machine readings")
        st.dataframe(history_df)
        st.metric("Total Saved Readings", get_reading_count())
    else:
        st.info("No machine readings saved yet.")


# ------------------------------------------------------------------
# Page: User management (Admin only)
# ------------------------------------------------------------------
def show_user_management():
    banner("User Management", "Admin only: create and view user accounts")

    if not is_admin:
        st.error("You do not have permission to view this page.")
        return

    st.subheader("Existing users")
    users_df = list_users()
    if users_df.empty:
        st.info("No users found.")
    else:
        st.dataframe(users_df)

    st.subheader("Add a new user")
    with st.form("add_user_form", clear_on_submit=True):
        new_username = st.text_input("Username (letters, numbers, underscore)")
        new_password = st.text_input("Password (at least 8 characters)",
                                     type="password")
        new_role = st.selectbox("Role", ROLES, index=1)
        create = st.form_submit_button("Create user")

    if create:
        ok, message = add_user(new_username, new_password, new_role)
        if ok:
            st.success(message)
        else:
            st.error(message)


# ------------------------------------------------------------------
# Page: About & Method
# ------------------------------------------------------------------
def show_about():
    masthead("HMS / PROJECT", "About & method",
             "What this system does, how it works, and its limits",
             [("CAPSTONE PROJECT", False)])
    st.markdown(
        """
**Real-Time Production Performance Monitoring System** for a medical manufacturing
environment (HMS Medical Systems, Chennai, used as the organisational context).

**Data flow:** Python machine simulator → validate → store in SQLite → calculate with
pandas → show in Streamlit → review history → download reports.

**Technology:** Python, Streamlit, Pandas, SQLite.

**What is real and what is not**
- The machine readings are **synthetic**. No real machine or industrial sensor is connected.
- Thresholds, severity levels, targets and maintenance advice are **demonstration rules**,
  not validated industrial limits.
- Warnings are **rule based**. They do not prove a failure and are not predictive maintenance.
- Machine learning is **not included**, because there is no labelled failure data to
  train and validate a model. It is listed as a future enhancement.

**Calculated metrics**
- *Availability* = saved readings not in Maintenance ÷ all saved readings.
- *Alert reading* = a reading above the temperature or vibration threshold.
- *Units (saved samples)* = sum of saved `units_produced` values.
- *Production progress* = simulated units this session ÷ configurable target.

**Future enhancements:** real sensor connection (for example OPC UA or MQTT), a trained and
validated predictive-maintenance model, a formatted PDF report, and a saved alerts table.
"""
    )


# ------------------------------------------------------------------
# Show the selected page
# ------------------------------------------------------------------
if page == NAV_OVERVIEW:
    show_overview()
elif page == NAV_LIVE:
    show_live_monitoring()
elif page == NAV_HISTORY:
    show_history()
elif page == NAV_ALERTS:
    show_alerts()
elif page == NAV_REPORTS:
    show_reports()
elif page == NAV_USERS:
    show_user_management()
elif page == NAV_SAMPLE:
    show_sample_dashboard()
else:
    show_about()