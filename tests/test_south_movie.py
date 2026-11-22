import hashlib
import json
import zipfile
from unittest.mock import Mock, patch

import requests

from notebook_support import OfflineCase, SOUTH, cells, run_cell
from run_south_movie_preview import ATTEMPT_2897, recorded_inputs

CURRENT = SOUTH / "Telegram_South_Movie_Export_Recovered_Ready.ipynb"
ATTEMPT = "d5c39ccae9404bc69dc6fa79cd21b846"


def preview(path, directory):
    namespace = {"__name__": "__main__"}
    settings = {
        "RUN_MODE": "PREVIEW", "INPUT": directory / "input",
        "WORK": directory, "CACHE": directory / "cache",
    }
    for cell in cells(path):
        if cell["cell_type"] == "code":
            run_cell(cell, namespace, path, settings)
    return namespace


def destination_export(nb, include_pending=False):
    """Build a synthetic full destination export with nonconsecutive Telegram IDs."""
    posts = nb["POSTS"]
    historical = dict(zip((sid for sid, _ in nb["PREFIX"][:-1]), nb["HISTORICAL_DESTINATION_IDS"], strict=True))

    def photo(sid, message_id):
        return {
            "type": "message", "id": message_id, "photo": "photos/fixture.jpg",
            "text": posts[sid]["caption"] if sid in posts else "",
        }

    rows = [photo(sid, mid) for sid, mid in historical.items() if nb["LEGACY"][sid] == "photo"]
    end = 1228 if include_pending else 1227
    for index, sid in enumerate(list(posts)[:end]):
        if sid not in historical:
            rows.append(photo(sid, 10000 + 3 * index))
    return {"type": "public_channel", "id": 4376620825, "messages": rows}


class SouthMovieRecovery(OfflineCase):
    def setUp(self):
        super().setUp()
        self.nb = preview(CURRENT, self.work)

    def from_export(self, include_pending=False):
        file = self.work / "result.json"
        data = destination_export(self.nb, include_pending)
        file.write_text(json.dumps(data), encoding="utf-8")
        self.nb["DESTINATION_EXPORT"] = str(file)
        return self.nb["load_progress"](), data

    def test_plan_and_report_at_logged_pause(self):
        n = self.nb
        self.assertEqual(n["RUN_RESULT"]["status"], "PAUSED")  # No checkpoint attached yet.
        self.assertEqual((n["BASELINE_COUNT"], n["INTERRUPTED_SOURCE"], n["INTERRUPTED_ATTEMPT"]), (1227, "1568", ATTEMPT))
        self.assertEqual((n["PENDING_KEY"], n["PENDING_MESSAGE_ID"]), ("d203966ee25045fa9e9ff1acc44a6954", None))
        posts = n["POSTS"]
        self.assertEqual(list(posts)[1226:1229], ["1567", "1568", "1569"])
        self.assertEqual(posts["1567"]["caption"].splitlines()[0], "Ombatthane Dikku (2022)")
        self.assertEqual(posts["1567"]["link_count"], 2)
        self.assertEqual(posts["1568"]["caption"].splitlines()[0], "Annapoorani - The Goddess of Food (2023)")
        self.assertRegex(posts["1568"]["caption"], r"1080p\s*:\s*https?://\S*/13BVytyTZYtIL68b2DSUmFw\b")
        self.from_export()
        summary = n["execute"]()
        self.assertEqual(summary["status"], "PREVIEW")
        self.assertEqual(summary["confirmed_movie_photos"], 1227)
        self.assertEqual(summary["remaining_movie_photos"], 1500)
        self.assertEqual(summary["old_text_messages_removed"], 12)
        self.assertEqual(summary["old_nonmovie_photo_captions_cleared"], 2)
        self.assertEqual(summary["pending"], {"sid": "1568", "kind": "photo", "attempt": ATTEMPT})
        self.assertEqual(json.loads((self.work / "south_movie_run_summary.json").read_bytes()), summary)

    def test_present_photo_uses_its_destination_id_and_skips_resend(self):
        n = self.nb
        state, export = self.from_export(include_pending=True)
        mid = export["messages"][-1]["id"]
        self.assertIsNone(state["pending"])
        self.assertEqual(state["receipts"]["1568"]["message_id"], mid)
        self.assertEqual(state["resolutions"][ATTEMPT], {"sid": "1568", "message_id": mid})
        api = Mock()
        api.call.side_effect = n["UnknownSend"]("simulated interruption")
        with self.assertRaisesRegex(n["Pause"], "1569:0"):
            n["send_remaining"](state, api, Mock())
        self.assertEqual(api.call.call_count, 1)
        self.assertEqual(api.call.call_args.args[1]["caption"], n["POSTS"]["1569"]["caption"])

    def test_disconnect_saves_one_attempt_and_old_decision_cannot_retry_it(self):
        n = self.nb
        state, _ = self.from_export()
        state["bot_id"] = 42  # A live run binds the verified bot before persisting.
        # Explicitly resolve the earlier synthetic Annapoorani attempt; the live default is now source 2897.
        n.update(PENDING_KEY=ATTEMPT, PENDING_MESSAGE_ID=0)
        n["resolve_pending"](state)
        session = Mock()
        def disconnect(*args, **kwargs):
            pending = json.loads((self.work / n["CHECKPOINT_NAME"]).read_bytes())["pending"]
            self.assertEqual(pending["sid"], "1568")  # Intent was durable before the API call.
            raise requests.ConnectionError("simulated lost connection")
        session.post.side_effect = disconnect
        client = n["Telegram"]("fixture", session, wait=lambda seconds: None)
        media = Mock()
        media.read.return_value = b"fixture-photo"
        with self.assertRaisesRegex(n["Pause"], "1568:0 is saved as pending"):
            n["send_remaining"](state, client, media)
        self.assertEqual(session.post.call_count, 1)
        n["DESTINATION_EXPORT"] = ""
        restored = n["load_progress"]()
        self.assertNotIn("1568", restored["receipts"])
        key = restored["pending"]["attempt"]
        self.assertNotEqual(key, ATTEMPT)
        with self.assertRaises(n["Pause"]):
            n["resolve_pending"](restored)
        n.update(PENDING_KEY=key, PENDING_MESSAGE_ID="https://t.me/southdhamal/90001")
        n["resolve_pending"](restored)
        self.assertEqual(n["load_progress"]()["receipts"]["1568"]["message_id"], 90001)

    def test_wrong_incomplete_or_altered_export_is_rejected(self):
        n = self.nb
        for change in ("wrong target", "old export", "changed caption", "duplicate destination ID"):
            data = destination_export(n)
            if change == "wrong target":
                data["id"] = 123
            elif change == "old export":
                data["messages"] = data["messages"][:248]
            elif change == "changed caption":
                data["messages"][-1]["text"] = "different movie"
            else:
                data["messages"][-1]["id"] = data["messages"][-2]["id"]
            with self.subTest(change=change), self.assertRaises(n["Pause"]):
                n["state_from_export"](data, 42)

    def test_final_photo_completes_once_through_notebook_entry_point(self):
        n = self.nb
        state, _ = self.from_export(include_pending=True)
        state["bot_id"] = 42
        last = list(n["POSTS"])[-1]
        for index, sid in enumerate(n["POSTS"]):
            if sid != last and sid not in state["receipts"]:
                n["add_receipt"](state, sid, 20000 + index, "photo")
                state["done"][sid] = "caption"
        n["persist"](state)
        media, session = Mock(), Mock()
        media.read.return_value = b"fixture-photo"
        sent = []

        def reply(url, **kwargs):
            method = url.rsplit("/", 1)[-1]
            results = {
                "getMe": {"id": 42, "username": "fixture"},
                "getChat": {"id": n["CHAT_ID"], "type": "channel", "username": "southdhamal", "title": "South Movie"},
                "getChatMember": {"status": "administrator", "can_post_messages": True},
                "sendPhoto": {"message_id": 90001, "chat": {"id": n["CHAT_ID"]}, "photo": [{"file_id": "fixture"}]},
            }
            if method == "sendPhoto":
                sent.append(kwargs["data"]["caption"])
            return Mock(status_code=200, json=Mock(return_value={"ok": True, "result": results[method]}))

        session.post.side_effect = reply
        settings = {"RUN_MODE": "REPAIR_AND_CONTINUE", "DESTINATION_EXPORT": "",
                    "bot_token": lambda: "fixture", "open_source": Mock(return_value=media)}
        with patch.dict(n, settings), patch("requests.Session") as new_session:
            new_session.return_value.__enter__.return_value = session
            for _ in range(2):  # Restart from the completed checkpoint.
                summary = n["execute"]()
                self.assertEqual(summary["status"], "COMPLETE", summary.get("reason"))
                self.assertEqual(summary["confirmed_movie_photos"], 2727)
                self.assertEqual(summary["remaining_movie_photos"], 0)
                self.assertIsNone(summary["pending"])
            n["open_source"].assert_called_once()
        media.close.assert_called_once()
        self.assertEqual(sent, [n["POSTS"][last]["caption"]])

    def test_long_explicit_429_waits_then_retries_same_photo(self):
        """The real Kaggle pause requested 474 seconds; an explicit 429 is safe to retry."""
        n = self.nb
        reply = lambda status, body: Mock(status_code=status, json=Mock(return_value=body))
        session, wait = Mock(), Mock()
        session.post.side_effect = [
            reply(429, {"ok": False, "error_code": 429,
                        "parameters": {"retry_after": 474}}),
            reply(200, {"ok": True, "result": {"message_id": 88}}),
        ]
        client = n["Telegram"]("fixture", session, wait=wait)
        self.assertEqual(client.call("sendPhoto", photo=("fixture.jpg", b"photo-data")), {"message_id": 88})
        wait.assert_any_call(475)
        self.assertEqual(session.post.call_count, 2)
        self.assertIn("sendPhoto", session.post.call_args_list[0].args[0])
        self.assertIn("sendPhoto", session.post.call_args_list[1].args[0])

    def test_overlong_429_clears_pending_and_keeps_resume_safe(self):
        """A cooldown exceeding our 15-minute ceiling must save definitive rejection, not uncertainty."""
        n = self.nb
        state, _ = self.from_export(include_pending=True)
        state["bot_id"] = 42
        session, wait = Mock(), Mock()
        session.post.return_value = Mock(status_code=429, json=Mock(
            return_value={"ok": False, "error_code": 429, "parameters": {"retry_after": 901}}))
        client = n["Telegram"]("fixture", session, wait=wait)
        media = Mock()
        media.read.return_value = b"photo-data"
        with self.assertRaisesRegex(n["Pause"], "Resume after 902 seconds"):
            n["send_remaining"](state, client, media)
        wait.assert_not_called()
        self.assertIsNone(state["pending"])
        self.assertEqual(len(session.post.call_args_list), 1)
        self.assertEqual(state["resolutions"][next(reversed(state["resolutions"]))]["message_id"], 0)
        n["DESTINATION_EXPORT"] = ""
        restored = n["load_progress"]()
        self.assertIsNone(restored["pending"])
        self.assertNotIn("1569", restored["receipts"])

    def later_pending_checkpoint(self):
        """Build an exact, synthetic 2,441-photo channel snapshot and pending source 2897."""
        n = self.nb
        state, _ = self.from_export(include_pending=True)
        state["bot_id"] = 42
        for index, sid in enumerate(list(n["POSTS"])[:2441]):
            if sid not in state["receipts"]:
                n["add_receipt"](state, sid, 100000 + index, "photo")
            state["done"][sid] = "caption"
        self.assertEqual(next(k for k in n["POSTS"] if k not in state["receipts"]), "2897")
        attempt = "d203966ee25045fa9e9ff1acc44a6954"
        state["pending"] = {"sid": "2897", "kind": "photo", "attempt": attempt}
        n["persist"](state)
        rows = []
        for sid, row in state["receipts"].items():
            if row["kind"] == "photo":
                rows.append({"type": "message", "id": row["message_id"], "photo": "photos/fixture.jpg",
                             "text": n["POSTS"][sid]["caption"] if sid in n["POSTS"] else ""})
        rows.sort(key=lambda message: message["id"])
        export = {"type": "public_channel", "id": 4376620825, "messages": rows}
        return state, export

    def test_pending_2897_full_export_confirms_absence_and_resumes_once(self):
        n = self.nb
        prior, data = self.later_pending_checkpoint()
        target = self.work / "result.json"
        target.write_text(json.dumps(data), encoding="utf-8")
        n["DESTINATION_EXPORT"] = str(target)
        recovered = n["load_progress"]()
        self.assertEqual(n["stats"](recovered)["confirmed_movie_photos"], 2441)
        self.assertEqual(n["stats"](recovered)["remaining_movie_photos"], 286)
        self.assertIsNone(recovered["pending"])
        self.assertEqual(recovered["resolutions"][prior["pending"]["attempt"]], {
            "sid": "2897", "message_id": 0, "export_through_id": data["messages"][-1]["id"],
        })
        self.assertEqual(next(sid for sid in n["POSTS"] if sid not in recovered["receipts"]), "2897")
        self.assertEqual(n["RUN_MODE"], "PREVIEW")
        self.assertIsNotNone(n["load_progress"]())
        # Preview resolves in memory only; the checkpoint on disk is not mutated.
        self.assertEqual(json.loads((self.work / n["CHECKPOINT_NAME"]).read_text())["pending"]["sid"], "2897")

    def test_pending_2897_full_export_confirms_delivery_and_skips_duplicate(self):
        n = self.nb
        state, data = self.later_pending_checkpoint()
        posted_id = data["messages"][-1]["id"] + 1
        data["messages"].append({"type": "message", "id": posted_id, "photo": "photos/pending.jpg",
                                  "text": n["POSTS"]["2897"]["caption"]})
        target = self.work / "result.json"
        target.write_text(json.dumps(data), encoding="utf-8")
        n["DESTINATION_EXPORT"] = str(target)
        recovered = n["load_progress"]()
        self.assertEqual(recovered["receipts"]["2897"]["message_id"], posted_id)
        self.assertEqual(recovered["done"]["2897"], "caption")
        self.assertIsNone(recovered["pending"])
        self.assertEqual(next(sid for sid in n["POSTS"] if sid not in recovered["receipts"]), "2898")

    def test_pending_2897_stale_or_mismatched_export_is_rejected(self):
        n = self.nb
        state, snapshot = self.later_pending_checkpoint()
        for scenario in ("incomplete", "wrong caption", "wrong destination", "unexpected post"):
            data = json.loads(json.dumps(snapshot))
            if scenario == "incomplete":
                data["messages"].pop()
            elif scenario == "wrong caption":
                data["messages"][-1]["text"] = "Changed caption"
            elif scenario == "wrong destination":
                data["id"] = 12345
            else:
                data["messages"].append({"type": "message", "id": data["messages"][-1]["id"] + 2,
                                         "photo": "photos/unexpected.jpg", "text": "Not the movie"})
            with self.subTest(scenario=scenario), self.assertRaises(n["Pause"]):
                n["reconcile_pending_export"](state, data)

    def test_pending_2897_stale_export_reports_actual_channel_ids(self):
        n = self.nb
        _, data = self.later_pending_checkpoint()
        data["messages"] = [m for m in data["messages"] if m["id"] <= 250]
        data["messages"].append({"type": "message", "id": 1243,
                                 "photo": "photos/old.jpg", "text": "Old export ending at 1243"})
        stale = self.work / "result.json"
        stale.write_text(json.dumps(data), encoding="utf-8")
        n["DESTINATION_EXPORT"] = str(stale)
        with self.assertRaisesRegex(n["Pause"],
                                    "STALE OR MISMATCHED DESTINATION EXPORT: it ends at Telegram ID 1243"):
            n["load_progress"]()

    def test_operator_can_ignore_stale_autodiscovered_export_after_verification(self):
        n = self.nb
        state, data = self.later_pending_checkpoint()
        data["messages"] = [m for m in data["messages"] if m["id"] <= 250]
        data["messages"].append({"type": "message", "id": 1243,
                                 "photo": "photos/old.jpg", "text": "Old export ending at 1243"})
        input_folder = self.work / "input"
        input_folder.mkdir(parents=True, exist_ok=True)
        (input_folder / "result.json").write_text(json.dumps(data), encoding="utf-8")
        n["INPUT"] = input_folder
        n["DESTINATION_EXPORT"] = ""
        n["PENDING_KEY"] = state["pending"]["attempt"]
        n["PENDING_MESSAGE_ID"] = 0  # operator only sets this after verifying absence
        restored = n["load_progress"]()
        self.assertEqual(restored["pending"]["sid"], "2897")
        n["resolve_pending"](restored)
        self.assertIsNone(restored["pending"])
        self.assertNotIn("2897", restored["receipts"])
        self.assertEqual(restored["resolutions"][state["pending"]["attempt"]],
                         {"sid": "2897", "message_id": 0})
        self.assertEqual(n["stats"](restored)["remaining_movie_photos"], 286)

    def test_post_2457_gap_keeps_love_birds_receipt_and_retries_only_pending_movie(self):
        n = self.nb
        state, export = recorded_inputs()
        folder = self.work / "input"
        folder.mkdir()
        checkpoint = folder / n["CHECKPOINT_NAME"]
        checkpoint.write_text(json.dumps(state), encoding="utf-8")
        (folder / "result.json").write_text(json.dumps(export), encoding="utf-8")
        summary = n["execute"]()
        self.assertEqual(summary["status"], "PREVIEW", summary.get("reason"))
        self.assertEqual(summary["historical_photos_missing_from_export"], {"2711": 2282})
        self.assertEqual(summary["manual_review_items"], 1)
        self.assertEqual(summary["next_outstanding_source"], "2897")
        self.assertIsNone(summary["pending"])
        self.assertEqual(json.loads(checkpoint.read_bytes()), state)
        self.assertFalse((self.work / n["CHECKPOINT_NAME"]).exists())

        resolved = n["load_progress"]()
        self.assertEqual(resolved["resolutions"][ATTEMPT_2897]["export_through_id"], 2457)
        self.assertEqual(resolved["receipts"], state["receipts"])
        self.assertEqual(resolved["done"], state["done"])
        api = Mock()
        api.call.side_effect = n["UnknownSend"]("interrupted")
        with self.assertRaisesRegex(n["Pause"], "2897:0"):
            n["send_remaining"](resolved, api, Mock())
        api.call.assert_called_once()
        self.assertEqual(api.call.call_args.args[1]["caption"], n["POSTS"]["2897"]["caption"])
        saved = json.loads((self.work / n["CHECKPOINT_NAME"]).read_bytes())
        self.assertEqual(saved["export_missing_photos"], {"2711": 2282})
        self.assertNotEqual(saved["pending"]["attempt"], ATTEMPT_2897)
        with self.assertRaisesRegex(n["Pause"], "earlier attempt"):
            n["load_progress"]()
        self.assertEqual(json.loads((self.work / n["CHECKPOINT_NAME"]).read_bytes()), saved)

    def test_post_2457_gap_allows_a_verified_pending_photo_and_a_later_recheck(self):
        n = self.nb
        state, export = recorded_inputs()
        export["messages"].append({"type": "message", "id": 2460, "photo": "fixture.jpg",
                                   "text": [{"type": "plain", "text": n["POSTS"]["2897"]["caption"]}]})
        resolved = n["reconcile_pending_export"](state, export)
        self.assertEqual(resolved["receipts"]["2897"]["message_id"], 2460)
        self.assertEqual(resolved["resolutions"][ATTEMPT_2897], {"sid": "2897", "message_id": 2460})
        self.assertEqual(n["stats"](resolved)["next_outstanding_source"], "2898")
        self.assertEqual(resolved["export_missing_photos"], {"2711": 2282})
        n["persist"](resolved)
        export["messages"].append({"type": "message", "id": 2282, "photo": "fixture.jpg",
                                   "text": n["POSTS"]["2711"]["caption"]})
        export["messages"].sort(key=lambda m: m["id"])
        path = self.work / "result.json"
        path.write_text(json.dumps(export), encoding="utf-8")
        n["DESTINATION_EXPORT"] = str(path)
        rechecked = n["load_progress"]()
        self.assertEqual(rechecked["receipts"], resolved["receipts"])
        self.assertEqual(n["stats"](rechecked)["historical_photos_missing_from_export"], {})
        self.assertEqual(n["stats"](rechecked)["manual_review_items"], 0)

    def test_post_2457_known_gap_cannot_hide_a_second_mismatch_or_a_stale_tail(self):
        n = self.nb
        state, snapshot = recorded_inputs()
        for scenario in ("another interior gap", "missing last receipt", "wrong caption", "wrong type at gap",
                         "unexpected interior message", "pending caption differs", "two later messages"):
            export = json.loads(json.dumps(snapshot))
            rows = export["messages"]
            if scenario == "another interior gap":
                rows[:] = [m for m in rows if m["id"] != 2281]
            elif scenario == "missing last receipt":
                rows.pop()
                rows.append({"type": "message", "id": 2460, "photo": "fixture.jpg", "text": n["POSTS"]["2897"]["caption"]})
            elif scenario == "wrong caption":
                rows[-2]["text"] = "Changed"
            elif scenario == "wrong type at gap":
                rows.append({"type": "service", "id": 2282})
            elif scenario == "unexpected interior message":
                rows.append({"type": "message", "id": 55, "text": "unexpected"})
            elif scenario == "pending caption differs":
                rows.append({"type": "message", "id": 2460, "photo": "fixture.jpg", "text": "Different movie"})
            else:
                rows.extend({"type": "message", "id": mid, "photo": "fixture.jpg", "text": n["POSTS"]["2897"]["caption"]}
                            for mid in (2460, 2461))
            rows.sort(key=lambda m: m["id"])
            with self.subTest(scenario=scenario), self.assertRaises(n["Pause"]):
                n["reconcile_pending_export"](state, export)
            self.assertEqual(state["pending"]["attempt"], ATTEMPT_2897)
            self.assertNotIn("2897", state["receipts"])

    def test_pending_2897_requires_operator_decision_without_export(self):
        n = self.nb
        state, _ = self.later_pending_checkpoint()
        n["DESTINATION_EXPORT"] = ""
        recovered = n["load_progress"]()
        self.assertEqual(recovered["pending"]["attempt"], "d203966ee25045fa9e9ff1acc44a6954")
        with self.assertRaisesRegex(n["Pause"], "PENDING_MESSAGE_ID"):
            n["resolve_pending"](recovered)

    def test_new_checkpoint_at_2266_resumes_at_source_2712(self):
        """A later verified checkpoint supersedes the older 1227-photo export boundary."""
        n = self.nb
        state, _ = self.from_export(include_pending=True)
        state["bot_id"] = 42
        for index, sid in enumerate(list(n["POSTS"])[:2266]):
            if sid not in state["receipts"]:
                n["add_receipt"](state, sid, 100000 + index, "photo")
            state["done"][sid] = "caption"
        n["persist"](state)
        n["DESTINATION_EXPORT"] = ""
        restored = n["load_progress"]()
        self.assertEqual(n["stats"](restored)["confirmed_movie_photos"], 2266)
        self.assertEqual(n["stats"](restored)["remaining_movie_photos"], 461)
        self.assertEqual(next(sid for sid in n["POSTS"] if sid not in restored["receipts"]), "2712")
        self.assertIsNone(restored["pending"])

    def test_source_archive_checks_photo_hash_and_movie_links(self):
        n = self.nb
        data = b"fixture-photo"
        url = "https://example.org/watch/1080"
        rel = "photos/fixture.jpg"
        post = {"source_id": 1568, "path": rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "caption": "Fixture 1080p: " + url}
        path = self.work / "source.zip"
        for case in ("valid", "changed photo", "changed link", "wrong snapshot"):
            target = url + "/different" if case == "changed link" else url
            raw = json.dumps({"messages": [{"id": 1568, "type": "message", "photo": rel,
                                           "text_entities": [{"type": "link", "text": target}]}]}).encode()
            blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            with zipfile.ZipFile(path, "w") as output:
                output.writestr("snapshot/result.json", raw)
                output.writestr("snapshot/" + rel, data[::-1] if case == "changed photo" else data)
            with self.subTest(case=case), patch.dict(n, {"POSTS": {"1568": post},
                                                          "JSON_BLOB": "" if case == "wrong snapshot" else blob}):
                if case == "valid":
                    archive = n["PhotoArchive"](path)
                    try:
                        self.assertEqual(archive.read(post), data)
                    finally:
                        archive.close()
                else:
                    with self.assertRaises(n["Pause"]):
                        n["PhotoArchive"](path)

    def test_explicit_flood_wait_retries_but_server_error_is_ambiguous(self):
        n = self.nb
        response = lambda status, body: Mock(status_code=status, json=Mock(return_value=body))
        session, wait = Mock(), Mock()
        session.post.side_effect = [
            response(429, {"ok": False, "error_code": 429, "parameters": {"retry_after": 7}}),
            response(200, {"ok": True, "result": {"message_id": 91}}),
        ]
        client = n["Telegram"]("fixture", session, wait=wait)
        self.assertEqual(client.call("sendPhoto", photo=("fixture.jpg", b"data")), {"message_id": 91})
        wait.assert_any_call(8)
        self.assertEqual(session.post.call_count, 2)
        session.post.reset_mock()
        session.post.side_effect = [response(502, {})]
        with self.assertRaises(n["UnknownSend"]):
            client.call("sendPhoto")
        session.post.assert_called_once()


class HistoricalSouthMoviePreviews(OfflineCase):
    def test_repair_notebooks_in_preview(self):
        for filename in ("Clean_Repair_Resume", "Ready_To_Resume", "Export_Recovered_248"):
            path = SOUTH / f"Telegram_South_Movie_{filename}.ipynb"
            with self.subTest(notebook=filename):
                n = preview(path, self.work / filename)
                self.assertEqual(n["RUN_RESULT"]["status"], "PREVIEW")
                self.assertEqual(n["PLAN_COUNTS"]["movie_photos"], 2727)
                self.assertEqual(n["PLAN_COUNTS"]["movie_links"], 8125)
                if filename == "Export_Recovered_248":
                    state = n["load_progress"]()
                    self.assertEqual(len(state["receipts"]), 248)
                    self.assertEqual(state["pending"]["sid"], "408")
