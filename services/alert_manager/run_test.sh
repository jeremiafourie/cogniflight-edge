#!/bin/bash
# Test Script Wrapper for Alert Manager State Testing
# This script loads the system configuration and runs the test script

# Load CogniFlight configuration
if [ -f /etc/cogniflight/config.env ]; then
    set -a  # Automatically export all variables
    source /etc/cogniflight/config.env
    set +a  # Disable automatic export
    echo "Loaded configuration from /etc/cogniflight/config.env"
    echo "Redis Host: ${REDIS_HOST:-localhost}"
    echo ""
else
    echo "Warning: /etc/cogniflight/config.env not found, using defaults"
    echo ""
fi

# Activate virtual environment and run test script
cd "$(dirname "$0")"
source venv/bin/activate
python test_states.py
