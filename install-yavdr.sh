#!/bin/bash
if (( $EUID != 0 )); then
    echo "This script must be run using sudo -H or as root"
    exit
fi

apt-get -y install software-properties-common
# update packages
apt-get update
# install required packages
apt-get -y install --no-install-recommends ansible python-jmespath

# TODO: run ansible on local host
ansible-playbook yavdr07.yml -b -i 'localhost_inventory' --connection=local --tags="all" --extra-vars "first_run=True"
