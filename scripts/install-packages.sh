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

MITOGEN_DIR='/usr/local/lib/mitogen'

if [ ! -e "$MITOGEN_DIR" ]; then
    git clone 'https://github.com/dw/mitogen.git' "$MITOGEN_DIR"
else
    pushd "$MITOGEN_DIR"
    git pull
    popd
fi

if [ -e "${MITOGEN_DIR}/ansible_mitogen/plugins/strategy" ]; then
        export ANSIBLE_STRATEGY_PLUGINS="${MITOGEN_DIR}/ansible_mitogen/plugins/strategy"
        export ANSIBLE_STRATEGY=mitogen_linear
fi
