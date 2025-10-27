"""
CogniFlight Environmental Monitor Service

Monitors environmental sensors for the CogniFlight edge computing system:
- DHT22: Temperature and humidity sensor on GPIO 6
- GY-91: 10-DOF sensor board containing:
  * MPU9250: 9-axis IMU (accelerometer, gyroscope, magnetometer) at I2C 0x68
  * BMP280: Barometric pressure and temperature sensor at I2C 0x76

Hardware Configuration:
- Device: Raspberry Pi 4 (Secondary)
- I2C Bus 1: GPIO 2 (SDA) / GPIO 3 (SCL) - Pins 3 & 5 - Default I2C bus
- DHT22: GPIO 6 (Pin 31)
- Polling interval: 2 seconds
- Publishes data to CogniCore Redis infrastructure

Service Configuration:
- Systemd service with watchdog (30s timeout)
- Resource limits: 512MB RAM, 25% CPU quota
- Automatic restart on failure with exponential backoff
"""

import time
import sys
import logging
from pathlib import Path
import board
import busio
import adafruit_dht
import smbus
from imusensor.MPU9250 import MPU9250
import adafruit_bmp280
import systemd.daemon
from board import I2C

# Add project root to path for imports (deployment flexible)
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from CogniCore import CogniCore

# Configuration
DHT_PIN = 6  # BCM pin (board.D6) - DHT22 temperature/humidity sensor
I2C_BUS_NUM = 1  # Linux device number for I2C1 bus (/dev/i2c-1)
I2C_BUS_SDA = 2  # GPIO 2 - I2C1 SDA for GY-91 (Pin 3)
I2C_BUS_SCL = 3  # GPIO 3 - I2C1 SCL for GY-91 (Pin 5)
POLL_INTERVAL = 1.0  # 1 second polling interval
SERVICE_NAME = "env_monitor"

# Initialize sensors
try:
    # DHT22 sensor
    dht_device = adafruit_dht.DHT22(board.D6, use_pulseio=False)

    # I2C Bus 1 configuration for GY-91 sensor board (Raspberry Pi 4)
    # Hardware: Default I2C1 enabled via dtparam=i2c_arm=on in /boot/config.txt
    # Physical: GPIO 2 (SDA), GPIO 3 (SCL) - Pins 3 & 5 on 40-pin header
    # Devices: MPU9250 (IMU) at 0x68 + BMP280 (pressure) at 0x76
    mpu = None
    bmp = None

    try:
        # Initialize MPU9250 sensor using imusensor library with smbus
        # MPU9250: 9-axis IMU (accelerometer, gyroscope, magnetometer)
        address = 0x68
        bus = smbus.SMBus(I2C_BUS_NUM)  # Use I2C Bus 1 (/dev/i2c-1)
        mpu = MPU9250.MPU9250(bus, address)
        mpu.begin()
        print(f"MPU9250 sensor initialized successfully on I2C Bus {I2C_BUS_NUM}")

        # Initialize BMP280 sensor using adafruit library with ExtendedI2C
        # BMP280: Barometric pressure and temperature sensor
        try:
            # Use adafruit_extended_bus for I2C bus access
            from adafruit_extended_bus import ExtendedI2C as I2C
            i2c = I2C(I2C_BUS_NUM)  # Access /dev/i2c-1 directly
            bmp = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=0x76)
            print(f"BMP280 sensor initialized successfully on I2C Bus {I2C_BUS_NUM} using ExtendedI2C")
        except Exception as e:
            bmp = None
            print(f"BMP280 sensor initialization failed (continuing without pressure data): {e}")

        print(f"GY-91 sensor board initialized on I2C Bus {I2C_BUS_NUM} (GPIO {I2C_BUS_SDA}/{I2C_BUS_SCL})")
    except Exception as e:
        print(f"GY-91 sensor initialization failed (will continue without): {e}")
        mpu = None
        bmp = None
    
    # Configure BMP280 if successfully initialized
    if bmp:
        # Set BMP280 to high resolution mode
        bmp.mode = adafruit_bmp280.MODE_NORMAL
        bmp.standby_period = adafruit_bmp280.STANDBY_TC_500
        bmp.iir_filter = adafruit_bmp280.IIR_FILTER_X16
        bmp.overscan_pressure = adafruit_bmp280.OVERSCAN_X16
        bmp.overscan_temperature = adafruit_bmp280.OVERSCAN_X2
    
except Exception as e:
    print(f"Failed to initialize sensors: {e}")
    sys.exit(1)

def read_dht_data_with_retry(logger, max_attempts=10, retry_delay=0.1):
    """Read temperature and humidity from DHT sensor with robust retry logic."""
    last_error = None
    
    for attempt in range(max_attempts):
        try:
            humidity = dht_device.humidity
            temperature = dht_device.temperature
            
            if humidity is not None and temperature is not None:
                if attempt > 0:
                    logger.debug(f"DHT22 successful read on attempt {attempt + 1}")
                return {
                    "temp": round(temperature, 1),
                    "humidity": round(humidity, 1),
                    "t_sensor": time.time(),
                    "attempts": attempt + 1
                }
                
        except RuntimeError as error:
            last_error = error
            if attempt < max_attempts - 1:
                time.sleep(retry_delay)
                continue
        except Exception as e:
            logger.error(f"Unexpected DHT22 error on attempt {attempt + 1}: {e}")
            last_error = e
            if attempt < max_attempts - 1:
                time.sleep(retry_delay)
                continue
            break
    
    # All attempts failed
    if last_error:
        logger.warning(f"DHT22 failed after {max_attempts} attempts. Last error: {last_error}")
    else:
        logger.warning(f"DHT22 returned None values after {max_attempts} attempts")
    
    return None

def read_gy91_data_with_retry(logger, max_attempts=5, retry_delay=0.1):
    """Read IMU and pressure data from GY-91 sensor with retry logic."""
    # Check if MPU sensor is initialized
    if not mpu:
        logger.debug("GY-91 MPU sensor not initialized, skipping reading")
        return None
        
    last_error = None
    
    for attempt in range(max_attempts):
        try:
            # Read MPU9250 (IMU) data using the imusensor library
            mpu.readSensor()
            mpu.computeOrientation()
            
            # Get sensor values from imusensor
            acceleration = mpu.AccelVals  # [x, y, z] in m/s^2
            gyro = mpu.GyroVals  # [x, y, z] in rad/s
            magnetometer = mpu.MagVals  # [x, y, z] in µT
            
            # Read BMP280 (pressure/temperature) data if available
            if bmp:
                pressure = bmp.pressure  # hPa
                bmp_temperature = bmp.temperature  # °C
                
                # Calculate altitude from pressure (standard atmosphere)
                # Using standard formula: h = 44330 * (1 - (P/P0)^0.1903)
                sea_level_pressure = 1013.25  # hPa at sea level
                altitude = 44330 * (1 - (pressure / sea_level_pressure) ** 0.1903)
            else:
                pressure = None
                bmp_temperature = None
                altitude = None
            
            if attempt > 0:
                logger.debug(f"GY-91 successful read on attempt {attempt + 1}")
                
            return {
                # Accelerometer data (m/s^2)
                "accel_x": round(acceleration[0], 3),
                "accel_y": round(acceleration[1], 3),
                "accel_z": round(acceleration[2], 3),
                # Gyroscope data (rad/s)
                "gyro_x": round(gyro[0], 3),
                "gyro_y": round(gyro[1], 3),
                "gyro_z": round(gyro[2], 3),
                # Magnetometer data (µT)
                "mag_x": round(magnetometer[0], 2),
                "mag_y": round(magnetometer[1], 2),
                "mag_z": round(magnetometer[2], 2),
                # Orientation data (degrees)
                "roll": round(mpu.roll, 2),
                "pitch": round(mpu.pitch, 2),
                "yaw": round(mpu.yaw, 2),
                # Pressure and altitude (if available)
                "pressure": round(pressure, 2) if pressure is not None else None,
                "bmp_temp": round(bmp_temperature, 1) if bmp_temperature is not None else None,
                "altitude": round(altitude, 1) if altitude is not None else None,
                "t_sensor": time.time(),
                "attempts": attempt + 1
            }
                
        except Exception as e:
            last_error = e
            logger.debug(f"GY-91 read attempt {attempt + 1} failed: {e}")
            if attempt < max_attempts - 1:
                time.sleep(retry_delay)
                continue
            break
    
    # All attempts failed
    logger.warning(f"GY-91 failed after {max_attempts} attempts. Last error: {last_error}")
    return None

def main():
    """Main environmental monitoring service loop with continuous reading."""
    # Initialize CogniCore first to enable logging
    try:
        core = CogniCore(SERVICE_NAME)
        logger = core.get_logger(SERVICE_NAME)
        logger.info("Environmental monitoring service started (continuous reading mode)")

        # Notify systemd that service is ready
        systemd.daemon.notify('READY=1')
        logger.info("Notified systemd that service is ready")
    except Exception as e:
        print(f"Failed to connect to CogniCore: {e}")
        return

    # Track last successful readings for continuity
    last_successful_dht_data = None
    last_successful_gy91_data = None
    consecutive_dht_failures = 0
    consecutive_gy91_failures = 0

    # Track last publish times for guaranteed interval publishing
    last_dht_publish_time = 0
    last_gy91_publish_time = 0
    last_watchdog_time = time.time()

    try:
        while True:
            current_time = time.time()

            # Continuous reading: Always try to get fresh data
            # Read DHT22 sensor data with robust retry
            dht_data = read_dht_data_with_retry(logger)

            # Check if it's time to publish DHT22 data (at least POLL_INTERVAL has passed)
            if current_time - last_dht_publish_time >= POLL_INTERVAL:
                # Handle DHT22 data
                if dht_data:
                    try:
                        # Publish DHT22 data to CogniCore
                        core.publish_data("env_sensor", dht_data)
                        logger.info(f"DHT22 reading: {dht_data['temp']}°C, {dht_data['humidity']}% (attempts: {dht_data.get('attempts', 1)})")

                        # Update tracking variables
                        last_successful_dht_data = dht_data
                        consecutive_dht_failures = 0
                        last_dht_publish_time = current_time

                    except Exception as e:
                        logger.error(f"Failed to publish DHT22 data: {e}")
                else:
                    consecutive_dht_failures += 1

                    # Publish last known good DHT22 data with failure flag
                    if last_successful_dht_data and consecutive_dht_failures < 10:
                        stale_data = last_successful_dht_data.copy()
                        stale_data.update({
                            "t_sensor": time.time(),
                            "data_stale": True,
                            "consecutive_failures": consecutive_dht_failures,
                            "stale_age_seconds": round(time.time() - last_successful_dht_data["t_sensor"], 1)
                        })

                        try:
                            core.publish_data("env_sensor", stale_data)
                            logger.info(f"DHT22 using stale data: {stale_data['temp']}°C, {stale_data['humidity']}% (stale for {stale_data['stale_age_seconds']}s, failure #{consecutive_dht_failures})")
                            last_dht_publish_time = current_time
                        except Exception as e:
                            logger.error(f"Failed to publish stale DHT22 data: {e}")
                    else:
                        if consecutive_dht_failures >= 10:
                            logger.error(f"DHT22 sensor completely failed after {consecutive_dht_failures} consecutive failures")
                        else:
                            logger.warning(f"DHT22 sensor read failed (failure #{consecutive_dht_failures})")
                        last_dht_publish_time = current_time

            # Read GY-91 sensor data with retry
            gy91_data = read_gy91_data_with_retry(logger)

            # Check if it's time to publish GY-91 data (at least POLL_INTERVAL has passed)
            if current_time - last_gy91_publish_time >= POLL_INTERVAL:
                # Handle GY-91 data
                if gy91_data:
                    try:
                        # Publish GY-91 data to CogniCore
                        core.publish_data("imu_sensor", gy91_data)
                        logger.info(f"GY-91 reading: acc({gy91_data['accel_x']},{gy91_data['accel_y']},{gy91_data['accel_z']}) gyro({gy91_data['gyro_x']},{gy91_data['gyro_y']},{gy91_data['gyro_z']}) mag({gy91_data['mag_x']},{gy91_data['mag_y']},{gy91_data['mag_z']}) orientation(r:{gy91_data['roll']},p:{gy91_data['pitch']},y:{gy91_data['yaw']}) press:{gy91_data['pressure']}hPa alt:{gy91_data['altitude']}m (attempts: {gy91_data.get('attempts', 1)})")

                        # Update tracking variables
                        last_successful_gy91_data = gy91_data
                        consecutive_gy91_failures = 0
                        last_gy91_publish_time = current_time

                    except Exception as e:
                        logger.error(f"Failed to publish GY-91 data: {e}")
                else:
                    consecutive_gy91_failures += 1

                    # Publish last known good GY-91 data with failure flag
                    if last_successful_gy91_data and consecutive_gy91_failures < 10:
                        stale_data = last_successful_gy91_data.copy()
                        stale_data.update({
                            "t_sensor": time.time(),
                            "data_stale": True,
                            "consecutive_failures": consecutive_gy91_failures,
                            "stale_age_seconds": round(time.time() - last_successful_gy91_data["t_sensor"], 1)
                        })

                        try:
                            core.publish_data("imu_sensor", stale_data)
                            logger.info(f"GY-91 using stale data: press:{stale_data['pressure']}hPa alt:{stale_data['altitude']}m (stale for {stale_data['stale_age_seconds']}s, failure #{consecutive_gy91_failures})")
                            last_gy91_publish_time = current_time
                        except Exception as e:
                            logger.error(f"Failed to publish stale GY-91 data: {e}")
                    else:
                        if consecutive_gy91_failures >= 10:
                            logger.error(f"GY-91 sensor completely failed after {consecutive_gy91_failures} consecutive failures")
                        else:
                            logger.warning(f"GY-91 sensor read failed (failure #{consecutive_gy91_failures})")
                        last_gy91_publish_time = current_time

            # Send systemd watchdog keepalive every 10 seconds
            if current_time - last_watchdog_time >= 10:
                systemd.daemon.notify('WATCHDOG=1')
                last_watchdog_time = current_time

            # Small sleep to prevent CPU spinning (10ms)
            time.sleep(0.01)

    except KeyboardInterrupt:
        logger.info("Environmental monitoring service stopping...")
        logger.info("Service stopped by user interrupt")
    except Exception as e:
        logger.critical(f"Environmental monitoring service crashed: {e}")
        logger.critical(f"Service crashed: {e}")
    finally:
        core.shutdown()
        logger.info("Environmental monitoring service exited")

if __name__ == "__main__":
    main()
