#!/bin/bash

# Motion Controller Service Deployment Script

set -e

echo "=== Motion Controller Service Deployment ==="
echo

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root for systemd operations
if [ "$EUID" -eq 0 ]; then 
   echo -e "${RED}Please run without sudo first. Script will ask for sudo when needed.${NC}"
   exit 1
fi

# Get the directory where script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname $(dirname "$SCRIPT_DIR"))"

echo "Script directory: $SCRIPT_DIR"
echo "Project root: $PROJECT_ROOT"
echo

# Check if virtual environment exists
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv "$SCRIPT_DIR/.venv"
    echo -e "${GREEN}✓ Virtual environment created${NC}"
else
    echo -e "${GREEN}✓ Virtual environment exists${NC}"
fi

# Activate virtual environment
source "$SCRIPT_DIR/.venv/bin/activate"

# Upgrade pip
echo -e "${YELLOW}Upgrading pip...${NC}"
pip install --upgrade pip > /dev/null 2>&1
echo -e "${GREEN}✓ Pip upgraded${NC}"

# Install dependencies
echo -e "${YELLOW}Installing dependencies...${NC}"
pip install -r "$SCRIPT_DIR/requirements.txt"
echo -e "${GREEN}✓ Dependencies installed${NC}"

# Check I2C is enabled
echo -e "${YELLOW}Checking I2C configuration...${NC}"
if ! command -v i2cdetect &> /dev/null; then
    echo -e "${YELLOW}Installing I2C tools...${NC}"
    sudo apt-get update > /dev/null 2>&1
    sudo apt-get install -y i2c-tools > /dev/null 2>&1
    echo -e "${GREEN}✓ I2C tools installed${NC}"
fi

# Check if I2C is enabled
if ! ls /dev/i2c-* 2>/dev/null | grep -q i2c; then
    echo -e "${RED}I2C does not appear to be enabled!${NC}"
    echo "Please add the following to /boot/config.txt and reboot:"
    echo "  dtparam=i2c_arm=on"
    exit 1
fi

# Detect PCA9685
echo -e "${YELLOW}Scanning for PCA9685 on I2C bus 1...${NC}"
I2C_SCAN=$(sudo i2cdetect -y 1 2>/dev/null)
if echo "$I2C_SCAN" | grep -q "40\|7f"; then
    echo -e "${GREEN}✓ PCA9685 detected on I2C bus 1${NC}"
    if echo "$I2C_SCAN" | grep -q "40"; then
        echo "  Address: 0x40 (default)"
    fi
    if echo "$I2C_SCAN" | grep -q "7f"; then
        echo "  Address: 0x7F (Seeed default)"
        echo -e "${YELLOW}  Note: Update I2C_ADDRESS in main.py if using 0x7F${NC}"
    fi
else
    echo -e "${YELLOW}⚠ PCA9685 not detected on I2C bus 1${NC}"
    echo "  Please check your connections:"
    echo "  - SDA: Pin 3 (GPIO 2)"
    echo "  - SCL: Pin 5 (GPIO 3)"
    echo "  - VCC: Pin 4 (5V)"
    echo "  - GND: Pin 6"
    echo "  - External 5V to V+ terminal for servos"
fi

# Test import
echo -e "${YELLOW}Testing Python imports...${NC}"
python -c "import adafruit_pca9685; import adafruit_servokit; print('✓ Imports successful')" 2>/dev/null || {
    echo -e "${RED}Failed to import required modules${NC}"
    exit 1
}
echo -e "${GREEN}✓ Python imports successful${NC}"

# Create systemd service (if not exists)
echo -e "${YELLOW}Checking systemd service...${NC}"
if [ -f "/etc/systemd/system/cogniflight@motion_controller.service" ]; then
    echo -e "${GREEN}✓ Systemd service already exists${NC}"
else
    echo "Systemd service not found. Please run the main deployment script:"
    echo "  cd $PROJECT_ROOT"
    echo "  sudo ./scripts/deploy.sh"
fi

echo
echo -e "${GREEN}=== Deployment Complete ===${NC}"
echo
echo "Next steps:"
echo "1. Verify servo connections to channels 0 (pan) and 1 (tilt)"
echo "2. Ensure external 5V power is connected to V+ terminal"
echo "3. Start the service:"
echo "   sudo systemctl start cogniflight@motion_controller"
echo "4. Check status:"
echo "   sudo systemctl status cogniflight@motion_controller"
echo "5. View logs:"
echo "   journalctl -u cogniflight@motion_controller -f"
echo
echo "To test servo movement manually:"
echo "   python3 -c \"from adafruit_servokit import ServoKit; kit = ServoKit(channels=16); kit.servo[0].angle = 90\""