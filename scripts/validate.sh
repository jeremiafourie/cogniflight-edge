#!/bin/bash

# CogniFlight Edge - System Validation Script
# Validates deployment configuration and service health

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
CONFIG_DIR="/etc/cogniflight"
PROJECT_ROOT=""
DEPLOYMENT_MODE=""
REDIS_HOST=""
REDIS_PASSWORD="13MyFokKaren79."

# Service lists
PRIMARY_SERVICES=("go_client" "predictor" "vision_processor" "network_connector" "motion_controller" "bio_monitor")
SECONDARY_SERVICES=("env_monitor" "alert_manager")
ALL_SERVICES=("${PRIMARY_SERVICES[@]}" "${SECONDARY_SERVICES[@]}")

# Validation counters
PASSED=0
FAILED=0
WARNINGS=0

# Function to print colored output
print_header() { echo -e "\n${BLUE}═══ $1 ═══${NC}"; }
print_status() { echo -e "${BLUE}[CHECK]${NC} $1"; }
print_success() { echo -e "${GREEN}[PASS]${NC} $1"; ((PASSED++)); }
print_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; ((WARNINGS++)); }
print_error() { echo -e "${RED}[FAIL]${NC} $1"; ((FAILED++)); }

# Load configuration
load_config() {
    if [[ -f "$CONFIG_DIR/config.env" ]]; then
        source "$CONFIG_DIR/config.env"
        print_success "Configuration loaded from $CONFIG_DIR/config.env"
    else
        print_error "Configuration file not found at $CONFIG_DIR/config.env"
        print_status "Run: sudo ./scripts/deploy.sh install [--primary|--secondary]"
        exit 1
    fi
}

# Validate system dependencies
validate_system_dependencies() {
    print_header "System Dependencies"

    # Python
    if command -v python3 &> /dev/null; then
        print_success "Python3 installed: $(python3 --version | cut -d' ' -f2)"
    else
        print_error "Python3 not found"
    fi

    # Redis
    if command -v redis-cli &> /dev/null; then
        print_success "Redis CLI installed"
    else
        print_error "Redis CLI not found"
    fi

    # I2C tools (for motion controller)
    if [[ "$DEPLOYMENT_MODE" == "primary" ]] || [[ "$DEPLOYMENT_MODE" == "full" ]]; then
        if command -v i2cdetect &> /dev/null; then
            print_success "I2C tools installed"
        else
            print_warning "I2C tools not found (needed for motion_controller)"
        fi
    fi

    # Go (if go_client is deployed)
    if [[ "$DEPLOYMENT_MODE" == "primary" ]] || [[ "$DEPLOYMENT_MODE" == "full" ]]; then
        if command -v go &> /dev/null; then
            print_success "Go installed: $(go version | cut -d' ' -f3)"
        else
            print_warning "Go not found (needed for go_client)"
        fi
    fi

    # Avahi daemon (for .local resolution)
    if systemctl is-active --quiet avahi-daemon; then
        print_success "Avahi daemon running (mDNS/.local resolution)"
    else
        print_warning "Avahi daemon not running - .local hostnames may not resolve"
    fi
}

# Validate Redis connectivity
validate_redis() {
    print_header "Redis Connectivity"

    # Test Redis connection
    if redis-cli -h "$REDIS_HOST" -a "$REDIS_PASSWORD" ping &>/dev/null; then
        print_success "Redis connection successful ($REDIS_HOST)"
    else
        print_error "Cannot connect to Redis at $REDIS_HOST"
        return
    fi

    # Check Redis version
    redis_version=$(redis-cli -h "$REDIS_HOST" -a "$REDIS_PASSWORD" INFO server 2>/dev/null | grep redis_version | cut -d: -f2 | tr -d '\r')
    if [[ -n "$redis_version" ]]; then
        print_success "Redis version: $redis_version"
    fi

    # Check Redis memory usage
    used_memory=$(redis-cli -h "$REDIS_HOST" -a "$REDIS_PASSWORD" INFO memory 2>/dev/null | grep used_memory_human | cut -d: -f2 | tr -d '\r')
    if [[ -n "$used_memory" ]]; then
        print_status "Redis memory usage: $used_memory"
    fi

    # Check key count
    key_count=$(redis-cli -h "$REDIS_HOST" -a "$REDIS_PASSWORD" DBSIZE 2>/dev/null | cut -d: -f2 | tr -d ' ')
    if [[ -n "$key_count" ]]; then
        print_status "Redis keys: $key_count"
    fi
}

# Validate network connectivity
validate_network() {
    print_header "Network Connectivity"

    if [[ "$DEPLOYMENT_MODE" == "secondary" ]]; then
        # Secondary device should reach primary
        if ping -c 1 -W 2 primary.local &>/dev/null; then
            print_success "Can reach primary device (primary.local)"
        else
            print_error "Cannot ping primary device (primary.local)"
        fi
    elif [[ "$DEPLOYMENT_MODE" == "primary" ]]; then
        # Primary device should be resolvable as primary.local
        hostname_current=$(hostname)
        if [[ "$hostname_current" == "primary" ]]; then
            print_success "Hostname is set to 'primary' (resolvable as primary.local)"
        else
            print_warning "Hostname is '$hostname_current' (expected 'primary')"
            print_status "To fix: sudo hostnamectl set-hostname primary"
        fi
    fi

    # Check internet connectivity
    if ping -c 1 -W 2 8.8.8.8 &>/dev/null; then
        print_success "Internet connectivity available"
    else
        print_warning "No internet connectivity (offline mode)"
    fi
}

# Validate hardware
validate_hardware() {
    print_header "Hardware"

    # I2C devices (for motion controller on primary)
    if [[ "$DEPLOYMENT_MODE" == "primary" ]] || [[ "$DEPLOYMENT_MODE" == "full" ]]; then
        if lsmod | grep -q i2c_dev; then
            print_success "I2C modules loaded"

            # Check for PCA9685
            if command -v i2cdetect &> /dev/null; then
                if i2cdetect -y 1 2>/dev/null | grep -q -E "(40|7f)"; then
                    print_success "PCA9685 PWM controller detected on I2C bus"
                else
                    print_warning "PCA9685 not detected - motion_controller may not work"
                fi
            fi
        else
            print_warning "I2C modules not loaded - motion_controller requires I2C"
        fi

        # Camera
        if [[ -e /dev/video0 ]]; then
            print_success "Camera device detected (/dev/video0)"
        else
            print_warning "Camera device not found - vision_processor requires camera"
        fi
    fi

    # GPIO (for alert manager on secondary)
    if [[ "$DEPLOYMENT_MODE" == "secondary" ]] || [[ "$DEPLOYMENT_MODE" == "full" ]]; then
        if [[ -d /sys/class/gpio ]]; then
            print_success "GPIO sysfs available"
        else
            print_warning "GPIO not available - alert_manager may not work"
        fi
    fi
}

# Validate service files
validate_service_files() {
    print_header "Service Files"

    # Determine which services should be installed
    if [[ "$DEPLOYMENT_MODE" == "primary" ]]; then
        EXPECTED_SERVICES=("${PRIMARY_SERVICES[@]}")
    elif [[ "$DEPLOYMENT_MODE" == "secondary" ]]; then
        EXPECTED_SERVICES=("${SECONDARY_SERVICES[@]}")
    else
        EXPECTED_SERVICES=("${ALL_SERVICES[@]}")
    fi

    for service in "${EXPECTED_SERVICES[@]}"; do
        service_dir="$PROJECT_ROOT/services/$service"

        # Check if service directory exists
        if [[ ! -d "$service_dir" ]]; then
            print_error "Service directory not found: $service_dir"
            continue
        fi

        # Check for Python services
        if [[ -f "$service_dir/main.py" ]]; then
            # Check venv
            if [[ -d "$service_dir/.venv" ]]; then
                print_success "$service: venv exists"
            else
                print_error "$service: venv missing"
            fi

            # Check requirements
            if [[ -f "$service_dir/requirements.txt" ]]; then
                print_status "$service: requirements.txt found"
            else
                print_warning "$service: no requirements.txt"
            fi
        fi

        # Check for Go services
        if [[ "$service" == "go_client" ]]; then
            if [[ -f "$service_dir/go_client" ]]; then
                if [[ -x "$service_dir/go_client" ]]; then
                    print_success "$service: compiled binary exists and is executable"
                else
                    print_error "$service: binary not executable"
                fi
            else
                print_error "$service: compiled binary not found"
            fi
        fi
    done
}

# Validate systemd services
validate_systemd_services() {
    print_header "Systemd Services"

    # Determine which services should be installed
    if [[ "$DEPLOYMENT_MODE" == "primary" ]]; then
        EXPECTED_SERVICES=("${PRIMARY_SERVICES[@]}")
    elif [[ "$DEPLOYMENT_MODE" == "secondary" ]]; then
        EXPECTED_SERVICES=("${SECONDARY_SERVICES[@]}")
    else
        EXPECTED_SERVICES=("${ALL_SERVICES[@]}")
    fi

    # Check target
    if systemctl is-enabled --quiet cogniflight.target 2>/dev/null; then
        print_success "cogniflight.target is enabled"
    else
        print_error "cogniflight.target is not enabled"
    fi

    # Check individual services
    for service in "${EXPECTED_SERVICES[@]}"; do
        # Determine service unit name
        if [[ "$service" == "go_client" ]]; then
            service_unit="cogniflight-go@${service}"
        else
            service_unit="cogniflight@${service}"
        fi

        # Check if enabled
        if systemctl is-enabled --quiet "${service_unit}.service" 2>/dev/null; then
            # Check if active
            if systemctl is-active --quiet "${service_unit}.service" 2>/dev/null; then
                print_success "$service_unit: enabled and running"
            else
                print_error "$service_unit: enabled but not running"
                # Show recent logs
                print_status "Recent logs for $service_unit:"
                journalctl -u "${service_unit}.service" -n 5 --no-pager 2>/dev/null | sed 's/^/    /'
            fi
        else
            print_error "$service_unit: not enabled"
        fi
    done
}

# Validate service health
validate_service_health() {
    print_header "Service Health"

    # Determine which services should be checked
    if [[ "$DEPLOYMENT_MODE" == "primary" ]]; then
        EXPECTED_SERVICES=("${PRIMARY_SERVICES[@]}")
    elif [[ "$DEPLOYMENT_MODE" == "secondary" ]]; then
        EXPECTED_SERVICES=("${SECONDARY_SERVICES[@]}")
    else
        EXPECTED_SERVICES=("${ALL_SERVICES[@]}")
    fi

    for service in "${EXPECTED_SERVICES[@]}"; do
        # Determine service unit name
        if [[ "$service" == "go_client" ]]; then
            service_unit="cogniflight-go@${service}"
        else
            service_unit="cogniflight@${service}"
        fi

        if systemctl is-active --quiet "${service_unit}.service" 2>/dev/null; then
            # Check restart count
            restart_count=$(systemctl show "${service_unit}.service" -p NRestarts --value 2>/dev/null || echo "0")
            if [[ "$restart_count" -eq 0 ]]; then
                print_success "$service: running stable (0 restarts)"
            elif [[ "$restart_count" -lt 3 ]]; then
                print_warning "$service: $restart_count restarts detected"
            else
                print_error "$service: $restart_count restarts (check logs)"
            fi

            # Check memory usage
            memory_current=$(systemctl show "${service_unit}.service" -p MemoryCurrent --value 2>/dev/null || echo "0")
            if [[ "$memory_current" != "0" ]] && [[ "$memory_current" != "[not set]" ]]; then
                memory_mb=$((memory_current / 1024 / 1024))
                if [[ $memory_mb -lt 500 ]]; then
                    print_status "$service: memory usage ${memory_mb}MB"
                else
                    print_warning "$service: high memory usage ${memory_mb}MB"
                fi
            fi
        fi
    done
}

# Validate configuration files
validate_configuration() {
    print_header "Configuration"

    # Main config
    if [[ -f "$CONFIG_DIR/config.env" ]]; then
        print_success "Main configuration exists"

        # Check critical settings
        if grep -q "REDIS_HOST=" "$CONFIG_DIR/config.env"; then
            redis_host_config=$(grep "REDIS_HOST=" "$CONFIG_DIR/config.env" | cut -d= -f2)
            print_status "Redis host configured as: $redis_host_config"
        fi
    else
        print_error "Main configuration missing"
    fi

    # Service-specific configs
    for config_file in "$CONFIG_DIR"/config.*.env; do
        if [[ -f "$config_file" ]]; then
            config_name=$(basename "$config_file")
            print_status "Service config exists: $config_name"
        fi
    done
}

# Generate summary report
generate_summary() {
    print_header "Validation Summary"

    total=$((PASSED + FAILED + WARNINGS))

    echo ""
    echo -e "${GREEN}Passed:   $PASSED${NC}"
    echo -e "${YELLOW}Warnings: $WARNINGS${NC}"
    echo -e "${RED}Failed:   $FAILED${NC}"
    echo -e "Total:    $total"
    echo ""

    if [[ $FAILED -eq 0 ]]; then
        if [[ $WARNINGS -eq 0 ]]; then
            echo -e "${GREEN}✓ System validation passed with no issues${NC}"
            exit 0
        else
            echo -e "${YELLOW}⚠ System validation passed with warnings${NC}"
            exit 0
        fi
    else
        echo -e "${RED}✗ System validation failed - please address the errors above${NC}"
        exit 1
    fi
}

# Main validation
main() {
    echo "============================================"
    echo "  CogniFlight Edge - System Validation"
    echo "============================================"

    load_config

    print_status "Deployment mode: $DEPLOYMENT_MODE"
    print_status "Project root: $PROJECT_ROOT"
    print_status "Redis host: $REDIS_HOST"

    validate_system_dependencies
    validate_redis
    validate_network
    validate_hardware
    validate_configuration
    validate_service_files
    validate_systemd_services
    validate_service_health

    generate_summary
}

main "$@"
