# NASA Official Challenge Dataset Directory

Drop any newly released NASA Space Apps physiological baseline files (`.json` or `.csv`) into this folder (`data/nasa_official_dataset/`).

`backend/services/anomaly_detector.py` checks this directory as Priority #1 and falls back to `data/nasa_baselines_and_thresholds.json` for any missing parameters.
