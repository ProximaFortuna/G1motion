# G1 synchronized clock timeline proof of concept

Software-only: **does not start SONIC, press T, send Unitree commands or move a robot**.

## Install (no external Python packages)

Copy `agent.py` to both Jetsons, start on each:

```bash
python3 agent.py --name G1
python3 agent.py --name Lugan
```

The TCP agent listens on port 8765; restrict this port to the trusted demo LAN (no built-in authentication). Do **not** expose to the internet or untrusted campus LAN.

On Aurelius:

```bash
python3 coordinator.py --g1 192.168.0.8 --lugan 192.168.0.42 --motion J_Dance2_Salsa --duration 20 --start-delay 8
```

## What is synchronized?

- Before arming, coordinator samples each agent's wall-clock offset using a 4-timestamp NTP-like approximation, chooses the lowest-RTT sample, and sends the estimated offset.
- Each robot agent schedules an absolute coordinator-time start and determines its reference frame using `floor(50 * (estimated_coordinator_now - T0))`. The agent does **not** increment a frame counter and drift independently.
- Coordinator periodically resamples clock offsets during execution; agent low-pass-adjusts corrections to avoid sudden phase discontinuities.
- Agents print first scheduler-tick timestamps and timeline phase. They perform no joint commands.

## Limits and required future engineering

- Python on general Linux plus Wi-Fi is **not a hard real-time clock synchronization system**. RTT asymmetry biases offset estimates; the reported skew is estimated using those same offsets and is not ground truth.
- A phase may skip frames if the scheduler runs late. SONIC must support interpolation and timeline sampling rather than a naive keyboard-T trigger. Integrating into the policy loop requires code-specific review.
- A shared `T0` does not guarantee identical physical movements, dynamics or actuator delay. Measure using independent telemetry/video after safe deployment.
- Implement authenticated transport, bounded clock-drift tolerance, controller-specific safety gates and independent emergency stops before any hardware integration.
- If one robot starts and the other fails, this demo code does not stop the first. This is intentional: there is **no actuator stop interface** in the software proof of concept. Do not connect this code to actuators without implementing an independently tested safe abort.
