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

DATASETS = {
    "sms-spam": "UCI SMS Spam", "duplicates": "Quora Question Pairs", "clinc150": "CLINC150",
    "doc-yesno": "BoolQ", "massive-en": "Amazon MASSIVE", "massive-it": "Amazon MASSIVE",
    "offensive": "TweetEval", "ag-news": "AG News", "sentiment-it": "CardiffNLP tweets",
    "banking77": "Banking77", "ledgar": "LEDGAR · SEC filings", "yelp-stars": "Yelp reviews",
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
        b.append(t(x0 - 30, y + 1, NAMES[r["name"]], 22, INK, "end"))
        b.append(t(x0 - 30, y + 20, DATASETS[r["name"]], 15, MUTED, "end"))
        b.append(f'<line x1="{px(0.75):.1f}" x2="{px(v):.1f}" y1="{y}" y2="{y}" stroke="{SERIES[0]}" stroke-width="2" opacity="0.28"/>')
        b.append(f'<circle cx="{px(v):.1f}" cy="{y}" r="9" fill="{SERIES[0]}" stroke="{SURFACE}" stroke-width="2"/>')
        b.append(t(px(v) + 18, y + 7, f"{v:.1%}", 22, INK, weight=700).replace("<text ", f'<text stroke="{SURFACE}" stroke-width="7" paint-order="stroke" '))
        b.append(t(x1 + 130, y + 7, f"{cov:.0%}", 22, INK2))
    return frame("“90% sure” is not one number",
                 "How often Jev's top answer was right when its probability was 0.9 or more. 12 public datasets, 500 examples each.", b)


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
                 "x: probability of its top answer · y: how often that answer was right · 500 examples per task · bands under 10 answers not drawn", b)


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


def fig_method():
    """How a number is born, on one task: one example -> 500 rows -> count."""
    rows = sorted((json.loads(l) for l in (HERE.parent / "predictions" / "duplicates.jsonl").read_text().splitlines()),
                  key=lambda r: -r["p_top"])
    n = len(rows)
    above = [r for r in rows if r["p_top"] >= 0.9]
    below = rows[len(above):]
    wrong = lambda rs: sum(1 - r["correct"] for r in rs)
    yn = {"true": "yes", "false": "no"}
    cw, gap, top, ch = 470, 25, 185, 580
    b = []
    for i, title in enumerate(["1 · Ask Jev one question", f"2 · Do it {n} times", "3 · Count the wrong ones"]):
        x = 70 + i * (cw + gap)
        b.append(f'<rect x="{x}" y="{top}" width="{cw}" height="{ch}" rx="14" fill="#ffffff" stroke="{GRID}"/>')
        b.append(t(x + 30, top + 50, title, 27, INK, weight=700))
    # card 1: one real example
    x, y = 100, top + 100
    for label, lines, big in [("TWO REQUESTS FROM THE DATASET", ["“Why do I always feel a headache?”", "“Why do we feel headache?”"], False),
                              ("THE QUESTION", ["Are these two requests duplicates?"], False),
                              ("JEV ANSWERS", ["yes · confidence 0.57"], True),
                              ("THE PEOPLE WHO BUILT THE DATASET SAID", ["no"], True)]:
        b.append(t(x, y, label, 14, MUTED, weight=700))
        for k, line in enumerate(lines):
            b.append(t(x, y + 30 + k * 27, line, 24 if big else 20, INK, weight=700 if big else 400))
        y += 62 + 27 * len(lines)
    b.append(f'<line x1="{x}" x2="{x + cw - 60}" y1="{y - 8}" y2="{y - 8}" stroke="{GRID}"/>')
    b.append(t(x, y + 26, "→ this answer counts as wrong", 21, INK, weight=700))
    b.append(t(x, y + 54, "Public datasets come with the right answer", 17, INK2))
    b.append(t(x, y + 77, "already written by people. That is the referee.", 17, INK2))
    # card 2: real rows, sorted by confidence, with the gate drawn across
    x = 70 + cw + gap + 30
    cols = [(0, "Jev said"), (105, "confidence"), (225, "people said"), (345, "result")]
    y = top + 100
    for dx, h in cols:
        b.append(t(x + dx, y, h.upper(), 13, MUTED, weight=700))
    pick = [0, len(above) // 2, len(above) - 1, None, len(above), len(above) + len(below) // 3, len(above) + 2 * len(below) // 3, n - 1]
    y += 34
    for idx in pick:
        if idx is None:
            y += 16
            b.append(f'<line x1="{x - 10}" x2="{x + cw - 50}" y1="{y - 12}" y2="{y - 12}" stroke="{INK2}" stroke-width="2" stroke-dasharray="7 5"/>')
            b.append(t(x + cw - 50, y - 20, "the gate: 0.9", 15, INK2, "end", 700))
            y += 22
            continue
        r = rows[idx]
        b.append(t(x, y, yn[r["pred"]], 20, INK))
        b.append(t(x + 105, y, f"{r['p_top']:.2f}", 20, INK))
        b.append(t(x + 225, y, yn[r["label"]], 20, INK))
        c = SERIES[0] if r["correct"] else SERIES[1]
        b.append(f'<circle cx="{x + 353}" cy="{y - 7}" r="7" fill="{c}"/>')
        b.append(t(x + 370, y, "right" if r["correct"] else "wrong", 20, INK))
        y += 40
        if idx in (0, len(above)):
            b.append(t(x, y - 12, "…", 20, MUTED))
            y += 16
    b.append(t(x, top + ch - 62, f"{n} real rows, sorted from most to least confident.", 17, INK2))
    b.append(t(x, top + ch - 38, f"{len(above)} are at 0.9 or more, {len(below)} are below.", 17, INK2))
    # card 3: the numbers
    x = 70 + 2 * (cw + gap) + 30
    y = top + 100
    for label, big, small in [
            ("NO GATE: ACT ON ALL THE ROWS", f"{wrong(rows)} wrong of {n} = {wrong(rows) / n:.1%}", "Jev used as a plain classifier: top answer, every time."),
            ("GATE AT 0.9: ACT ONLY ON THE ROWS ABOVE THE LINE", f"{wrong(above)} wrong of {len(above)} = {wrong(above) / len(above):.1%}", "These run on their own. The error that gets through."),
            ("THE ROWS BELOW THE LINE GO TO A PERSON", f"{len(below)} rows: {wrong(below)} wrong, {len(below) - wrong(below)} right", "Wrong ones stopped. The right ones are the price.")]:
        b.append(t(x, y, label, 13, MUTED, weight=700))
        b.append(t(x, y + 40, big, 28, INK, weight=700))
        b.append(t(x, y + 68, small, 16, INK2))
        y += 140
    b.append(t(70, top + ch + 46, "Same recipe for every task. The answer is always Jev's most probable option (for yes / no: yes if P(yes) ≥ 0.5) and the confidence is its probability.", 20, INK2))
    return frame("How a number on this page is born",
                 "One task from start to finish: “are these two requests duplicates?”, 500 pairs from Quora Question Pairs.", b)


def fig_gate():
    """No gate vs gate at 0.9, as two literal bars per task. Counts, not rates."""
    pred = HERE.parent / "predictions"
    focus = ["sms-spam", "duplicates", "banking77", "yelp-stars"]
    RIGHT, WRONG = SERIES[0], SERIES[1]
    x0, sc, top, block, bh, ggap = 560, 1.5, 215, 138, 26, 60
    b = [t(x0 + 500 * sc + ggap + 120, top - 22, "wrong answers", 17, INK2, "middle"),
         t(x0 + 500 * sc + ggap + 120, top - 2, "acted on", 17, INK2, "middle")]
    def seg(x, y, w, c):
        return f'<rect x="{x:.1f}" y="{y}" width="{max(w, 3):.1f}" height="{bh}" rx="3" fill="{c}"/>' if w > 0 else ""
    for i, n in enumerate(focus):
        rows = [json.loads(l) for l in (pred / f"{n}.jsonl").read_text().splitlines()]
        ar = sum(1 for r in rows if r["p_top"] >= 0.9 and r["correct"]); aw = sum(1 for r in rows if r["p_top"] >= 0.9 and not r["correct"])
        hr = sum(1 for r in rows if r["p_top"] < 0.9 and r["correct"]); hw = sum(1 for r in rows if r["p_top"] < 0.9 and not r["correct"])
        y = top + i * block + 20
        b.append(t(70, y + 20, NAMES[n], 22, INK))
        b.append(t(70, y + 44, f"{DATASETS[n]} · {len(rows)} answers", 16, MUTED))
        xn = x0 + 500 * sc + ggap + 120
        # row A: no gate
        b.append(t(x0 - 16, y + 19, "no gate", 18, INK2, "end"))
        b.append(seg(x0, y, (ar + hr) * sc - 2, RIGHT)); b.append(seg(x0 + (ar + hr) * sc, y, (aw + hw) * sc, WRONG))
        b.append(t(xn, y + 21, f"{aw + hw}", 26, INK, "middle", 700))
        # row B: gate at 0.9, two groups
        y2 = y + bh + 10
        b.append(t(x0 - 16, y2 + 19, "gate at 0.9", 18, INK2, "end"))
        b.append(seg(x0, y2, ar * sc - 2, RIGHT)); b.append(seg(x0 + ar * sc, y2, aw * sc, WRONG))
        xp = x0 + (ar + aw) * sc + ggap
        b.append(seg(xp, y2, hr * sc - 2, RIGHT)); b.append(seg(xp + hr * sc, y2, hw * sc, WRONG))
        b.append(t(xn, y2 + 21, f"{aw}", 26, INK, "middle", 700))
        b.append(t(x0, y2 + bh + 22, f"{ar + aw} run on their own", 16, INK2))
        b.append(t(xp, y2 + bh + 22, f"{hr + hw} go to a person" + (f" ({hw} wrong, {hr} right)" if (hr + hw) * sc > 230 else ""), 16, INK2))
    ly = top + block * len(focus) + 40
    b.append(f'<rect x="70" y="{ly - 15}" width="18" height="18" rx="3" fill="{RIGHT}"/>')
    b.append(t(98, ly, "answer was right", 20, INK2))
    b.append(f'<rect x="290" y="{ly - 15}" width="18" height="18" rx="3" fill="{WRONG}"/>')
    b.append(t(318, ly, "answer was wrong", 20, INK2))
    b.append(t(540, ly, "bar length = number of answers · gate at 0.9 = only answers with confidence 0.9 or more run on their own", 18, MUTED))
    return frame("Top answer every time, or a person below 0.9?",
                 "The same 500 answers, used two ways. With the gate, the wrong answers below 0.9 reach a person instead of going through.", b)


def fig_ignore():
    """Risk-coverage: automate the most confident answers first; how wrong are you as you automate more?"""
    pred = HERE.parent / "predictions"
    x0, x1, top, bot = 150, 1080, 215, 740
    px = lambda v: x0 + (v - 0.25) / 0.75 * (x1 - x0)
    py = lambda v: bot - v / 0.30 * (bot - top)
    b = []
    for v in (0, 0.10, 0.20, 0.30):
        b.append(f'<line x1="{x0}" x2="{x1}" y1="{py(v):.1f}" y2="{py(v):.1f}" stroke="{GRID}"/>')
        b.append(t(x0 - 16, py(v) + 7, f"{v:.0%}", 20, MUTED, "end"))
    for v in (0.25, 0.5, 0.75, 1.0):
        b.append(t(px(v), bot + 36, f"{v:.0%}", 20, MUTED, "middle"))
    b.append(t((x0 + x1) / 2, bot + 78, "← stricter gate, more work for people  ·  share of answers that run without a person  ·  no gate →", 21, INK2, "middle"))
    b.append(t(x0 - 96, top - 28, "wrong answers among them", 21, INK2))
    b.append(t(px(1.0), top - 28, "100% = no gate, top answer always", 19, INK2, "middle"))
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
            if i >= len(rows) // 4:
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
    g, e = curves["duplicates"][1], curves["duplicates"][0][-1][1]
    for k, line in enumerate(["How to read the orange line:", f"at the ○ (gate at 0.9) {g[0]:.0%} of the answers run",
                              f"on their own and {g[1]:.1%} of them are wrong.", f"At the right edge they all do: {e:.1%} wrong."]):
        b.append(t(x1 + 22, 520 + k * 27, line, 19, INK if k == 0 else INK2, weight=700 if k == 0 else 400))
    b.append(f'<circle cx="{x1 + 110}" cy="{bot + 71}" r="8" fill="{SURFACE}" stroke="{INK2}" stroke-width="3"/>')
    b.append(t(x1 + 130, bot + 78, "= where a gate at 0.9 stops", 20, INK2))
    b.append(t(x1 + 130, bot + 108, "grey lines: the other 8 tasks", 20, MUTED))
    return frame("The stricter the gate, the fewer errors get through",
                 "12 public datasets, 500 answers each, sorted by confidence. Let through more of them (go right) and more errors get in.", b)


if __name__ == "__main__":
    for name, fn in (("method", fig_method), ("gate", fig_gate), ("ignore-confidence", fig_ignore), ("threshold", fig_threshold), ("reliability", fig_reliability), ("options", fig_options), ("missing-answer", fig_missing)):
        write(name, fn())
        print("wrote", name)
