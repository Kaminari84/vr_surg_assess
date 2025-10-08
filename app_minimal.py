# app.py (minimal: consistent height player + rich logging of all CSV columns)
import os, base64, mimetypes, csv
from pathlib import Path
from datetime import datetime
import pandas as pd
import streamlit as st
from streamlit.components.v1 import html as components_html

st.set_page_config(page_title="Stitch Viewer (minimal)", layout="wide")

# ---------- compat rerun ----------
def do_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

# ---------- helpers ----------
def to_data_uri(video_path: str) -> str:
    """Read local video and return a data: URI (stable for autoplay)."""
    mime, _ = mimetypes.guess_type(video_path)
    if mime is None: mime = "video/mp4"
    with open(video_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"

# One template used for BOTH idle & playing states (consistent height)
HTML_PLAYER_TEMPLATE = """
<style>
  #player-wrap {{ width: 100%; }}
  #player-wrap video {{
    width: 100%;
    height: {H}px;       /* fixed height so layout doesn't jump */
    object-fit: contain;
    background: #000;
    border-radius: 8px;
  }}
</style>

<div id="player-wrap">
  <video id="stitchvid" controls {AUTOPLAY} {MUTED} playsinline preload="{PRELOAD}">
    <source src="{SRC}">
    Your browser does not support the video tag.
  </video>
</div>

<script>
  const v = document.getElementById('stitchvid');

  function ensurePlayIfNeeded() {{
    {PLAY_JS}
  }}

  // ---- Scroll helpers (works in Streamlit's top page) ----
  function scrollToControls(offset=120) {{
    try {{
      const topWin = window.top;
      const topDoc = (topWin && topWin.document) ? topWin.document : null;
      if (!topDoc) return;

      const target = topDoc.getElementById('controls-anchor') || topDoc.getElementById('heading-anchor');
      if (!target) return;

      const rect = target.getBoundingClientRect();
      const pageY = (topWin.pageYOffset || topDoc.documentElement.scrollTop || topDoc.body.scrollTop || 0);
      const y = Math.max(0, rect.top + pageY - offset);
      topWin.scrollTo({{ top: y, behavior: 'auto' }});
    }} catch (e) {{}}
  }}

  function onFSChange() {{
    const leftFS = !document.fullscreenElement && !document.webkitFullscreenElement;
    if (leftFS) {{
      // Do a few attempts because layout collapses over a couple of frames
      scrollToControls(120);                                // right away
      setTimeout(() => scrollToControls(120), 80);          // after layout settles
      requestAnimationFrame(() => scrollToControls(120));   // next frame
    }}
  }}

  document.addEventListener('fullscreenchange', onFSChange);
  document.addEventListener('webkitfullscreenchange', onFSChange);

  v.addEventListener('loadedmetadata', ensurePlayIfNeeded);
  if (v.readyState >= 1) ensurePlayIfNeeded();
</script>
"""



def render_player(src_uri: str, play: bool, height_px: int = 540):
    html = HTML_PLAYER_TEMPLATE.format(
        SRC=src_uri,
        AUTOPLAY=("autoplay" if play else ""),
        MUTED=("muted" if play else ""),        # autoplay needs muted
        PRELOAD=("auto" if play else "metadata"),
        H=height_px,
        PLAY_JS=("try { const p=v.play(); if(p&&p.catch){p.catch(()=>{});} } catch(e){}" if play else "// not playing"),
    )
    components_html(html, height=height_px + 30, scrolling=False)

# ---------- session state ----------
ss = st.session_state
ss.setdefault("df", None)
ss.setdefault("csv_cols", None)      # full original CSV column order
ss.setdefault("i", 0)
ss.setdefault("view_start", None)    # datetime when START pressed (None = not playing)
ss.setdefault("stopped", False)      # True after STOP until NEXT/START
ss.setdefault("autoplay", False)     # True right after START to trigger autoplay
ss.setdefault("base", "/Users/rafalko/Desktop/GradioHF/VR_stitch_study/Video/stitches")

# near the top, before the title
st.markdown('<div id="heading-anchor"></div>', unsafe_allow_html=True)

st.title("🧵 Stitch Viewer (minimal)")
csv_file = st.file_uploader("Upload CSV", type=["csv"])
ss["base"] = st.text_input("(Optional) Base folder for videos", ss["base"])

# Per-session log filename with date + hour-minute (and make path absolute)
if "log_path" not in ss:
    logs_dir = Path.cwd() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    ss["log_path"] = logs_dir / f"log_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.csv"
log_path: Path = Path(ss["log_path"])
st.caption(f"Logs append to: **{log_path}**")

# Load CSV once (requires only Stitch video, Condition; keeps all extra cols)
if csv_file and ss["df"] is None:
    df = pd.read_csv(csv_file)
    df = df.rename(columns={
        "stitchvideo": "stitch_video",
        "stitch video": "stitch_video",
        "Stitch video": "stitch_video",
        "Stitch Video": "stitch_video",
        "Condition": "condition",
        "condition": "condition",
    })
    needed = {"stitch_video", "condition"}
    missing = needed - set(df.columns)
    if missing:
        st.error(f"Missing columns: {missing} (required: Stitch video, Condition)")
    else:
        # Keep ALL original columns (pass-through), but ensure stitch/condition exist
        ss["csv_cols"] = list(df.columns)
        ss["df"] = df.reset_index(drop=True)
        ss["i"] = 0
        ss["view_start"] = None
        ss["stopped"] = False
        ss["autoplay"] = False
        st.success(f"Loaded {len(df)} rows with columns: {', '.join(ss['csv_cols'])}")

def append_log_row(row_series: pd.Series, start_dt: datetime, end_dt: datetime):
    """Append a row to log: include ALL original CSV columns + start_time/end_time."""
    if start_dt is None or end_dt is None:
        return
    # Prepare header: original CSV columns + timestamps
    base_cols = ss["csv_cols"] or []
    header = base_cols + ["start_time", "end_time"]

    # Make sure the log has the header once
    write_header = not log_path.exists()
    with log_path.open("a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(header)
        # Build row values in the same order as header
        row_dict = row_series.to_dict()
        values = [row_dict.get(c, "") for c in base_cols] + [start_dt.isoformat(), end_dt.isoformat()]
        writer.writerow(values)
        f.flush()
        os.fsync(f.fileno())

if ss["df"] is None:
    st.stop()

# ---------- current row ----------
df, i = ss["df"], ss["i"]
row = df.iloc[i]
cond = str(row["condition"]).strip().lower()
st.markdown(
    "### 🥽 **STEREO** — use VR goggles" if cond == "stereo"
    else "### 🖥️ **MONO** — use computer screen"
)

# Status line
if ss["view_start"] is not None:
    st.success("▶️ **PLAYING the video to assess — press STOP when done, then NEXT**")
elif ss["stopped"]:
    st.info("✅ **Video assessed, press NEXT to move on to the next one**")
else:
    st.warning("⏳ **Waiting to press START**")

# Resolve video path (allow relative)
path = str(row["stitch_video"]).strip()
if ss["base"] and not os.path.isabs(path) and not path.startswith("http"):
    path = os.path.join(ss["base"], path)

st.write(f"**Clip:** {row['stitch_video']}")

# Single, consistent player (same height before/after START)
if not os.path.exists(path) and not str(path).startswith("http"):
    st.warning(f"Video not found: {path}")
else:
    try:
        src_uri = path if str(path).startswith("http") else to_data_uri(path)
        render_player(src_uri, play=ss["autoplay"], height_px=540)
    except Exception as e:
        st.error(f"Custom player error: {e}")


# right ABOVE the buttons (controls block)
st.markdown('<div id="controls-anchor"></div>', unsafe_allow_html=True)

# ---------- controls (single action per run, then rerun) ----------
c1, c2, c3 = st.columns(3)
start_clicked = c1.button("▶️ START", key="btn_start", disabled=(ss["view_start"] is not None))
stop_clicked  = c2.button("⏹ STOP",  key="btn_stop",  disabled=(ss["view_start"] is None))
next_disabled = (i >= len(df)-1) or (not ss["stopped"])
next_clicked  = c3.button("Next ➡️", key="btn_next", disabled=next_disabled)

if start_clicked:
    if ss["view_start"] is None:
        ss["view_start"] = datetime.now()
    ss["stopped"] = False
    ss["autoplay"] = True
    do_rerun()

elif stop_clicked:
    if ss["view_start"] is not None:
        append_log_row(row, ss["view_start"], datetime.now())
    ss["view_start"] = None
    ss["stopped"] = True
    ss["autoplay"] = False
    do_rerun()

elif next_clicked:
    ss["i"] = min(len(df)-1, i+1)
    ss["view_start"] = None
    ss["stopped"] = False
    ss["autoplay"] = False
    do_rerun()

st.progress((i+1)/len(df))
