# Robot Fleet Monitor

Local web dashboard that shows which robots (Unitree G1 on-board PCs) are
connected, with their IP, hostname, serial-number-based robot ID, uptime, and
network interfaces. Everything runs in Docker so the same code works on macOS
and Ubuntu.

**Monitor only.** The backend issues read-only inspection commands over SSH
(`hostname`, `ip addr`, `/proc/uptime`, device-tree serial). No motion, SONIC,
or controller commands are implemented yet.

## Run

```bash
cd fleet
docker compose up --build
# open http://localhost:8080
```

The container mounts `~/.ssh/id_rsa` by default. To use another key:

```bash
SSH_KEY=/path/to/key docker compose up --build
```

## Add robots

Edit `robots.yaml` (hot-reloaded every poll, no restart needed):

```yaml
robots:
  - name: g1-02
    host: 192.168.0.9
    user: unitree
    key: /keys/id_rsa
    role: G1 (SONIC on-board)
```

Press **Scan network** in the UI to TCP-probe port 22 across
`discovery.subnet` and identify Unitree hosts by hostname. Hosts not yet in
`robots.yaml` are flagged so you can add them.

## Robot ID

`robot_id` is the Jetson device-tree serial number when available (stable
across IP/hostname changes), falling back to hostname, then to the MAC of the
NIC that carries the configured IP.

## Layout

```
fleet/
  app/main.py         FastAPI app, polling loop, WebSocket push, /api/scan
  app/probe.py        read-only SSH probe + subnet scan (asyncssh)
  app/static/index.html  dashboard (vanilla JS, no build step)
  app/control.py      Control tab backend: dry-run commands, tmux pane view
  app/static/control.html  Control tab
  robots.yaml         robot list + discovery settings
  docker-compose.yml  one service, port 8080, mounts config + SSH key
```

## Time sync (chrony)

`docker-compose.yml` also runs a chrony NTP server (`timesync/`) on UDP 123 of
this PC. Robots are pointed at it so they share one clock and agree with each
other to ~1 ms, which is what synchronized commands will be scheduled against.

PC side starts with `docker compose up`. Robot side is a one-line chrony
source file, written once per robot (needs the robot's sudo password):

```bash
./timesync/install-robot.sh 192.168.0.8            # auto-detects this PC's IP
./timesync/install-robot.sh 192.168.0.9 192.168.0.58
```

It writes `/etc/chrony/sources.d/fleet.sources` and runs `chronyc reload
sources`. Nothing else on the robot is touched. Undo with
`sudo rm /etc/chrony/sources.d/fleet.sources && sudo chronyc reload sources`.

Set `timesync.pc_ip` in `robots.yaml` to this PC's LAN IP. The dashboard then
shows per robot whether it is synced to the fleet PC and the offset, and the
header shows whether the time server is answering.

## Control tab

`http://localhost:8080/control` has an E-stop strip, three controllers (Both,
and one per robot), the live tmux pane of each robot's SONIC session, and a
command log.

`control.dry_run` in `robots.yaml` decides what a click does (hot-reloaded):

- `true`: the command is only logged as the shell line that would run.
- `false` (**live, robots can move**): Initialize types the robot's `launch:`
  line into the `sonic_demo` tmux session, and every other button types one
  SONIC key into it with `tmux send-keys`. "Both" sends to all robots at once.

In Planner mode the direction buttons are hold-to-move: the key repeats
`control.hold_hz` times a second while the button is held, and stops on
release, when the tab loses focus, or 0.4 s after the browser stops answering.

E-STOP sends `O` (stop control and exit SONIC). It is a software stop over
Wi-Fi and SSH, not a safety stop: keep the physical e-stop in reach.

The state badges follow the buttons pressed here, corrected in live mode by
whether a SONIC process exists (`RUNNING` = found running, control state
unknown). Whether control is on, the Normal/Planner mode and the motion frame
are not read back from SONIC; watch the console.

Settings live under `control:` in `robots.yaml` and `launch:` on each robot.
Key meanings are in `app/control.py`.

Not implemented: the clock-synced countdown start, and reading real SONIC state.
