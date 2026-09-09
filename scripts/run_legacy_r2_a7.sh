#!/bin/bash
# A7 rev3: kf_every_frame=true (dense keyframing). Outputs into *_a7 dirs.
set -u
cd /data/dynamic_3dgs
export CUDA_VISIBLE_DEVICES=0
PY=/data/conda_envs/dynamic_3dgs/bin/python
run_one () {
  echo "=== $1 -> $2 ==="
  $PY scripts/run_legacy.py --config "$1" --out "$2"
  local rc=$?
  echo "=== rc=$rc $2 ==="
  return 0
}
run_one configs/legacy/bonn_removing_nonobstructing_box.yaml results/legacy_core/bonn_removing_a7/seed_0
run_one configs/legacy/bonn_placing_nonobstructing_box.yaml results/legacy_core/bonn_placing_a7/seed_0
run_one configs/legacy/tum_walking_xyz.yaml results/legacy_core/tum_walking_xyz_a7/seed_0
exit 0
