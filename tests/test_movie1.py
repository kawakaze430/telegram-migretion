import contextlib
import hashlib
import json
import runpy
import sys
import unittest

from notebook_support import MOVIE1, ROOT, OfflineCase, cells, run_cell


class Movie1Previews(OfflineCase):
    def test_full_colab_and_kaggle_plans(self):
        root_notebook = ROOT / "Telegram_Channel_Migration.ipynb"
        colab_notebook = MOVIE1 / "Telegram_Movie1_All_Links_No_Channels.ipynb"
        paths = [
            root_notebook, colab_notebook,
            MOVIE1 / "Telegram_Movie1_Kaggle_Background.ipynb",
            MOVIE1 / "Telegram_Movie1_Kaggle_One_Click_Auto.ipynb",
            MOVIE1 / "Telegram_Movie1_Kaggle_Compact_Auto_Fixed.ipynb",
        ]
        for path in paths:
            with self.subTest(notebook=path.name):
                directory = self.work / path.stem
                directory.mkdir()
                ns = {"__name__": "__main__"}
                settings = {"RUN_MODE": "PREVIEW", "WORKDIR": directory / "plan"}
                code = [c for c in cells(path) if c["cell_type"] == "code"]
                # On Colab, setup and preview precede a separate interactive bot login.
                if path in (root_notebook, colab_notebook):
                    code = code[:2]
                with contextlib.chdir(directory):
                    for cell in code:
                        run_cell(cell, ns, path, settings)
                self.assertEqual(len(ns["MESSAGES"]), 3780)
                self.assertEqual(sum(bool(m.get("photo")) for m in ns["MESSAGES"]), 3751)
                self.assertFalse(list(directory.rglob("progress_*.json")))

    def test_original_uploader_and_extra_batch(self):
        original = MOVIE1 / "Telegram_Movie1_Uploader.ipynb"
        extra = MOVIE1 / "Telegram_Movie1_Extra_1219.ipynb"
        ns = {"__name__": "__main__"}
        for cell in [c for c in cells(original) if c["cell_type"] == "code"][:3]:
            run_cell(cell, ns, original)
        self.assertEqual(len(ns["MESSAGES"]), 2573)
        directory = ns["WORKDIR"]
        embedded = runpy.run_path(str(directory / "test_uploader.py"))
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(embedded["UploadTests"])
        result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(suite)
        self.assertGreaterEqual(result.testsRun, 10)
        self.assertTrue(result.wasSuccessful())
        prepare = next(c for c in cells(extra) if c["cell_type"] == "code")
        with self.assertRaisesRegex(ValueError, "First-batch progress not found"):
            run_cell(prepare, ns, extra)

        target = ns["extra_pass"].TARGET_ID
        checkpoint = directory / f"progress_{target}.json"
        state = ns["uploader"].load_state(checkpoint, ns["MESSAGES"], 42, target)
        state["sent"] = {str(m["id"]): {"message_id": 10000 + i} for i, m in enumerate(ns["MESSAGES"])}
        checkpoint.write_text(json.dumps(state), encoding="utf-8")
        run_cell(prepare, ns, extra)
        base_ids = {m["id"] for m in ns["BASE_MESSAGES"]}
        extra_ids = {m["id"] for m in ns["EXTRA_MESSAGES"]}
        self.assertEqual(len(extra_ids), 1219)
        self.assertTrue(base_ids.isdisjoint(extra_ids))
        self.assertFalse(ns["EXTRA_STATE_PATH"].exists())

    def test_incremental_exports_validate_photos_and_keep_all_61_links(self):
        # Use generated media and hashes so CI can run even when the Kaggle dataset is private.
        source = self.work / "source"
        source.mkdir()
        messages, hashes = [], {}
        for sid in range(3835, 3856):
            name = f"{sid}.jpg"
            raw = f"fixture photo {sid}".encode()
            (source / name).write_bytes(raw)
            hashes[str(sid)] = hashlib.sha256(raw).hexdigest()
            links = [f"https://example.org/{sid}/{size}" for size in (480, 720, 1080)]
            if sid < 3837:
                links.pop()
            caption = "\n".join([f"Fixture {sid}", "Genre: Drama", *links,
                                 "All private channels: https://t.me/fixture"])
            messages.append({"id": sid, "photo": name, "text": [{"type": "plain", "text": caption}]})
        data = json.dumps({"id": 1881963160, "messages": messages}).encode()
        (source / "result.json").write_bytes(data)
        paths = sorted(MOVIE1.glob("Telegram_Movie1_Nov22_*.ipynb"))
        self.assertEqual(len(paths), 2)
        for path in paths:
            with self.subTest(notebook=path.name):
                directory = self.work / path.stem
                ns = {"__name__": "__main__"}
                settings = {
                    "WORK": directory, "RESULT_SHA256": hashlib.sha256(data).hexdigest(),
                    "EXPECTED_PHOTOS": hashes, "RUN_MODE": "PREVIEW",
                    "SYNC_REPO_IF_GITHUB_SECRET_AVAILABLE": False,
                }
                if "AutoDetect" in path.name:
                    settings["SOURCE_SEARCH_ROOTS"] = (source,)
                else:
                    settings["SOURCE"] = source
                code = [c for c in cells(path) if c["cell_type"] == "code"]
                for cell in code:
                    run_cell(cell, ns, path, settings)
                self.assertEqual([p["source_id"] for p in ns["POSTS"]], list(range(3835, 3856)))
                self.assertEqual(sum(len(p["non_channel_links"]) for p in ns["POSTS"]), 61)
                self.assertFalse(any("t.me/" in p["caption"] for p in ns["POSTS"]))
                self.assertFalse(ns["CHECKPOINT"].exists())
                first = source / "3835.jpg"
                saved = first.read_bytes()
                try:
                    first.write_bytes(b"corrupt")
                    with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                        run_cell(code[1], ns, path)
                finally:
                    first.write_bytes(saved)
