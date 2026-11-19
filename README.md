# G1motion

Motion conversion, SONIC reference data, and two-G1 synchronization experiments.

**Private research repository.** This checkout includes BONES-derived motion data for internal use. Keep the repository and its data archives private; the BONES-SEED license prohibits public data mirrors.

- [Numbered motion library](reference/sync_gallery90/README.md): 51 references — Macarena (000), 29 unpadded BONES clips (001–029), and 21 padded G1 Moves dances with their original gallery IDs preserved. The seven removed dances remain excluded.
- [System documentation](docs/G1_MOTION_SYSTEM_DOCUMENTATION.md): conversion tools, deployment configuration, synchronization prototype, and validation limits.
- `converted/` contains the earlier conversions; `repaired/` contains the experimental Salsa repair. The numbered runtime references are in `reference/sync_gallery90/`.

The numbered motion CSVs use [Git LFS](https://git-lfs.com/). Install Git LFS, clone this private repository using an authorized account, and run `git lfs pull` from the checkout to retrieve the actual arrays.

Motion Data by [Bones Studio](https://bones.studio/). Use of the underlying BONES data is subject to the [BONES-SEED Dataset License Agreement](https://bones.studio/info/seed-license). The G1 Moves derivatives retain their upstream CC BY 4.0 license. See the [library attribution and source notes](reference/sync_gallery90/README.md#sources-and-licenses).
