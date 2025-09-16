import os
import json
import asyncio
import traceback
from pathlib import Path

import aiohttp
import magic

import const

fl_cache_dir = const.DOWNLOAD_FILELIST_CACHE_DIR
fl_cache_dir.mkdir(exist_ok=True)
doc_cache_dir = const.DOWNLOAD_DOC_CACHE_DIR
doc_cache_dir.mkdir(exist_ok=True)

CHUNK_SIZE = 65536

CHUNK_PATH = doc_cache_dir / 'chunk'
CHUNK_PATH.mkdir(exist_ok=True)

SAVE_PATHS = {
    'pdf': doc_cache_dir / 'pdf' / "{save_filename}.pdf",
    'doc': doc_cache_dir / 'doc' / "{save_filename}.doc",
    'wpf': doc_cache_dir / 'wpf' / "{save_filename}.wpf",
    'wpd': doc_cache_dir / 'wpd' / "{save_filename}.wpd",
    '404': doc_cache_dir / '404' / "{save_filename}",
    'tmt': doc_cache_dir / 'tmt' / "{save_filename}",
    'exc': doc_cache_dir / 'exc' / "{save_filename}",
}

for sp in SAVE_PATHS.values():
    sp.parent.mkdir(exist_ok=True)

filelist = list(os.listdir(fl_cache_dir))

RETRIES = 3
WORKERS = 32

LANGMAP = {
    'ar': 'A',
    'zh': 'C',
    'zh-cn': 'C',
    'en': 'E',
    'fr': 'F',
    'ru': 'R',
    'es': 'S',
    # 'other': 'O', # 一般是德语
    'ot': 'O',
}

task_list = asyncio.Queue(maxsize=WORKERS)
pendingtask = set() # prevent same task have been submitted to multiple worker, when using scan partial list to generate tasks

async def get_doc():
    while 1:
        task_list_arg = await task_list.get()
        if task_list_arg is None:
            return
        urlarg, save_filename = task_list_arg
        url = f'https://documents.un.org/api/symbol/access?{urlarg}&t=doc'
        save_paths = {k: Path(str(sp.absolute()).format(save_filename=save_filename)) for k, sp in SAVE_PATHS.items()}

        if any(sp.exists() for sp in save_paths.values()):
            # print("skip", save_filename, "as", sp, "exists.")
            continue
        if '^' in urlarg or r'%5E' in urlarg:
            # print(f"skip {save_filename}: invalid ^ in urlarg {urlarg}")
            continue

        partial_file_path: Path = CHUNK_PATH / save_filename

        for retry in range(RETRIES):
            pendinglen = len(pendingtask)
            pendingtask.add(task_list_arg)
            if len(pendingtask) == pendinglen:
                break

            headers = {
                "accept-encoding":"gzip, deflate, br", # br压缩要额外装brotli这个库才能有requests支持
                "user-agent":"Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36"
            }
            existing_size = 0
            if partial_file_path.exists():
                existing_size = partial_file_path.stat().st_size
                headers["Range"] = f"bytes={existing_size}-"
            try:
                async with aiohttp.ClientSession(headers=headers) as session:
                    resp = await session.get(url, timeout=1800)
                    if resp.status in (200, 206):
                        if resp.status == 200 and existing_size > 0:
                            print(f"[{save_filename}] chunk file discarded as server do not support partial content")
                            existing_size = 0
                        else:
                            print(f"[{save_filename}] resume from {existing_size}")

                        mode = 'ab' if existing_size > 0 and resp.status == 206 else 'wb'
                        with open(partial_file_path, mode) as f:
                            async for chunk in resp.content.iter_chunked(CHUNK_SIZE):
                                f.write(chunk)
                            
                        with open(partial_file_path, 'rb') as f:
                            bin_content = f.read()

                        # bin_content = await resp.content.read()
                        url_suffix_lower = resp.url.suffix.lower()
                        typ = magic.from_buffer(bin_content, mime=True)
                        if typ == 'application/pdf' or url_suffix_lower == '.pdf':
                            save_dir_key = 'pdf'
                        elif typ in (
                            'application/msword',
                            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                        ) or url_suffix_lower in ('.doc', '.docx'):
                            save_dir_key = 'doc'
                        elif typ in (
                            "application/vnd.wordperfect",
                        ) or url_suffix_lower == '.wpf' :
                            save_dir_key = 'wpf'
                        elif url_suffix_lower == '.wpd':
                            save_dir_key = 'wpd'
                        else:
                            print(f'!!!!!unknown type: {typ} {url}!!!!!')
                            partial_file_path.rename(const.WORK_DIR / resp.url.name)
                            exit(1)
                        partial_file_path.rename(save_paths[save_dir_key])
                        print('download done:', save_paths[save_dir_key])
                        break
                    elif resp.status == 400:
                        print(f"!!!BAD REQUEST {url} {save_filename} !!!")
                        print(resp)
                        print(resp.headers)
                        print(await resp.text())
                        exit(1)
                    elif resp.status == 404:
                        # print(resp)
                        # print(resp.headers)
                        # print(await resp.text())
                        print(f'!!!!!404 NOT FOUND {url} {save_filename}!!!!!')
                        with open(save_paths['404'], "wb") as f:
                            f.write(urlarg.encode('utf-8'))
                        break
                    else:
                        if retry == RETRIES - 1:
                            print(resp)
                            print(resp.headers)
                            print(await resp.text())
                            print(f'!!!!!ERROR {url} {save_filename}!!!!!')
                            with open(save_paths['tmt'], "wb") as f:
                                f.write(b"[HEADER]\n" + str(dict(resp.headers)).encode('utf-8') + b"\n\n[BODY]\n" + (await resp.content.read()))
                            break
            except Exception as e:
                print(e)
                print('retry:', retry)
                if retry == RETRIES - 1:
                    print(f'!!!!!Exception {url} {save_filename}!!!!!')
                    with open(save_paths['exc'], "wb") as f:
                        f.write(traceback.format_exc().encode('utf-8'))
                    break
            finally:
                pendingtask.remove(task_list_arg)

async def main():
    for i in filelist:
        if i.endswith('.json'):
            with open(fl_cache_dir / i, 'r') as f:
                data = json.load(f)
            for idx, j in enumerate(data['docs']):
                symbol = j['symbol']
                langs = j['languageCode']
                for lang in langs:
                    lang = lang.lower()[:2]
                    if lang in LANGMAP:
                        l = LANGMAP[lang]
                        await task_list.put((f"s={symbol}&l={l}", f"{i.removesuffix('.json')}-{idx}={lang}"))
    for i in range(WORKERS):
        await task_list.put(None)
    workers = [
        get_doc() for _ in range(WORKERS)
    ]
    await asyncio.gather(*workers)
if __name__ == "__main__":
    asyncio.run(main())
