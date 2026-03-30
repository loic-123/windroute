"""Tests for the physics engine (power ↔ speed)."""

import pytest

from app.engine.physics import air_density, power_to_speed, speed_to_power, wind_component


class TestAirDensity:
    def test_sea_level_15c(self):
        rho = air_density(15.0, 0.0)
        assert 1.20 < rho < 1.25  # ~1.225

    def test_higher_altitude_lower_density(self):
        rho_0 = air_density(15.0, 0.0)
        rho_1000 = air_density(15.0, 1000.0)
        assert rho_1000 < rho_0

    def test_higher_temp_lower_density(self):
        rho_cold = air_density(5.0, 0.0)
        rho_hot = air_density(35.0, 0.0)
        assert rho_hot < rho_cold


class TestWindComponent:
    def test_pure_headwind(self):
        # Wind from north (0°), riding north (0°) → headwind
        comp = wind_component(5.0, 0.0, 0.0)
        assert comp > 0  # headwind is positive

    def test_pure_tailwind(self):
        # Wind from north (0°), riding south (180°) → tailwind
        comp = wind_component(5.0, 0.0, 180.0)
        assert comp < 0  # tailwind is negative

    def test_crosswind(self):
        # Wind from north (0°), riding east (90°) → crosswind
        comp = wind_component(5.0, 0.0, 90.0)
        assert abs(comp) < 0.01  # nearly zero


class TestPowerToSpeed:
    def test_flat_no_wind(self):
        """Typical flat road speed at 200W, ~30 km/h for 75kg rider."""
        speed = power_to_speed(200, grade_percent=0.0, wind_component_ms=0.0)
        speed_kmh = speed * 3.6
        assert 28 < speed_kmh < 35

    def test_uphill_5_percent(self):
        """Uphill at 5% should be much slower."""
        speed_flat = power_to_speed(250, grade_percent=0.0)
        speed_hill = power_to_speed(250, grade_percent=5.0)
        assert speed_hill < speed_flat
        assert speed_hill * 3.6 > 8  # should still be > 8 km/h

    def test_downhill(self):
        """Downhill should be faster than flat at same power."""
        speed_flat = power_to_speed(150, grade_percent=0.0)
        speed_down = power_to_speed(150, grade_percent=-3.0)
        assert speed_down > speed_flat

    def test_headwind_slows_down(self):
        speed_calm = power_to_speed(200, wind_component_ms=0.0)
        speed_headwind = power_to_speed(200, wind_component_ms=5.0)
        assert speed_headwind < speed_calm

    def test_tailwind_speeds_up(self):
        speed_calm = power_to_speed(200, wind_component_ms=0.0)
        speed_tailwind = power_to_speed(200, wind_component_ms=-5.0)
        assert speed_tailwind > speed_calm

    def test_high_power_faster(self):
        speed_low = power_to_speed(150)
        speed_high = power_to_speed(300)
        assert speed_high > speed_low

    def test_lighter_rider_faster(self):
        speed_heavy = power_to_speed(200, weight_kg=85)
        speed_light = power_to_speed(200, weight_kg=65)
        assert speed_light > speed_heavy

    def test_aero_position_faster(self):
        speed_hoods = power_to_speed(200, cda=0.36)
        speed_aero = power_to_speed(200, cda=0.24)
        assert speed_aero > speed_hoods

    def test_floor_speed_extreme_conditions(self):
        """Very low power on steep climb with headwind should hit floor."""
        speed = power_to_speed(
            50, grade_percent=15.0, wind_component_ms=10.0
        )
        assert speed >= 0.5  # should not go below floor

    def test_consistency_with_inverse(self):
        """power_to_speed and speed_to_power should be consistent."""
        speed = power_to_speed(250, grade_percent=3.0, wind_component_ms=2.0)
        power = speed_to_power(speed, grade_percent=3.0, wind_component_ms=2.0)
        assert abs(power - 250) < 1.0  # within 1W
