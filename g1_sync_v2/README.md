# G1 synchronized timeline V2 (software only)

No SONIC, ROS, Unitree SDK, or physical motor control. The server listens on TCP port 8765 without authentication. Use only on an isolated trusted LAN.

Run on Aurelius from the project directory:

    python3 -m py_compile agent.py coordinator.py
    ssh G1 'cp ~/g1_sync_agent.py ~/g1_sync_agent.py.v1.bak'
    ssh Lugan 'cp ~/g1_sync_agent.py ~/g1_sync_agent.py.v1.bak'
    scp agent.py G1:~/g1_sync_agent.py
    scp agent.py Lugan:~/g1_sync_agent.py

Stop previous agents in their terminals with Ctrl+C, then restart:

    ssh G1 'python3 ~/g1_sync_agent.py --name G1'
    ssh Lugan 'python3 ~/g1_sync_agent.py --name Lugan'

Use separate terminals for the agents. On Aurelius:

    python3 coordinator.py --g1 192.168.0.8 --lugan 192.168.0.42 --motion J_Dance2_Salsa --duration 60 --start-delay 10

Copy robot tick logs back after completion:

    scp G1:~/g1_sync_logs/G1_<mission_id>.csv .
    scp Lugan:~/g1_sync_logs/Lugan_<mission_id>.csv .

## Timing

Each agent samples a local *monotonic* clock at 50 Hz. Coordinator monotonic time is estimated using round-trip probes. Clock estimate correction is slewed at most 50 microseconds per tick. Robot CSV files contain each local scheduler timestamp, estimated coordinator timestamp, playback elapsed time, frame index, and recent clock calibration information. The logs are not proof of absolute clock accuracy, as errors due to path asymmetry remain. Coordinator status requests are sequential and should not be compared as simultaneous measurements. Before physical motion, integrate at the reference-time sampling layer, interpolate motion smoothly, validate observation history, measure actual joint tracking and timebase uncertainty, and implement safe-stop and authenticated communications.
