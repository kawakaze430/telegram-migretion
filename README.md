# Telegram channel migration

## South Movie recovery

The Kaggle run for `@southdhamal` confirmed 1,227 of 2,727 movie photos. The channel owner confirmed that **Ombatthane Dikku (2022)**, source 1567, was the last visible post. The connection dropped while sending **Annapoorani – The Goddess of Food (2023)**, source 1568. At that checkpoint, 1,500 photos remained.

Use the notebook for the 1,227-photo checkpoint. Attach `south_movie_verified_checkpoint.json` from the paused Kaggle run or a full Telegram Desktop JSON export of the destination channel through that pause. For a read-only check, set `RUN_MODE = "PREVIEW"`. The notebook checks the evidence before continuing. [Open the South Movie recovery notebook](notebooks/south-movie/Telegram_South_Movie_Export_Recovered_Ready.ipynb)

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
