"""myKiln resources -> provider-neutral values for mb.kiln and mb.firing.

Kept apart from both the client and the models so it can be tested against
recorded fixtures with no network and no database, which is what the Increment 4
gate asks for: a replay-safe import proven without live credentials.
"""

from datetime import timedelta

from .mykiln_client import as_number, as_str, nested_id, parse_instant

FIRING_STATES = {"firing", "heating", "ramping", "soaking", "holding"}

# myKiln's vocabulary on the left, `mb.kiln`'s on the right. Anything the
# provider invents later lands on "other" rather than on an empty field, so an
# unknown value still says "we looked and it was not one of these".
CONFIGURATIONS = {"top_loader": "top_loader", "front_loader": "front_loader"}
HEATING_METHODS = {"electric": "electric", "gas": "gas"}


def temperature_units(value):
    return "Fahrenheit" if as_str(value).lower().startswith("f") else "Celsius"


def _mapped(value, table):
    text = as_str(value).strip().lower()
    if not text:
        return None
    return table.get(text, "other")


def index_kiln_types(kiln_types):
    """The model catalogue, keyed by (manufacturer, model number).

    Case-folded because the catalogue and the kiln record are separate strings
    typed by separate people. Duplicates are real - the live catalogue lists
    'TE 80 S' once per sales region, differing only in `location` - and they
    agree on everything this reads, so the first wins.
    """
    index = {}
    for row in kiln_types or []:
        key = (
            as_str(row.get("manufacturer")).strip().lower(),
            as_str(row.get("model_number")).strip().lower(),
        )
        if key != ("", "") and key not in index:
            index[key] = row
    return index


def kiln_specification(kiln, kiln_types_index=None):
    """The hardware facts on a kiln resource, plus what its model adds.

    Volume and maximum temperature come from the kiln itself and never from
    the catalogue: the same model is built to more than one specification, and
    the record the potter configured is the one that describes their machine.
    The catalogue only fills in what the kiln record does not carry - the
    series, how it loads, and the supply it is built for.
    """
    values = {
        "manufacturer": as_str(kiln.get("manufacturer")).strip() or None,
        "model_number": as_str(kiln.get("model_number")).strip() or None,
        "chamber_litres": as_number(kiln.get("volume")),
        "max_temperature": as_number(kiln.get("max_temperature")),
        "power_kw": as_number(kiln.get("power")),
        "zone_count": as_number(kiln.get("zones")),
        "heating_method": _mapped(kiln.get("heating_method"), HEATING_METHODS),
        "serial_number": as_str(kiln.get("serial_number")).strip() or None,
        "purchase_date": as_str(kiln.get("purchase_date")).strip() or None,
        "series": None,
        "configuration": None,
        "voltage": None,
        "phases": None,
    }
    row = (kiln_types_index or {}).get(
        ((values["manufacturer"] or "").lower(), (values["model_number"] or "").lower())
    )
    if row:
        values["series"] = as_str(row.get("series")).strip() or None
        values["configuration"] = _mapped(row.get("configuration"), CONFIGURATIONS)
        values["voltage"] = as_number(row.get("voltage"))
        values["phases"] = as_number(row.get("phases"))
        if not values["heating_method"]:
            values["heating_method"] = _mapped(row.get("heating_method"), HEATING_METHODS)
    return values


def normalize_program(detail):
    """One firing's controller programme, or None if it names no slot.

    The slot is what makes a programme identifiable across firings, so a
    firing that reports none cannot refresh anything and is skipped. Segments
    may legitimately be absent - a firing started before the app recorded
    them - and that is a programme with a slot and no profile, not a failure.
    """
    detail = detail or {}
    number = as_number(detail.get("program_number"))
    if number is None:
        return None
    program = detail.get("program")
    program = program if isinstance(program, dict) else {}
    raw_segments = program.get("segments")
    segments = []
    for index, segment in enumerate(raw_segments or [], start=1):
        if not isinstance(segment, dict):
            continue
        segments.append(
            {
                "number": int(as_number(segment.get("number")) or index),
                # Rates and targets are in the controller's own units, which for
                # segments is always Celsius on this API - the Fahrenheit setting
                # is a display preference on live readings, and the programme
                # endpoints do not honour it.
                "ramp_rate": as_number(segment.get("ramp_rate")) or 0.0,
                "target_temperature": as_number(segment.get("target_temperature")) or 0.0,
                "soak_time": as_number(segment.get("soak_time")) or 0.0,
            }
        )
    segments.sort(key=lambda row: row["number"])
    name = as_str(detail.get("library_program_name")).strip()
    return {
        "program_number": int(number),
        # The library name when the potter saved one, the slot otherwise -
        # the same label `normalize_firing` puts on the firing, so the two
        # match each other rather than needing a translation table.
        "name": name or "Programme %d" % int(number),
        "provider_program_id": (
            str(int(as_number(program.get("id"))))
            if as_number(program.get("id")) is not None
            else None
        ),
        "segments": segments,
        "fired_at": parse_instant(detail.get("start_date_time")),
    }


def to_celsius(value, units):
    number = as_number(value)
    if number is None:
        return None
    if units == "Fahrenheit":
        number = (number - 32.0) * 5.0 / 9.0
    return round(number, 2)


def normalize_kilns(kilns, controllers, kiln_types=None):
    """Join physical kilns to their controllers' live readings and to a model.

    `kiln_types` is the manufacturer's catalogue, optional because a caller
    that only wants live state should not have to fetch three hundred rows to
    get it.
    """
    index = index_kiln_types(kiln_types)
    by_id = {}
    for controller in controllers:
        identifier = as_number(controller.get("id"))
        if identifier is not None:
            by_id[identifier] = controller

    normalized = []
    for kiln in kilns:
        kiln_id = as_number(kiln.get("id"))
        if kiln_id is None:
            continue
        controller = by_id.get(nested_id(kiln, "controller")) or {}
        units = temperature_units(controller.get("temperature_units"))
        state = as_str(controller.get("controller_state")).lower()
        normalized.append(
            {
                "external_id": str(int(kiln_id)),
                "name": as_str(kiln.get("name")) or "MyKiln %d" % int(kiln_id),
                "specification": kiln_specification(kiln, index),
                "units": units,
                "connected": bool(controller.get("is_communicating")),
                "state": state,
                "is_firing": state in FIRING_STATES,
                "is_cooling": state == "cooling",
                "current_temperature": to_celsius(controller.get("temperature_1"), units),
                "target_temperature": to_celsius(controller.get("temperature_set_point"), units),
                "segment": as_number(controller.get("current_segment_number")),
            }
        )
    return normalized


def _state(ended_at, kiln_state):
    if ended_at:
        return "done"
    if (kiln_state or "").lower() == "cooling":
        return "cooling"
    return "firing"


def normalize_firing(detail, samples, units="Celsius", kiln_state=None):
    """One firing's detail plus its parallel sample arrays.

    Returns None rather than a partial record when identity is missing: a
    firing with no id or no start cannot be keyed, and an unkeyable record
    would be re-imported as a new one on every poll.

    `kiln_state` is the controller's live state, and it is what separates a
    firing still ramping from one that has finished heating and is cooling.
    myKiln has no cooling flag on the firing itself: the live account shows a
    firing with no end date whose kiln reports "cooling" and whose samples
    already peaked. Without this the record sits at "firing" until the
    provider finally closes it, and the cooling gate that decides when a load
    may be unloaded would never open.
    """
    detail = detail or {}
    samples = samples or {}
    firing_id = as_number(detail.get("id"))
    kiln_id = nested_id(detail, "kiln")
    started_at = parse_instant(detail.get("start_date_time"))
    if firing_id is None or kiln_id is None or started_at is None:
        return None

    ended_at = parse_instant(detail.get("end_date_time"))
    elapsed = samples.get("elapsed_seconds") or []
    temperatures = samples.get("temperature_1") or []
    setpoints = samples.get("temperature_setpoint") or []
    segments = samples.get("segment_number") or []

    points = []
    peak = None
    for index, seconds in enumerate(elapsed):
        offset = as_number(seconds)
        if offset is None:
            continue
        temperature = to_celsius(temperatures[index] if index < len(temperatures) else None, units)
        if temperature is not None and (peak is None or temperature > peak):
            peak = temperature
        points.append(
            {
                "elapsed_seconds": offset,
                "temperature_c": temperature,
                "setpoint_c": to_celsius(
                    setpoints[index] if index < len(setpoints) else None, units
                ),
                "segment": as_number(segments[index] if index < len(segments) else None),
            }
        )

    program_number = as_number(detail.get("program_number"))
    program = as_str(detail.get("library_program_name")).strip()
    if not program and program_number is not None:
        program = "Programme %d" % int(program_number)

    duration = None
    if ended_at:
        duration = int((ended_at - started_at).total_seconds())
    elif points:
        duration = int(points[-1]["elapsed_seconds"])

    return {
        "external_id": str(int(firing_id)),
        "kiln_external_id": str(int(kiln_id)),
        "title": as_str(detail.get("name")).strip() or None,
        "program": program or None,
        # The slot as well as the label, because the label is the part a
        # potter renames. Matching falls back to the slot when it no longer
        # says "Programme 4".
        "program_number": int(program_number) if program_number is not None else None,
        "state": _state(ended_at, kiln_state),
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": duration,
        "peak_temperature": peak,
        # When heating actually stopped, for a firing the provider has not
        # closed yet. The cooling hold is measured from here.
        "last_sample_at": (
            started_at + timedelta(seconds=points[-1]["elapsed_seconds"]) if points else None
        ),
        "curve": {"units": "Celsius", "points": points},
        # Verbatim, for diagnostics and for fields this model does not carry
        # yet. The client sends its token in a header, so nothing credential
        # shaped is in here - checked against the live service.
        "raw": {"detail": detail, "samples": samples},
        "sample_count": len(points),
    }
