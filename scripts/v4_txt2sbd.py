import pickle
import gc
import time
import traceback
import multiprocessing as mp

import lmdb

import const
from v4_helpers import make_key, kv_get_many, kv_put_many, is_meaningful_line, encode_sentences, decode_sentences, get_or_install_package, build_stanza, sbd_with_stanza, \
    EN_LANG_ORDER, ORDER2LANG, _ZD, LMDB_MAP_SIZE_BYTES, TARGET_LANG, SBD_LMDB_MAP_SIZE

# =========================
# 配置
# =========================
TASK_GEN_WORKERS = 6
# 不够可以热扩 `env.set_mapsize(new_size)`.

const.V4_SBD_DIR.mkdir(exist_ok=True)

# =========================
# 数据集与任务生成
# =========================

def txt2sbd(q: mp.Queue, ftxt_dir: str, sbd_dir: str, rank: int, use_gpu: bool):
    sbd_env = lmdb.open( # para sha256 => zstd sentences
        sbd_dir,
        map_size=SBD_LMDB_MAP_SIZE,
        subdir=True,
        readonly=True,
        lock=True,
        max_dbs=1,
        readahead=True,
    )
    ftxt_env = lmdb.open( # use lmdb for better IO performance, job_number => txt bytes
        ftxt_dir,
        map_size=LMDB_MAP_SIZE_BYTES,
        subdir=True,
        readonly=True,
        lock=True,
        max_dbs=1,
        readahead=True,
    )
    
    # while 1:
    fcount = 0
    fptr = 0
    prv_time = time.time()
    for fn in list(const.V4_DOCUMENT_CACHE.iterdir())[::-1]:
        fptr += 1
        if fptr % TASK_GEN_WORKERS != rank:
            continue
        fcount += 1
        if fcount % 100 == 0:
            t1 = time.time()
            print(f"R:{rank} FP:{fptr} C:{fcount} T:{t1 - prv_time}")
            prv_time = t1
        with fn.open("rb") as f:
            pkl = pickle.load(f)
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
                kv_cache = kv_get_many(ftxt_env, [row['job_numbers'][i].encode("utf-8") for i in valid_jn_fp])
                for i in valid_jn_fp:
                    job_number = row['job_numbers'][i]
                    src_lang = ORDER2LANG[i]
                    paras = {
                        # line for line in flattxt_file.read_text(encoding="utf-8").split('\n\n')
                        line for line in kv_cache[job_number.encode('utf-8')].decode('utf-8').split('\n\n')
                    }
                    paras = [x for x in paras if is_meaningful_line(x, src_lang)]
                    if not paras:
                        continue
                    para_keys = [make_key(src_lang, TARGET_LANG, p) for p in paras]
                    sbd_hits = kv_get_many(sbd_env, para_keys)
                    sbd_to_process = []
                    for para_key, para in zip(para_keys, paras):
                        if sbd_hits[para_key] is None:
                            sbd_to_process.append((para_key, para))
                    if sbd_to_process:
                        sbd_to_cache = []
                        pkg = get_or_install_package(src_lang, TARGET_LANG)
                        stanza_pipe = build_stanza(src_lang, pkg, use_gpu=use_gpu)
                        for pk, para in sbd_to_process:
                            sents = sbd_with_stanza(stanza_pipe, para)
                            if sents:
                                sbd_to_cache.append((pk, encode_sentences(sents, src_lang, TARGET_LANG)))
                        if sbd_to_cache:
                            q.put(sbd_to_cache)
                            
                            print(f"R:{rank} W:{len(sbd_to_cache)} PR:{len(paras)} HC:{len(paras) - len(sbd_to_cache)} FP:{fptr} I:{fcount} [{src_lang}]{job_number} from <{fn.name}>")
    q.put(None)
    
if __name__ == '__main__':
    print(str(const.V4_FTXT_DIR), str(const.V4_SBD_DIR))
    q = mp.Queue()
    proc = [
        mp.Process(target=txt2sbd, args=(q, str(const.V4_FTXT_DIR), str(const.V4_SBD_DIR), rk, True)) for rk in range(TASK_GEN_WORKERS)
        # mp.Process(target=txt2sbd, args=(q, str(const.V4_FTXT_DIR), str(const.V4_SBD_DIR), 0, True)),
        # mp.Process(target=txt2sbd, args=(q, str(const.V4_FTXT_DIR), str(const.V4_SBD_DIR), 1, True)),
        # mp.Process(target=txt2sbd, args=(q, str(const.V4_FTXT_DIR), str(const.V4_SBD_DIR), 2, True)),
        # mp.Process(target=txt2sbd, args=(q, str(const.V4_FTXT_DIR), str(const.V4_SBD_DIR), 3, True)),
        # mp.Process(target=txt2sbd, args=(q, str(const.V4_FTXT_DIR), str(const.V4_SBD_DIR), 4, True)),
        # mp.Process(target=txt2sbd, args=(q, str(const.V4_FTXT_DIR), str(const.V4_SBD_DIR), 5, True)),
    ]
    for x in proc:
        x.start()
    sbd_env = lmdb.open( # para sha256 => zstd sentences
        str(const.V4_SBD_DIR),
        map_size=SBD_LMDB_MAP_SIZE,
        subdir=True,
        readonly=False,
        lock=True,
        max_dbs=1,
        writemap=True,
        map_async=True,
        readahead=True,
    )
    from queue import Empty
    cnone = 0
    while cnone < TASK_GEN_WORKERS:
        sbd_to_cache = q.get()
        if sbd_to_cache is None:
            cnone += 1
        else:
            try:
                while 1:
                    stc = q.get_nowait()
                    if stc is None:
                        cnone += 1
                        break
                    else:
                        sbd_to_cache.extend(stc)
            except Empty:
                pass
            finally:
                kv_put_many(sbd_env, sbd_to_cache)
                print(f"T:{time.time()} W:{len(sbd_to_cache)}")

    for x in proc:
        x.join()
    print("ALL DONE.")