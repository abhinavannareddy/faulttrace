"""Writes the four example vehicle configs (synthetic topologies, synthetic DTC codes)."""
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
          "hydraulics": "H20", "controls": "H30"}
# components that raise no diagnostic code of their own ("silent"): the diagnosis must infer them
SILENT = {"power_dist", "alternator", "fuel_rail", "wheel_speed_sensors", "body_ecu", "can_backbone", "air_dryer",
          "pump_controller", "main_valve", "joystick", "hvac_ecu", "door_ecu", "steering_ecu", "climate_ecu"}


def build(name, spec):
    comps = COMMON["components"] + spec["components"]
    edges = COMMON["edges"] + spec["edges"]
    dtcs, n = [], {}
    for cid, system in comps:
        if cid in SILENT:
            continue
        n[system] = n.get(system, 0) + 1
        dtcs.append({"code": f"{PREFIX[system]}{n[system]:02d}{len(dtcs) % 10}", "component": cid,
                     "description": f"{cid.replace('_', ' ')} fault or out-of-range"})
    return {"vehicle": name, "synthetic": True,
            "components": [{"id": c, "system": s} for c, s in comps],
            "edges": [{"from": a, "to": b, "p": 0.9} for a, b in edges],
            "dtcs": dtcs}


for name, spec in VEHICLES.items():
    (OUT / f"{name}.yaml").write_text(yaml.safe_dump(build(name, spec), sort_keys=False))
print("written", [p.name for p in OUT.iterdir()])
