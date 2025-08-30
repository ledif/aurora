#!/bin/bash
uptime_days=$(awk '{print int($1/86400)}' /proc/uptime)

if [ "$uptime_days" -ge 28 ]; then
    systemctl --user enable reboot-notifier.service
else
    systemctl --user disable reboot-notifier.service
fi