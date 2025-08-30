#!/bin/bash

# Check if we should show the notification (uptime > 30 days)
uptime_days=$(awk '{print int($1/86400)}' /proc/uptime)

if [ "$uptime_days" -lt 30 ]; then
    exit 0
fi

# Show desktop notification
notify-send --urgency=normal --expire-time=10000 \
    --icon=system-reboot \
    "System Update Available" \
    "Your system has been running for $uptime_days days. Please reboot to apply updates."

# Also try KDE notification if available
if command -v kdialog >/dev/null 2>&1; then
    kdialog --title "System Update Available" \
            --passivepopup "Your system has been running for $uptime_days days. Please reboot to apply updates." 10
fi
