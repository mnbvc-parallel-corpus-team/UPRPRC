import os, pickle
from typing import Iterator, Dict, Any

from datasets import Dataset, Features, Value, List

import const

# === 配置区 ===

REPO_ID = "bot-yaya/UPRPRC_docfiles_from_UN"   # 目标 HF 数据集仓库
PRIVATE = False                              # 是否私有
MAX_SHARD_SIZE = "2GB"                       # 自动分片上限，兼顾稳健上传
HF_TOKEN = os.environ.get("HF_TOKEN")        # 或者登录本机: huggingface-cli login

def row_generator() -> Iterator[Dict[str, Any]]:
    for fn in const.V4_DOCUMENT_CACHE.iterdir():
        with fn.open("rb") as f:
            pkl = pickle.load(f)
        for row in pkl:
            valid_docs_job_numbers = []
            sizes = row['sizes']
            for i in range(7):
                # pdf_size = sizes[i * 3]
                doc_size = sizes[i * 3 + 2]
                # if sizes[i * 3 + 1] != -1: # 可能是wpf
                    # print(f"DETECT MID SIZE:{row} {sizes[i * 3 + 1]}")
                if doc_size > 0:
                    valid_docs_job_numbers.append(i)
            blobs = [b'' for _ in range(7)]
            crawl_res = ["" for _ in range(7)]
            if len(valid_docs_job_numbers) > 1:
                for vi in valid_docs_job_numbers:
                    v = row['job_numbers'][vi]
                    save_paths = {
                        'pdf': const.DOWNLOAD_DOC_CACHE_DIR / f"pdf/{v}.pdf",
                        'wpf': const.DOWNLOAD_DOC_CACHE_DIR / f"wpf/{v}.wpf",
                        'doc': const.DOWNLOAD_DOC_CACHE_DIR / f"doc/{v}.doc",
                        'wpd': const.DOWNLOAD_DOC_CACHE_DIR / f"wpd/{v}.wpd",
                        # '404': const.DOWNLOAD_DOC_CACHE_DIR / f"404/{v}",
                    }
                    for typ, sp in save_paths.items():
                        if sp.exists():
                            with sp.open("rb") as f:
                                blobs[vi] = f.read()
                            crawl_res[vi] = typ
                            break
                    if not crawl_res[vi]:
                        if (const.DOWNLOAD_DOC_CACHE_DIR / f"404/{v}").exists():
                            crawl_res[vi] = '404'
                        else:
                            print(f"UNEXPECTED RESULT:{v} {fn}")
                            exit(1)
            row["blobs"] = blobs
            row["crawl_res"] = crawl_res
            yield row

# 明确声明 Features，避免推断出错
features = Features({
    "id": Value("string"),
    "symbol": Value("string"),
    "symbols": List(Value("string"), length=3),
    "publication_date": Value("string"),
    "area": Value("string"),
    "distribution": Value("string"),
    "agendas": List(Value("string"), length=3),
    "sessions": List(Value("string"), length=3),
    "job_numbers": List(Value("string"), length=7),
    "release_dates": List(Value("string"), length=7),
    "sizes": List(Value("int64"), length=21),
    "title": Value("string"),
    "subjects": List(Value("string")),
    "blobs": List(Value("large_binary"), length=7),
    "crawl_res": List(Value("string"), length=7),
})

# 用生成器流式构建，不把 180 万条路径全塞到内存
ds = Dataset.from_generator(row_generator, features=features)

# 可选：本地落盘备份（Arrow），再推
# ds.save_to_disk("./_local_arrow_backup")

# 直接推到 Hub，自动分片，commit 尽量少以提高成功率
ds.push_to_hub(
    REPO_ID,
    private=PRIVATE,
    max_shard_size=MAX_SHARD_SIZE,
    # num_shards=None  # 交给 max_shard_size 控制
    token=HF_TOKEN,
)

print("Done.")