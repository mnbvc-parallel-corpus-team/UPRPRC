# recover_docs.py
import json
import pickle
from pathlib import Path
from typing import Tuple, Optional
import os

import lmdb
from tqdm import tqdm
import zstandard as zstd
from datasets import Dataset, Features, Value, List
import msgpack


import const  # 复用你的常量
from v4_helpers import kv_get_many, make_key, is_meaningful_line, \
    LMDB_MAP_SIZE_BYTES, TARGET_LANG, ORDER2LANG, NON_EN_LANG_IDX, EN_LANG_ORDER, TR_LMDB_MAP_SIZE, SBD_LMDB_MAP_SIZE
from new_sample_translate2align import align

def decode_sentences(data: bytes):
    return msgpack.unpackb(zstd.ZstdDecompressor().decompress(data), raw=False)

def decode_value(b: bytes) -> str:
    return zstd.ZstdDecompressor().decompress(b).decode("utf-8")

def _iter_pkl():
    for p, fn in enumerate(const.V4_DOCUMENT_CACHE.iterdir()):
        print(f"file:{p} {fn}")
        with fn.open("rb") as f:
            pkl = pickle.load(f)
        for row in pkl:
            yield row

def _iter_non_eng():
    ftxt_env: lmdb.Environment = lmdb.open(
        str(const.V4_FTXT_DIR),
        # map_size=LMDB_MAP_SIZE_BYTES,
        subdir=True,
        readonly=True,
        lock=True,
        max_dbs=1,
        readahead=True,
    )
    for row in _iter_pkl():
        valid_jn_fp = []
        sizes = row['sizes']
        jnums = row["job_numbers"]
        for i in range(len(ORDER2LANG)):
            doc_size = sizes[i * 3 + 2]
            job_number = jnums[i]
            # flattxt_file = const.CONVERT_TEXT_FLATTEN_TABLE_CACHE_DIR / f"{job_number}.txt"
            if doc_size > 0 :
                valid_jn_fp.append(i)
        if len(valid_jn_fp) > 1:
            if EN_LANG_ORDER in valid_jn_fp:
                valid_jn_fp.remove(EN_LANG_ORDER)
            kv_cache = kv_get_many(ftxt_env, [jnums[i].encode("utf-8") for i in valid_jn_fp])
            for i in valid_jn_fp:
                job_number = jnums[i]
                cache = kv_cache[job_number.encode('utf-8')]
                if cache is None: continue
                src_lang = ORDER2LANG[i]
                paras = {
                    line for line in cache.decode('utf-8').split('\n\n')
                }
                paras = [x for x in paras if is_meaningful_line(x, src_lang)]
                if not paras: continue
                text_path = const.CONVERT_TEXT_FLATTEN_TABLE_CACHE_DIR / f"{jnums[i]}.txt"
                yield text_path, src_lang, paras

def gen_filewise():
    ftxt_env: lmdb.Environment = lmdb.open(
        str(const.V4_FTXT_DIR),
        map_size=LMDB_MAP_SIZE_BYTES,
        subdir=True,
        readonly=True,
        lock=True,
        max_dbs=1,
        readahead=True,
    )
    for row in _iter_pkl():
        jnums = row["job_numbers"]
        query = [jnums[i].encode("utf-8") for i in range(7) if jnums[i]]
        kv_cache = kv_get_many(ftxt_env, query)
        ftxt = []
        for p, i in enumerate(ORDER2LANG):
            t = kv_cache.get(jnums[p].encode("utf-8"))
            if t:
                t = t.decode("utf-8")
                if not is_meaningful_line(t, i): # discard meaningless file, especially from wpf exported Arabic
                    t = None
            ftxt.append(t or "")
        row["ftxt"] = ftxt
        # yield row
        yield {
            '文件名': row['id'],
            'ar_text': ftxt[0],
            'zh_text': ftxt[1],
            'en_text': ftxt[2],
            'fr_text': ftxt[3],
            'ru_text': ftxt[4],
            'es_text': ftxt[5],
            'de_text': ftxt[6],
        }

def gen_sbd_dataset():
    sbd_env = lmdb.open(
        str(const.V4_SBD_DIR),
        readonly=True, lock=True, subdir=True,
    )
    for text_path, src_lang, paras in _iter_non_eng():
        para_keys = [make_key(src_lang, TARGET_LANG, p) for p in paras]
        sbd_hits = kv_get_many(sbd_env, para_keys)
        for p, k in zip(paras, para_keys):
            hit = sbd_hits.get(k)
            if not hit:
                print(f"[WARN] incomplete sbd:{text_path} {src_lang} {p} miss:{k}")
                continue
            yield {
                "sha256": k,
                "src_lang": src_lang,
                "dst_lang": TARGET_LANG,
                "before_sbd": p,
                "after_sbd": decode_sentences(hit)[0],
            }


def gen_tr_dataset():
    sbd_env = lmdb.open(
        str(const.V4_SBD_DIR),
        readonly=True, lock=True, subdir=True,
        readahead=True, max_dbs=1
    )
    for text_path, src_lang, paras in _iter_non_eng():
        for pi, p in enumerate(paras):
            para_keys = [make_key(src_lang, TARGET_LANG, p) for p in paras]
            sbd_hits = kv_get_many(sbd_env, para_keys)
            sentences = []
            for p, k in zip(paras, para_keys):
                hit = sbd_hits.get(k)
                if not hit:
                    print(f"[WARN] incomplete sbd:{text_path} {src_lang} paraidx:{pi} {p} miss:{k}")
                    continue
                sentences.extend(decode_sentences(hit)[0])
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

def recover_translated_para(paras: list[str], src_lang: str):
    sbd_env = lmdb.open(
        str(const.V4_SBD_DIR),
        readonly=True, lock=True, subdir=True,
        readahead=True, max_dbs=1
    )
    tr_paras = []
    for pi, p in enumerate(paras):
        sentences = []
        if not is_meaningful_line(p, src_lang):
            tr_paras.append(p)
            continue
        para_keys = [make_key(src_lang, TARGET_LANG, p) for p in paras]
        sbd_hits = kv_get_many(sbd_env, para_keys)
        for p, k in zip(paras, para_keys):
            hit = sbd_hits.get(k)
            if not hit:
                print(f"[WARN] incomplete sbd:{src_lang} paraidx:{pi} {p} miss:{k}")
                continue
            sentences.extend(decode_sentences(hit)[0])
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
    for row in _iter_pkl():
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
    # ds_ftxt = Dataset.from_generator(gen_filewise, features=Features({
    #     "id": Value("string"),
    #     "symbol": Value("string"),
    #     "symbols": List(Value("string"), length=3),
    #     "publication_date": Value("string"),
    #     "area": Value("string"),
    #     "distribution": Value("string"),
    #     "agendas": List(Value("string"), length=3),
    #     "sessions": List(Value("string"), length=3),
    #     "job_numbers": List(Value("string"), length=7),
    #     "release_dates": List(Value("string"), length=7),
    #     "sizes": List(Value("int64"), length=21),
    #     "title": Value("string"),
    #     "subjects": List(Value("string")),
    #     "ftxt": List(Value("string"), length=7),
    # }))
    # ds_ftxt.save_to_disk(const.WORK_DIR / "v4_ds_ftxt")
    # ds_ftxt.push_to_hub(
    #     "bot-yaya/UPRPRC_FTXT_FILEWISE",
    #     private=False,
    #     max_shard_size="2GB",
    #     token=os.environ.get("HF_TOKEN"),
    # )

    # with const.FILEWISE_JSONL_OUTPUT_DIR.open("w", encoding="utf-8") as f:
    #     for row in tqdm(gen_filewise()):
    #         f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

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
    # ds_tr = Dataset.from_generator(gen_tr_dataset, features=Features({
    #     "sha256": Value("binary"),
    #     "src_lang": Value("string"),
    #     "dst_lang": Value("string"),
    #     "src": Value("string"),
    #     "tr": Value("string"),
    # }))
    # ds_tr.save_to_disk(const.WORK_DIR / "v4_ds_tr")
    # ds_tr.push_to_hub(
    #     "bot-yaya/UPRPRC_TR_KV",
    #     private=False,
    #     max_shard_size="2GB",
    #     token=os.environ.get("HF_TOKEN"),
    # )
    # ds_bilingual = Dataset.from_generator(gen_bilingual_align, features=Features({
    #     "id": Value("string"),
    #     "src_job_number": Value("string"),
    #     "dst_job_number": Value("string"),
    #     "clean_para_index_set_pair": Value("string"),
    #     "src_lang": Value("string"),
    #     "dst_lang": Value("string"),
    #     "src_text": Value("string"),
    #     "dst_text": Value("string"),
    #     "src_rate": Value("float"),
    #     "dst_rate": Value("float"),
    # }))
    # ds_bilingual.save_to_disk(const.WORK_DIR / "v4_ds_tr")
    # ds_bilingual.push_to_hub(
    #     "bot-yaya/UPRPRC_TR_KV",
    #     private=False,
    #     max_shard_size="2GB",
    #     token=os.environ.get("HF_TOKEN"),
    # )

if __name__ == "__main__":
    main()
