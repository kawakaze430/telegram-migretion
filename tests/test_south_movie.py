import json
from unittest.mock import Mock

import requests

from notebook_support import OfflineCase, SOUTH, cells, run_cell

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
        self.assertEqual((n["PENDING_KEY"], n["PENDING_MESSAGE_ID"]), (ATTEMPT, 0))
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
