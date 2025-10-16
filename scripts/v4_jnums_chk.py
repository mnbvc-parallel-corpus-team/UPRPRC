import json

from v4_tr_recover import _iter_pkl
import const

if __name__ == "__main__":
    dt = {
        "id","symbol","job_numbers","sizes"
    }
    for row in _iter_pkl():
        s = set()
        for jn in row["job_numbers"]:
            if jn != "":
                if jn in s:
                    with open(const.WORK_DIR / "v4_jnums_chk.log", "a", encoding="utf-8") as f:
                        f.write(json.dumps({k: row[k] for k in dt}, ensure_ascii=False)+'\n')
                    print(row["id"], row["symbol"], row["job_numbers"], row["sizes"])
                s.add(jn)