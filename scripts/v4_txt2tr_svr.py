from contextlib import asynccontextmanager
import os
import pickle
from queue import Empty
import re
import gc
import hashlib
import unicodedata
from pathlib import Path
from typing import List, Tuple, Dict, Optional
import multiprocessing as mp

import lmdb
import zstandard as zstd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel
import uvicorn
from tqdm import tqdm

import const

# =========================
# 配置
# =========================
ALL_SOURCE_LANGS = ('es', 'zh', 'fr', 'ru', 'ar', 'de')
TARGET_LANG = 'en'

# LMDB 环境参数
const.V4_TR_DIR.mkdir(exist_ok=True)

# 映射最大尺寸（内存映射上限，不是实际文件大小；文件按需增长）
# 你有 ~133.9 万 doc × 每 doc ~100 段 ≈ 1.339e8 段；按平均每段译文 200~400B 压缩后估算，
# 预留 1 TB 通常够用；不够可以热扩 `env.set_mapsize(new_size)`.
LMDB_MAP_SIZE_BYTES = int(os.environ.get("LMDB_MAP_SIZE_BYTES", 100 << 30))

# Zstd 压缩器/解压器
_ZC = zstd.ZstdCompressor(level=10)
_ZD = zstd.ZstdDecompressor()

import argostranslate.package as ARGOSPKG
import stanza

PKG_CACHE = {}
STANZA_CACHE = {}
G = {}

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

# =========================
# 规范化 & Key 生成
# =========================
# def normalize_text(s: str) -> str:
#     """一致化：换行统一，Unicode NFKC 归一化（见文末解释）"""
#     s = s.replace("\r\n", "\n").replace("\r", "\n")
#     # 不做激进空白折叠，避免改变句读；如确需可在这里加进一步规则
#     return unicodedata.normalize("NFKC", s)

def make_key(src_lang: str, dst_lang: str, src_text: str) -> bytes:
    """SHA-256 结果作为 LMDB key（32B），既短又稳"""
    h = hashlib.sha256()
    h.update(src_lang.encode("utf-8")); h.update(b"\x00")
    h.update(dst_lang.encode("utf-8")); h.update(b"\x00")
    # h.update(normalize_text(src_text).encode("utf-8"))
    h.update(src_text.encode("utf-8"))
    return h.digest()  # 32 bytes


# =========================
# LMDB 封装
# =========================
def open_env() -> lmdb.Environment:
    # 单库（默认 DBI）；writemap+map_async 典型的高吞吐设置
    env = lmdb.open(
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
    return env

def kv_put_many(items: List[Tuple[bytes, bytes]]):
    """一次写事务批量 upsert；避免频繁提交"""
    # 单 writer 锁；把一批（一个任务）放到一次事务里性能最佳
    with G["ENV"].begin(write=True) as txn:
        for k, v in items:
            txn.put(k, v, overwrite=True)

def encode_value(s: str) -> bytes:
    return _ZC.compress(s.encode("utf-8"))

def decode_value(b: bytes) -> str:
    return _ZD.decompress(b).decode("utf-8")


# =========================
# 数据集与任务生成
# =========================
ORDER2LANG = ['ar', 'zh', 'en', 'fr', 'ru', 'es', 'de',]

def task_gen(q: mp.Queue):
    """
    只下发“未命中的段落”给 worker。
    服务器无状态：worker 回传 (src_text, translation) 对即可写入缓存。
    """
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
    while 1:
        exists_task = False
        for fn in tqdm(const.V4_DOCUMENT_CACHE.iterdir()):
            with fn.open("rb") as f:
                pkl = pickle.load(f)
            for row in pkl:
                valid_jn_fp = []
                sizes = row['sizes']
                for i in range(7):
                    if ORDER2LANG[i] == 'en':
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
                        src_lang = ORDER2LANG[i]
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
                        q.put((src_lang, missing))
                        exists_task = True
                        # yield src_lang, missing
            gc.collect()
        if not exists_task:
            q.put(None)
            return

# _itr = task_gen()


# =========================
# FastAPI 服务
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    mgr = mp.Manager()
    task_queue = mgr.Queue(maxsize=512)
    G["task_queue"] = task_queue
    _PROC_PRODUCER = mp.Process(target=task_gen, args=(task_queue, ))
    _PROC_PRODUCER.start()
    G["ENV"] = open_env()
    yield
    _PROC_PRODUCER.join()

app = FastAPI(redoc_url=None, docs_url=None, swagger_ui_init_oauth=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(GZipMiddleware)


@app.get('/')
async def task_getter():
    try:
        task = G["task_queue"].get_nowait()
    except Empty:
        raise HTTPException(403)
    if task is not None:
        src_lang, src_texts = task
    else:
        print('no task')
        return {'taskid': -1}
    return {
        'taskid': 0,             # 无状态占位
        'src': src_lang,
        'dst': TARGET_LANG,
        'data': src_texts,       # 缺失的原文段落
    }

class UplBody2(BaseModel):
    src: str
    dst: str
    pairs: List[Tuple[str, str]]   # [(src_text, translated_text)]

@app.post('/u')
async def task_submit2(body: UplBody2):
    if not body.pairs:
        return 1
    items = []
    for src_text, trans in body.pairs:
        k = make_key(body.src, body.dst, src_text)
        v = encode_value(trans)
        items.append((k, v))
    kv_put_many(items)
    return 1

@app.get('/health')
async def health():
    st = G["ENV"].info()
    return {
        "map_size": st["map_size"],
        "last_pgno": st["last_pgno"],   # 近似占用页数
        "entries": st.get("entries"),   # 仅在 named db 下可用；默认 db 可能返回 None
    }

if __name__ == '__main__':
    # 需要扩容时，可在运行时调：ENV.set_mapsize(new_size)
    uvicorn.run(app, host="0.0.0.0", port=const.TRANSLATION_SERVER_PORT)

