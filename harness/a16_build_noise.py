"""2c / U2 — rakip metriğinin kendi gürültü tabanı.

"Rakip build −%3.7" iddiası, build duvar süresinin gürültüsü hiç
ölçülmeden yapıldı. Eğer `make -j16`'nın koşular arası CV'si %3.7'yi
yutuyorsa "iki taraflı kazanç" cümlesi düşer.

Ayrıca her koşunun gerçekten aynı işi yaptığı BELGELENMELİ: ccache
devredeyse ikinci koşu birinciden yapısal olarak hızlıdır ve ölçülen şey
zamanlayıcı değil önbellektir. Aynısı page cache için de geçerli --
burada kasten DÜŞÜRÜLMÜYOR (drop_caches root ister ve gerçek senaryo da
sıcak cache'tir), ama durum her koşuda kaydediliyor ki sistematik bir
kayma varsa görünsün.
"""

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_lib as bl


def hygiene(build_dir):
    """Her koşunun aynı başlangıç noktasından gittiğini belgeler."""
    info = {}
    info["ccache_on_path"] = shutil.which("ccache") is not None
    # CMake ccache'i launcher olarak bağlamış olabilir; asıl belirleyici bu.
    rules = os.path.join(build_dir, "CMakeCache.txt")
    info["cmake_compiler_launcher"] = None
    if os.path.exists(rules):
        for line in open(rules, errors="ignore"):
            if "COMPILER_LAUNCHER" in line:
                info["cmake_compiler_launcher"] = line.strip()
                break
    n_o = sum(1 for r, _d, fs in os.walk(build_dir) for f in fs
              if f.endswith(".o"))
    info["objects_present_before"] = n_o
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith(("Cached:", "MemAvailable:")):
                    k, v = line.split(":")
                    info[k.strip().lower() + "_kb"] = int(v.split()[0])
    except OSError:
        pass
    return info


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--build-dir", default="llama.cpp/build-compete")
    p.add_argument("--runs", type=int, default=20)
    p.add_argument("--cooldown", type=int, default=15)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    recs = []
    print(f"[a16] {args.runs} temiz build, -j16, rakipsiz", flush=True)
    for i in range(1, args.runs + 1):
        subprocess.run(["find", args.build_dir, "-name", "*.o", "-delete"],
                       check=True)
        hyg = hygiene(args.build_dir)
        if i > 1:
            time.sleep(args.cooldown)
        t0 = bl.now_ns()
        temp0 = bl.package_temp_c()
        r = subprocess.run(["make", "-C", args.build_dir, "-j16"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wall = (bl.now_ns() - t0) / 1e9
        rec = {"run": i, "wall_s": round(wall, 3), "rc": r.returncode,
               "temp_start_c": temp0, "temp_end_c": bl.package_temp_c(),
               **hyg}
        recs.append(rec)
        print(f"  {i:2d}/{args.runs}  {wall:6.2f}s  rc={r.returncode}  "
              f"objs_before={hyg['objects_present_before']}  "
              f"T={temp0}->{rec['temp_end_c']}", flush=True)

    ok = [r["wall_s"] for r in recs if r["rc"] == 0]
    mean = statistics.mean(ok)
    sd = statistics.stdev(ok)
    summary = {
        "n": len(ok), "mean_s": round(mean, 3),
        "median_s": round(statistics.median(ok), 3),
        "stdev_s": round(sd, 3), "cv_pct": round(sd / mean * 100, 3),
        "min_s": round(min(ok), 3), "max_s": round(max(ok), 3),
        "spread_pct": round((max(ok) - min(ok)) / mean * 100, 2),
    }
    json.dump({"summary": summary, "runs": recs}, open(args.out, "w"), indent=1)
    print(f"\n[a16] n={summary['n']}  medyan {summary['median_s']}s  "
          f"CV %{summary['cv_pct']}  yayılım %{summary['spread_pct']}")
    print(f"  -> iddia edilen kazanç %3.7 bu tabanın "
          f"{'ÜSTÜNDE' if 3.7 > summary['cv_pct'] * 2 else 'İÇİNDE/YAKININDA'}")


if __name__ == "__main__":
    main()
