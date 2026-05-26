"""Hermes plugin packages.

Sub-packages (voice_stack, home_assistant, etc.) are discovered from all
plugin installation locations to support both pip-installed and
user-installed (``~/.hermes/plugins/``) workflows.

Without explicit ``__path__`` resolution, Python only looks in the parent
directory of the first ``plugins`` package it finds on ``sys.path``.  When
``hermes-agent``'s own ``plugins/`` package shadows this one, sub-packages
become unreachable.  Including ``~/.hermes/plugins/`` in ``__path__``
ensures user-installed plugins are always importable.
"""
from __future__ import annotations

from pathlib import Path

_this_dir = Path(__file__).parent.resolve()
_user_plugins = Path.home() / ".hermes" / "plugins"

# Start with the current directory -- this always contains our sub-packages.
__path__ = [str(_this_dir)]

# If the user plugins directory exists and is different, include it so
# cross-package imports (e.g. voice_stack importing from home_assistant)
# work when plugins are installed there.
if _user_plugins.resolve() != _this_dir and _user_plugins.is_dir():
    __path__.append(str(_user_plugins.resolve()))