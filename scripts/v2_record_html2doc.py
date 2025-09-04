import re
import asyncio
import datetime

from pathlib import Path

from new_sample_get_doc_async_candidate import get_doc, doc_cache_dir, task_list, WORKERS

symbol_pattern = re.compile(r"<div class='metadata-row'><span class='title'>Symbol</span><span class='value'>(.*?)</span></div>")

WD = Path(__file__).parent
# 存储客户端提交结果的目录
INPUT_DIR = WD / "recorddmp_html"

LANGMAP = {
    'ar': 'A',
    'zh': 'C',
    'en': 'E',
    'fr': 'F',
    'ru': 'R',
    'es': 'S',
    'ot': 'O',
}

async def periodly_scan_html_dir():
    while 1:
        print("SCANDIR AT",datetime.datetime.now())
        for i in INPUT_DIR.glob("*"):
            if not i.name.isdigit():
                continue
            with i.open("r", encoding="utf-8") as f:
                s = symbol_pattern.search(f.read())
                if not s:
                    continue
                symbol = s.groups()[0]
                record_idx = i.name

                for lang, l in LANGMAP.items():
                    l = LANGMAP[lang]
                    save_filename_pdf = doc_cache_dir / 'pdf' / f"{record_idx}={lang}.pdf"
                    save_filename_doc = doc_cache_dir / 'doc' / f"{record_idx}={lang}.doc"
                    save_filename_err = doc_cache_dir / 'err' / f"{record_idx}={lang}.err"
                    save_filename_wpf = doc_cache_dir / 'wpf' / f"{record_idx}={lang}.wpf"
                    if save_filename_pdf.exists() or save_filename_doc.exists() or save_filename_wpf.exists() or save_filename_err.exists():
                        print('skip:', save_filename_pdf)
                        continue
                    print(f"put {record_idx} {symbol} {l}")
                    await task_list.put((symbol, l, save_filename_pdf, save_filename_doc, save_filename_wpf, save_filename_err))
        await asyncio.sleep(60)

async def main():
    workers = [
        get_doc() for _ in range(WORKERS)
    ] + [periodly_scan_html_dir()]
    await asyncio.gather(*workers)

if __name__ == "__main__":
    asyncio.run(main())