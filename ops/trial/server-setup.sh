#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu server (Oracle Cloud Always Free, Ampere
# A1, Ubuntu 24.04) for the unattended trial. Run it on your laptop:
#
#   ssh ubuntu@203.0.113.7 'bash -s' < ops/trial/server-setup.sh
#
# Installs Docker, opens ports 80 and 443 in the host firewall (Oracle's
# Ubuntu images reject everything but SSH in iptables), and adds 2 GB of swap.
# You must still open 80 and 443 in the VCN's security list in the Oracle
# console; this script cannot reach that.
set -euo pipefail

if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi

sudo apt-get install -y rsync >/dev/null

for port in 80 443; do
  sudo iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null \
    || sudo iptables -I INPUT 5 -p tcp --dport "$port" -j ACCEPT
done
sudo iptables -C INPUT -p udp --dport 443 -j ACCEPT 2>/dev/null \
  || sudo iptables -I INPUT 5 -p udp --dport 443 -j ACCEPT
if command -v netfilter-persistent >/dev/null; then
  sudo netfilter-persistent save
fi

if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "Server ready. Log out and back in once so the docker group applies."
