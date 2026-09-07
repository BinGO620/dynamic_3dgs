"""Config loading with inherit_from merge (lightweight, no torch)."""

from __future__ import annotations

import copy
import os

import yaml


def _repo_root(config_path: str) -> str:
    """Walk up from the config dir until a `configs` directory is found."""
    d = os.path.dirname(os.path.abspath(config_path))
    while True:
        if os.path.basename(d) == "configs":
            return os.path.dirname(d)
        parent = os.path.dirname(d)
        if parent == d:
            return os.getcwd()
        d = parent


def load_config(path: str) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    base = cfg.pop("inherit_from", None)
    if base and base != "null":
        base_path = os.path.normpath(os.path.join(_repo_root(path), base))
        parent = load_config(base_path)
        merged = copy.deepcopy(parent)
        for k, v in cfg.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k].update(v)
            else:
                merged[k] = v
        return merged
    return cfg
