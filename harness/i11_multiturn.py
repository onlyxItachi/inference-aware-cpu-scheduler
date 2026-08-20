"""İŞ 11 — çok turlu (etkileşimli) kullanım: iddianın geçerli olduğu senaryo.

Politika "etkileşimli yerel LLM" için tasarlandı ama şimdiye kadar hiç
etkileşimli senaryoda ölçülmedi: her ölçüm **tek** bir prefill→decode
geçişi içeriyordu. Gerçek sohbet prefill→decode→prefill→decode…

İki şey aynı anda ilk kez sınanıyor:

1. **Geri dönüş yönü (decode→prefill).** Histerezis bandı yalnızca ileri
   yön verisinden seçildi. İleri yönde −115 ms'lik erken tetikleme bir
   avantajdı (thread'ler yerleşmiş oluyor). Geri dönüşte erken tetikleme
   ise **decode hâlâ sürerken E-core'ları açmak** demek — yani zararlı
   olabilir. Bilinmiyor.

2. **Kısa prefill rejimi.** `cache_prompt=true` ile 2. turdan itibaren
   prefill yalnızca yeni token'ları işler, yani kısalır. Dedektörün bilinen
   zayıf noktası tam orası (32 token'da prefill recall %82.7).

Politika bu kez **çift yönlü**: →decode maskeyi P8'e daraltır,
→prefill P8+E8'e genişletir. Önceki deneylerin hepsi tek yönlüydü.

Okuma:
  turlar arası QoS korunuyorsa  -> iddia "etkileşimli kullanım için" olur
  bozuluyorsa                   -> kapsam "tek turlu / uzun promptlu" diye
                                   daraltılır. İkisi de savunulabilir; şu an
                                   hangisi olduğu bilinmiyor.
"""

import argparse
import glob
import json
import os
import signal
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_lib as bl
import run_once as ro
from phase_switch import (P8, P8E8, sched_totals, cputime_jiffies,
                          set_affinity_all, read_energy_uj, HZ)

TURN_SUFFIX = ("\n\nSoru: Yukarıdaki açıklamayı bir paragrafta özetle ve "
               "en kritik noktayı vurgula.\n\nCevap: ")


class BiDirSwitcher(threading.Thread):
    """Çift yönlü faz dedektörü; her geçişte affinity uygular.

    Tek yönlü sürümden farkı: decode→prefill geçişinde maskeyi geri açar.
    Tüm geçişler zaman damgasıyla kaydedilir, böylece her turun sınırında
    dedektörün ne zaman ve hangi yönde karar verdiği görülebilir.
    """

    def __init__(self, pid, hi, lo, k, interval_s, armed):
        super().__init__(daemon=True)
        self.pid, self.hi, self.lo, self.k = pid, hi, lo, k
        self.interval_s = interval_s
        self.armed = armed
        self.stop_flag = threading.Event()
        self.transitions = []      # (t_ns, "prefill"|"decode", apply_us)
        self.state = "prefill"

    def run(self):
        prev = None
        run_len = 0
        while not self.stop_flag.is_set():
            t = bl.now_ns()
            sw, _ = sched_totals(self.pid)
            cj = cputime_jiffies(self.pid)
            if prev is not None and cj is not None and prev[1] is not None:
                cpu_s = (cj - prev[1]) / HZ
                norm = ((sw - prev[0]) / cpu_s) if cpu_s > 0 else 0.0
                target = None
                if self.state == "prefill" and norm > self.hi:
                    run_len += 1
                    if run_len >= self.k:
                        target = "decode"
                elif self.state == "decode" and norm < self.lo:
                    run_len += 1
                    if run_len >= self.k:
                        target = "prefill"
                else:
                    run_len = 0
                if target:
                    cost = None
                    if self.armed:
                        t0 = bl.now_ns()
                        set_affinity_all(
                            self.pid, P8 if target == "decode" else P8E8)
                        cost = (bl.now_ns() - t0) / 1000.0
                    self.state = target
                    self.transitions.append(
                        {"t_ns": t, "to": target, "apply_us": cost})
                    run_len = 0
            prev = (sw, cj)
            self.stop_flag.wait(self.interval_s)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server-bin", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--prompt", required=True)
    p.add_argument("--arm", required=True, choices=["A_P8", "SWITCH"])
    p.add_argument("--turns", type=int, default=5)
    p.add_argument("--n-predict", type=int, default=128)
    p.add_argument("--port", type=int, default=8111)
    p.add_argument("--hi", type=float, default=3000.0)
    p.add_argument("--lo", type=float, default=2100.0)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    if args.arm == "A_P8":
        cpus, t_dec, t_bat, armed = P8, 8, 8, False
    else:
        cpus, t_dec, t_bat, armed = P8E8, 8, 16, True

    cmd = ["taskset", "-c", ",".join(map(str, cpus)), args.server_bin,
           "-m", args.model, "-t", str(t_dec), "-tb", str(t_bat),
           "-c", "8192", "-b", "2048", "-ub", "512", "-np", "1",
           "--host", ro.HOST, "--port", str(args.port)]

    log = open(os.devnull, "wb")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    turns = []
    try:
        ro.wait_for_health(args.port, proc)
        ro.stream_completion(args.port, {
            "prompt": "Warmup.", "n_predict": 1, "temperature": 0,
            "stream": True, "cache_prompt": False})
        time.sleep(1.0)
        set_affinity_all(proc.pid, cpus)

        sw = BiDirSwitcher(proc.pid, args.hi, args.lo, 2, 0.020, armed)
        sw.start()
        time.sleep(0.3)

        e0 = read_energy_uj()
        convo = open(args.prompt).read()

        for turn in range(1, args.turns + 1):
            # cache_prompt=true: sunucu ortak öneki yeniden kullanır, yani
            # 2. turdan itibaren prefill YALNIZCA yeni tokenları işler.
            # Etkileşimli kullanımın gerçek şekli bu.
            t_sent, token_ts, text, _ = ro.stream_completion(args.port, {
                "prompt": convo, "n_predict": args.n_predict,
                "temperature": 0.0, "seed": 42, "stream": True,
                "cache_prompt": True, "ignore_eos": True})
            itl = [(token_ts[i] - token_ts[i - 1]) / 1e6
                   for i in range(1, len(token_ts))]
            s_itl = sorted(itl)
            turns.append({
                "turn": turn,
                "t_sent_ns": t_sent,
                "t_first_ns": token_ts[0],
                "t_last_ns": token_ts[-1],
                "ttft_ms": round((token_ts[0] - t_sent) / 1e6, 2),
                "itl_p50_ms": round(bl.percentile(s_itl, 50), 3),
                "itl_p95_ms": round(bl.percentile(s_itl, 95), 3),
                "itl_max_ms": round(s_itl[-1], 3),
                "decode_tps": round((len(token_ts) - 1) /
                                    ((token_ts[-1] - token_ts[0]) / 1e9), 3),
                "n_tokens": len(token_ts),
            })
            convo = convo + text + TURN_SUFFIX
            time.sleep(0.8)   # kullanıcının yazma/düşünme payı

        sw.stop_flag.set()
        sw.join(timeout=5)
        e1 = read_energy_uj()
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=20)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
        log.close()

    # Her tur sınırında dedektörün kararını yer-gerçeğine hizala.
    for t in turns:
        fwd = [x for x in sw.transitions
               if x["to"] == "decode" and t["t_sent_ns"] <= x["t_ns"] <= t["t_last_ns"]]
        # geri dönüş: bu turun decode'u bittikten sonraki ilk ->prefill
        back = [x for x in sw.transitions
                if x["to"] == "prefill" and x["t_ns"] >= t["t_last_ns"]]
        t["fwd_vs_first_token_ms"] = (
            round((fwd[0]["t_ns"] - t["t_first_ns"]) / 1e6, 1) if fwd else None)
        t["n_fwd_in_turn"] = len(fwd)
        t["back_after_last_token_ms"] = (
            round((back[0]["t_ns"] - t["t_last_ns"]) / 1e6, 1) if back else None)
        # decode SIRASINDA gelen ->prefill = zararlı erken geri dönüş
        early_back = [x for x in sw.transitions
                      if x["to"] == "prefill"
                      and t["t_first_ns"] < x["t_ns"] < t["t_last_ns"]]
        t["premature_back_in_decode"] = len(early_back)

    energy_j = ((e1 - e0) / 1e6) if (e0 and e1 and e1 >= e0) else None
    total_tok = sum(t["n_tokens"] for t in turns)
    out = {
        "arm": args.arm, "turns": args.turns, "n_predict": args.n_predict,
        "energy_j": round(energy_j, 1) if energy_j else None,
        "j_per_token": round(energy_j / total_tok, 3) if energy_j else None,
        "n_transitions": len(sw.transitions),
        "transitions": sw.transitions,
        "per_turn": turns,
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps({k: v for k, v in out.items() if k != "transitions"}))


if __name__ == "__main__":
    main()
