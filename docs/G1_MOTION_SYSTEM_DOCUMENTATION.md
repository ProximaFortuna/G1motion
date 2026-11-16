# G1motion: Motion Processing, SONIC Deployment, and Two-G1 Synchronization

**Project:** Georgia Tech LIDAR Lab, G1 football demonstration  
**Repository:** https://github.com/ProximaFortuna/G1motion  
**Documentation date:** 2026-11-15  
**Status:** Research prototype. Motion processing is implemented; dual-robot network coordination was exercised; synchronized physical playback has **not** been demonstrated.

> **Scope and provenance.** The repository's publicly visible `main` top level and the four root Python scripts were inspected when this document was written. GitHub did not expose the contents of the nested `g1_sync_software/` tree through the available read interface. Synchronization implementation details below are instead grounded in the local `sync_demo_bridge_fixed.py` bridge that was developed and tested during this project, plus recorded terminal results. **Do not assume the bridge file is identical to the current GitHub copy until compared.** Paths described as robot-local or historical are not asserted to exist in the reorganized Git repository.

## 1. Purpose and end-to-end architecture

The work has two related, but distinct pipelines:

1. **Motion preparation:** read retargeted Unitree G1 motions, convert joint order and representation to a SONIC-compatible reference, inspect numerical discontinuities, and repair selected segments for further evaluation.
2. **Two-G1 demonstration:** use the same, verified prerecorded Macarena on two robots running their **own local SONIC whole-body controllers**, and have a coordinator request a common start time through one Python agent per robot.

```text
G1 Moves retarget .pkl
        |
        v
 g1moves_to_sonic.py  ---> converted/<motion>/ (SONIC CSV reference)
        |                           |
        |                           +-- hardware_motion_audit.py
        |                           +-- inspect_discontinuities.py
        |                           +-- repair_salsa.py ---> repaired/J_Dance2_Salsa/
        |
        +--> offline simulation / motion inspection (required before hardware)

                        AURELIUS (coordinator)
                       PREPARE / ARM / COMMIT
                                  |
                     shared UTC start time T0
                           /              \
                G1 UDP agent            Lugan UDP agent
                      |                      |
                tmux sends 'T'          tmux sends 'T'
                      |                      |
               local SONIC WBC         local SONIC WBC
                      |                      |
                    G1                       Lugan
```

The motion-conversion scripts and the Python synchronization bridge are not themselves motor controllers. SONIC, running separately on each Jetson, remains responsible for policy inference, robot observations, and motor commands.

## 2. Current public GitHub repository structure

The current visible root of `main` is:

```text
G1motion/
├── converted/                  # Generated SONIC reference directories
├── dataset/                    # Original motion data (script references dataset/dance/)
├── g1_sync_software/           # Renamed/moved synchronization software directory
├── repaired/
│   └── J_Dance2_Salsa/        # Repaired Salsa reference
├── .gitignore
├── g1moves_to_sonic.py
├── hardware_motion_audit.py
├── inspect_discontinuities.py
└── repair_salsa.py
```

These entries are verified from the repository landing page. **The internal files and subdirectories of `g1_sync_software/`, `converted/`, and `dataset/` were not independently enumerated.** The exact placement of `sync_demo.py`, telemetry scripts, and prototype variants inside `g1_sync_software/` must be checked against your checkout. This guide deliberately avoids inventing a nested path.

### Local paths from the development sessions

Before the reorganization, the active coordinator ran at:

```text
~/LIDAR/g1_sync_v2/g1_sync_telemetry_v2/g1_sync_telemetry/sync_demo.py
```

The bridge was copied to each robot as `~/sync_demo.py`. These are **historical operational paths**, not the newly verified GitHub layout. On a fresh checkout, locate the real file with:

```bash
cd /path/to/G1motion
find g1_sync_software -type f \( -name 'sync_demo.py' -o -name '*telemetry*.py' \) -print
```

Do not blindly substitute old folder names into the reorganized repository.

## 3. Motion conversion and repair

### `g1moves_to_sonic.py`

**Input:** a trusted G1 Moves retarget `.pkl` containing `fps`, `root_pos`, `root_rot`, and `dof_pos`. The code expects 29 joint-angle columns, three root-position coordinates, and a four-component root quaternion per frame.

**Processing:**

- Validates shapes, non-finite values, frame rate, and nonzero quaternion norms.
- Reorders the 29 joint angles from G1 Moves order to SONIC's IsaacLab joint ordering, using an explicit permutation.
- Resamples joint angles and root positions by linear interpolation to the requested target FPS (default 50 Hz).
- Resamples root orientation with quaternion SLERP, converting source XYZW to output WXYZ.
- Computes `joint_vel.csv` by numerical differentiation.

**Output:** `joint_pos.csv`, `joint_vel.csv`, `body_pos.csv`, `body_quat.csv`, `metadata.txt`, `info.txt` within the named output directory. The root-only conversion does not synthesize full-body forward-kinematics outputs such as complete body velocities, so compatibility with a particular SONIC loader must be verified.

Example from repository root:

```bash
python3 g1moves_to_sonic.py \
  dataset/dance/J_Dance2_Salsa/retarget/J_Dance2_Salsa.pkl \
  converted/J_Dance2_Salsa \
  --fps 50
```

**Security:** Python pickle deserialization can execute code. Only use trusted source files.

### `hardware_motion_audit.py`

Reads each directory under `converted/` and checks numeric shape and finiteness of the 29 joint angles, joint velocities, root positions, and root quaternions. Reports finite-difference maximum joint speed and acceleration, root linear/angular speeds, root height, X/Y excursion, horizontal travel distance, and quaternion norm error.

```bash
python3 hardware_motion_audit.py
```

**Critical limitation:** This is a numerical inspection script. Its own output explicitly states it does **not** certify a motion as safe for hardware. It does not check complete dynamics, contacts, self-collision, or the robot's available stabilization authority.

### `inspect_discontinuities.py`

Compares the original source trajectory with converted SONIC CSVs around hard-coded suspicious timestamps. It checks maximum adjacent-frame joint changes, number of joints exceeding 0.15 rad between samples, and root position jumps. The configured clips are `B_LongDance`, `J_Dance2_Salsa`, `J_Dance4_Broadway`, `J_Dance8_WestCoast`, and `J_Dance17_Shuffle`.

```bash
python3 inspect_discontinuities.py
```

### `repair_salsa.py`

Operates on `converted/J_Dance2_Salsa` and writes to `repaired/J_Dance2_Salsa` rather than replacing its source. It treats discontinuities at **12.62 s** and **32.32 s** with experimental ±0.40 s repair windows. It blends joint angles and root positions using a quintic Hermite polynomial matching endpoint position, velocity, and acceleration. Root quaternions use SLERP with a quintic easing parameter. It recomputes joint velocities from the repaired position trajectory.

```bash
python3 repair_salsa.py
```

**Limitations:** These are trajectory-level smoothing operations, not dynamic feasibility proofs. The repair script labels the intervals simulation-only, and no hardware safety claim should be inferred from a visually smooth trace.

## 4. Runtime hardware configuration

The following values were observed in the hardware development sessions, not inferred from the new GitHub tree.

| Component | Original G1 | Lugan |
|---|---|---|
| SSH alias on Aurelius | `G1` | `Lugan` |
| Robot Wi-Fi IPv4 at test time | `192.168.0.8` | `192.168.0.42` |
| DDS robot-local interface | `enP8p1s0` | `enP8p1s0` |
| SONIC deployment directory | `~/sonic-residual-c374bae/gear_sonic_deploy` | same |
| Isolated SONIC reference directory | `reference/sync_macarena` | `reference/lugan_preflight` |
| Terminal session | `tmux` session `sonic_demo` | same |
| UDP agent port | `19041` | `19041` |

**Network note:** The two robot Wi-Fi addresses are on the TP-Link LAN, and each robot has its own separate DDS Ethernet network. Do not bridge their internal DDS networks or assume that identical private Ethernet IP addresses imply a conflict. Addresses may change after reboot or DHCP reassignment.

### SONIC models and inputs

SONIC is a separate project installed on each robot, not necessarily tracked inside `G1motion`. The verified deployment prefix `policy/release/model` means the **two actual files** are:

```text
policy/release/model_decoder.onnx
policy/release/model_encoder.onnx
policy/release/observation_config.yaml
planner/target_vel/V2/planner_sonic.onnx
```

Passing `policy/release/model` as the decoder input is incorrect, because the binary expects an ONNX file, not a filename prefix. The successful deployment used the prebuilt `target/release/g1_deploy_onnx_ref` executable; G1 CMake rebuilds had failed in bundled Cyclone DDS headers. Do not treat the broken rebuild as proof that the prebuilt binary cannot run.

### Known Macarena motion

SONIC loaded a single directory named `macarena_001__A545` with **1,375 timesteps at 50 Hz**, approximately **27.5 s** of playback timeline. Its eight hashed files were:

```text
body_ang_vel.csv     body_lin_vel.csv     body_pos.csv
body_quat.csv        joint_pos.csv        joint_vel.csv
info.txt             metadata.txt
```

Both agents reported the same content manifest:

```text
1db944f62a3280b20bb2d718f78148e37028742b0cedf83fca6c41c600d94ff2
```

This digest is the bridge's SHA-256 over **relative filenames and file bytes**, not simply `sha256sum` of one CSV. The isolated SONIC directory must contain exactly one motion subdirectory to avoid selecting a different reference.

### Hardware launch commands (only in a secured test environment)

From each robot's SONIC directory, start its tmux terminal (`tmux new -s sonic_demo`), then run the appropriate command **inside that session**. These call the existing executable without rebuilding:

**Original G1**

```bash
./target/release/g1_deploy_onnx_ref \
  enP8p1s0 policy/release/model_decoder.onnx reference/sync_macarena \
  --obs-config policy/release/observation_config.yaml \
  --encoder-file policy/release/model_encoder.onnx \
  --planner-file planner/target_vel/V2/planner_sonic.onnx \
  --input-type keyboard --output-type all
```

**Lugan**

```bash
./target/release/g1_deploy_onnx_ref \
  enP8p1s0 policy/release/model_decoder.onnx reference/lugan_preflight \
  --obs-config policy/release/observation_config.yaml \
  --encoder-file policy/release/model_encoder.onnx \
  --planner-file planner/target_vel/V2/planner_sonic.onnx \
  --input-type keyboard --output-type all --zmq-host localhost
```

SONIC's `Init Done` is not proof that active balance control has been enabled. In the tested keyboard workflow, `]` is the operator's control-activation input and `T` requests reference playback. Neither is a safety-rated control. These commands are historical known-good *arguments*, not a claim that either robot is currently safe or properly initialized.

**Lugan TensorRT caveat:** After a reboot, Lugan's separate `/home/unitree/TensorRT/lib/libnvinfer.so.10` failed to resolve `cudlaDeviceGetCount@libcudla.so.1` from the NVIDIA system library. The CUDA 12.6 copy of `libcudla.so.1` exported that symbol. A **process-local** `LD_PRELOAD=/usr/local/cuda-12.6/targets/aarch64-linux/lib/libcudla.so.1` was proposed as a targeted workaround; a successful complete SONIC startup with that workaround was **not verified in the provided terminal output**. Do not replace system CUDA libraries or assume cached TensorRT engines are portable between devices.

## 5. Python synchronization software

This section describes the available **`sync_demo_bridge_fixed.py` implementation** developed for the demo. Verify it matches `g1_sync_software/` in the reorganized GitHub checkout before publishing as an exact code reference.

### Roles

- **Coordinator:** One Python process on Aurelius. Sends UDP JSON messages to two addresses, requires matching motion manifests, chooses a shared future start time, and sends heartbeats/status requests.
- **Agent:** One Python process on each G1 Jetson, listening on UDP port `19041`. Reads the reference-directory hash and processes coordination state transitions. In hardware bridge mode, it attempts to send `T` to a named tmux session at start time.
- **SONIC:** Independent real-time controller running locally. The Python program does **not** stream commands to the joints and does not directly control 50 Hz playback frame advancement.

### Wire messages and state flow

```text
Coordinator                 G1 agent                    Lugan agent
    |                           |                             |
    |------ PREPARE ----------->|                             |
    |------ PREPARE ------------------------------------------>|
    |<----- READY + manifest ---|                             |
    |<----- READY + manifest ----------------------------------|
    |        compare manifest (digest, file count, frames, FPS)
    |------ ARM(T0) ----------->|                             |
    |------ ARM(T0) ------------------------------------------>|
    |<----- ARMED_ACK ---------|                             |
    |<----- ARMED_ACK -----------------------------------------|
    |------ COMMIT ----------->|                             |
    |------ COMMIT ------------------------------------------->|
    |<----- COMMITTED_ACK -----|                             |
    |<----- COMMITTED_ACK -------------------------------------|
    |------ HEARTBEAT -------->|                             |
    |------ HEARTBEAT ---------------------------------------->|
    |                     T0: tmux sends 'T' on each robot     |
```

- The wire format is UDP JSON with `v=1`, `type`, a random hexadecimal session ID, and message-specific fields.
- The coordinator retries PREPARE, ARM, and COMMIT requests while waiting for both acknowledgments.
- Agents reject attempts to PREPARE if busy or if their local readiness gate fails.
- The coordinator rejects mismatched motion content, number of files, frame count, or FPS.
- `ARM(T0)` must be between **2 and 30 seconds** ahead according to the agent's local wall clock; the agent converts it once into a monotonic deadline.
- Heartbeats are sent at roughly **10 Hz**; the agent uses a **0.6 s** timeout in the prototype. This is not a validated safety threshold.
- Before the start, missing heartbeat, missing COMMIT, lost readiness, or a received ABORT disarms the agent without intending to trigger playback.
- After the trigger, heartbeat loss switches the agent's *software model* to `PLAYING_AUTONOMOUS`; it does not kill SONIC. It also does not prove that actual robot playback continues correctly.

### Readiness and the single-use operator marker

The bridge uses the file `~/.g1_sync_operator_ready` to record explicit local operator approval. Its required contents are:

```text
G1 <motion_digest>
```

or on the other robot:

```text
Lugan <motion_digest>
```

The corrected readiness method checks for this marker, a tmux pane's controlling TTY, one relevant SONIC process on that TTY, keyboard input mode, and exactly one isolated motion directory resolving to the expected Macarena folder. **It does not query SONIC's internal policy/balance state.** Earlier versions incorrectly searched tmux scrollback for initialization text; that was removed after the check failed on both robots.

The marker is **deleted after the bridge successfully sends `T`**, so it must be deliberately recreated for any later run. A coordinator rejection after an earlier attempt may therefore be due to a consumed marker. Reauthorizing solely to suppress an error is unsafe: operators must verify physical conditions again.

### Trigger behavior and the unverified step

At the local deadline the bridge runs the equivalent of:

```bash
tmux send-keys -t sonic_demo -l T
```

The `-l` argument sends a literal `T` character. A successful subprocess return proves only that tmux accepted the operation. **It does not confirm SONIC consumed the input, that control was active, that playback started, or that the robot moved.** The previously observed `SENT T` and `STARTED SONIC keyboard-triggered playback` log lines were overly optimistic and should not be interpreted as actuator-state evidence.

### Mock frames and telemetry

After the trigger, the agent estimates:

```python
frame = min(frames - 1, int((monotonic_now - start_monotonic) * 50.0))
```

The logs explicitly print `mock frame`. This is **a software timeline estimate, not the actual SONIC reference index or observed robot phase**. With 1,375 frames, the estimate reaches its final frame in about 27.5 s, whether or not the robot moves.

Optional agent `--telemetry <file.csv>` produces a local approximately 10 Hz CSV with `robot`, `session`, `unix_s`, `monotonic_s`, `elapsed_s`, `frame`, `state`, and `t0_unix_s`. Previously paired telemetry showing very low phase differences validates the model's clock arithmetic, **not physical synchronization precision**. There is no observed joint-position feedback in the bridge's synchronization telemetry.

### Clock discipline

During development, the original G1 served Chrony/NTP on `192.168.0.8`, and Lugan and Aurelius followed it. The shared UTC timestamp is mapped to a local monotonic deadline at ARM time, so subsequent wall-clock adjustments do not intentionally jump the local software timeline.

This approach coordinates **nominal start requests**, not continuously synchronized SONIC reference frame indices. Wireless latency, interpreter scheduling, tmux injection, policy timing, and robot actuation add unmeasured error. **Continuous phase correction/interpolation was a requirement discussed for the final demonstration but has not been integrated into the running SONIC controllers.**

## 6. Operating the prototype

These commands reflect the previously tested CLI. The active coordinator path depends on where you placed `sync_demo.py` after reorganizing `g1_sync_software/`.

### Prerequisites before a live test

- Both robots physically secured against falling, operating area cleared, operators stationed at separate physical emergency stops.
- Each SONIC process running and confirmed to have loaded only `macarena_001__A545`.
- Each controller safely activated, stabilized, and independently assessed for readiness; `Init Done` is insufficient.
- Both agents use the **same** bridge version and motion manifest, with network/Chrony reachability checked.
- Fresh, deliberate single-use operator authorization on each robot.
- No other process or operator sending `T` during the coordinated test.

### Run software checks first

```bash
python3 sync_demo.py selftest
```

Reported regression checks covered matching hash/start and coordinator loss, autonomous software completion, pre-start heartbeat disarm, and manifest mismatch rejection. The tests were software-only.

### Agents, in two separate terminals

```bash
ssh G1 'python3 ~/sync_demo.py agent \
  --name G1 --port 19041 \
  --motion ~/sonic-residual-c374bae/gear_sonic_deploy/reference/example/macarena_001__A545 \
  --frames 1375 --sonic-session sonic_demo'
```

```bash
ssh Lugan 'python3 ~/sync_demo.py agent \
  --name Lugan --port 19041 \
  --motion ~/sonic-residual-c374bae/gear_sonic_deploy/reference/example/macarena_001__A545 \
  --frames 1375 --sonic-session sonic_demo'
```

Each process is long-running. A `listening on 0.0.0.0:19041` message means it is waiting for UDP commands, not hung. Starting a second agent on the same robot/port yields `OSError: [Errno 98] Address already in use`.

### Coordinator, separate terminal on Aurelius

**Warning:** This may trigger physical motion if both robots are armed and ready. Do not use it as a connectivity test.

```bash
python3 sync_demo.py coordinator \
  --robots 192.168.0.8:19041 192.168.0.42:19041 \
  --lead 10 --duration 30
```

`--lead 10` requests a start ten seconds in the future. `--duration 30` controls how long the coordinator remains in its monitoring loop; it **does not** command the robots to stop after 30 seconds.

### Deliberate operator authorization, after physical readiness verification

Each robot's authorization text is exactly `<robot_name> <bridge_digest>` followed by a newline. The digest is calculated from the approved Macarena directory using `digest_dir()` in the agent. Authorization should be created only as part of a supervised launch checklist, not automatically on process startup.

## 7. Stop behavior and safe operation

Stopping the coordinator or Python agents **does not stop SONIC playback** once the local controller has accepted the motion command. The bridge has **no safety-rated emergency-stop channel**. A physical emergency stop must remain accessible to each robot's operator. SONIC's `O` key is a software stop whose effect on balance must be separately verified. Killing SONIC or cutting power may cause the robot to fall. Never equate communications loss with a safe stop.

The system currently has no reliable remote emergency-stop guarantee, no independently verified hold-position transition, and no demonstrated supervised recovery from mid-motion faults. Avoid public or unsupported operation until these risks are resolved and physical timing/control tests pass.

## 8. Debugging history and known failure modes

| Symptom | Observed explanation | Action/interpretation |
|---|---|---|
| G1 CMake rebuild failed in bundled DDS headers | `StatusMask` incomplete type and `operator new(size_t)` compile errors | Existing prebuilt executable remained available; avoid unnecessary rebuild |
| Policy initialization failed with `Cannot find ONNX ... policy/release/model` | Passed a prefix rather than decoder filename | Use `policy/release/model_decoder.onnx` and matching `_encoder.onnx` |
| Lugan failed `undefined symbol: cudlaDeviceGetCount` | System `libcudla.so.1` lacked symbol expected by separate TensorRT install | Candidate CUDA 12.6 process-local preload; complete success not verified in session |
| `Address already in use` on UDP 19041 | A previous agent was still bound to the port | Reuse its terminal or stop that agent cleanly before launching another |
| PREPARE rejected `SONIC not operator-authorized and verified ready` | Generic readiness gate failure | Check marker, actual process and tmux session; earlier scrollback heuristic was unreliable |
| Coordinator rejected a subsequent run | Single-use authorization marker was consumed after trigger | Do a fresh physical readiness/authorization cycle, not a blind retry |
| Both agents showed `PLAYING_SYNCED mock frame ...`, robots did not move | Simulated timeline advanced independently of actual SONIC | Treat as failed *physical* integration; check that SONIC was activated with `]` and that it actually accepted `T` |
| Both tmux sessions disappeared | Robots had intentionally been shut down for battery replacement | Relaunch controllers and perform fresh checks after reboot |
| `No route to host` on both Wi-Fi IPs | Network was temporarily unavailable after battery/reboot cycle | Reestablish network routes and confirm live IPs before new launch |

During one observed coordinator run, both agents agreed on the start time and logged `SENT T`, but **neither robot physically moved**. In that attempt the operator had not pressed `]` to activate SONIC's controller. This is a plausible contributing factor, not proof that enabling `]` alone solves every trigger problem. A later independent manual `T` test demonstrated robot motion, but no successful two-robot synchronized physical dance was recorded in the provided history.

## 9. Validation evidence and remaining engineering work

| Capability | Evidence/status |
|---|---|
| Motion conversion and numerical analysis | Scripts present in GitHub root, reviewed |
| Repaired Salsa reference | `repair_salsa.py` and `repaired/J_Dance2_Salsa/` present; hardware validation not established |
| Identical Macarena content | Matching manifest reported for both robots |
| Agent/coordinator network handshake | PREPARE, READY, ARM, COMMIT observed in terminal logs |
| Chrony time sync | G1 master and clients configured and observed following during development |
| Agent software-timeline alignment | Mock telemetry and regression tests passed |
| Coordinator disappearance without terminating SONIC | Tested in mock software mode; bridge sends no controller shutdown |
| SONIC accepted synchronous triggers on both robots | **Not demonstrated** |
| Measured physical inter-robot motion offset | **Not measured** |
| Continuous SONIC frame-phase synchronization | **Not implemented** |
| Safety-rated stop and fault recovery | **Not implemented** |

### Engineering priorities

1. **Authoritative SONIC state interface:** report active control mode, loaded motion ID/hash, paused/playing state, current reference frame, and fault state, rather than inferring readiness from a process or terminal.
2. **Acknowledged scheduled playback:** confirm that both controllers actually accepted the scheduled start; fail closed if one is not ready before execution. A successful tmux injection is not an acknowledgment.
3. **Physical timing instrumentation:** compare motion onset and frame phase with timestamped robot/controller feedback or synchronized sensor measurements. Distinguish requested T0, accepted start, actual reference index, and physical actuation.
4. **Continuous synchronization, if required:** integrate a bounded, measured reference-phase adjustment into SONIC while protecting gait stability; the standalone scheduler experiments were not integrated into the controller.
5. **Operational safety:** test motion stop, hold/recovery, unexpected network loss, stale/mismatched sessions, low battery, and boot-cycle recovery under fall protection before public demonstration.
6. **Repository hygiene:** make the new `g1_sync_software/` tree self-contained with one authoritative `sync_demo.py`, a clear test entry point, `docs/`, and an explicit separation between source files, generated telemetry, and robot-specific launch configuration. Preserve the original working source in version control rather than accumulating similarly named copies in production paths.

## 10. Confirming the reorganized repository

On Aurelius, from the current local checkout, inspect without modifying files:

```bash
cd /path/to/G1motion
find . -maxdepth 4 -type f -not -path './.git/*' | sort
find g1_sync_software -type f -name '*.py' -print
```

The repository listing shown in Section 2 is the confirmed public root as inspected. File paths deeper than that must be reconciled with this output. Once reconciled, this documentation can live at `docs/G1_MOTION_SYSTEM_DOCUMENTATION.md` (recommended) without renaming or moving working scripts again.

---

**Bottom line:** We built motion-conversion and inspection utilities plus a two-agent, time-coordinated start-request prototype. We proved matching motion content and coordinator protocol operation. We have **not** yet proved that both physical G1s respond to those start requests synchronously. The remaining work is controller-state integration, acknowledgment, physical measurement, and fault-safe operation.
