# Configurable physiological thresholds and rules
CONSTRAINTS = {
    "blood_pressure": {
        "min_systolic": 40,
        "max_systolic": 250,
        "min_diastolic": 20,
        "max_diastolic": 180,
    },
    "heart_rate": {
        "min": 20,
        "max": 300,
        "warning_max": 180,
        "warning_min": 40
    },
    "spo2": {
        "min": 0,
        "max": 100,
        "warning_min": 85
    },
    "temperature": {
        "min": 25.0, # Celsius
        "max": 43.0,
        "warning_min": 35.0,
        "warning_max": 39.5
    },
    "age": {
        "min": 0,
        "max": 120
    },
    "respiratory_rate": {
        "min": 0,
        "max": 80,
        "warning_min": 8,
        "warning_max": 40
    },
    "height": {
        "min": 20, # cm
        "max": 250
    },
    "weight": {
        "min": 1, # kg
        "max": 400
    },
    "blood_glucose": {
        "min": 0,
        "max": 1500,
        "warning_min": 50,
        "warning_max": 300
    }
}
