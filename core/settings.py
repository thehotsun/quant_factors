"""Centralized runtime settings and config loading for quant_factors."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

import yaml

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
CHAINS_CONFIG_PATH = CONFIG_DIR / "chains.yaml"
FACTOR_PARAMS_PATH = CONFIG_DIR / "factor_params.yaml"
PUSH_CONFIG_PATH = CONFIG_DIR / "push.yaml"
SIGNALS_DB_PATH = DATA_DIR / "signals.db"
IC_DB_PATH = DATA_DIR / "ic_monitor.db"
REFRESH_MANIFEST_PATH = DATA_DIR / "refresh_manifest.json"


def load_yaml(path: Path) -> Dict[str, Any]:
    """Load a YAML file as a dict, returning an empty dict for empty files."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_chains_config(path: Path = CHAINS_CONFIG_PATH) -> Dict[str, Dict[str, Any]]:
    """Load chain runtime configuration from chains.yaml."""
    try:
        config = load_yaml(path)
        chains = config.get("chains")
        if not isinstance(chains, dict):
            raise ValueError("chains.yaml missing top-level 'chains' mapping")
        return chains
    except Exception as e:
        logger.error("加载 chains.yaml 失败: %s", e)
        raise


def load_factor_params(path: Path = FACTOR_PARAMS_PATH) -> Dict[str, Any]:
    """Load optional factor parameter overrides."""
    if not path.exists():
        return {}
    try:
        config = load_yaml(path)
        return config.get("factors", {}) or {}
    except Exception as e:
        logger.warning("加载 factor_params.yaml 失败: %s", e)
        return {}
