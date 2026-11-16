"""Read-only robot probing over SSH.

Every command issued here is an inspection command (hostname, uptime, ip addr,
serial number). No motion, SONIC, or controller commands live in this module.
"""
from __future__ import annotations

import asyncio
import ipaddress
import time
from dataclasses import dataclass, field, asdict
from typing import Any

import asyncssh

# One shell line, read-only. Fields are separated by a marker so parsing is trivial.
_PROBE_CMD = r"""
echo "@hostname=$(hostname)"
echo "@uptime=$(cut -d' ' -f1 /proc/uptime)"
echo "@load=$(cut -d' ' -f1-3 /proc/loadavg)"
echo "@os=$(. /etc/os-release 2>/dev/null; echo "$PRETTY_NAME")"
echo "@kernel=$(uname -r) $(uname -m)"
echo "@serial=$(tr -d '\0' < /sys/firmware/devicetree/base/serial-number 2>/dev/null)"
echo "@model=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null)"
echo "@mem=$(awk '/MemTotal/{t=$2}/MemAvailable/{a=$2}END{printf "%d %d", t/1024, a/1024}' /proc/meminfo)"
ip -4 -o addr show 2>/dev/null | awk '$2!="lo"{print "@ip=" $2 " " $4}'
ip -o link show 2>/dev/null | awk -F': ' '{print $2}' | while read i; do m=$(cat /sys/class/net/$i/address 2>/dev/null); [ -n "$m" ] && echo "@mac=$i $m"; done
echo "@docker=$(docker ps --format '{{.Names}}' 2>/dev/null | tr '\n' ',')"
echo "@tracking=$(chronyc -c tracking 2>/dev/null)"
chronyc -c sources 2>/dev/null | while read l; do echo "@source=$l"; done
"""


@dataclass
class RobotState:
    name: str
    host: str
    user: str
    role: str = ""
    reachable: bool = False          # TCP port 22 answers
    ssh_ok: bool = False             # SSH login + probe succeeded
    latency_ms: float | None = None
    hostname: str | None = None
    serial: str | None = None
    model: str | None = None
    os: str | None = None
    kernel: str | None = None
    uptime_s: float | None = None
    load: str | None = None
    mem_total_mb: int | None = None
    mem_avail_mb: int | None = None
    interfaces: list[dict[str, str]] = field(default_factory=list)
    docker_containers: list[str] = field(default_factory=list)
    clock: dict[str, Any] | None = None    # chrony tracking + sources (read-only chronyc)
    error: str | None = None
    last_seen: float | None = None
    last_probe: float | None = None

    @property
    def robot_id(self) -> str | None:
        """Stable identifier.

        1. Jetson device-tree serial (JetPack 6 exposes it; JetPack 5 does not).
        2. MAC of the NIC on the internal robot LAN 192.168.123.x (built-in Ethernet,
           survives Wi-Fi dongle swaps and reflashes).
        3. MAC of the NIC carrying the configured host address.
        4. Hostname, unless it is a generic image default like "ubuntu".
        """
        if self.serial:
            return self.serial
        for itf in self.interfaces:
            if "192.168.123." in itf.get("ip", ""):
                return "mac:" + itf["mac"]
        for itf in self.interfaces:
            if any(a.strip().split("/")[0] == self.host for a in itf.get("ip", "").split(",")):
                return "mac:" + itf["mac"]
        if self.hostname and self.hostname.lower() not in {"ubuntu", "localhost", "jetson", "nvidia"}:
            return self.hostname
        return None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["robot_id"] = self.robot_id
        return d


async def tcp_ping(host: str, port: int = 22, timeout: float = 1.5) -> float | None:
    """Return round-trip time in ms to open a TCP connection, or None."""
    t0 = time.perf_counter()
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, asyncio.TimeoutError):
        return None
    w.close()
    try:
        await w.wait_closed()
    except Exception:
        pass
    return (time.perf_counter() - t0) * 1000


def _parse(out: str) -> dict[str, Any]:
    info: dict[str, Any] = {"ips": {}, "macs": {}}
    for line in out.splitlines():
        if not line.startswith("@") or "=" not in line:
            continue
        k, v = line[1:].split("=", 1)
        v = v.strip()
        if k == "ip":
            itf, addr = v.split(" ", 1)
            info["ips"].setdefault(itf, []).append(addr)
        elif k == "mac":
            itf, mac = v.split(" ", 1)
            info["macs"][itf] = mac
        elif k == "source":
            info.setdefault("sources", []).append(v)
        else:
            info[k] = v
    return info


async def ssh_probe(host: str, user: str, key: str, timeout: float = 8.0) -> dict[str, Any]:
    async with asyncssh.connect(
        host,
        username=user,
        client_keys=[key],
        known_hosts=None,          # lab LAN; hosts change IPs often
        connect_timeout=timeout,
    ) as conn:
        result = await asyncio.wait_for(conn.run(_PROBE_CMD, check=False), timeout)
    return _parse(result.stdout or "")


async def probe_robot(state: RobotState, key: str, time_server: str | None = None) -> RobotState:
    state.last_probe = time.time()
    rtt = await tcp_ping(state.host)
    state.reachable = rtt is not None
    state.latency_ms = round(rtt, 1) if rtt is not None else None
    if not state.reachable:
        state.ssh_ok = False
        state.error = "port 22 unreachable"
        return state
    try:
        info = await ssh_probe(state.host, state.user, key)
    except Exception as e:  # noqa: BLE001
        state.ssh_ok = False
        state.error = f"ssh: {type(e).__name__}: {e}"
        return state

    state.ssh_ok = True
    state.error = None
    state.last_seen = time.time()
    state.hostname = info.get("hostname") or None
    state.serial = info.get("serial") or None
    state.model = info.get("model") or None
    state.os = info.get("os") or None
    state.kernel = info.get("kernel") or None
    state.load = info.get("load") or None
    try:
        state.uptime_s = float(info.get("uptime", ""))
    except ValueError:
        state.uptime_s = None
    try:
        t, a = info.get("mem", "").split()
        state.mem_total_mb, state.mem_avail_mb = int(t), int(a)
    except ValueError:
        pass
    ifaces = []
    for itf, mac in info["macs"].items():
        if itf == "lo":
            continue
        ifaces.append({"name": itf, "mac": mac, "ip": ", ".join(info["ips"].get(itf, []))})
    state.interfaces = ifaces
    state.docker_containers = [c for c in info.get("docker", "").split(",") if c]
    state.clock = _parse_chrony(info, time_server)
    return state


def _parse_chrony(info: dict[str, Any], time_server: str | None) -> dict[str, Any] | None:
    """Turn `chronyc -c tracking/sources` CSV into a small summary. Read-only data."""
    t = info.get("tracking", "")
    if not t:
        return None
    f = t.split(",")
    clock: dict[str, Any] = {}
    try:
        clock = {"ref": f[1] or f[0], "stratum": int(f[2]),
                 "offset_ms": round(float(f[4]) * 1000, 3),
                 "rms_ms": round(float(f[6]) * 1000, 3), "leap": f[13] if len(f) > 13 else ""}
    except (IndexError, ValueError):
        return None
    sources = []
    for line in info.get("sources", []):
        c = line.split(",")
        if len(c) < 10:
            continue
        try:
            src = {"mode": c[0], "state": c[1], "name": c[2], "stratum": int(c[3]),
                   "reach": c[5], "offset_ms": round(float(c[7]) * 1000, 3),
                   "err_ms": round(float(c[9]) * 1000, 3)}
        except ValueError:
            continue
        src["is_fleet"] = bool(time_server) and src["name"] == time_server
        sources.append(src)
    clock["sources"] = sources
    fleet_src = next((s for s in sources if s["is_fleet"]), None)
    clock["fleet_source"] = fleet_src
    clock["synced_to_fleet"] = bool(fleet_src and fleet_src["state"] == "*")
    return clock


async def scan_subnet(subnet: str, user: str, key: str, known_hosts: set[str],
                      concurrency: int = 64) -> list[dict[str, Any]]:
    """Find hosts with port 22 open, then identify them with the read-only probe."""
    net = ipaddress.ip_network(subnet, strict=False)
    sem = asyncio.Semaphore(concurrency)

    async def check(ip: str) -> dict[str, Any] | None:
        async with sem:
            rtt = await tcp_ping(ip, timeout=0.8)
        if rtt is None:
            return None
        found: dict[str, Any] = {"host": ip, "latency_ms": round(rtt, 1),
                                 "known": ip in known_hosts, "hostname": None,
                                 "serial": None, "is_unitree": False, "ssh_ok": False}
        try:
            info = await ssh_probe(ip, user, key, timeout=4.0)
            found.update(ssh_ok=True, hostname=info.get("hostname"),
                         serial=info.get("serial") or None, model=info.get("model") or None)
            found["is_unitree"] = (info.get("hostname") or "").lower().startswith("unitree")
        except Exception as e:  # noqa: BLE001
            found["error"] = type(e).__name__
        return found

    results = await asyncio.gather(*(check(str(ip)) for ip in net.hosts()))
    return [r for r in results if r]
