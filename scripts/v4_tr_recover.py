# recover_docs.py
import os
import pickle
from pathlib import Path
from typing import List, Tuple, Optional

import lmdb
import zstandard as zstd
import argostranslate.package as ARGOSPKG
import stanza
from tqdm import tqdm

import const  # 复用你的常量

# -------- LMDB 只读打开 --------
ENV = lmdb.open(
    str(const.V4_TR_DIR),
    readonly=True, lock=True, subdir=True,
    readahead=True, max_dbs=1
)

_ZD = zstd.ZstdDecompressor()

ORDER2LANG = ['ar', 'zh', 'en', 'fr', 'ru', 'es', 'de']
TARGET_LANG = 'en'

PKG_CACHE = {}
STANZA_CACHE = {}

def get_pkg(src: str, dst: str):
    key = (src, dst)
    if key in PKG_CACHE:
        return PKG_CACHE[key]
    for P in ARGOSPKG.get_installed_packages():
        if P.from_code == src and P.to_code == dst:
            PKG_CACHE[key] = P
            return P
    raise RuntimeError(f"package {src}->{dst} not installed on this machine")

def build_stanza(src: str, pkg) -> stanza.Pipeline:
    pipe = STANZA_CACHE.get(src)
    if pipe is None:
        pipe = stanza.Pipeline(
            lang=src, processors="tokenize",
            use_gpu=True,  # 恢复阶段 CPU 即可；你要用 GPU 也行
            dir=str(pkg.package_path / "stanza"),
            logging_level="WARNING",
        )
        STANZA_CACHE[src] = pipe
    return pipe

def sbd_with_stanza(pipe: stanza.Pipeline, text: str) -> List[str]:
    doc = pipe(text)
    out = []
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

# 重要：与服务器保持完全一致的 make_key（不做 NFKC）
import hashlib
def make_key(src_lang: str, dst_lang: str, src_text: str) -> bytes:
    h = hashlib.sha256()
    h.update(src_lang.encode("utf-8")); h.update(b"\x00")
    h.update(dst_lang.encode("utf-8")); h.update(b"\x00")
    h.update(src_text.encode("utf-8"))
    return h.digest()

def kv_get_many(keys: List[bytes]) -> List[Optional[bytes]]:
    """一次读事务里批量 get；注意每次不要塞太多，避免超大事务占用太久"""
    with ENV.begin(write=False) as txn:
        return [txn.get(k) for k in keys]

def decode_value(b: bytes) -> str:
    return _ZD.decompress(b).decode("utf-8")

def split_paragraphs(raw: str) -> List[str]:
    return [x for x in raw.split("\n\n") if x]

def recover_one_text(src_lang: str, text_path: Path, out_path: Path):
    pkg = get_pkg(src_lang, TARGET_LANG)
    pipe = build_stanza(src_lang, pkg)

    raw = text_path.read_text("utf-8", errors="ignore")
    paras = split_paragraphs(raw)

    # 记录段落->句子范围，以便回拼
    para_ranges: List[Tuple[int,int]] = []
    sentences: List[str] = []
    for p in paras:
        sents = sbd_with_stanza(pipe, p)
        start = len(sentences)
        sentences.extend(sents)
        para_ranges.append((start, len(sentences)))

    if not sentences:
        out_path.write_text("", encoding="utf-8"); return

    # 查 LMDB
    keys = [make_key(src_lang, TARGET_LANG, s) for s in sentences]
    vals = kv_get_many(keys)

    # 译文句子列表
    trans_sents: List[Optional[str]] = [decode_value(v) if v is not None else None for v in vals]

    # 统计缺失
    miss = sum(1 for t in trans_sents if t is None)
    if miss:
        print(f"[warn] {text_path.name}: missing {miss}/{len(trans_sents)} sentences (not translated yet)")

    # 回拼段落
    out_paras: List[str] = []
    for s, e in para_ranges:
        segs = trans_sents[s:e]
        # 缺失的先用原文占位或空串，看你需求
        merged = " ".join((seg if seg is not None else "") for seg in segs).strip()
        out_paras.append(merged)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n\n".join(out_paras), encoding="utf-8")

def main():
    OUT_DIR = const.V4_TR_DIR / "recovered"  # 输出目录
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 枚举与你服务器相同的来源
    for fn in tqdm(list(const.V4_DOCUMENT_CACHE.iterdir())):
        with fn.open("rb") as f:
            pkl = pickle.load(f)

        for row in pkl:
            sizes = row["sizes"]
            jnums = row["job_numbers"]

            # 逐语言恢复（跳过英语）
            for i, lang in enumerate(ORDER2LANG):
                if lang == "en":
                    continue
                doc_size = sizes[i*3 + 2]
                if doc_size <= 0:
                    continue
                txt = const.CONVERT_TEXT_FLATTEN_TABLE_CACHE_DIR / f"{jnums[i]}.txt"
                if not txt.exists():
                    continue

                out_file = OUT_DIR / f"{jnums[i]}.{lang}-en.txt"
                recover_one_text(lang, txt, out_file)

if __name__ == "__main__":
    main()
