# yavdr-ansible
ansible playbooks for yaVDR

## Usage:

On a Ubuntu Server 16.04.x Installation run the following commands:
```
sudo add-apt-repository ppa:ansible/ansible
sudo apt-get update
sudo apt-get dist-upgrade
sudo apt-get install ansible git
git clone https://github.com/yavdr/yavdr-ansible
cd yavdr-ansible
ansible-playbook yavdr07.yml -c local -K -i "localhost,"
```


