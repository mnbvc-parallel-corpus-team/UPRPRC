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

# =========================
# 配置
# =========================
TARGET_LANG = 'en'
TQUEUE_SIZE = 16384
MAX_SKEW = 7200  # 秒，允许的时钟偏差
API_SECRET = b"1145141919810"
HOST = "0.0.0.0"
PORT = 29999
TASK_GEN_WORKERS = 1
LMDB_MAP_SIZE_BYTES = 100 << 30
SENTENCE_PER_TASK = 128
# 不够可以热扩 `env.set_mapsize(new_size)`.

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

ORDER2LANG = ['ar', 'zh', 'en', 'fr', 'ru', 'es', 'de',]
EN_LANG_ORDER = 2
NON_EN_LANG_IDX = (0, 1, 3, 4, 5, 6)

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

def kv_put_many(env: lmdb.Environment, items: List[Tuple[bytes, bytes]]):
    with env.begin(write=True) as txn:
        for k, v in items:
            txn.put(k, v, overwrite=True)

def kv_get_many(env: lmdb.Environment, keys: List[bytes]) -> Dict[bytes, Optional[bytes]]:
    out = {k: None for k in keys}
    with env.begin(write=False) as txn:
        cursor = txn.cursor()
        # 使用 cursor.getmulti() 批量读取，效率更高
        for k, v in cursor.getmulti(keys):
            out[k] = v
    return out
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
    s = s.strip()
    if not s:
        return False
    # 至少包含一个 Unicode 字母（避免“纯数字/标点/空白”）
    if not any(ch.isalpha() for ch in s):
        return False
    # 至少包含一个该语言特征字母
    pat = IS_MEANINGFUL.get(lang)
    return bool(pat and pat.search(s))

def decode_sentences(data: bytes) -> List[str]:
    return msgpack.unpackb(_ZD.decompress(data), raw=False)
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
                use_gpu=False,
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
    # 写分句缓存用
    def encode_sentences(sentences: List[str]) -> bytes:
        return _ZC.compress(msgpack.packb(sentences, use_bin_type=True))
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
            if hash(fn.name) % TASK_GEN_WORKERS != rank:
                continue
            with fn.open("rb") as f:
                if fn.name.endswith(".pkl"):
                    pkl = pickle.load(f)
                elif fn.name.endswith(".msgpack"):
                    pkl = msgpack.unpack(f)
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
                        paras = []
                        with flattxt_file.open("r", encoding="utf-8") as f:
                            for line in f.read().split('\n\n'):
                                if is_meaningful_line(line, src_lang):
                                    paras.append(line)
                        if not paras:
                            continue
                        pkg = get_or_install_package(src_lang, TARGET_LANG)
                        stanza_pipe = build_stanza(src_lang, str(pkg.package_path / "stanza"))
                        sentences: List[str] = []
                        para_keys = [make_key(src_lang, TARGET_LANG, p) for p in paras]
                        sbd_hits = kv_get_many(sbd_env, para_keys)

                        sbd_to_process = [] # 需要Stanza处理的段落
                        for i, para in enumerate(paras):
                            para_key = para_keys[i]
                            if sbd_hits[para_key] is not None:
                                sentences.extend(decode_sentences(sbd_hits[para_key]))
                            else:
                                sbd_to_process.append((para_key, para))

                        sbd_to_cache = []
                        for pk, para in sbd_to_process:
                            t0 = time.time()
                            sents = sbd_with_stanza(stanza_pipe, para)
                            t1 = time.time()
                            tdelta = (t1 - t0)
                            print(f"SBD {len(para)} char with {tdelta}, v:{len(para) / max(tdelta, 1e-12)}")
                            if sents:
                                sentences.extend(sents)
                                sbd_to_cache.append((pk, encode_sentences(sents)))
                        if sbd_to_cache:
                            kv_put_many(sbd_env, sbd_to_cache)
                            print(f"SBDWCC:{len(sbd_to_cache)} I:{fcount} [{src_lang}]{job_number} from <{fn.name}>")
                        
                        sentences = [x for x in set(sentences) if is_meaningful_line(x, src_lang)]
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
                        # yield src_lang, missing
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

    def encode_value(s: str) -> bytes:
        return _ZC.compress(s.encode("utf-8"))

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
                logger.info(f"CLIENT SUBMIT:{addr} \n\t{'\n\t'.join(str(x) for x in pairs[:5])}")
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
