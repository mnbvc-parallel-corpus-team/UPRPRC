# recover_docs.py
import pickle
from pathlib import Path
from typing import Tuple, Optional
import os

import lmdb
import zstandard as zstd
from tqdm import tqdm
from datasets import Dataset, Features, Value, List

import const  # 复用你的常量
from v4_txt2tr_tcps import kv_get_many, kv_put_many, make_key, is_meaningful_line, decode_sentences, LMDB_MAP_SIZE_BYTES, TARGET_LANG, ORDER2LANG, NON_EN_LANG_IDX, EN_LANG_ORDER
from new_sample_translate2align import align

# -------- LMDB 只读打开 --------
TR_ENV = lmdb.open(
    str(const.V4_TR_DIR),
    readonly=True, lock=True, subdir=True,
    map_size=LMDB_MAP_SIZE_BYTES,
    readahead=True, max_dbs=1
)
SBD_ENV = lmdb.open(
    str(const.V4_SBD_DIR),
    readonly=True, lock=True, subdir=True,
    map_size=LMDB_MAP_SIZE_BYTES,
    readahead=True, max_dbs=1
)
_ZD = zstd.ZstdDecompressor()

def gen_filewise():
    for fn in const.V4_DOCUMENT_CACHE.iterdir():
        with fn.open("rb") as f:
            pkl = pickle.load(f)
        for row in pkl:
            sizes = row["sizes"]
            jnums = row["job_numbers"]
            for i in NON_EN_LANG_IDX:
                src_lang = ORDER2LANG[i]
                doc_size = sizes[i*3 + 2]
                if doc_size <= 0:
                    continue
                text_path = const.CONVERT_TEXT_FLATTEN_TABLE_CACHE_DIR / f"{jnums[i]}.txt"
                if not text_path.exists():
                    continue
                raw = text_path.read_text("utf-8", errors="ignore")
                paras = raw.split('\n\n')
                for pi, p in enumerate(paras):
                    if not is_meaningful_line(p, src_lang):
                        continue
                    para_keys = [make_key(src_lang, TARGET_LANG, p) for p in paras]
                    sbd_hits = kv_get_many(SBD_ENV, para_keys)
                    for p, k in zip(paras, para_keys):
                        hit = sbd_hits.get(k)
                        if not hit:
                            print(f"[WARN] incomplete sbd:{text_path} {src_lang} paraidx:{pi} {p} miss:{k}")
                            continue
                        yield {
                            "sha256": k,
                            "src_lang": src_lang,
                            "dst_lang": TARGET_LANG,
                            "before_sbd": p,
                            "after_sbd": decode_sentences(hit),
                        }

def gen_sbd_dataset():
    for fn in const.V4_DOCUMENT_CACHE.iterdir():
        with fn.open("rb") as f:
            pkl = pickle.load(f)
        for row in pkl:
            sizes = row["sizes"]
            jnums = row["job_numbers"]
            for i in NON_EN_LANG_IDX:
                src_lang = ORDER2LANG[i]
                doc_size = sizes[i*3 + 2]
                if doc_size <= 0:
                    continue
                text_path = const.CONVERT_TEXT_FLATTEN_TABLE_CACHE_DIR / f"{jnums[i]}.txt"
                if not text_path.exists():
                    continue
                raw = text_path.read_text("utf-8", errors="ignore")
                paras = raw.split('\n\n')
                for pi, p in enumerate(paras):
                    if not is_meaningful_line(p, src_lang):
                        continue
                    para_keys = [make_key(src_lang, TARGET_LANG, p) for p in paras]
                    sbd_hits = kv_get_many(SBD_ENV, para_keys)
                    for p, k in zip(paras, para_keys):
                        hit = sbd_hits.get(k)
                        if not hit:
                            print(f"[WARN] incomplete sbd:{text_path} {src_lang} paraidx:{pi} {p} miss:{k}")
                            continue
                        yield {
                            "sha256": k,
                            "src_lang": src_lang,
                            "dst_lang": TARGET_LANG,
                            "before_sbd": p,
                            "after_sbd": decode_sentences(hit),
                        }

def decode_value(b: bytes) -> str:
    return _ZD.decompress(b).decode("utf-8")

def gen_tr_dataset():
    for fn in const.V4_DOCUMENT_CACHE.iterdir():
        with fn.open("rb") as f:
            pkl = pickle.load(f)

        for row in pkl:
            sizes = row["sizes"]
            jnums = row["job_numbers"]
            # symbol_id = row["id"]

            # 逐语言恢复（跳过英语）
            for i in NON_EN_LANG_IDX:
                src_lang = ORDER2LANG[i]
                doc_size = sizes[i*3 + 2]
                if doc_size <= 0:
                    continue
                text_path = const.CONVERT_TEXT_FLATTEN_TABLE_CACHE_DIR / f"{jnums[i]}.txt"
                if not text_path.exists():
                    continue
                raw = text_path.read_text("utf-8", errors="ignore")
                paras = raw.split('\n\n')

                for pi, p in enumerate(paras):
                    if not is_meaningful_line(p, src_lang):
                        continue
                    para_keys = [make_key(src_lang, TARGET_LANG, p) for p in paras]
                    sbd_hits = kv_get_many(SBD_ENV, para_keys)
                    sentences = []
                    for p, k in zip(paras, para_keys):
                        hit = sbd_hits.get(k)
                        if not hit:
                            print(f"[WARN] incomplete sbd:{text_path} {src_lang} paraidx:{pi} {p} miss:{k}")
                            continue
                        sentences.extend(decode_sentences(hit))
                    keys = [make_key(src_lang, TARGET_LANG, s) for s in sentences]
                    vals = kv_get_many(keys)
                    # trans_sents = []

                    for si, s, k in zip(range(len(sentences)), sentences, keys):
                        if not is_meaningful_line(s, src_lang):
                            # trans_sents.append(s)
                            continue
                        hit = vals.get(k)
                        if not hit:
                            print(f"[WARN] incomplete tr:{text_path} {src_lang} sentidx:{si} {s} miss:{k}")
                            continue
                        dec = decode_value(hit)
                        # trans_sents.append(dec)
                        yield {
                            "sha256": k,
                            "src_lang": src_lang,
                            "dst_lang": TARGET_LANG,
                            "src": s,
                            "tr": dec
                        }
                    # out_paras: List[str] = []
                    # for s, e in para_ranges:
                    #     segs = trans_sents[s:e]
                    #     # 缺失的先用原文占位或空串，看你需求
                    #     merged = " ".join((seg if seg is not None else "") for seg in segs).strip()
                    #     out_paras.append(merged)

def recover_translated_para(paras: list[str], src_lang: str):
    tr_paras = []
    for pi, p in enumerate(paras):
        sentences = []
        if not is_meaningful_line(p, src_lang):
            tr_paras.append(p)
            continue
        para_keys = [make_key(src_lang, TARGET_LANG, p) for p in paras]
        sbd_hits = kv_get_many(SBD_ENV, para_keys)
        for p, k in zip(paras, para_keys):
            hit = sbd_hits.get(k)
            if not hit:
                print(f"[WARN] incomplete sbd:{src_lang} paraidx:{pi} {p} miss:{k}")
                continue
            sentences.extend(decode_sentences(hit))
        keys = [make_key(src_lang, TARGET_LANG, s) for s in sentences]
        vals = kv_get_many(keys)
        trans_sents = []
        for si, s, k in zip(range(len(sentences)), sentences, keys):
            if not is_meaningful_line(s, src_lang):
                trans_sents.append(s)
                continue
            hit = vals.get(k)
            if not hit:
                print(f"[WARN] incomplete tr:{src_lang} sentidx:{si} {s} miss:{k}")
                continue
            dec = decode_value(hit)
            trans_sents.append(dec)
        tr_paras.append(''.join(trans_sents))
    return tr_paras

def gen_bilingual_align():
    for fn in const.V4_DOCUMENT_CACHE.iterdir():
        with fn.open("rb") as f:
            pkl = pickle.load(f)
        for row in pkl:
            sizes = row["sizes"]
            jnums = row["job_numbers"]
            tr_para_cache = {}
            for i, lang in enumerate(ORDER2LANG):
                doc_size = sizes[i*3 + 2]
                if doc_size <= 0:
                    continue
                src_job_number = jnums[i]
                text_path = const.CONVERT_TEXT_FLATTEN_TABLE_CACHE_DIR / f"{src_job_number}.txt"
                if not text_path.exists():
                    continue
                paras = text_path.read_text("utf-8", errors="ignore").split('\n\n')
                tr_para_cache[lang] = (paras, recover_translated_para(paras, lang) if lang != TARGET_LANG else paras)

            for p, src_lang in enumerate(ORDER2LANG):
                src_cache = tr_para_cache.get(src_lang)
                if not src_lang:
                    continue
                src_paras, src_tr = src_cache
                for q in range(p+1, len(ORDER2LANG)):
                    dst_lang = ORDER2LANG[q]
                    dst_cache = tr_para_cache.get(dst_lang)
                    if not dst_cache:
                        continue
                    dst_paras, dst_tr = dst_cache
                    doc_size = sizes[i*3 + 2]
                    src_job_number = jnums[p]
                    dst_job_number = jnums[q]

                    aligned, pairs, preview = align(src_paras, dst_paras, src_tr, dst_tr)
                    for apairs, atext in zip(aligned, pairs):
                        i, o, _ir, _or = atext
                        yield {
                            'id': row["id"],
                            "src_job_number": src_job_number,
                            "dst_job_number": dst_job_number,
                            'clean_para_index_set_pair': apairs, 
                            'src_lang': src_lang, 
                            'dst_lang': dst_lang, 
                            'src_text': i, 
                            'dst_text': o, 
                            'src_rate': _ir, 
                            'dst_rate': _or
                        }


def gen_all_lang_align():
    pass

def main():
    ds_sbd = Dataset.from_generator(gen_sbd_dataset, features=Features({
        "sha256": Value("binary"),
        "src_lang": Value("string"),
        "dst_lang": Value("string"),
        "before_sbd": Value("string"),
        "after_sbd": List(Value("string")),
    }))
    ds_sbd.save_to_disk(const.WORK_DIR / "v4_ds_sbd")
    ds_sbd.push_to_hub(
        "bot-yaya/UPRPRC_SBD_KV",
        private=False,
        max_shard_size="2GB",
        token=os.environ.get("HF_TOKEN"),
    )
    ds_tr = Dataset.from_generator(gen_tr_dataset, features=Features({
        "sha256": Value("binary"),
        "src_lang": Value("string"),
        "dst_lang": Value("string"),
        "src": Value("string"),
        "tr": Value("string"),
    }))
    ds_tr.save_to_disk(const.WORK_DIR / "v4_ds_tr")
    ds_tr.push_to_hub(
        "bot-yaya/UPRPRC_TR_KV",
        private=False,
        max_shard_size="2GB",
        token=os.environ.get("HF_TOKEN"),
    )
    ds_bilingual = Dataset.from_generator(gen_bilingual_align, features=Features({
        "id": Value("string"),
        "src_job_number": Value("string"),
        "dst_job_number": Value("string"),
        "clean_para_index_set_pair": Value("string"),
        "src_lang": Value("string"),
        "dst_lang": Value("string"),
        "src_text": Value("string"),
        "dst_text": Value("string"),
        "src_rate": Value("float"),
        "dst_rate": Value("float"),
    }))
    ds_bilingual.save_to_disk(const.WORK_DIR / "v4_ds_tr")
    ds_bilingual.push_to_hub(
        "bot-yaya/UPRPRC_TR_KV",
        private=False,
        max_shard_size="2GB",
        token=os.environ.get("HF_TOKEN"),
    )

if __name__ == "__main__":
    main()
