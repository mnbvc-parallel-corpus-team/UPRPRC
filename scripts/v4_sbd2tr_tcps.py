import asyncio
import hmac
import pickle
from queue import Empty
import gc
import hashlib
import time
import traceback
from pathlib import Path
from typing import List, Tuple, Dict, Optional
import multiprocessing as mp

from loguru import logger
import lmdb
import msgpack

import const
from v4_helpers import make_key, kv_get_many, kv_put_many, is_meaningful_line, encode_sentences, decode_sentences, get_or_install_package, build_stanza, sbd_with_stanza, read_frame, pack_frame, verify, encode_value, \
    EN_LANG_ORDER, ORDER2LANG, _ZD, TARGET_LANG, TR_LMDB_MAP_SIZE, SBD_LMDB_MAP_SIZE

# =========================
# 配置
# =========================
TQUEUE_SIZE = 16384
HOST = "0.0.0.0"
PORT = 29999
SENTENCE_PER_TASK = 128 # 128 is recommanded
# 不够可以热扩 `env.set_mapsize(new_size)`.

const.V4_TR_DIR.mkdir(exist_ok=True)
const.V4_SBD_DIR.mkdir(exist_ok=True)

# =========================
# 数据集与任务生成
# =========================

def task_gen(q: mp.Queue):
    """
    只下发“未命中的段落”给 worker。
    服务器无状态：worker 回传 (src_text, translation) 对即可写入缓存。
    """
    tr_env = lmdb.open( # sentence sha256 => zstd translated text
        str(const.V4_TR_DIR),
        map_size=TR_LMDB_MAP_SIZE,
        subdir=True,
        readonly=True,
        lock=True,
        max_dbs=1,
        readahead=False,
    )
    sbd_env = lmdb.open( # para sha256 => zstd sentences
        str(const.V4_SBD_DIR),
        subdir=True,
        readonly=True,
        lock=True,
        max_dbs=1,
        readahead=True,
    )
    published_keys = set() # avoid publish same keys
    lang2sentbuf = {} # client task batching
    lang2querybuf = {} # server lmdb query batching
    fcount = 0

    def flush_lang2querybuf():
        print(f"[{time.time()}]TASK BATCHING {fcount}")
        for (src_lang, dst_lang), sents in lang2querybuf.items():
            sentences = [x for x in sents if is_meaningful_line(x, src_lang)]
            sents.clear()
            keys = [make_key(src_lang, dst_lang, p) for p in sentences]
            hits = kv_get_many(tr_env, keys)
            missing = [sentences[i] for i, k in enumerate(keys) if k not in published_keys and hits[k] is None]
            for k, v in hits.items():
                if v is not None:
                    published_keys.discard(k)
                else:
                    published_keys.add(k)
            if not missing:
                continue
            print(f"[{time.time()}]C:{fcount} [{src_lang}] M:{len(missing)}")
            sentbuf: list = lang2sentbuf.setdefault(src_lang, [])
            while missing:
                if len(sentbuf) < SENTENCE_PER_TASK:
                    sentbuf.append(missing.pop())
                else:
                    q.put((src_lang, dst_lang, list(sentbuf)))
                    # print("PUT",src_lang, dst_lang, list(sentbuf))
                    sentbuf.clear()
            if sentbuf:
                q.put((src_lang, dst_lang, list(sentbuf)))
                sentbuf.clear()
    while 1:
        fcount = 0
        with sbd_env.begin() as txn:
            with txn.cursor() as cursor:
                for kv_sent_bytes in cursor.iternext(keys=False, values=True):
                    fcount += 1
                    if fcount % 100000 == 0:
                        flush_lang2querybuf()
                        print(f"GC PK begin:{len(published_keys)}")
                        for k, v in kv_get_many(tr_env, [x for x in published_keys]).items():
                            if v is not None:
                                published_keys.discard(k)
                        print(f"GC PK end:{len(published_keys)}")
                        gc.collect()
                    sents, src_lang, dst_lang = decode_sentences(kv_sent_bytes)
                    lang2querybuf.setdefault((src_lang, dst_lang), set()).update(sents)
        flush_lang2querybuf()
        print("TASK DONE, SLEEP 180s")
        time.sleep(180)
    q.put(None)

async def tcp_main():
    main_env = lmdb.open(
        str(const.V4_TR_DIR),
        map_size=TR_LMDB_MAP_SIZE,
        subdir=True,
        readonly=False,
        lock=True,
        max_dbs=1,
        readahead=False,
    )
    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info("peername")
        logger.info(f"INBOUND:{addr}")
        try:
            raw = await read_frame(reader)
            outer = msgpack.unpackb(_ZD.decompress(raw), raw=False)
            op = outer.get(b"op" if b"op" in outer else "op")
            ts = outer.get(b"ts" if b"ts" in outer else "ts")
            sig = outer.get(b"sig" if b"sig" in outer else "sig")
            body_bytes = outer.get(b"body" if b"body" in outer else "body")
            if isinstance(op, bytes): op = op.decode()
            if isinstance(sig, bytes): sig = sig.decode()
            verify(int(ts), body_bytes, sig)
            body = msgpack.unpackb(body_bytes, raw=False)
            if op == "g": # get translate task
                try:
                    item = tq.get_nowait()
                    if not item:
                        resp = {"o": 2} # NO TASK
                    else:
                        src, dst, txt = item
                        resp = {"p": txt, "s": src, "t": dst, "o":0}
                except Empty:
                    resp = {"o": 1} # TRY AGAIN
            elif op == "u": # upload translate task
                src = body["s"]; dst = body["t"]
                # zstandard 压缩的二进制：先解压再解 msgpack
                pairs = body["p"]
                logger.info(f"CLIENT SUBMIT:{addr} \n\t{pairs[:1]}")
                items = [(make_key(src, dst, s), encode_value(t)) for (s, t) in pairs]
                kv_put_many(main_env, items)
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
    producers = [
        mp.Process(target=task_gen, args=(tq,)),
    ]
    for x in producers:
        x.start()
    server = await asyncio.start_server(handle_client, HOST, PORT)
    addr = ", ".join(str(sock.getsockname()) for sock in server.sockets)
    logger.info(f"[tcp] serving on {addr}")
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    asyncio.run(tcp_main())
