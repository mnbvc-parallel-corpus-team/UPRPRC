import asyncio
import hmac
import os
import pickle
from queue import Empty
import gc
import hashlib
import struct
import time
import traceback
from pathlib import Path
from typing import List, Tuple, Dict, Optional
import multiprocessing as mp

from loguru import logger
import lmdb
import msgpack
import zstandard as zstd

import const

# =========================
# 配置
# =========================
TARGET_LANG = 'en'
TQUEUE_SIZE = 65536
MAX_SKEW = 7200  # 秒，允许的时钟偏差
API_SECRET = b"1145141919810"
HOST = "0.0.0.0"
PORT = 29999
TASK_GEN_WORKERS = 2
LMDB_MAP_SIZE_BYTES = 100 << 30
# 不够可以热扩 `env.set_mapsize(new_size)`.

# LMDB 环境参数
const.V4_TR_DIR.mkdir(exist_ok=True)

# Zstd 压缩器/解压器
_ZC = zstd.ZstdCompressor(level=10)
_ZD = zstd.ZstdDecompressor()

def make_key(src_lang: str, dst_lang: str, src_text: str) -> bytes:
    """SHA-256 结果作为 LMDB key（32B），既短又稳"""
    h = hashlib.sha256()
    h.update(src_lang.encode("utf-8")); h.update(b"\x00")
    h.update(dst_lang.encode("utf-8")); h.update(b"\x00")
    # h.update(normalize_text(src_text).encode("utf-8"))
    h.update(src_text.encode("utf-8"))
    return h.digest()  # 32 bytes

# =========================
# 数据集与任务生成
# =========================

def task_gen(q: mp.Queue, rank: int):
    """
    只下发“未命中的段落”给 worker。
    服务器无状态：worker 回传 (src_text, translation) 对即可写入缓存。
    """
    import argostranslate.package as ARGOSPKG
    import stanza

    PKG_CACHE = {}
    STANZA_CACHE = {}
    order2lang = ['ar', 'zh', 'en', 'fr', 'ru', 'es', 'de',]
    env = lmdb.open(
        str(const.V4_TR_DIR),
        map_size=LMDB_MAP_SIZE_BYTES,
        subdir=True,
        readonly=True,
        lock=True,
        max_dbs=1,
        readahead=True,     # 顺序读友好
    )
    def kv_get_many(keys: List[bytes]) -> Dict[bytes, Optional[bytes]]:
        """批量读（逐个 get）；LMDB 读极快，这样做简单稳定"""
        out = {k: None for k in keys}
        with env.begin(write=False) as txn:
            for k in keys:
                v = txn.get(k)
                if v is not None:
                    out[k] = v
        return out
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
    def build_stanza(src_lang: str, stanza_dir: str) -> stanza.Pipeline:
        """Create or reuse a Stanza tokenizer-only pipeline for src_lang from package's stanza/"""
        pipe = STANZA_CACHE.get(src_lang)
        if pipe is None:
            pipe = stanza.Pipeline(
                lang=src_lang,
                processors="tokenize",
                use_gpu=True,
                dir=stanza_dir,
                logging_level="WARNING",
            )
            STANZA_CACHE[src_lang] = pipe
        return pipe
    def sbd_with_stanza(pipe: stanza.Pipeline, text: str) -> List[str]:
        doc = pipe(text)
        # 统一抽取句子文本
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
    while 1:
        fcount = 0
        exists_task = False
        for fn in const.V4_DOCUMENT_CACHE.iterdir():
            fcount += 1
            if hash(fn.name) % TASK_GEN_WORKERS != rank:
                continue
            with fn.open("rb") as f:
                pkl = pickle.load(f)
            for row in pkl:
                valid_jn_fp = []
                sizes = row['sizes']
                for i in range(7):
                    if order2lang[i] == 'en':
                        continue
                    doc_size = sizes[i * 3 + 2]
                    job_number = row['job_numbers'][i]
                    flattxt_file = const.CONVERT_TEXT_FLATTEN_TABLE_CACHE_DIR / f"{job_number}.txt"
                    if doc_size > 0 and flattxt_file.exists() and flattxt_file.stat().st_size > 0:
                        valid_jn_fp.append(i)
                if len(valid_jn_fp) > 1:
                    for i in valid_jn_fp:
                        job_number = row['job_numbers'][i]
                        flattxt_file = const.CONVERT_TEXT_FLATTEN_TABLE_CACHE_DIR / f"{job_number}.txt"
                        src_lang = order2lang[i]
                        with flattxt_file.open("r", encoding="utf-8") as f:
                            paras = f.read().split('\n\n')
                        if not paras:
                            continue
                        pkg = get_or_install_package(src_lang, TARGET_LANG)
                        stanza_pipe = build_stanza(src_lang, str(pkg.package_path / "stanza"))
                        sentences: List[str] = []
                        for p in paras:
                            sents = sbd_with_stanza(stanza_pipe, p)
                            sentences.extend(sents)
                        sentences = list(set(sentences))
                        keys = [make_key(src_lang, TARGET_LANG, p) for p in sentences]
                        hits = kv_get_many(keys)
                        missing = [sentences[i] for i, k in enumerate(keys) if hits[k] is None]
                        if not missing:
                            continue
                        print(f"R:{rank} I:{fcount} [{src_lang}]{job_number} from <{fn.name}>")
                        q.put((src_lang, missing))
                        exists_task = True
                        # yield src_lang, missing
            gc.collect()
        if not exists_task:
            q.put(None)
            return

async def tcp_main():
    main_env = lmdb.open(
        str(const.V4_TR_DIR),
        map_size=LMDB_MAP_SIZE_BYTES,
        subdir=True,
        readonly=False,
        lock=True,
        max_dbs=1,
        writemap=True,
        map_async=True,     # 异步 flush，降低写延迟；进程退出前会同步
        readahead=True,     # 顺序读友好
    )
    def kv_put_many(items: List[Tuple[bytes, bytes]]):
        with main_env.begin(write=True) as txn:
            for k, v in items:
                txn.put(k, v, overwrite=True)

    def encode_value(s: str) -> bytes:
        return _ZC.compress(s.encode("utf-8"))

    def pack_frame(payload: bytes) -> bytes:
        c = _ZC.compress(payload)
        return struct.pack(">I", len(c)) + c

    async def read_exactly(reader: asyncio.StreamReader, n: int) -> bytes:
        buf = []
        while len(buf) < n:
            chunk = await reader.read(n - len(buf))
            if not chunk:
                raise ConnectionError("peer closed")
            buf.append(chunk)
        return b"".join(buf)

    async def read_frame(reader: asyncio.StreamReader) -> bytes:
        hdr = await read_exactly(reader, 4)
        print(len(hdr), hdr)
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
    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info("peername")
        logger.info(f"INBOUND:{addr}")
        try:
            raw = await read_frame(reader)
            outer = msgpack.unpackb(raw, raw=False)
            op = outer.get(b"op" if b"op" in outer else "op")
            ts = outer.get(b"ts" if b"ts" in outer else "ts")
            sig = outer.get(b"sig" if b"sig" in outer else "sig")
            body_bytes = outer.get(b"body" if b"body" in outer else "body")
            if isinstance(op, bytes): op = op.decode()
            if isinstance(sig, bytes): sig = sig.decode()
            verify(int(ts), body_bytes, sig)
            body = msgpack.unpackb(body_bytes, raw=False)
            if op == "g":
                try:
                    item = tq.get_nowait()
                    if not item:
                        resp = {"o": 2} # NO TASK
                    else:
                        src, txt = item
                        resp = {"p": txt, "s": src, "t": TARGET_LANG, "o":0}
                except Empty:
                    resp = {"o": 1} # TRY AGAIN
            elif op == "u":
                src = body["s"]; dst = body["t"]
                # zstandard 压缩的二进制：先解压再解 msgpack
                deco = _ZD.decompress(body["p"])
                pairs = msgpack.unpackb(deco, raw=False)
                items = [(make_key(src, dst, s), encode_value(t)) for (s, t) in pairs]
                kv_put_many(items)
                resp = {"o": 0}
            else:
                resp = {"o": 0} # "err": "unknown op"
                logger.critical(f"MALICE CLIENT:{addr} {op}")
        except Exception as e:
            resp = {"o": 0} # "err": str(e)
            logger.critical(f"EXC:{addr} " + traceback.format_exc())
        finally:
            out = msgpack.packb(resp, use_bin_type=True)
            writer.write(pack_frame(out))
            await writer.drain()
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
    mgr = mp.Manager()
    tq = mgr.Queue(maxsize=TQUEUE_SIZE)
    producers = [mp.Process(target=task_gen, args=(tq, rk)) for rk in range(TASK_GEN_WORKERS)]
    for x in producers:
        x.start()
    
    server = await asyncio.start_server(handle_client, HOST, PORT)
    addr = ", ".join(str(sock.getsockname()) for sock in server.sockets)
    logger.info(f"[tcp] serving on {addr}")
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    asyncio.run(tcp_main())
