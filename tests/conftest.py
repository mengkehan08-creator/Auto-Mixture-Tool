"""Explicit isolation for orchestration tests that already use FakeClient.

Real resource validation is exercised separately by test_resource_validation.
Cloud scheduling unit tests must not depend on the developer's OBS mount.
"""
import pytest
from unittest.mock import patch


@pytest.fixture
def mock_resource_preflight():
    with patch('auto_mixture_tool.modelarts.input_validation.validate_workflow_resources', return_value=None) as check:
        yield check
