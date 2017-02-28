#!/bin/bash
# return all vendor:device ids
# typical device path:
# /sys/devices/pci0000\:00/0000\:00\:1f.2/

for device in /sys/devices/pci*/*:*:*/; do
  echo "$(cat "$device"/vendor):$(cat "$device"/device)" | sed 's/0x//g'
done

