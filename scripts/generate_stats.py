"""
Generates the cards shown on the profile README:
  about.svg, stats.svg, top-langs.svg, streak.svg, activity-graph.svg

Runs inside GitHub Actions, using the GITHUB_TOKEN to read public data
from the GitHub GraphQL API. Only the Python standard library is used.

Usage: python scripts/generate_stats.py <username> <output-dir>
"""

import base64
import datetime as dt
import json
import os
import sys
import urllib.request
from html import escape

# Colors (purple theme to match the profile)
BG = "#1a1b27"
ACCENT = "#C471ED"
TEXT = "#c0caf5"
MUTED = "#7a88cf"
GRID = "#2a2e45"
FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Sans-Serif"


def graphql(query, variables):
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": "bearer " + os.environ["GITHUB_TOKEN"],
            "Content-Type": "application/json",
            "User-Agent": "profile-stats-generator",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    if "errors" in result:
        raise RuntimeError(result["errors"])
    return result["data"]


USER_QUERY = """
query($login: String!) {
  user(login: $login) {
    name
    avatarUrl(size: 160)
    createdAt
    followers { totalCount }
    following { totalCount }
    pullRequests { totalCount }
    issues { totalCount }
    repositoriesContributedTo(contributionTypes: [COMMIT, PULL_REQUEST, ISSUE]) { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100, privacy: PUBLIC) {
      totalCount
      nodes {
        name
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
    contributionsCollection { contributionYears }
  }
}
"""

YEAR_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      restrictedContributionsCount
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def fetch_avatar(url):
    """Avatar as a data URI: GitHub does not load external images inside SVGs."""
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            kind = response.headers.get_content_type() or "image/png"
            return f"data:{kind};base64," + base64.b64encode(response.read()).decode()
    except OSError:
        return ""


def fetch_data(login):
    user = graphql(USER_QUERY, {"login": login})["user"]
    today = dt.date.today()

    total_commits = 0
    days = {}
    for year in user["contributionsCollection"]["contributionYears"]:
        start = dt.datetime(year, 1, 1)
        end = dt.datetime(year, 12, 31, 23, 59, 59)
        collection = graphql(
            YEAR_QUERY,
            {"login": login, "from": start.isoformat() + "Z", "to": end.isoformat() + "Z"},
        )["user"]["contributionsCollection"]
        total_commits += collection["totalCommitContributions"] + collection["restrictedContributionsCount"]
        for week in collection["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                date = dt.date.fromisoformat(day["date"])
                if date <= today:
                    days[date] = day["contributionCount"]

    languages = {}
    stars = 0
    for repo in user["repositories"]["nodes"]:
        stars += repo["stargazerCount"]
        if repo["name"].lower() == login.lower():
            continue  # skip the profile README repo: its helper script is not real project code
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            color = edge["node"]["color"] or "#858585"
            size, _ = languages.get(name, (0, color))
            languages[name] = (size + edge["size"], color)

    return {
        "name": user["name"] or login,
        "stars": stars,
        "commits": total_commits,
        "prs": user["pullRequests"]["totalCount"],
        "issues": user["issues"]["totalCount"],
        "contributed": user["repositoriesContributedTo"]["totalCount"],
        "followers": user["followers"]["totalCount"],
        "following": user["following"]["totalCount"],
        "since": user["createdAt"][:4],
        "avatar": fetch_avatar(user["avatarUrl"]),
        "repos": user["repositories"]["totalCount"],
        "languages": languages,
        "days": days,
    }


def card(width, height, title, body):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <style>
    .title {{ font: 600 18px {FONT}; fill: {ACCENT}; }}
    .label {{ font: 400 14px {FONT}; fill: {TEXT}; }}
    .value {{ font: 700 14px {FONT}; fill: {TEXT}; }}
    .small {{ font: 400 11px {FONT}; fill: {MUTED}; }}
    .big {{ font: 700 28px {FONT}; fill: {TEXT}; }}
  </style>
  <rect x="0.5" y="0.5" rx="6" width="{width - 1}" height="{height - 1}" fill="{BG}" stroke="{GRID}"/>
  <text x="25" y="35" class="title">{escape(title)}</text>
{body}
</svg>
"""


def stats_svg(data):
    rows = [
        ("⭐", "Total Stars", data["stars"]),
        ("📝", "Total Commits", data["commits"]),
        ("🔀", "Total PRs", data["prs"]),
        ("❗", "Total Issues", data["issues"]),
        ("📦", "Public Repos", data["repos"]),
        ("🤝", "Contributed to", data["contributed"]),
        ("👥", "Followers", data["followers"]),
    ]
    body = ""
    for i, (icon, label, value) in enumerate(rows):
        y = 70 + i * 25
        body += f'  <text x="25" y="{y}" class="label">{icon}  {label}:</text>\n'
        body += f'  <text x="250" y="{y}" class="value">{value}</text>\n'
    return card(400, 250, f"{data['name']}'s GitHub Stats", body)


def top_langs_svg(data):
    langs = sorted(data["languages"].items(), key=lambda item: item[1][0], reverse=True)[:6]
    total = sum(size for _, (size, _) in langs)
    body = ""
    if total == 0:
        body = '  <text x="25" y="75" class="label">No code yet - stay tuned!</text>\n'
        return card(400, 120, "Most Used Languages", body)

    # Stacked progress bar
    x = 25.0
    bar_width = 350
    body += f'  <clipPath id="bar"><rect x="25" y="55" width="{bar_width}" height="10" rx="5"/></clipPath>\n'
    body += '  <g clip-path="url(#bar)">\n'
    for name, (size, color) in langs:
        width = bar_width * size / total
        body += f'    <rect x="{x:.2f}" y="55" width="{width + 0.5:.2f}" height="10" fill="{color}"/>\n'
        x += width
    body += "  </g>\n"

    # Legend, two columns
    for i, (name, (size, color)) in enumerate(langs):
        col, row = i % 2, i // 2
        lx = 25 + col * 180
        ly = 95 + row * 25
        percent = 100 * size / total
        body += f'  <circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{color}"/>\n'
        body += f'  <text x="{lx + 16}" y="{ly}" class="label">{escape(name)} {percent:.1f}%</text>\n'

    height = 95 + ((len(langs) + 1) // 2) * 25
    return card(400, height, "Most Used Languages", body)


def streaks(days):
    ordered = sorted(days)
    longest = run = 0
    for date in ordered:
        run = run + 1 if days[date] > 0 else 0
        longest = max(longest, run)

    current = 0
    date = dt.date.today()
    if days.get(date, 0) == 0:
        date -= dt.timedelta(days=1)  # today not counted yet: streak may still be alive
    while days.get(date, 0) > 0:
        current += 1
        date -= dt.timedelta(days=1)
    return current, longest


def streak_svg(data):
    current, longest = streaks(data["days"])
    total = sum(data["days"].values())
    first = min(data["days"]) if data["days"] else dt.date.today()
    columns = [
        (100, str(total), "Total Contributions", f"{first:%b %d, %Y} - Present"),
        (300, str(current), "Current Streak", "🔥 Keep it going!"),
        (500, str(longest), "Longest Streak", "Best run so far"),
    ]
    body = ""
    for cx, value, label, sub in columns:
        body += f'  <text x="{cx}" y="95" class="big" text-anchor="middle">{value}</text>\n'
        body += f'  <text x="{cx}" y="125" class="value" text-anchor="middle" style="fill:{ACCENT}">{label}</text>\n'
        body += f'  <text x="{cx}" y="148" class="small" text-anchor="middle">{escape(sub)}</text>\n'
    body += f'  <line x1="200" y1="60" x2="200" y2="155" stroke="{GRID}"/>\n'
    body += f'  <line x1="400" y1="60" x2="400" y2="155" stroke="{GRID}"/>\n'
    return card(600, 180, "Contribution Streak", body)


def activity_svg(data):
    today = dt.date.today()
    dates = [today - dt.timedelta(days=i) for i in range(30, -1, -1)]
    counts = [data["days"].get(d, 0) for d in dates]
    peak = max(4, -(-max(counts) // 4) * 4)  # round up to a multiple of 4 so labels are whole numbers

    width, height = 900, 300
    left, right, top, bottom = 50, 20, 60, 50
    plot_w = width - left - right
    plot_h = height - top - bottom

    def point(i, value):
        return left + plot_w * i / (len(counts) - 1), top + plot_h * (1 - value / peak)

    body = ""
    # Horizontal grid lines with labels
    for step in range(5):
        value = peak * step / 4
        _, y = point(0, value)
        body += f'  <line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="{GRID}"/>\n'
        body += f'  <text x="{left - 10}" y="{y + 4:.1f}" class="small" text-anchor="end">{value:.0f}</text>\n'

    points = [point(i, c) for i, c in enumerate(counts)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area = f"{left},{top + plot_h} {line} {width - right},{top + plot_h}"
    body += f'  <polygon points="{area}" fill="{ACCENT}" fill-opacity="0.15"/>\n'
    body += f'  <polyline points="{line}" fill="none" stroke="{ACCENT}" stroke-width="2.5" stroke-linejoin="round"/>\n'

    for i, ((x, y), date) in enumerate(zip(points, dates)):
        body += f'  <circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="#ffffff"><title>{date:%b %d}: {counts[i]}</title></circle>\n'
        if i % 5 == 0 or i == len(dates) - 1:
            body += f'  <text x="{x:.1f}" y="{height - bottom + 20}" class="small" text-anchor="middle">{date:%d %b}</text>\n'

    body += f'  <text x="{width / 2}" y="{height - 8}" class="small" text-anchor="middle">Days</text>\n'
    return card(width, height, f"{data['name']}'s Contribution Graph (last 31 days)", body)


def about_svg(data):
    """A code-editor style 'About Me' card. Numbers and languages update daily."""
    today = dt.date.today()
    year_ago = today - dt.timedelta(days=365)
    yearly = sum(count for date, count in data["days"].items() if date > year_ago)
    langs = sorted(data["languages"].items(), key=lambda item: item[1][0], reverse=True)
    lang_list = ", ".join(f'"{escape(name)}"' for name, _ in langs[:6]) or '"C"'

    kw, typ, fld, st, num, com, txt = ACCENT, "#7dcfff", "#e0af68", "#9ece6a", "#ff9e64", "#565f89", TEXT

    def field(name, value, color):
        return (f'<tspan fill="{txt}">    .</tspan><tspan fill="{fld}">{name:<14}</tspan>'
                f'<tspan fill="{txt}">= </tspan><tspan fill="{color}">{value}</tspan><tspan fill="{txt}">,</tspan>')

    lines = [
        f'<tspan fill="{com}">// about_me.c  -  updates automatically every day</tspan>',
        f'<tspan fill="{kw}">#include</tspan> <tspan fill="{st}">&lt;passion.h&gt;</tspan>',
        "",
        f'<tspan fill="{kw}">struct</tspan> <tspan fill="{typ}">Developer</tspan> <tspan fill="{txt}">hafsa = {{</tspan>',
        field("name", f'"{escape(data["name"])}"', st),
        field("role", '"Software Developer"', st),
        field("education", '"COMSATS University"', st),
        field("languages", "{" + lang_list + "}", st),
        field("repositories", data["repos"], num),
        field("followers", data["followers"], num),
        field("following", data["following"], num),
        field("stars_earned", data["stars"], num),
        field("contributions", yearly, num) + f'<tspan fill="{com}">  // last 12 months</tspan>',
        field("github_since", data["since"], num),
        field("motto", '"Keep learning, keep building"', st),
        f'<tspan fill="{txt}">}};</tspan>',
        "",
        f'<tspan fill="{com}">// Last updated: {today:%d %b %Y}</tspan>',
    ]

    width, top, step = 760, 70, 22
    height = top + step * len(lines) + 10
    body = f"""  <rect x="0.5" y="0.5" rx="8" width="{width - 1}" height="{height - 1}" fill="{BG}" stroke="{GRID}"/>
  <rect x="0.5" y="0.5" rx="8" width="{width - 1}" height="36" fill="#16161e"/>
  <rect x="0.5" y="28" width="{width - 1}" height="9" fill="#16161e"/>
  <circle cx="22" cy="18" r="6" fill="#ff5f56"/>
  <circle cx="42" cy="18" r="6" fill="#ffbd2e"/>
  <circle cx="62" cy="18" r="6" fill="#27c93f"/>
  <text x="{width / 2}" y="23" text-anchor="middle" class="tab">about_me.c</text>
"""
    for i, line in enumerate(lines):
        y = top + i * step
        body += f'  <text x="20" y="{y}" class="ln" text-anchor="end" dx="12">{i + 1}</text>\n'
        if line:
            body += f'  <text x="55" y="{y}" class="code" xml:space="preserve">{line}</text>\n'
    # Blinking cursor after the last line
    body += (f'  <rect x="55" y="{top + len(lines) * step - 14}" width="9" height="17" fill="{ACCENT}">'
             '<animate attributeName="opacity" values="1;0;1" dur="1s" repeatCount="indefinite"/></rect>\n')

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height + 10}" viewBox="0 0 {width} {height + 10}">
  <style>
    .code {{ font: 400 15px 'Fira Code', Consolas, 'Courier New', monospace; }}
    .ln {{ font: 400 13px Consolas, 'Courier New', monospace; fill: #3b4261; }}
    .tab {{ font: 400 13px {FONT}; fill: {MUTED}; }}
  </style>
{body}</svg>
"""


def plural(count, word):
    return f"{count} {word}" + ("" if count == 1 else "s")


def about_common(data):
    today = dt.date.today()
    year_ago = today - dt.timedelta(days=365)
    yearly = sum(count for date, count in data["days"].items() if date > year_ago)
    langs = sorted(data["languages"].items(), key=lambda item: item[1][0], reverse=True)[:6]
    if not langs:
        langs = [("C", (1, "#555555"))]
    return today, yearly, langs


def about_neofetch_svg(data):
    """Terminal 'neofetch' style card: ASCII computer on the left, live info on the right."""
    today, yearly, langs = about_common(data)
    years = today.year - int(data["since"])
    art = [
        " .------------------------.",
        " |  .------------------.  |",
        " |  | #include         |  |",
        " |  |   <hafsa.h>      |  |",
        " |  |                  |  |",
        " |  | int main() {     |  |",
        " |  |   code();        |  |",
        " |  |   learn();       |  |",
        " |  |   repeat();      |  |",
        " |  | }                |  |",
        " |  '------------------'  |",
        " '------------------------'",
        "      _|____________|_",
        "     /________________\\",
    ]
    info = [
        ("title", "hafsa@github"),
        ("rule", "-" * 30),
        ("Name", data["name"]),
        ("Role", "Software Developer"),
        ("Education", "COMSATS University"),
        ("Languages", ", ".join(name for name, _ in langs)),
        ("Repositories", str(data["repos"])),
        ("Followers", str(data["followers"])),
        ("Following", str(data["following"])),
        ("Stars", str(data["stars"])),
        ("Contributions", f"{yearly} (last 12 months)"),
        ("Uptime", f"on GitHub since {data['since']}" + (f" ({years} yrs)" if years > 0 else "")),
        ("Editor", "VS Code"),
        ("blank", ""),
        ("colors", ""),
    ]
    width, top, step = 860, 90, 21
    rows = max(len(art), len(info))
    height = top + rows * step + 50
    body = f"""  <rect x="0.5" y="0.5" rx="8" width="{width - 1}" height="{height - 1}" fill="#0f0f17" stroke="{GRID}"/>
  <rect x="0.5" y="0.5" rx="8" width="{width - 1}" height="36" fill="#16161e"/>
  <rect x="0.5" y="28" width="{width - 1}" height="9" fill="#16161e"/>
  <circle cx="22" cy="18" r="6" fill="#ff5f56"/><circle cx="42" cy="18" r="6" fill="#ffbd2e"/><circle cx="62" cy="18" r="6" fill="#27c93f"/>
  <text x="{width / 2}" y="23" text-anchor="middle" class="tab">hafsa@github: ~</text>
  <text x="20" y="65" class="mono"><tspan fill="#9ece6a">hafsa@github</tspan><tspan fill="{TEXT}">:</tspan><tspan fill="#7dcfff">~</tspan><tspan fill="{TEXT}">$ neofetch</tspan></text>
"""
    for i, line in enumerate(art):
        body += f'  <text x="20" y="{top + i * step}" class="mono" fill="{ACCENT}" xml:space="preserve">{escape(line)}</text>\n'
    x = 340
    for i, (key, value) in enumerate(info):
        y = top + i * step
        if key == "title":
            body += f'  <text x="{x}" y="{y}" class="mono bold" fill="{ACCENT}">{escape(value)}</text>\n'
        elif key == "rule":
            body += f'  <text x="{x}" y="{y}" class="mono" fill="{GRID}">{value}</text>\n'
        elif key == "colors":
            for j, color in enumerate(["#f7768e", "#ff9e64", "#e0af68", "#9ece6a", "#7dcfff", "#7aa2f7", ACCENT, TEXT]):
                body += f'  <rect x="{x + j * 28}" y="{y - 15}" width="28" height="18" fill="{color}"/>\n'
        elif key != "blank":
            body += (f'  <text x="{x}" y="{y}" class="mono" xml:space="preserve"><tspan fill="{ACCENT}" class="bold">{key}</tspan>'
                     f'<tspan fill="{TEXT}">: {escape(value)}</tspan></text>\n')
    last = top + rows * step + 12
    body += f'  <text x="20" y="{last}" class="mono"><tspan fill="#9ece6a">hafsa@github</tspan><tspan fill="{TEXT}">:</tspan><tspan fill="#7dcfff">~</tspan><tspan fill="{TEXT}">$</tspan></text>\n'
    body += (f'  <rect x="157" y="{last - 14}" width="9" height="17" fill="{ACCENT}">'
             '<animate attributeName="opacity" values="1;0;1" dur="1s" repeatCount="indefinite"/></rect>\n')
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <style>
    .mono {{ font: 400 15px 'Fira Code', Consolas, 'Courier New', monospace; }}
    .bold {{ font-weight: 700; }}
    .tab {{ font: 400 13px {FONT}; fill: {MUTED}; }}
  </style>
{body}</svg>
"""


def about_card_svg(data):
    """Modern profile card: avatar, name, stat tiles and language pills."""
    today, yearly, langs = about_common(data)
    width, height = 860, 330
    body = f"""  <defs>
    <linearGradient id="hdr" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#6A1B9A"/><stop offset="1" stop-color="{ACCENT}"/>
    </linearGradient>
    <clipPath id="avatar"><circle cx="140" cy="130" r="70"/></clipPath>
  </defs>
  <rect x="0.5" y="0.5" rx="14" width="{width - 1}" height="{height - 1}" fill="{BG}" stroke="{GRID}"/>
  <rect x="0.5" y="0.5" rx="14" width="{width - 1}" height="90" fill="url(#hdr)"/>
  <rect x="0.5" y="70" width="{width - 1}" height="21" fill="url(#hdr)"/>
  <circle cx="140" cy="130" r="76" fill="{BG}"/>
  <circle cx="140" cy="130" r="73" fill="none" stroke="{ACCENT}" stroke-width="3"/>
"""
    if data.get("avatar"):
        body += f'  <image href="{data["avatar"]}" x="70" y="60" width="140" height="140" clip-path="url(#avatar)" preserveAspectRatio="xMidYMid slice"/>\n'
    else:
        body += f'  <text x="140" y="148" text-anchor="middle" class="initials">HK</text>\n'
    body += f"""  <text x="140" y="240" text-anchor="middle" class="name">{escape(data['name'])}</text>
  <text x="140" y="264" text-anchor="middle" class="role">Software Developer</text>
  <text x="140" y="290" text-anchor="middle" class="sub">🎓 COMSATS University</text>
  <text x="140" y="312" text-anchor="middle" class="sub">📅 On GitHub since {data['since']}</text>
  <line x1="280" y1="115" x2="280" y2="305" stroke="{GRID}"/>
"""
    tiles = [("👥", data["followers"], "Followers"), ("🤝", data["following"], "Following"),
             ("📦", data["repos"], "Repositories"), ("⭐", data["stars"], "Stars"), ("🔥", yearly, "Contributions")]
    tw, gap, tx = 100, 12, 305
    for i, (icon, value, label) in enumerate(tiles):
        x = tx + i * (tw + gap)
        body += f"""  <rect x="{x}" y="112" width="{tw}" height="92" rx="10" fill="#222436" stroke="{GRID}"/>
  <text x="{x + tw / 2}" y="138" text-anchor="middle" class="icon">{icon}</text>
  <text x="{x + tw / 2}" y="170" text-anchor="middle" class="num">{value}</text>
  <text x="{x + tw / 2}" y="192" text-anchor="middle" class="lbl">{label}</text>
"""
    body += f'  <text x="{tx}" y="238" class="section">LANGUAGES</text>\n'
    px = tx
    for name, (_, color) in langs:
        w = 30 + 9 * len(name)
        body += (f'  <rect x="{px}" y="250" width="{w}" height="28" rx="14" fill="#222436" stroke="{color}"/>\n'
                 f'  <circle cx="{px + 15}" cy="264" r="5" fill="{color}"/>\n'
                 f'  <text x="{px + 25}" y="269" class="pill">{escape(name)}</text>\n')
        px += w + 10
    body += f'  <text x="{width - 20}" y="{height - 14}" text-anchor="end" class="upd">Updated {today:%d %b %Y}</text>\n'
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <style>
    .name {{ font: 700 22px {FONT}; fill: #ffffff; }}
    .role {{ font: 600 15px {FONT}; fill: {ACCENT}; }}
    .sub {{ font: 400 13px {FONT}; fill: {MUTED}; }}
    .initials {{ font: 700 48px {FONT}; fill: {ACCENT}; }}
    .icon {{ font: 400 18px {FONT}; }}
    .num {{ font: 700 26px {FONT}; fill: #ffffff; }}
    .lbl {{ font: 400 12px {FONT}; fill: {MUTED}; }}
    .section {{ font: 700 12px {FONT}; fill: {ACCENT}; letter-spacing: 2px; }}
    .pill {{ font: 600 13px {FONT}; fill: {TEXT}; }}
    .upd {{ font: 400 11px {FONT}; fill: #3b4261; }}
  </style>
{body}</svg>
"""


def about_terminal_svg(data):
    """Animated terminal: commands type themselves out one after another."""
    today, yearly, langs = about_common(data)
    langs_text = "  ".join(name for name, _ in langs)
    session = [
        ("whoami", [f"{data['name']}  -  Software Developer"]),
        ("cat education.txt", ["🎓 COMSATS University graduate"]),
        ("ls skills/", [f"{langs_text}  Git  GitHub  VS Code"]),
        ("github --stats", [f"👥 {plural(data['followers'], 'follower')}   🤝 {data['following']} following   📦 {plural(data['repos'], 'repo')}",
                            f"⭐ {plural(data['stars'], 'star')}   🔥 {plural(yearly, 'contribution')} in the last 12 months"]),
        ('echo "$MOTTO"', ["Keep learning, keep building 🚀"]),
    ]
    width, top, step = 860, 70, 24
    lines = sum(1 + len(out) for _, out in session) + 1
    height = top + lines * step + 10
    body = f"""  <rect x="0.5" y="0.5" rx="8" width="{width - 1}" height="{height - 1}" fill="#0f0f17" stroke="{GRID}"/>
  <rect x="0.5" y="0.5" rx="8" width="{width - 1}" height="36" fill="#16161e"/>
  <rect x="0.5" y="28" width="{width - 1}" height="9" fill="#16161e"/>
  <circle cx="22" cy="18" r="6" fill="#ff5f56"/><circle cx="42" cy="18" r="6" fill="#ffbd2e"/><circle cx="62" cy="18" r="6" fill="#27c93f"/>
  <text x="{width / 2}" y="23" text-anchor="middle" class="tab">hafsa@github: ~ (bash)</text>
"""
    prompt = (f'<tspan fill="#9ece6a">hafsa@github</tspan><tspan fill="{TEXT}">:</tspan>'
              f'<tspan fill="#7dcfff">~</tspan><tspan fill="{TEXT}">$ </tspan>')
    prompt_w = 150  # width of "hafsa@github:~$ " in 15px monospace
    t, row = 0.3, 0
    for n, (command, output) in enumerate(session):
        y = top + row * step
        type_time = 0.06 * len(command) + 0.2
        cmd_w = 9.1 * len(command) + 4
        body += f'  <clipPath id="c{n}"><rect x="{20 + prompt_w}" y="{y - 18}" width="0" height="24">' \
                f'<animate attributeName="width" from="0" to="{cmd_w:.0f}" begin="{t:.2f}s" dur="{type_time:.2f}s" fill="freeze"/></rect></clipPath>\n'
        body += f'  <g opacity="0"><set attributeName="opacity" to="1" begin="{t - 0.25:.2f}s" fill="freeze"/>' \
                f'<text x="20" y="{y}" class="mono" xml:space="preserve">{prompt}</text></g>\n'
        body += f'  <text x="{20 + prompt_w}" y="{y}" class="mono" fill="{TEXT}" clip-path="url(#c{n})">{escape(command)}</text>\n'
        t += type_time + 0.3
        row += 1
        for line in output:
            y = top + row * step
            body += f'  <text x="20" y="{y}" class="mono out" opacity="0" xml:space="preserve">{escape(line)}' \
                    f'<set attributeName="opacity" to="1" begin="{t:.2f}s" fill="freeze"/></text>\n'
            row += 1
        t += 0.6
    y = top + row * step
    body += f'  <g opacity="0"><set attributeName="opacity" to="1" begin="{t:.2f}s" fill="freeze"/>' \
            f'<text x="20" y="{y}" class="mono" xml:space="preserve">{prompt}</text>' \
            f'<rect x="{20 + prompt_w}" y="{y - 14}" width="9" height="17" fill="{ACCENT}">' \
            f'<animate attributeName="opacity" values="1;0;1" dur="1s" repeatCount="indefinite"/></rect></g>\n'
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <style>
    .mono {{ font: 400 15px 'Fira Code', Consolas, 'Courier New', monospace; }}
    .out {{ fill: {ACCENT}; }}
    .tab {{ font: 400 13px {FONT}; fill: {MUTED}; }}
  </style>
{body}</svg>
"""


def main():
    login, out_dir = sys.argv[1], sys.argv[2]
    data = fetch_data(login)
    os.makedirs(out_dir, exist_ok=True)
    files = {
        "about.svg": about_svg(data),
        "about-neofetch.svg": about_neofetch_svg(data),
        "about-card.svg": about_card_svg(data),
        "about-terminal.svg": about_terminal_svg(data),
        "stats.svg": stats_svg(data),
        "top-langs.svg": top_langs_svg(data),
        "streak.svg": streak_svg(data),
        "activity-graph.svg": activity_svg(data),
    }
    for name, svg in files.items():
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            f.write(svg)
        print("Wrote", name)


if __name__ == "__main__":
    main()
