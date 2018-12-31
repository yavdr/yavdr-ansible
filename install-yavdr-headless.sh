#!/bin/bash
set -e
if (( $EUID != 0 )); then
    echo "This script must be run using sudo -H or as root"
    exit
fi

# update packages
apt update
apt -y install software-properties-common
add-apt-repository -y ppa:ansible/ansible-2.7

# install required packages
apt-get -y install --no-install-recommends ansible python-jmespath

# TODO: run ansible on local host
ansible-playbook yavdr07-headless.yml -b -i 'localhost_inventory' --connection=local --tags="all" --extra-vars "first_run=True"
