from pathlib import Path
import asyncio
import json

from tqdm import tqdm
import datasets

from new_sample_get_doc_async_candidate import get_doc, doc_cache_dir, task_list, WORKERS

WD = Path(__file__).parent
DS_PATH = WD / 'documents.un.org_search_result'

async def amain():
    ds = datasets.load_from_disk(DS_PATH)['train']
    symbolset = set()
    jstrset = set()
    for i in tqdm(ds):
        s = i["id"]
        jstr = json.dumps(i, sort_keys=True)
        sbcond = s in symbolset
        if sbcond:
            print("dup sb",s)
        dtcond = jstr in jstrset
        if dtcond:
            print("dup data", s)
        if sbcond and not dtcond:
            print("MULTI SYMBOL:", s)
        symbolset.add(s)
        jstrset.add(jstr)
    print(len(symbolset))

if __name__ == "__main__":
    asyncio.run(amain())
