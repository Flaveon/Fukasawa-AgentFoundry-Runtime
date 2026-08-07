# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
import sys

import pytest
from unittest.mock import patch

from src.app_entry import main

def test_main_cli_dispatch():
    """Test that main() delegates to CLI when given arguments."""
    with patch.object(sys, 'argv', ['app_entry.py', 'some_arg']):
        with patch('src.cli.app') as mock_app:
            main()
            mock_app.assert_called_once()

def test_main_gui_dispatch():
    """Test that main() delegates to GUI when given no arguments.

    Skips when the GUI stack is unavailable, matching tests/test_gui.py. The
    dispatch under test imports src.gui.app, and patch() can only resolve that
    target once the submodule imports — so without tkinter or customtkinter
    this fails on the patch target rather than on the behavior it checks. CI
    installs the gui extra and runs under xvfb, so the assertion still runs
    there.
    """
    pytest.importorskip("customtkinter")
    pytest.importorskip("tkinter")
    with patch.object(sys, 'argv', ['app_entry.py']):
        with patch('src.gui.app.main') as mock_gui_main:
            main()
            mock_gui_main.assert_called_once()
