import hashlib
import json
import zipfile

from notebook_support import SOUTH, OfflineCase, cells, run_cell


class LegacySourceArchives(OfflineCase):
    def test_cached_zip_previews_preserve_captions_and_report_missing_media(self):
        for name in ("GitHub_to_Kaggle_One_Click", "Kaggle_Missing_Media_Fixed"):
            with self.subTest(notebook=name):
                path = SOUTH / f"Telegram_South_Movie_{name}.ipynb"
                directory = self.work / name
                directory.mkdir()
                archive = directory / "source.zip"
                url = "https://example.org/watch/480"
                caption = "Fixture (2022)\n" + "😀" * 600 + "\nGenre: Drama\n480p: " + url
                rows = [
                    {"id": 1, "type": "message", "photo": "photos/1.jpg",
                     "text": caption + "\nJoin our channel https://t.me/fixture"},
                    {"id": 2, "type": "message", "text": "Join our channel https://t.me/fixture"},
                ]
                missing_media = name == "Kaggle_Missing_Media_Fixed"
                if missing_media:
                    rows.append({"id": 3, "type": "message", "photo": "photos/missing.jpg", "text": url})
                raw = json.dumps({"type": "public_channel", "id": 123, "messages": rows}).encode()
                with zipfile.ZipFile(archive, "w") as output:
                    output.writestr("snapshot/result.json", raw)
                    output.writestr("snapshot/photos/1.jpg", b"fixture")
                digest = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
                settings = {"RUN_MODE": "PREVIEW", "WORK": directory, "TEMP": directory,
                            "ARCHIVE": archive, "EXPECTED_JSON_GIT_SHA": digest}
                ns = {"__name__": "__main__"}
                code = [c for c in cells(path) if c["cell_type"] == "code"]
                try:
                    for cell in code:
                        run_cell(cell, ns, path, settings)
                    posts = ns["POSTS"]
                    self.assertEqual([p["source_id"] for p in posts], [1, 3] if missing_media else [1])
                    self.assertEqual(posts[0]["caption"], caption)
                    units = [u for u in ns["UNITS"] if u["source_id"] == 1]
                    self.assertEqual([u["kind"] for u in units], ["photo", "text"])
                    self.assertEqual("".join(u["text"] for u in units), caption)
                    self.assertLessEqual(len(units[0]["text"].encode("utf-16-le")) // 2, 1024)
                    self.assertFalse(ns["CHECKPOINT"].exists())
                    if missing_media:
                        self.assertIsNone(posts[-1]["media"])
                        self.assertEqual(posts[-1]["caption"], url)
                        self.assertEqual(len(json.loads((directory / "south_movie_missing_media_audit.json").read_bytes())), 1)
                    else:
                        rows[0]["photo"] = "photos/missing.jpg"
                        ns["SOURCE_DATA"]["messages"] = rows
                        with self.assertRaisesRegex(RuntimeError, "Missing media"):
                            run_cell(code[1], ns, path)
                finally:
                    if "SOURCE_ZIP" in ns:
                        ns["SOURCE_ZIP"].close()
