#!/bin/bash
set -e
if (( $EUID != 0 )); then
    echo "This script must be run using sudo -H or as root"
    exit
fi

# update packages
apt update
apt -y install software-properties-common
add-apt-repository -y ppa:ansible/ansible-2.8

# install required packages
apt-get -y install --no-install-recommends ansible python-jmespath

# speed up playbook execution
export ANSIBLE_PIPELINING=1
# TODO: run ansible on local host
ansible-playbook yavdr07.yml -b -i 'localhost_inventory' --connection=local --tags="all"
