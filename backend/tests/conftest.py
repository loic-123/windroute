import pytest


@pytest.fixture
def sample_athlete():
    return {
        "weight_kg": 72.0,
        "ftp_watts": 280,
        "cda": 0.36,
        "bike_weight_kg": 7.5,
        "crr": 0.004,
    }
