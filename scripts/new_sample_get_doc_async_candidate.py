import os
import json
import asyncio
import traceback

import aiohttp
import magic

import const


fl_cache_dir = const.DOWNLOAD_FILELIST_CACHE_DIR
fl_cache_dir.mkdir(exist_ok=True)
doc_cache_dir = const.DOWNLOAD_DOC_CACHE_DIR
doc_cache_dir.mkdir(exist_ok=True)
(doc_cache_dir / 'pdf').mkdir(exist_ok=True)
(doc_cache_dir / 'doc').mkdir(exist_ok=True)
(doc_cache_dir / 'wpf').mkdir(exist_ok=True)
(doc_cache_dir / '404').mkdir(exist_ok=True)
(doc_cache_dir / 'tmt').mkdir(exist_ok=True) # too many tries
(doc_cache_dir / 'exc').mkdir(exist_ok=True) # exception

filelist = list(os.listdir(fl_cache_dir))

RETRIES = 5
WORKERS = 4

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

async def get_doc():
    while 1:
        task_list_arg = await task_list.get()
        if task_list_arg is None:
            return
        symbol, l, save_filename = task_list_arg
        url = f'https://documents.un.org/api/symbol/access?s={symbol}&l={l}&t=doc'
        save_pdf = doc_cache_dir / 'pdf' / f"{save_filename}.pdf"
        save_doc = doc_cache_dir / 'doc' / f"{save_filename}.doc"
        save_wpf = doc_cache_dir / 'wpf' / f"{save_filename}.wpf"
        save_404 = doc_cache_dir / '404' / f"{save_filename}"
        save_tmt = doc_cache_dir / 'tmt' / f"{save_filename}"
        save_exc = doc_cache_dir / 'exc' / f"{save_filename}"
        should_skip = False
        for sp in (
            save_pdf,
            save_doc,
            save_wpf,
            save_404,
            save_tmt,
            save_exc,
        ):
            if sp.exists():
                print("skip", save_filename, "as", sp, "exists.")
                should_skip = True
                break
        if should_skip:
            continue
        if '^' in symbol or r'%5E' in symbol:
            print(f"skip {save_filename}: invalid ^ in symbol {symbol}")
            continue
        for retry in range(RETRIES):
            try:
                async with aiohttp.ClientSession() as session:
                    resp = await session.get(url, headers={
                        "accept-encoding":"gzip, deflate, br", # br压缩要额外装brotli这个库才能有requests支持
                        "user-agent":"Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36"
                    }, timeout=120)
                    if resp.status == 200:
                        bin_content = await resp.content.read()
                        url_suffix_lower = resp.url.suffix.lower()
                        typ = magic.from_buffer(bin_content, mime=True)
                        if typ == 'application/pdf' or url_suffix_lower == '.pdf':
                            save_dir = save_pdf
                        elif typ in (
                            'application/msword',
                            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                        ) or url_suffix_lower in ('.doc', '.docx'):
                            save_dir = save_doc
                        elif typ in (
                            "application/vnd.wordperfect",
                        ) or url_suffix_lower == '.wpf' :
                            save_dir = save_wpf
                        else:
                            print(f'!!!!!unknown type: {typ} {url}!!!!!')
                            with open(const.WORK_DIR / resp.url.name, "wb") as f:
                                f.write(bin_content)
                            exit(1)
                        with open(save_dir, 'wb') as f:
                            f.write(bin_content)
                        print('download done:', save_dir)
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
                        with open(save_404, "wb") as f:
                            f.write(symbol.encode('utf-8'))
                        break
                    else:
                        if retry == RETRIES - 1:
                            print(resp)
                            print(resp.headers)
                            print(await resp.text())
                            print(f'!!!!!ERROR {url} {save_filename}!!!!!')
                            with open(save_tmt, "wb") as f:
                                f.write(b"[HEADER]\n" + str(dict(resp.headers)).encode('utf-8') + b"\n\n[BODY]\n" + (await resp.content.read()))
                            break
            except Exception as e:
                print(e)
                print('retry:', retry)
                if retry == RETRIES - 1:
                    print(f'!!!!!Exception {url} {save_filename}!!!!!')
                    with open(save_exc, "wb") as f:
                        f.write(traceback.format_exc().encode('utf-8'))
                    break

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
                        await task_list.put((symbol, l, f"{i.removesuffix('.json')}-{idx}={lang}"))
    for i in range(WORKERS):
        task_list.put(None)
    workers = [
        get_doc() for _ in range(WORKERS)
    ]
    await asyncio.gather(*workers)
if __name__ == "__main__":
    asyncio.run(main())
