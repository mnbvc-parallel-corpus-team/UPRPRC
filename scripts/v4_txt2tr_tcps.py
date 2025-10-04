import asyncio
import hmac
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

import const
from v4_helpers import make_key, kv_get_many, kv_put_many, is_meaningful_line, encode_sentences, decode_sentences, get_or_install_package, build_stanza, sbd_with_stanza, read_frame, pack_frame, verify, encode_value, \
    EN_LANG_ORDER, ORDER2LANG, _ZD, LMDB_MAP_SIZE_BYTES, TARGET_LANG

# =========================
# 配置
# =========================
TQUEUE_SIZE = 16384
HOST = "0.0.0.0"
PORT = 29999
TASK_GEN_WORKERS = 1
SENTENCE_PER_TASK = 128
# 不够可以热扩 `env.set_mapsize(new_size)`.

const.V4_TR_DIR.mkdir(exist_ok=True)
const.V4_SBD_DIR.mkdir(exist_ok=True)

# =========================
# 数据集与任务生成
# =========================

def task_gen(q: mp.Queue, rank: int):
    """
    只下发“未命中的段落”给 worker。
    服务器无状态：worker 回传 (src_text, translation) 对即可写入缓存。
    """
    tr_env = lmdb.open(
        str(const.V4_TR_DIR),
        map_size=LMDB_MAP_SIZE_BYTES,
        subdir=True,
        readonly=True,
        lock=True,
        max_dbs=1,
        readahead=True,     # 顺序读友好
    )
    sbd_env = lmdb.open(
        str(const.V4_SBD_DIR),
        map_size=LMDB_MAP_SIZE_BYTES,
        subdir=True,
        readonly=False,
        lock=True,
        max_dbs=1,
        writemap=True,
        map_async=True,     # 异步 flush，降低写延迟；进程退出前会同步
        readahead=True,     # 顺序读友好
    )
    
    while 1:
        published_keys = set() # avoid publish same keys
        lang2sentbuf = {} # 句子个数平滑打批
        fcount = 0
        exists_task = False
        for fn in const.V4_DOCUMENT_CACHE.iterdir():
            fcount += 1
            if fcount % 100 == 0:
                print(f"GEN TASK CURRENT IDX:{fcount}")
                print(f"GC published keys begin:{len(published_keys)}")
                for k, v in kv_get_many(tr_env, [x for x in published_keys]).items():
                    if v is not None:
                        published_keys.discard(k)
                print(f"GC published keys end:{len(published_keys)}")
            # if hash(fn.name) % TASK_GEN_WORKERS != rank:
                # continue
            with fn.open("rb") as f:
                # if fn.name.endswith(".pkl"):
                pkl = pickle.load(f)
                # elif fn.name.endswith(".msgpack"): # msgpack enumerate takes 5.722s, while pickle use 5.420s
                    # pkl = msgpack.unpack(f)
            for row in pkl:
                valid_jn_fp = []
                sizes = row['sizes']
                for i in range(len(ORDER2LANG)):
                    doc_size = sizes[i * 3 + 2]
                    job_number = row['job_numbers'][i]
                    flattxt_file = const.CONVERT_TEXT_FLATTEN_TABLE_CACHE_DIR / f"{job_number}.txt"
                    if doc_size > 0 and flattxt_file.exists() and flattxt_file.stat().st_size > 0:
                        valid_jn_fp.append(i)
                if len(valid_jn_fp) > 1:
                    if EN_LANG_ORDER in valid_jn_fp:
                        valid_jn_fp.remove(EN_LANG_ORDER)
                    for i in valid_jn_fp:
                        job_number = row['job_numbers'][i]
                        flattxt_file = const.CONVERT_TEXT_FLATTEN_TABLE_CACHE_DIR / f"{job_number}.txt"
                        src_lang = ORDER2LANG[i]
                        paras = {
                            line for line in flattxt_file.read_text(encoding="utf-8").split('\n\n')
                        }
                        paras = [x for x in paras if is_meaningful_line(x, src_lang)]
                        if not paras:
                            continue
                        para_keys = [make_key(src_lang, TARGET_LANG, p) for p in paras]
                        sbd_hits = kv_get_many(sbd_env, para_keys)

                        sbd_to_process = [] # 需要Stanza处理的段落
                        sentences = set()
                        for para_key, para in zip(para_keys, paras):
                            if sbd_hits[para_key] is not None:
                                sentences.update(decode_sentences(sbd_hits[para_key]))
                            else:
                                sbd_to_process.append((para_key, para))
                        if sbd_to_process:
                            sbd_to_cache = []
                            pkg = get_or_install_package(src_lang, TARGET_LANG)
                            stanza_pipe = build_stanza(src_lang, pkg, use_gpu=True)
                            for pk, para in sbd_to_process:
                                t0 = time.time()
                                sents = sbd_with_stanza(stanza_pipe, para)
                                t1 = time.time()
                                tdelta = (t1 - t0)
                                print(f"SBD {len(para)} char with {tdelta}, v:{len(para) / max(tdelta, 1e-12)}")
                                if sents:
                                    sentences.update(sents)
                                    sbd_to_cache.append((pk, encode_sentences(sents)))
                            if sbd_to_cache:
                                kv_put_many(sbd_env, sbd_to_cache)
                                print(f"SBDWCC:{len(sbd_to_cache)} I:{fcount} [{src_lang}]{job_number} from <{fn.name}>")
                        
                        sentences = [x for x in sentences if is_meaningful_line(x, src_lang)]
                        keys = [make_key(src_lang, TARGET_LANG, p) for p in sentences]
                        hits = kv_get_many(tr_env, keys)
                        missing = [sentences[i] for i, k in enumerate(keys) if k not in published_keys and hits[k] is None]
                        for k, v in hits.items():
                            if v is not None:
                                published_keys.discard(k)
                            else:
                                published_keys.add(k)
                        if not missing:
                            continue
                        print(f"R:{rank} I:{fcount} [{src_lang}]{job_number} from <{fn.name}>")
                        sentbuf: list = lang2sentbuf.setdefault(src_lang, [])
                        while missing:
                            if len(sentbuf) < SENTENCE_PER_TASK:
                                sentbuf.append(missing.pop())
                            else:
                                q.put((src_lang, list(sentbuf)))
                                sentbuf.clear()
                        exists_task = True
            gc.collect()
        for src_lang, sentbuf in lang2sentbuf.items():
            q.put((src_lang, list(sentbuf)))
            sentbuf.clear()
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
                        src, txt = item
                        resp = {"p": txt, "s": src, "t": TARGET_LANG, "o":0}
                except Empty:
                    resp = {"o": 1} # TRY AGAIN
            elif op == "u": # upload translate task
                src = body["s"]; dst = body["t"]
                # zstandard 压缩的二进制：先解压再解 msgpack
                pairs = body["p"]
                logger.info(f"CLIENT SUBMIT:{addr} \n\t{'\n\t'.join(str(x) for x in pairs[:1])}")
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
