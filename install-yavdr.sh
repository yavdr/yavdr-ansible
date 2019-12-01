#!/bin/bash
set -e

if (( $EUID != 0 )); then
    echo "This script must be run using sudo -H or as root"
    exit
fi

venv_dir="/root/.ansible-venv"

# update packages
apt update
# install required packages
apt -y install software-properties-common python3-venv python3-wheel build-essential

set +e
[ ! -r  "${venv_dir}/bin/activate" ] && python3 -m venv "${venv_dir}"
set -e
source "${venv_dir}/bin/activate"

"${venv_dir}/bin/pip" install -U pip wheel kmodpy ansible jmespath 

# speed up playbook execution
export ANSIBLE_PIPELINING=1
# TODO: run ansible on local host
"${venv_dir}/bin/ansible-playbook" yavdr07.yml -b -i 'localhost_inventory' --connection=local --tags="all"
