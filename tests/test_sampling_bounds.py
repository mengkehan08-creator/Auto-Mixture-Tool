import argparse
import ast
from pathlib import Path

import pytest
from quadmix.core.sampling_bounds import validate_sampling_bounds, sampler_bound_overrides

ROOT = Path(__file__).resolve().parents[1]


def test_default_bounds_preserve_original_internal_ranges():
    assert set(sampler_bound_overrides().values()) == {0.0, 1.0}
    assert validate_sampling_bounds()['omega'] == [0, .1]


@pytest.mark.parametrize('bounds', [{'omega': [.2, .1]}, {'omega': [0, 2]}, {'eta': [-1, 1]},
                                  {'epsilon': [0, float('nan')]}, {'lambda': [True, 4]},
                                  {'unknown': [0, 1]}, {'eta': [0]}, []])
def test_bad_ranges_fail_closed(bounds):
    with pytest.raises(ValueError):
        validate_sampling_bounds(bounds)


def test_adapter_cli_and_core_preserve_effective_values():
    from auto_mixture_tool.plugins.algorithms.quadmix import QuadMixAlgorithm
    bounds = {'omega': [.03, .4], 'epsilon': [.002, .01], 'lambda': [20, 800], 'eta': [.3, .8]}
    stage = QuadMixAlgorithm().build({'schema_uri': 'schema', 'dataset_uri': 'data', 'output_uri': 'out',
                                     'algorithm_config': {'sampling_bounds': bounds}}, ROOT)[0]
    # Execute only the CLI declaration, never import the GPU/cloud entry point.
    tree = ast.parse((ROOT / 'scripts/runners/run_essential_web_v1.py').read_text(encoding='utf-8'))
    declaration = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'build_parser')
    scope = {'argparse': argparse, 'DEFAULT_PREPROCESSED_DIR': 'data', 'DEFAULT_EVAL_BUNDLE': 'eval'}
    exec(compile(ast.Module(body=[declaration], type_ignores=[]), '<parser-test>', 'exec'), scope)
    args = scope['build_parser']().parse_args(stage.args[1:])
    parsed = {name: [getattr(args, f'{name}_min'), getattr(args, f'{name}_max')] for name in bounds}
    assert parsed == bounds
    raw = sampler_bound_overrides(parsed)
    assert raw['omega_max'] * .1 == pytest.approx(.4)
    assert raw['epsilon_min'] * .001 == pytest.approx(.002)


def test_workflow_normalization_preserves_upper_bound(tmp_path):
    from auto_mixture_tool.modelarts.workflow import ModelArtsWorkflowManager
    from test_modelarts_workflow import config
    settings = config()
    settings['strategies'][0]['sampling_bounds'] = {'omega': [0, .3]}
    result = ModelArtsWorkflowManager(tmp_path)._validate(settings)
    assert result['strategies'][0]['sampling_bounds']['omega'] == [0, .3]
