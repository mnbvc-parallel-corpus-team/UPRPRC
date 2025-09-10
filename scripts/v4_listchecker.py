from pathlib import Path
import asyncio

from tqdm import tqdm
import datasets

from new_sample_get_doc_async_candidate import get_doc, doc_cache_dir, task_list, WORKERS

WD = Path(__file__).parent
DS_PATH = WD / 'documents.un.org_search_result'

async def amain():
    ds = datasets.load_from_disk(DS_PATH)['train']
    symbolset = set()
    for i in tqdm(ds):
        s = i["symbol"]
        if s in symbolset:
            print(s)
        symbolset.add(s)

    print(len(symbolset))

if __name__ == "__main__":
    asyncio.run(amain())
