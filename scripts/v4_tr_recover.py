# recover_docs.py
import json
import pickle
from pathlib import Path
from typing import Tuple, Optional
import os
import multiprocessing as mp

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
    tr_env = lmdb.open(
        str(const.V4_TR_DIR),
        readonly=True, lock=True, subdir=True,
        readahead=True, max_dbs=1
    )
    for text_path, src_lang, paras in _iter_non_eng():
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
        vals = kv_get_many(tr_env, keys)
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

def recover_translated_para(paras: list[str], src_lang: str, sbd_env, tr_env):
    tr_paras = [None] * len(paras)
    valid_paras = []
    for pi, p in enumerate(paras):
        if not is_meaningful_line(p, src_lang):
            tr_paras[pi] = p
            continue
        valid_paras.append((pi, p, make_key(src_lang, TARGET_LANG, p)))
    sbd_hits = kv_get_many(sbd_env, [x[2] for x in valid_paras])
    for pi, p, pkey in valid_paras:
        hit = sbd_hits.get(pkey)
        if not hit:
            print(f"[WARN] incomplete sbd:{src_lang} paraidx:{pi} {p} miss:{k}")
            continue
        sentences = decode_sentences(hit)[0]
        keys = [make_key(src_lang, TARGET_LANG, s) for s in sentences]
        vals = kv_get_many(tr_env, keys)
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
        tr_paras[pi] = ''.join(trans_sents)
    assert None not in tr_paras
    return tr_paras

BILINGUAL_ALIGN_WORKERS = 1
QUEUE_PENDING_WORK = 128

def gen_bilingual_align_producer(qin: mp.Queue):
    for row in _iter_pkl():
        qin.put(row)
    for _ in range(BILINGUAL_ALIGN_WORKERS):
        qin.put(None)

def gen_bilingual_align_consumer(qin: mp.Queue, qout: mp.Queue):
    print("consumer start")
    ftxt_env: lmdb.Environment = lmdb.open(
        str(const.V4_FTXT_DIR),
        # map_size=LMDB_MAP_SIZE_BYTES,
        subdir=True,
        readonly=True,
        lock=True,
        max_dbs=1,
        readahead=True,
    )
    sbd_env = lmdb.open(
        str(const.V4_SBD_DIR),
        readonly=True, lock=True, subdir=True,
        readahead=True, max_dbs=1
    )
    tr_env = lmdb.open(
        str(const.V4_TR_DIR),
        readonly=True, lock=True, subdir=True,
        readahead=True, max_dbs=1
    )
    const.V4_BILINGUAL_ALIGN_CACHE.mkdir(exist_ok=True, parents=True)
    from urllib.parse import quote
    while 1:
        row = qin.get()
        if row is None:
            qout.put(None)
            return
        rowwise_output_cache = const.V4_BILINGUAL_ALIGN_CACHE / quote(row["id"], safe="")
        if rowwise_output_cache.exists():
            with rowwise_output_cache.open("rb") as f:
                for res_row in pickle.load(f):
                    qout.put(res_row)
            continue
        rowwise_cache = []
        sizes = row["sizes"]
        jnums = row["job_numbers"]
        tr_para_cache = {}
        valid_jn_fp = []
        for i, lang in enumerate(ORDER2LANG):
            doc_size = sizes[i*3 + 2]
            if doc_size <= 0:
                continue
            valid_jn_fp.append(i)
        if len(valid_jn_fp) <= 1:
            continue
        kv_cache = kv_get_many(ftxt_env, [jnums[i].encode("utf-8") for i in valid_jn_fp])
        for i, lang in enumerate(ORDER2LANG):
            hit = kv_cache.get(jnums[i].encode("utf-8"))
            if not hit:
                continue
            rawtext = hit.decode("utf-8")
            if not is_meaningful_line(rawtext, lang): # discard meaningless files
                continue
            paras = rawtext.split("\n\n")
            tr_para_cache[lang] = (paras, recover_translated_para(paras, lang, sbd_env, tr_env) if lang != TARGET_LANG else paras)
        if len(tr_para_cache) <= 1:
            continue
        for p, src_lang in enumerate(ORDER2LANG):
            src_cache = tr_para_cache.get(src_lang)
            if not src_cache:
                continue
            src_paras, src_tr = src_cache
            for q in range(p+1, len(ORDER2LANG)):
                dst_lang = ORDER2LANG[q]
                dst_cache = tr_para_cache.get(dst_lang)
                if not dst_cache:
                    continue
                dst_paras, dst_tr = dst_cache
                src_job_number = jnums[p]
                dst_job_number = jnums[q]

                aligned, pairs, preview = align(src_paras, dst_paras, src_tr, dst_tr)
                for apairs, atext in zip(aligned, pairs):
                    i, o, _ir, _or = atext
                    rowwise_cache.append({
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
                    })
        with rowwise_output_cache.open("wb") as f:
            pickle.dump(rowwise_cache, f)
        for x in rowwise_cache:
            qout.put(x)
        del rowwise_cache

def gen_bilingual_align(qout: mp.Queue):
    nonectr = 0
    while 1:
        res_row = qout.get()
        if res_row is None:
            nonectr += 1
            if nonectr == BILINGUAL_ALIGN_WORKERS:
                return
            continue
        yield res_row
        
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

    # ds_sbd = Dataset.from_generator(gen_sbd_dataset, features=Features({
    #     "sha256": Value("binary"),
    #     "src_lang": Value("string"),
    #     "dst_lang": Value("string"),
    #     "before_sbd": Value("string"),
    #     "after_sbd": List(Value("string")),
    # }))
    # ds_sbd.save_to_disk(const.WORK_DIR / "v4_ds_sbd")
    # ds_sbd.push_to_hub(
    #     "bot-yaya/UPRPRC_SBD_KV",
    #     private=False,
    #     max_shard_size="2GB",
    #     token=os.environ.get("HF_TOKEN"),
    # )
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
    qin = mp.Queue(maxsize=QUEUE_PENDING_WORK)
    qout = mp.Queue(maxsize=QUEUE_PENDING_WORK)
    bilingual_workers = [
        mp.Process(target=gen_bilingual_align_consumer, args=(qin,qout)) for _ in range(BILINGUAL_ALIGN_WORKERS)
    ] + [mp.Process(target=gen_bilingual_align_producer, args=(qin,))]
    for x in bilingual_workers:
        x.start()
    output_jsonl_path = Path(r"C:\etc\UPRPRC-bilingual.jsonl")
    with open(output_jsonl_path, "w", encoding="utf-8") as f:
        for res_row in tqdm(gen_bilingual_align(qout)):
            f.write(json.dumps(res_row, ensure_ascii=False) + "\n")

    for x in bilingual_workers:
        x.join()

    ds_bilingual = Dataset.from_json(str(output_jsonl_path), features=Features({
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
    ds_bilingual.save_to_disk(const.WORK_DIR / "v4_ds_bilingual")
    ds_bilingual.push_to_hub(
        "bot-yaya/UPRPRC_BILINGUAL",
        private=False,
        max_shard_size="2GB",
        token=os.environ.get("HF_TOKEN"),
    )

if __name__ == "__main__":
    main()
