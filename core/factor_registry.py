from typing import Dict, Type, List, Optional


class FactorRegistry:
    """因子注册表：装饰器自动注册，告别手动维护 __init__.py"""
    _factors: Dict[str, Type] = {}
    _metadata: Dict[str, Dict] = {}

    @classmethod
    def register(cls, name: str = None, category: str = "uncategorized",
                 description: str = "", asset: str = "", data_deps: list = None,
                 status: str = "active"):
        """Register a factor class.

        Args:
            status: factor status - "active", "experimental", or "deprecated"
        """
        def decorator(factor_cls):
            key = name or factor_cls.__name__
            cls._factors[key] = factor_cls
            cls._metadata[key] = {
                "name": key,
                "category": category,
                "description": description,
                "asset": asset,
                "data_deps": data_deps or [],
                "status": status,
            }
            factor_cls._factor_name = key
            factor_cls._category = category
            factor_cls._description = description
            factor_cls._asset = asset
            factor_cls._data_deps = data_deps or []
            factor_cls._status = status
            return factor_cls
        return decorator

    @classmethod
    def sync_from_chains(cls, chains_config: Dict[str, Dict]) -> int:
        """Align in-memory registry metadata with chains.yaml as the runtime source of truth.

        This does not change the registered classes themselves; it only updates the
        metadata exposed by ``info()`` and other registry views.  Parameterized
        chains may share one factor class under several chain names; those names
        are added as aliases to the same class.
        """
        updated = 0
        for name, cfg in chains_config.items():
            factor_cls = cls._factors.get(name)
            if factor_cls is None:
                class_name = cfg.get("factor_class")
                factor_cls = next(
                    (registered_cls for registered_cls in cls._factors.values()
                     if registered_cls.__name__ == class_name),
                    None,
                )
                if factor_cls is None:
                    continue
                cls._factors[name] = factor_cls
                updated += 1
            metadata = cls._metadata.setdefault(name, {"name": name})
            for attr, field in (("_category", "category"), ("_description", "description"),
                              ("_asset", "asset"), ("_data_deps", "data_deps")):
                current = metadata.get(field)
                desired = cfg.get(field, [] if field == "data_deps" else "")
                if current != desired:
                    metadata[field] = desired
                    updated += 1
                    # Keep class-level attributes for legacy callers.  For aliases
                    # the key-specific metadata above is authoritative.
                    setattr(factor_cls, attr, desired)
        return updated

    @classmethod
    def get(cls, name: str) -> Optional[Type]:
        return cls._factors.get(name)

    @classmethod
    def list_all(cls) -> List[str]:
        return list(cls._factors.keys())

    @classmethod
    def list_by_category(cls, category: str) -> List[str]:
        return [k for k in cls._factors
                if cls._metadata.get(k, {}).get('category', getattr(cls._factors[k], '_category', '')) == category]

    @classmethod
    def categories(cls) -> List[str]:
        cats = set()
        for key, factor_cls in cls._factors.items():
            cat = cls._metadata.get(key, {}).get('category', getattr(factor_cls, '_category', 'uncategorized'))
            if '/' in cat:
                cats.add(cat.split('/')[0])
            else:
                cats.add(cat)
        return sorted(cats)

    @classmethod
    def info(cls, name: str) -> Optional[Dict]:
        factor_cls = cls._factors.get(name)
        if factor_cls is None:
            return None
        metadata = cls._metadata.get(name)
        if metadata is not None:
            return {
                "name": metadata.get("name", name),
                "category": metadata.get("category", ""),
                "description": metadata.get("description", ""),
                "asset": metadata.get("asset", ""),
                "data_deps": metadata.get("data_deps", []),
            }
        return {
            "name": getattr(factor_cls, '_factor_name', name),
            "category": getattr(factor_cls, '_category', ''),
            "description": getattr(factor_cls, '_description', ''),
            "asset": getattr(factor_cls, '_asset', ''),
            "data_deps": getattr(factor_cls, '_data_deps', []),
        }

    @classmethod
    def list_all_info(cls) -> List[Dict]:
        return [cls.info(k) for k in cls._factors]

    @classmethod
    def size(cls) -> int:
        return len(cls._factors)