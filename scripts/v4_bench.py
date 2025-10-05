import pickle
import os
import time

import msgpack

from const import V4_DOCUMENT_CACHE

def pickle2msgpack():
    for fn in V4_DOCUMENT_CACHE.iterdir():
        if fn.name.endswith(".pkl"):
            with fn.open("rb") as f:
                pkl = pickle.load(f)
            tfn = str(fn.absolute()).replace(".pkl", ".tmp")
            msgpack_fn = str(fn.absolute()).replace(".pkl", ".msgpack")
            with open(tfn, "wb") as f:
                msgpack.pack(pkl, f)
            os.replace(tfn, msgpack_fn)
            # fn.unlink()
            print(fn.name, ">>", msgpack_fn)

def clear_msgpack():
    for fn in list(V4_DOCUMENT_CACHE.iterdir()):
        if fn.name.endswith(".msgpack"):
            fn.unlink()

def bench_pickle():
    t0 = time.time()
    for fn in V4_DOCUMENT_CACHE.iterdir():
        if fn.name.endswith(".pkl"):
            with fn.open("rb") as f:
                pkl = pickle.load(f)
    t1 = time.time()
    print(f"pickle: {t1 - t0}") # 5.420s

def bench_msgpack():
    t0 = time.time()
    for fn in V4_DOCUMENT_CACHE.iterdir():
        if fn.name.endswith(".msgpack"):
            with fn.open("rb") as f:
                pkl = msgpack.load(f)
    t1 = time.time()
    print(f"msgpack: {t1 - t0}") # 5.722s


def bench_enumerate_ftxt():
    import const
    from v4_helpers import EN_LANG_ORDER, ORDER2LANG
    fcount = 0
    t0 = time.time()
    for fn in const.V4_DOCUMENT_CACHE.iterdir(): # About 15s per 100 item
        fcount += 1
        if fcount % 100 == 0:
            print(f"GEN TASK CURRENT IDX:{fcount} Elapsed:{time.time() - t0}")
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
                for i in valid_jn_fp:
                    job_number = row['job_numbers'][i]
                    flattxt_file = const.CONVERT_TEXT_FLATTEN_TABLE_CACHE_DIR / f"{job_number}.txt"
                    paras = {
                        line for line in flattxt_file.read_text(encoding="utf-8").split('\n\n')
                    }
    print(f"raw ftxt:{time.time() - t0}")

def rawftxt2lmdb():
    import lmdb
    import const
    from v4_helpers import kv_put_many, LMDB_MAP_SIZE_BYTES
    ftxt_env = lmdb.open(
        str(const.V4_FTXT_DIR),
        map_size=LMDB_MAP_SIZE_BYTES,
        subdir=True,
        readonly=False,
        lock=True,
        max_dbs=1,
        writemap=True,
        map_async=True,
        readahead=True,
    )

    fctr = 0
    t0 = time.time()
    for fn in const.CONVERT_TEXT_FLATTEN_TABLE_CACHE_DIR.iterdir():
        fctr+=1
        if fctr % 1000 == 0:
            print(f"{fctr} {time.time() - t0}")
        k = fn.stem
        kv_put_many(ftxt_env, [(k.encode('utf-8'), fn.read_bytes())])
    print(f"ftxt>>lmdb done. Time:{time.time() - t0}")

def bench_enumerate_ftxt():
    import const
    import lmdb
    from v4_helpers import EN_LANG_ORDER, ORDER2LANG, LMDB_MAP_SIZE_BYTES, kv_get_many
    
    ftxt_env = lmdb.open(
        str(const.V4_FTXT_DIR),
        map_size=LMDB_MAP_SIZE_BYTES,
        subdir=True,
        readonly=True,
        lock=True,
        max_dbs=1,
        readahead=True,     # 顺序读友好
    )
    fcount = 0
    t0 = time.time()

    for fn in const.V4_DOCUMENT_CACHE.iterdir(): # About 15s per 100 item
        fcount += 1
        if fcount % 100 == 0:
            print(f"GEN TASK CURRENT IDX:{fcount} Elapsed:{time.time() - t0}")
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
                for job_number, rawtext in kv_get_many(ftxt_env, [row['job_numbers'][i] for i in valid_jn_fp]):
                    paras = {
                        line for line in rawtext.split('\n\n')
                    }
    print(f"lmdb ftxt:{time.time() - t0}")


if __name__ == "__main__":
    # bench_msgpack()
    # bench_pickle()
    # clear_msgpack()
    # bench_enumerate_ftxt()
    rawftxt2lmdb()

