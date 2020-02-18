#!/bin/bash
set -e

if (( $EUID != 0 )); then
    echo "This script must be run using sudo -H or as root"
    exit
fi

. scripts/install-packages.sh

"${venv_dir}/bin/ansible-playbook" yavdr07.yml -b -i 'localhost_inventory' --connection=local --tags="all"
