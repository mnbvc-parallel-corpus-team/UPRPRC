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
                    print(f"put {record_idx} {symbol} {l}")
                    await task_list.put((f"s={symbol}&l={l}", f"{record_idx}={lang}"))
        await asyncio.sleep(60)

async def main():
    workers = [
        get_doc() for _ in range(WORKERS)
    ] + [periodly_scan_html_dir()]
    await asyncio.gather(*workers)

if __name__ == "__main__":
    asyncio.run(main())