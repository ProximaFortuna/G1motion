# Numbered SONIC motion references

This private library contains **51 motions** (354,918,530 bytes of per-motion files before LFS storage):

- **000:** the unchanged Macarena baseline, eight files, 1,375 frames at 50 Hz.
- **001–029:** 29 BONES references, without added padding.
- **036–062, with gaps:** the 21 remaining padded G1 Moves dances. The seven requested removals remain excluded; karate and bonus clips are excluded.

IDs match the original motion gallery and have not been renumbered. These references are separate from the earlier unpadded `converted/` data.

**Keep this repository and copies of its BONES data private for authorized internal use.** The [BONES-SEED license](https://bones.studio/info/seed-license) permits internal private copies under its terms and prohibits public dataset mirrors. Educational use does not remove that public-redistribution restriction. The G1 Moves CC BY 4.0 license does not apply to BONES or Macarena.

## Get the data

Install Git LFS, then clone with an authorized GitHub account:

```bash
git lfs install
git clone git@github.com:ProximaFortuna/G1motion.git
cd G1motion
git lfs pull --include='reference/sync_gallery90/*/*.csv'
```

A source ZIP may contain LFS pointer text instead of the arrays. `file_manifest.json` lists the byte count and SHA-256 of every per-motion file after LFS retrieval. `playlist.json` and `playlist.csv` describe all 51 included clips. `external_sources.json` retains the upstream source and license links for Macarena and BONES, with `included: true` and expected file checksums.

## Padding and format

Only the G1 Moves dances have the reviewed Dad Dance preparation:

1. 2 seconds holding the G1 release controller's default standing pose.
2. 4 seconds blending into the source pose using a quintic curve for joints/root position and SO(3) interpolation for root orientation.
3. The source motion path, with 1-second playback-rate easing at each end.
4. 4 seconds blending out to the default standing joints at the final source XY position and yaw.
5. 2 seconds holding that neutral end pose.

The padded timeline is the source duration plus 13 seconds. This preserves internal source discontinuities; it does not repair them. Macarena and BONES receive no extra neutral padding. All runtime CSVs and `metadata.txt` are byte-identical to the prepared motion library; provenance JSON paths use source identifiers instead of internal server paths.

Every clip contains six runtime CSV arrays and `metadata.txt`:

| File | Columns per frame | Convention |
| --- | --- | --- |
| `joint_pos.csv` | 29 | Radians, SONIC IsaacLab joint order |
| `joint_vel.csv` | 29 | Radians/second, same joint order |
| `body_pos.csv` | 90; 42 for Macarena | XYZ per body, world frame, meters |
| `body_quat.csv` | 120; 56 for Macarena | WXYZ per body |
| `body_lin_vel.csv` | 90; 42 for Macarena | World-frame link-origin velocity, meters/second |
| `body_ang_vel.csv` | 90; 42 for Macarena | World-frame angular velocity, radians/second |
| `metadata.txt` | — | Body indexes and frame count; 50 Hz references |

CSVs have one header row. Body arrays are flattened by body, then component. BONES and G1 Moves have 30 canonical body channels. Macarena retains its original 14 selected body channels, whose mapping is in `metadata.txt`.

G1 Moves folders also contain `padding.json` and `conversion.json`; the latter describes the intermediate before padding, so use `metadata.txt` or the playlist for final dimensions and duration. BONES folders contain `conversion.json`. Macarena retains its original `info.txt`. Duration is `(frames - 1) / 50`.

This is reference data for an existing SONIC deployment. Installing it does not start playback. The existing loader does not sort motion directories, so numeric prefixes alone do not guarantee its Next/Previous order.

## Recorded validation

All reference arrays were previously loaded through the existing SONIC C++ CSV reader; the repository copies are checked against the prepared arrays. No new controller trials were run for this copy operation.

The **21 included padded G1 Moves dances** each have one recorded MuJoCo trial from neutral with the installed G1 release encoder/decoder, original gains, and residual disabled. No physical assistance or state resets followed initialization. **20 of those 21 trials completed; `057 J_Dance7_Party` fell at 32.06 seconds and remains included.** `simulation_results.json` contains those 21 trial records only. Macarena was previously hardware-tested according to the operator's report; this addition does not establish release-controller performance for the BONES selection. Existing `previous_v11_*` BONES metrics refer to the earlier controller, not the installed G1 release controller.

Controller file hashes and conditions are in `validation_provenance.json`. Simulation completion does not establish hardware safety or robust tracking. No SONIC controller code, weights, gains, or configuration are added or changed here.

| ID | Motion | Padded | Timeline (s) | Recorded release-controller status |
| --- | --- | --- | ---: | --- |
| 000 | macarena_001__A545 | no | 27.48 | previously tested baseline, per user |
| 001 | egypt_dance_R_002__A140 | no | 4.58 | no release-controller trial recorded |
| 002 | dance_basic_fourth_entry_position_R_002__A308_M | no | 5.04 | no release-controller trial recorded |
| 003 | dance_basic_head_accent_R_fast_001__A308 | no | 2.70 | no release-controller trial recorded |
| 004 | dance_retro_clap_step_R_003__A310 | no | 6.26 | no release-controller trial recorded |
| 005 | dance_retro_clap_step_variation_R_002__A306 | no | 5.28 | no release-controller trial recorded |
| 006 | dance_retro_disco_finger_down_up_R_002__A306_M | no | 3.26 | no release-controller trial recorded |
| 007 | dance_retro_disco_finger_horizontal_R_002__A307 | no | 7.04 | no release-controller trial recorded |
| 008 | victory_dance_brick_brick_slide_slide_R_002__A308 | no | 5.12 | no release-controller trial recorded |
| 009 | victory_dance_robot_dance_180_R_003__A306 | no | 12.76 | no release-controller trial recorded |
| 010 | victory_dance_robot_dance_180_R_003__A310_M | no | 8.64 | no release-controller trial recorded |
| 011 | dance_retro_charleston_jump_R_001__A309_M | no | 2.88 | no release-controller trial recorded |
| 012 | dance_basic_padeburee_R_fast_002__A307 | no | 6.54 | no release-controller trial recorded |
| 013 | victory_dance_orange_justice_180_R_001__A309 | no | 7.72 | no release-controller trial recorded |
| 014 | victory_dance_ymca_R_002__A308 | no | 9.00 | no release-controller trial recorded |
| 015 | dance_hiphop_flintstones_kick_ball_change_R_003__A312 | no | 9.24 | no release-controller trial recorded |
| 016 | dance_hiphop_2_step_270_R_002__A311 | no | 7.68 | no release-controller trial recorded |
| 017 | dance_hiphop_2_step_270_R_003__A311 | no | 7.08 | no release-controller trial recorded |
| 018 | dance_hiphop_alt_stump_R_003__A313 | no | 6.00 | no release-controller trial recorded |
| 019 | dance_hiphop_bart_simpson_R_001__A311_M | no | 10.26 | no release-controller trial recorded |
| 020 | dance_hiphop_bounce_180_R_002__A313 | no | 7.30 | no release-controller trial recorded |
| 021 | dance_hiphop_bounce_to_feed_R_002__A314_M | no | 3.22 | no release-controller trial recorded |
| 022 | dance_hiphop_cabath_path_R_001__A312 | no | 10.60 | no release-controller trial recorded |
| 023 | dance_hiphop_happy_feet_R_001__A313_M | no | 5.54 | no release-controller trial recorded |
| 024 | dance_hiphop_kick_it_variation_R_002__A315_M | no | 9.40 | no release-controller trial recorded |
| 025 | dance_hiphop_kid_n_play_R_001__A312_M | no | 11.00 | no release-controller trial recorded |
| 026 | dance_latino_chase_mambo_R_fast_001__A314 | no | 8.44 | no release-controller trial recorded |
| 027 | dance_latino_mambo_180_mambo_360_R_001__A313 | no | 9.28 | no release-controller trial recorded |
| 028 | dance_hiphop_floss_R_002__A312_M | no | 7.58 | no release-controller trial recorded |
| 029 | moonwalk_R_001__A533 | no | 7.20 | no release-controller trial recorded |
| 036 | B_DadDance | yes | 54.80 | completed |
| 037 | B_LongDance | yes | 132.42 | completed |
| 038 | B_SpiralDance | yes | 60.78 | completed |
| 041 | J_Dance0_StepTouch | yes | 45.46 | completed |
| 042 | J_Dance11_Gnarly | yes | 58.12 | completed |
| 043 | J_Dance12_LushLife | yes | 48.58 | completed |
| 045 | J_Dance18_TikTok | yes | 30.92 | completed |
| 046 | J_Dance19_LetsGO | yes | 37.82 | completed |
| 049 | J_Dance21_Blunt | yes | 41.72 | completed |
| 050 | J_Dance22_Thrilling | yes | 39.96 | completed |
| 051 | J_Dance23_MidnightSun | yes | 61.56 | completed |
| 052 | J_Dance2_Salsa | yes | 48.82 | completed |
| 053 | J_Dance3_Woah | yes | 42.98 | completed |
| 054 | J_Dance4_Broadway | yes | 40.92 | completed |
| 055 | J_Dance5_Hype | yes | 44.58 | completed |
| 057 | J_Dance7_Party | yes | 59.20 | fell at 32.06 s |
| 058 | J_Dance8_WestCoast | yes | 52.90 | completed |
| 059 | J_Dance9_PeaceMaker | yes | 71.32 | completed |
| 060 | J_ShortDance13_SingleLadies | yes | 27.00 | completed |
| 061 | J_ShortDance14_Disco | yes | 27.28 | completed |
| 062 | J_ShortDance15_Nineties | yes | 26.10 | completed |

## Sources and licenses

**G1 Moves:** Mitch Chaiet / Experiential Technologies (2026), [G1 Moves](https://huggingface.co/datasets/exptech/g1-moves), revision `895d064b2385725e6aabf540461c219afc3e0916`. Licensed under [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/) ([full text](LICENSE-CC-BY-4.0.txt)). Upstream credits Mitch Chaiet and Jasmine Coro for these dance performances. Each playlist entry links to its original retarget CSV and records its hash.

Changes: resampled 60 Hz retarget CSVs to 50 Hz; subtracted initial horizontal root translation; reordered joints/bodies for SONIC; computed full-body forward kinematics and velocities; added neutral holds, entry/exit blends, and playback-rate easing; exported SONIC CSV references. No new human-to-robot retargeting or model training was performed. Credit the original dataset and indicate these changes when redistributing the G1 Moves derivatives.

**BONES selection:** Motion Data by [Bones Studio](https://bones.studio/), [BONES-SEED dataset](https://huggingface.co/datasets/bones-studio/seed), revision `2f59b2077b9da34dd4e43618e705c7cb962c9a66`. Use of the underlying data is subject to the [BONES-SEED Dataset License Agreement](https://bones.studio/info/seed-license). These converted references are private internal-use copies. Joint/body order, resampling, initial XY removal, and recomputed forward kinematics/velocities are documented in each `conversion.json`. No extra neutral padding was applied. Public mirrors and redistribution are not authorized by this repository.

**Macarena:** unchanged [SONIC sample](https://github.com/NVlabs/GR00T-WholeBodyControl/tree/1fa5f7fa3966cbd4845c4e641d13c3f0cd5b0d9b/gear_sonic_deploy/reference/example/macarena_001__A545) at revision `1fa5f7fa3966cbd4845c4e641d13c3f0cd5b0d9b`. All eight files match the known baseline and pinned source. The [upstream license](https://github.com/NVlabs/GR00T-WholeBodyControl/blob/1fa5f7fa3966cbd4845c4e641d13c3f0cd5b0d9b/LICENSE) and file hashes are recorded in the source index. It is retained here as a private research baseline, not relicensed under G1 Moves' CC BY 4.0 terms.

The CC BY 4.0 license here applies to G1 Moves derivatives only. Other data, code, and third-party assets retain their respective terms.
