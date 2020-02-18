#!/usr/bin/bash
required_packages=( 
    ansible
    build-essential
    python3-argcomplete
    python3-venv
    python3-wheel
    software-properties-common
)
apt update
apt -y install "${required_packages[@]}"
