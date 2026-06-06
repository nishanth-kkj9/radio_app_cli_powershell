"""
core/config.py — PowerShell Radio Pro configuration
Windows-native build: python-vlc / libvlc, no WSL2, no cava.
"""

# ── Network ────────────────────────────────────────────────────────────────
API_TIMEOUT    = 8        # seconds per API host attempt
ALIVE_TIMEOUT  = (8, 5)  # (connect, read) for liveness checks

# ── Results / workers ──────────────────────────────────────────────────────
MAX_RESULTS = 30
MAX_WORKERS = 10          # concurrent alive-check threads

# ── Stream URL scheme allowlist ────────────────────────────────────────────
ALLOWED_STREAM_SCHEMES = {"http", "https", "rtsp", "rtp", "mms", "rtmp"}

# ── VLC options (passed to vlc.Instance) ──────────────────────────────────
VLC_INSTANCE_ARGS = [
    "--no-video",
    "--quiet",
    "--network-caching=3000",
    "--live-caching=3000",
    "--file-caching=3000",
    "--http-reconnect",
    "--sout-mux-caching=3000",
]

# ── Health / reconnect ─────────────────────────────────────────────────────
HEALTH_INTERVAL    = 8    # seconds between health checks
MAX_RECONNECT      = 5
RECONNECT_DELAYS   = [2, 4, 8, 16, 30]   # seconds per attempt

# ── Cache / refresh ────────────────────────────────────────────────────────
CACHE_TTL         = 600   # 10 min
REFRESH_INTERVAL  = 600   # 10 min

# ── Categories (label, key) ────────────────────────────────────────────────
CATEGORIES = [
    ("Top Charts", "top"),
    ("Hindi",      "hindi"),
    ("Kannada",    "kannada"),
    ("Pop",        "pop"),
    ("Rock",       "rock"),
    ("Jazz",       "jazz"),
    ("Classical",  "classical"),
    ("News",       "news"),
    ("Favorites",  "favorites"),
]

# ── Multi-query map ────────────────────────────────────────────────────────
QUERY_MAP = {
    "top":       ["top hits", "india"],
    "hindi":     ["hindi", "bollywood"],
    "kannada":   ["kannada", "karnataka"],
    "pop":       ["pop", "pop hits"],
    "rock":      ["rock", "classic rock"],
    "jazz":      ["jazz", "smooth jazz"],
    "classical": ["classical", "orchestra"],
    "news":      ["news", "bbc news"],
}

# Categories pre-loaded in the background (all except "top")
PRELOAD_CATEGORIES = [
    "hindi", "kannada", "pop", "rock", "jazz", "classical", "news"
]
