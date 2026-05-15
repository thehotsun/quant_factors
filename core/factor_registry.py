from typing import Dict, Type, List, Optional


class FactorRegistry:
    """因子注册表：装饰器自动注册，告别手动维护 __init__.py"""
    _factors: Dict[str, Type] = {}

    @classmethod
    def register(cls, name: str = None, category: str = "uncategorized",
                 description: str = "", asset: str = "", data_deps: list = None):
        def decorator(factor_cls):
            key = name or factor_cls.__name__
            cls._factors[key] = factor_cls
            factor_cls._factor_name = key
            factor_cls._category = category
            factor_cls._description = description
            factor_cls._asset = asset
            factor_cls._data_deps = data_deps or []
            return factor_cls
        return decorator

    @classmethod
    def get(cls, name: str) -> Optional[Type]:
        return cls._factors.get(name)

    @classmethod
    def list_all(cls) -> List[str]:
        return list(cls._factors.keys())

    @classmethod
    def list_by_category(cls, category: str) -> List[str]:
        return [k for k, v in cls._factors.items()
                if getattr(v, '_category', '') == category]

    @classmethod
    def categories(cls) -> List[str]:
        cats = set()
        for v in cls._factors.values():
            cat = getattr(v, '_category', 'uncategorized')
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