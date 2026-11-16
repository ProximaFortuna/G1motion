# G1 synchronization protocol: dry-run prototype

**Does not connect to SONIC, publish motor commands, or move robots.** It simulates a 50 Hz playback cursor.

This is a communications experiment, **not field-ready or safety-rated software**. The agent hashes a motion directory on disk but **cannot verify SONIC actually loaded that directory**. It uses UTC to schedule `T0` and a monotonic local timeline once armed. Heartbeat timeout is a testing parameter, not validated hardware safety behavior.

## On Aurelius

```bash
python3 sync_demo.py selftest
scp sync_demo.py G1:~/sync_demo.py
scp sync_demo.py Lugan:~/sync_demo.py
```

## On each G1, in separate SSH sessions

Original G1:

```bash
ssh G1
python3 ~/sync_demo.py agent --name G1 --port 19041 --motion ~/sonic-residual-c374bae/gear_sonic_deploy/reference/example/macarena_001__A545 --frames 1375
```

Lugan:

```bash
ssh Lugan
python3 ~/sync_demo.py agent --name Lugan --port 19041 --motion ~/sonic-residual-c374bae/gear_sonic_deploy/reference/example/macarena_001__A545 --frames 1375
```

## On Aurelius, in a third terminal

```bash
python3 sync_demo.py coordinator --robots 192.168.0.8:19041 192.168.0.42:19041 --lead 6 --duration 30
```

For heartbeat loss **after** playback starts:

```bash
python3 sync_demo.py coordinator --robots 192.168.0.8:19041 192.168.0.42:19041 --lead 6 --duration 30 --drop-after 10
```

Agents should report `PLAYING_AUTONOMOUS` and continue counting frames.

## Implemented

- Checks digest of directory file names and contents on both robots, plus frame count and rate.
- `PREPARE/READY`, `ARM/ARMED_ACK`, `COMMIT/COMMITTED_ACK`, `HEARTBEAT/STATUS`, `ABORT` before start.
- Session IDs reject old messages. Idempotent ACKs for retries.
- Abort if heartbeat disappears before start, but **continue mock playback** if heartbeat disappears after start.
- Per-robot motion cursor uses monotonic time, no frame correction on reconnect.

## Known limitations, must be addressed before SONIC/hardware

- No authentication, encryption, replay persistence, or authoritative controller-state check. Only use on an isolated trusted LAN for non-actuating tests.
- UDP does not permit atomic two-robot start if a partition occurs during the commit window. Redundant ACKs and prestart heartbeat lease reduce but do not eliminate risk. A robust deployment needs a separate prestart safety agreement and conservative launch policy.
- Real robot control failsafe and balance fault handling are **not implemented**.
- Playback end only changes a mock state; no standing transition is implemented.
- Agent trusts claimed `frames` and `fps`, which are passed as CLI arguments. Future SONIC integration must read actual loaded reference metadata.
- Wall-clock synchronization errors and network latency affect actual relative starts. Measure on the actual field network.
- The currently configured G1 SSH alias may connect over `192.168.123.164`, while UDP demo packets use Wi-Fi addresses. Verify both are the intended robots.
