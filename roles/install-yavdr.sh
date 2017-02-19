#!/bin/bash
if (( $EUID != 0 )); then
    echo "This script must be run using sudo or as root"
    exit
fi

# Add repository for ansible
add-apt-repository -y ppa:ansible/ansible
# update packages
apt-get update
# install required packages
apt-get -y install ansible libyaml-0-2 python-crypto python-ecdsa python-httplib2 python-jinja2 python-markupsafe python-paramiko python-pkg-resources python-setuptools python-six python-yaml sshpass
