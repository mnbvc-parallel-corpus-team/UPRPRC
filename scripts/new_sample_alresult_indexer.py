import os
import json
import random
import shutil
os.environ['ARGOS_DEVICE_TYPE'] = 'cuda'

import datasets


import const

# ALL_SOURCE_LANGS = ('zh','ar','fr','es','ru')
ALL_SOURCE_LANGS = ('zh',)
DST_DOC_PATH = const.ALIGN_OUTPUT_DIR / '源doc样例'

if __name__ == "__main__":
    for lang in ALL_SOURCE_LANGS:
        with open(const.ALIGN_OUTPUT_DIR / f'{lang}2en_dumpall_sorted.jsonl', 'r') as f:
            li = f.read().splitlines()
            print(len(li))
            li = [json.loads(line) for line in li if len(line) > 10000]
        print(len(li))
        record_set = set()
        for i, item in enumerate(li):
            record = item['record']
            record = record[:record.rfind('_')]
            print(record, len(item['src_text']))
            record_set.add(record)
        for lite_filename in os.listdir(const.DOWNLOAD_FILELIST_CACHE_DIR):
            filename = const.DOWNLOAD_FILELIST_CACHE_DIR / lite_filename
            with open(filename, 'r') as f:
                fcontent = f.read()
                fjson = json.loads(fcontent)
                for doc_idx, doc in enumerate(fjson['docs']):
                    if doc['symbol'] in record_set: # and doc['body'] != 'No full text found!'
                        filelist_idx = int(lite_filename.removeprefix('2023-2023_').removesuffix('.json'))
                        print('found:', doc['symbol'], 'in', filelist_idx, doc_idx, f"2023-2023_{filelist_idx}-{doc_idx}={lang}.doc")
                        try:
                            shutil.copy(const.DOWNLOAD_DOC_CACHE_DIR / 'doc' / f"2023-2023_{filelist_idx}-{doc_idx}={lang}.doc", DST_DOC_PATH / f"2023-2023_{filelist_idx}-{doc_idx}={lang}.doc")
                            shutil.copy(const.CONVERT_TEXT_CACHE_DIR / f"2023-2023_{filelist_idx}-{doc_idx}={lang}.txt", DST_DOC_PATH / f"2023-2023_{filelist_idx}-{doc_idx}={lang}.txt")
                            shutil.copy(const.DOWNLOAD_DOC_CACHE_DIR / 'doc' / f"2023-2023_{filelist_idx}-{doc_idx}=en.doc", DST_DOC_PATH / f"2023-2023_{filelist_idx}-{doc_idx}=en.doc")
                            shutil.copy(const.CONVERT_TEXT_CACHE_DIR / f"2023-2023_{filelist_idx}-{doc_idx}=en.txt", DST_DOC_PATH / f"2023-2023_{filelist_idx}-{doc_idx}=en.txt")
                        except Exception as e:
                            print('copy error:', e)
