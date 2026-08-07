"""How long a controller programme takes, from its ramp/soak segments.

Free of Odoo imports so the arithmetic can be tested on plain tuples, and
shared: `mb.kiln.program.segment` computes a stored schedule with it, and
`mb_kiln_bridge` uses it on provider payloads before any record exists.

A Rohde segment is a rate, a target and a hold - not a duration. The controller
derives the duration, and so must we:

    ramp minutes = 60 * |target - where the previous segment left off| / rate
    segment      = ramp + soak

with two rules taken from the controller's own behaviour rather than invented:

* **A rate at or above 999 deg/hour means full power**, not "999 degrees an
  hour". The ST411 uses it as the skip-the-ramp sentinel, so the scheduled ramp
  is zero and the segment is its soak alone. Live data confirms it: a segment
  carrying 1000.0 targets the temperature the previous one already reached.
* **The first segment starts from ambient.** The controller starts from
  whatever the chamber happens to be, which for a load put in cold is room
  temperature. Nothing in the programme records it, so it is assumed, and a kiln
  still warm from yesterday will beat the estimate rather than miss it.

The result is the *scheduled* length. What a firing actually took is measured
separately from its own record, and the two are deliberately never merged.
"""

AMBIENT_C = 20.0
FULL_POWER_RATE = 999.0


def ramp_minutes(rate, start_temperature, target_temperature):
    """Minutes to climb (or fall) to the target. Zero at full power."""
    if rate is None or rate <= 0.0 or rate >= FULL_POWER_RATE:
        return 0.0
    return 60.0 * abs(target_temperature - start_temperature) / rate


def schedule(segments, ambient=AMBIENT_C):
    """Walk segments in order, returning one dict of timings each.

    `segments` is any sequence of objects exposing `ramp_rate`,
    `target_temperature` and `soak_time` - Odoo records and provider dicts both
    qualify, via `_read`. Segments are used in the order given; the caller
    orders them.
    """
    start_temperature = ambient
    elapsed = 0.0
    rows = []
    for segment in segments:
        rate = _read(segment, "ramp_rate")
        target = _read(segment, "target_temperature")
        soak = _read(segment, "soak_time") or 0.0
        if target is None:
            target = start_temperature
        climb = ramp_minutes(rate, start_temperature, target)
        rows.append({
            "start_temperature": start_temperature,
            "target_temperature": target,
            "ramp_minutes": climb,
            "soak_minutes": soak,
            "start_minutes": elapsed,
            "end_minutes": elapsed + climb + soak,
        })
        elapsed += climb + soak
        start_temperature = target
    return rows


def total_minutes(segments, ambient=AMBIENT_C):
    rows = schedule(segments, ambient)
    return rows[-1]["end_minutes"] if rows else 0.0


def peak_temperature(segments):
    """The highest target the programme asks for, or None if it asks for none."""
    targets = [
        _read(segment, "target_temperature") for segment in segments]
    targets = [target for target in targets if target is not None]
    return max(targets) if targets else None


def _read(segment, key):
    """One field, from a dict or from anything with attributes."""
    value = segment.get(key) if isinstance(segment, dict) else getattr(
        segment, key, None)
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
