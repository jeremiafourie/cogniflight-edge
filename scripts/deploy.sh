#!/bin/bash

# CogniFlight Edge - Universal Deployment Script
# Supports primary (primary.local) and secondary device deployments

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Auto-detect installation paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_DIR="/etc/cogniflight"
SYSTEMD_DIR="/etc/systemd/system"
TARGET_USER="${DEPLOY_USER:-$(logname 2>/dev/null || whoami)}"

# Setup pyenv for Python 3.11 (mediapipe doesn't support Python 3.13)
export PYENV_ROOT="/home/$TARGET_USER/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
if command -v pyenv >/dev/null 2>&1; then
    eval "$(pyenv init - bash)"
    PYTHON_BIN="$PYENV_ROOT/versions/3.11.11/bin/python3"
else
    PYTHON_BIN="python3"
fi

# Deployment mode (primary/secondary/full)
DEPLOYMENT_MODE=""
PRIMARY_HOST="primary.local"  # Fixed primary hostname

# Service distribution
# Primary device (primary.local) runs main processing + Redis + Motion Control + Bio Monitor
PRIMARY_SERVICES=(
    "go_client"
    "predictor"
    "vision_processor"
    "network_connector"
    "motion_controller"
    "bio_monitor"
)

# Secondary devices run environmental monitoring and alerts
SECONDARY_SERVICES=(
    "env_monitor"
    "alert_manager"
)

# All services for full installation
ALL_SERVICES=(
    "env_monitor"
    "bio_monitor"
    "alert_manager"
    "go_client"
    "predictor"
    "vision_processor"
    "network_connector"
    "motion_controller"
)

# Python services (need venv)
PYTHON_SERVICES=(
    "env_monitor"
    "bio_monitor"
    "alert_manager"
    "predictor"
    "vision_processor"
    "network_connector"
    "motion_controller"
)

# Go services (need compilation)
GO_SERVICES=(
    "go_client"
)

# Function to print colored output
print_status() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check if running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

# Parse deployment mode
parse_deployment_mode() {
    case "${2:-}" in
        --primary)
            DEPLOYMENT_MODE="primary"
            print_status "Deploying as PRIMARY device (primary.local)"
            print_status "Services: go_client, predictor, vision_processor, network_connector, motion_controller, bio_monitor"
            SERVICES=("${PRIMARY_SERVICES[@]}")
            ;;
        --secondary)
            DEPLOYMENT_MODE="secondary"
            print_status "Deploying as SECONDARY device"
            print_status "Services: env_monitor, alert_manager"
            print_status "Will connect to primary at: $PRIMARY_HOST"
            SERVICES=("${SECONDARY_SERVICES[@]}")

            # Test connection to primary
            print_status "Testing connection to primary device..."

            # Test 1: Ping connectivity
            if ! ping -c 1 -W 2 "$PRIMARY_HOST" &>/dev/null; then
                print_error "Cannot ping $PRIMARY_HOST"
                print_status "Troubleshooting steps:"
                print_status "  1. Verify both devices are on the same network"
                print_status "  2. Try ping with IP: ping 10.0.0.107"
                print_status "  3. Check primary device is online"
                print_status "  4. If hostname fails, add to /etc/hosts: echo '10.0.0.107 primary.local' | sudo tee -a /etc/hosts"
                exit 1
            fi
            print_success "Network connectivity OK"

            # Test 2: Check if redis-cli is installed
            if ! command -v redis-cli &> /dev/null; then
                print_status "Installing redis-tools for connection testing..."
                apt update -qq
                apt install -y redis-tools
            fi

            # Test 3: Port connectivity
            print_status "Testing Redis port connectivity..."
            if timeout 3 bash -c "echo > /dev/tcp/$PRIMARY_HOST/6379" 2>/dev/null; then
                print_success "Port 6379 is accessible"
            else
                print_error "Cannot connect to port 6379 on $PRIMARY_HOST"
                print_status "On PRIMARY device, verify Redis is listening on network:"
                print_status "  sudo netstat -tlnp | grep 6379"
                print_status "  (Should show: 0.0.0.0:6379)"
                print_status "On PRIMARY device, check Redis config:"
                print_status "  sudo grep '^bind' /etc/redis/redis.conf"
                print_status "  (Should show: bind 0.0.0.0)"
                exit 1
            fi

            # Test 4: Redis authentication
            print_status "Testing Redis authentication..."
            REDIS_RESPONSE=$(redis-cli -h "$PRIMARY_HOST" -a "13MyFokKaren79." ping 2>&1)
            if echo "$REDIS_RESPONSE" | grep -q "PONG"; then
                print_success "Redis connection successful!"
            else
                print_error "Cannot authenticate with Redis on $PRIMARY_HOST"
                print_status "Response: $REDIS_RESPONSE"
                print_status ""
                print_status "On PRIMARY device, verify Redis password:"
                print_status "  sudo grep '^requirepass' /etc/redis/redis.conf"
                print_status "  (Should show: requirepass 13MyFokKaren79.)"
                print_status "On PRIMARY device, test locally:"
                print_status "  redis-cli -h localhost -a '13MyFokKaren79.' ping"
                print_status ""
                read -p "Continue deployment anyway? (y/n): " -n 1 -r
                echo
                if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                    exit 1
                fi
            fi
            ;;
        *)
            DEPLOYMENT_MODE="full"
            print_status "Deploying FULL installation (all services)"
            SERVICES=("${ALL_SERVICES[@]}")
            ;;
    esac
}

# Install system dependencies
install_dependencies() {
    print_status "Installing system dependencies..."

    apt update
    apt install -y \
        python3 python3-pip python3-venv python3-dev \
        build-essential cmake pkg-config gfortran swig \
        redis-server \
        libjpeg-dev libpng-dev libtiff-dev \
        libhdf5-dev libopenblas-dev \
        python3-lgpio python3-gpiozero liblgpio-dev \
        i2c-tools python3-smbus \
        libsystemd-dev libcap-dev \
        libgl1 libglib2.0-0 \
        python3-redis

    # Install Go if go_client is being deployed
    if [[ " ${SERVICES[@]} " =~ " go_client " ]]; then
        if ! command -v go &> /dev/null; then
            print_status "Installing Go..."
            GO_VERSION="1.21.0"
            wget "https://go.dev/dl/go${GO_VERSION}.linux-arm64.tar.gz" -O /tmp/go.tar.gz
            rm -rf /usr/local/go
            tar -C /usr/local -xzf /tmp/go.tar.gz
            rm /tmp/go.tar.gz
            export PATH=$PATH:/usr/local/go/bin
            echo 'export PATH=$PATH:/usr/local/go/bin' >> /etc/profile
            print_success "Go installed successfully"
        else
            print_success "Go already installed: $(go version)"
        fi
    fi

    # Install avahi-daemon for hostname resolution (all deployments)
    apt install -y avahi-daemon
    systemctl enable avahi-daemon
    systemctl start avahi-daemon

    # Enable I2C for motion controller (primary/full) and env_monitor (secondary/full)
    if [[ "$DEPLOYMENT_MODE" == "primary" ]] || [[ "$DEPLOYMENT_MODE" == "full" ]] || [[ "$DEPLOYMENT_MODE" == "secondary" ]]; then
        # Enable I2C in boot config
        if ! grep -q "dtparam=i2c_arm=on" /boot/config.txt 2>/dev/null && [[ -f /boot/config.txt ]]; then
            echo "dtparam=i2c_arm=on" >> /boot/config.txt
            print_status "I2C enabled in boot config (will persist after reboot)"
        elif ! grep -q "dtparam=i2c_arm=on" /boot/firmware/config.txt 2>/dev/null && [[ -f /boot/firmware/config.txt ]]; then
            # For Ubuntu/newer Raspberry Pi OS
            echo "dtparam=i2c_arm=on" >> /boot/firmware/config.txt
            print_status "I2C enabled in boot config (will persist after reboot)"
        fi

        # Enable I2C using raspi-config if available (non-interactive)
        if command -v raspi-config >/dev/null 2>&1; then
            raspi-config nonint do_i2c 0 2>/dev/null || true
            print_status "I2C enabled via raspi-config"
        fi

        # Load I2C kernel modules immediately
        modprobe i2c-dev 2>/dev/null || true
        modprobe i2c-bcm2835 2>/dev/null || true

        # Add modules to load on boot
        if ! grep -q "i2c-dev" /etc/modules 2>/dev/null; then
            echo "i2c-dev" >> /etc/modules
        fi
        if ! grep -q "i2c-bcm2835" /etc/modules 2>/dev/null; then
            echo "i2c-bcm2835" >> /etc/modules
        fi
    fi

    # Only enable Redis on primary or full installation
    if [[ "$DEPLOYMENT_MODE" == "primary" ]] || [[ "$DEPLOYMENT_MODE" == "full" ]]; then
        systemctl enable redis-server
        systemctl start redis-server
        print_success "Redis server enabled (primary device)"
    elif [[ "$DEPLOYMENT_MODE" == "secondary" ]]; then
        # Disable local Redis on secondary
        systemctl stop redis-server 2>/dev/null || true
        systemctl disable redis-server 2>/dev/null || true
        print_status "Local Redis disabled (using primary's Redis at $PRIMARY_HOST)"
    fi

    print_success "Dependencies installed"
}

# Configure Redis with password (primary only)
configure_redis() {
    if [[ "$DEPLOYMENT_MODE" == "secondary" ]]; then
        print_status "Skipping Redis configuration (secondary device)"
        return
    fi

    print_status "Configuring Redis for network access..."

    # Backup Redis configuration
    if [[ ! -f /etc/redis/redis.conf.backup ]]; then
        cp /etc/redis/redis.conf /etc/redis/redis.conf.backup
    fi

    # Configure Redis for network access
    sed -i 's/^bind .*/bind 0.0.0.0/' /etc/redis/redis.conf
    sed -i 's/^protected-mode .*/protected-mode no/' /etc/redis/redis.conf
    sed -i '/^requirepass /d' /etc/redis/redis.conf
    echo "requirepass 13MyFokKaren79." >> /etc/redis/redis.conf

    # Add network optimizations
    if ! grep -q "tcp-keepalive" /etc/redis/redis.conf; then
        echo "" >> /etc/redis/redis.conf
        echo "# Network optimizations for CogniFlight Edge" >> /etc/redis/redis.conf
        echo "tcp-keepalive 300" >> /etc/redis/redis.conf
        echo "timeout 0" >> /etc/redis/redis.conf
        echo "tcp-backlog 511" >> /etc/redis/redis.conf
    fi

    systemctl restart redis-server
    print_success "Redis configured with authentication and network access"
}

# Verify motion controller hardware (primary only)
verify_motion_controller_hardware() {
    if [[ "$DEPLOYMENT_MODE" == "secondary" ]]; then
        return
    fi

    if [[ " ${SERVICES[@]} " =~ " motion_controller " ]]; then
        print_status "Verifying motion controller hardware..."

        # Check if I2C is enabled
        if ! lsmod | grep -q i2c_dev; then
            print_status "Loading I2C modules..."
            modprobe i2c-dev 2>/dev/null || true
            modprobe i2c-bcm2835 2>/dev/null || true
            if lsmod | grep -q i2c_dev; then
                print_success "I2C modules loaded successfully"
            else
                print_warning "I2C modules not loaded - reboot may be required"
            fi
        else
            print_success "I2C modules already loaded"
        fi

        # Check for PCA9685 on I2C bus (if I2C is available)
        if command -v i2cdetect >/dev/null 2>&1; then
            if i2cdetect -y 1 2>/dev/null | grep -q -E "(40|7f)"; then
                print_success "PCA9685 PWM controller detected on I2C bus"
            else
                print_warning "PCA9685 not detected - check hardware connections"
                print_warning "Expected at address 0x40 or 0x7f on I2C bus 1"
            fi
        fi
    fi
}

# Setup configuration
setup_configuration() {
    print_status "Setting up configuration..."

    # Create config directory
    mkdir -p "$CONFIG_DIR"

    # Determine Redis host based on deployment mode
    if [[ "$DEPLOYMENT_MODE" == "secondary" ]]; then
        REDIS_HOST_CONFIG="$PRIMARY_HOST"
        DEPLOYMENT_INFO="Secondary device - connects to primary at $PRIMARY_HOST"
    else
        REDIS_HOST_CONFIG="localhost"
        if [[ "$DEPLOYMENT_MODE" == "primary" ]]; then
            DEPLOYMENT_INFO="Primary device (primary.local) - local Redis"
        else
            DEPLOYMENT_INFO="Full installation - local Redis"
        fi
    fi

    # Create main configuration file
    cat > "$CONFIG_DIR/config.env" << EOF
# CogniFlight Edge Configuration
# Auto-generated on $(date)
# Deployment mode: $DEPLOYMENT_MODE
# $DEPLOYMENT_INFO

# Installation paths
PROJECT_ROOT=$PROJECT_ROOT
CONFIG_DIR=$CONFIG_DIR

# System Configuration
COGNIFLIGHT_USER=$TARGET_USER
COGNIFLIGHT_GROUP=$TARGET_USER
DEPLOYMENT_MODE=$DEPLOYMENT_MODE

# Redis Configuration
REDIS_HOST=$REDIS_HOST_CONFIG
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=13MyFokKaren79.
REDIS_TIMEOUT=10
REDIS_RETRY_ON_TIMEOUT=true
REDIS_SOCKET_KEEPALIVE=true
REDIS_TCP_KEEPIDLE=1
REDIS_TCP_KEEPINTVL=3
REDIS_TCP_KEEPCNT=5

# Redis Data Settings
REDIS_TTL=300
STATE_HISTORY_LIMIT=1000
REDIS_HEALTH_CHECK=30

# Default Resource Limits
MEMORY_MAX=2G
CPU_QUOTA=80%
EOF

    # Create service-specific override for vision_processor (if installed)
    if [[ " ${SERVICES[@]} " =~ " vision_processor " ]]; then
        cat > "$CONFIG_DIR/config.vision_processor.env" << EOF
# Vision Processor - Service-Specific Configuration
MEMORY_MAX=3G
CPU_QUOTA=100%
NICE_PRIORITY=-5
EOF
    fi

    # Create service-specific override for motion_controller (if installed)
    if [[ " ${SERVICES[@]} " =~ " motion_controller " ]]; then
        cat > "$CONFIG_DIR/config.motion_controller.env" << EOF
# Motion Controller - Service-Specific Configuration
MEMORY_MAX=512M
CPU_QUOTA=50%
NICE_PRIORITY=-10
# Supplementary groups for hardware access
SupplementaryGroups=gpio i2c spi
EOF
    fi

    chmod 644 "$CONFIG_DIR"/*.env
    print_success "Configuration created in $CONFIG_DIR"
    print_status "Redis host configured as: $REDIS_HOST_CONFIG"
}

# Install systemd services
install_services() {
    print_status "Installing systemd services..."

    # Process Python service template with actual paths
    sed -e "s|{{USER}}|$TARGET_USER|g" \
        -e "s|{{PROJECT_ROOT}}|$PROJECT_ROOT|g" \
        -e "s|{{CONFIG_DIR}}|$CONFIG_DIR|g" \
        "$PROJECT_ROOT/systemd/cogniflight@.service" > "$SYSTEMD_DIR/cogniflight@.service"

    # Process Go service template with actual paths
    sed -e "s|{{USER}}|$TARGET_USER|g" \
        -e "s|{{PROJECT_ROOT}}|$PROJECT_ROOT|g" \
        -e "s|{{CONFIG_DIR}}|$CONFIG_DIR|g" \
        "$PROJECT_ROOT/systemd/cogniflight-go@.service" > "$SYSTEMD_DIR/cogniflight-go@.service"

    # Install target
    cp "$PROJECT_ROOT/systemd/cogniflight.target" "$SYSTEMD_DIR/"

    # Set permissions
    chmod 644 "$SYSTEMD_DIR/cogniflight@.service"
    chmod 644 "$SYSTEMD_DIR/cogniflight-go@.service"
    chmod 644 "$SYSTEMD_DIR/cogniflight.target"

    # Reload systemd
    systemctl daemon-reload

    print_success "Systemd services installed"
}

# Create virtual environments (only for Python services being installed)
create_virtualenvs() {
    print_status "Creating virtual environments for Python services..."

    for service in "${SERVICES[@]}"; do
        # Skip non-Python services
        if [[ ! " ${PYTHON_SERVICES[@]} " =~ " ${service} " ]]; then
            continue
        fi

        service_dir="$PROJECT_ROOT/services/$service"
        if [[ -d "$service_dir" ]]; then
            if [[ ! -d "$service_dir/.venv" ]]; then
                print_status "Creating venv for $service using Python 3.11..."
                # Use pyenv Python 3.11 if available, otherwise fall back to system python3
                if [[ -f "$PYTHON_BIN" ]]; then
                    sudo -u "$TARGET_USER" "$PYTHON_BIN" -m venv "$service_dir/.venv"
                else
                    sudo -u "$TARGET_USER" python3 -m venv "$service_dir/.venv"
                fi
                sudo -u "$TARGET_USER" "$service_dir/.venv/bin/pip" install --upgrade pip setuptools wheel
            fi

            if [[ -f "$service_dir/requirements.txt" ]]; then
                print_status "Installing dependencies for $service..."
                sudo -u "$TARGET_USER" "$service_dir/.venv/bin/pip" install -r "$service_dir/requirements.txt"

                # Create smbus compatibility layer for packages that import smbus instead of smbus2
                if grep -q "smbus2" "$service_dir/requirements.txt"; then
                    SITE_PACKAGES="$service_dir/.venv/lib/python*/site-packages"
                    cat > $SITE_PACKAGES/smbus.py << 'EOF'
# Compatibility layer for smbus -> smbus2
from smbus2 import *
EOF
                    print_status "Created smbus compatibility layer for $service"
                fi
            fi
            print_success "Setup complete for $service"
        fi
    done

    print_success "Virtual environments created"
}

# Build Go services
build_go_services() {
    print_status "Building Go services..."

    for service in "${SERVICES[@]}"; do
        # Skip non-Go services
        if [[ ! " ${GO_SERVICES[@]} " =~ " ${service} " ]]; then
            continue
        fi

        service_dir="$PROJECT_ROOT/services/$service"
        if [[ -d "$service_dir" ]]; then
            print_status "Building $service..."
            cd "$service_dir"

            # Build as the target user
            sudo -u "$TARGET_USER" /usr/local/go/bin/go build -o "$service" .

            # Make executable
            chmod +x "$service"

            print_success "Built $service"
        fi
    done

    print_success "Go services built"
}

# Setup embeddings file for go_client
setup_embeddings_file() {
    if [[ " ${SERVICES[@]} " =~ " go_client " ]]; then
        print_status "Setting up embeddings file for go_client..."

        # Check if embeddings file already exists in go_client directory
        if [[ -f "$PROJECT_ROOT/services/go_client/embeddings.pkl" ]]; then
            print_success "Embeddings file already exists in go_client directory"
        else
            print_warning "No embeddings file found - go_client will fetch from server"
            print_warning "Embeddings will be synced from server on first run"
        fi
    fi
}

# Enable and start services (only selected ones)
enable_services() {
    print_status "Enabling selected services..."

    # Enable target
    systemctl enable cogniflight.target

    # Enable only selected services
    for service in "${SERVICES[@]}"; do
        # Determine which systemd template to use
        if [[ " ${GO_SERVICES[@]} " =~ " ${service} " ]]; then
            systemctl enable "cogniflight-go@${service}.service"
            print_success "Enabled: cogniflight-go@${service}"
        else
            systemctl enable "cogniflight@${service}.service"
            print_success "Enabled: cogniflight@${service}"
        fi
    done
}

# Start services
start_services() {
    print_status "Starting services..."
    systemctl start cogniflight.target
    print_success "Services started"
}

# Stop old services if they exist
cleanup_old_services() {
    print_status "Cleaning up old services..."

    for service in "${ALL_SERVICES[@]}"; do
        if systemctl list-units --full --all | grep -q "${service}.service"; then
            systemctl stop "${service}.service" 2>/dev/null || true
            systemctl disable "${service}.service" 2>/dev/null || true
            rm -f "$SYSTEMD_DIR/${service}.service"
            print_status "Removed old ${service}.service"
        fi
    done

    systemctl daemon-reload
}

# Show status
show_status() {
    echo "===================================="
    echo "CogniFlight Edge Service Status"
    echo "===================================="
    echo "Installation Path: $PROJECT_ROOT"
    echo "Configuration: $CONFIG_DIR"
    echo "User: $TARGET_USER"
    echo "Deployment Mode: ${DEPLOYMENT_MODE:-full}"
    if [[ "$DEPLOYMENT_MODE" == "secondary" ]]; then
        echo "Primary Host: $PRIMARY_HOST"
    fi
    echo "===================================="

    # Show only installed services
    for service in "${SERVICES[@]}"; do
        # Determine which systemd template to check
        if [[ " ${GO_SERVICES[@]} " =~ " ${service} " ]]; then
            status=$(systemctl is-active "cogniflight-go@${service}" 2>/dev/null || echo "inactive")
            service_name="cogniflight-go@${service}"
        else
            status=$(systemctl is-active "cogniflight@${service}" 2>/dev/null || echo "inactive")
            service_name="cogniflight@${service}"
        fi

        if [[ "$status" == "active" ]]; then
            echo -e "${GREEN}●${NC} $service_name: $status"
        else
            echo -e "${RED}●${NC} $service_name: $status"
        fi
    done

    echo "===================================="
    echo "Service Distribution:"
    if [[ "$DEPLOYMENT_MODE" == "primary" ]]; then
        echo "Primary (this device) runs:"
        echo "  - go_client (pilot profiles)"
        echo "  - predictor (fusion & fatigue)"
        echo "  - vision_processor (authentication & fatigue monitoring)"
        echo "  - network_connector (telemetry)"
        echo "  - motion_controller (camera tracking)"
        echo "  - bio_monitor (heart rate & alcohol detection)"
        echo ""
        echo "Secondary devices should run:"
        echo "  - env_monitor (temperature/humidity/IMU)"
        echo "  - alert_manager (GPIO/RGB LED/alerts)"
    elif [[ "$DEPLOYMENT_MODE" == "secondary" ]]; then
        echo "Secondary (this device) runs:"
        echo "  - env_monitor (temperature/humidity/IMU)"
        echo "  - alert_manager (GPIO/RGB LED/alerts)"
        echo ""
        echo "Primary (primary.local) runs:"
        echo "  - go_client, predictor, vision_processor"
        echo "  - network_connector, motion_controller, bio_monitor"
    else
        echo "Full installation: all services"
    fi
}

# Main installation
main() {
    check_root

    # Parse command and deployment mode
    COMMAND="${1:-install}"

    # Parse deployment mode for install/update commands
    if [[ "$COMMAND" == "install" ]] || [[ "$COMMAND" == "update" ]]; then
        parse_deployment_mode "$@"
    else
        # For other commands, load existing deployment mode from config
        if [[ -f "$CONFIG_DIR/config.env" ]]; then
            source "$CONFIG_DIR/config.env"
            if [[ -n "${DEPLOYMENT_MODE:-}" ]]; then
                if [[ "$DEPLOYMENT_MODE" == "primary" ]]; then
                    SERVICES=("${PRIMARY_SERVICES[@]}")
                elif [[ "$DEPLOYMENT_MODE" == "secondary" ]]; then
                    SERVICES=("${SECONDARY_SERVICES[@]}")
                else
                    SERVICES=("${ALL_SERVICES[@]}")
                fi
            else
                SERVICES=("${ALL_SERVICES[@]}")
            fi
        else
            SERVICES=("${ALL_SERVICES[@]}")
        fi
    fi

    print_status "CogniFlight Edge Deployment"
    print_status "Project Root: $PROJECT_ROOT"
    print_status "Target User: $TARGET_USER"

    case "$COMMAND" in
        install)
            install_dependencies
            configure_redis
            verify_motion_controller_hardware
            setup_configuration
            create_virtualenvs
            build_go_services
            setup_embeddings_file
            cleanup_old_services
            install_services
            enable_services
            start_services
            show_status
            print_success "Installation complete!"

            if [[ "$DEPLOYMENT_MODE" == "primary" ]]; then
                echo ""
                print_status "To deploy secondary devices, run on other Pis:"
                print_success "sudo ./scripts/deploy.sh install --secondary"
                echo ""
                print_status "Ensure this device is accessible as 'primary.local'"
                print_status "You may need to install avahi-daemon if not already installed:"
                echo "  sudo apt install avahi-daemon"
                echo ""
                print_status "Network Configuration:"
                print_status "- Primary device should be accessible as 'primary.local'"
                print_status "- Redis server running on port 6379 with password authentication"
                print_status "- Secondary devices will connect to this Redis instance"
                echo ""
                print_status "Verify Redis network access with:"
                echo "  redis-cli -h primary.local -a '13MyFokKaren79.' ping"
            elif [[ "$DEPLOYMENT_MODE" == "secondary" ]]; then
                echo ""
                print_status "Secondary device deployment complete!"
                print_status "This device connects to primary at: $PRIMARY_HOST"
                print_status "Services on this device: ${SERVICES[*]}"
            fi
            ;;
        update)
            setup_configuration
            setup_embeddings_file
            create_virtualenvs
            build_go_services
            cleanup_old_services
            install_services
            enable_services
            systemctl restart cogniflight.target
            show_status
            print_success "Update complete!"
            ;;
        start)
            start_services
            show_status
            ;;
        stop)
            systemctl stop cogniflight.target
            print_success "Services stopped"
            ;;
        restart)
            systemctl restart cogniflight.target
            show_status
            ;;
        status)
            show_status
            ;;
        uninstall)
            systemctl stop cogniflight.target 2>/dev/null || true
            systemctl disable cogniflight.target 2>/dev/null || true
            for service in "${ALL_SERVICES[@]}"; do
                systemctl disable "cogniflight@${service}.service" 2>/dev/null || true
                systemctl disable "cogniflight-go@${service}.service" 2>/dev/null || true
            done
            rm -f "$SYSTEMD_DIR"/cogniflight@.service
            rm -f "$SYSTEMD_DIR"/cogniflight-go@.service
            rm -f "$SYSTEMD_DIR"/cogniflight.target
            rm -rf "$CONFIG_DIR"
            systemctl daemon-reload
            print_success "Uninstalled"
            ;;
        *)
            echo "Usage: $0 {install|update|start|stop|restart|status|uninstall} [options]"
            echo ""
            echo "Installation modes:"
            echo "  $0 install              # Full installation (all services)"
            echo "  $0 install --primary    # Primary device at primary.local"
            echo "  $0 install --secondary  # Secondary device (connects to primary.local)"
            echo ""
            echo "Service distribution:"
            echo "  Primary (primary.local):"
            echo "    - go_client, predictor, vision_processor"
            echo "    - network_connector, motion_controller, bio_monitor"
            echo "    - Redis server with network access"
            echo ""
            echo "  Secondary devices:"
            echo "    - env_monitor, alert_manager"
            echo "    - Connects to primary's Redis"
            exit 1
            ;;
    esac
}

main "$@"
