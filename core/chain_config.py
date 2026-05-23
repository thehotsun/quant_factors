"""Unified chain configuration layer.

Builds ``ChainDefinition`` objects by merging ``chains.yaml`` runtime config
with ``FactorRegistry`` metadata, and exposes consistency checks so that
drift between the two surfaces is caught early.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ChainDefinition:
    """Immutable description of a single analysis chain.

    Combines the runtime configuration from ``chains.yaml`` (factor_module,
    factor_class, symbol, far_symbol, sub_chains, params) with the static
    metadata registered via ``@FactorRegistry.register`` (category, description,
    asset, data_deps).
    """
    name: str
    category: str = ""
    description: str = ""
    asset: str = ""
    trade_asset: str = ""
    trade_asset_type: str = ""  # etf / stock / futures / basket / index / ""
    execution_asset: str = ""  # real tradeable ticker, e.g. "159865"
    signal_target: str = ""    # semantic target, e.g. "breeding_profit"
    data_deps: tuple = ()
    drivers: dict = field(default_factory=dict)
    factor_module: str = ""
    factor_class: str = ""
    symbol: str = ""
    far_symbol: str = ""
    sub_chains: tuple = ()
    params: dict = field(default_factory=dict)

    @property
    def is_composite(self) -> bool:
        return self.category == "composite" or bool(self.sub_chains)

    @property
    def has_factor(self) -> bool:
        return bool(self.factor_module and self.factor_class)


def build_chain_definitions(
    chains_config: Dict[str, Dict[str, Any]],
    registry_info_fn=None,
) -> Dict[str, ChainDefinition]:
    """Build unified ``ChainDefinition`` for every chain in ``chains_config``.

    ``registry_info_fn`` is an optional callable ``(name) -> dict|None`` that
    returns registry metadata for a chain name.  When provided, the returned
    metadata is merged with the YAML config, with YAML values taking precedence
    for runtime fields (factor_module, symbol, params, …) and registry values
    filling in metadata fields (category, description, asset, data_deps) when
    the YAML does not specify them.
    """
    defs: Dict[str, ChainDefinition] = {}
    for name, cfg in chains_config.items():
        reg = registry_info_fn(name) if registry_info_fn else None
        merged = dict(reg) if reg else {}
        # YAML always wins for runtime fields
        merged.update(cfg)

        defs[name] = ChainDefinition(
            name=name,
            category=merged.get("category", ""),
            description=merged.get("description", ""),
            asset=merged.get("asset", ""),
            trade_asset=merged.get("trade_asset", merged.get("asset", "")),
            trade_asset_type=merged.get("trade_asset_type", ""),
            execution_asset=merged.get("execution_asset", ""),
            signal_target=merged.get("signal_target", ""),
            data_deps=tuple(merged.get("data_deps", []) or []),
            drivers=dict(merged.get("drivers", {}) or {}),
            factor_module=merged.get("factor_module", ""),
            factor_class=merged.get("factor_class", ""),
            symbol=merged.get("symbol", ""),
            far_symbol=merged.get("far_symbol", ""),
            sub_chains=tuple(merged.get("sub_chains", []) or []),
            params=dict(merged.get("params", {}) or {}),
        )
    return defs


@dataclass
class MetadataDiff:
    chain: str
    field: str
    yaml_value: Any
    registry_value: Any


def check_metadata_consistency(
    chains_config: Dict[str, Dict[str, Any]],
    registry_info_fn,
) -> List[MetadataDiff]:
    """Return non-fatal metadata drift between chains.yaml and registry."""
    diffs: List[MetadataDiff] = []
    for name, cfg in chains_config.items():
        reg = registry_info_fn(name)
        if reg is None:
            continue
        for field_name in ("category", "description", "asset", "data_deps"):
            yaml_val = cfg.get(field_name, [] if field_name == "data_deps" else "")
            reg_val = reg.get(field_name, [] if field_name == "data_deps" else "")
            if yaml_val != reg_val:
                diffs.append(MetadataDiff(
                    chain=name,
                    field=field_name,
                    yaml_value=yaml_val,
                    registry_value=reg_val,
                ))
    return diffs
