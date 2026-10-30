"""Render the past year of GitHub contributions as an animated ECG trace.

Each week is one heartbeat: no contributions -> flatline, more contributions ->
a taller QRS spike. Output: assets/heartbeat.svg

Usage: GITHUB_TOKEN=... python scripts/heartbeat.py [login]
"""

import json
import math
import os
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

LOGIN = sys.argv[1] if len(sys.argv) > 1 else "MuhammadMaheem"
OUT = Path(__file__).resolve().parent.parent / "assets" / "heartbeat.svg"

W, H = 900, 240
LEFT, RIGHT = 30, 30
BASE_Y = 160          # isoelectric line
MAX_SPIKE = 92        # tallest R wave in px

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def fetch_calendar(login: str) -> tuple[int, list[tuple[date, int]]]:
    """Return (total, [(week_start, contributions_that_week), ...])."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN (or GH_TOKEN) is required")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": login}}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if "errors" in payload:
        sys.exit(f"GraphQL error: {payload['errors']}")
    cal = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    weeks = [
        (date.fromisoformat(w["contributionDays"][0]["date"]),
         sum(d["contributionCount"] for d in w["contributionDays"]))
        for w in cal["weeks"]
    ]
    return cal["totalContributions"], weeks


def beat(x0: float, w: float, amp: float) -> list[tuple[float, float]]:
    """One PQRST complex inside [x0, x0 + w]. amp == 0 -> flatline."""
    b = BASE_Y
    if amp <= 0:
        return [(x0 + w, b)]
    u = w / 14
    p = amp * 0.12
    return [
        (x0 + 2 * u, b),
        (x0 + 3 * u, b - p),          # P wave
        (x0 + 4 * u, b),
        (x0 + 5.5 * u, b + amp * 0.10),  # Q
        (x0 + 6.5 * u, b - amp),      # R
        (x0 + 7.5 * u, b + amp * 0.28),  # S
        (x0 + 8.5 * u, b),
        (x0 + 10 * u, b - amp * 0.20),   # T wave
        (x0 + 11.5 * u, b),
        (x0 + w, b),
    ]


def render(total: int, window: list[tuple[date, int]]) -> str:
    counts = [c for _, c in window]
    peak = max(counts) if counts else 0
    span = W - LEFT - RIGHT
    step = span / len(window)

    pts: list[tuple[float, float]] = [(LEFT, BASE_Y)]
    for i, c in enumerate(counts):
        amp = 0 if c == 0 else 10 + (MAX_SPIKE - 10) * math.log1p(c) / math.log1p(max(peak, 1))
        pts += beat(LEFT + i * step, step, amp)

    d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts)
    length = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))

    last90 = sum(counts[-13:])
    active = sum(1 for c in counts if c)
    peak_i = counts.index(peak) if peak else 0
    peak_x = LEFT + peak_i * step + 6.5 * step / 14
    peak_y = BASE_Y - MAX_SPIKE
    first, last = window[0][0], window[-1][0]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    peak_note = ""
    if peak:
        anchor = "end" if peak_x > W - 160 else "start"
        dx = -8 if anchor == "end" else 8
        peak_note = f"""
  <circle cx="{peak_x:.1f}" cy="{peak_y:.1f}" r="3.5" fill="#f85149" class="fade" style="animation-delay:4s"/>
  <text x="{peak_x + dx:.1f}" y="{peak_y + 4:.1f}" text-anchor="{anchor}" class="mono small red fade" style="animation-delay:4s">best week · {peak} (wk of {window[peak_i][0]:%b %d})</text>"""

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="Commit heartbeat: {total} contributions in the past year, {active} active weeks">
  <defs>
    <pattern id="minor" width="10" height="10" patternUnits="userSpaceOnUse">
      <path d="M10 0H0V10" fill="none" stroke="#3fb950" stroke-opacity=".07"/>
    </pattern>
    <pattern id="major" width="50" height="50" patternUnits="userSpaceOnUse">
      <rect width="50" height="50" fill="url(#minor)"/>
      <path d="M50 0H0V50" fill="none" stroke="#3fb950" stroke-opacity=".14"/>
    </pattern>
    <filter id="glow" x="-5%" y="-30%" width="110%" height="160%">
      <feGaussianBlur stdDeviation="3" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <linearGradient id="fadeR" x1="0" x2="1">
      <stop offset="0" stop-color="#3fb950" stop-opacity=".25"/>
      <stop offset="1" stop-color="#3fb950" stop-opacity="1"/>
    </linearGradient>
  </defs>
  <style>
    .mono {{ font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace; }}
    .lbl {{ font-size: 12px; fill: #8b949e; letter-spacing: 1px; }}
    .big {{ font-size: 22px; font-weight: 700; fill: #e6edf3; }}
    .small {{ font-size: 11px; fill: #8b949e; }}
    .red {{ fill: #f85149; }}
    .trace {{ stroke-dasharray: {length:.0f}; stroke-dashoffset: {length:.0f}; animation: draw 4s ease-in-out forwards; }}
    .sweep {{ stroke-dasharray: 90 {length:.0f}; stroke-dashoffset: 90; animation: sweep 5s linear 4s infinite; opacity: 0; }}
    .fade {{ opacity: 0; animation: fade .6s ease-out forwards; }}
    .heart {{ transform-box: fill-box; transform-origin: center; animation: thump 1s ease-in-out infinite; }}
    @keyframes draw {{ to {{ stroke-dashoffset: 0; }} }}
    @keyframes sweep {{ 0% {{ opacity: 1; stroke-dashoffset: 90; }} 100% {{ opacity: 1; stroke-dashoffset: -{length:.0f}; }} }}
    @keyframes fade {{ to {{ opacity: 1; }} }}
    @keyframes thump {{ 0%,100% {{ transform: scale(1); }} 15% {{ transform: scale(1.25); }} 30% {{ transform: scale(.95); }} 45% {{ transform: scale(1.12); }} }}
  </style>

  <rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="12" fill="#0d1117" stroke="#30363d" stroke-width="1.5"/>
  <rect x="{LEFT}" y="58" width="{span}" height="{H - 58 - 34}" fill="url(#major)"/>

  <g transform="translate({LEFT} 34)">
    <path class="heart" d="M0 4 C0 -2 8 -4 10 2 C12 -4 20 -2 20 4 C20 10 10 16 10 16 C10 16 0 10 0 4Z" fill="#f85149" transform="translate(0 -12) scale(.9)"/>
    <text x="26" y="0" class="mono lbl">COMMIT HEARTBEAT · 1 BEAT = 1 WEEK · PAST YEAR</text>
  </g>
  <g class="mono" text-anchor="end">
    <text x="{W - RIGHT - 300}" y="40" class="big">{last90}</text>
    <text x="{W - RIGHT - 300}" y="54" class="small">last 90 days</text>
    <text x="{W - RIGHT - 160}" y="40" class="big">{active}<tspan class="small">/{len(window)}</tspan></text>
    <text x="{W - RIGHT - 160}" y="54" class="small">active weeks</text>
    <text x="{W - RIGHT}" y="40" class="big">{total}</text>
    <text x="{W - RIGHT}" y="54" class="small">past year</text>
  </g>

  <path d="{d}" fill="none" stroke="url(#fadeR)" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round" class="trace" filter="url(#glow)"/>
  <path d="{d}" fill="none" stroke="#aff5b4" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round" class="sweep" filter="url(#glow)"/>
  {peak_note}

  <g class="mono small">
    <text x="{LEFT}" y="{H - 14}">{first:%b %d}</text>
    <text x="{W / 2}" y="{H - 14}" text-anchor="middle">public contributions · updated {stamp}</text>
    <text x="{W - RIGHT}" y="{H - 14}" text-anchor="end">{last:%b %d}</text>
  </g>
</svg>
"""


def main() -> None:
    total, weeks = fetch_calendar(LOGIN)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(total, weeks), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
