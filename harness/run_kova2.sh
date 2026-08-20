#!/bin/sh
# KOVA 2 zinciri. i14 (Pareto cephesi) bitene kadar bekler, sonra kalan
# ölçümleri SIRAYLA koşar -- paralel koşmak ölçüm hijyenini bozar.
#
# Sıra kasıtlı: membw en başta, çünkü bellek bant genişliğini doyuruyor ve
# yanında hiçbir şey koşmamalı; en kısa olan da o.
set -e
cd "$(dirname "$0")/.."

SRV=llama.cpp/build/bin/llama-server
MODEL=models/Qwen3.5-9B-Q4_K_M.gguf

echo "### i14 bitmesi bekleniyor..."
while pgrep -f "i14_frontier.py" >/dev/null 2>&1; do sleep 20; done
echo "### i14 bitti, kova 2 başlıyor: $(date +%H:%M:%S)"

echo
echo "### 2d — bellek bant genişliği tabanı (membw)"
mkdir -p results/membw
for t in 4 8 16 24; do harness/membw "$t"; done | tee results/membw/membw.txt

echo
echo "### 1a ek koşular — c4 ve c8'i n=6'ya çıkar"
for r in 04 05 06; do
  python3 harness/h5_capture.py --server-bin "$SRV" --model "$MODEL" \
    --prompt harness/prompt_512.txt --cpus 0,2,4,6 --threads 4 \
    --port 8171 --out "results/h5_cores/r${r}_c4.json"
  sleep 20
  python3 harness/h5_capture.py --server-bin "$SRV" --model "$MODEL" \
    --prompt harness/prompt_512.txt --cpus 0,2,4,6,8,10,12,14 --threads 8 \
    --port 8171 --out "results/h5_cores/r${r}_c8.json"
  sleep 20
done

echo
mkdir -p results/build_noise
echo "### 2c — build gürültü tabanı (20 koşu)"
python3 harness/a16_build_noise.py --runs 20 \
  --out results/build_noise/summary.json 2>&1 | tail -30

echo
echo "### 2b — çekişmeli gürültü tabanı (20 koşu)"
python3 harness/a17_contended_noise.py --server-bin "$SRV" --model "$MODEL" \
  --runs 20 --outdir results/contended_noise 2>&1 | tail -30

echo
echo "### 2f — chrt --idle genellemesi (18 koşu)"
python3 harness/a18_idle_build.py --server-bin "$SRV" --model "$MODEL" \
  --rounds 6 --outdir results/idle_build 2>&1 | tail -30

echo
echo "### KOVA 2 BİTTİ: $(date +%H:%M:%S)"
