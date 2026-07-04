"""Seed the readings collection with hourly multivariate data so predict.py has
enough history for lags and moving averages. Timestamps are shifted so the last
reading is ~now. Run: python seed_hourly.py"""

import pandas as pd
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient, ASCENDING

CSV_PATH = "../data/DATA-large.CSV"
N_HOURS = 168  # one week of hourly history

SENSOR_META = {
    "temperature": {"sensor_id": "temp_01", "type": "temperature", "location": "Lab Room A", "unit": "C"},
    "humidity":    {"sensor_id": "hum_01",  "type": "humidity",    "location": "Lab Room A", "unit": "%"},
    "pressure":    {"sensor_id": "pres_01", "type": "pressure",    "location": "Lab Room A", "unit": "Pa"},
    "lux":         {"sensor_id": "lux_01",  "type": "illuminance", "location": "Lab Room A", "unit": "lux"},
}


def load_hourly():
    df = pd.read_csv(CSV_PATH)
    df["time"] = pd.to_datetime(df["time"], format="mixed")
    df = df.sort_values("time").set_index("time")
    for c in ["temperature", "humidity", "pressure", "lux"]:
        df[c] = df[c].interpolate(method="time", limit_direction="both")
    df = df.resample("1h").mean().dropna()
    return df.tail(N_HOURS)


def main():
    df = load_hourly()

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    new_index = [now - timedelta(hours=(len(df) - 1 - i)) for i in range(len(df))]

    client = MongoClient("mongodb://localhost:27017/")
    col = client["sensor_timeseries"]["readings"]
    col.create_index([("sensor.sensor_id", ASCENDING), ("recorded_at", ASCENDING)])

    # idempotent: drop previously seeded rows before reinserting
    col.delete_many({"sensor.sensor_id": {"$in": [m["sensor_id"] for m in SENSOR_META.values()]},
                     "source": "hourly_seed"})

    docs = []
    for ts, (_, row) in zip(new_index, df.iterrows()):
        for var, meta in SENSOR_META.items():
            docs.append({
                "sensor": meta,
                "recorded_at": ts,
                "value": round(float(row[var]), 4),
                "is_interpolated": False,
                "source": "hourly_seed",
            })
    col.insert_many(docs)
    print(f"Inserted {len(docs)} hourly docs "
          f"({len(df)} hours x {len(SENSOR_META)} sensors).")
    print(f"Time range: {new_index[0]} -> {new_index[-1]}")


if __name__ == "__main__":
    main()
