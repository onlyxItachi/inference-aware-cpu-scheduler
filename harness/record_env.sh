#!/usr/bin/env bash
# Captures everything needed to reproduce a measurement session.
# Run once per session; the output belongs next to the CSV it describes.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/results/phase0/env.txt}"
mkdir -p "$(dirname "$OUT")"

{
  echo "=== captured ==="
  date -Is
  echo
  echo "=== kernel / os ==="
  uname -a
  [ -f /etc/os-release ] && grep PRETTY_NAME /etc/os-release
  echo
  echo "=== llama.cpp ==="
  git -C "$ROOT/llama.cpp" log -1 --format='commit %H%ncommitted %cI'
  echo "cmake flags: -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=OFF -DGGML_BLAS=OFF -DGGML_VULKAN=OFF -DGGML_NATIVE=ON -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF"
  echo "compiler: $(gcc --version | head -1)"
  echo "arch flag: -march=native"
  echo "backends built:"
  ls "$ROOT/llama.cpp/build/bin/" | grep -E '^libggml-(cpu|cuda|blas|vulkan)' || true
  echo
  echo "=== model ==="
  for m in "$ROOT"/models/*.gguf; do
    [ -e "$m" ] || continue
    echo "path: $m"
    echo "bytes: $(stat -c %s "$m")"
    echo "sha256: $(sha256sum "$m" | cut -d' ' -f1)"
  done
  echo
  echo "=== cpu ==="
  lscpu | grep -Ei 'model name|^cpu\(s\)|thread|core|socket|cache'
  echo "governor: $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)"
  echo "driver:   $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_driver)"
  echo "no_turbo: $(cat /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null || echo n/a)"
  echo "per-cpu max freq (kHz):"
  for c in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/cpuinfo_max_freq; do
    idx="${c#*/cpu}"; idx="${idx%%/*}"
    printf "  cpu%-2s %s\n" "$idx" "$(cat "$c")"
  done
  echo
  echo "=== sched_ext ==="
  cat /sys/kernel/sched_ext/state 2>/dev/null || echo "not present"
  echo
  echo "=== memory ==="
  free -h | head -2
  echo
  echo "=== thermal at capture ==="
  sensors 2>/dev/null | grep -iE 'package|Tctl' || echo "n/a"
} > "$OUT" 2>&1

echo "-> $OUT"
