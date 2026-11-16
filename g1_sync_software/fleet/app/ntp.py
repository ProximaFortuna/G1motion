"""Tiny SNTP client used only to confirm the fleet chrony container is serving time."""
from __future__ import annotations

import asyncio
import socket
import struct
import time
from typing import Any

_NTP_EPOCH = 2208988800  # 1900 -> 1970


def _query(host: str, timeout: float = 1.5) -> dict[str, Any]:
    pkt = bytearray(48)
    pkt[0] = 0x23  # LI=0, VN=4, Mode=3 (client)
    t1 = time.time()
    struct.pack_into("!II", pkt, 40, int(t1) + _NTP_EPOCH, int((t1 % 1) * 2**32))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        s.sendto(pkt, (host, 123))
        data, _ = s.recvfrom(48)
    t4 = time.time()
    stratum = data[1]
    def ts(off: int) -> float:
        sec, frac = struct.unpack_from("!II", data, off)
        return sec - _NTP_EPOCH + frac / 2**32
    t2, t3 = ts(32), ts(40)
    offset = ((t2 - t1) + (t3 - t4)) / 2
    return {"ok": True, "host": host, "stratum": stratum,
            "offset_ms": round(offset * 1000, 3), "rtt_ms": round((t4 - t1 - (t3 - t2)) * 1000, 3)}


async def check_time_server(host: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_query, host)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "host": host, "error": f"{type(e).__name__}: {e}"}
