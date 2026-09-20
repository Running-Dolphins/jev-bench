#!/bin/sh
# Runs every task and every experiment, then rebuilds RESULTS.md. Expects TYPESAFE_API_KEY in the env or in .env
cd "$(dirname "$0")"
python3 jevbench.py run all --n "${N:-500}" > run-all.log 2>&1
python3 jevbench.py experiment all --n "${NX:-300}" > run-x.log 2>&1
python3 jevbench.py report >> run-x.log 2>&1
echo done > .done
