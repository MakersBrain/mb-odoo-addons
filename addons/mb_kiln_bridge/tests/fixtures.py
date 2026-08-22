"""Recorded myKiln API v1 shapes. No credential appears here, by design.

Field names and value vocabulary are the live service's, captured on
7 August 2026: `volume` in litres, `max_temperature` in Celsius, `power` in kW,
`configuration` as `top_loader`, a segment as rate/target/soak. Serial numbers
and identifiers are invented; the shapes are not.

Kiln 41 is fully described and kiln 42 is deliberately sparse. A myKiln account
where the potter never filled the kiln in is an ordinary account, and a sync
that fell over on one - or wiped what somebody had typed here - would be a bug
found in the field rather than in this file.
"""

KILNS = [
    {
        "id": 41,
        "name": "Ecotop 80",
        "zones": 1,
        "control_method": "TC304",
        "controller": {"id": 77},
        "manufacturer": "Rohde",
        "model_number": "TE 80 S",
        "volume": 80,
        "power": 6.0,
        "max_temperature": 1320.0,
        "heating_method": "electric",
        "serial_number": "80275",
        "purchase_date": "2025-04-24",
    },
    {"id": 42, "name": "", "zones": 3, "controller": 78},
]

# ROHDE's model catalogue. The live one holds 315 rows and lists a model once
# per sales region, identical but for `location` - so the duplicate is here too.
KILN_TYPES = [
    {
        "id": 468,
        "manufacturer": "Rohde",
        "series": "TE-S",
        "model_number": "TE 80 S",
        "configuration": "top_loader",
        "heating_method": "electric",
        "location": "location_1_europe",
        "voltage": 400,
        "phases": 1,
    },
    {
        "id": 611,
        "manufacturer": "Rohde",
        "series": "TE-S",
        "model_number": "TE 80 S",
        "configuration": "top_loader",
        "heating_method": "electric",
        "location": "location_3_other",
        "voltage": 400,
        "phases": 1,
    },
    {
        "id": 486,
        "manufacturer": "Rohde",
        "series": "ELS-N",
        "model_number": "ELS 150 N",
        "configuration": "front_loader",
        "heating_method": "electric",
        "location": "location_1_europe",
        "voltage": 230,
        "phases": 1,
    },
]

CONTROLLERS = [
    {
        "id": 77,
        "is_communicating": True,
        "controller_state": "firing",
        "temperature_1": 1043.5,
        "temperature_set_point": 1240,
        "temperature_units": "Celsius",
        "current_segment_number": 3,
    },
    {
        "id": 78,
        "is_communicating": False,
        "controller_state": "idle",
        "temperature_1": 68,
        "temperature_set_point": None,
        "temperature_units": "Fahrenheit",
        "current_segment_number": None,
    },
]

# 100 deg/h from ambient to 1000, then a 90 minute hold. The second segment
# carries a rate of 1000, which the controller reads as full power rather than
# as a thousand degrees an hour, so it schedules as its hold alone:
#   (1000 - 20) / 100 * 60 = 588 minutes, + 90 = 678 = 11.3 hours.
BISQUE_PROGRAM = {
    "id": 289506,
    "event_relay_1_function": "unused",
    "event_relay_2_function": "unused",
    "segments": [
        {
            "id": 488992,
            "program_id": 289506,
            "number": 1,
            "ramp_rate": 100.0,
            "target_temperature": 1000.0,
            "soak_time": 0,
        },
        {
            "id": 488993,
            "program_id": 289506,
            "number": 2,
            "ramp_rate": 1000.0,
            "target_temperature": 1000.0,
            "soak_time": 90,
        },
    ],
}

# The same slot after the potter edited it: hotter, and held longer.
BISQUE_PROGRAM_REVISED = {
    "id": 293771,
    "event_relay_1_function": "unused",
    "event_relay_2_function": "unused",
    "segments": [
        {
            "id": 498147,
            "program_id": 293771,
            "number": 1,
            "ramp_rate": 150.0,
            "target_temperature": 1040.0,
            "soak_time": 30,
        },
        {
            "id": 498148,
            "program_id": 293771,
            "number": 2,
            "ramp_rate": 1000.0,
            "target_temperature": 1040.0,
            "soak_time": 120,
        },
    ],
}

# Slot 4, well over 1100, so it is inferred as a glaze rather than a bisque.
GLAZE_PROGRAM = {
    "id": 564200,
    "event_relay_1_function": "unused",
    "event_relay_2_function": "unused",
    "segments": [
        {
            "id": 1087713,
            "program_id": 564200,
            "number": 1,
            "ramp_rate": 150.0,
            "target_temperature": 900.0,
            "soak_time": 0,
        },
        {
            "id": 1087714,
            "program_id": 564200,
            "number": 2,
            "ramp_rate": 60.0,
            "target_temperature": 1230.0,
            "soak_time": 0,
        },
    ],
}

FIRING_DETAIL = {
    "id": 4417,
    "kiln": {"id": 41},
    "name": "Biscuit 12/04",
    "start_date_time": "2026-08-04T06:30:00Z",
    "end_date_time": "2026-08-04T18:30:00Z",
    "library_program_name": "Bisque 1000",
    "program_number": 3,
    "program": BISQUE_PROGRAM,
}

# The same slot, fired earlier, on the profile the potter has since revised.
# Live myKiln never names a programme - `library_program_name` is null on every
# firing, because the library the name would come from is empty.
FIRING_DETAIL_OLDER = {
    "id": 4416,
    "kiln": {"id": 41},
    "name": None,
    "start_date_time": "2026-07-30T06:00:00Z",
    "end_date_time": "2026-07-30T19:00:00Z",
    "library_program_name": None,
    "program_number": 3,
    "program": BISQUE_PROGRAM_REVISED,
}

FIRING_DETAIL_GLAZE = {
    "id": 4419,
    "kiln": {"id": 41},
    "name": None,
    "start_date_time": "2026-08-06T05:00:00Z",
    "end_date_time": "2026-08-06T20:00:00Z",
    "library_program_name": None,
    "program_number": 4,
    "program": GLAZE_PROGRAM,
}

FIRING_SAMPLES = {
    "elapsed_seconds": [0, 1800, 3600, 5400],
    "temperature_1": [22.0, 310.5, 705.0, 998.25],
    "temperature_setpoint": [20, 300, 700, 1000],
    "segment_number": [1, 1, 2, 3],
}

RUNNING_DETAIL = dict(FIRING_DETAIL, id=4418, end_date_time=None, name=None)
