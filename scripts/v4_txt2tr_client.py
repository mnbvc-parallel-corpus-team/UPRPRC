# -*- coding: utf-8 -*-
"""
High-throughput Argos Translate client (package-native paths)
- SBD: package_path/stanza
- CT2: package_path/model
- Tokenizer: pkg.tokenizer (single SentencePiece for both src & tgt)

Server API:
  GET  /?ver=1         -> {"taskid", "src", "dst", "data":[paras...]}
  POST /upl2           <- {"src","dst","pairs":[[src_text, translation], ...]}
"""

import os
os.environ["ARGOS_DEVICE_TYPE"] = "cuda"
import time
import gc
from datetime import datetime
from typing import List, Tuple

import requests
import argostranslate.translate as ARGOS
import argostranslate.package as ARGOSPKG
import ctranslate2
import stanza
from tqdm import tqdm

# -----------------------------
# Config
# -----------------------------

API = os.environ.get("API", "http://127.0.0.1:29999")
MAX_TOKENS_PER_BATCH = int(os.environ.get("MAX_TOKENS", "1024"))
ALLOW_COMPRESS = {"accept-encoding": "gzip, deflate, br"}
REQUEST_TIMEOUT = 240
DEVICE = os.environ.get("ARGOS_DEVICE_TYPE", "cpu")  # "cuda" or "cpu"

# Caches
PKG_CACHE: dict[tuple[str, str], ARGOSPKG.Package] = {}
CT2_CACHE: dict[tuple[str, str], ctranslate2.Translator] = {}
STANZA_CACHE: dict[str, stanza.Pipeline] = {}  # keyed by source lang (pipeline只依赖src)

# -----------------------------
# Helpers
# -----------------------------

def get_or_install_package(src: str, dst: str) -> ARGOSPKG.Package:
    """Return Argos package for (src,dst), install if missing."""
    if (src, dst) in PKG_CACHE:
        return PKG_CACHE[(src, dst)]
    # 先尝试已安装
    for P in ARGOSPKG.get_installed_packages():
        if P.from_code == src and P.to_code == dst:
            PKG_CACHE[(src, dst)] = P
            return P
    # 不在本地则安装
    ARGOSPKG.update_package_index()
    for cand in ARGOSPKG.get_available_packages():
        if cand.from_code == src and cand.to_code == dst:
            print("install", cand)
            cand.install()
            break
    # 再次检索已安装
    for P in ARGOSPKG.get_installed_packages():
        if P.from_code == src and P.to_code == dst:
            PKG_CACHE[(src, dst)] = P
            return P
    raise RuntimeError(f"Argos package {src}->{dst} not found after install.")

def get_translator(src: str, dst: str, pkg: ARGOSPKG.Package) -> ctranslate2.Translator:
    """Create or reuse CTranslate2 translator from package_path/model."""
    key = (src, dst)
    tr = CT2_CACHE.get(key)
    if tr is None:
        model_dir = pkg.package_path / "model"
        tr = ctranslate2.Translator(
            str(model_dir),
            device=DEVICE,
            # compute_type=("float16" if DEVICE == "cuda" else "int8"), # 这个不能用，不然翻出来是错的
            inter_threads=max(2, (os.cpu_count() or 8)//4),
            intra_threads=max(1, (os.cpu_count() or 8)//2),
            # max_queued_batches=8,
        )
        CT2_CACHE[key] = tr
    return tr

def translate_fast(
    sentences: List[str],
    pkg: ARGOSPKG.Package,
    translator: ctranslate2.Translator,
    max_tokens_per_batch: int,
) -> List[str]:

    tokenizer = pkg.tokenizer
    encoded = [tokenizer.encode(s) for s in sentences]

    # target_prefix = None
    # if getattr(pkg, "target_prefix", ""):
        # target_prefix = [[pkg.target_prefix]] * 1  # 将在每批时扩展到批大小

    translate_kwargs = dict(
        num_hypotheses=1,
        # batch_type="tokens",
        max_batch_size=max_tokens_per_batch,
        return_scores=False,
        replace_unknowns=True,
        length_penalty=0.2,
        beam_size=1,
    )

    # 5) 翻译
    preds: List[str] = ["" for _ in sentences]

    # 每批设置与批大小匹配的 target_prefix（如果需要）
    kw = translate_kwargs.copy()
    # if target_prefix is not None:
        # kw["target_prefix"] = [target_prefix[0]] * len(encoded)
    outs = translator.translate_batch(encoded, **kw)
    for i, out in enumerate(outs):
        out_tokens = out.hypotheses[0]
        text = tokenizer.decode(out_tokens)
        # 去掉可选的 target_prefix 前缀文本
        # tp = getattr(pkg, "target_prefix", "")
        # if tp and text.startswith(tp):
            # text = text[len(tp):]
        if text.startswith(" "):  # 对齐 apply_packaged_translation 的处理
            text = text[1:]
        preds[i] = text
    return preds, sum(len(x) for x in encoded)

# -----------------------------
# 主循环
# -----------------------------
def main():
    print(f"[client] API={API}  MAX_TOKENS_PER_BATCH={MAX_TOKENS_PER_BATCH}  DEVICE={DEVICE}")
    while True:
        # 取任务
        try:
            r = requests.get(f"{API}/", headers=ALLOW_COMPRESS, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            task = r.json()
        except Exception as e:
            print("[client] fetch error:", e)
            time.sleep(5); continue

        if not task or task.get("taskid", -1) == -1:
            time.sleep(5); continue

        src = task["src"]; dst = task["dst"]; data = task["data"]
        if not data:
            continue

        # 包 + 引擎 + SBD
        pkg = get_or_install_package(src, dst)
        translator = get_translator(src, dst, pkg)

        # 翻译
        t0 = datetime.now()
        try:
            outs, token_count = translate_fast(
                data, pkg, translator,
                max_tokens_per_batch=MAX_TOKENS_PER_BATCH
            )
        except Exception as e:
            print("[client] translate error:", e)
            time.sleep(1); continue
        t1 = datetime.now()

        # 回传（无状态：原文与译文成对）
        try:
            payload = {"src": src, "dst": dst, "pairs": list(zip(data, outs))}
            rr = requests.post(f"{API}/u", json=payload, headers=ALLOW_COMPRESS, timeout=REQUEST_TIMEOUT)
            rr.raise_for_status()
        except Exception as e:
            print("[client] upload error:", e)
            time.sleep(3)
            try:
                rr = requests.post(f"{API}/u", json=payload, headers=ALLOW_COMPRESS, timeout=REQUEST_TIMEOUT)
                rr.raise_for_status()
            except Exception as e2:
                print("[client] upload error (2nd):", e2)

        secs = (t1 - t0).total_seconds()
        print(f"[client] {t1}  batch {len(data)} paras {token_count} tokens {secs:.3f}s  ~{token_count/max(1e-12,secs):.4f}tk/s")
        gc.collect()

if __name__ == "__main__":
    main()
