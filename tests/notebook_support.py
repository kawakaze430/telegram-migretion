"""Helpers for running notebook code offline in a disposable working directory."""
import ast
import contextlib
import io
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOUTH = ROOT / "notebooks" / "south-movie"
MOVIE1 = ROOT / "notebooks" / "movie1"


def cells(path):
    return json.loads(path.read_bytes())["cells"]


def run_cell(cell, namespace, filename, overrides=None):
    """Redirect top-level settings and paths while executing the original cell logic."""
    tree = ast.parse("".join(cell["source"]), filename=str(filename))
    if overrides:
        namespace["_test_settings"] = overrides
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name) and target.id in overrides:
                    node.value = ast.Subscript(
                        value=ast.Name(id="_test_settings", ctx=ast.Load()),
                        slice=ast.Constant(target.id), ctx=ast.Load(),
                    )
        ast.fix_missing_locations(tree)
    exec(compile(tree, str(filename), "exec"), namespace)


class OfflineCase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.work = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(contextlib.chdir(self.work))
        self.output = self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "GITHUB_TOKEN": "", "GH_TOKEN": ""}))
        self.network_attempts = []
        def refuse(*args, **kwargs):
            self.network_attempts.append(True)
            raise AssertionError("Notebook tests must not access the network")
        self.enterContext(patch.object(socket.socket, "connect", refuse))
        self.enterContext(patch.object(socket.socket, "connect_ex", refuse))
        self.enterContext(patch.object(socket, "getaddrinfo", refuse))
        self.addCleanup(self.assertEqual, self.network_attempts, [], "A notebook attempted network access")
