# Telegram channel migration

## South Movie recovery

The latest verified Kaggle run for `@southdhamal` confirmed **2,266 of 2,727 movie photos** and paused on **source 2712** after an explicit Telegram HTTP 429 flood limit requested **475 seconds**. **461 photos remain.** There was **no uncertain pending delivery** in this run; the latest checkpoint contains 2,280 receipts (including legacy non-movie entries), 12 previously deleted legacy text messages, and no manual-review items.

Use **[the active South Movie recovery notebook](notebooks/south-movie/Telegram_South_Movie_Export_Recovered_Ready.ipynb)** on Kaggle with **`south_movie_verified_checkpoint.json` from the 2,266-photo saved run**, not the old 1,227-photo checkpoint or the embedded 248-message export. Attach the newest `results.zip` as notebook input only if its JSON is extracted as an input file; the notebook searches `/kaggle/input/**/*.json` for that exact checkpoint filename.

1. For a read-only validation, set `RUN_MODE = "PREVIEW"` and verify **2,266 confirmed**, **461 remaining**, and **source 2712** next. The notebook defaults to `REPAIR_AND_CONTINUE` for live operation; no manual setting change is needed after that check.
2. Keep Internet on, the original `TELEGRAM_BOT_TOKEN` Kaggle secret enabled, and exactly one uploader running.
3. The live uploader now handles explicit Telegram HTTP 429 cooldowns up to **900 seconds** (plus a one-second safety margin), retries the same rejected photo, and still pauses safely on ambiguous disconnects or 5xx responses. A cooldown longer than 900 seconds or repeated rejections still pauses with the latest checkpoint saved.
4. After each run, retain its newly generated `south_movie_verified_checkpoint.json` from `/kaggle/working`. **Never re-run with an older checkpoint after more photos were uploaded**: doing so can duplicate posts.

The full Telegram Desktop `result.json` fallback only reconstructs the earlier 1,227-photo boundary. Use the new checkpoint for all later progress.

| Notebook collection | Contents |
| --- | --- |
| [South Movie](notebooks/south-movie) | Six versions covering initial import, missing media, caption repair, and recovery. The file ending in `_248` is for the earlier Vikram interruption. |
| [Movie1](notebooks/movie1) | Eight versions covering the original uploader, extra photos, full migration and the 21-post incremental batch. |
| [Original Colab notebook](Telegram_Channel_Migration.ipynb) | The existing developer handoff and interactive Movie1 migration. |

## GitHub Actions

Pushes, pull requests and manual runs use the same offline test command on Python 3.11, 3.12 and 3.13. Tests validate the notebooks, compile their Python code, check embedded archives, run preparation and preview cells, and exercise delivery and recovery with simulated Telegram responses. The suite uses temporary directories and synthetic checkpoints. [Open Notebook checks](https://github.com/kawakaze430/telegram-migretion/actions/workflows/notebook-checks.yml)

Run locally from the repository root on Linux with one of the Python versions above.

```bash
python -m pip install -r tests/requirements.txt
python -m unittest discover -s tests -v
```
