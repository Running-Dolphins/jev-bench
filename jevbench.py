#!/usr/bin/env python3
"""jev-bench: measure accuracy AND calibration of Jev (TypeSafe AI) on public datasets.

Standard library only. Needs TYPESAFE_API_KEY in the environment or in a local `.env` file.

    python3 jevbench.py list
    python3 jevbench.py run sms-spam --n 500
    python3 jevbench.py run all --n 300
    python3 jevbench.py experiment oos            # see `list` for all experiments
    python3 jevbench.py report                    # rebuilds RESULTS.md from results/*.json
    python3 jevbench.py run banking77 --dry-run   # no API calls, fake answers: tests the code

Per-example outputs go to raw/ (git-ignored: they contain dataset text). Aggregates go to
results/ and are what RESULTS.md is built from.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import random
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = os.environ.get("JEV_MODEL", "jev-latest")
PRICE_PER_MTOK = 0.042  # USD per million input tokens, output free (TypeSafe pricing, Sept 2026)
WORKERS = int(os.environ.get("JEV_WORKERS", "8"))
SEED = 0


# ----------------------------------------------------------------------------- API

def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def call(state, questions, dry_run=False, retries=6):
    """One Jev request. Returns (answers, usage, latency_s)."""
    if dry_run:
        return _fake(questions), {"input_tokens": 80, "output_tokens": 4}, 0.001
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        sys.exit("TYPESAFE_API_KEY is not set (export it, or put it in .env)")
    body = json.dumps({"state": state, "model": MODEL, "questions": questions}).encode()
    req = urllib.request.Request(
        API_URL, data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    wait = 1.0
    for i in range(retries):
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read())
            return data["answers"], data.get("usage", {}), time.perf_counter() - t0
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529) and i < retries - 1:
                time.sleep(wait)
                wait *= 2
                continue
            raise SystemExit(f"HTTP {e.code}: {e.read()[:400]!r}")
        except (urllib.error.URLError, TimeoutError):
            if i < retries - 1:
                time.sleep(wait)
                wait *= 2
                continue
            raise
    raise SystemExit("too many retries")


def _fake(questions):
    out = {}
    for k, q in questions.items():
        if q["type"] == "noul":
            out[k] = {"type": "noul", "noul": random.random()}
            continue
        crit = q["criteria"]
        keys = list(crit) if isinstance(crit, dict) else [str(i) for i in range(len(crit))]
        w = [random.random() ** 3 for _ in keys]
        prob = {c: x / sum(w) for c, x in zip(keys, w)}
        out[k] = {"type": q["type"], "probabilities": prob, "confidence": max(prob.values())}
    return out


def read_answer(ans):
    """-> (predicted label, top probability, confidence field or None, distribution)."""
    if ans["type"] == "noul":
        p = ans["noul"]
        return ("true" if p >= 0.5 else "false"), max(p, 1 - p), ans.get("confidence"), {"true": p, "false": 1 - p}
    prob = ans["probabilities"]
    top = max(prob, key=prob.get)
    return top, prob[top], ans.get("confidence"), prob


# ----------------------------------------------------------------------------- data

def _get(url):
    """GET with patience: the public datasets-server rate-limits bursts (HTTP 429)."""
    for i in range(8):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except Exception:
            if i == 7:
                raise
            time.sleep(min(60, 3 * 2 ** i))


def hf_rows(dataset, config, split, n, seed=SEED, page=100):
    """Random sample of n rows from a public Hugging Face dataset via datasets-server
    (no auth, no `datasets` dependency). Cached in data/. Returns (rows, features)."""
    cache = ROOT / "data" / f"{dataset.replace('/', '__')}__{config}__{split}__{n}__{seed}.json"
    if cache.exists():
        d = json.loads(cache.read_text())
        return d["rows"], d["features"]
    base = ("https://datasets-server.huggingface.co/rows?dataset=" + urllib.parse.quote(dataset, safe="")
            + f"&config={urllib.parse.quote(config)}&split={split}")
    first = json.loads(_get(base + "&offset=0&length=1"))
    total, features = first["num_rows_total"], first["features"]
    rng = random.Random(seed)
    starts = list(range(0, total, page))
    rng.shuffle(starts)
    rows = []
    for s in starts:
        if len(rows) >= n:
            break
        got = json.loads(_get(base + f"&offset={s}&length={page}"))
        rows += [r["row"] for r in got["rows"]]
        time.sleep(0.5)
        print(f"  downloading {dataset}: {min(len(rows), n)}/{n}", file=sys.stderr, end="\r")
    print(file=sys.stderr)
    rng.shuffle(rows)
    rows = rows[:n]
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps({"rows": rows, "features": features}, ensure_ascii=False))
    return rows, features


def class_names(features, column):
    for f in features:
        if f["name"] == column:
            return f["type"]["names"]
    raise KeyError(column)


def pretty(label):
    return label.replace("_", " ").replace("-", " ")


# ----------------------------------------------------------------------------- tasks
# A task returns (examples, question). Each example: {"state": str|dict, "label": str}.
# `question` is one Jev question: choice (criteria = {key: description}), score (criteria =
# ordered list, labels "0".."k"), or noul (labels "true"/"false").

def t_banking77(n):
    raw = _get("https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data/test.csv").decode()
    rows = list(csv.DictReader(io.StringIO(raw)))
    labels = sorted({r["category"] for r in rows})
    random.Random(SEED).shuffle(rows)
    ex = [{"state": r["text"], "label": r["category"]} for r in rows[:n]]
    return ex, {"type": "choice", "instructions": "Which banking support intent does this customer message express?",
                "criteria": {l: pretty(l) for l in labels}}


def _massive(lang):
    def task(n):
        rows, _ = hf_rows("mteb/amazon_massive_intent", lang, "test", 2974)  # whole split: EN and IT share ids
        rows.sort(key=lambda r: int(r["id"]))
        labels = sorted({r["label_text"] for r in rows})
        pick = random.Random(SEED).sample(range(len(rows)), min(n, len(rows)))
        ex = [{"state": rows[i]["text"], "label": rows[i]["label_text"], "id": rows[i]["id"]} for i in pick]
        instr = {"en": "Which intent does this voice-assistant request express?",
                 "it": "Quale intento esprime questa richiesta a un assistente vocale?"}[lang]
        return ex, {"type": "choice", "instructions": instr, "criteria": {l: pretty(l) for l in labels}}
    return task


def t_clinc(n, keep_oos=False):
    rows, feats = hf_rows("clinc/clinc_oos", "plus", "test", 3000)
    names = class_names(feats, "intent")
    inscope = [l for l in names if l != "oos"]
    ex = [{"state": r["text"], "label": names[r["intent"]]} for r in rows]
    if not keep_oos:
        ex = [e for e in ex if e["label"] != "oos"]
    return ex[:n], {"type": "choice", "instructions": "Which intent does this user request express?",
                    "criteria": {l: pretty(l) for l in inscope}}


def t_sms_spam(n):
    rows, _ = hf_rows("ucirvine/sms_spam", "plain_text", "train", n)
    ex = [{"state": r["sms"].strip(), "label": "true" if r["label"] == 1 else "false"} for r in rows]
    return ex, {"type": "noul", "instructions": "Is this text message spam?",
                "criteria": {"true": "unsolicited promotion, prize, scam or premium-rate bait",
                             "false": "a normal personal or transactional message"}}


def t_qqp(n):
    rows, _ = hf_rows("nyu-mll/glue", "qqp", "validation", n)
    ex = [{"state": {"request_a": r["question1"], "request_b": r["question2"]},
           "label": "true" if r["label"] == 1 else "false"} for r in rows]
    return ex, {"type": "noul", "instructions": "Are these two requests duplicates, i.e. would the same answer fully resolve both?"}


def t_boolq(n):
    rows, _ = hf_rows("google/boolq", "default", "validation", n)
    ex = [{"state": {"document": r["passage"], "question": r["question"]},
           "label": "true" if r["answer"] else "false"} for r in rows]
    return ex, {"type": "noul", "instructions": "According to the document, is the answer to the question yes?"}


def t_ledgar(n):
    rows, feats = hf_rows("coastalcph/lex_glue", "ledgar", "test", n)
    names = class_names(feats, "label")
    ex = [{"state": r["text"], "label": names[r["label"]]} for r in rows]
    return ex, {"type": "choice", "instructions": "What type of contract clause is this?",
                "criteria": {l: l for l in names}}


def t_yelp(n):
    rows, _ = hf_rows("Yelp/yelp_review_full", "yelp_review_full", "test", n)
    ex = [{"state": r["text"], "label": str(r["label"])} for r in rows]
    return ex, {"type": "score", "instructions": "How many stars did the customer give in this review?",
                "criteria": ["1 star: very dissatisfied", "2 stars: dissatisfied", "3 stars: mixed",
                             "4 stars: satisfied", "5 stars: very satisfied"]}


def t_sentiment_it(n):
    rows, _ = hf_rows("cardiffnlp/tweet_sentiment_multilingual", "italian", "test", min(n, 870))
    ex = [{"state": r["text"], "label": str(r["label"])} for r in rows]
    return ex, {"type": "score", "instructions": "Qual è il sentimento espresso da questo tweet?",
                "criteria": ["Negativo: lamentela, rabbia, tristezza, disprezzo",
                             "Neutro: informazione o commento senza carica emotiva",
                             "Positivo: entusiasmo, affetto, approvazione, gioia"]}


AG_DESCR = {"World": "international politics, conflicts, diplomacy, disasters",
            "Sports": "matches, athletes, leagues, results",
            "Business": "companies, markets, economy, earnings, deals",
            "Sci/Tech": "technology, science, software, internet, space"}


def t_agnews(n, described=True):
    rows, feats = hf_rows("fancyzhx/ag_news", "default", "test", n)
    names = class_names(feats, "label")
    ex = [{"state": r["text"], "label": names[r["label"]]} for r in rows]
    return ex, {"type": "choice", "instructions": "Which desk should this news item be routed to?",
                "criteria": {l: (AG_DESCR[l] if described else l) for l in names}}


def t_offensive(n):
    rows, _ = hf_rows("cardiffnlp/tweet_eval", "offensive", "test", min(n, 860))
    ex = [{"state": r["text"], "label": "true" if r["label"] == 1 else "false"} for r in rows]
    return ex, {"type": "noul", "instructions": "Is this post offensive (insults, slurs, targeted attacks, profanity aimed at someone)?"}


TASKS = {
    "banking77":    (t_banking77,    "choice · 77 options",  "Route a bank customer's message to one of 77 intents (PolyAI Banking77, EN)"),
    "massive-en":   (_massive("en"), "choice · 59 options",  "Voice-assistant intent, English (Amazon MASSIVE) — parallel to massive-it"),
    "massive-it":   (_massive("it"), "choice · 59 options",  "Same utterances translated to Italian (Amazon MASSIVE)"),
    "clinc150":     (t_clinc,        "choice · 150 options", "Intent routing with 150 in-scope intents (CLINC150, EN)"),
    "ledgar":       (t_ledgar,       "choice · 100 options", "Contract clause type, from SEC filings (LEDGAR / LexGLUE, EN)"),
    "ag-news":      (t_agnews,       "choice · 4 options",   "Route a news item to a desk (AG News, EN)"),
    "sms-spam":     (t_sms_spam,     "noul",                 "Is this message spam? (UCI SMS Spam Collection, EN)"),
    "duplicates":   (t_qqp,          "noul",                 "Are these two requests duplicates? (Quora Question Pairs, EN)"),
    "doc-yesno":    (t_boolq,        "noul",                 "Does the document answer yes to this question? (BoolQ, EN)"),
    "offensive":    (t_offensive,    "noul",                 "Moderation: is this post offensive? (TweetEval, EN)"),
    "yelp-stars":   (t_yelp,         "score · 5 levels",     "Predict the 1-5 star rating of a review (Yelp, EN)"),
    "sentiment-it": (t_sentiment_it, "score · 3 levels",     "Sentiment of Italian tweets (CardiffNLP multilingual)"),
}


# ----------------------------------------------------------------------------- metrics

def ece(pairs, bins=10):
    """pairs = [(p, correct)] -> (expected calibration error, reliability table)."""
    table, err = [], 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        inside = [(p, c) for p, c in pairs if lo < p <= hi or (b == 0 and p == 0)]
        if not inside:
            continue
        conf = statistics.fmean(p for p, _ in inside)
        acc = statistics.fmean(c for _, c in inside)
        err += len(inside) / len(pairs) * abs(conf - acc)
        table.append({"lo": lo, "hi": hi, "n": len(inside), "stated": round(conf, 4), "actual": round(acc, 4)})
    return err, table


def auroc(scores_pos, scores_neg):
    """P(score of a random positive > score of a random negative). 0.5 = useless."""
    if not scores_pos or not scores_neg:
        return float("nan")
    wins = sum((p > q) + 0.5 * (p == q) for p in scores_pos for q in scores_neg)
    return wins / (len(scores_pos) * len(scores_neg))


def confidence_value(rows, gate=0.9):
    """What the confidence is worth on a task. `rows` need p_top and correct."""
    n = len(rows)
    right = [r["p_top"] for r in rows if r["correct"]]
    wrong = [r["p_top"] for r in rows if not r["correct"]]
    passed = [r for r in rows if r["p_top"] >= gate]
    low = [r for r in rows if r["p_top"] < 0.7]
    wrong_passed = sum(1 - r["correct"] for r in passed)
    return {
        "error_if_you_ignore_confidence": round(len(wrong) / n, 4),
        "error_among_answers_above_gate": round(wrong_passed / len(passed), 4) if passed else None,
        "share_of_errors_stopped_by_gate": round(1 - wrong_passed / len(wrong), 4) if wrong else None,
        "share_of_right_answers_held_back": round(1 - (len(passed) - wrong_passed) / len(right), 4) if right else None,
        "accuracy_below_0.7": round(statistics.fmean(r["correct"] for r in low), 4) if low else None,
        "n_below_0.7": len(low),
        "auroc_confidence_separates_right_from_wrong": round(auroc(right, wrong), 4) if right and wrong else None,
    }


def summarize(name, rows, meta=None):
    n = len(rows)
    e, table = ece([(r["p_top"], r["correct"]) for r in rows])
    lat = sorted(r["latency_s"] for r in rows)
    tok = sum(r["usage"].get("input_tokens", 0) for r in rows)
    out = {
        "name": name, "n": n, "model": MODEL, "date": time.strftime("%Y-%m-%d"),
        "accuracy": round(statistics.fmean(r["correct"] for r in rows), 4),
        "ece": round(e, 4),
        "brier": round(statistics.fmean(
            sum((p - (1.0 if k == r["label"] else 0.0)) ** 2 for k, p in r["prob"].items()) for r in rows), 4),
        "thresholds": {},
        "reliability": table,
        "latency_median_s": round(statistics.median(lat), 3),
        "latency_p90_s": round(lat[max(0, int(0.9 * n) - 1)], 3),
        "input_tokens": tok,
        "usd_per_1000_decisions": round(tok / 1e6 * PRICE_PER_MTOK / n * 1000, 4),
    }
    for t in (0.5, 0.7, 0.8, 0.9, 0.95, 0.99):
        above = [r for r in rows if r["p_top"] >= t]
        out["thresholds"][str(t)] = {
            "coverage": round(len(above) / n, 4),
            "accuracy": round(statistics.fmean(r["correct"] for r in above), 4) if above else None,
            "errors_let_through": sum(1 - r["correct"] for r in above)}
    if all(r.get("confidence") is not None for r in rows):
        out["ece_confidence_field"] = round(ece([(r["confidence"], r["correct"]) for r in rows])[0], 4)
    out["confidence_value"] = confidence_value(rows)
    if meta:
        out.update(meta)
    return out


def show(s):
    print(f"\n== {s['name']} · n={s['n']} ==")
    print(f"accuracy {s['accuracy']:.1%} · ECE {s['ece']:.3f} · Brier {s['brier']:.3f} · "
          f"median {s['latency_median_s']:.2f}s · ${s['usd_per_1000_decisions']:.4f} per 1,000 decisions")
    print("threshold  coverage  accuracy above  errors let through")
    for t, v in s["thresholds"].items():
        acc = f"{v['accuracy']:.1%}" if v["accuracy"] is not None else "   —"
        print(f"  ≥{t:<5}   {v['coverage']:6.1%}     {acc:>6}         {v['errors_let_through']}")
    print("reliability — stated confidence vs actual accuracy")
    for b in s["reliability"]:
        gap = b["actual"] - b["stated"]
        print(f"  {b['lo']:.1f}-{b['hi']:.1f}  n={b['n']:<5} stated {b['stated']:.2f}  actual {b['actual']:.2f}  "
              f"{'over-confident' if gap < -0.05 else 'under-confident' if gap > 0.05 else 'ok':<15} {'#' * int(b['actual'] * 30)}")


# ----------------------------------------------------------------------------- runner

def run_examples(examples, question, dry_run=False, per_example_question=None):
    """Asks `question` about every example. `per_example_question(ex)` overrides it per example."""
    def one(ex):
        q = per_example_question(ex) if per_example_question else question
        ans, usage, lat = call(ex["state"], {"q": q}, dry_run=dry_run)
        pred, p_top, conf, prob = read_answer(ans["q"])
        return {**ex, "pred": pred, "p_top": p_top, "confidence": conf, "prob": prob,
                "correct": 1 if pred == ex["label"] else 0, "latency_s": lat, "usage": usage}
    rows = []
    with ThreadPoolExecutor(max_workers=1 if dry_run else WORKERS) as pool:
        for i, r in enumerate(pool.map(one, examples), 1):
            rows.append(r)
            if i % 100 == 0:
                print(f"  {i}/{len(examples)}", file=sys.stderr, end="\r")
    return rows


def save(name, rows, summary, dry_run):
    if dry_run:
        return
    (ROOT / "raw").mkdir(exist_ok=True)
    (ROOT / "results").mkdir(exist_ok=True)
    with open(ROOT / "raw" / f"{name}.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (ROOT / "results" / f"{name}.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    export_predictions(name, rows)


KEEP = ("id", "label", "pred", "p_top", "confidence", "correct", "k", "order", "repeat", "variant")


def export_predictions(name, rows):
    """Per-example predictions WITHOUT the dataset text: safe to commit, enough to recompute
    every table (accuracy, reliability, thresholds) without calling the API again."""
    (ROOT / "predictions").mkdir(exist_ok=True)
    with open(ROOT / "predictions" / f"{name}.jsonl", "w") as f:
        for i, r in enumerate(rows):
            slim = {"i": i, **{k: r[k] for k in KEEP if k in r}}
            slim["p_top"] = round(slim["p_top"], 4)
            slim["latency_s"] = round(r["latency_s"], 3)
            slim["input_tokens"] = r["usage"].get("input_tokens", 0)
            f.write(json.dumps(slim, ensure_ascii=False) + "\n")


def run_task(name, n, dry_run):
    fn, kind, descr = TASKS[name]
    examples, q = fn(n)
    rows = run_examples(examples, q, dry_run)
    s = summarize(name, rows, {"kind": kind, "description": descr})
    show(s)
    save(name, rows, s, dry_run)
    return rows, s


# ----------------------------------------------------------------------------- experiments

def x_oos(n, dry_run):
    """What happens when the right answer is not among the options?
    CLINC150 ships 'out-of-scope' requests. A: no exit option — does low confidence flag them?
    B: an explicit exit option is added — does Jev take it?"""
    examples, q = t_clinc(10 ** 6, keep_oos=True)
    ins = [e for e in examples if e["label"] != "oos"][:n]
    oos = [e for e in examples if e["label"] == "oos"][:max(50, n // 2)]
    out = {"name": "x-oos", "n_in_scope": len(ins), "n_out_of_scope": len(oos), "date": time.strftime("%Y-%m-%d")}
    rows_a = run_examples(ins + oos, q, dry_run)
    a_in, a_oos = rows_a[:len(ins)], rows_a[len(ins):]
    out["A_no_exit_option"] = {
        "in_scope_accuracy": round(statistics.fmean(r["correct"] for r in a_in), 4),
        "oos_median_top_probability": round(statistics.median(r["p_top"] for r in a_oos), 4),
        "in_scope_median_top_probability": round(statistics.median(r["p_top"] for r in a_in), 4),
        "oos_share_at_or_above_0.9": round(sum(r["p_top"] >= 0.9 for r in a_oos) / len(a_oos), 4),
        "oos_share_at_or_above_0.7": round(sum(r["p_top"] >= 0.7 for r in a_oos) / len(a_oos), 4),
        "auroc_top_probability_detects_oos": round(auroc([-r["p_top"] for r in a_oos], [-r["p_top"] for r in a_in]), 4),
    }
    if all(r["confidence"] is not None for r in rows_a):
        out["A_no_exit_option"]["auroc_confidence_field_detects_oos"] = round(
            auroc([-r["confidence"] for r in a_oos], [-r["confidence"] for r in a_in]), 4)
    q_b = {**q, "criteria": {**q["criteria"], "oos": "none of the listed intents: the request is out of scope"}}
    rows_b = run_examples(ins + oos, q_b, dry_run)
    b_in, b_oos = rows_b[:len(ins)], rows_b[len(ins):]
    out["B_with_exit_option"] = {
        "in_scope_accuracy": round(statistics.fmean(r["correct"] for r in b_in), 4),
        "oos_caught": round(statistics.fmean(r["correct"] for r in b_oos), 4),
        "in_scope_wrongly_sent_to_exit": round(sum(r["pred"] == "oos" for r in b_in) / len(b_in), 4),
    }
    return out, rows_a + rows_b


def x_language(n, dry_run):
    """Same utterances, English vs Italian (MASSIVE is a parallel corpus)."""
    en, q_en = _massive("en")(n)
    it, q_it = _massive("it")(n)
    assert [e["id"] for e in en] == [e["id"] for e in it]
    r_en, r_it = run_examples(en, q_en, dry_run), run_examples(it, q_it, dry_run)
    # Italian text, English instructions: isolates the language of the *input*
    r_mix = run_examples(it, q_en, dry_run)
    out = {"name": "x-language", "n": len(en), "date": time.strftime("%Y-%m-%d")}
    for k, rows in (("english", r_en), ("italian", r_it), ("italian_text_english_instructions", r_mix)):
        s = summarize(k, rows)
        out[k] = {"accuracy": s["accuracy"], "ece": s["ece"], "at_0.9": s["thresholds"]["0.9"]}
    out["both_right"] = sum(a["correct"] and b["correct"] for a, b in zip(r_en, r_it))
    out["only_english_right"] = sum(a["correct"] and not b["correct"] for a, b in zip(r_en, r_it))
    out["only_italian_right"] = sum(b["correct"] and not a["correct"] for a, b in zip(r_en, r_it))
    return out, r_en + r_it + r_mix


def x_options(n, dry_run):
    """Same examples, 5 / 20 / 60 options: the right one plus random distractors."""
    examples, q = _massive("en")(n)
    labels = list(q["criteria"])
    out = {"name": "x-options", "n": len(examples), "date": time.strftime("%Y-%m-%d"), "by_number_of_options": {}}
    allrows = []
    for k in (5, 20, len(labels)):
        def per_ex(ex, k=k):
            rng = random.Random(f"{ex['id']}-{k}")
            others = rng.sample([l for l in labels if l != ex["label"]], k - 1)
            keep = sorted(others + [ex["label"]])
            return {**q, "criteria": {l: q["criteria"][l] for l in keep}}
        rows = run_examples(examples, None, dry_run, per_example_question=per_ex)
        s = summarize(f"{k} options", rows)
        out["by_number_of_options"][str(k)] = {"accuracy": s["accuracy"], "ece": s["ece"], "at_0.9": s["thresholds"]["0.9"],
                                                 "usd_per_1000_decisions": s["usd_per_1000_decisions"]}
        allrows += [{**r, "k": k} for r in rows]
    return out, allrows


def x_order(n, dry_run):
    """Same question, options listed in 3 different orders. Does the answer move?"""
    examples, q = t_banking77(n)
    labels = list(q["criteria"])
    runs = []
    for s in range(3):
        order = labels[:]
        random.Random(s).shuffle(order)
        runs.append(run_examples(examples, {**q, "criteria": {l: q["criteria"][l] for l in order}}, dry_run))
    flips = [len({r[i]["pred"] for r in runs}) > 1 for i in range(len(examples))]
    stable_conf = [statistics.fmean(r[i]["p_top"] for r in runs) for i in range(len(examples)) if not flips[i]]
    flip_conf = [statistics.fmean(r[i]["p_top"] for r in runs) for i in range(len(examples)) if flips[i]]
    hi = [i for i in range(len(examples)) if min(r[i]["p_top"] for r in runs) >= 0.9]
    out = {"name": "x-order", "n": len(examples), "date": time.strftime("%Y-%m-%d"),
           "accuracy_per_order": [round(statistics.fmean(x["correct"] for x in r), 4) for r in runs],
           "answer_changed_with_order": round(sum(flips) / len(flips), 4),
           "mean_top_probability_when_stable": round(statistics.fmean(stable_conf), 4) if stable_conf else None,
           "mean_top_probability_when_it_flips": round(statistics.fmean(flip_conf), 4) if flip_conf else None,
           "share_always_at_or_above_0.9": round(len(hi) / len(examples), 4),
           "flips_among_always_at_or_above_0.9": sum(flips[i] for i in hi)}
    return out, [{**x, "order": s} for s, r in enumerate(runs) for x in r]


def x_repeat(n, dry_run):
    """The exact same request 5 times. How much does the number move on its own?"""
    examples, q = t_banking77(n)
    runs = [run_examples(examples, q, dry_run) for _ in range(5)]
    spread = [max(r[i]["p_top"] for r in runs) - min(r[i]["p_top"] for r in runs) for i in range(len(examples))]
    flips = [len({r[i]["pred"] for r in runs}) > 1 for i in range(len(examples))]
    cross = [min(r[i]["p_top"] for r in runs) < 0.9 <= max(r[i]["p_top"] for r in runs) for i in range(len(examples))]
    out = {"name": "x-repeat", "n": len(examples), "repeats": 5, "date": time.strftime("%Y-%m-%d"),
           "median_spread_of_top_probability": round(statistics.median(spread), 4),
           "p95_spread": round(sorted(spread)[int(0.95 * len(spread)) - 1], 4),
           "answer_changed_between_repeats": round(sum(flips) / len(flips), 4),
           "crossed_the_0.9_line_between_repeats": round(sum(cross) / len(cross), 4)}
    return out, [{**x, "repeat": s} for s, r in enumerate(runs) for x in r]


def x_descriptions(n, dry_run):
    """Bare label names vs one line of description per option (AG News, 4 options)."""
    out = {"name": "x-descriptions", "date": time.strftime("%Y-%m-%d")}
    allrows = []
    for k, described in (("labels_only", False), ("with_descriptions", True)):
        examples, q = t_agnews(n, described)
        rows = run_examples(examples, q, dry_run)
        s = summarize(k, rows)
        out["n"] = s["n"]
        out[k] = {"accuracy": s["accuracy"], "ece": s["ece"], "at_0.9": s["thresholds"]["0.9"]}
        allrows += [{**r, "variant": k} for r in rows]
    return out, allrows


EXPERIMENTS = {
    "oos": (x_oos, "The right answer is not among the options: does the confidence tell you?"),
    "language": (x_language, "Same requests in English and Italian (parallel corpus)"),
    "options": (x_options, "Same examples with 5, 20 and 59 options"),
    "order": (x_order, "Same options in a different order: does the answer move?"),
    "repeat": (x_repeat, "Same request five times: how stable is the number?"),
    "descriptions": (x_descriptions, "Bare labels vs one line of description per option"),
}


# ----------------------------------------------------------------------------- report

def pct(x):
    return "—" if x is None else f"{x:.1%}"


def wilson(k, n, z=1.96):
    """95% interval for k right out of n (Wilson score)."""
    p, d = k / n, 1 + z * z / n
    c, h = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def experiment_tables(res):
    """Markdown for each experiment, one small table each."""
    L = []
    if "x-oos" in res:
        r = res["x-oos"]; a, b = r["A_no_exit_option"], r["B_with_exit_option"]
        L += [f"### `oos` — {EXPERIMENTS['oos'][1]}", "",
              f"CLINC150, {r['n_in_scope']} in-scope and {r['n_out_of_scope']} out-of-scope requests.", "",
              "![What happens when the right answer is missing](figures/missing-answer.png)", "",
              "| Without a \"none of these\" option | |", "|---|---|",
              f"| Median top probability, in-scope requests | {a['in_scope_median_top_probability']:.2f} |",
              f"| Median top probability, out-of-scope requests | {a['oos_median_top_probability']:.2f} |",
              f"| Top probability separates the two (AUROC) | {a['auroc_top_probability_detects_oos']:.2f} |",
              f"| Out-of-scope requests answered at ≥ 0.9 anyway | {pct(a['oos_share_at_or_above_0.9'])} |",
              f"| Out-of-scope requests answered at ≥ 0.7 anyway | {pct(a['oos_share_at_or_above_0.7'])} |", "",
              "| With the option added | |", "|---|---|",
              f"| Out-of-scope requests caught | {pct(b['oos_caught'])} |",
              f"| In-scope requests wrongly sent to the exit | {pct(b['in_scope_wrongly_sent_to_exit'])} |",
              f"| In-scope accuracy, before → after | {pct(a['in_scope_accuracy'])} → {pct(b['in_scope_accuracy'])} |", ""]
    if "x-language" in res:
        r = res["x-language"]
        L += [f"### `language` — {EXPERIMENTS['language'][1]}", "", f"MASSIVE, the same {r['n']} requests.", "",
              "| | Accuracy | ECE | Coverage ≥0.9 | Accuracy ≥0.9 |", "|---|---|---|---|---|"]
        for k, name in (("english", "English"), ("italian", "Italian"),
                        ("italian_text_english_instructions", "Italian text, English instructions")):
            v = r[k]
            L.append(f"| {name} | {pct(v['accuracy'])} | {v['ece']:.3f} | {pct(v['at_0.9']['coverage'])} | {pct(v['at_0.9']['accuracy'])} |")
        L += ["", f"Both right: {r['both_right']} · only English right: {r['only_english_right']} · "
                  f"only Italian right: {r['only_italian_right']}.", ""]
    if "x-options" in res:
        r = res["x-options"]
        L += [f"### `options` — {EXPERIMENTS['options'][1]}", "",
              f"MASSIVE (EN), the same {r['n']} requests; the right option plus random distractors. Random distractors are the easy case: real queues resemble each other more.", "",
              "![Accuracy and coverage with 5, 20 and 59 options](figures/options.png)", "",
              "| Options | Accuracy | ECE | Coverage ≥0.9 | Accuracy ≥0.9 | $ / 1,000 |", "|---|---|---|---|---|---|"]
        for k, v in r["by_number_of_options"].items():
            L.append(f"| {k} | {pct(v['accuracy'])} | {v['ece']:.3f} | {pct(v['at_0.9']['coverage'])} | "
                     f"{pct(v['at_0.9']['accuracy'])} | {v['usd_per_1000_decisions']:.4f} |")
        L.append("")
    if "x-order" in res:
        r = res["x-order"]
        L += [f"### `order` — {EXPERIMENTS['order'][1]}", "", f"Banking77, {r['n']} requests, 77 options in three random orders.", "",
              "| | |", "|---|---|",
              f"| Accuracy in each order | {' · '.join(pct(x) for x in r['accuracy_per_order'])} |",
              f"| Requests whose answer changed with the order | {pct(r['answer_changed_with_order'])} |",
              f"| Mean top probability when the answer is stable / when it flips | {r['mean_top_probability_when_stable']:.2f} / {r['mean_top_probability_when_it_flips']:.2f} |",
              f"| Requests at ≥ 0.9 in all three orders | {pct(r['share_always_at_or_above_0.9'])} |",
              f"| …of which changed answer | {r['flips_among_always_at_or_above_0.9']} |", ""]
    if "x-repeat" in res:
        r = res["x-repeat"]
        L += [f"### `repeat` — {EXPERIMENTS['repeat'][1]}", "", f"Banking77, {r['n']} requests, each sent {r['repeats']} times unchanged.", "",
              "| | |", "|---|---|",
              f"| Spread of the top probability across repeats, median / 95th percentile | {r['median_spread_of_top_probability']:.2f} / {r['p95_spread']:.2f} |",
              f"| Requests whose answer changed between repeats | {pct(r['answer_changed_between_repeats'])} |",
              f"| Requests that crossed the 0.9 line between repeats | {pct(r['crossed_the_0.9_line_between_repeats'])} |", ""]
    if "x-descriptions" in res:
        r = res["x-descriptions"]
        L += [f"### `descriptions` — {EXPERIMENTS['descriptions'][1]}", "", f"AG News, {r['n']} items, 4 options.", "",
              "| Criteria | Accuracy | ECE | Coverage ≥0.9 | Accuracy ≥0.9 |", "|---|---|---|---|---|"]
        for k, name in (("labels_only", "Label names only"), ("with_descriptions", "One line of description each")):
            v = r[k]
            L.append(f"| {name} | {pct(v['accuracy'])} | {v['ece']:.3f} | {pct(v['at_0.9']['coverage'])} | {pct(v['at_0.9']['accuracy'])} |")
        L.append("")
    return L


def report():
    res = {p.stem: json.loads(p.read_text()) for p in sorted((ROOT / "results").glob("*.json"))}
    tasks = sorted((r for k, r in res.items() if not k.startswith("x-")), key=lambda r: -(r["thresholds"]["0.9"]["accuracy"] or 0))
    L = ["# Results", "",
         f"Model `{tasks[0]['model']}`, run on {tasks[0]['date']}. One run per task, random sample with a fixed seed. "
         "Measurements on *these* datasets with *these* prompts: examples of what you can measure, not properties of the model.", "",
         "How a number is produced, which dataset and which question each task uses, and the limits of all this: see the "
         "[README](README.md#how-every-number-is-produced). Throughout, **the answer is Jev's most probable option and "
         "\"confidence\" is that option's probability**; right or wrong is judged against the dataset's own label.", "",
         "![How often Jev was right above 0.9, per task](figures/threshold.png)", "",
         "## Tasks", "", "Sorted by accuracy above the 0.9 line. *Coverage ≥0.9* is the share of answers at 0.9 or more; "
         "*Accuracy ≥0.9* is how many of those were right, with its 95% interval (Wilson): with a few hundred answers "
         "the last digit is not to be trusted.", "",
         "| Task | Type | n | Accuracy | ECE | Coverage ≥0.9 | Accuracy ≥0.9 | 95% interval | Median latency | $ / 1,000 |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for r in tasks:
        t = r["thresholds"]["0.9"]
        above = round(t["coverage"] * r["n"])
        lo, hi = wilson(above - t["errors_let_through"], above)
        kind = TASKS[r["name"]][1] if r["name"] in TASKS else r.get("kind", "")
        L.append(f"| `{r['name']}` | {kind} | {r['n']} | {pct(r['accuracy'])} | {r['ece']:.3f} | {pct(t['coverage'])} | "
                 f"**{pct(t['accuracy'])}** | {lo:.1%} – {hi:.1%} | {r['latency_median_s']:.2f} s | {r['usd_per_1000_decisions']:.4f} |")
    L += ["", "## With and without the gate", "",
          "One row per task, 500 answers each. Two ways to use Jev are compared. **Ignore the confidence**: take the most "
          "probable answer every time and act on all 500. **Gate at 0.9**: act only on the answers whose probability is "
          "0.9 or more, send the rest to a person.", "",
          "Worked example, `duplicates` (500 pairs from Quora Question Pairs): ignoring the confidence, 83 answers of 500 "
          "are wrong (16.6%). With the gate, 272 answers run on their own and 3 of them are wrong (1.1%): the gate stopped "
          "80 of the 83 errors (96.4%). The price: of the 228 answers sent to a person, 148 were right, which is 35.5% of "
          "all the right answers.", "",
          "![What a gate at 0.9 does to 500 answers, four tasks](figures/gate.png)", "",
          "Columns: *Wrong if you ignore it* = error rate on all 500 · *Wrong above 0.9* = error rate among the answers the "
          "gate lets through · *Errors the gate stops* = share of all errors that fell below 0.9 · *Right answers held "
          "back* = share of all right answers that fell below 0.9 · *Right when confidence < 0.7* = accuracy among the "
          "least confident answers.", "",
          "| Task | Wrong if you ignore it | Wrong above 0.9 | Errors the gate stops | Right answers held back | Right when confidence < 0.7 | AUROC |",
          "|---|---|---|---|---|---|---|"]
    for r in sorted(tasks, key=lambda r: -(r["confidence_value"]["error_if_you_ignore_confidence"])):
        c = r["confidence_value"]
        L.append(f"| `{r['name']}` | {pct(c['error_if_you_ignore_confidence'])} | {pct(c['error_among_answers_above_gate'])} | "
                 f"{pct(c['share_of_errors_stopped_by_gate'])} | {pct(c['share_of_right_answers_held_back'])} | "
                 f"{pct(c['accuracy_below_0.7'])} (n={c['n_below_0.7']}) | {c['auroc_confidence_separates_right_from_wrong']:.2f} |")
    L += ["", "AUROC: the chance that a right answer carries a higher confidence than a wrong one. 0.5 means the number is noise, 1.0 means it sorts them perfectly.", "",
          "The same comparison for every possible gate, not just 0.9. Answers are sorted from most to least confident; at "
          "x = 60% you act on the most confident 60% and y is the error rate among them. The hollow dot is the gate at 0.9, "
          "the right edge is no gate at all. The curves start at 25% because with fewer answers one error moves the line by "
          "whole points. Some curves do not start at zero: there are wrong answers even at probability 1.00 (11 of 191 on "
          "`banking77`, 14 of 187 on `ledgar`), and how many of those are errors in the dataset's labels we did not check.", "",
          "![Error rate as you automate more of the answers, 12 tasks](figures/ignore-confidence.png)", ""]
    L += ["", "## Reliability: stated confidence vs actual accuracy", "", "![Reliability diagram](figures/reliability.png)", "",
          "Each cell: how often Jev was right among the answers whose top probability fell in that band (n in brackets). "
          "A calibrated model shows ~0.55 under 0.5-0.6 and ~0.95 under 0.9-1.0. Mind the n: a cell with 13 answers has a "
          "95% interval of about ±25 points, and the chart leaves out cells with fewer than 10.", "",
          "| Task | " + " | ".join(f"{b / 10:.1f}-{(b + 1) / 10:.1f}" for b in range(5, 10)) + " |", "|---|" + "---|" * 5]
    for r in tasks:
        cells = {round(b["lo"], 1): f"{b['actual']:.2f} ({b['n']})" for b in r["reliability"]}
        L.append(f"| `{r['name']}` | " + " | ".join(cells.get(round(b / 10, 1), "—") for b in range(5, 10)) + " |")
    L += ["", "## Experiments", ""] + experiment_tables(res)
    (ROOT / "RESULTS.md").write_text("\n".join(L) + "\n")
    print(f"RESULTS.md written ({len(tasks)} tasks) — figures: python3 figures/make_figures.py")


# ----------------------------------------------------------------------------- cli

def main():
    load_env()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["list", "run", "experiment", "report"])
    ap.add_argument("name", nargs="?")
    ap.add_argument("--n", type=int, default=300, help="examples per task (default 300)")
    ap.add_argument("--dry-run", action="store_true", help="no API calls: fake answers, nothing saved")
    a = ap.parse_args()
    if a.command == "list":
        print("TASKS")
        for k, (_, kind, d) in TASKS.items():
            print(f"  {k:<14} {kind:<22} {d}")
        print("\nEXPERIMENTS")
        for k, (_, d) in EXPERIMENTS.items():
            print(f"  {k:<14} {d}")
    elif a.command == "report":
        report()
    elif a.command == "run":
        names = list(TASKS) if a.name == "all" else [a.name]
        for nm in names:
            if nm not in TASKS:
                sys.exit(f"unknown task {nm!r}: see `list`")
            run_task(nm, a.n, a.dry_run)
    else:
        names = list(EXPERIMENTS) if a.name == "all" else [a.name]
        for nm in names:
            if nm not in EXPERIMENTS:
                sys.exit(f"unknown experiment {nm!r}: see `list`")
            out, rows = EXPERIMENTS[nm][0](a.n, a.dry_run)
            print(json.dumps(out, indent=1, ensure_ascii=False))
            if not a.dry_run:
                save(f"x-{nm}", rows, out, False)


if __name__ == "__main__":
    main()
