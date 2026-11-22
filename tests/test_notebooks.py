import ast
import base64
import hashlib
import io
import json
import re
import tarfile
import unittest
import zipfile
import zlib
from pathlib import PurePosixPath

import nbformat

from notebook_support import ROOT

EMBEDDED = {
    "PACKED_PLAN": ("PLAN_SHA", "json"),
    "EMBEDDED_EXPORT_ZLIB_B64": ("EMBEDDED_EXPORT_SHA256", "json"),
    "BUNDLE_B64": ("EXPECTED_BUNDLE_SHA256", "zip"),
    "EXTRA_PACKAGE_B64": ("EXPECTED_PACKAGE_SHA256", "zip"),
    "ARCHIVE_B64": ("EXPECTED_ARCHIVE_SHA256", "tar"),
}
CREDENTIAL = re.compile(
    rb"\b\d{6,16}:[A-Za-z0-9_-]{30,}|\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{16,}"
    rb"|-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"
)


class NotebookFiles(unittest.TestCase):
    def test_schema_code_and_embedded_data(self):
        paths = sorted(ROOT.rglob("*.ipynb"))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(notebook=str(path.relative_to(ROOT))):
                raw = path.read_bytes()
                self.assertFalse(CREDENTIAL.search(raw), "Credential found in notebook")
                notebook = json.loads(raw)
                nbformat.validate(notebook)
                if (notebook["nbformat"], notebook["nbformat_minor"]) >= (4, 5):
                    ids = [c["id"] for c in notebook["cells"]]
                    self.assertEqual(len(ids), len(set(ids)))
                constants = {}
                for index, cell in enumerate(notebook["cells"]):
                    if cell["cell_type"] != "code":
                        continue
                    label = f"{path.name} cell {index}"
                    source = "".join(cell["source"])
                    compile(source, label, "exec")
                    for node in ast.parse(source).body:
                        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                            for target in node.targets:
                                if isinstance(target, ast.Name):
                                    constants[target.id] = node.value.value
                for name, (checksum, kind) in EMBEDDED.items():
                    if name not in constants:
                        continue
                    with self.subTest(payload=name):
                        data = base64.b64decode(constants[name], validate=True)
                        if kind == "json":
                            data = zlib.decompress(data)
                        self.assertEqual(hashlib.sha256(data).hexdigest(), constants[checksum])
                        if kind == "json":
                            self.check_member(name + ".json", data)
                        elif kind == "zip":
                            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                                self.assertIsNone(archive.testzip())
                                for info in archive.infolist():
                                    if not info.is_dir():
                                        self.check_member(info.filename, archive.read(info))
                        else:
                            with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as archive:
                                for info in archive:
                                    self.assertTrue(info.isfile())
                                    self.check_member(info.name, archive.extractfile(info).read())

    def check_member(self, name, data):
        path = PurePosixPath(name)
        self.assertFalse(path.is_absolute() or ".." in path.parts, name)
        self.assertFalse(CREDENTIAL.search(data), f"Credential found in {name}")
        if name.endswith(".py"):
            compile(data, name, "exec")
        elif name.endswith(".json"):
            json.loads(data)
