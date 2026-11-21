# Canonical environment

The validation host used Linux x86-64, kernel 6.18.57, Debian 13 with glibc 2.41-12+deb13u4, Bubblewrap 0.12.0, and GCC/G++ 14.2.0. The CPython base is 3.12.14 at `/opt/codex/runtimes/codex-primary-runtime/dependencies/python`. This host path is also the guest path, since the staged environments reference it. Staging pins and distribution-manifest hashes are in `environment.lock`. The validated runtime used uv 0.13.9.

| Task | Runner group | Independent dependencies |
| --- | --- | --- |
| C35 | c35 | PyTorch CPU and locked dependencies |
| C02 | c02 | NumPy and locked Python packages |
| C45 | c45-c48 | Locked Python packages. LangGraph-owned packages load from the trial |
| C37 | c37 | CPython 3.14.10 and 3.14.10t directories `toolchain-c37/gil` and `toolchain-c37/free` |
| C04 | c04 | Reuse the c35 Python runtime. Rust 1.100.0 and staged registry crates |
| C13 | c13 | CMake 4.4.5 and Ninja 1.13.2 |
| C48 | c45-c48 | Locked Python packages. Agents SDK loads from the trial |

Stage the applicable wheelhouse outside the trial. The PyTorch distribution is the CPython 3.12 x86-64 CPU wheel from https://download.pytorch.org/whl/cpu, version `2.15.0+cpu`, with git hash `d0f2af8b66b20da4baa50644c0cd3f887a2eae2e`. Other versions are pinned in requirements files. Install the exact staged wheels using `WHEELHOUSE=/absolute/path BENCH_PYTHON=/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3.12 bash stage.sh GROUP`. For C04, create a link named `c04` to `c35` within runtime, and install the platform Rust toolchain under `toolchain-c04`. Acquire the locked registry crates before grading and vendor them into `toolchain-c04/vendor` by running `cargo vendor --locked --offline <absolute vendor directory>` from `trials/C04/bindings/python`. The config in the trial refers to the guest mount. No build outputs from acquired source should be staged. C37 uses the two standard standalone CPython builds. C13 uses the CMake distribution's `bin` and `share` trees and the Ninja executable under `toolchain-c13/bin`.

For a session use `bash runtime/run.sh GROUP trials/CANDIDATE bash` or supply the fixture command instead of `bash`. Pass exactly one candidate directory per run. The mount contains the selected trial, third-party toolchain and dependencies, isolated temporary space, and host system tools. The seccomp filter is inherited by children and denies IPv4 and IPv6 sockets while allowing UNIX multiprocessing sockets. There is no stage cache, host home, other trial or author directory in the guest. Keep the base system site-packages hidden.

These packaging files pin and describe the dependency assets. Stage the dependency binaries and wheels separately before offline trials. The task and author archives themselves contain source and validation records.
