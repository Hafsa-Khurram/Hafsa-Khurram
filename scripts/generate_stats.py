"""
Generates the GitHub stats cards shown on the profile README:
  stats.svg, top-langs.svg, streak.svg, activity-graph.svg

Runs inside GitHub Actions, using the GITHUB_TOKEN to read public data
from the GitHub GraphQL API. Only the Python standard library is used.

Usage: python scripts/generate_stats.py <username> <output-dir>
"""

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
    followers { totalCount }
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


def main():
    login, out_dir = sys.argv[1], sys.argv[2]
    data = fetch_data(login)
    os.makedirs(out_dir, exist_ok=True)
    files = {
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
