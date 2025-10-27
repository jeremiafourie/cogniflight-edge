#!/usr/bin/env python3
"""
CogniFlight Flight Simulator
Simulates realistic flight scenarios for testing the CogniFlight edge system
"""

import os
import json
import time
import ssl
import random
import math
import argparse
from datetime import datetime
from typing import Dict, Any, List, Tuple
import paho.mqtt.client as mqtt

# MQTT Configuration (same as main.py)
DEFAULT_MQTT_BROKER = "cogniflight.exequtech.com"
DEFAULT_MQTT_PORT = 8883
DEFAULT_MQTT_USERNAME = "EdgeSimulator-1"
DEFAULT_MQTT_PASSWORD = "EdgeSimulator-1"
DEFAULT_MQTT_TOPIC = "cogniflight/telemetry"


def round_values(data: Dict[str, Any], decimals: int = 1) -> Dict[str, Any]:
    """Round all float values in dictionary to specified decimal places"""
    rounded = {}
    for key, value in data.items():
        if isinstance(value, float):
            rounded[key] = round(value, decimals)
        else:
            rounded[key] = value
    return rounded


def get_altitude_temp_pressure(altitude_ft: float) -> Tuple[float, float]:
    """Calculate temperature and pressure at given altitude using standard atmosphere"""
    # ISA standard: 15°C at sea level, -2°C per 1000 ft
    sea_level_temp = random.uniform(18, 22)
    temperature = sea_level_temp - (altitude_ft / 1000.0) * 1.98

    # Barometric pressure decreases exponentially with altitude
    pressure = 1013.25 * math.pow((1 - altitude_ft * 0.00002255), 5.255)

    return temperature, pressure


def calculate_g_forces(pitch: float, roll: float, climb_rate: float, turning: bool) -> Tuple[float, float, float]:
    """Calculate realistic G-forces based on aircraft attitude and movement"""
    # Base gravity vector
    g_base = 9.81

    # Vertical G-force (affected by climb/descent and turns)
    if turning:
        # Load factor in turn: 1/cos(bank_angle)
        gz = -g_base * (1 / max(0.1, math.cos(math.radians(roll))))
    else:
        gz = -g_base + (climb_rate * 0.0001)  # Minor variation from climb

    # Lateral G-force (from banking)
    gy = -math.sin(math.radians(roll)) * g_base * 0.5

    # Longitudinal G-force (from pitch changes)
    gx = math.sin(math.radians(pitch)) * g_base * 0.3

    # Add small vibrations
    gx += random.uniform(-0.2, 0.2)
    gy += random.uniform(-0.2, 0.2)
    gz += random.uniform(-0.3, 0.3)

    return gx, gy, gz


class FlightScenario:
    """Base class for flight scenarios with realistic sensor data generation"""

    def __init__(self, name: str, pilot_username: str, flight_id: str, duration_seconds: int):
        self.name = name
        self.pilot_username = pilot_username
        self.flight_id = flight_id
        self.duration_seconds = duration_seconds
        self.elapsed_time = 0

        # Aircraft state (persistent across updates)
        self.heading = random.uniform(0, 360)
        self.altitude = 0
        self.airspeed = 0
        self.climb_rate = 0
        self.roll = 0
        self.pitch = 0

        # Pilot state
        self.base_hr = random.uniform(68, 78)
        self.current_hr = self.base_hr
        self.base_ear = random.uniform(0.34, 0.38)
        self.stress_level = 0.1
        self.fatigue_level = 0.0

    def smooth_transition(self, current: float, target: float, rate: float = 0.1) -> float:
        """Smoothly transition between values"""
        return current + (target - current) * rate

    def generate_data(self) -> Dict[str, Any]:
        """Generate telemetry data for current scenario state. Override in subclasses."""
        raise NotImplementedError

    def update(self, delta_time: float):
        """Update scenario state. Override in subclasses."""
        self.elapsed_time += delta_time

        # Smooth heart rate changes
        self.current_hr = self.smooth_transition(self.current_hr, self.base_hr + (self.stress_level * 30), 0.05)

    def is_complete(self) -> bool:
        """Check if scenario is complete"""
        return self.elapsed_time >= self.duration_seconds


class PatternWorkScenario(FlightScenario):
    """Training flight with multiple touch-and-go landings"""

    def __init__(self, pilot_username: str, flight_id: str, duration_seconds: int = 420):
        super().__init__("Pattern Work Training", pilot_username, flight_id, duration_seconds)
        self.pattern_count = 0
        self.pattern_phase = "taxi"
        self.pattern_timer = 0
        self.wind_speed = random.uniform(5, 15)
        self.wind_direction = random.uniform(0, 360)

    def update(self, delta_time: float):
        super().update(delta_time)
        self.pattern_timer += delta_time

        # Each pattern takes about 90 seconds
        pattern_duration = 90
        patterns_complete = int(self.elapsed_time / pattern_duration)
        phase_in_pattern = (self.elapsed_time % pattern_duration) / pattern_duration

        if patterns_complete >= 4:
            # Final landing
            self.pattern_phase = "final_landing"
            self.altitude = max(0, self.altitude - delta_time * 50)
            self.airspeed = max(0, 65 - self.altitude * 0.01)
        else:
            if phase_in_pattern < 0.15:  # Takeoff
                self.pattern_phase = "takeoff"
                self.altitude = min(500, phase_in_pattern / 0.15 * 500)
                self.airspeed = 55 + phase_in_pattern / 0.15 * 20
                self.climb_rate = 700
                self.pitch = 12
                self.stress_level = 0.4
            elif phase_in_pattern < 0.35:  # Crosswind
                self.pattern_phase = "crosswind"
                self.altitude = 500 + (phase_in_pattern - 0.15) / 0.20 * 300
                self.airspeed = 75
                self.climb_rate = 300
                self.pitch = 5
                self.roll = 25
                self.heading = self.smooth_transition(self.heading, self.heading + 90, 0.1)
                self.stress_level = 0.2
            elif phase_in_pattern < 0.55:  # Downwind
                self.pattern_phase = "downwind"
                self.altitude = 800 + random.uniform(-20, 20)
                self.airspeed = 80
                self.climb_rate = 0
                self.pitch = 2
                self.roll = 0
                self.stress_level = 0.1
            elif phase_in_pattern < 0.75:  # Base
                self.pattern_phase = "base"
                self.altitude = 800 - (phase_in_pattern - 0.55) / 0.20 * 300
                self.airspeed = 70
                self.climb_rate = -400
                self.pitch = -2
                self.roll = -20
                self.heading = self.smooth_transition(self.heading, self.heading + 90, 0.1)
                self.stress_level = 0.3
            else:  # Final
                self.pattern_phase = "final"
                self.altitude = max(0, 500 - (phase_in_pattern - 0.75) / 0.25 * 500)
                self.airspeed = 65 - (phase_in_pattern - 0.75) / 0.25 * 10
                self.climb_rate = -500
                self.pitch = -3
                self.roll = random.uniform(-5, 5)  # Crosswind corrections
                self.stress_level = 0.5

                # Touch and go decision
                if self.altitude < 10:
                    self.pattern_count += 1

    def generate_data(self) -> Dict[str, Any]:
        temp, pressure = get_altitude_temp_pressure(self.altitude)
        gx, gy, gz = calculate_g_forces(self.pitch, self.roll, self.climb_rate, self.roll != 0)

        # Student pilot shows higher stress and variable performance
        ear_adjustment = -0.02 if self.stress_level > 0.3 else 0

        return round_values({
            "temperature": temp,
            "humidity": random.uniform(45, 60),
            "pressure": pressure,
            "altitude": self.altitude,

            "accel_x": gx,
            "accel_y": gy,
            "accel_z": gz,
            "gyro_x": random.uniform(-0.02, 0.02) if self.roll != 0 else random.uniform(-0.005, 0.005),
            "gyro_y": random.uniform(-0.01, 0.01),
            "gyro_z": random.uniform(-0.02, 0.02) if abs(self.roll) > 10 else random.uniform(-0.005, 0.005),
            "mag_x": math.sin(math.radians(self.heading)) * 0.5,
            "mag_y": math.cos(math.radians(self.heading)) * 0.5,
            "mag_z": -0.8,
            "roll": self.roll + random.uniform(-2, 2),
            "pitch": self.pitch + random.uniform(-1, 1),
            "yaw": self.heading,

            "heart_rate": self.current_hr + random.uniform(-3, 3),
            "rr_interval": 60.0 / self.current_hr,
            "baseline_deviation": 0.015 + self.stress_level * 0.04,
            "rmssd": 60 - self.stress_level * 15,
            "hr_trend": self.stress_level * 5,
            "stress_index": 0.06 + self.stress_level * 0.15,

            "avg_ear": self.base_ear + ear_adjustment + random.uniform(-0.02, 0.02),
            "mar": random.uniform(0.26, 0.32),
            "eyes_closed": False,
            "closure_duration": 0.0,
            "microsleep_count": 0.0,
            "blink_rate": 15 + self.stress_level * 20,
            "yawning": False,
            "yawn_count": 0.0,
            "yawn_duration": 0.0,

            "fusion_score": 0.08 + self.stress_level * 0.2,
            "confidence": 0.93 + random.uniform(0, 0.07),

            "system_state": "monitoring_active",
            "state_message": f"{self.pattern_phase.upper()} P{self.pattern_count}\n{self.base_ear + ear_adjustment:.2f} 0 {int(self.current_hr)} {int(self.airspeed)}kt",

            "pilot_username": self.pilot_username,
            "flight_id": self.flight_id,
            "collection_time": time.time(),
            "predictor_version": "1.0.0",
        })


class MountainFlyingScenario(FlightScenario):
    """Flying through mountain passes with updrafts and downdrafts"""

    def __init__(self, pilot_username: str, flight_id: str, duration_seconds: int = 360):
        super().__init__("Mountain Flying", pilot_username, flight_id, duration_seconds)
        self.terrain_height = 0
        self.in_turbulence = False
        self.updraft = 0

    def update(self, delta_time: float):
        super().update(delta_time)
        progress = self.elapsed_time / self.duration_seconds

        # Terrain profile - mountain passes
        if progress < 0.15:
            # Initial climb
            self.altitude = progress / 0.15 * 8500
            self.terrain_height = 0
            self.airspeed = 90
            self.climb_rate = 500
        elif progress < 0.35:
            # First mountain pass
            pass_progress = (progress - 0.15) / 0.20
            self.terrain_height = 6000 + math.sin(pass_progress * math.pi) * 2000
            self.altitude = self.terrain_height + 2000 + random.uniform(-200, 200)

            # Mountain wave turbulence
            self.updraft = math.sin(pass_progress * math.pi * 4) * 800
            self.altitude += self.updraft * delta_time * 0.01
            self.in_turbulence = abs(self.updraft) > 400
            self.airspeed = 85 + random.uniform(-10, 10)
        elif progress < 0.65:
            # Valley between mountains
            self.terrain_height = 4000 + random.uniform(-500, 500)
            self.altitude = 7500 + random.uniform(-300, 300)
            self.updraft = random.uniform(-200, 200)
            self.in_turbulence = False
            self.airspeed = 95
        elif progress < 0.85:
            # Second mountain pass (higher)
            pass_progress = (progress - 0.65) / 0.20
            self.terrain_height = 7000 + math.sin(pass_progress * math.pi) * 3000
            self.altitude = self.terrain_height + 1500 + random.uniform(-300, 300)

            # Severe mountain wave
            self.updraft = math.sin(pass_progress * math.pi * 6) * 1200
            self.altitude += self.updraft * delta_time * 0.01
            self.in_turbulence = True
            self.airspeed = 80 + random.uniform(-15, 15)
        else:
            # Descent to landing
            descent_progress = (progress - 0.85) / 0.15
            self.altitude = max(0, 10000 - descent_progress * 10000)
            self.terrain_height = max(0, 2000 - descent_progress * 2000)
            self.in_turbulence = False
            self.airspeed = 90 - descent_progress * 25

        # Stress from terrain proximity
        terrain_clearance = self.altitude - self.terrain_height
        if terrain_clearance < 1000:
            self.stress_level = 0.7
        elif terrain_clearance < 2000:
            self.stress_level = 0.4
        else:
            self.stress_level = 0.2

        if self.in_turbulence:
            self.stress_level = min(1.0, self.stress_level + 0.3)

        # Dynamic aircraft attitude
        self.pitch = 5 + self.updraft * 0.01 + random.uniform(-3, 3)
        self.roll = random.uniform(-30, 30) if self.in_turbulence else random.uniform(-5, 5)
        self.climb_rate = self.updraft + random.uniform(-100, 100)

    def generate_data(self) -> Dict[str, Any]:
        temp, pressure = get_altitude_temp_pressure(self.altitude)

        # Mountain effects on temperature
        if self.terrain_height > 5000:
            temp -= random.uniform(3, 8)

        gx, gy, gz = calculate_g_forces(self.pitch, self.roll, self.climb_rate, self.in_turbulence)

        # Add turbulence effects
        if self.in_turbulence:
            gx += random.uniform(-2, 2)
            gy += random.uniform(-2, 2)
            gz += random.uniform(-3, 3)

        return round_values({
            "temperature": temp,
            "humidity": random.uniform(25, 40),  # Dry mountain air
            "pressure": pressure,
            "altitude": self.altitude,

            "accel_x": gx,
            "accel_y": gy,
            "accel_z": gz,
            "gyro_x": random.uniform(-0.1, 0.1) if self.in_turbulence else random.uniform(-0.01, 0.01),
            "gyro_y": random.uniform(-0.1, 0.1) if self.in_turbulence else random.uniform(-0.01, 0.01),
            "gyro_z": random.uniform(-0.05, 0.05) if self.in_turbulence else random.uniform(-0.005, 0.005),
            "mag_x": math.sin(math.radians(self.heading)) * 0.5,
            "mag_y": math.cos(math.radians(self.heading)) * 0.5,
            "mag_z": -0.8,
            "roll": self.roll,
            "pitch": self.pitch,
            "yaw": self.heading + random.uniform(-10, 10) if self.in_turbulence else self.heading,

            "heart_rate": self.current_hr + random.uniform(-4, 4),
            "rr_interval": 60.0 / self.current_hr,
            "baseline_deviation": 0.02 + self.stress_level * 0.08,
            "rmssd": 55 - self.stress_level * 20,
            "hr_trend": self.stress_level * 8,
            "stress_index": 0.08 + self.stress_level * 0.25,

            "avg_ear": self.base_ear + 0.02,  # Wide-eyed attention
            "mar": random.uniform(0.25, 0.30),
            "eyes_closed": False,
            "closure_duration": 0.0,
            "microsleep_count": 0.0,
            "blink_rate": 18 + self.stress_level * 15,
            "yawning": False,
            "yawn_count": 0.0,
            "yawn_duration": 0.0,

            "fusion_score": 0.10 + self.stress_level * 0.3,
            "confidence": 0.90 + random.uniform(0, 0.10),

            "system_state": "alert" if self.stress_level > 0.6 else "monitoring_active",
            "state_message": f"{'TERRAIN!' if self.altitude - self.terrain_height < 1000 else 'Mountain wave'}\n{self.base_ear:.2f} 0 {int(self.current_hr)} CLR:{int(self.altitude - self.terrain_height)}ft",

            "pilot_username": self.pilot_username,
            "flight_id": self.flight_id,
            "collection_time": time.time(),
            "predictor_version": "1.0.0",
        })


class LongHaulFatigueScenario(FlightScenario):
    """8-hour overnight flight with circadian rhythm effects"""

    def __init__(self, pilot_username: str, flight_id: str, duration_seconds: int = 600):
        super().__init__("Long Haul Overnight", pilot_username, flight_id, duration_seconds)
        self.cruise_altitude = 35000
        self.circadian_low = False
        self.microsleep_count = 0
        self.yawn_count = 0
        self.last_microsleep = -30
        self.last_yawn = -20
        self.coffee_effect = 0

    def update(self, delta_time: float):
        super().update(delta_time)
        progress = self.elapsed_time / self.duration_seconds

        # Flight phases
        if progress < 0.08:
            # Climb
            self.altitude = progress / 0.08 * self.cruise_altitude
            self.airspeed = 250 + progress / 0.08 * 220
            self.climb_rate = 2000
            self.pitch = 8
            self.fatigue_level = 0.1
        elif progress < 0.92:
            # Long cruise
            self.altitude = self.cruise_altitude + random.uniform(-500, 500)
            self.airspeed = 470 + random.uniform(-10, 10)
            self.climb_rate = 0
            self.pitch = 2.5

            # Circadian rhythm - worst between 2-6 AM (simulated as 30-60% of cruise)
            cruise_progress = (progress - 0.08) / 0.84
            if cruise_progress > 0.3 and cruise_progress < 0.6:
                self.circadian_low = True
                self.fatigue_level = 0.4 + abs(math.sin((cruise_progress - 0.3) * math.pi / 0.3)) * 0.5
            else:
                self.circadian_low = False
                self.fatigue_level = 0.2 + cruise_progress * 0.3

            # Coffee boost (temporary alertness)
            if cruise_progress > 0.25 and cruise_progress < 0.35:
                self.coffee_effect = 0.3
            elif cruise_progress > 0.55 and cruise_progress < 0.65:
                self.coffee_effect = 0.25
            else:
                self.coffee_effect = max(0, self.coffee_effect - delta_time * 0.01)

            self.fatigue_level = max(0.1, self.fatigue_level - self.coffee_effect)
        else:
            # Descent
            descent_progress = (progress - 0.92) / 0.08
            self.altitude = self.cruise_altitude * (1 - descent_progress)
            self.airspeed = 470 - descent_progress * 200
            self.climb_rate = -1800
            self.pitch = -2
            self.fatigue_level = max(0.2, self.fatigue_level - 0.2)  # Wake up for landing

        # Heading changes (following airways)
        if int(self.elapsed_time / 120) != int((self.elapsed_time - delta_time) / 120):
            self.heading = (self.heading + random.uniform(-30, 30)) % 360

        self.stress_level = 0.1 + self.fatigue_level * 0.2

        # Reduce base heart rate with fatigue
        self.base_hr = 68 - self.fatigue_level * 10

    def generate_data(self) -> Dict[str, Any]:
        temp, pressure = get_altitude_temp_pressure(self.altitude)
        gx, gy, gz = calculate_g_forces(self.pitch, self.roll, self.climb_rate, False)

        # Microsleeps during circadian low
        microsleep = False
        if self.circadian_low and self.fatigue_level > 0.7 and random.random() < 0.05:
            if self.elapsed_time - self.last_microsleep > 20:
                microsleep = True
                self.microsleep_count += 1
                self.last_microsleep = self.elapsed_time

        # Yawning
        yawning = False
        if self.fatigue_level > 0.3 and random.random() < 0.08:
            if self.elapsed_time - self.last_yawn > 15:
                yawning = True
                self.yawn_count += 1
                self.last_yawn = self.elapsed_time

        # EAR drops significantly with fatigue
        current_ear = self.base_ear - self.fatigue_level * 0.15
        if microsleep:
            current_ear = random.uniform(0.10, 0.15)

        return round_values({
            "temperature": temp,
            "humidity": random.uniform(10, 25),  # Very dry at altitude
            "pressure": pressure,
            "altitude": self.altitude,

            "accel_x": gx,
            "accel_y": gy,
            "accel_z": gz,
            "gyro_x": random.uniform(-0.002, 0.002),
            "gyro_y": random.uniform(-0.002, 0.002),
            "gyro_z": random.uniform(-0.002, 0.002),
            "mag_x": math.sin(math.radians(self.heading)) * 0.5,
            "mag_y": math.cos(math.radians(self.heading)) * 0.5,
            "mag_z": -0.8,
            "roll": self.roll + random.uniform(-2, 2),
            "pitch": self.pitch + random.uniform(-0.5, 0.5),
            "yaw": self.heading,

            "heart_rate": self.current_hr + random.uniform(-2, 2),
            "rr_interval": 60.0 / max(50, self.current_hr),
            "baseline_deviation": 0.025 + self.fatigue_level * 0.06,
            "rmssd": 45 - self.fatigue_level * 15,
            "hr_trend": -self.fatigue_level * 6,
            "stress_index": 0.05 + self.fatigue_level * 0.05,

            "avg_ear": current_ear + random.uniform(-0.01, 0.01),
            "mar": 0.30 if not yawning else 0.48,
            "eyes_closed": microsleep,
            "closure_duration": random.uniform(1.0, 3.0) if microsleep else 0.0,
            "microsleep_count": float(self.microsleep_count),
            "blink_rate": 10 + self.fatigue_level * 8,
            "yawning": yawning,
            "yawn_count": float(self.yawn_count),
            "yawn_duration": random.uniform(2.5, 4.0) if yawning else 0.0,

            "fusion_score": 0.15 + self.fatigue_level * 0.7 + (0.3 if microsleep else 0),
            "confidence": 0.88 + (0.12 * (1 - self.fatigue_level)),

            "system_state": "critical" if microsleep else ("alert" if self.fatigue_level > 0.75 else ("warning" if self.fatigue_level > 0.5 else "monitoring_active")),
            "state_message": f"{'MICROSLEEP!' if microsleep else ('Circadian LOW' if self.circadian_low else 'Cruise')}\n{current_ear:.2f} {self.microsleep_count} {int(self.current_hr)} FL{int(self.altitude/100)}",

            "pilot_username": self.pilot_username,
            "flight_id": self.flight_id,
            "collection_time": time.time(),
            "predictor_version": "1.0.0",
        })


class MedicalEmergencyScenario(FlightScenario):
    """Pilot experiences hypoxia at altitude"""

    def __init__(self, pilot_username: str, flight_id: str, duration_seconds: int = 300):
        super().__init__("Medical Emergency - Hypoxia", pilot_username, flight_id, duration_seconds)
        self.hypoxia_onset = False
        self.hypoxia_level = 0
        self.confusion_level = 0
        self.oxygen_restored = False

    def update(self, delta_time: float):
        super().update(delta_time)
        progress = self.elapsed_time / self.duration_seconds

        if progress < 0.15:
            # Normal climb
            self.altitude = progress / 0.15 * 12000
            self.airspeed = 120
            self.hypoxia_onset = False
        elif progress < 0.40:
            # Continue climb - hypoxia begins
            climb_progress = (progress - 0.15) / 0.25
            self.altitude = 12000 + climb_progress * 3000
            self.airspeed = 110

            # Gradual hypoxia onset above 12,500 ft
            if self.altitude > 12500:
                self.hypoxia_onset = True
                self.hypoxia_level = min(1.0, (self.altitude - 12500) / 2500 * 0.8)
                self.confusion_level = self.hypoxia_level * 0.7
        elif progress < 0.60:
            # Hypoxia worsens - erratic behavior
            self.altitude = 15000 + random.uniform(-500, 500)
            self.airspeed = 105 + random.uniform(-15, 15)
            self.hypoxia_level = min(1.0, self.hypoxia_level + delta_time * 0.01)
            self.confusion_level = min(1.0, self.confusion_level + delta_time * 0.015)

            # Erratic control inputs
            self.pitch = random.uniform(-5, 10)
            self.roll = random.uniform(-35, 35)
            self.heading = (self.heading + random.uniform(-5, 5)) % 360
        elif progress < 0.65:
            # Oxygen restored / descent initiated
            self.oxygen_restored = True
            self.altitude = max(10000, self.altitude - delta_time * 100)
            self.hypoxia_level = max(0, self.hypoxia_level - delta_time * 0.05)
            self.confusion_level = max(0, self.confusion_level - delta_time * 0.04)
        else:
            # Recovery and safe descent
            descent_progress = (progress - 0.65) / 0.35
            self.altitude = max(0, 10000 - descent_progress * 10000)
            self.airspeed = 100
            self.hypoxia_level = 0
            self.confusion_level = 0
            self.pitch = -3
            self.roll = 0

        # Physiological effects
        if self.hypoxia_onset:
            # Increased heart rate (body trying to compensate)
            self.base_hr = 75 + self.hypoxia_level * 25
            # But paradoxically feeling euphoric/calm
            self.stress_level = max(0.1, 0.3 - self.hypoxia_level * 0.2)
        else:
            self.base_hr = 72
            self.stress_level = 0.2

    def generate_data(self) -> Dict[str, Any]:
        temp, pressure = get_altitude_temp_pressure(self.altitude)
        gx, gy, gz = calculate_g_forces(self.pitch, self.roll, self.climb_rate, abs(self.roll) > 10)

        # Hypoxia affects vision (tunnel vision, dimming)
        if self.hypoxia_onset:
            ear_mod = -self.hypoxia_level * 0.08  # Eyes appear drowsy
            blink_rate = 8 - self.hypoxia_level * 3  # Reduced blinking
        else:
            ear_mod = 0
            blink_rate = 16

        # Confusion causes poor fusion scores
        fusion_adjust = self.confusion_level * 0.6

        return round_values({
            "temperature": temp,
            "humidity": random.uniform(30, 45),
            "pressure": pressure,
            "altitude": self.altitude,

            "accel_x": gx + (random.uniform(-1, 1) if self.confusion_level > 0.5 else 0),
            "accel_y": gy + (random.uniform(-1, 1) if self.confusion_level > 0.5 else 0),
            "accel_z": gz,
            "gyro_x": random.uniform(-0.05, 0.05) if self.confusion_level > 0.3 else random.uniform(-0.01, 0.01),
            "gyro_y": random.uniform(-0.05, 0.05) if self.confusion_level > 0.3 else random.uniform(-0.01, 0.01),
            "gyro_z": random.uniform(-0.03, 0.03) if self.confusion_level > 0.3 else random.uniform(-0.005, 0.005),
            "mag_x": math.sin(math.radians(self.heading)) * 0.5,
            "mag_y": math.cos(math.radians(self.heading)) * 0.5,
            "mag_z": -0.8,
            "roll": self.roll + random.uniform(-5, 5) if self.confusion_level > 0 else self.roll,
            "pitch": self.pitch + random.uniform(-3, 3) if self.confusion_level > 0 else self.pitch,
            "yaw": self.heading,

            "heart_rate": self.current_hr + random.uniform(-3, 3),
            "rr_interval": 60.0 / max(50, self.current_hr),
            "baseline_deviation": 0.03 + self.hypoxia_level * 0.10,
            "rmssd": 50 - self.hypoxia_level * 30,
            "hr_trend": self.hypoxia_level * 10,
            "stress_index": 0.15 + self.hypoxia_level * 0.35,

            "avg_ear": self.base_ear + ear_mod + random.uniform(-0.01, 0.01),
            "mar": random.uniform(0.26, 0.32),
            "eyes_closed": False,
            "closure_duration": 0.0,
            "microsleep_count": 0.0,
            "blink_rate": blink_rate + random.uniform(-2, 2),
            "yawning": False,
            "yawn_count": 0.0,
            "yawn_duration": 0.0,

            "fusion_score": 0.20 + fusion_adjust,
            "confidence": 0.85 - self.confusion_level * 0.3,

            "system_state": "critical" if self.hypoxia_level > 0.7 else ("alert" if self.hypoxia_level > 0.3 else "monitoring_active"),
            "state_message": f"{'HYPOXIA!' if self.hypoxia_onset and not self.oxygen_restored else ('O2 RESTORED' if self.oxygen_restored else 'Normal')}\n{self.base_ear + ear_mod:.2f} 0 {int(self.current_hr)} SPO2:{int(98 - self.hypoxia_level * 25)}%",

            "pilot_username": self.pilot_username,
            "flight_id": self.flight_id,
            "collection_time": time.time(),
            "predictor_version": "1.0.0",
        })


class AerobaticScenario(FlightScenario):
    """Aerobatic routine with high G maneuvers"""

    def __init__(self, pilot_username: str, flight_id: str, duration_seconds: int = 240):
        super().__init__("Aerobatic Routine", pilot_username, flight_id, duration_seconds)
        self.maneuver = "level"
        self.g_load = 1.0
        self.maneuver_count = 0

    def update(self, delta_time: float):
        super().update(delta_time)

        # Sequence of aerobatic maneuvers
        sequence_time = self.elapsed_time % 40  # 40-second sequence

        if sequence_time < 5:
            self.maneuver = "setup"
            self.altitude = 3000 + random.uniform(-50, 50)
            self.airspeed = 140
            self.pitch = 0
            self.roll = 0
            self.g_load = 1.0
            self.stress_level = 0.3
        elif sequence_time < 10:
            # Loop
            self.maneuver = "loop"
            loop_progress = (sequence_time - 5) / 5
            self.pitch = 360 * loop_progress
            self.altitude = 3000 + math.sin(loop_progress * math.pi * 2) * 500
            self.airspeed = 140 - math.cos(loop_progress * math.pi * 2) * 40
            self.g_load = 1 + math.sin(loop_progress * math.pi * 2) * 3.5  # Up to 4.5G
            self.stress_level = 0.6
        elif sequence_time < 15:
            # Barrel roll
            self.maneuver = "barrel_roll"
            roll_progress = (sequence_time - 10) / 5
            self.roll = 360 * roll_progress
            self.altitude = 3000 + math.sin(roll_progress * math.pi * 2) * 200
            self.pitch = math.sin(roll_progress * math.pi * 4) * 15
            self.g_load = 1 + math.sin(roll_progress * math.pi * 2) * 2
            self.stress_level = 0.5
        elif sequence_time < 20:
            # Hammerhead
            self.maneuver = "hammerhead"
            hammer_progress = (sequence_time - 15) / 5
            if hammer_progress < 0.4:
                # Vertical climb
                self.pitch = 90
                self.altitude = 3000 + hammer_progress / 0.4 * 800
                self.airspeed = 140 * (1 - hammer_progress / 0.4)
                self.g_load = 3.5
            else:
                # Pivot and dive
                self.pitch = 90 - (hammer_progress - 0.4) / 0.6 * 180
                self.altitude = 3800 - (hammer_progress - 0.4) / 0.6 * 800
                self.airspeed = (hammer_progress - 0.4) / 0.6 * 140
                self.g_load = -1.0  # Negative G
                self.heading = (self.heading + 180) % 360
            self.stress_level = 0.7
        elif sequence_time < 25:
            # Cuban Eight
            self.maneuver = "cuban_eight"
            cuban_progress = (sequence_time - 20) / 5
            self.pitch = 45 * math.sin(cuban_progress * math.pi * 4)
            self.roll = 180 * math.sin(cuban_progress * math.pi * 2)
            self.altitude = 3000 + math.sin(cuban_progress * math.pi * 2) * 300
            self.g_load = 1 + abs(math.sin(cuban_progress * math.pi * 4)) * 2.5
            self.stress_level = 0.6
        elif sequence_time < 30:
            # Inverted flight
            self.maneuver = "inverted"
            self.roll = 180
            self.pitch = -2
            self.altitude = 3000
            self.airspeed = 130
            self.g_load = -1.0
            self.stress_level = 0.5
        else:
            # Recovery
            self.maneuver = "recovery"
            self.roll = 0
            self.pitch = 0
            self.altitude = 3000
            self.airspeed = 120
            self.g_load = 1.0
            self.stress_level = 0.2
            self.maneuver_count += 1

        # High G effects on heart rate
        self.base_hr = 75 + abs(self.g_load - 1) * 15

    def generate_data(self) -> Dict[str, Any]:
        temp, pressure = get_altitude_temp_pressure(self.altitude)

        # G-forces from maneuver
        gz = -9.81 * self.g_load
        gy = random.uniform(-2, 2) if abs(self.roll) > 45 else random.uniform(-0.5, 0.5)
        gx = random.uniform(-1, 1)

        # High G effects on vision (greyout/redout)
        if self.g_load > 3.5:
            ear_effect = -0.05  # Slight droop from G
        elif self.g_load < -0.5:
            ear_effect = 0.03  # Wide eyes from negative G
        else:
            ear_effect = 0

        return round_values({
            "temperature": temp,
            "humidity": random.uniform(40, 55),
            "pressure": pressure,
            "altitude": self.altitude,

            "accel_x": gx,
            "accel_y": gy,
            "accel_z": gz,
            "gyro_x": random.uniform(-0.5, 0.5) if self.maneuver != "setup" else random.uniform(-0.01, 0.01),
            "gyro_y": random.uniform(-0.5, 0.5) if self.maneuver != "setup" else random.uniform(-0.01, 0.01),
            "gyro_z": random.uniform(-0.3, 0.3) if self.maneuver != "setup" else random.uniform(-0.005, 0.005),
            "mag_x": math.sin(math.radians(self.heading)) * 0.5,
            "mag_y": math.cos(math.radians(self.heading)) * 0.5,
            "mag_z": -0.8 * math.cos(math.radians(self.roll)),
            "roll": self.roll % 360,
            "pitch": self.pitch % 360,
            "yaw": self.heading,

            "heart_rate": self.current_hr + random.uniform(-5, 5),
            "rr_interval": 60.0 / max(50, self.current_hr),
            "baseline_deviation": 0.02 + abs(self.g_load - 1) * 0.03,
            "rmssd": 55 - abs(self.g_load - 1) * 10,
            "hr_trend": abs(self.g_load - 1) * 5,
            "stress_index": 0.10 + abs(self.g_load - 1) * 0.15,

            "avg_ear": self.base_ear + ear_effect + random.uniform(-0.01, 0.01),
            "mar": random.uniform(0.24, 0.30),
            "eyes_closed": False,
            "closure_duration": 0.0,
            "microsleep_count": 0.0,
            "blink_rate": 20 + abs(self.g_load - 1) * 10,
            "yawning": False,
            "yawn_count": 0.0,
            "yawn_duration": 0.0,

            "fusion_score": 0.15 + abs(self.g_load - 1) * 0.2,
            "confidence": 0.92 + random.uniform(0, 0.08),

            "system_state": "alert" if abs(self.g_load) > 3 else "monitoring_active",
            "state_message": f"{self.maneuver.upper()}\n{self.base_ear:.2f} 0 {int(self.current_hr)} {self.g_load:.1f}G",

            "pilot_username": self.pilot_username,
            "flight_id": self.flight_id,
            "collection_time": time.time(),
            "predictor_version": "1.0.0",
        })


class IFRApproachScenario(FlightScenario):
    """Instrument approach in IMC (fog/clouds)"""

    def __init__(self, pilot_username: str, flight_id: str, duration_seconds: int = 320):
        super().__init__("IFR Approach in IMC", pilot_username, flight_id, duration_seconds)
        self.visibility = 10000  # meters
        self.in_clouds = False
        self.on_approach = False
        self.decision_height = 200
        self.ils_deviation = 0

    def update(self, delta_time: float):
        super().update(delta_time)
        progress = self.elapsed_time / self.duration_seconds

        if progress < 0.20:
            # Descent from cruise
            self.altitude = 8000 - progress / 0.20 * 4000
            self.airspeed = 180
            self.visibility = 5000
            self.in_clouds = False
            self.stress_level = 0.2
        elif progress < 0.40:
            # Entering clouds
            self.altitude = 4000 - (progress - 0.20) / 0.20 * 1500
            self.airspeed = 160
            self.visibility = 800
            self.in_clouds = True
            self.stress_level = 0.4
        elif progress < 0.75:
            # ILS approach in IMC
            self.on_approach = True
            approach_progress = (progress - 0.40) / 0.35
            self.altitude = 2500 - approach_progress * 2300
            self.airspeed = 140 - approach_progress * 20
            self.visibility = 400 - approach_progress * 200
            self.in_clouds = self.altitude > 400

            # ILS needle deviations (pilot corrections)
            self.ils_deviation = math.sin(approach_progress * math.pi * 8) * (1 - approach_progress) * 2
            self.roll = self.ils_deviation * 5 + random.uniform(-2, 2)
            self.pitch = -3 + self.ils_deviation * 0.5

            self.stress_level = 0.5 + approach_progress * 0.3
        elif progress < 0.90:
            # Breaking out of clouds, visual landing
            final_progress = (progress - 0.75) / 0.15
            self.altitude = max(0, 200 - final_progress * 200)
            self.airspeed = 120 - final_progress * 50
            self.visibility = 200 + final_progress * 2000
            self.in_clouds = False
            self.roll = random.uniform(-5, 5)
            self.pitch = -2
            self.stress_level = 0.6
        else:
            # Taxi
            self.altitude = 0
            self.airspeed = 0
            self.visibility = 2200
            self.stress_level = 0.1

        # Workload increases significantly during approach
        if self.on_approach:
            self.base_hr = 78 + self.stress_level * 15

    def generate_data(self) -> Dict[str, Any]:
        temp, pressure = get_altitude_temp_pressure(self.altitude)

        # IMC adds moisture
        if self.in_clouds:
            humidity = random.uniform(85, 98)
            temp -= random.uniform(2, 5)
        else:
            humidity = random.uniform(60, 75)

        gx, gy, gz = calculate_g_forces(self.pitch, self.roll, self.climb_rate, False)

        # Focus intensifies during approach
        if self.on_approach:
            ear_mod = 0.02  # Slightly wider eyes from concentration
            blink_rate = 25  # Increased from concentration
        else:
            ear_mod = 0
            blink_rate = 16

        return round_values({
            "temperature": temp,
            "humidity": humidity,
            "pressure": pressure,
            "altitude": self.altitude,

            "accel_x": gx,
            "accel_y": gy,
            "accel_z": gz,
            "gyro_x": random.uniform(-0.02, 0.02) if self.on_approach else random.uniform(-0.005, 0.005),
            "gyro_y": random.uniform(-0.01, 0.01),
            "gyro_z": random.uniform(-0.02, 0.02) if abs(self.roll) > 5 else random.uniform(-0.005, 0.005),
            "mag_x": math.sin(math.radians(self.heading)) * 0.5,
            "mag_y": math.cos(math.radians(self.heading)) * 0.5,
            "mag_z": -0.8,
            "roll": self.roll,
            "pitch": self.pitch,
            "yaw": self.heading,

            "heart_rate": self.current_hr + random.uniform(-3, 3),
            "rr_interval": 60.0 / max(50, self.current_hr),
            "baseline_deviation": 0.02 + self.stress_level * 0.05,
            "rmssd": 58 - self.stress_level * 15,
            "hr_trend": self.stress_level * 6,
            "stress_index": 0.08 + self.stress_level * 0.20,

            "avg_ear": self.base_ear + ear_mod + random.uniform(-0.015, 0.015),
            "mar": random.uniform(0.24, 0.29),
            "eyes_closed": False,
            "closure_duration": 0.0,
            "microsleep_count": 0.0,
            "blink_rate": blink_rate + random.uniform(-3, 3),
            "yawning": False,
            "yawn_count": 0.0,
            "yawn_duration": 0.0,

            "fusion_score": 0.12 + self.stress_level * 0.25,
            "confidence": 0.91 + random.uniform(0, 0.09),

            "system_state": "alert" if self.on_approach else "monitoring_active",
            "state_message": f"{'IMC - ILS' if self.in_clouds else ('VISUAL' if self.altitude < 500 else 'VMC')}\n{self.base_ear + ear_mod:.2f} 0 {int(self.current_hr)} VIS:{int(self.visibility)}m",

            "pilot_username": self.pilot_username,
            "flight_id": self.flight_id,
            "collection_time": time.time(),
            "predictor_version": "1.0.0",
        })


class BirdStrikeScenario(FlightScenario):
    """Bird strike during climb with engine failure"""

    def __init__(self, pilot_username: str, flight_id: str, duration_seconds: int = 280):
        super().__init__("Bird Strike Emergency", pilot_username, flight_id, duration_seconds)
        self.bird_strike_occurred = False
        self.engine_failed = False
        self.emergency_declared = False
        self.vibration_level = 0

    def update(self, delta_time: float):
        super().update(delta_time)
        progress = self.elapsed_time / self.duration_seconds

        if progress < 0.20:
            # Normal takeoff and climb
            self.altitude = progress / 0.20 * 3000
            self.airspeed = 120 + progress / 0.20 * 30
            self.pitch = 10
            self.climb_rate = 800
            self.stress_level = 0.2
        elif progress < 0.22:
            # BIRD STRIKE!
            self.bird_strike_occurred = True
            self.engine_failed = True
            self.emergency_declared = True
            self.vibration_level = 1.0
            self.altitude = 3000 + random.uniform(-100, 100)
            self.airspeed = 150 - (progress - 0.20) / 0.02 * 30
            self.pitch = random.uniform(-5, 5)
            self.roll = random.uniform(-20, 20)
            self.stress_level = 1.0
        elif progress < 0.50:
            # Emergency glide and return
            glide_progress = (progress - 0.22) / 0.28
            self.altitude = max(1000, 3000 - glide_progress * 2000)
            self.airspeed = 95  # Best glide speed
            self.pitch = -5
            self.roll = random.uniform(-10, 10)
            self.vibration_level = max(0.3, 1.0 - glide_progress * 0.5)

            # Turn back to airport
            if glide_progress < 0.3:
                self.heading = (self.heading + delta_time * 60) % 360
                self.roll = -30

            self.stress_level = 0.9
        elif progress < 0.85:
            # Emergency approach
            approach_progress = (progress - 0.50) / 0.35
            self.altitude = max(0, 1000 - approach_progress * 1000)
            self.airspeed = 85 - approach_progress * 20
            self.pitch = -3
            self.roll = random.uniform(-5, 5)
            self.vibration_level = 0.2
            self.stress_level = 0.85
        else:
            # Emergency landing and stop
            self.altitude = 0
            self.airspeed = max(0, 65 - (progress - 0.85) / 0.15 * 65)
            self.pitch = 0
            self.roll = 0
            self.vibration_level = 0
            self.stress_level = 0.6

        # Extreme stress response
        if self.emergency_declared:
            self.base_hr = 85 + self.stress_level * 30

    def generate_data(self) -> Dict[str, Any]:
        temp, pressure = get_altitude_temp_pressure(self.altitude)
        gx, gy, gz = calculate_g_forces(self.pitch, self.roll, self.climb_rate, abs(self.roll) > 10)

        # Add vibration from damaged engine
        if self.vibration_level > 0:
            gx += random.uniform(-1, 1) * self.vibration_level
            gy += random.uniform(-1, 1) * self.vibration_level
            gz += random.uniform(-1.5, 1.5) * self.vibration_level

        # Extreme stress shows in all metrics
        if self.emergency_declared:
            ear_mod = 0.04  # Wide eyes from adrenaline
            blink_rate = 35  # Rapid blinking
        else:
            ear_mod = 0
            blink_rate = 18

        return round_values({
            "temperature": temp,
            "humidity": random.uniform(50, 65),
            "pressure": pressure,
            "altitude": self.altitude,

            "accel_x": gx,
            "accel_y": gy,
            "accel_z": gz,
            "gyro_x": random.uniform(-0.1, 0.1) if self.vibration_level > 0.5 else random.uniform(-0.02, 0.02),
            "gyro_y": random.uniform(-0.1, 0.1) if self.vibration_level > 0.5 else random.uniform(-0.02, 0.02),
            "gyro_z": random.uniform(-0.05, 0.05) if self.vibration_level > 0.5 else random.uniform(-0.01, 0.01),
            "mag_x": math.sin(math.radians(self.heading)) * 0.5,
            "mag_y": math.cos(math.radians(self.heading)) * 0.5,
            "mag_z": -0.8,
            "roll": self.roll,
            "pitch": self.pitch,
            "yaw": self.heading,

            "heart_rate": self.current_hr + random.uniform(-5, 5),
            "rr_interval": 60.0 / max(50, self.current_hr),
            "baseline_deviation": 0.05 + self.stress_level * 0.20,
            "rmssd": 45 - self.stress_level * 25,
            "hr_trend": self.stress_level * 15,
            "stress_index": 0.15 + self.stress_level * 0.40,

            "avg_ear": self.base_ear + ear_mod + random.uniform(-0.02, 0.02),
            "mar": random.uniform(0.23, 0.28),
            "eyes_closed": False,
            "closure_duration": 0.0,
            "microsleep_count": 0.0,
            "blink_rate": blink_rate + random.uniform(-5, 5),
            "yawning": False,
            "yawn_count": 0.0,
            "yawn_duration": 0.0,

            "fusion_score": 0.25 + self.stress_level * 0.45,
            "confidence": 0.85 + random.uniform(0, 0.15),

            "system_state": "critical" if self.emergency_declared and self.altitude > 100 else ("alert" if self.stress_level > 0.5 else "monitoring_active"),
            "state_message": f"{'BIRD STRIKE!' if self.bird_strike_occurred and progress < 0.25 else ('ENGINE OUT' if self.engine_failed else 'Emergency')}\n{self.base_ear + ear_mod:.2f} 0 {int(self.current_hr)} MAYDAY",

            "pilot_username": self.pilot_username,
            "flight_id": self.flight_id,
            "collection_time": time.time(),
            "predictor_version": "1.0.0",
        })


class FlightSimulator:
    """Main flight simulator that manages scenarios and MQTT transmission"""

    def __init__(self, broker: str, port: int, username: str, password: str, topic: str):
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.topic = topic

        self.mqtt_client = None
        self.mqtt_connected = False

        self.setup_mqtt_client()

    def setup_mqtt_client(self):
        """Setup MQTT client with TLS"""
        client_id = f"{self.username}_sim_{int(time.time())}"
        self.mqtt_client = mqtt.Client(
            client_id=client_id,
            protocol=mqtt.MQTTv311,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2
        )

        self.mqtt_client.username_pw_set(self.username, self.password)

        # Configure TLS
        self.mqtt_client.tls_set(
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLS,
            ciphers=None
        )

        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_disconnect = self.on_disconnect

        print(f"[MQTT] Client configured: {client_id}")

    def on_connect(self, client, userdata, flags, reason_code, properties):
        """MQTT connection callback"""
        rc = reason_code.value if hasattr(reason_code, 'value') else reason_code

        if rc == 0:
            self.mqtt_connected = True
            print(f"[MQTT] ✓ Connected to {self.broker}:{self.port}")
        else:
            self.mqtt_connected = False
            error_msgs = {
                1: "incorrect protocol version",
                2: "invalid client identifier",
                3: "server unavailable",
                4: "bad username or password",
                5: "not authorized"
            }
            print(f"[MQTT] ✗ Connection failed (rc={rc}): {error_msgs.get(rc, 'unknown error')}")

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        """MQTT disconnection callback"""
        rc = reason_code.value if hasattr(reason_code, 'value') else reason_code

        self.mqtt_connected = False
        if rc != 0:
            print(f"[MQTT] Unexpected disconnection (rc={rc})")

    def connect(self):
        """Connect to MQTT broker"""
        print(f"[MQTT] Connecting to {self.broker}:{self.port}...")
        try:
            self.mqtt_client.connect(self.broker, self.port, keepalive=60)
            self.mqtt_client.loop_start()

            # Wait for connection
            timeout = 10
            start_time = time.time()
            while not self.mqtt_connected and (time.time() - start_time) < timeout:
                time.sleep(0.1)

            if not self.mqtt_connected:
                print("[MQTT] Connection timeout")
                return False

            return True
        except Exception as e:
            print(f"[MQTT] Connection error: {e}")
            return False

    def disconnect(self):
        """Disconnect from MQTT broker"""
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        print("[MQTT] Disconnected")

    def publish_data(self, data: Dict[str, Any]) -> bool:
        """Publish telemetry data to MQTT"""
        if not self.mqtt_connected:
            return False

        try:
            # Send flat JSON payload directly
            payload = json.dumps(data)
            topic_with_edge = f"{self.topic}/{self.username}"

            result = self.mqtt_client.publish(topic_with_edge, payload, qos=1, retain=False)

            return result.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            print(f"[MQTT] Publish error: {e}")
            return False

    def run_scenario(self, scenario: FlightScenario, interval: float = 2.0):
        """Run a flight scenario"""
        print(f"\n{'='*70}")
        print(f"SCENARIO: {scenario.name}")
        print(f"Pilot: {scenario.pilot_username}")
        print(f"Flight ID: {scenario.flight_id}")
        print(f"Duration: {scenario.duration_seconds}s (sending data every {interval}s)")
        print(f"{'='*70}\n")

        iteration = 0
        start_time = time.time()

        while not scenario.is_complete():
            iteration += 1
            current_time = time.time()
            elapsed = current_time - start_time

            # Generate data
            data = scenario.generate_data()

            # Publish
            success = self.publish_data(data)

            # Log
            status = "✓" if success else "✗"
            alt_display = f"{data.get('altitude', 0):5.0f}ft" if data.get('altitude', 0) > 0 else "GROUND"
            print(f"[{iteration:3d}] {status} t={elapsed:6.1f}s | "
                  f"ALT={alt_display} | "
                  f"HR={data.get('heart_rate', 0):3.0f} | "
                  f"EAR={data.get('avg_ear', 0):.2f} | "
                  f"Fusion={data.get('fusion_score', 0):.2f} | "
                  f"State={data.get('system_state', 'unknown'):<18}")

            # Update scenario state
            scenario.update(interval)

            # Wait for next iteration
            time.sleep(interval)

        print(f"\n[SCENARIO] {scenario.name} completed!\n")


def main():
    parser = argparse.ArgumentParser(description="CogniFlight Flight Simulator")
    parser.add_argument("--broker", default=DEFAULT_MQTT_BROKER, help="MQTT broker address")
    parser.add_argument("--port", type=int, default=DEFAULT_MQTT_PORT, help="MQTT broker port")
    parser.add_argument("--username", default=DEFAULT_MQTT_USERNAME, help="MQTT username (edge ID)")
    parser.add_argument("--password", default=DEFAULT_MQTT_PASSWORD, help="MQTT password")
    parser.add_argument("--topic", default=DEFAULT_MQTT_TOPIC, help="MQTT base topic")
    parser.add_argument("--interval", type=float, default=2.0, help="Data transmission interval (seconds)")
    parser.add_argument("--scenario",
                       choices=["pattern", "mountain", "longhaul", "medical", "aerobatic",
                               "ifr", "birdstrike", "all"],
                       default="all", help="Scenario to run")

    args = parser.parse_args()

    # Create simulator
    simulator = FlightSimulator(
        broker=args.broker,
        port=args.port,
        username=args.username,
        password=args.password,
        topic=args.topic
    )

    # Connect to MQTT
    if not simulator.connect():
        print("Failed to connect to MQTT broker. Exiting.")
        return

    try:
        # Define scenarios
        scenarios = []

        if args.scenario in ["pattern", "all"]:
            scenarios.append(PatternWorkScenario("Student_Pattern", "FLT001_PATTERN", 420))

        if args.scenario in ["mountain", "all"]:
            scenarios.append(MountainFlyingScenario("Mountain_Pilot", "FLT002_MOUNTAIN", 360))

        if args.scenario in ["longhaul", "all"]:
            scenarios.append(LongHaulFatigueScenario("Captain_LongHaul", "FLT003_LONGHAUL", 600))

        if args.scenario in ["medical", "all"]:
            scenarios.append(MedicalEmergencyScenario("Pilot_Hypoxia", "FLT004_HYPOXIA", 300))

        if args.scenario in ["aerobatic", "all"]:
            scenarios.append(AerobaticScenario("Aerobatic_Pilot", "FLT005_AEROBATIC", 240))

        if args.scenario in ["ifr", "all"]:
            scenarios.append(IFRApproachScenario("IFR_Pilot", "FLT006_IFR_IMC", 320))

        if args.scenario in ["birdstrike", "all"]:
            scenarios.append(BirdStrikeScenario("Emergency_Pilot", "FLT007_BIRDSTRIKE", 280))

        # Run scenarios
        print("\n" + "="*70)
        print("COGNIFLIGHT FLIGHT SIMULATOR")
        print(f"Running {len(scenarios)} scenario(s)")
        print("="*70)

        for scenario in scenarios:
            simulator.run_scenario(scenario, interval=args.interval)

        print("\n" + "="*70)
        print("ALL SCENARIOS COMPLETED")
        print("="*70 + "\n")

    except KeyboardInterrupt:
        print("\n\n[SIMULATOR] Interrupted by user")
    finally:
        simulator.disconnect()


if __name__ == "__main__":
    main()