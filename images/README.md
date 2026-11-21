# Shared Podman base image

`fr-base/cpu:1` contains Debian, Git, uv, Node and basic build tools. Build it
once with rootless Podman on WSL:

```sh
podman build -t localhost/fr-base/cpu:1 images/base-cpu
```

Tasks reference the base through `[environment] docker_image`. The runner
mounts canonical Python dependencies, Rust toolchains and caches, pinned
harnesses and optional toolkit binaries from the benchmark store. It copies
each repo snapshot into the trial's writable layer. For setup commands and
store locations, see [running benchmarks](../docs/running.md). For the native
pytortch verification subset, see [the Podman integration checks](../docs/spikes.md#sections-34-integration-checks).
