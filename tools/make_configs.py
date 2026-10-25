"""Writes the four example vehicle configs (synthetic topologies; invented codes in the OBD-II format,
a letter P/C/B/U followed by four digits)."""
from pathlib import Path

import yaml

OUT = Path(__file__).resolve().parent.parent / "config" / "vehicles"

COMMON = {  # shared electrical and network backbone
    "components": [("battery", "power"), ("alternator", "power"), ("power_dist", "power"),
                   ("can_backbone", "network"), ("engine_ecu", "powertrain"), ("body_ecu", "body")],
    "edges": [("alternator", "battery"), ("battery", "power_dist"), ("power_dist", "engine_ecu"),
              ("power_dist", "can_backbone"), ("can_backbone", "body_ecu"), ("can_backbone", "engine_ecu")],
}

VEHICLES = {
    "truck": {
        "components": [("fuel_pump", "fuel"), ("fuel_rail", "fuel"), ("injectors", "fuel"), ("turbo", "air"),
                       ("maf_sensor", "air"), ("coolant_sensor", "cooling"), ("trans_ecu", "driveline"),
                       ("transmission", "driveline"), ("abs_ecu", "chassis"), ("brakes", "chassis"),
                       ("wheel_speed_sensors", "chassis"), ("aftertreatment", "emissions"), ("dashboard", "body"),
                       ("lighting", "body")],
        "edges": [("power_dist", "fuel_pump"), ("fuel_pump", "fuel_rail"), ("fuel_rail", "injectors"),
                  ("engine_ecu", "injectors"), ("engine_ecu", "turbo"), ("power_dist", "maf_sensor"),
                  ("power_dist", "coolant_sensor"), ("can_backbone", "trans_ecu"), ("trans_ecu", "transmission"),
                  ("can_backbone", "abs_ecu"), ("power_dist", "wheel_speed_sensors"), ("wheel_speed_sensors", "abs_ecu"),
                  ("abs_ecu", "brakes"), ("engine_ecu", "aftertreatment"), ("can_backbone", "dashboard"),
                  ("body_ecu", "lighting"), ("maf_sensor", "engine_ecu")],
    },
    "car": {
        "components": [("fuel_pump", "fuel"), ("injectors", "fuel"), ("throttle_body", "air"), ("o2_sensor", "emissions"),
                       ("ignition_coils", "ignition"), ("trans_ecu", "driveline"), ("gearbox", "driveline"),
                       ("abs_ecu", "chassis"), ("wheel_speed_sensors", "chassis"), ("steering_ecu", "chassis"),
                       ("power_steering", "chassis"), ("infotainment", "body"), ("climate_ecu", "body"),
                       ("hvac", "body")],
        "edges": [("power_dist", "fuel_pump"), ("fuel_pump", "injectors"), ("engine_ecu", "injectors"),
                  ("engine_ecu", "throttle_body"), ("o2_sensor", "engine_ecu"), ("power_dist", "o2_sensor"),
                  ("engine_ecu", "ignition_coils"), ("can_backbone", "trans_ecu"), ("trans_ecu", "gearbox"),
                  ("can_backbone", "abs_ecu"), ("power_dist", "wheel_speed_sensors"), ("wheel_speed_sensors", "abs_ecu"),
                  ("can_backbone", "steering_ecu"), ("steering_ecu", "power_steering"), ("can_backbone", "infotainment"),
                  ("body_ecu", "climate_ecu"), ("climate_ecu", "hvac")],
    },
    "bus": {
        "components": [("fuel_pump", "fuel"), ("injectors", "fuel"), ("air_compressor", "air"), ("air_dryer", "air"),
                       ("brake_circuit", "chassis"), ("abs_ecu", "chassis"), ("door_ecu", "body"), ("doors", "body"),
                       ("hvac_ecu", "body"), ("hvac", "body"), ("kneeling_valve", "chassis"), ("trans_ecu", "driveline"),
                       ("transmission", "driveline"), ("passenger_counter", "body"), ("display", "body")],
        "edges": [("power_dist", "fuel_pump"), ("fuel_pump", "injectors"), ("engine_ecu", "injectors"),
                  ("engine_ecu", "air_compressor"), ("air_compressor", "air_dryer"), ("air_dryer", "brake_circuit"),
                  ("air_dryer", "kneeling_valve"), ("can_backbone", "abs_ecu"), ("abs_ecu", "brake_circuit"),
                  ("body_ecu", "door_ecu"), ("door_ecu", "doors"), ("air_dryer", "doors"), ("body_ecu", "hvac_ecu"),
                  ("hvac_ecu", "hvac"), ("can_backbone", "trans_ecu"), ("trans_ecu", "transmission"),
                  ("can_backbone", "passenger_counter"), ("can_backbone", "display")],
    },
    "excavator": {
        "components": [("hydraulic_pump", "hydraulics"), ("pump_controller", "hydraulics"), ("main_valve", "hydraulics"),
                       ("boom_cylinder", "hydraulics"), ("arm_cylinder", "hydraulics"), ("swing_motor", "hydraulics"),
                       ("oil_cooler", "cooling"), ("oil_temp_sensor", "cooling"), ("pressure_sensor", "hydraulics"),
                       ("joystick_ecu", "controls"), ("joystick", "controls"), ("fuel_pump", "fuel"), ("injectors", "fuel"),
                       ("cab_display", "body")],
        "edges": [("engine_ecu", "hydraulic_pump"), ("can_backbone", "pump_controller"), ("pump_controller", "hydraulic_pump"),
                  ("hydraulic_pump", "main_valve"), ("main_valve", "boom_cylinder"), ("main_valve", "arm_cylinder"),
                  ("main_valve", "swing_motor"), ("oil_cooler", "oil_temp_sensor"), ("hydraulic_pump", "oil_cooler"),
                  ("power_dist", "pressure_sensor"), ("pressure_sensor", "pump_controller"),
                  ("can_backbone", "joystick_ecu"), ("joystick", "joystick_ecu"), ("joystick_ecu", "main_valve"),
                  ("power_dist", "fuel_pump"), ("fuel_pump", "injectors"), ("engine_ecu", "injectors"),
                  ("can_backbone", "cab_display")],
    },
}

PREFIX = {"power": "P05", "network": "U01", "powertrain": "P06", "body": "B10", "fuel": "P02", "air": "P01",
          "cooling": "P00", "driveline": "P07", "chassis": "C12", "emissions": "P04", "ignition": "P03",
          "hydraulics": "P25", "controls": "P26"}
# components that raise no diagnostic code of their own ("silent"): the diagnosis must infer them
SILENT = {"power_dist", "alternator", "fuel_rail", "wheel_speed_sensors", "body_ecu", "can_backbone", "air_dryer",
          "pump_controller", "main_valve", "joystick", "hvac_ecu", "door_ecu", "steering_ecu", "climate_ecu"}


# Example repair information per system: what to do first and roughly how long it takes. Illustrative
# numbers; a real deployment would take these from the service manual or the workshop system.
SERVICE = {
    "power": ("Measure supply voltage and ground drop under load; inspect fuses, terminals and connectors", 40),
    "network": ("Check bus termination and wiring resistance; look for a node that is holding the bus down", 60),
    "powertrain": ("Read freeze-frame data, check supply and ground, then reflash or replace the control unit", 45),
    "body": ("Check the module's supply, its connector and the fuse before replacing it", 25),
    "fuel": ("Test supply pressure and inspect lines, filter and electrical connector", 35),
    "air": ("Inspect the air path for leaks and the sensor connector; compare the reading with a reference", 30),
    "cooling": ("Compare the sensor reading with a reference thermometer; inspect connector and wiring", 20),
    "driveline": ("Check fluid level and condition, then the module connector and harness", 50),
    "chassis": ("Check sensor air gap, wiring and connector; test the signal with a scope", 35),
    "emissions": ("Inspect the sensor and exhaust for leaks; check heater and signal circuits", 40),
    "ignition": ("Test coil resistance and supply; check the plug and connector", 25),
    "hydraulics": ("Check pressure at the test port and inspect hoses and fittings for leaks", 55),
    "controls": ("Check the input device calibration, wiring and supply voltage", 30),
}


def service_for(system):
    action, minutes = SERVICE[system]
    return {"action": action, "minutes": minutes}


def build(name, spec, code_map=None):
    """`code_map` maps a component to (SPN, FMI) for the J1939 variant; components not in it are silent."""
    comps = COMMON["components"] + spec["components"]
    edges = COMMON["edges"] + spec["edges"]
    dtcs, n = [], {}
    for cid, system in comps:
        if cid in SILENT:
            continue
        if code_map is not None:
            if cid not in code_map:
                continue
            spn, fmi = code_map[cid]
            dtcs.append({"code": f"SPN{spn}-FMI{fmi}", "component": cid,
                         "description": f"SPN {spn} FMI {fmi} ({cid.replace('_', ' ')})"})
            continue
        n[system] = n.get(system, 0) + 1
        dtcs.append({"code": f"{PREFIX[system]}{n[system]:02d}", "component": cid,
                     "description": f"{cid.replace('_', ' ')} fault or out-of-range"})
    return {"vehicle": name, "synthetic": True,
            "components": [{"id": c, "system": s, "service": service_for(s)} for c, s in comps],
            "edges": [{"from": a, "to": b, "p": 0.9} for a, b in edges],
            "dtcs": dtcs}


# Heavy-duty truck reporting J1939 SPN/FMI pairs. The SPNs are real parameter numbers (checked against
# published J1939 parameter lists: 84 vehicle speed, 94 fuel delivery pressure, 102 intake manifold
# pressure, 110 coolant temperature, 132 intake air mass flow, 157 rail pressure, 168 battery potential,
# 177 transmission oil temperature, 521 brake pedal position, 563 ABS active, 639 J1939 network,
# 3216 aftertreatment intake NOx). Which component raises which pair, and the FMI chosen, is an
# illustration for this synthetic topology and must be replaced by the OEM's own mapping.
TRUCK_J1939 = {
    "battery": (168, 4), "engine_ecu": (639, 9), "fuel_pump": (94, 1), "injectors": (157, 18),
    "turbo": (102, 1), "maf_sensor": (132, 1), "coolant_sensor": (110, 3), "trans_ecu": (639, 2),
    "transmission": (177, 0), "abs_ecu": (563, 2), "brakes": (521, 13), "aftertreatment": (3216, 2),
    "dashboard": (84, 9),
}


for name, spec in VEHICLES.items():
    (OUT / f"{name}.yaml").write_text(yaml.safe_dump(build(name, spec), sort_keys=False))
(OUT / "truck_j1939.yaml").write_text(yaml.safe_dump(build("truck_j1939", VEHICLES["truck"], TRUCK_J1939), sort_keys=False))
print("written", [p.name for p in OUT.iterdir()])
