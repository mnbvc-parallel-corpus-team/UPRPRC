import asyncio
import functools
import hmac
import struct
import time
from typing import Dict, Iterable, List, Optional, Tuple
import hashlib
import gc
import os

import ctranslate2
import msgpack
import regex
import zstandard as zstd
from loguru import logger
import stanza
import argostranslate.package as ARGOSPKG

_ZC = zstd.ZstdCompressor(level=10)
_ZD = zstd.ZstdDecompressor()
LMDB_MAP_SIZE_BYTES = 100 << 30
TR_LMDB_MAP_SIZE = 42 << 30
SBD_LMDB_MAP_SIZE = int(LMDB_MAP_SIZE_BYTES)
MAX_SKEW = 7200  # 秒，允许的时钟偏差
API_SECRET = b"1145141919810"
TARGET_LANG = 'en'
ORDER2LANG = ['ar', 'zh', 'en', 'fr', 'ru', 'es', 'de',]
EN_LANG_ORDER = 2
NON_EN_LANG_IDX = (0, 1, 3, 4, 5, 6)
MAX_RETRIES = 3
RETRY_DELAY = 6
REQUEST_TIMEOUT = 30
API_HOST = "127.0.0.1"
API_PORT = 29999

def make_key(src_lang: str, dst_lang: str, src_text: str) -> bytes:
    """SHA-256 结果作为 LMDB key（32B），既短又稳"""
    h = hashlib.sha256()
    h.update(src_lang.encode("utf-8")); h.update(b"\x00")
    h.update(dst_lang.encode("utf-8")); h.update(b"\x00")
    # h.update(normalize_text(src_text).encode("utf-8"))
    h.update(src_text.encode("utf-8"))
    return h.digest()  # 32 bytes

def digest_string_list(s: Iterable[str]):
    h = hashlib.sha256()
    for i in s:
        h.update(i.encode("utf-8"))
        h.update(b"\x00")
    return h.digest()

def serialize_lcs_align_res(aligned, pairs):
    return _ZC.compress(msgpack.packb([aligned, pairs], use_bin_type=True))

def deserialize_lcs_align_res(b):
    return msgpack.unpackb(zstd.ZstdDecompressor().decompress(b), raw=False)

def kv_put_many(env, items: List[Tuple[bytes, bytes]]):
    with env.begin(write=True) as txn:
        for k, v in sorted(items, key=lambda x:x[0]):
            txn.put(k, v, overwrite=True)

def kv_get_many(env, keys: List[bytes]) -> Dict[bytes, Optional[bytes]]:
    out = {k: None for k in keys}
    with env.begin(write=False) as txn:
        cursor = txn.cursor()
        # 使用 cursor.getmulti() 批量读取，效率更高
        for k, v in cursor.getmulti(keys):
            out[k] = v
    return out

def lmdb_usage(env):
    info = env.info()     # 含 map_size
    stat = env.stat()     # psize / branch_pages / leaf_pages / overflow_pages / entries
    p = stat["psize"]
    used_pages = stat["branch_pages"] + stat["leaf_pages"] + stat["overflow_pages"] + 2  # +2 个元页
    used_bytes = used_pages * p
    free_bytes_est = info["map_size"] - used_bytes
    high_water_bytes = (info["last_pgno"] + 1) * stat["psize"]
    return {
        "map_size": info["map_size"],
        "page_size": p,
        "used_bytes": used_bytes,
        "last_pgno": info["last_pgno"],
        "free_bytes_estimate": max(0, free_bytes_est),
        "entries": stat["entries"],
        "high_water_bytes": high_water_bytes,
        "high_water_ratio": high_water_bytes / info["map_size"],
        "num_readers": info.get("numreaders"),
    }

def lmdb_compact_migrate():
    """sbd过程中分配的页面过多没有完全被使用"""
    import lmdb
    import const
    src = lmdb.open(str(const.V4_SBD_DIR), readonly=True, lock=True, max_dbs=1, subdir=True)
    try:
        from pathlib import Path
        compact_path = Path(r"X:\v4_sbd3")
        compact_path.mkdir(exist_ok=True)
        src.copy(str(compact_path), compact=True)
    except Exception as e:
        import traceback
        exc = traceback.format_exc()
        print(exc.encode("utf-8"))

IS_MEANINGFUL = {
    # 用字符类 + 交集，并开启 VERSION1 语法
    'ar': regex.compile(r'(?V1)[\p{Arabic}&&\p{L}]'),      # 阿拉伯字母
    'zh': regex.compile(r'(?V1)\p{Han}'),                  # 任意汉字
    'ru': regex.compile(r'(?V1)[\p{Cyrillic}&&\p{L}]'),    # 西里尔字母
    # 拉丁系：只要是“拉丁脚本的字母”即可（含变音/扩展）
    'fr': regex.compile(r'(?V1)[\p{Latin}&&\p{L}]'),
    'es': regex.compile(r'(?V1)[\p{Latin}&&\p{L}]'),
    'de': regex.compile(r'(?V1)[\p{Latin}&&\p{L}]'),
    # 如果你想把英语限制为 ASCII 26 字母，保留这一条；否则也可用上面的 Latin+L
    'en': regex.compile(r'[A-Za-z]'),
}
def is_meaningful_line(s: str, lang: str) -> bool:
    pat = IS_MEANINGFUL.get(lang)
    return bool(pat.search(s))

def encode_sentences(sentences: List[str], src_lang: str, dst_lang: str) -> bytes:
    return _ZC.compress(msgpack.packb([sentences, src_lang, dst_lang], use_bin_type=True))

def decode_sentences(data: bytes) -> Tuple[List[str], str, str]:
    return msgpack.unpackb(_ZD.decompress(data), raw=False)

def encode_value(s: str) -> bytes:
    return _ZC.compress(s.encode("utf-8"))

def decode_value(b: bytes) -> str:
    return _ZD.decompress(b).decode("utf-8")

def pack_frame(payload: bytes) -> bytes:
    c = _ZC.compress(payload)
    return struct.pack(">I", len(c)) + c

async def read_exactly(reader: asyncio.StreamReader, n: int) -> bytes:
    buf = []
    cnt = 0
    while cnt < n:
        chunk = await reader.read(n - cnt)
        if not chunk:
            raise ConnectionError("peer closed")
        buf.append(chunk)
        cnt += len(chunk)
    return b"".join(buf)

async def read_frame(reader: asyncio.StreamReader) -> bytes:
    hdr = await read_exactly(reader, 4)
    (ln,) = struct.unpack(">I", hdr)
    return await read_exactly(reader, ln)
def sign(ts: int, body_bytes: bytes) -> str:
    return hmac.new(API_SECRET, f"{ts}\n".encode() + body_bytes, hashlib.sha256).hexdigest()
def verify(ts: int, body_bytes: bytes, sig_hex: str):
    if abs(time.time() - ts) > MAX_SKEW:
        raise ValueError("timestamp out of window")
    exp = sign(ts, body_bytes)
    if not hmac.compare_digest(exp, sig_hex):
        raise ValueError("bad signature")

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

# Caches
PKG_CACHE: dict[tuple[str, str], ARGOSPKG.Package] = {}
CT2_CACHE: dict[tuple[str, str], ctranslate2.Translator] = {}
STANZA_CACHE = {}

def get_or_install_package(src: str, dst: str) -> ARGOSPKG.Package:
    """Return Argos package for (src,dst), install if missing."""
    _c = PKG_CACHE.get((src, dst))
    if _c: return _c
    for P in ARGOSPKG.get_installed_packages():
        if P.from_code == src and P.to_code == dst:
            PKG_CACHE[(src, dst)] = P
            return P
    ARGOSPKG.update_package_index()
    for cand in ARGOSPKG.get_available_packages():
        if cand.from_code == src and cand.to_code == dst:
            print("install", cand)
            cand.install()
            break
    for P in ARGOSPKG.get_installed_packages():
        if P.from_code == src and P.to_code == dst:
            PKG_CACHE[(src, dst)] = P
            return P
    raise RuntimeError(f"Argos package {src}->{dst} not found after install.")

def build_stanza(src_lang: str, pkg, use_gpu=True) -> stanza.Pipeline:
    """Create or reuse a Stanza tokenizer-only pipeline for src_lang from package's stanza/"""
    pipe = STANZA_CACHE.get(src_lang)
    if pipe is None:
        pipe = stanza.Pipeline(
            lang=src_lang,
            processors="tokenize",
            use_gpu=use_gpu,
            dir=str(pkg.package_path / "stanza"),
            logging_level="WARNING",
        )
        STANZA_CACHE[src_lang] = pipe
    return pipe
def sbd_with_stanza(pipe: stanza.Pipeline, text: str) -> List[str]:
    doc = pipe(text)
    out: List[str] = []
    for s in doc.sentences:
        if hasattr(s, "text"):
            val = s.text.strip()
        elif hasattr(s, "tokens"):
            val = "".join([t.text_with_ws for t in s.tokens]).strip()
        else:
            val = ""
        if val:
            out.append(val)
    return out

def unload_unused_cache(src: str, dst: str):
    for k in list(PKG_CACHE):
        if (src, dst) != k:
            PKG_CACHE.pop(k)
    for k in list(CT2_CACHE):
        if (src, dst) != k:
            CT2_CACHE.pop(k)
    for k in list(STANZA_CACHE):
        if src != k:
            STANZA_CACHE.pop(k)
    gc.collect()

def get_translator(src: str, dst: str, pkg: ARGOSPKG.Package) -> ctranslate2.Translator:
    """Create or reuse CTranslate2 translator from package_path/model."""
    key = (src, dst)
    tr = CT2_CACHE.get(key)
    if tr is None:
        model_dir = pkg.package_path / "model"
        tr = ctranslate2.Translator(
            str(model_dir),
            device=os.environ.get("ARGOS_DEVICE_TYPE", "cpu"),
            # compute_type=("float16" if DEVICE == "cuda" else "int8"), # 这个不能用，不然翻出来是错的
            inter_threads=max(2, (os.cpu_count() or 8)//4),
            intra_threads=max(1, (os.cpu_count() or 8)//2),
            # max_queued_batches=8,
        )
        CT2_CACHE[key] = tr
    return tr

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

if __name__ == "__main__":
    # import lmdb
    # import const
    # tr_env = lmdb.open(
    #     str(const.V4_TR_DIR),
    #     # map_size=TR_LMDB_MAP_SIZE,
    #     subdir=True,
    #     readonly=True,
    #     lock=True,
    #     max_dbs=1,
    #     readahead=True,
    # )
    # print(lmdb_usage(tr_env))
    # sbd_env = lmdb.open(
    #     # str(const.WORK_DIR / "v4_sbd"),
    #     str(const.V4_SBD_DIR),
    #     # map_size=SBD_LMDB_MAP_SIZE,
    #     subdir=True,
    #     readonly=True,
    #     lock=True,
    #     max_dbs=1,
    #     readahead=True,
    # )
    # print(lmdb_usage(sbd_env))
    # ftxt_env = lmdb.open(
    #     str(const.V4_FTXT_DIR),
    #     map_size=LMDB_MAP_SIZE_BYTES,
    #     subdir=True,
    #     readonly=True,
    #     lock=True,
    #     max_dbs=1,
    #     readahead=True,
    # )
    # print(lmdb_usage(ftxt_env))
    lmdb_compact_migrate()