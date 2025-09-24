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

# -----------------------------
# Config
# -----------------------------

MAX_TOKENS_PER_BATCH = 1024
REQUEST_TIMEOUT = 30
DEVICE = os.environ.get("ARGOS_DEVICE_TYPE", "cpu")  # "cuda" or "cpu"
API_HOST = "127.0.0.1"
API_PORT = 29999
SECRET = b"1145141919810"
MAX_RETRIES = 3
RETRY_DELAY = 6

# Caches
PKG_CACHE: dict[tuple[str, str], ARGOSPKG.Package] = {}
CT2_CACHE: dict[tuple[str, str], ctranslate2.Translator] = {}

# Zstd 压缩器/解压器
_ZC = zstd.ZstdCompressor(level=10)
_ZD = zstd.ZstdDecompressor()
# -----------------------------
# Helpers
# -----------------------------

# --- 新增：超时重试装饰器 ---
def retry_on_timeout(max_retries=MAX_RETRIES, delay=RETRY_DELAY, timeout=REQUEST_TIMEOUT):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    # 使用 asyncio.wait_for 来设置超时
                    result = await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
                    return result
                except (asyncio.TimeoutError, ConnectionError, struct.error) as e:
                    # 捕获超时、连接错误或数据帧不完整错误
                    logger.warning(
                        f"RPC call failed on attempt {attempt + 1}/{max_retries}. Error: {type(e).__name__}: {e}. "
                        f"Retrying in {delay} seconds..."
                    )
                    if attempt + 1 == max_retries:
                        # 如果是最后一次尝试，则重新引发异常，让上层捕获
                        logger.error("RPC call failed after all retries.")
                        raise
                    await asyncio.sleep(delay)
        return wrapper
    return decorator

def pack_frame(payload: bytes) -> bytes:
    c = _ZC.compress(payload)
    return struct.pack(">I", len(c)) + c

async def read_exactly(r, n):
    buf = b""
    while len(buf) < n:
        chunk = await r.read(n - len(buf))
        if not chunk: raise ConnectionError("peer closed")
        buf += chunk
    return buf
async def read_frame(r):
    ln, = struct.unpack(">I", await read_exactly(r, 4))
    return await read_exactly(r, ln)

def sign(ts, body): return hmac.new(SECRET, f"{ts}\n".encode()+body, hashlib.sha256).hexdigest()

@retry_on_timeout()
async def rpc(op: str, body_dict: dict):
    body = msgpack.packb(body_dict, use_bin_type=True)
    ts = int(time.time())
    outer = {"op": op, "ts": ts, "sig": sign(ts, body), "body": body}
    payload = msgpack.packb(outer, use_bin_type=True)
    reader, writer = await asyncio.open_connection(API_HOST, API_PORT)
    writer.write(pack_frame(payload)); await writer.drain()
    recv_body = await read_frame(reader)
    writer.close(); await writer.wait_closed()
    deco = _ZD.decompress(recv_body)
    resp = msgpack.unpackb(deco, raw=False)
    return resp

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

def unload_unused_cache(src: str, dst: str):
    for k in list(PKG_CACHE):
        if (src, dst) != k:
            PKG_CACHE.pop(k)
    for k in list(CT2_CACHE):
        if (src, dst) != k:
            CT2_CACHE.pop(k)
    gc.collect()

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
            task = await rpc("get", {"v": 1})
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
