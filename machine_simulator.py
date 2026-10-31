"""
machine_simulator.py
--------------------
Generates SYNTHETIC machine readings for demonstration only.
No real factory machines or industrial sensors are connected.

The thresholds below are demonstration values, NOT validated
industrial safety limits.
"""

import random
from datetime import datetime

import pandas as pd

DEFAULT_TEMP_THRESHOLD = 82.0   # demo value
DEFAULT_VIB_THRESHOLD = 3.8     # demo value

# Each machine has a consistent identity and "normal" operating level.
MACHINE_PROFILES = {
    "M001": {"stage": "Cutting",       "temp": 72.0, "vib": 2.0, "pressure": 5.5, "units": 100},
    "M002": {"stage": "Assembly",      "temp": 70.0, "vib": 1.8, "pressure": 6.0, "units": 105},
    "M003": {"stage": "Quality Check", "temp": 66.0, "vib": 1.5, "pressure": 5.0, "units": 90},
    "M004": {"stage": "Packaging",     "temp": 68.0, "vib": 1.7, "pressure": 6.5, "units": 110},
}

# Simulation settings (all demonstration values)
FAULT_CHANCE = 0.03        # chance per reading that a "fault episode" starts
MAINTENANCE_CHANCE = 0.01  # chance per reading that maintenance starts
MAINTENANCE_TICKS = 6      # how many readings maintenance lasts


class MachineSimulator:
    """Keeps the state of every machine so values change gradually."""

    def __init__(self, profiles=None,
                 temp_threshold=DEFAULT_TEMP_THRESHOLD,
                 vib_threshold=DEFAULT_VIB_THRESHOLD):
        self.profiles = profiles or MACHINE_PROFILES
        self.temp_threshold = temp_threshold
        self.vib_threshold = vib_threshold
        self.state = {
            machine: {
                "temp": p["temp"],
                "vib": p["vib"],
                "pressure": p["pressure"],
                "fault_ticks": 0,
                "maint_ticks": 0,
            }
            for machine, p in self.profiles.items()
        }

    def _step(self, machine):
        """Move one machine forward by one reading."""
        p = self.profiles[machine]
        s = self.state[machine]

        # Possibly start maintenance or a fault episode
        if s["maint_ticks"] == 0 and random.random() < MAINTENANCE_CHANCE:
            s["maint_ticks"] = MAINTENANCE_TICKS
            s["fault_ticks"] = 0
        if (s["fault_ticks"] == 0 and s["maint_ticks"] == 0
                and random.random() < FAULT_CHANCE):
            s["fault_ticks"] = random.randint(5, 10)

        if s["maint_ticks"] > 0:
            # Machine is stopped: cools down, low vibration, no output
            s["maint_ticks"] -= 1
            s["temp"] += 0.35 * (35.0 - s["temp"]) + random.gauss(0, 0.3)
            s["vib"] += 0.35 * (0.3 - s["vib"]) + random.gauss(0, 0.03)
            s["pressure"] += 0.35 * (1.0 - s["pressure"]) + random.gauss(0, 0.05)
            units = 0
            maintenance = True
        else:
            maintenance = False
            if s["fault_ticks"] > 0:
                s["fault_ticks"] -= 1
                target_temp = p["temp"] + 16.0
                target_vib = p["vib"] + 2.3
            else:
                target_temp = p["temp"]
                target_vib = p["vib"]

            # Move part of the way towards the target, plus small noise
            s["temp"] += 0.25 * (target_temp - s["temp"]) + random.gauss(0, 0.8)
            s["vib"] += 0.25 * (target_vib - s["vib"]) + random.gauss(0, 0.12)
            s["pressure"] += 0.25 * (p["pressure"] - s["pressure"]) + random.gauss(0, 0.08)
            units = max(0, int(random.gauss(p["units"], 6)))

        s["temp"] = max(s["temp"], 0.0)
        s["vib"] = max(s["vib"], 0.0)
        s["pressure"] = max(s["pressure"], 0.0)

        if maintenance:
            status = "Maintenance"
        elif s["temp"] > self.temp_threshold or s["vib"] > self.vib_threshold:
            status = "Warning"
        else:
            status = "Running"

        return {
            "Machine": machine,
            "Timestamp": datetime.now().replace(microsecond=0),
            "Temperature": round(s["temp"], 2),
            "Vibration": round(s["vib"], 2),
            "Pressure": round(s["pressure"], 2),
            "Units Produced": units,   # units produced during this reading interval
            "Status": status,
        }

    def next_readings(self):
        """Return one new reading for every machine as a DataFrame."""
        rows = [self._step(machine) for machine in self.profiles]
        return pd.DataFrame(rows)


# Backward-compatible function (old code called this)
_default_simulator = MachineSimulator()


def generate_machine_data():
    return _default_simulator.next_readings()