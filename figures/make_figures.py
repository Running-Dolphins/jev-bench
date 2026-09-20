#!/usr/bin/env python3
"""Draws the figures in this folder from ../results/*.json. Standard library only: writes SVG;
if `rsvg-convert` is installed it also writes PNG (for places that don't take SVG).

    python3 figures/make_figures.py
"""

import json
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = {p.stem: json.loads(p.read_text()) for p in (HERE.parent / "results").glob("*.json")}

W, H = 1600, 900
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]  # fixed order, never cycled
FONT = "Helvetica Neue, Helvetica, Arial, sans-serif"
SOURCE = "github.com/Running-Dolphins/jev-bench · one run, 20 Sept 2026 · public datasets"

NAMES = {
    "sms-spam": "Is this message spam?",
    "duplicates": "Are these two requests duplicates?",
    "clinc150": "Route a request · 150 queues",
    "doc-yesno": "Does the document say yes?",
    "massive-en": "Route a request · 59 queues · English",
    "massive-it": "Route a request · 59 queues · Italian",
    "offensive": "Is this post offensive?",
    "ag-news": "Route a news item · 4 desks",
    "sentiment-it": "Sentiment of a tweet · Italian",
    "banking77": "Route a bank customer · 77 queues",
    "ledgar": "Type of contract clause · 100 types",
    "yelp-stars": "Exact star rating of a review · 1-5",
}


def t(x, y, s, size=22, fill=INK, anchor="start", weight=400):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
            f'font-weight="{weight}">{s}</text>')


def frame(title, subtitle, body):
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="{FONT}">',
        f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>',
        t(70, 92, title, 44, INK, weight=700), t(70, 138, subtitle, 25, INK2),
        *body, t(70, H - 34, SOURCE, 19, MUTED), "</svg>"])


def write(name, svg):
    (HERE / f"{name}.svg").write_text(svg)
    if shutil.which("rsvg-convert"):
        subprocess.run(["rsvg-convert", "-w", str(W), str(HERE / f"{name}.svg"), "-o", str(HERE / f"{name}.png")], check=True)


def fig_threshold():
    """Dot plot: how often Jev was right among the answers it gave at 0.9 or more."""
    tasks = sorted((r for k, r in RES.items() if not k.startswith("x-")), key=lambda r: -r["thresholds"]["0.9"]["accuracy"])
    x0, x1, top, row = 600, 1180, 205, 50
    px = lambda v: x0 + (v - 0.75) / 0.25 * (x1 - x0)
    b = []
    for v in (0.75, 0.80, 0.85, 0.90, 0.95, 1.0):
        b.append(f'<line x1="{px(v):.1f}" x2="{px(v):.1f}" y1="{top - 22}" y2="{top + row * len(tasks) - 20}" stroke="{GRID}"/>')
        b.append(t(px(v), top + row * len(tasks) + 10, f"{v:.0%}", 19, MUTED, "middle"))
    b.append(f'<line x1="{px(0.9):.1f}" x2="{px(0.9):.1f}" y1="{top - 22}" y2="{top + row * len(tasks) - 20}" stroke="{INK2}" stroke-width="2"/>')
    b.append(t(px(0.9) - 8, top - 30, "what “0.9” promises", 19, INK2, "end"))
    b.append(t(x1 + 130, top - 30, "share of answers at 0.9+", 19, INK2))
    for i, r in enumerate(tasks):
        y = top + i * row
        v, cov = r["thresholds"]["0.9"]["accuracy"], r["thresholds"]["0.9"]["coverage"]
        b.append(t(x0 - 30, y + 7, NAMES[r["name"]], 22, INK, "end"))
        b.append(f'<line x1="{px(0.75):.1f}" x2="{px(v):.1f}" y1="{y}" y2="{y}" stroke="{SERIES[0]}" stroke-width="2" opacity="0.28"/>')
        b.append(f'<circle cx="{px(v):.1f}" cy="{y}" r="9" fill="{SERIES[0]}" stroke="{SURFACE}" stroke-width="2"/>')
        b.append(t(px(v) + 18, y + 7, f"{v:.1%}", 22, INK, weight=700).replace("<text ", f'<text stroke="{SURFACE}" stroke-width="7" paint-order="stroke" '))
        b.append(t(x1 + 130, y + 7, f"{cov:.0%}", 22, INK2))
    return frame("“90% sure” is not one number",
                 "How often Jev was right when it said 0.9 or more. 12 tasks, 500 examples each, same model, same threshold.", b)


def fig_reliability():
    tasks = [r for k, r in RES.items() if not k.startswith("x-")]
    groups = [("Yes / no", "noul"), ("Pick one of N", "choice"), ("Ordered scale", "score")]
    S, left, gap, top = 400, 110, 95, 215
    b = []
    for g, (title, kind) in enumerate(groups):
        x0 = left + g * (S + gap)
        px = lambda v: x0 + (v - 0.5) / 0.5 * S
        py = lambda v: top + S - (v - 0.25) / 0.75 * S
        b.append(t(x0, top - 22, title, 26, INK, weight=700))
        for v in (0.25, 0.5, 0.75, 1.0):
            b.append(f'<line x1="{x0}" x2="{x0 + S}" y1="{py(v):.1f}" y2="{py(v):.1f}" stroke="{GRID}"/>')
            b.append(t(x0 - 12, py(v) + 6, f"{v:.0%}", 18, MUTED, "end"))
        for v in (0.5, 0.75, 1.0):
            b.append(t(px(v), top + S + 26, f"{v:.2f}", 18, MUTED, "middle"))
        b.append(f'<line x1="{px(0.5):.1f}" y1="{py(0.5):.1f}" x2="{px(1):.1f}" y2="{py(1):.1f}" stroke="{AXIS}" stroke-width="2"/>')
        mine = sorted((r for r in tasks if r["kind"].startswith(kind)), key=lambda r: -r["thresholds"]["0.9"]["accuracy"])
        for i, r in enumerate(mine):
            pts = [(x["stated"], x["actual"]) for x in r["reliability"] if x["lo"] >= 0.5 and x["n"] >= 10]
            c = SERIES[i]
            b.append(f'<polyline fill="none" stroke="{c}" stroke-width="2.5" stroke-linejoin="round" points="'
                     + " ".join(f"{px(a):.1f},{py(v):.1f}" for a, v in pts) + '"/>')
            b += [f'<circle cx="{px(a):.1f}" cy="{py(v):.1f}" r="5.5" fill="{c}" stroke="{SURFACE}" stroke-width="2"/>' for a, v in pts]
            ly = top + S + 66 + i * 28
            b.append(f'<circle cx="{x0 + 7}" cy="{ly - 6}" r="6" fill="{c}"/>')
            b.append(t(x0 + 24, ly, NAMES[r["name"]].split(" · ")[0] + (" · " + NAMES[r["name"]].split(" · ", 1)[1] if " · " in NAMES[r["name"]] else ""), 18, INK2))
    b.append(t(left, top + S + 26, "", 18))
    b.append(t(W - 70, 138, "grey diagonal = perfectly calibrated · below it = over-confident", 19, MUTED, "end"))
    return frame("When Jev says X% sure, how often is it right?",
                 "x: confidence it stated · y: how often it was right · 500 examples per task", b)


def fig_options():
    r = RES["x-options"]["by_number_of_options"]
    ks = list(r)
    x0, x1, top, bot = 330, 1130, 215, 730
    px = lambda i: x0 + i * (x1 - x0) / (len(ks) - 1)
    py = lambda v: bot - (v - 0.70) / 0.30 * (bot - top)
    b = []
    for v in (0.70, 0.80, 0.90, 1.0):
        b.append(f'<line x1="{x0 - 40}" x2="{x1 + 40}" y1="{py(v):.1f}" y2="{py(v):.1f}" stroke="{GRID}"/>')
        b.append(t(x0 - 56, py(v) + 7, f"{v:.0%}", 20, MUTED, "end"))
    for i, k in enumerate(ks):
        b.append(t(px(i), bot + 44, f"{k} options", 23, INK2, "middle"))
    series = [("Right, among answers at 0.9 or more", lambda v: v["at_0.9"]["accuracy"], SERIES[0]),
              ("Right, all answers", lambda v: v["accuracy"], SERIES[1]),
              ("Share of answers that clear 0.9", lambda v: v["at_0.9"]["coverage"], SERIES[2])]
    for name, f, c in series:
        vals = [f(r[k]) for k in ks]
        b.append(f'<polyline fill="none" stroke="{c}" stroke-width="3" stroke-linejoin="round" points="'
                 + " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(vals)) + '"/>')
        b += [f'<circle cx="{px(i):.1f}" cy="{py(v):.1f}" r="7" fill="{c}" stroke="{SURFACE}" stroke-width="2"/>' for i, v in enumerate(vals)]
        below = name != series[0][0]
        b.append(t(px(0) + 4, py(vals[0]) + (34 if below else -18), f"{vals[0]:.1%}", 20, INK, "middle", 700))
        b.append(t(px(len(ks) - 1) + 20, py(vals[-1]) + 7, f"{vals[-1]:.1%}", 22, INK, weight=700))
        b.append(t(px(len(ks) - 1) + 100, py(vals[-1]) + 7, name, 20, INK2))
    return frame("More options cost coverage, not safety",
                 "The same 300 requests, asked with 5, 20 and 59 options to choose from.", b)


def fig_missing():
    r = RES["x-oos"]
    a, c = r["A_no_exit_option"], r["B_with_exit_option"]
    tiles = [(f"{a['oos_median_top_probability']:.2f}", "median confidence when the right",
              f"answer is missing ({a['in_scope_median_top_probability']:.2f} when it is there)"),
             (f"{a['oos_share_at_or_above_0.9']:.0%}", "of those impossible questions still", "got an answer at 0.9 or more"),
             (f"{c['oos_caught']:.0%}", "caught once “none of these” is", "written in as an option")]
    b = []
    for i, (big, l1, l2) in enumerate(tiles):
        x = 70 + i * 500
        b.append(f'<rect x="{x}" y="230" width="460" height="400" rx="14" fill="#ffffff" stroke="{GRID}"/>')
        b.append(t(x + 40, 400, big, 130, INK, weight=700))
        b.append(t(x + 40, 480, l1, 23, INK2))
        b.append(t(x + 40, 514, l2, 23, INK2))
    b.append(t(70, 710, f"CLINC150: {r['n_in_scope']} requests with a right answer among 150 options, {r['n_out_of_scope']} without one. "
                        f"Adding the exit cost {a['in_scope_accuracy'] - c['in_scope_accuracy']:.1%} of accuracy on the rest.", 22, MUTED))
    return frame("What if the right answer isn't among the options?",
                 "Jev always picks one. Mostly its confidence drops. Not always.", b)


def fig_ignore():
    """Risk-coverage: automate the most confident answers first; how wrong are you as you automate more?"""
    pred = HERE.parent / "predictions"
    x0, x1, top, bot = 150, 1080, 215, 740
    px = lambda v: x0 + (v - 0.10) / 0.90 * (x1 - x0)
    py = lambda v: bot - v / 0.30 * (bot - top)
    b = []
    for v in (0, 0.10, 0.20, 0.30):
        b.append(f'<line x1="{x0}" x2="{x1}" y1="{py(v):.1f}" y2="{py(v):.1f}" stroke="{GRID}"/>')
        b.append(t(x0 - 16, py(v) + 7, f"{v:.0%}", 20, MUTED, "end"))
    for v in (0.10, 0.25, 0.5, 0.75, 1.0):
        b.append(t(px(v), bot + 36, f"{v:.0%}", 20, MUTED, "middle"))
    b.append(t((x0 + x1) / 2, bot + 78, "share of answers you let through without a person, most confident first", 21, INK2, "middle"))
    b.append(t(x0 - 96, top - 28, "wrong answers among them", 21, INK2))
    b.append(t(px(1.0), top - 28, "100% = ignore the confidence", 19, INK2, "middle"))
    b.append(f'<line x1="{px(1):.1f}" x2="{px(1):.1f}" y1="{top - 14}" y2="{bot}" stroke="{AXIS}" stroke-width="2"/>')
    focus = ["sms-spam", "duplicates", "banking77", "yelp-stars"]
    curves = {}
    for f in sorted(pred.glob("*.jsonl")):
        if f.stem.startswith("x-"):
            continue
        rows = sorted((json.loads(l) for l in f.read_text().splitlines()), key=lambda r: -r["p_top"])
        pts, wrong, gate = [], 0, None
        for i, r in enumerate(rows, 1):
            wrong += 1 - r["correct"]
            if i >= len(rows) // 10:
                pts.append((i / len(rows), wrong / i))
            if gate is None and r["p_top"] < 0.9:
                gate = ((i - 1) / len(rows), (wrong - (1 - r["correct"])) / max(1, i - 1))
        curves[f.stem] = (pts, gate)
    def line(name, color, width, opacity=1.0):
        pts = curves[name][0]
        return (f'<polyline fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round" opacity="{opacity}" points="'
                + " ".join(f"{px(a):.1f},{py(min(v, 0.30)):.1f}" for a, v in pts) + '"/>')
    b += [line(n, GRID, 2) for n in curves if n not in focus]
    for i, n in enumerate(focus):
        pts, gate = curves[n]
        b.append(line(n, SERIES[i], 3))
        b.append(f'<circle cx="{px(gate[0]):.1f}" cy="{py(gate[1]):.1f}" r="8" fill="{SURFACE}" stroke="{SERIES[i]}" stroke-width="3"/>')
        end = pts[-1][1]
        b.append(f'<circle cx="{px(1):.1f}" cy="{py(end):.1f}" r="7" fill="{SERIES[i]}" stroke="{SURFACE}" stroke-width="2"/>')
        b.append(t(px(1) + 22, py(end) + 7, f"{end:.1%}", 22, INK, weight=700))
        b.append(t(px(1) + 100, py(end) + 7, NAMES[n], 20, INK2))
    b.append(f'<circle cx="{x1 + 110}" cy="{bot + 71}" r="8" fill="{SURFACE}" stroke="{INK2}" stroke-width="3"/>')
    b.append(t(x1 + 130, bot + 78, "= where a gate at 0.9 stops", 20, INK2))
    b.append(t(x1 + 130, bot + 108, "grey lines: the other 8 tasks", 20, MUTED))
    return frame("Can you just ignore the confidence?",
                 "Sort the answers by confidence and let through more and more of them. The further right, the more errors get in.", b)


if __name__ == "__main__":
    for name, fn in (("ignore-confidence", fig_ignore), ("threshold", fig_threshold), ("reliability", fig_reliability), ("options", fig_options), ("missing-answer", fig_missing)):
        write(name, fn())
        print("wrote", name)
