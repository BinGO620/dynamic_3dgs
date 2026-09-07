#!/usr/bin/env bash
# Batch baseline runner with a fixed worker pool (DISCIPLINE.md GPU policy).
# Usage: bash scripts/run_baselines.sh <exp_id> <n_workers> <seq1> [seq2 ...]
#   e.g. bash scripts/run_baselines.sh baseline_vanilla 1 removing_nonobstructing_box placing_nonobstructing_box
set -u

PY=${PY:-/data/conda_envs/dynamic_3dgs/bin/python}
# torch cpp_extension needs ninja on PATH: prepend the env's bin dir
ENV_BIN=$(dirname "$PY")
export PATH="$ENV_BIN:$PATH"
EXP_ID=$1; shift
NWORKERS=$1; shift
SEQS=("$@")
mkdir -p "results/${EXP_ID}/logs"

run_one() {
    local seq=$1
    # skip if manifest already exists (idempotent restart)
    if [ -f "results/${EXP_ID}/${seq}/seed_0/manifest.json" ]; then
        echo "SKIP ${seq} (manifest exists)"
        return 0
    fi
    echo "RUN  ${seq}"
    "$PY" scripts/run_baseline.py \
        --config "configs/bonn/${seq}.yaml" \
        --exp-id "$EXP_ID" --seed 0 \
        > "results/${EXP_ID}/logs/${seq}.log" 2>&1
    local rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "FAIL ${seq} (rc=${rc})"
    else
        echo "DONE ${seq}"
    fi
    return 0
}

# fixed worker pool over the sequence list
pids=()
i=0
for seq in "${SEQS[@]}"; do
    run_one "$seq" &
    pids+=($!)
    i=$((i + 1))
    if [ "$i" -ge "$NWORKERS" ]; then
        wait -n || true
        i=$((i - 1))
    fi
done
wait
echo "ALL DONE"
