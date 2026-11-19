# Numbered SONIC motion references

This directory contains the 21 padded **G1 Moves dance** references listed below (293,704,683 bytes of per-motion files before LFS storage). The IDs match the original motion gallery. Karate and bonus clips are excluded; the numbering gaps are intentional. These references are separate from the earlier unpadded `converted/` data.

**Macarena (000)** is recorded in [`external_sources.json`](external_sources.json), with a pinned [original SONIC sample](https://github.com/NVlabs/GR00T-WholeBodyControl/tree/1fa5f7fa3966cbd4845c4e641d13c3f0cd5b0d9b/gear_sonic_deploy/reference/example/macarena_001__A545) and SHA-256 checksums for all eight files. The known baseline is unchanged: 1,375 frames at 50 Hz, 29 joints, and 14 body channels. Its trajectory files are linked at their original source rather than mirrored here because a separate motion-data redistribution license was not identified. To assemble a local combined library, use that sample or your existing matching baseline under `000__macarena_001__A545/`.

**BONES (001–029)** are listed in the same source index with their original names and numbers. Their CSVs are not mirrored: the BONES-SEED license prohibits public redistribution, including public GitHub mirrors. Obtain those files from the original gated dataset under its terms, or use your existing authorized local copies.

## Get the data

Install Git LFS before cloning:

```bash
git lfs install
git clone https://github.com/ProximaFortuna/G1motion.git
cd G1motion
git lfs pull --include='reference/sync_gallery90/*/*.csv'
```

A GitHub source ZIP may contain LFS pointer text instead of the arrays. `file_manifest.json` lists the byte count and SHA-256 of every per-motion file after LFS retrieval. `playlist.json` and `playlist.csv` describe the 21 included clips; external motions are listed separately so missing trajectories cannot be mistaken for installed references.

## Padding and format

Every included dance uses the reviewed Dad Dance preparation:

1. 2 seconds holding the G1 release controller's default standing pose.
2. 4 seconds blending into the source pose using a quintic curve for joints/root position and SO(3) interpolation for root orientation.
3. The source motion path, with 1-second playback-rate easing at each end.
4. 4 seconds blending out to the default standing joints at the final source XY position and yaw.
5. 2 seconds holding that neutral end pose.

The total timeline is the source duration plus 13 seconds. This preserves internal source discontinuities; it does not repair them. The six runtime CSV arrays and `metadata.txt` are byte-identical to the prepared motion library. Only provenance JSON paths were replaced with public source identifiers.

Each clip folder contains:

| File | Columns per frame | Convention |
| --- | --- | --- |
| `joint_pos.csv` | 29 | Radians, SONIC IsaacLab joint order |
| `joint_vel.csv` | 29 | Radians/second, same joint order |
| `body_pos.csv` | 90 | XYZ for 30 canonical bodies, world frame, meters |
| `body_quat.csv` | 120 | WXYZ for each body |
| `body_lin_vel.csv` | 90 | World-frame link-origin velocity, meters/second |
| `body_ang_vel.csv` | 90 | World-frame angular velocity, radians/second |
| `metadata.txt` | — | Body indexes, frame count, 50 Hz rate |
| `padding.json` | — | Padding parameters and source identifiers |
| `conversion.json` | — | Unpadded conversion details and exact joint/body ordering |

CSVs have one header row. Body arrays are flattened by body, then component. Velocities and forward kinematics were recomputed after padding. `conversion.json` describes the intermediate **before** padding; use `metadata.txt` or `playlist.json` for the final frame count and duration. Duration is `(frames - 1) / 50`.

This is reference data for an existing SONIC deployment. Installing it does not start playback. The existing loader does not sort motion directories, so numeric prefixes alone do not guarantee its Next/Previous order.

## Recorded validation

All references loaded through the existing SONIC C++ CSV reader. Each padded dance was evaluated once in MuJoCo from neutral with the installed G1 release encoder/decoder, original gains, and residual disabled. No physical assistance or state resets followed initialization. Controller file hashes and evaluation conditions are recorded in [`validation_provenance.json`](validation_provenance.json); no controller weights or SONIC code are included in this addition.

**20 of 21 included trials completed. `057 J_Dance7_Party` fell at 32.06 seconds during the dance and remains included.** [`simulation_results.json`](simulation_results.json) preserves every trial result. These are nominal simulation results, not hardware validation or evidence of robust tracking. The reviewed Dad Dance trial and its exact CSVs are retained.

| ID | Motion | Padded timeline (s) | Release-controller simulation |
| --- | --- | ---: | --- |
| 036 | B_DadDance | 54.80 | completed |
| 037 | B_LongDance | 132.42 | completed |
| 038 | B_SpiralDance | 60.78 | completed |
| 041 | J_Dance0_StepTouch | 45.46 | completed |
| 042 | J_Dance11_Gnarly | 58.12 | completed |
| 043 | J_Dance12_LushLife | 48.58 | completed |
| 045 | J_Dance18_TikTok | 30.92 | completed |
| 046 | J_Dance19_LetsGO | 37.82 | completed |
| 049 | J_Dance21_Blunt | 41.72 | completed |
| 050 | J_Dance22_Thrilling | 39.96 | completed |
| 051 | J_Dance23_MidnightSun | 61.56 | completed |
| 052 | J_Dance2_Salsa | 48.82 | completed |
| 053 | J_Dance3_Woah | 42.98 | completed |
| 054 | J_Dance4_Broadway | 40.92 | completed |
| 055 | J_Dance5_Hype | 44.58 | completed |
| 057 | J_Dance7_Party | 59.20 | fell at 32.06 s |
| 058 | J_Dance8_WestCoast | 52.90 | completed |
| 059 | J_Dance9_PeaceMaker | 71.32 | completed |
| 060 | J_ShortDance13_SingleLadies | 27.00 | completed |
| 061 | J_ShortDance14_Disco | 27.28 | completed |
| 062 | J_ShortDance15_Nineties | 26.10 | completed |

## Sources and licenses

**G1 Moves:** Mitch Chaiet / Experiential Technologies (2026), [G1 Moves](https://huggingface.co/datasets/exptech/g1-moves), revision [`895d064b2385725e6aabf540461c219afc3e0916`](https://huggingface.co/datasets/exptech/g1-moves/tree/895d064b2385725e6aabf540461c219afc3e0916). Licensed under [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/) ([full text](LICENSE-CC-BY-4.0.txt)). Upstream credits Mitch Chaiet and Jasmine Coro for these dance performances. Each playlist entry links to its original retarget CSV and records its hash.

Changes: resampled 60 Hz retarget CSVs to 50 Hz; subtracted initial horizontal root translation; reordered joints/bodies for SONIC; computed full-body forward kinematics and velocities; added neutral holds, entry/exit blends, and playback-rate easing; exported SONIC CSV references. No new human-to-robot retargeting or model training was performed. Credit the original dataset and indicate these changes when redistributing the derivatives.

**BONES selection:** Motion Data by [Bones Studio](https://bones.studio/), [BONES-SEED dataset](https://huggingface.co/datasets/bones-studio/seed), original revision `2f59b2077b9da34dd4e43618e705c7cb962c9a66`. Its [custom license](https://bones.studio/info/seed-license), including section 6's public-mirror restriction, applies to the source data. This repository includes the selection names and source links, not those trajectories.

**Macarena:** the pinned SONIC sample and [`upstream license`](https://github.com/NVlabs/GR00T-WholeBodyControl/blob/1fa5f7fa3966cbd4845c4e641d13c3f0cd5b0d9b/LICENSE) are linked for provenance. SONIC's source-code/model licenses do not explicitly identify a separate license for this third-party motion sample. Do not assume the G1 Moves license covers it.

The CC BY 4.0 license here applies to the G1 Moves motion derivatives; it does not relicense other repository code, data, or third-party assets.
