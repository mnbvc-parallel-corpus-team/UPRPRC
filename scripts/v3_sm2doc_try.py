import asyncio
import csv
from pathlib import Path
import re

import requests

from new_sample_get_doc_async_candidate import get_doc, doc_cache_dir, task_list, WORKERS


# https://digitallibrary.un.org/search?ln=zh_CN&p=&f=&c=Resource%20Type&c=UN%20Bodies&sf=&so=d&rg=50&fti=0
# POST https://documents.un.org/api/search?l=en&rid=1f176b95-f5f1-473e-9b01-967fe74e0c5d
# {"symbol":"","jobNumber":"*","publicationDate":"* TO *","releaseDate":"* TO *","title":"","subject":"","session":"","agenda":"","truncation":"right","fullTextSearch":{"language":"en","searchText":"","type":"Find this phrase","exact":false},"sortOptions":{"sortField":"Sort by symbol"},"pagination":{"currentPage":29690,"itemsPerPage":20},"screenLanguage":"en","tcodes":[]}


WD = Path(__file__).parent

PATTERN_RECORD_ID = re.compile("\d+")
PATTERN_SYMBOL = re.compile(r"\d+/files/([^\.]+)\.pdf")

input_file = WD / "un_library_sitemap_data.csv"

LANG_MAP = {
    'AR': 'A',
    'ZH': 'C',
    'EN': 'E',
    'FR': 'F',
    'RU': 'R',
    'ES': 'S',
    'DE': 'O',
}

async def amain():
    with open(input_file, "r", encoding="utf-8") as f:
        cr = csv.DictReader(f)
        for i in cr:
            # print(i)
            sb = i["loc"][37:]
            recid = int(PATTERN_RECORD_ID.match(sb).group())
            # rec_id_set.add(recid)
            filename_sb = PATTERN_SYMBOL.match(sb)
            if not filename_sb:
                continue
            r = filename_sb.groups()[0]
            match_lang = None
            match_symbol = None
            match_lang_shorts = None
            for lang, shorts in LANG_MAP.items():
                ls = f"-{lang}"
                if r.endswith(ls):
                    match_lang_shorts = shorts
                    match_lang = lang
                    match_symbol = r.removesuffix(ls)
                    break
            if match_lang:
                match_symbol = match_symbol.replace("_","/")
                match_lang = match_lang.lower()
                print(f"put {recid} {match_symbol} {match_lang_shorts}")
                await task_list.put((match_symbol, match_lang_shorts, f"{recid}={match_lang}"))

    # print(len(rec_id_set), len(symbol_set), len(reslist))
        

async def main():
    workers = [
        get_doc() for _ in range(WORKERS)
    ] + [amain()]
    await asyncio.gather(*workers)

if __name__ == "__main__":
    asyncio.run(main())

# rec_id_set = set()
# symbol_set = set()
# reslist = []
