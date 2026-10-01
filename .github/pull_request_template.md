## What and why

<!-- One or two sentences. Link the issue if there is one. -->

## Checklist

- [ ] `make test` passes (tests/run.sh), and new behaviour has a test
- [ ] `make lint` is clean: shellcheck, `bash -n` and Python syntax
- [ ] Works on bash 3.2: `make lint BASH_N=/bin/bash` on macOS, no bash 4+ features
- [ ] `scripts/lint-portability.sh` passes (it runs in `make lint`)
- [ ] A line under `[Unreleased]` in CHANGELOG.md
- [ ] Fictional data only: session names, tab titles, paths and ids in tests, demo and docs come from the demo world or the neutral test set
- [ ] If docs/img changed: `make scrub` passes and every frame was looked at
