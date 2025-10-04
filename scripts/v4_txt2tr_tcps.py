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
import zstandard as zstd
import regex

import const
from v4_helpers import _ZD, NON_EN_LANG_IDX, ORDER2LANG, TARGET_LANG, decode_sentences, decode_value, encode_sentences, encode_value, make_key, kv_get_many, kv_put_many, is_meaningful_line, LMDB_MAP_SIZE_BYTES, pack_frame, read_frame, verify

# =========================
# 配置
# =========================
TQUEUE_SIZE = 250
HOST = "0.0.0.0"
PORT = 29999
TASK_GEN_WORKERS = 1
SENTENCE_PER_TASK = 128

"""
IS_MEANINGFUL = {
    # 仅阿拉伯字母（排除数字/标点）。涵盖基本字母与常见扩展
    # 基本字母：0621–064A；扩展：066E–066F, 0671–06D3, 06FA–06FC 等
    'ar': re.compile(r'[\u0621-\u064A\u066E-\u066F\u0671-\u06D3\u06FA-\u06FC]'),

    # 至少一个汉字（统一表意文字：基本区 + 扩展 A/B/C/D/E/F/G）
    # 注：不含 〇 等数字用字形，避免纯“〇〇”被当作有意义
    'zh': re.compile(
        r'[\u4E00-\u9FFF\u3400-\u4DBF'
        r'\U00020000-\U0002A6DF\U0002A700-\U0002EBEF\U00030000-\U0003134F]'
    ),

    # 法语：拉丁字母 + 全量常用变体（大/小写），含 œ/Œ、ç/Ç、æ/Æ
    'fr': re.compile(r'[A-Za-zÀ-ÖØ-öø-ÿŒœÆæÇç]'),

    # 西语：拉丁字母 + áéíóúüñ（及大写）
    'es': re.compile(r'[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]'),

    # 俄语：整块西里尔（含扩展与古字母），避免你原来把逗号写进字符类的错误
    'ru': re.compile(r'[\u0400-\u04FF\u0500-\u052F\u2DE0-\u2DFF\uA640-\uA69F]'),

    # 英语：纯 ASCII 字母
    'en': re.compile(r'[A-Za-z]'),

    # 德语：拉丁字母 + ÄÖÜäöüßẞ（注意大写 ß U+1E9E）
    'de': re.compile(r'[A-Za-zÄÖÜäöüßẞ]'),
}
"""

const.V4_TR_DIR.mkdir(exist_ok=True)
const.V4_SBD_DIR.mkdir(exist_ok=True)

# =========================
# 数据集与任务生成
# =========================

def task_gen(sbdq: mp.Queue, trq: mp.Queue, rank: int):
    """
    只下发“未命中的段落”给 worker。
    服务器无状态：worker 回传 (src_text, translation) 对即可写入缓存。
    """
    import argostranslate.package as ARGOSPKG
    import stanza

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
        readonly=True,
        lock=True,
        max_dbs=1,
        readahead=True,     # 顺序读友好
    )

    while 1:
        fcount = 0
        exists_task = False
        for fn in const.V4_DOCUMENT_CACHE.iterdir():
            fcount += 1
            if fcount % 100 == 0:
                print(f"GEN TASK CURRENT IDX:{fcount} sbdq:{sbdq.qsize()}")
            if hash(fn.name) % TASK_GEN_WORKERS != rank:
                continue
            with fn.open("rb") as f:
                pkl = pickle.load(f)
            for row in pkl:
                valid_jn_fp = []
                sizes = row['sizes']
                for i in NON_EN_LANG_IDX:
                    doc_size = sizes[i * 3 + 2]
                    job_number = row['job_numbers'][i]
                    flattxt_file = const.CONVERT_TEXT_FLATTEN_TABLE_CACHE_DIR / f"{job_number}.txt"
                    if doc_size > 0 and flattxt_file.exists() and flattxt_file.stat().st_size > 0:
                        valid_jn_fp.append(i)
                if len(valid_jn_fp) > 1:
                    for i in valid_jn_fp:
                        job_number = row['job_numbers'][i]
                        flattxt_file = const.CONVERT_TEXT_FLATTEN_TABLE_CACHE_DIR / f"{job_number}.txt"
                        src_lang = ORDER2LANG[i]
                        paras: list[str] = []
                        with flattxt_file.open("r", encoding="utf-8") as f:
                            for line in f.read().split('\n\n'):
                                if is_meaningful_line(line, src_lang):
                                    paras.append(line)
                        if not paras:
                            continue
                        para_keys = [make_key(src_lang, TARGET_LANG, p) for p in paras]
                        sbd_hits = kv_get_many(sbd_env, para_keys)
                        sbd_to_process = []
                        all_sents = []
                        for i, para in enumerate(paras):
                            para_key = para_keys[i]
                            enc_sents = sbd_hits.get(para_key)
                            if enc_sents is None:
                                sbd_to_process.append((para_key, para))
                            else:
                                all_sents.extend([x for x in decode_sentences(enc_sents) if is_meaningful_line(x, src_lang)])
                        for pk, para in sbd_to_process:
                            sbdq.put((src_lang, pk, para))
                            exists_task = True
                        keylist = [make_key(src_lang, TARGET_LANG, x) for x in all_sents]
                        sent_hits = kv_get_many(tr_env, keylist)
                        for k, v in zip(keylist, all_sents):
                            if sent_hits[k] is None:
                                trq.put((src_lang, v))
                                # print(f"put trq:{src_lang} {v}")
                        print(f"R:{rank} I:{fcount} [{src_lang}]{job_number} from <{fn.name}> sbd_to_process:{len(sbd_to_process)}")
            gc.collect()

        if not exists_task:
            sbdq.put(None)
            return

async def tcp_main():
    tr_env = lmdb.open(
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
    mgr = mp.Manager()
    sbdq = mgr.Queue(maxsize=TQUEUE_SIZE)
    trq = mgr.Queue()

    lang2sentbuf = {} # 句子个数平滑打批
    def enqueue_sentbuf(src_lang: str, sentence_list: list[str]):
        sentbuf: set = lang2sentbuf.setdefault(src_lang, set())
        sentbuf.update([x for x in sentence_list if is_meaningful_line(x, src_lang)])
        # print(f"enqueue {src_lang} {sentence_list} {len(sentbuf)}")
        k2p = {make_key(src_lang, TARGET_LANG, p):p for p in sentbuf}
        for k, v in kv_get_many(tr_env, [make_key(src_lang, TARGET_LANG, p) for p in sentbuf]).items():
            if v is not None:
                sentbuf.discard(k2p[k])
        # print(f"after enqueue gc {len(sentbuf)}")

    def pop_sentbuf():
        """find the language which contains the most task, pop at most SENTENCE_PER_TASK tasks."""
        while 1:
            try:
                it = trq.get_nowait()
                src_lang, sent = it
                sentbuf: set = lang2sentbuf.setdefault(src_lang, set())
                sentbuf.add(sent)
            except Empty:
                break
        mx = 0
        mxlang = None
        for langidx in NON_EN_LANG_IDX:
            lang = ORDER2LANG[langidx]
            sentbuf: set = lang2sentbuf.setdefault(lang, set())
            if len(sentbuf) > mx:
                mx = len(sentbuf)
                mxlang = lang
        if mxlang is None:
            return None, []
        mxsentbuf: set = lang2sentbuf[mxlang]
        ret = []
        for _ in range(SENTENCE_PER_TASK):
            if mxsentbuf:
                ret.append(mxsentbuf.pop())
        return mxlang, ret

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
                src, txt = pop_sentbuf() # lang, sentence list
                if src is None:
                    resp = {"o": 1} # TRY AGAIN
                else:
                    resp = {"p": txt, "s": src, "t": TARGET_LANG, "o": 0}
            elif op == "u": # upload translate task
                src = body["s"]; dst = body["t"]
                pairs = body["p"]
                logger.info(f"CLIENT SUBMIT:{addr} \n\t{'\n\t'.join(str(x) for x in pairs[:1])}")
                items = [(make_key(src, dst, s), encode_value(t)) for (s, t) in pairs]
                kv_put_many(tr_env, items)
                resp = {"o": 0}
            elif op == "s": # sbd
                try:
                    item = sbdq.get_nowait()
                    if not item:
                        resp = {"o": 2} # NO TASK
                    else:
                        src, pk, txt = item
                        resp = {"p": txt, "s": src, "k": pk, "o": 0}
                except Empty:
                    resp = {"o": 1} # TRY AGAIN
            elif op == "b": # sbd
                src = body["s"]
                pairs = body["p"] # keys => encoded_sentences
                # print(f"pairs:{pairs}")
                kv_put_many(sbd_env, [(pk, encode_sentences(s)) for pk, s in pairs])
                for pk, sents in pairs:
                    enqueue_sentbuf(src, sents)
                    logger.info(f"SBD:{addr} \n\t{'\n\t'.join(str(x) for x in sents[:3])}")
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

    producers = [mp.Process(target=task_gen, args=(sbdq, trq, rk)) for rk in range(TASK_GEN_WORKERS)]
    for x in producers:
        x.start()
    
    server = await asyncio.start_server(handle_client, HOST, PORT)
    addr = ", ".join(str(sock.getsockname()) for sock in server.sockets)
    logger.info(f"[tcp] serving on {addr}")
    async with server:
        await server.serve_forever()

def _dl_pkl_cache():
    from datasets import load_dataset
    from v4_use_docunorg_for_list import SEARCH_CONFIG_HASH
    ds = load_dataset("bot-yaya/documents.un.org_search_result")
    ds.save_to_disk(const.WORK_DIR / "ds_documents.un.org_search_result")
    allres = []
    cache_file = const.V4_DOCUMENT_CACHE / f"{SEARCH_CONFIG_HASH}.pkl"
    
    for p,row in enumerate(ds["train"]):
        allres.append(dict(row))
        # cache_file = const.V4_DOCUMENT_CACHE / f"{SEARCH_CONFIG_HASH}-20-{p+1}.pkl"
        # if cache_file.exists():
        #     continue
    with cache_file.open("wb") as f:
        pickle.dump(allres, f)

if __name__ == '__main__':
    # _dl_pkl_cache()
    asyncio.run(tcp_main())
