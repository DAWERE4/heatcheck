"""Heat index math, using the U.S. National Weather Service formula.

Reference: https://www.wpc.ncep.noaa.gov/html/heatindex_equation.shtml
"""

import math

# (minimum heat index in °F, label, css class), highest first.
# NWS bands: Caution 80-90, Extreme caution 90-103, Danger 103-124, Extreme danger 125+.
CATEGORIES = [
    (125.0, "Extreme danger", "extreme-danger"),
    (103.0, "Danger", "danger"),
    (90.0, "Extreme caution", "extreme-caution"),
    (80.0, "Caution", "caution"),
    (float("-inf"), "Normal", "normal"),
]


def c_to_f(temp_c: float) -> float:
    return float(temp_c) * 9.0 / 5.0 + 32.0


def heat_index_f(temp_f: float, humidity: float) -> float:
    """Return the heat index ("feels like" temperature) in °F.

    temp_f   -- air temperature in °F
    humidity -- relative humidity in percent (0-100)
    """
    t = float(temp_f)
    rh = max(0.0, min(100.0, float(humidity)))

    # NWS: compute the simple formula first, average it with the temperature,
    # and only use the full regression if that average is 80°F or higher.
    simple = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094)
    if (simple + t) / 2.0 < 80.0:
        return simple

    hi = (
        -42.379
        + 2.04901523 * t
        + 10.14333127 * rh
        - 0.22475541 * t * rh
        - 0.00683783 * t * t
        - 0.05481717 * rh * rh
        + 0.00122874 * t * t * rh
        + 0.00085282 * t * rh * rh
        - 0.00000199 * t * t * rh * rh
    )

    if rh < 13.0 and 80.0 <= t <= 112.0:
        hi -= ((13.0 - rh) / 4.0) * math.sqrt((17.0 - abs(t - 95.0)) / 17.0)
    elif rh > 85.0 and 80.0 <= t <= 87.0:
        hi += ((rh - 85.0) / 10.0) * ((87.0 - t) / 5.0)

    return hi


def category(hi_f: float) -> dict:
    """Return the NWS category for a heat index value."""
    for minimum, label, css in CATEGORIES:
        if hi_f >= minimum:
            return {"label": label, "css": css}
    return {"label": "Normal", "css": "normal"}  # pragma: no cover
