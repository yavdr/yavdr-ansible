#!/bin/bash
set -e

if (( $EUID != 0 )); then
    echo "This script must be run using sudo -H or as root"
    exit
fi

. scripts/install-packages.sh

# speed up playbook execution
export ANSIBLE_PIPELINING=1

ansible-playbook" yavdr07-headless.yml -b -i 'localhost_inventory' --connection=local --tags="all"
