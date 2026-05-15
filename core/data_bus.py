from pathlib import Path
from typing import Dict, Optional
import logging
import pandas as pd

logger = logging.getLogger(__name__)


class DataBus:
    """单例数据中心：统一加载+缓存，所有因子共享，避免重复 I/O"""
    _instance: Optional["DataBus"] = None

    def __new__(cls, data_dir: str = "./data"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._data_dir = Path(data_dir)
            cls._instance._cache = {}
        elif str(cls._instance._data_dir) != str(Path(data_dir)):
            logger.warning(
                f"DataBus 已用 data_dir={cls._instance._data_dir} 初始化，"
                f"忽略新参数 data_dir={data_dir}"
            )
        return cls._instance

    @classmethod
    def reset(cls):
        if cls._instance is not None:
            cls._instance._cache.clear()
        cls._instance = None

    def get(self, name: str, date_col: str = 'date') -> Optional[pd.DataFrame]:
        if name in self._cache:
            return self._cache[name]
        path = self._data_dir / f"{name}.parquet"
        if not path.exists():
            return None
        df = pd.read_parquet(path)
        if date_col in df.columns:
            df[date_col] = pd.to_datetime(df[date_col])
            df = df.sort_values(date_col)
        self._cache[name] = df
        return df

    def invalidate(self, name: str = None):
        if name:
            self._cache.pop(name, None)
        else:
            self._cache.clear()

    def preload(self, names: list):
        for name in names:
            self.get(name)

    @property
    def cache_stats(self) -> Dict[str, int]:
        return {k: len(v) for k, v in self._cache.items()}