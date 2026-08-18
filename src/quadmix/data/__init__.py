"""Data adapters, imported lazily so schema inspection stays lightweight."""

from importlib import import_module

_LAZY_EXPORTS = {
    "BaseDataAdapter": ("quadmix.data.base", "BaseDataAdapter"),
    "UnifiedData": ("quadmix.data.base", "UnifiedData"),
    "ParquetDataAdapter": ("quadmix.data.parquet_adapter", "ParquetDataAdapter"),
    "JSONLDataAdapter": ("quadmix.data.jsonl_adapter", "JSONLDataAdapter"),
    "CSVDataAdapter": ("quadmix.data.csv_adapter", "CSVDataAdapter"),
    "TxtDataAdapter": ("quadmix.data.txt_adapter", "TxtDataAdapter"),
    "get_adapter": ("quadmix.data.registry", "get_adapter"),
    "auto_detect_adapter": ("quadmix.data.registry", "auto_detect_adapter"),
}


def __getattr__(name):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = _LAZY_EXPORTS[name]
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


__all__ = list(_LAZY_EXPORTS)
