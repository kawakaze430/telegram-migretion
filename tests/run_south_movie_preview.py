"""Replay the recovery-relevant data from the Telegram export ending at post 2457 in Jupyter."""
import ast
import base64
import hashlib
import json
import os
import tempfile
import zlib
from pathlib import Path

from notebook_support import SOUTH, cells

NOTEBOOK = SOUTH / "Telegram_South_Movie_Export_Recovered_Ready.ipynb"
CHECKPOINT = "south_movie_verified_checkpoint.json"
ATTEMPT_2897 = "d203966ee25045fa9e9ff1acc44a6954"


def digest(rows):
    raw = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def recorded_inputs():
    """Reconstruct receipt IDs, actions and exported captions without publishing the raw files."""
    cell = next(c for c in cells(NOTEBOOK) if any(line.startswith("PACKED_PLAN =") for line in c["source"]))
    packed = next(node.value for node in ast.parse("".join(cell["source"])).body
                  if isinstance(node, ast.Assign) and node.targets[0].id == "PACKED_PLAN")
    raw = zlib.decompress(base64.b64decode(ast.literal_eval(packed)))
    plan = json.loads(raw)
    captions = {p["source_id"]: p["caption"] for p in plan["posts"] if p["source_id"] <= 2895}
    confirmed = sorted(set(captions) | {sid for sid, _ in plan["failed_run_prefix"][:-1]})
    kinds = dict(plan["legacy_units"])
    receipts, done = {}, {}
    messages = [{"type": "service", "id": 1}, {"type": "message", "id": 2, "text": "setup"}]
    receipt_rows, photo_rows = [], []
    # In these attachments the checkpoint covers every Telegram ID from 3 through 2457.
    for mid, sid in enumerate(confirmed, start=3):
        kind = kinds[sid]
        action = "caption" if kind == "photo" else "deleted"
        receipts[str(sid)] = {"message_id": mid, "kind": kind}
        done[str(sid)] = action
        receipt_rows.append([sid, mid, kind, action])
        if kind == "photo" and mid != 2282:
            caption = captions.get(sid, "")
            photo_rows.append([mid, caption.strip()])
            messages.append({"type": "message", "id": mid, "photo": "fixture.jpg", "text": caption})
    # Fixed digests were computed independently from the uploaded checkpoint and Desktop export.
    # They cover every receipt ID/kind/action and every exported photo ID/normalized caption.
    if digest(receipt_rows) != "9984c78c72d81c62c878d0bdc147b2a30bc45626d6352f703fdb4c3ec04950fa":
        raise AssertionError("Fixture receipt history differs from the supplied checkpoint")
    if digest(photo_rows) != "02054d30a988a6879d794950cbcd3a227a21248b8e8f04eb3eb9c52b34dcb240":
        raise AssertionError("Fixture photo history differs from the supplied export")
    state = {
        "version": 3, "target": "@southdhamal", "target_id": -1004376620825, "bot_id": 42,
        "repo": "kawakaze430/south-movie", "ref": plan["ref"], "plan_digest": hashlib.sha256(raw).hexdigest(),
        "receipts": receipts, "done": done, "issues": {}, "revision": 4671,
        "pending": {"sid": "2897", "kind": "photo", "attempt": ATTEMPT_2897},
        "resolutions": {
            "v1-408": {"sid": "408", "message_id": 0},
            "d5c39ccae9404bc69dc6fa79cd21b846": {"sid": "1568", "message_id": 0},
            "fixture-2712": {"sid": "2712", "message_id": 0},
        },
    }
    return state, {"type": "public_channel", "id": 4376620825, "messages": messages}


def main():
    import nbformat
    from nbclient import NotebookClient

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        checkpoint, export = recorded_inputs()
        checkpoint_path = root / CHECKPOINT
        export_path = root / "result.json"
        checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")
        export_path.write_text(json.dumps(export), encoding="utf-8")

        notebook = nbformat.read(NOTEBOOK, as_version=4)
        settings = next(c for c in notebook.cells if c.cell_type == "code" and
                        any(line.startswith("RUN_MODE =") for line in c.source.splitlines()))
        settings.source += (f"\nRUN_MODE = 'PREVIEW'\nCHECKPOINT_PATH = {str(checkpoint_path)!r}"
                            f"\nDESTINATION_EXPORT = {str(export_path)!r}\n")
        NotebookClient(notebook, kernel_name="python3", timeout=120,
                       resources={"metadata": {"path": directory}}).execute()
        output = root / "south_movie_output"
        summary = json.loads((output / "south_movie_run_summary.json").read_bytes())
        expected = {
            "status": "PREVIEW", "confirmed_movie_photos": 2441, "remaining_movie_photos": 286,
            "next_outstanding_source": "2897", "pending": None, "manual_review_items": 1,
            "historical_photos_missing_from_export": {"2711": 2282},
        }
        for field, value in expected.items():
            if summary.get(field) != value or field not in summary:
                raise AssertionError(f"{field} should be {value!r}. Notebook summary: {summary}")
        if (output / CHECKPOINT).exists() or json.loads(checkpoint_path.read_bytes()) != checkpoint:
            raise AssertionError("Preview changed the checkpoint")
        print(json.dumps(expected, indent=2))
        if step_summary := os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(step_summary, "a", encoding="utf-8") as out:
                out.write("### South Movie Jupyter preview\n\n"
                          "| Checked against the supplied files | Result |\n| --- | --- |\n"
                          "| Historical photo receipts | 2,443 |\n| Exported photos matched by ID and caption | 2,442 |\n"
                          "| Historical receipt for review | Source 2711, Telegram post 2282 |\n"
                          "| Confirmed movie photos | 2,441 of 2,727 |\n| Remaining movie photos | 286 |\n"
                          "| Next source in this export | 2897 |\n\n"
                          "The notebook ran in preview using reconstructed inputs with verified content digests. "
                          "The input checkpoint was preserved.\n")


if __name__ == "__main__":
    main()
