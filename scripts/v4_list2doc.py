from pathlib import Path
import asyncio

from tqdm import tqdm
import datasets

from new_sample_get_doc_async_candidate import get_doc, doc_cache_dir, task_list, WORKERS

WD = Path(__file__).parent
DS_PATH = WD / 'documents.un.org_search_result'
DOCUMENT_SEARCH_CACHE_DIR = WD / "doc_search_cache"

# 读 sizes 顺序是 ar zh en fr ru es de
# 头一个是pdf，中间固定-1，尾部是doc
# 只有一个语言的不要下载

async def gen_task():
    ds = datasets.load_from_disk(DS_PATH)['train']
    for row in tqdm(ds):
        valid_docs_job_numbers = []
        sizes = row['sizes']
        for i in range(7):
            # pdf_size = sizes[i * 3]
            doc_size = sizes[i * 3 + 2]
            # if sizes[i * 3 + 1] != -1: # 可能是wpf
                # print(f"DETECT MID SIZE:{row} {sizes[i * 3 + 1]}")
            if doc_size > 0:
                valid_docs_job_numbers.append(row['job_numbers'][i])
        if len(valid_docs_job_numbers) > 1:
            for v in valid_docs_job_numbers:
                await task_list.put((f"j={v}", v))

    for _ in range(WORKERS):
        await task_list.put(None)

async def gen_task_by_dl_cache():
    import pickle
    while 1:
        for fn in tqdm(DOCUMENT_SEARCH_CACHE_DIR.glob("*")):
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
                        valid_docs_job_numbers.append(row['job_numbers'][i])
                if len(valid_docs_job_numbers) > 1:
                    for v in valid_docs_job_numbers:
                        await task_list.put((f"j={v}", v))
        await asyncio.sleep(30)
        print('scan dl done. sleep 30s')
    for _ in range(WORKERS):
        await task_list.put(None)

async def amain():
    workers = [
        get_doc() for _ in range(WORKERS)
    ] + [gen_task_by_dl_cache()]
    await asyncio.gather(*workers)

if __name__ == "__main__":
    asyncio.run(amain())
