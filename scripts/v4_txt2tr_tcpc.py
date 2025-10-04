import functools
import os
os.environ["ARGOS_DEVICE_TYPE"] = "cuda"
import asyncio
import hashlib
import traceback

import msgpack
import hmac
import struct
import time
import gc
from datetime import datetime
from typing import List

import argostranslate.package as ARGOSPKG
import ctranslate2
import zstandard as zstd
from loguru import logger

from v4_helpers import unload_unused_cache, rpc, get_or_install_package, get_translator, \
    API_HOST, API_PORT

# -----------------------------
# Config
# -----------------------------

MAX_TOKENS_PER_BATCH = 1024
DEVICE = os.environ.get("ARGOS_DEVICE_TYPE", "cpu")

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
async def tcp_main():
    logger.info(f"[client] API={API_HOST}:{API_PORT}  MAX_TOKENS_PER_BATCH={MAX_TOKENS_PER_BATCH}  DEVICE={DEVICE}")
    while True:
        # 取任务
        try:
            task = await rpc("g", {"v": 1})
            # r = requests.get(f"{API}/", headers=ALLOW_COMPRESS, timeout=REQUEST_TIMEOUT)
            # r.raise_for_status()
            # task = r.json()
        except Exception as e:
            logger.error(f"[client] fetch error: {traceback.format_exc()} SLEEP 5s")
            time.sleep(5); continue
        task_o = task.get("o", -1)
        if task_o != 0:
            logger.warning(f"task o == {task_o}, SLEEP 5s")
            time.sleep(5); continue

        src = task["s"]; dst = task["t"]; data = task["p"]
        logger.info(f"{datetime.now()} recv task: {src}>{dst} sentences:{len(data)}")

        # 包 + 引擎 + SBD
        pkg = get_or_install_package(src, dst)
        translator = get_translator(src, dst, pkg)

        # 对于内存不足的机器，需要把用不到的模型卸载
        if os.environ.get("MSAVE", ""):
            unload_unused_cache(src, dst)

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
        secs = (t1 - t0).total_seconds()
        logger.info(f"[client] {t1} batch {len(data)} paras {token_count} tokens {secs:.3f}s  ~{token_count/max(1e-12,secs):.4f}tk/s")
        
        try:
            resp = await rpc("u", {"s": src, "t": dst, "p": list(zip(data, outs))})
            logger.info(f"submit done. resp: {resp}")
            # rr = requests.post(f"{API}/u", json=payload, headers=ALLOW_COMPRESS, timeout=REQUEST_TIMEOUT)
            # rr.raise_for_status()
        except Exception as e:
            logger.error(f"[client] upload error: {e}")
            # time.sleep(3)
        gc.collect()
if __name__ == "__main__":
    asyncio.run(tcp_main())
