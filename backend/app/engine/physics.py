"""
Physics engine: power → speed model for cycling.

Solves the fundamental equation:
  P_total = P_aero + P_rolling + P_gravity

for speed, given power, grade, wind, and rider parameters.
"""

import logging
import math

from scipy.optimize import brentq

logger = logging.getLogger(__name__)

# Constants
G = 9.80665  # gravitational acceleration (m/s²)
P0 = 101325.0  # standard sea-level pressure (Pa)
T0 = 288.15  # standard temperature (K)
M_AIR = 0.0289644  # molar mass of dry air (kg/mol)
R_GAS = 8.31447  # universal gas constant (J/(mol·K))
LAPSE_RATE = 0.0065  # temperature lapse rate (K/m)


def air_density(temperature_c: float, altitude_m: float = 0.0) -> float:
    """Calculate air density using the barometric formula.

    Args:
        temperature_c: ambient temperature in Celsius
        altitude_m: altitude above sea level in meters

    Returns:
        Air density in kg/m³
    """
    temp_k = temperature_c + 273.15

    # Pressure at altitude (barometric formula)
    pressure = P0 * (1 - LAPSE_RATE * altitude_m / T0) ** (
        G * M_AIR / (R_GAS * LAPSE_RATE)
    )

    # Density from ideal gas law
    return pressure * M_AIR / (R_GAS * temp_k)


def wind_component(
    wind_speed_ms: float,
    wind_direction_deg: float,
    route_bearing_deg: float,
) -> float:
    """Calculate headwind component along route direction.

    Args:
        wind_speed_ms: wind speed in m/s
        wind_direction_deg: meteorological wind direction (where wind comes FROM)
        route_bearing_deg: compass bearing of the route segment (0-360)

    Returns:
        Headwind component in m/s. Positive = headwind, negative = tailwind.
    """
    # Wind blows FROM wind_direction, so the wind vector points
    # in the opposite direction: wind_direction + 180
    relative_angle = math.radians(route_bearing_deg - wind_direction_deg)
    return wind_speed_ms * math.cos(relative_angle)


def power_to_speed(
    power_w: float,
    grade_percent: float = 0.0,
    wind_component_ms: float = 0.0,
    cda: float = 0.36,
    weight_kg: float = 75.0,
    bike_weight_kg: float = 8.0,
    crr: float = 0.004,
    temp_c: float = 15.0,
    altitude_m: float = 0.0,
) -> float:
    """Solve for cycling speed given power and conditions.

    Uses Brent's method to solve P_total(v) = P_target.

    Args:
        power_w: target power output in watts
        grade_percent: road gradient in percent (e.g., 5.0 for 5%)
        wind_component_ms: headwind component in m/s (positive = headwind)
        cda: aerodynamic drag coefficient × frontal area (m²)
        weight_kg: rider weight in kg
        bike_weight_kg: bicycle weight in kg
        crr: rolling resistance coefficient
        temp_c: temperature in Celsius
        altitude_m: altitude above sea level in meters

    Returns:
        Speed in m/s
    """
    rho = air_density(temp_c, altitude_m)
    total_mass = weight_kg + bike_weight_kg
    grade_rad = math.atan(grade_percent / 100.0)

    def power_required(v: float) -> float:
        if v <= 0:
            return 0.0

        # Aerodynamic drag: 0.5 × ρ × CdA × (v + v_wind)² × v
        v_apparent = v + wind_component_ms
        p_aero = 0.5 * rho * cda * v_apparent * abs(v_apparent) * v

        # Rolling resistance
        p_rolling = crr * total_mass * G * math.cos(grade_rad) * v

        # Gravity
        p_gravity = total_mass * G * math.sin(grade_rad) * v

        return p_aero + p_rolling + p_gravity

    def equation(v: float) -> float:
        return power_required(v) - power_w

    try:
        speed = brentq(equation, 0.5, 25.0, xtol=0.001)
        return max(speed, 0.5)
    except ValueError:
        # Power insufficient (steep climb + headwind) or equation has no root
        # Try with wider bounds first
        try:
            speed = brentq(equation, 0.1, 30.0, xtol=0.001)
            return max(speed, 0.5)
        except ValueError:
            # Check if rider can move at all
            p_min = power_required(0.5)
            if power_w < p_min:
                logger.warning(
                    "Power %.0fW insufficient for grade=%.1f%%, wind=%.1fm/s "
                    "(need %.0fW minimum). Using floor speed 1.0 m/s.",
                    power_w,
                    grade_percent,
                    wind_component_ms,
                    p_min,
                )
                return 1.0
            logger.warning(
                "brentq failed for power=%.0fW, grade=%.1f%%. "
                "Using floor speed 1.0 m/s.",
                power_w,
                grade_percent,
            )
            return 1.0


def speed_to_power(
    speed_ms: float,
    grade_percent: float = 0.0,
    wind_component_ms: float = 0.0,
    cda: float = 0.36,
    weight_kg: float = 75.0,
    bike_weight_kg: float = 8.0,
    crr: float = 0.004,
    temp_c: float = 15.0,
    altitude_m: float = 0.0,
) -> float:
    """Calculate power required for a given speed (inverse of power_to_speed)."""
    rho = air_density(temp_c, altitude_m)
    total_mass = weight_kg + bike_weight_kg
    grade_rad = math.atan(grade_percent / 100.0)

    v_apparent = speed_ms + wind_component_ms
    p_aero = 0.5 * rho * cda * v_apparent * abs(v_apparent) * speed_ms
    p_rolling = crr * total_mass * G * math.cos(grade_rad) * speed_ms
    p_gravity = total_mass * G * math.sin(grade_rad) * speed_ms

    return p_aero + p_rolling + p_gravity


def estimate_speed_flat(
    power_w: float,
    cda: float = 0.36,
    weight_kg: float = 75.0,
    bike_weight_kg: float = 8.0,
    crr: float = 0.004,
    temp_c: float = 15.0,
) -> float:
    """Quick estimate of flat-road speed (no wind, no grade)."""
    return power_to_speed(
        power_w=power_w,
        grade_percent=0.0,
        wind_component_ms=0.0,
        cda=cda,
        weight_kg=weight_kg,
        bike_weight_kg=bike_weight_kg,
        crr=crr,
        temp_c=temp_c,
    )
