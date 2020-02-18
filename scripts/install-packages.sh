#!/usr/bin/bash
required_packages=( 
    ansible
    build-essential
    python3-kmodpy
    python3-argcomplete
    python3-mysqldb
    python3-venv
    python3-wheel
    software-properties-common
)
apt update
apt -y install "${required_packages[@]}"
