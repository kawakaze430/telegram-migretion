# Telegram channel migration

## South Movie recovery

**Latest verified pause:** The Kaggle run confirmed **2,441 / 2,727** movie photos (286 remaining). The last confirmed photo was **Ten Hours (2025)**, source 2895 at [destination Telegram post 2457](https://t.me/southdhamal/2457). During **Krishnavataram Part 1: The Heart (2026)** at source **2897**, the connection ended in `sendPhoto`, so the delivery is **uncertain**. The newest checkpoint has pending attempt `d203966ee25045fa9e9ff1acc44a6954`.

Use the [active South Movie recovery notebook](notebooks/south-movie/Telegram_South_Movie_Export_Recovered_Ready.ipynb) together with **`south_movie_verified_checkpoint.json` from the run that confirmed 2,441 photos**. Extract the checkpoint from its Kaggle `results (2).zip` or attach it as Kaggle Input. Do not use the older 2,266-, 1,227-, or 248-photo checkpoint after later uploads.

For the pending photo, choose **one** of these verifiable paths:

1. **Recommended:** Export **all messages** from the destination channel `@southdhamal` using Telegram Desktop's JSON export **after the failure**, and attach its current `result.json` alongside the latest checkpoint in Kaggle Input. The notebook verifies **every previously confirmed photo and Telegram message ID** and resolves the single pending photo only if the entire export matches. A stale or mismatching export stops before new posts.
2. **Manual alternative:** Inspect the destination channel after Telegram post 2457. If **Krishnavataram** is already there, put its exact Telegram post link in `PENDING_MESSAGE_ID`; if it is definitely absent, set integer `PENDING_MESSAGE_ID = 0`. `PENDING_KEY` is already set to `d203966ee25045fa9e9ff1acc44a6954`. The notebook **defaults to `PENDING_MESSAGE_ID = None`** and refuses to guess.

Run `RUN_MODE = "PREVIEW"` to validate the checkpoint without posting. For a live run, use `RUN_MODE = "REPAIR_AND_CONTINUE"`, enable Internet and the original `TELEGRAM_BOT_TOKEN` Kaggle secret, and run exactly one uploader at a time. After every run, keep its **new** `south_movie_verified_checkpoint.json`. Telegram explicitly rejected 429 responses can be retried after their cooldown (up to 900 seconds); ambiguous network errors and HTTP 5xx during `sendPhoto` still stop deliberately to avoid duplicates. GitHub Actions tests are **offline simulations**, not verification of live Telegram delivery.

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
