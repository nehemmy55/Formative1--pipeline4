"""CRUD and time-series query API for the sensor project (MySQL + MongoDB)."""

import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from pymongo import MongoClient, ASCENDING, DESCENDING

app = FastAPI(title="Sensor Time-Series API", version="1.0.0")

MYSQL_URL = os.getenv(
    "MYSQL_URL", "mysql+pymysql://root:password@localhost:3306/sensor_timeseries"
)
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017/")

engine = create_engine(MYSQL_URL, pool_pre_ping=True)
mongo_client = MongoClient(MONGO_URL)
mongo_db = mongo_client["sensor_timeseries"]
readings_col = mongo_db["readings"]


class ReadingIn(BaseModel):
    sensor_id: int
    recorded_at: datetime
    value: float
    is_interpolated: bool = False


class ReadingUpdate(BaseModel):
    value: Optional[float] = None
    is_interpolated: Optional[bool] = None


class MongoReadingIn(BaseModel):
    sensor_id: str
    sensor_type: str
    location: Optional[str] = None
    unit: str
    recorded_at: datetime
    value: float
    is_interpolated: bool = False


# ---- MySQL ----

@app.post("/sql/readings", status_code=201)
def create_sql_reading(reading: ReadingIn):
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """INSERT INTO readings (sensor_id, recorded_at, value, is_interpolated)
                   VALUES (:sensor_id, :recorded_at, :value, :is_interpolated)"""
            ),
            reading.model_dump(),
        )
        return {"reading_id": result.lastrowid}


# /range must come before /{reading_id} or "range" is read as an id.
@app.get("/sql/readings/range")
def sql_readings_by_range(
    start: datetime = Query(...),
    end: datetime = Query(...),
    sensor_id: Optional[int] = None,
):
    query = "SELECT * FROM readings WHERE recorded_at BETWEEN :start AND :end"
    params = {"start": start, "end": end}
    if sensor_id is not None:
        query += " AND sensor_id = :sensor_id"
        params["sensor_id"] = sensor_id
    query += " ORDER BY recorded_at ASC"
    with engine.connect() as conn:
        rows = conn.execute(text(query), params).mappings().all()
        return [dict(r) for r in rows]


@app.get("/sql/readings/{reading_id}")
def get_sql_reading(reading_id: int):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM readings WHERE reading_id = :id"), {"id": reading_id}
        ).mappings().first()
        if not row:
            raise HTTPException(404, "Reading not found")
        return dict(row)


@app.put("/sql/readings/{reading_id}")
def update_sql_reading(reading_id: int, update: ReadingUpdate):
    fields = {k: v for k, v in update.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "No fields to update")
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = reading_id
    with engine.begin() as conn:
        result = conn.execute(
            text(f"UPDATE readings SET {set_clause} WHERE reading_id = :id"), fields
        )
        if result.rowcount == 0:
            raise HTTPException(404, "Reading not found")
    return {"status": "updated"}


@app.delete("/sql/readings/{reading_id}")
def delete_sql_reading(reading_id: int):
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM readings WHERE reading_id = :id"), {"id": reading_id}
        )
        if result.rowcount == 0:
            raise HTTPException(404, "Reading not found")
        return {"status": "deleted"}


@app.get("/sql/readings/sensor/{sensor_id}/latest")
def latest_sql_reading(sensor_id: int):
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """SELECT * FROM readings WHERE sensor_id = :sensor_id
                   ORDER BY recorded_at DESC LIMIT 1"""
            ),
            {"sensor_id": sensor_id},
        ).mappings().first()
        if not row:
            raise HTTPException(404, "No readings for this sensor")
        return dict(row)


# ---- MongoDB ----

@app.post("/mongo/readings", status_code=201)
def create_mongo_reading(reading: MongoReadingIn):
    doc = {
        "sensor": {
            "sensor_id": reading.sensor_id,
            "type": reading.sensor_type,
            "location": reading.location,
            "unit": reading.unit,
        },
        "recorded_at": reading.recorded_at,
        "value": reading.value,
        "is_interpolated": reading.is_interpolated,
    }
    result = readings_col.insert_one(doc)
    return {"_id": str(result.inserted_id)}


@app.get("/mongo/readings/range")
def mongo_readings_by_range(
    start: datetime = Query(...),
    end: datetime = Query(...),
    sensor_id: Optional[str] = None,
):
    query = {"recorded_at": {"$gte": start, "$lte": end}}
    if sensor_id:
        query["sensor.sensor_id"] = sensor_id
    docs = list(readings_col.find(query).sort("recorded_at", ASCENDING))
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


@app.get("/mongo/readings/{doc_id}")
def get_mongo_reading(doc_id: str):
    from bson import ObjectId

    doc = readings_col.find_one({"_id": ObjectId(doc_id)})
    if not doc:
        raise HTTPException(404, "Reading not found")
    doc["_id"] = str(doc["_id"])
    return doc


@app.put("/mongo/readings/{doc_id}")
def update_mongo_reading(doc_id: str, value: Optional[float] = None, is_interpolated: Optional[bool] = None):
    from bson import ObjectId

    fields = {}
    if value is not None:
        fields["value"] = value
    if is_interpolated is not None:
        fields["is_interpolated"] = is_interpolated
    if not fields:
        raise HTTPException(400, "No fields to update")
    result = readings_col.update_one({"_id": ObjectId(doc_id)}, {"$set": fields})
    if result.matched_count == 0:
        raise HTTPException(404, "Reading not found")
    return {"status": "updated"}


@app.delete("/mongo/readings/{doc_id}")
def delete_mongo_reading(doc_id: str):
    from bson import ObjectId

    result = readings_col.delete_one({"_id": ObjectId(doc_id)})
    if result.deleted_count == 0:
        raise HTTPException(404, "Reading not found")
    return {"status": "deleted"}


@app.get("/mongo/readings/sensor/{sensor_id}/latest")
def latest_mongo_reading(sensor_id: str):
    doc = readings_col.find_one(
        {"sensor.sensor_id": sensor_id}, sort=[("recorded_at", DESCENDING)]
    )
    if not doc:
        raise HTTPException(404, "No readings for this sensor")
    doc["_id"] = str(doc["_id"])
    return doc


@app.get("/health")
def health():
    return {"status": "ok"}
