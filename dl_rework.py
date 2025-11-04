import datasets
import json
from pathlib import Path
wd = Path(__file__).parent

ds = datasets.load_from_disk(wd / "DS_rework")["train"]

# 12567 ru 2110519 254 19549265 S_PRST_2014_3
mx = 0

valid_pairs = 0

# with open(wd / "rework_largest_para.txt", "w", encoding="utf-8") as f:
def mapfunc(i, idx):
    global mx
    global valid_pairs
    m = 2
    for lang in ['en','ar','es','fr','ru','zh','de']:
        l = len(i[lang])
        if l > 0:
            m -= 1
            if m <= 0:
                valid_pairs += 1
                return
        # p = i[lang].count('\n\n')
        # t = len(i[lang].strip().split())
        
        # if p > mx:
        #     print(idx, lang, t, p, l, i['record'])
        #     mx = p
        #     f.write(f"{idx} {lang} {t} {p} {l} {i['record']}\n")
ds.map(mapfunc, with_indices=True)
# for i in ds:

print(valid_pairs)


# ds = datasets.load_dataset("bot-yaya/rework_undl_text")

# ds.save_to_disk(wd / "DS_rework")
