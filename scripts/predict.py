"""End-to-end forecast: fetch readings from the API, preprocess, load the model, predict.

The model is multivariate but the databases store one value per sensor per
timestamp, so we pull every sensor over the window and pivot back to wide.

    python predict.py --sensor-id 1 --source mongo --model rf
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

import joblib # type: ignore
import numpy as np
import pandas as pd
import requests

ARTIFACTS_DIR = "../notebook/artifacts"

TYPE_TO_COL = {
    "temperature": "temperature",
    "humidity": "humidity",
    "pressure": "pressure",
    "illuminance": "lux",
    "lux": "lux",
}
SQL_SENSOR_ID_TO_COL = {1: "temperature", 2: "humidity", 3: "pressure", 4: "lux"}


def fetch_wide_readings(api_base: str, source: str, lookback_hours: int = 96) -> pd.DataFrame:
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=lookback_hours)
    resp = requests.get(
        f"{api_base}/{source}/readings/range",
        params={"start": start.isoformat(), "end": end.isoformat()},
        timeout=15,
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        raise RuntimeError(
            f"No readings from /{source}/readings/range in the last {lookback_hours}h. "
            f"Seed recent hourly data first (see mongodb/seed_hourly.py)."
        )

    records = []
    for r in rows:
        ts = pd.to_datetime(r["recorded_at"])
        if source == "mongo":
            col = TYPE_TO_COL.get(r["sensor"]["type"])
        else:
            col = SQL_SENSOR_ID_TO_COL.get(r["sensor_id"])
        if col:
            records.append({"recorded_at": ts, "variable": col, "value": r["value"]})

    long_df = pd.DataFrame(records)
    wide = long_df.pivot_table(index="recorded_at", columns="variable",
                               values="value", aggfunc="mean").sort_index()
    wide.index = wide.index.tz_localize(None)
    return wide


def preprocess(df: pd.DataFrame, config: dict, feature_columns: list) -> pd.DataFrame:
    target_col = config["target_col"]
    if target_col not in df.columns:
        raise RuntimeError(f"Target column '{target_col}' missing from fetched data.")

    out = df.copy()
    for lag in [1, 3, 6]:
        out[f"{target_col}_lag{lag}"] = out[target_col].shift(lag)
    out[f"{target_col}_ma6"] = out[target_col].rolling(6).mean()
    out[f"{target_col}_ma24"] = out[target_col].rolling(24).mean()
    out[f"{target_col}_std6"] = out[target_col].rolling(6).std()
    out["hour"] = out.index.hour
    out["dayofweek"] = out.index.dayofweek

    out = out.dropna()
    missing = [c for c in feature_columns if c not in out.columns]
    if missing:
        raise RuntimeError(f"Missing engineered features after preprocessing: {missing}")
    if out.empty:
        raise RuntimeError("Not enough history after feature engineering (need >= 24 hourly rows).")
    return out[feature_columns]


def load_artifacts(artifacts_dir: str):
    scaler = joblib.load(f"{artifacts_dir}/scaler.joblib")
    with open(f"{artifacts_dir}/feature_columns.json") as f:
        feature_columns = json.load(f)
    with open(f"{artifacts_dir}/config.json") as f:
        config = json.load(f)
    return scaler, feature_columns, config


def load_model(artifacts_dir: str, model_choice: str):
    if model_choice == "rf":
        return joblib.load(f"{artifacts_dir}/random_forest_model.joblib"), "sklearn"
    elif model_choice == "lstm":
        import tensorflow as tf
        return tf.keras.models.load_model(f"{artifacts_dir}/lstm_model.keras"), "keras"
    raise ValueError("model_choice must be 'rf' or 'lstm'")


def predict(model, model_kind: str, X_scaled: np.ndarray, seq_len: int = 12):
    if model_kind == "sklearn":
        return float(model.predict(X_scaled[-1:])[0])
    if len(X_scaled) < seq_len:
        raise RuntimeError(f"Need at least {seq_len} recent rows for the LSTM window, got {len(X_scaled)}")
    window = X_scaled[-seq_len:].reshape(1, seq_len, -1)
    return float(model.predict(window, verbose=0).flatten()[0])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sensor-id", type=int, default=1)
    parser.add_argument("--api-base", type=str, default="http://localhost:8000")
    parser.add_argument("--source", type=str, choices=["mongo", "sql"], default="mongo")
    parser.add_argument("--model", type=str, choices=["rf", "lstm"], default="rf")
    parser.add_argument("--lookback-hours", type=int, default=96)
    parser.add_argument("--artifacts-dir", type=str, default=ARTIFACTS_DIR)
    args = parser.parse_args()

    print(f"[1/4] Fetching recent readings ({args.source}) from {args.api_base} ...")
    wide_df = fetch_wide_readings(args.api_base, args.source, args.lookback_hours)
    print(f"      pulled {len(wide_df)} hourly rows, variables={list(wide_df.columns)}")

    print("[2/4] Preprocessing (lags, moving averages, scaling) ...")
    scaler, feature_columns, config = load_artifacts(args.artifacts_dir)
    feat_df = preprocess(wide_df, config, feature_columns)
    X_scaled = scaler.transform(feat_df.values)

    print(f"[3/4] Loading model: {args.model} ...")
    model, model_kind = load_model(args.artifacts_dir, args.model)

    print("[4/4] Predicting next value ...")
    prediction = predict(model, model_kind, X_scaled, seq_len=config.get("seq_len", 12))

    result = {
        "sensor_id": args.sensor_id,
        "target": config["target_col"],
        "model": args.model,
        "source": args.source,
        "predicted_value": round(prediction, 4),
        "based_on_last_timestamp": str(feat_df.index[-1]),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
