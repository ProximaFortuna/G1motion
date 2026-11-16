#!/usr/bin/env bash
# Point a robot's chrony at the fleet PC. Run from the PC:
#   ./timesync/install-robot.sh <robot_ip> [pc_ip] [ssh_user] [ssh_key]
# It prompts for the robot's sudo password (chrony config needs root).
# It writes ONE file on the robot and reloads chrony sources. Nothing else.
# Undo: sudo rm /etc/chrony/sources.d/fleet.sources && sudo chronyc reload sources
set -euo pipefail
ROBOT=${1:?robot ip}
PC_IP=${2:-}
USER_=${3:-unitree}
KEY=${4:-$HOME/.ssh/id_rsa}

if [ -z "$PC_IP" ]; then
  prefix=$(echo "$ROBOT" | cut -d. -f1-3)
  PC_IP=$(ifconfig 2>/dev/null | grep -oE "inet $prefix\.[0-9]+" | awk '{print $2}' | head -1 || true)
  [ -z "$PC_IP" ] && PC_IP=$(ip -4 -o addr 2>/dev/null | grep -oE "$prefix\.[0-9]+" | head -1 || true)
  [ -z "$PC_IP" ] && { echo "could not detect PC IP on $prefix.0/24, pass it as 2nd arg"; exit 1; }
fi

LINE="server $PC_IP iburst prefer trust minpoll 2 maxpoll 4"
echo "robot $ROBOT -> fleet time server $PC_IP"
echo "writing /etc/chrony/sources.d/fleet.sources: $LINE"

ssh -t -i "$KEY" "$USER_@$ROBOT" "
  printf '# fleet PC time server (managed by fleet/timesync/install-robot.sh)\n$LINE\n' | sudo tee /etc/chrony/sources.d/fleet.sources >/dev/null &&
  sudo chronyc reload sources && sleep 8 &&
  echo '--- sources' && chronyc sources && echo '--- tracking' && chronyc tracking | head -6
"
