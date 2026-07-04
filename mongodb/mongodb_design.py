# MongoDB design for the sensor data: one document per reading with the sensor
# metadata embedded (no joins), plus a collection of model prediction runs.
# Run: python mongodb_design.py

from pymongo import MongoClient, ASCENDING, DESCENDING
from datetime import datetime

client = MongoClient("mongodb://localhost:27017/")
db = client["sensor_timeseries"]

readings_col = db["readings"]
predictions_col = db["model_predictions"]

sample_readings = [
    {
        "sensor": {
            "sensor_id": "temp_01",
            "type": "temperature",
            "location": "Lab Room A",
            "unit": "C",
        },
        "recorded_at": datetime(2023, 6, 1, 8, 0, 0),
        "value": 21.4,
        "is_interpolated": False,
    },
    {
        "sensor": {
            "sensor_id": "hum_01",
            "type": "humidity",
            "location": "Lab Room A",
            "unit": "%",
        },
        "recorded_at": datetime(2023, 6, 1, 8, 0, 0),
        "value": 55.2,
        "is_interpolated": False,
    },
    {
        "sensor": {
            "sensor_id": "pres_01",
            "type": "pressure",
            "location": "Lab Room A",
            "unit": "hPa",
        },
        "recorded_at": datetime(2023, 6, 1, 8, 0, 0),
        "value": 1013.2,
        "is_interpolated": False,
    },
]

sample_predictions = [
    {
        "model_name": "random_forest_v1",
        "target_sensor_id": "temp_01",
        "predicted_for": datetime(2023, 6, 1, 9, 0, 0),
        "predicted_value": 22.0,
        "actual_value": 22.1,
        "generated_at": datetime.utcnow(),
    }
]


def seed():
    readings_col.delete_many({})
    predictions_col.delete_many({})
    readings_col.insert_many(sample_readings)
    predictions_col.insert_many(sample_predictions)

    readings_col.create_index([("sensor.sensor_id", ASCENDING), ("recorded_at", DESCENDING)])
    readings_col.create_index([("recorded_at", ASCENDING)])
    predictions_col.create_index([("predicted_for", ASCENDING)])
    print("Seeded collections and created indexes.")


def query_latest_reading(sensor_id: str):
    return readings_col.find_one(
        {"sensor.sensor_id": sensor_id}, sort=[("recorded_at", DESCENDING)]
    )


def query_by_date_range(start: datetime, end: datetime, sensor_type: str = None):
    query = {"recorded_at": {"$gte": start, "$lte": end}}
    if sensor_type:
        query["sensor.type"] = sensor_type
    return list(readings_col.find(query).sort("recorded_at", ASCENDING))


def query_daily_average(sensor_type: str):
    pipeline = [
        {"$match": {"sensor.type": sensor_type}},
        {
            "$group": {
                "_id": {
                    "$dateToString": {"format": "%Y-%m-%d", "date": "$recorded_at"}
                },
                "avg_value": {"$avg": "$value"},
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"_id": 1}},
    ]
    return list(readings_col.aggregate(pipeline))


if __name__ == "__main__":
    seed()
    print("Latest temp_01 reading:", query_latest_reading("temp_01"))
    print(
        "Readings in range:",
        query_by_date_range(datetime(2023, 6, 1), datetime(2023, 6, 2)),
    )
    print("Daily average (temperature):", query_daily_average("temperature"))
