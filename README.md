# jev-bench

Measure **accuracy and calibration** of [Jev](https://typesafe.ai) (TypeSafe AI's decision model) on public datasets, on tasks that look like the decisions a business actually automates: route this message, is this a duplicate, is this spam, what kind of clause is this, how unhappy is this customer.

One Python file, standard library only, no dataset to download by hand. A full run of all twelve tasks at 500 examples each costs a few cents.

> Not affiliated with TypeSafe AI. Built by [Running Dolphins](https://runningdolphins.com) because at launch nobody outside TypeSafe had published a calibration measurement, and the confidence number is the whole point of the model.

## Why calibration, not just accuracy

Jev doesn't write text. You give it some state and a closed question, and it returns probabilities plus a confidence number. That number is what makes a decision automatable: above a threshold the step runs on its own, below it a person looks.

That only works if the number means what it says. **If the model says 0.9, is it right 9 times out of 10?** Accuracy can't answer that. A reliability table can:

```
banking77 · reliability — stated confidence vs actual accuracy
  0.5-0.6  n=33    stated 0.55  actual 0.42  over-confident
  0.6-0.7  n=26    stated 0.65  actual 0.42  over-confident
  0.8-0.9  n=45    stated 0.86  actual 0.73  over-confident
  0.9-1.0  n=333   stated 0.98  actual 0.90  over-confident
```

Read it as: "of the answers where Jev claimed 80-90%, 73% were right". On a different task (`sms-spam`) the same band is right 99% of the time: the model is *under*-confident there. Same model, same band, opposite behaviour. That gap, per band, is what tells you where to put your threshold.

## What we saw (one run, 20 September 2026)

Observations, not laws. Each one is a reason to run the table on your own data.

- **"0.9" is not one number.** Above 0.9 Jev was right 99.8% of the time on spam, 98.9% on duplicates, 95-97% on intent routing, 86.7% on contract clauses and 81.6% on exact star ratings. The threshold has to be set per task.
- **The middle of the range was over-confident on multi-option tasks, not on yes/no ones.** Between 0.5 and 0.7, routing tasks claimed ~0.6 and were right 32-56% of the time. On `doc-yesno` the same band was right 70-78%, and on `sms-spam` 71-85%: under-confident.
- **More options cost coverage, not safety.** Same examples with 5 / 20 / 59 options: accuracy 97.7% → 92.3% → 86.7%, but accuracy above 0.9 stayed at 99.6% → 98.1% → 97.4%. What dropped is the share of answers that clear the bar (92% → 86% → 76%).
- **Italian cost nothing here.** Same 300 requests in English and Italian: 87.0% and 87.0%, ten errors unique to each side, 97.8% vs 98.1% above 0.9.
- **When the right answer is missing, the confidence mostly says so, but not always.** Out-of-scope requests got a median top probability of 0.54 against 1.00 for in-scope ones (AUROC 0.91), yet 15% of them still came back at 0.9 or more. Adding an explicit "none of these" option caught 73% of them and cost 0.3 points of in-scope accuracy.
- **Instability lives where confidence is low.** Shuffling the order of 77 options changed the answer 8.7% of the time, never among answers that stayed above 0.9. The same request sent five times changed answer 3% of the time and crossed the 0.9 line 4.7% of the time: a gate at 0.9 is not perfectly deterministic near the line.
- **On an ordered scale, wrong means slightly wrong.** Star ratings: 70.4% exact, 99.6% within one star, and no error of two stars or more above 0.9.
- **One line of description per option did not help** on a 4-option task (93.3% bare labels, 92.7% described). A null result on one easy task, nothing more.
- **Latency was flat** at about 0.9 s from Italy for every task, against the 70-500 ms on the product page. Cost ran from $0.014 to $0.10 per thousand decisions, driven by how many options you list.

## Quick start

```bash
git clone https://github.com/Running-Dolphins/jev-bench.git && cd jev-bench
cp .env.example .env          # paste your TypeSafe API key
python3 jevbench.py list
python3 jevbench.py run sms-spam --n 200
python3 jevbench.py run all --n 500
python3 jevbench.py experiment all --n 300
python3 jevbench.py report    # rebuilds RESULTS.md
```

`--dry-run` makes no API calls (fake answers) and is there to test the code.

## Tasks

| Task | Jev question type | The business decision it stands for |
|---|---|---|
| `banking77` | choice · 77 options | route a customer message to the right queue, many queues |
| `clinc150` | choice · 150 options | same, with very many intents |
| `massive-en` / `massive-it` | choice · 60 options | same requests in English and Italian (parallel corpus) |
| `ledgar` | choice · 100 options | what type of contract clause is this |
| `ag-news` | choice · 4 options | coarse routing, few options |
| `sms-spam` | noul (true/false) | filter junk before it reaches a person |
| `duplicates` | noul | is this ticket a duplicate of that one |
| `doc-yesno` | noul | does this document say yes to this question (policy checks) |
| `offensive` | noul | content moderation |
| `yelp-stars` | score · 5 ordered levels | how satisfied is this customer |
| `sentiment-it` | score · 3 levels | sentiment, in Italian |

## Experiments

Accuracy on a benchmark is the least interesting thing you can measure. These are the questions that decide whether you can put the model in a process:

| Experiment | Question |
|---|---|
| `oos` | The right answer is **not among the options**. Does the confidence drop, or does it pick something at 0.9? And if you add a "none of these" option, does it use it? |
| `language` | Same requests in English and Italian. How much do you lose? |
| `options` | Same examples with 5, 20, 60 options. What does each extra option cost? |
| `order` | Same options, shuffled. Does the answer change? Does it change above 0.9? |
| `repeat` | Same request five times. How much does the number move on its own, and how often does it cross your threshold? |
| `descriptions` | Bare label names vs one line of description per option. |
| `length` | Accuracy and calibration for short vs long inputs (reads saved runs, no API calls). |

## Results

Ours are in [RESULTS.md](RESULTS.md), with date and sample size. **They are measurements on these datasets, with these prompts, on one day.** Public datasets have noisy labels, which lowers measured accuracy and makes calibration look worse than it is. Treat every number as an example of what you can measure, not as a property of the model. The useful move is to run the same table on a few hundred of *your* labelled examples:

```python
# your_task.py — add a task in ten lines
from jevbench import run_examples, summarize, show, load_env
load_env()
examples = [{"state": "text of the email…", "label": "billing"}, ...]   # label = the truth
question = {"type": "choice", "instructions": "Which team should handle this email?",
            "criteria": {"billing": "invoices, charges, refunds", "tech": "bugs, access", "sales": "quotes, upgrades"}}
show(summarize("my-inbox", run_examples(examples, question)))
```

## What is in the repo, and what is not

- `results/*.json` — aggregates (accuracy, ECE, thresholds, reliability table). Committed.
- `raw/` — per-example outputs. **Git-ignored**: they contain dataset text, and yours may contain your data.
- `data/` — dataset cache. Git-ignored. Datasets are fetched from their public sources (Hugging Face datasets-server, PolyAI's GitHub); check each dataset's licence before reusing the data itself.
- `.env` — your key. Git-ignored.

## Licence

MIT.
