#!/usr/bin/env bash
# Stage-1 arms: P1/Ma/Mb x removing/placing/kidnapping, fixed 2-worker pool
set -u
PY=${PY:-/data/conda_envs/dynamic_3dgs/bin/python}
ENV_BIN=$(dirname "$PY"); export PATH="$ENV_BIN:$PATH"
EXP=lifecycle_gate
ARMS=(${@:-"P1 Ma Mb"})   # queue split across GPUs by arm name
declare -A LCS=( [P1]=placebo [Ma]=retire [Mb]=full )
SEQS=(rgbd_bonn_removing_nonobstructing_box rgbd_bonn_placing_nonobstructing_box rgbd_bonn_kidnapping_box)
mkdir -p "results/${EXP}/logs"
run_one() {
    local arm=$1 lc=$2 seq=$3
    if [ -f "results/${EXP}/${seq}_${arm}/seed_0/manifest.json" ]; then
        echo "SKIP ${seq}_${arm}"; return 0
    fi
    echo "RUN ${seq}_${arm}"
    "$PY" scripts/run_baseline.py --config "configs/bonn/${seq}.yaml" \
        --exp-id "${EXP}_${arm}" --seed 0 --lifecycle "$lc" \
        > "results/${EXP}/logs/${seq}_${arm}.log" 2>&1
    [ $? -eq 0 ] && echo "DONE ${seq}_${arm}" || echo "FAIL ${seq}_${arm}"
    return 0
}
i=0
for arm in ${ARMS[@]}; do
    for seq in "${SEQS[@]}"; do
        run_one "$arm" "${LCS[$arm]}" "$seq" &
        i=$((i+1))
        if [ "$i" -ge 2 ]; then wait -n || true; i=$((i-1)); fi
    done
done
wait
echo "ARMS_DONE"
