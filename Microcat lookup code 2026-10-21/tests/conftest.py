# -*- coding: utf-8 -*-
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fakes                                            # noqa: E402


@pytest.fixture
def env(monkeypatch, tmp_path):
    """The real microcat_runner on stand-ins - see fakes.py. Offline only."""
    return fakes.Env(monkeypatch, tmp_path)


@pytest.fixture
def mr(env):
    return env.mr
