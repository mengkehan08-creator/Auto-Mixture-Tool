"""User-facing bounds use effective values, not the sampler's internal scales."""
import math

DEFAULT_BOUNDS = {'omega': (0.0, 0.1), 'epsilon': (0.0, 0.001),
                  'lambda': (0.0, 1000.0), 'eta': (0.0, 1.0)}


def validate_sampling_bounds(value=None):
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - set(DEFAULT_BOUNDS):
        raise ValueError('sampling_bounds 仅支持 omega、epsilon、lambda、eta')
    result = {}
    for name, default in DEFAULT_BOUNDS.items():
        pair = value.get(name, default)
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError(f'{name} 必须包含下限和上限')
        if any(type(n) not in (float, int) or not math.isfinite(n) for n in pair):
            raise ValueError(f'{name} 上下限必须为有限数值')
        low, high = pair
        if low < 0 or high < low or (name != 'lambda' and high > 1):
            raise ValueError(f'{name} 范围无效：要求 0 ≤ 下限 ≤ 上限' + (' ≤ 1' if name != 'lambda' else ''))
        result[name] = [float(low), float(high)]
    return result


def sampler_bound_overrides(value=None):
    bounds = validate_sampling_bounds(value)
    scales = {'omega': 0.1, 'epsilon': 0.001, 'lambda': 1000.0, 'eta': 1.0}
    return {f'{name}_{side}': pair[i] / scales[name]
            for name, pair in bounds.items() for i, side in enumerate(('min', 'max'))}
