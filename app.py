# app.py — autoplay+loop after "Start viewing"
import os, csv, base64, mimetypes
from pathlib import Path
from datetime import datetime
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Stitch Viewer", layout="centered")

# ---------- Helpers ----------
def normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={
        "Stitch video": "stitch_video",
        "Stitch Video": "stitch_video",
        "Stitch_video": "stitch_video",
        "Start": "start",
        "End": "end",
        "Condition": "condition",
        "condition": "condition",
    })
    need = {"stitch_video", "start", "end", "condition"}
    if not need.issubset(df.columns):
        rename = {}
        for c in df.columns:
            lc = c.lower().strip()
            if "stitch" in lc and "video" in lc: rename[c] = "stitch_video"
            elif lc == "start": rename[c] = "start"
            elif lc == "end": rename[c] = "end"
            elif lc.startswith("cond"): rename[c] = "condition"
        df = df.rename(columns=rename)
    missing = [c for c in ["stitch_video", "start", "end", "condition"] if c not in df.columns]
    if missing:
        raise ValueError(f"CSV is missing required columns: {missing}")
    return df[["stitch_video", "start", "end", "condition"]].copy()

def mmss_to_seconds(s):
    s = str(s).strip()
    if not s or s.lower() in {"nan", "none"}:
        return 0
    parts = s.split(":")
    try:
        if len(parts) == 2:
            m, sec = map(int, parts); return m*60 + sec
        if len(parts) == 3:
            h, m, sec = map(int, parts); return h*3600 + m*60 + sec
        return int(float(s))
    except Exception:
        return 0

def append_log_row(log_path: Path, stitch_video, start_dt, end_dt):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not log_path.exists()
    with log_path.open("a", newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["stitch_video", "start_time", "end_time"])
        w.writerow([
            str(stitch_video),
            start_dt.isoformat() if start_dt else "",
            end_dt.isoformat()
        ])
        f.flush(); os.fsync(f.fileno())
    st.toast(f"Logged: {stitch_video}", icon="✅")

def to_data_uri(video_path: str) -> str:
    """Read a local video and return a data: URI for HTML5 <video>."""
    mime, _ = mimetypes.guess_type(video_path)
    if mime is None:
        # default to mp4 if unknown
        mime = "video/mp4"
    with open(video_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"

def html_video_player(src_uri: str, start_seconds: int, autoplay=True, loop=True):
    """Embed a custom HTML5 video tag with optional autoplay+loop and start offset."""
    # playsinline avoids full-screen auto-switching on some systems
    a = "autoplay" if autoplay else ""
    l = "loop" if loop else ""
    html = f"""
    <video id="stitchvid" controls {a} {l} playsinline style="width:100%;max-height:70vh;">
      <source src="{src_uri}">
      Your browser does not support the video tag.
    </video>
    <script>
      const v = document.getElementById('stitchvid');
      const startAt = {int(start_seconds)};
      function seek() {{
        try {{
          if (Math.abs((v.currentTime||0) - startAt) > 0.5) v.currentTime = startAt;
        }} catch (e) {{}}
      }}
      v.addEventListener('loadedmetadata', seek);
      // If metadata was already loaded, try immediately too:
      if (v.readyState >= 1) seek();
    </script>
    """
    st.html(html, height=420)

# ---------- Session state ----------
ss = st.session_state
ss.setdefault("df", None)
ss.setdefault("idx", 0)
ss.setdefault("view_start_ts", None)
ss.setdefault("started_autoplay", False)  # whether to use autoplay+loop for current row

# Your default base folder
ss.setdefault("base", "/Users/rafalko/Desktop/GradioHF/VR_stitch_study/Video/stitches")

# Per-session log file with date + hour-minute, under ./logs
if "log_path" not in ss:
    logs_dir = Path.cwd() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    ss["log_path"] = logs_dir / f"log_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.csv"
log_path = Path(ss["log_path"])

# ---------- UI ----------
st.title("🧵 Stitch Viewer")

st.write("Upload a CSV with columns **Stitch video**, **Start**, **End**, **Condition**. "
         "Video paths can be absolute, or relative to the base folder below.")

uploaded = st.file_uploader("Upload CSV", type=["csv"])

# Base folder input (prefilled with your default)
ss["base"] = st.text_input(
    "(Optional) Base folder for videos",
    value=ss["base"],
    placeholder="/absolute/path/to/videos"
)

st.caption(f"Logs append to: **{log_path}**")

# ---------- Load CSV ----------
if uploaded is not None:
    try:
        raw = pd.read_csv(uploaded)
        df = normalize_cols(raw)
        ss["df"] = df.reset_index(drop=True)
        ss["idx"] = 0
        ss["view_start_ts"] = None
        ss["started_autoplay"] = False
        st.success(f"Loaded {len(df)} rows.")
    except Exception as e:
        st.error(f"Failed to read/normalize CSV: {e}")

if ss.get("df") is None or len(ss["df"]) == 0:
    st.stop()

df = ss["df"]
i = ss["idx"]
row = df.iloc[i]

# Condition banner
cond = str(row["condition"]).strip().lower()
if cond == "stereo":
    st.markdown("### 🥽 Condition: **STEREO** — use VR goggles")
else:
    st.markdown("### 🖥️ Condition: **MONO** — use computer screen")

# Resolve path
stitch_rel = str(row["stitch_video"]).strip()
if ss["base"] and not os.path.isabs(stitch_rel) and not stitch_rel.startswith("http"):
    stitch_path = os.path.join(ss["base"], stitch_rel)
else:
    stitch_path = stitch_rel

st.caption(f"Clip: **{row['stitch_video']}** | Watch from **{row['start']}** to **{row['end']}**")

# -------- Video player --------
start_seconds = mmss_to_seconds(row["start"])
if not os.path.exists(stitch_path) and not stitch_path.startswith("http"):
    st.warning(f"Video not found: {stitch_path}")
else:
    if ss["started_autoplay"]:
        # Use custom HTML5 player with autoplay + loop and seek to start
        try:
            src_uri = stitch_path if stitch_path.startswith("http") else to_data_uri(stitch_path)
            html_video_player(src_uri, start_seconds, autoplay=True, loop=True)
        except Exception as e:
            st.error(f"Could not render custom player: {e}")
            st.video(stitch_path, start_time=start_seconds)  # fallback
    else:
        # Before starting, show normal player (no autoplay/loop)
        st.video(stitch_path, start_time=start_seconds)

# -------- Controls --------
c1, c2, c3 = st.columns([1,1,2])
with c1:
    if st.button("▶️ Start viewing", use_container_width=True):
        ss["view_start_ts"] = datetime.now()
        ss["started_autoplay"] = True  # switch to looping, autoplaying player
with c2:
    if st.button("⬅️ Prev", use_container_width=True, disabled=(i == 0)):
        if ss["view_start_ts"] is not None:
            append_log_row(log_path, row["stitch_video"], ss["view_start_ts"], datetime.now())
        ss["idx"] = max(0, i - 1)
        ss["view_start_ts"] = None
        ss["started_autoplay"] = False  # require Start again on the new row
with c3:
    if st.button("Next ➡️", use_container_width=True, disabled=(i >= len(df) - 1)):
        if ss["view_start_ts"] is not None:
            append_log_row(log_path, row["stitch_video"], ss["view_start_ts"], datetime.now())
        ss["idx"] = min(len(df) - 1, i + 1)
        ss["view_start_ts"] = None
        ss["started_autoplay"] = False  # require Start again on the new row

st.progress((i + 1) / len(df))

# Recent log preview
with st.expander("Show recent log entries"):
    st.code(str(log_path))
    if log_path.exists():
        try:
            log_df = pd.read_csv(log_path)
            st.dataframe(log_df.tail(20), use_container_width=True)
        except Exception as e:
            st.write(f"Could not read log yet: {e}")
    else:
        st.write("No log file yet.")
