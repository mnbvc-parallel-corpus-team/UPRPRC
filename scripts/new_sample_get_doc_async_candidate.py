import os
import json
import asyncio

import aiohttp
import magic

import const

fl_cache_dir = const.DOWNLOAD_FILELIST_CACHE_DIR
fl_cache_dir.mkdir(exist_ok=True)
doc_cache_dir = const.DOWNLOAD_DOC_CACHE_DIR
doc_cache_dir.mkdir(exist_ok=True)
(doc_cache_dir / 'pdf').mkdir(exist_ok=True)
(doc_cache_dir / 'doc').mkdir(exist_ok=True)
(doc_cache_dir / 'err').mkdir(exist_ok=True)
(doc_cache_dir / 'wpf').mkdir(exist_ok=True)

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

task_list = asyncio.Queue(maxsize=WORKERS+1)

async def get_doc():
    while 1:
        task_list_arg = await task_list.get()
        if task_list_arg is None:
            return
        symbol, l, save_filename_pdf, save_filename_doc, save_filename_wpf, save_filename_err = task_list_arg
        url = f'https://documents.un.org/api/symbol/access?s={symbol}&l={l}&t=doc'
        for retry in range(RETRIES):
            try:
                async with aiohttp.ClientSession() as session:
                    resp = await session.get(url, headers={
                        "accept-encoding":"gzip, deflate, br", # br压缩要额外装brotli这个库才能有requests支持
                        "user-agent":"Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36"
                    }, timeout=120)
                    if resp.status == 200:
                        bin_content = await resp.content.read()
                        typ = magic.from_buffer(bin_content, mime=True)
                        if typ == 'application/pdf':
                            save_dir = save_filename_pdf
                        elif typ in (
                            'application/msword',
                            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                        ):
                            save_dir = save_filename_doc
                        elif typ in (
                            "application/vnd.wordperfect",
                        ):
                            save_dir = save_filename_wpf
                        else:
                            print(f'!!!!!unknown type: {typ}!!!!!')
                            with open(doc_cache_dir / f'unknowndoc{typ}.bin', "wb") as f:
                                f.write(bin_content)
                            exit(1)
                        with open(save_dir, 'wb') as f:
                            f.write(bin_content)
                        print('download done:', save_dir)
                        break
                    elif resp.status == 404:
                        # print(resp)
                        # print(resp.headers)
                        # print(await resp.text())
                        print(f'!!!!!404 NOT FOUND {url} {save_filename_err}!!!!!')
                        with open(save_filename_err, "wb") as f:
                            f.write(b"HTTP 404:" + symbol.encode('utf-8'))
                        break
                    else:
                        if retry == RETRIES - 1:
                            print(resp)
                            print(resp.headers)
                            print(await resp.text())
                            print(f'!!!!!ERROR {url} {save_filename_doc}!!!!!')
                            break
            except Exception as e:
                print(e)
                print('retry:', retry)
                if retry == RETRIES - 1:
                    print(f'!!!!!Exception {url} {save_filename_doc}!!!!!')
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
                        save_filename_pdf = doc_cache_dir / 'pdf' / f"{i.removesuffix('.json')}-{idx}={lang}.pdf"
                        save_filename_doc = doc_cache_dir / 'doc' / f"{i.removesuffix('.json')}-{idx}={lang}.doc"
                        save_filename_err = doc_cache_dir / 'err' / f"{i.removesuffix('.json')}-{idx}={lang}.err"
                        save_filename_wpf = doc_cache_dir / 'wpf' / f"{i.removesuffix('.json')}-{idx}={lang}.wpf"
                        if save_filename_pdf.exists() or save_filename_doc.exists() or save_filename_err.exists() or save_filename_wpf.exists():
                            print('skip:', save_filename_pdf)
                            continue
                        await task_list.put((symbol, l, save_filename_pdf, save_filename_doc, save_filename_wpf, save_filename_err))
    for i in range(WORKERS):
        task_list.put(None)
    workers = [
        get_doc() for _ in range(WORKERS)
    ]
    await asyncio.gather(*workers)
if __name__ == "__main__":
    asyncio.run(main())
