-- Relational schema (MySQL) for the sensor time-series dataset.
-- Group 12

CREATE DATABASE IF NOT EXISTS sensor_timeseries
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE sensor_timeseries;

-- sensors: one row per physical sensor
CREATE TABLE sensors (
    sensor_id     INT AUTO_INCREMENT PRIMARY KEY,
    sensor_name   VARCHAR(100) NOT NULL,
    sensor_type   ENUM('temperature', 'humidity', 'pressure', 'illuminance') NOT NULL,
    location      VARCHAR(150) DEFAULT NULL,
    unit          VARCHAR(20)  NOT NULL,          -- e.g. 'C', '%', 'hPa', 'lux'
    installed_at  DATE         DEFAULT NULL,
    UNIQUE KEY uq_sensor_name (sensor_name)
) ENGINE=InnoDB;

-- readings: one row per sensor per timestamp (narrow/long format)
CREATE TABLE readings (
    reading_id    BIGINT AUTO_INCREMENT PRIMARY KEY,
    sensor_id     INT NOT NULL,
    recorded_at   DATETIME NOT NULL,
    value         DECIMAL(10, 4) NOT NULL,
    is_interpolated TINYINT(1) NOT NULL DEFAULT 0,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_readings_sensor
        FOREIGN KEY (sensor_id) REFERENCES sensors(sensor_id)
        ON DELETE CASCADE,
    UNIQUE KEY uq_sensor_time (sensor_id, recorded_at),
    INDEX idx_recorded_at (recorded_at)
) ENGINE=InnoDB;

-- model_predictions: forecasts produced by the prediction script
CREATE TABLE model_predictions (
    prediction_id   BIGINT AUTO_INCREMENT PRIMARY KEY,
    model_name      VARCHAR(100) NOT NULL,
    target_sensor_id INT NOT NULL,
    predicted_for   DATETIME NOT NULL,
    predicted_value DECIMAL(10, 4) NOT NULL,
    actual_value    DECIMAL(10, 4) DEFAULT NULL,
    generated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_predictions_sensor
        FOREIGN KEY (target_sensor_id) REFERENCES sensors(sensor_id)
        ON DELETE CASCADE,
    INDEX idx_predicted_for (predicted_for)
) ENGINE=InnoDB;

-- experiment_runs: persists the Task 1 experiment/metrics table
CREATE TABLE experiment_runs (
    run_id          INT AUTO_INCREMENT PRIMARY KEY,
    model_name      VARCHAR(100) NOT NULL,
    hyperparameters JSON NOT NULL,
    mae             DECIMAL(10, 4) NOT NULL,
    rmse            DECIMAL(10, 4) NOT NULL,
    r2              DECIMAL(6, 4)  NOT NULL,
    trained_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- Sample seed data
INSERT INTO sensors (sensor_name, sensor_type, location, unit, installed_at) VALUES
  ('temp_01', 'temperature', 'Lab Room A', 'C', '2023-01-01'),
  ('hum_01',  'humidity',    'Lab Room A', '%', '2023-01-01'),
  ('pres_01', 'pressure',    'Lab Room A', 'hPa', '2023-01-01'),
  ('lux_01',  'illuminance', 'Lab Room A', 'lux', '2023-01-01');

INSERT INTO readings (sensor_id, recorded_at, value, is_interpolated) VALUES
  (1, '2023-06-01 08:00:00', 21.4, 0),
  (1, '2023-06-01 09:00:00', 22.1, 0),
  (2, '2023-06-01 08:00:00', 55.2, 0),
  (2, '2023-06-01 09:00:00', 54.8, 0);

-- Required queries (results shown in the report)

-- Q1: Latest reading for every sensor
SELECT s.sensor_name, r.recorded_at, r.value
FROM readings r
JOIN sensors s ON s.sensor_id = r.sensor_id
WHERE r.recorded_at = (
    SELECT MAX(r2.recorded_at) FROM readings r2 WHERE r2.sensor_id = r.sensor_id
);

-- Q2: All temperature readings within a date range
SELECT s.sensor_name, r.recorded_at, r.value
FROM readings r
JOIN sensors s ON s.sensor_id = r.sensor_id
WHERE s.sensor_type = 'temperature'
  AND r.recorded_at BETWEEN '2023-06-01 00:00:00' AND '2023-06-02 00:00:00'
ORDER BY r.recorded_at;

-- Q3: Daily average per sensor type (aggregation query)
SELECT s.sensor_type, DATE(r.recorded_at) AS day, ROUND(AVG(r.value), 2) AS avg_value
FROM readings r
JOIN sensors s ON s.sensor_id = r.sensor_id
GROUP BY s.sensor_type, DATE(r.recorded_at)
ORDER BY day;

-- Q4: Best-performing experiment run (lowest MAE)
SELECT model_name, hyperparameters, mae, rmse, r2
FROM experiment_runs
ORDER BY mae ASC
LIMIT 1;
