#!/usr/bin/env python3
"""
Custom GitHub Contribution Snake Generator
- Fetches contribution data via GitHub GraphQL API
- Generates an SVG where the snake grows based on commit density
"""

import argparse
import json
import math
import os
import sys
from datetime import date, timedelta
from typing import Optional
import urllib.request
import urllib.error


# ── GitHub GraphQL ──────────────────────────────────────────────────────────

GRAPHQL_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks {
          contributionDays {
            date
            contributionCount
            color
          }
        }
      }
    }
  }
}
"""


def fetch_contributions(username: str, token: str) -> list[dict]:
    """Fetch 52 weeks of contribution data."""
    today = date.today()
    from_date = (today - timedelta(weeks=52)).isoformat() + "T00:00:00Z"
    to_date = today.isoformat() + "T23:59:59Z"

    payload = json.dumps({
        "query": GRAPHQL_QUERY,
        "variables": {"login": username, "from": from_date, "to": to_date},
    }).encode()

    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "custom-snake-generator/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"[ERROR] GitHub API returned {e.code}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)

    weeks = (
        data["data"]["user"]["contributionsCollection"]
        ["contributionCalendar"]["weeks"]
    )

    # Flatten to list of dicts: {col, row, count, color}
    cells = []
    for col, week in enumerate(weeks):
        for row, day in enumerate(week["contributionDays"]):
            cells.append({
                "col": col,
                "row": row,
                "count": day["contributionCount"],
                "color": day["color"],
                "date": day["date"],
            })
    return cells


# ── Snake Path ───────────────────────────────────────────────────────────────

def build_snake_path(cells: list[dict]) -> list[dict]:
    """
    Build an ordered snake path through non-zero cells only.
    Strategy: boustrophedon (zigzag) column traversal — same as a real
    contribution grid snake. Only eat cells with actual contributions.
    """
    grid: dict[tuple[int, int], dict] = {(c["col"], c["row"]): c for c in cells}
    cols = sorted(set(c["col"] for c in cells))

    path = []
    for col in cols:
        rows = range(7) if col % 2 == 0 else range(6, -1, -1)
        for row in rows:
            cell = grid.get((col, row))
            if cell and cell["count"] > 0:  # skip empty days
                path.append(cell)
    return path


# ── SVG Generation ───────────────────────────────────────────────────────────

CELL_SIZE = 11        # px per grid cell
CELL_GAP = 3          # gap between cells
PADDING = 20          # outer padding
COLS = 53             # max columns
ROWS = 7

SNAKE_BASE_WIDTH = 6  # px, snake width with 0 commits
SNAKE_MAX_EXTRA = 8   # px of extra width for highest density
SNAKE_COLOR = "#58a6ff"
SNAKE_HEAD_COLOR = "#1f6feb"

LEVEL_COLORS = {
    0: "#161b22",
    1: "#0e4429",
    2: "#006d32",
    3: "#26a641",
    4: "#39d353",
}


def cell_center(col: int, row: int) -> tuple[float, float]:
    step = CELL_SIZE + CELL_GAP
    x = PADDING + col * step + CELL_SIZE / 2
    y = PADDING + row * step + CELL_SIZE / 2
    return x, y


def count_to_width(count: int, max_count: int) -> float:
    if max_count == 0:
        return SNAKE_BASE_WIDTH
    ratio = min(count / max_count, 1.0)
    return SNAKE_BASE_WIDTH + ratio * SNAKE_MAX_EXTRA


def count_to_level(count: int) -> int:
    if count == 0:
        return 0
    if count <= 2:
        return 1
    if count <= 5:
        return 2
    if count <= 10:
        return 3
    return 4


def generate_svg(cells: list[dict], path: list[dict], username: str) -> str:
    step = CELL_SIZE + CELL_GAP
    width = PADDING * 2 + COLS * step
    height = PADDING * 2 + ROWS * step + 24  # extra for label

    max_count = max((c["count"] for c in cells), default=1) or 1
    total_path = len(path)
    if total_path == 0:
        total_path = 1

    # ── Static grid rects ──────────────────────────────────────────────────
    grid_rects = []
    for c in cells:
        lvl = count_to_level(c["count"])
        color = LEVEL_COLORS[lvl]
        x, y = cell_center(c["col"], c["row"])
        rx = x - CELL_SIZE / 2
        ry = y - CELL_SIZE / 2
        grid_rects.append(
            f'  <rect x="{rx:.1f}" y="{ry:.1f}" width="{CELL_SIZE}" height="{CELL_SIZE}" '
            f'rx="2" fill="{color}" />'
        )

    # ── Snake segments (one <polyline> per segment pair, animated) ─────────
    # Build cumulative widths for each waypoint
    waypoints = []
    for cell in path:
        cx, cy = cell_center(cell["col"], cell["row"])
        w = count_to_width(cell["count"], max_count)
        waypoints.append((cx, cy, w))

    # Duration constants
    total_duration = max(total_path * 0.12, 8)  # seconds
    anim_duration = f"{total_duration:.1f}s"

    # We build a single <path> element for the snake body that morphs the
    # stroke-width and stroke-dashoffset to reveal the snake progressively.
    # Since SVG doesn't support variable-width polylines cleanly natively,
    # we generate N <line> segments each with their own stroke-width and
    # animate their visibility with a delay.

    segments_svg = []
    for i, (cx, cy, w) in enumerate(waypoints):
        if i == 0:
            continue
        px, py, pw = waypoints[i - 1]
        # Each segment appears at its own time
        start_pct = (i - 1) / total_path * 100
        end_pct = i / total_path * 100
        avg_w = (pw + w) / 2

        # Animate opacity: hidden → visible at the right moment
        # Use a discrete keyframe trick
        k_before = max(start_pct - 0.01, 0)
        segments_svg.append(f"""
  <line x1="{px:.1f}" y1="{py:.1f}" x2="{cx:.1f}" y2="{cy:.1f}"
        stroke="{SNAKE_COLOR}" stroke-width="{avg_w:.1f}" stroke-linecap="round"
        opacity="0">
    <animate attributeName="opacity"
      values="0;0;1;1"
      keyTimes="0;{k_before/100:.4f};{end_pct/100:.4f};1"
      dur="{anim_duration}" repeatCount="indefinite" />
  </line>""")

    # ── Snake head (circle that travels along the path) ────────────────────
    # Build x/y keyframe strings
    xs = ";".join(f"{wp[0]:.1f}" for wp in waypoints)
    ys = ";".join(f"{wp[1]:.1f}" for wp in waypoints)
    ws_head = ";".join(f"{wp[2]/2:.1f}" for wp in waypoints)
    kt = ";".join(f"{i/(total_path-1):.4f}" for i in range(total_path)) if total_path > 1 else "0;1"

    head_svg = f"""
  <circle r="5" fill="{SNAKE_HEAD_COLOR}" opacity="1">
    <animate attributeName="cx" values="{xs}" keyTimes="{kt}" dur="{anim_duration}" repeatCount="indefinite" />
    <animate attributeName="cy" values="{ys}" keyTimes="{kt}" dur="{anim_duration}" repeatCount="indefinite" />
    <animate attributeName="r"  values="{ws_head}" keyTimes="{kt}" dur="{anim_duration}" repeatCount="indefinite" />
  </circle>"""

    # ── "Eaten" cell flash: cells go dark when the head eats them ──────────
    eaten_svg = []
    for i, cell in enumerate(path):
        eat_pct = i / total_path
        cx, cy = cell_center(cell["col"], cell["row"])
        rx = cx - CELL_SIZE / 2
        ry = cy - CELL_SIZE / 2
        lvl = count_to_level(cell["count"])
        bg_color = LEVEL_COLORS[lvl]
        # Flash: bg → flash white → bg
        flash_start = max(eat_pct - 0.005, 0)
        flash_mid   = eat_pct
        flash_end   = min(eat_pct + 0.015, 1.0)
        eaten_svg.append(f"""
  <rect x="{rx:.1f}" y="{ry:.1f}" width="{CELL_SIZE}" height="{CELL_SIZE}" rx="2" fill="{bg_color}">
    <animate attributeName="fill"
      values="{bg_color};#ffffff;{LEVEL_COLORS[0]}"
      keyTimes="0;{flash_mid:.4f};{flash_end:.4f}"
      begin="{flash_start * total_duration:.2f}s"
      dur="{total_duration:.1f}s" repeatCount="indefinite" />
  </rect>""")

    # ── Assemble ──────────────────────────────────────────────────────────
    grid_block = "\n".join(grid_rects)
    segments_block = "".join(segments_svg)
    eaten_block = "".join(eaten_svg)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
     width="{width}" height="{height}"
     viewBox="0 0 {width} {height}">

  <!-- Dark background -->
  <rect width="100%" height="100%" fill="#0d1117" rx="8"/>

  <!-- Contribution grid -->
{grid_block}

  <!-- Eaten cell flash overlays -->
{eaten_block}

  <!-- Snake body segments -->
{segments_block}

  <!-- Snake head -->
{head_svg}

  <!-- Label -->
  <text x="{PADDING}" y="{height - 6}"
        font-family="monospace" font-size="10" fill="#484f58">
    {username}'s contributions — snake grows with commit density
  </text>
</svg>
"""
    return svg


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate a custom contribution snake SVG.")
    parser.add_argument("--user",  default=os.getenv("GITHUB_USER", "RishiM1408"),
                        help="GitHub username")
    parser.add_argument("--token", default=os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN"),
                        help="GitHub Personal Access Token")
    parser.add_argument("--out",   default="dist/github-contribution-grid-snake.svg",
                        help="Output SVG path")
    args = parser.parse_args()

    if not args.token:
        print("[ERROR] Provide --token or set GH_TOKEN env var.", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Fetching contributions for {args.user}...")
    cells = fetch_contributions(args.user, args.token)
    print(f"[*] Got {len(cells)} cells.")

    path = build_snake_path(cells)
    print(f"[*] Snake path has {len(path)} waypoints.")

    svg = generate_svg(cells, path, args.user)

    out_path = args.out
    os.makedirs(os.path.dirname(out_path) if os.path.dirname(out_path) else ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"[✓] SVG written to {out_path}")


if __name__ == "__main__":
    main()
