import pickle
import gc
import time
import traceback
import multiprocessing as mp
from queue import Empty

import lmdb

import const
from v4_helpers import make_key, kv_get_many, kv_put_many, is_meaningful_line, encode_sentences, decode_sentences, get_or_install_package, build_stanza, sbd_with_stanza, \
    EN_LANG_ORDER, ORDER2LANG, _ZD, LMDB_MAP_SIZE_BYTES, TARGET_LANG, SBD_LMDB_MAP_SIZE

# =========================
# 配置
# =========================
TASK_GEN_WORKERS = 5
# 不够可以热扩 `env.set_mapsize(new_size)`.

const.V4_SBD_DIR.mkdir(exist_ok=True)

# =========================
# 数据集与任务生成
# =========================

def gen_task(qin: mp.Queue):
    sbd_env: lmdb.Environment = lmdb.open(
        str(const.V4_SBD_DIR),
        map_size=SBD_LMDB_MAP_SIZE,
        subdir=True,
        readonly=True,
        lock=True,
        max_dbs=1,
        readahead=False,
    )
    ftxt_env: lmdb.Environment = lmdb.open(
        str(const.V4_FTXT_DIR),
        map_size=LMDB_MAP_SIZE_BYTES,
        subdir=True,
        readonly=True,
        lock=True,
        max_dbs=1,
        readahead=False,
    )
    # while 1:
    fcount = 0
    # fptr = 0
    prv_time = time.time()
    for fn in const.V4_DOCUMENT_CACHE.iterdir():
        # fptr += 1
        fcount += 1
        # if fcount < 11820:
            # continue
        if fcount % 100 == 0:
            t1 = time.time()
            print(f"C:{fcount} T:{t1 - prv_time}")
            # cleared = sbd_env.reader_check()
            # if cleared:
            #     print("sbd_env:", cleared)
            # sbd_env.close()
            # sbd_env: lmdb.Environment = lmdb.open(
            #     str(const.V4_SBD_DIR),
            #     map_size=SBD_LMDB_MAP_SIZE,
            #     subdir=True,
            #     readonly=True,
            #     lock=True,
            #     max_dbs=1,
            #     readahead=True,
            # )
            # cleared = ftxt_env.reader_check()
            # if cleared:
            #     print("ftxt_env:", cleared)
            # ftxt_env.close()
            # ftxt_env: lmdb.Environment = lmdb.open(
            #     str(const.V4_FTXT_DIR),
            #     map_size=LMDB_MAP_SIZE_BYTES,
            #     subdir=True,
            #     readonly=True,
            #     lock=True,
            #     max_dbs=1,
            #     readahead=True,
            # )
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
                do_write = 0
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
                        if not sbd_hits[para_key]:
                            sbd_to_process.append((para_key, para))
                    if sbd_to_process:
                        qin.put((src_lang, sbd_to_process))
                        do_write += len(sbd_to_process)
                if do_write:
                    print(f"S:{do_write} C:{fcount}")
    for _ in range(TASK_GEN_WORKERS):
        qin.put(None)

def txt2sbd(qout: mp.Queue, qin: mp.Queue, rank: int, use_gpu: bool):
    while 1:
        t = qin.get()
        if t is None:
            break
        src_lang, sbd_to_process = t
        pkg = get_or_install_package(src_lang, TARGET_LANG)
        stanza_pipe = build_stanza(src_lang, pkg, use_gpu=use_gpu)
        sbd_to_cache = []
        for pk, para in sbd_to_process:
            sents = sbd_with_stanza(stanza_pipe, para)
            if sents:
                sbd_to_cache.append((pk, encode_sentences(sents, src_lang, TARGET_LANG)))
        if sbd_to_cache:
            qout.put(sbd_to_cache)
            print(f"R:{rank} W:{len(sbd_to_cache)}")
    qout.put(None)
    
if __name__ == '__main__':
    print(str(const.V4_FTXT_DIR), str(const.V4_SBD_DIR))
    qout = mp.Queue()
    qin = mp.Queue(maxsize=128)
    proc = [
        mp.Process(target=txt2sbd, args=(qout, qin, rk, True)) for rk in range(TASK_GEN_WORKERS)
        # mp.Process(target=txt2sbd, args=(q, str(const.V4_FTXT_DIR), str(const.V4_SBD_DIR), 0, True)),
        # mp.Process(target=txt2sbd, args=(q, str(const.V4_FTXT_DIR), str(const.V4_SBD_DIR), 1, True)),
        # mp.Process(target=txt2sbd, args=(q, str(const.V4_FTXT_DIR), str(const.V4_SBD_DIR), 2, True)),
        # mp.Process(target=txt2sbd, args=(q, str(const.V4_FTXT_DIR), str(const.V4_SBD_DIR), 3, True)),
        # mp.Process(target=txt2sbd, args=(q, str(const.V4_FTXT_DIR), str(const.V4_SBD_DIR), 4, True)),
        # mp.Process(target=txt2sbd, args=(q, str(const.V4_FTXT_DIR), str(const.V4_SBD_DIR), 5, True)),
    ] + [mp.Process(target=gen_task, args=(qin,))]
    for x in proc:
        x.start()
    sbd_env: lmdb.Environment = lmdb.open( # para sha256 => zstd sentences
        str(const.V4_SBD_DIR),
        map_size=SBD_LMDB_MAP_SIZE,
        subdir=True,
        readonly=False,
        lock=True,
        max_dbs=1,
        # writemap=True,
        # map_async=True,
        readahead=False,
    )
    cnone = 0
    write_cnt = 0
    while cnone < TASK_GEN_WORKERS:
        sbd_to_cache = qout.get()
        if sbd_to_cache is None:
            cnone += 1
        else:
            try:
                while 1:
                    stc = qout.get_nowait()
                    if stc is None:
                        cnone += 1
                        break
                    else:
                        sbd_to_cache.extend(stc)
            except Empty:
                pass
            except Exception as e:
                exc = traceback.format_exc()
                print(exc)
                with open(const.WORKDIR / "v4sbderr.log", "w") as f:
                    f.write(exc)
            finally:
                kv_put_many(sbd_env, sbd_to_cache)
                print(f"T:{time.time()} W:{len(sbd_to_cache)}")
                write_cnt += 1
                if write_cnt == 10:
                    write_cnt = 0
                    sbd_env.sync(True)
                    print(f"SYNC {time.time()}")
                    # t0 = time.time()
                    # print(f"RC a {t0}")
                    # cleared = sbd_env.reader_check()
                    # if cleared:
                    #     print("cleared zombie readers:", cleared)
                    # print(f"RC d {time.time() - t0}")

    for x in proc:
        x.join()
    print("ALL DONE.")