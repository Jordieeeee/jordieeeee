#!/usr/bin/env python3
"""
Render a neofetch-style profile card as SVG (light + dark), with live GitHub stats.

Usage:
    GH_TOKEN=... python3 .github/scripts/generate_card.py

Design notes
------------
* GitHub renders README SVGs inside an <img>, so no external CSS, no JS, no
  web fonts. Everything is inline and static.
* The viewer's monospace font is unknown, so column alignment cannot rely on
  font metrics. Every run of text is absolutely positioned at `col * CHAR_W`
  and pinned with `textLength` + `lengthAdjust`. This is the whole reason the
  ASCII art and the dotted leaders line up on any machine.
* Every network call is best-effort. If the API is down or the token expired,
  the previous stats are reused from the cache and the card still renders.
  A broken workflow must never produce a broken image.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONFIG = ROOT / ".github" / "card-config.json"
PORTRAIT = ROOT / ".github" / "assets" / "portrait.txt"
CACHE = ROOT / ".github" / "stats-cache.json"
OUT_DIR = ROOT / "assets"

FONT_SIZE = 14.0
CHAR_W = FONT_SIZE * 0.6          # every mainstream monospace face is 0.6em
LINE_H = 17.0
PAD_X = 22.0
PAD_Y = 20.0
GUTTER = 4                        # blank columns between art and info panel
INFO_W = 58                       # info panel width, in characters
FONT_STACK = (
    "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,"
    "'Liberation Mono','DejaVu Sans Mono',monospace"
)

THEMES = {
    "dark": {
        "bg": "#0D1117", "border": "#30363D", "art": "#8B949E",
        "title": "#E6EDF3", "rule": "#30363D", "label": "#FFA657",
        "dots": "#30363D", "value": "#79C0FF", "punct": "#FFA657",
        "add": "#3FB950", "del": "#F85149", "muted": "#6E7681",
    },
    "light": {
        "bg": "#FFFFFF", "border": "#D0D7DE", "art": "#57606A",
        "title": "#1F2328", "rule": "#D0D7DE", "label": "#BC4C00",
        "dots": "#D8DEE4", "value": "#0969DA", "punct": "#BC4C00",
        "add": "#1A7F37", "del": "#CF222E", "muted": "#6E7681",
    },
}

API = "https://api.github.com"


# --------------------------------------------------------------------------
# GitHub data
# --------------------------------------------------------------------------
def _request(url: str, token: str, data: dict | None = None, accept: str = "application/vnd.github+json"):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", accept)
    req.add_header("User-Agent", "neofetch-card-generator")
    if body:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, json.loads(resp.read().decode() or "null")


def graphql(query: str, variables: dict, token: str) -> dict:
    _, payload = _request(f"{API}/graphql", token, {"query": query, "variables": variables})
    if payload.get("errors"):
        raise RuntimeError(f"GraphQL: {payload['errors']}")
    return payload["data"]


REPO_QUERY = """
query($login:String!, $id:ID!, $after:String) {
  user(login:$login) {
    followers { totalCount }
    repositoriesContributedTo(
      first:1, includeUserRepositories:false,
      contributionTypes:[COMMIT, PULL_REQUEST, REPOSITORY]
    ) { totalCount }
    repositories(first:50, after:$after, ownerAffiliations:OWNER, isFork:false,
                 orderBy:{field:PUSHED_AT, direction:DESC}) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        nameWithOwner
        stargazerCount
        pushedAt
        isPrivate
        primaryLanguage { name }
        defaultBranchRef {
          target { ... on Commit { history(author:{id:$id}) { totalCount } } }
        }
      }
    }
  }
}
"""


def fetch_stats(login: str, token: str, loc_cache: dict) -> dict:
    _, me = _request(f"{API}/users/{login}", token)
    node_id = me["node_id"]

    followers = contributed = repo_count = stars = commits = 0
    repos: list[dict] = []
    languages: set[str] = set()
    cursor = None
    while True:
        data = graphql(REPO_QUERY, {"login": login, "id": node_id, "after": cursor}, token)
        user = data["user"]
        followers = user["followers"]["totalCount"]
        contributed = user["repositoriesContributedTo"]["totalCount"]
        repo_count = user["repositories"]["totalCount"]
        for node in user["repositories"]["nodes"]:
            stars += node["stargazerCount"]
            if node.get("primaryLanguage"):
                languages.add(node["primaryLanguage"]["name"])
            branch = node.get("defaultBranchRef")
            if branch and branch.get("target"):
                commits += branch["target"]["history"]["totalCount"]
            repos.append(node)
        page = user["repositories"]["pageInfo"]
        if not page["hasNextPage"]:
            break
        cursor = page["endCursor"]

    added, deleted = count_loc(repos, login, token, loc_cache)
    return {
        "repos": repo_count, "contributed": contributed, "stars": stars,
        "followers": followers, "commits": commits, "languages": len(languages),
        "added": added, "deleted": deleted, "net": added - deleted,
    }


def count_loc(repos: list[dict], login: str, token: str, cache: dict) -> tuple[int, int]:
    """Sum additions/deletions authored by `login` across their repos.

    Uses the contributor-stats endpoint rather than cloning. GitHub computes
    that stat asynchronously and answers 202 while the cache warms, so a repo
    that isn't ready is skipped this run and picked up on the next one --
    never blocking the workflow. Results are memoised per (repo, pushedAt).
    """
    total_add = total_del = 0
    for node in repos:
        full = node["nameWithOwner"]
        key = f"{full}@{node['pushedAt']}"
        hit = cache.get(full)
        if hit and hit.get("key") == key:
            total_add += hit["add"]
            total_del += hit["del"]
            continue

        add = dele = 0
        ok = False
        for attempt in range(3):
            try:
                status, payload = _request(f"{API}/repos/{full}/stats/contributors", token)
            except urllib.error.HTTPError as exc:            # 403/404/409 on empty repos
                print(f"  ! {full}: HTTP {exc.code}, skipping", file=sys.stderr)
                break
            if status == 202 or payload is None:             # still computing
                time.sleep(3 * (attempt + 1))
                continue
            for entry in payload or []:
                if (entry.get("author") or {}).get("login", "").lower() != login.lower():
                    continue
                for week in entry.get("weeks", []):
                    add += week.get("a", 0)
                    dele += week.get("d", 0)
            ok = True
            break

        if ok:
            cache[full] = {"key": key, "add": add, "del": dele}
            total_add += add
            total_del += dele
        elif hit:                                            # fall back to stale entry
            total_add += hit["add"]
            total_del += hit["del"]
    return total_add, total_del


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------
Run = tuple[int, str, str]  # (column, text, colour key)


def leader(label: str, value: str, width: int = INFO_W) -> list[Run]:
    """`· Label: .......... value` with the value flushed right."""
    head = f"· {label}: "
    value = value[: max(0, width - len(head) - 1)]
    dots = max(1, width - len(head) - len(value))
    return [
        (0, "·", "muted"),
        (2, f"{label}:", "label"),
        (len(head), "." * dots, "dots"),
        (width - len(value), value, "value"),
    ]


def rule(title: str | None, width: int = INFO_W) -> list[Run]:
    if not title:
        return [(0, "─" * width, "rule")]
    head = f"─ {title} "
    return [
        (0, "─", "rule"),
        (2, title, "title"),
        (len(head), "─" * max(1, width - len(head)), "rule"),
    ]


def banner(title: str, width: int = INFO_W) -> list[Run]:
    head = f"{title} "
    return [
        (0, title, "title"),
        (len(head), "─" * max(1, width - len(head)), "rule"),
    ]


def group(n: int) -> str:
    return f"{n:,}"


def paint(line: str, spec: list[tuple[str, str]]) -> list[Run]:
    """Colour a finished line by locating each fragment in it.

    Composite rows (two label/value pairs plus punctuation) are far too easy to
    get wrong when columns are added up by hand, so the line is assembled as a
    plain string first and the colours are attached afterwards by searching for
    each fragment in order. Layout and colour can then never disagree.
    """
    runs: list[Run] = []
    cursor = 0
    for fragment, key in spec:
        col = line.index(fragment, cursor)
        if line[cursor:col].strip():                  # dotted filler between fragments
            runs.append((cursor, line[cursor:col], "dots"))
        runs.append((col, fragment, key))
        cursor = col + len(fragment)
    if line[cursor:].strip():
        runs.append((cursor, line[cursor:], "dots"))
    return runs


METRIC_LABELS = {
    "repos": "Repos",
    "contributed": "Contributed to",
    "commits": "Commits",
    "languages": "Languages",
    "stars": "Stars",
    "followers": "Followers",
}

DEFAULT_METRICS = ["repos", "contributed", "commits", "languages", "loc"]


def stat_rows(s: dict, metrics: list[str] | None = None, width: int = INFO_W) -> list[list[Run]]:
    """Lay the requested metrics out two per line, with `loc` on its own line.

    Which metrics appear is deliberately configurable. A stats block is only
    worth showing when the numbers in it flatter you; `stars` and `followers`
    are off by default because a highlighted `Stars: 0` reads worse than no
    stats block at all.
    """
    metrics = metrics or DEFAULT_METRICS
    rows: list[list[Run]] = []

    def pad(left: str, right: str) -> str:
        return f"{left}{'.' * max(1, width - len(left) - len(right))}{right}"

    simple = [m for m in metrics if m in METRIC_LABELS]
    for i in range(0, len(simple), 2):
        pair = simple[i:i + 2]
        lk = pair[0]
        lv = group(s.get(lk, 0))
        left = f"· {METRIC_LABELS[lk]}: {lv} "
        spec = [("·", "muted"), (f"{METRIC_LABELS[lk]}:", "label"), (lv, "value")]
        if len(pair) == 2:
            rk = pair[1]
            rv = group(s.get(rk, 0))
            right = f" | {METRIC_LABELS[rk]}: {rv}"
            spec += [("|", "muted"), (f"{METRIC_LABELS[rk]}:", "label"), (rv, "value")]
        else:
            right = ""
        rows.append(paint(pad(left, right), spec))

    if "loc" in metrics:
        net, add, dele = group(s["net"]), group(s["added"]), group(s["deleted"])
        line = pad("· Lines of Code: ", f"{net} ( {add}++, {dele}-- )")
        rows.append(paint(line, [
            ("·", "muted"), ("Lines of Code:", "label"), (net, "value"),
            ("(", "muted"), (f"{add}++", "add"), (",", "muted"),
            (f"{dele}--", "del"), (")", "muted"),
        ]))
    return rows


def build_info(cfg: dict, stats: dict) -> list[list[Run]]:
    lines: list[list[Run]] = [banner(cfg["title"])]
    for section in cfg["sections"]:
        if section.get("heading"):
            lines.append([])
            lines.append(rule(section["heading"]))
        if section.get("stats"):
            metrics = section["stats"] if isinstance(section["stats"], list) else None
            lines.extend(stat_rows(stats, metrics))
        for label, value in section.get("rows", []):
            lines.append(leader(label, value))
    return lines


# --------------------------------------------------------------------------
# SVG
# --------------------------------------------------------------------------
def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tspan(col: int, text: str, colour: str, offset: int = 0) -> str:
    x = (col + offset) * CHAR_W
    return (
        f'<tspan x="{x:.2f}" fill="{colour}" textLength="{len(text) * CHAR_W:.2f}" '
        f'lengthAdjust="spacingAndGlyphs">{esc(text)}</tspan>'
    )


def render(art: list[str], info: list[list[Run]], theme: dict) -> str:
    art_w = max((len(line) for line in art), default=0)
    info_col = art_w + GUTTER
    cols = info_col + INFO_W
    rows = max(len(art), len(info))

    width = cols * CHAR_W + PAD_X * 2
    height = rows * LINE_H + PAD_Y * 2

    body = []
    for i in range(rows):
        y = PAD_Y + (i + 1) * LINE_H - LINE_H * 0.25
        spans = []
        if i < len(art) and art[i].strip():
            line = art[i]
            spans.append(tspan(0, line, theme["art"]))
        if i < len(info):
            for col, text, key in info[i]:
                if not text:
                    continue
                spans.append(tspan(col, text, theme[key], offset=info_col))
        if spans:
            body.append(f'<text y="{y:.2f}">{"".join(spans)}</text>')

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" \
viewBox="0 0 {width:.2f} {height:.2f}" role="img" aria-label="Profile card">
  <rect x="0.5" y="0.5" width="{width - 1:.2f}" height="{height - 1:.2f}" rx="10"
        fill="{theme['bg']}" stroke="{theme['border']}"/>
  <g font-family="{FONT_STACK}" font-size="{FONT_SIZE}" xml:space="preserve">
{chr(10).join('    ' + line for line in body)}
  </g>
</svg>
"""


# --------------------------------------------------------------------------
def main() -> int:
    cfg = json.loads(CONFIG.read_text())
    art = PORTRAIT.read_text().rstrip("\n").split("\n")

    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    loc_cache = cache.get("loc", {})
    stats = cache.get("stats", {
        "repos": 0, "contributed": 0, "stars": 0, "followers": 0,
        "commits": 0, "languages": 0, "added": 0, "deleted": 0, "net": 0,
    })

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        try:
            stats = fetch_stats(cfg["github_user"], token, loc_cache)
            print(f"stats: {stats}")
        except Exception as exc:                       # noqa: BLE001 - never fail the card
            print(f"WARNING: live stats unavailable ({exc}); using cache", file=sys.stderr)
    else:
        print("WARNING: no GH_TOKEN; using cached stats", file=sys.stderr)

    CACHE.write_text(json.dumps({"stats": stats, "loc": loc_cache}, indent=2) + "\n")

    info = build_info(cfg, stats)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, theme in THEMES.items():
        path = OUT_DIR / f"neofetch-{name}.svg"
        path.write_text(render(art, info, theme))
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
