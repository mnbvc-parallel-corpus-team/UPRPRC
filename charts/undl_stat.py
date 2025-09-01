import datasets
import json
import os
from pathlib import Path
from urllib.parse import quote, unquote
from collections import Counter
import datetime
import jieba
from dateutil import parser

t = datasets.load_dataset("bot-yaya/rework_undl_text", split="train")#.select(range(200))
SCRIPT_WORKDIR = Path(__file__).parent
SYMBOLKEY = 'UNDL_WD_SYMBOL'
IDKEY = 'UNDL_WD_ID'
DSSBKEY = 'UNDL_WD_DOCSEARCH_SYMBOL'
DSSBDIR = SCRIPT_WORKDIR / DSSBKEY
SYMBOLDIR = SCRIPT_WORKDIR / SYMBOLKEY
IDDIR = SCRIPT_WORKDIR / IDKEY
SYMBOLDIR.mkdir(exist_ok=True)
IDDIR.mkdir(exist_ok=True)

LANG_ORDER = ["ar","zh","en","fr","ru","es","de"]

# INDEXFILE = SCRIPT_WORKDIR / "indexfile.txt"


# doneset = {}
# with INDEXFILE.open("r", encoding="utf-8") as f:
#     for line in f:
#         j = json.loads(line.strip())
#         doneset[j['rec']] = j['firstmatch']
    # if j['rec'].replace('_','/') != j['firstmatch']:
        # print("W!",j['rec'],j['firstmatch'])

# 2000-01-01 2023-8-5
year_ctr = Counter()
begintime = datetime.datetime.now()

每种语言的有效文件数_总数 = Counter()
每种语言的有效文件数_按年 = Counter()

每种语言同一个文号中缺失的文件数_按年 = Counter()
每种语言同一个文号中缺失的文件数_总数 = Counter()

每种语言的字符数_按年 = Counter()
每种语言的字符数_总数 = Counter()

每种语言的段落数_按年 = Counter()
每种语言的段落数_总数 = Counter()

每种语言的词汇量_按年 = {}
每种语言的词汇量_总数 = {}

每种语言的词汇_按年 = {}
每种语言的词汇_总数 = {}

每种文号的前缀统计_按年 = {}
每种文号的前缀统计_总数 = Counter()

accctr = 0

for idx, row in enumerate(t):
    if idx & 4095 == 0:
        print(datetime.datetime.now(), idx, len(t), json.dumps(每种语言的有效文件数_总数, indent=4, sort_keys=True))
    rec = row['record']
    recrp = rec.replace('_','/')
    erecrp = quote(recrp,safe='')
    pa: Path = (SYMBOLDIR / erecrp)
    p2 = DSSBDIR / erecrp
    

    acc = False
    if pa.exists():
        with pa.open("r", encoding="utf-8") as f:
            j = json.load(f)
        da = j['Publication Date']
        dt = datetime.datetime.strptime(da, "%d %b, %Y")
        # lc = j['languageCode']
        acc = True
    elif p2.exists():
        with p2.open("r", encoding="utf-8") as f:
            j = json.load(f)
        da = j['publication_date']
        dt = parser.isoparse(da)
        # dt = datetime.datetime.strptime(da, "%d %b, %Y")
        # jn = j['job_numbers']
        # lc = []
        # for lang, jnb in zip(LANG_ORDER, jn):
        #     if jnb:
        #         lc.append(lang)
        acc = True
    if not acc:
        continue
    dt_year = dt.year
    recrp_splited = recrp.split('/')
    for spcnt in range(len(recrp_splited)):
        spkey = '/'.join(recrp_splited[:spcnt+1])
        每种文号的前缀统计_按年.setdefault(dt_year, Counter())[spkey] += 1
        每种文号的前缀统计_总数[spkey] += 1
    for langdefined in LANG_ORDER:
        r = row[langdefined]
        if r:
            词汇 = r.split() if langdefined != 'zh' else jieba.lcut(r)
            段落数 = r.count('\n\n') + 1
            每种语言的有效文件数_按年.setdefault(dt_year, Counter())[langdefined] += 1
            每种语言的字符数_按年.setdefault(dt_year, Counter())[langdefined] += len(r)
            每种语言的词汇_按年.setdefault(dt_year, {}).setdefault(langdefined, Counter()).update(词汇)
            每种语言的段落数_按年.setdefault(dt_year, Counter())[langdefined] += 段落数
            
            每种语言的有效文件数_总数[langdefined] += 1
            每种语言的字符数_总数[langdefined] += len(r)
            每种语言的段落数_总数[langdefined] += 段落数
            每种语言的词汇_总数.setdefault(langdefined, Counter()).update(词汇)
        else:
            每种语言同一个文号中缺失的文件数_按年.setdefault(dt_year, Counter())[langdefined] += 1
            每种语言同一个文号中缺失的文件数_总数[langdefined] += 1
    # elif fm := doneset.get(rec):
    #     p3 = SYMBOLDIR / quote(fm, safe='')
    #     with p3.open("r", encoding="utf-8") as f:
    #         j = json.load(f)
    #     da = j['Publication Date']
    #     dt = datetime.datetime.strptime(da, "%d %b, %Y")
    #     lc = j['languageCode']
    #     for langdefined in LANG_ORDER:
    #         if row[langdefined]:
    #             每种语言的有效文件数_按年.setdefault(dt.year, Counter())[langdefined] += 1
    # else:
    #     raise FileNotFoundError(f"No such symbol: {recrp}")

    year_ctr[dt.year] += 1
    accctr += 1

for y, ld in 每种语言的词汇_按年.items():
    c = Counter()
    for l in ld.keys():
        c[l] = len(ld[l])
    每种语言的词汇量_按年[y] = c
for l in 每种语言的词汇_总数.keys():
    每种语言的词汇量_总数[l] = len(每种语言的词汇_总数[l])

endtime = datetime.datetime.now()
print(f"TIME ELAPSED: {endtime - begintime}")

with open(SCRIPT_WORKDIR / "每种语言的词汇_按年.txt", "w", encoding='utf-8') as f:
    json.dump(每种语言的词汇_按年,f,sort_keys=True, ensure_ascii=False)
with open(SCRIPT_WORKDIR / "每种语言的词汇_总数.txt", "w", encoding='utf-8') as f:
    json.dump(每种语言的词汇_总数,f,sort_keys=True, ensure_ascii=False)

with open(SCRIPT_WORKDIR / "stat.txt", "w", encoding='utf-8') as f:
    f.write(f"已收录语料的文件号总数量:{accctr}\n")
    f.write(f"每个年份的文件号数量(每个文号只算一次，不关心它有多少种语言):{json.dumps(year_ctr, sort_keys=True, ensure_ascii=False)}\n")
    f.write(f"已收录的语料中每种语言的文件数量:{json.dumps(每种语言的有效文件数_总数, sort_keys=True, ensure_ascii=False)}\n")
    f.write(f"已收录的语料中每个年份、每种语言的数量:{json.dumps(每种语言的有效文件数_按年,sort_keys=True, ensure_ascii=False)}\n")
    f.write(f"每种语言的段落数_按年:{json.dumps(每种语言的段落数_按年,sort_keys=True, ensure_ascii=False)}\n")
    f.write(f"每种语言的段落数_总数:{json.dumps(每种语言的段落数_总数,sort_keys=True, ensure_ascii=False)}\n")
    f.write(f"每种语言的字符数_按年:{json.dumps(每种语言的字符数_按年,sort_keys=True, ensure_ascii=False)}\n")
    f.write(f"每种语言的字符数_总数:{json.dumps(每种语言的字符数_总数,sort_keys=True, ensure_ascii=False)}\n")
    f.write(f"每种语言的词汇量_按年:{json.dumps(每种语言的词汇量_按年,sort_keys=True, ensure_ascii=False)}\n")
    f.write(f"每种语言的词汇量_总数:{json.dumps(每种语言的词汇量_总数,sort_keys=True, ensure_ascii=False)}\n")
    f.write(f"每种语言同一个文号中缺失的文件数_按年:{json.dumps(每种语言同一个文号中缺失的文件数_按年,sort_keys=True, ensure_ascii=False)}\n")
    f.write(f"每种语言同一个文号中缺失的文件数_总数:{json.dumps(每种语言同一个文号中缺失的文件数_总数,sort_keys=True, ensure_ascii=False)}\n")
    f.write(f"每种文号的前缀统计_按年:{json.dumps(每种文号的前缀统计_按年,sort_keys=True, ensure_ascii=False)}\n")
    f.write(f"每种文号的前缀统计_总数:{json.dumps(每种文号的前缀统计_总数,sort_keys=True, ensure_ascii=False)}\n")