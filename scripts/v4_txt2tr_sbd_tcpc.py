import os
os.environ["ARGOS_DEVICE_TYPE"] = "cuda"
import asyncio
import traceback
import time
import gc
from datetime import datetime

from loguru import logger

from v4_helpers import API_HOST, API_PORT, TARGET_LANG, build_stanza, encode_sentences, get_or_install_package, rpc, sbd_with_stanza, unload_unused_cache
async def tcp_main():
    logger.info(f"[sbdclient] API={API_HOST}:{API_PORT}")
    while True:
        # 取任务
        try:
            task = await rpc("s", {"v": 1})
            print(f"task:{task}")
        except Exception as e:
            logger.error(f"[client] fetch error: {traceback.format_exc()} SLEEP 5s")
            time.sleep(5); continue
        task_o = task.get("o", -1)
        if task_o != 0:
            logger.warning(f"task o == {task_o}, SLEEP 5s")
            time.sleep(5); continue

        src = task["s"]; txt = task["p"]; pk = task["k"]

        logger.info(f"{datetime.now()} sbd recv: {src} ")

        # 包 + 引擎 + SBD
        pkg = get_or_install_package(src, TARGET_LANG)
        pipe = build_stanza(src, str(pkg.package_path / "stanza"), use_gpu=True)

        # 对于内存不足的机器，需要把用不到的模型卸载
        if os.environ.get("MSAVE", ""):
            unload_unused_cache(src, TARGET_LANG)

        t0 = datetime.now()
        try:
            outs = sbd_with_stanza(
                pipe, txt
            )
        except Exception as e:
            print("[client] translate error:", e)
            time.sleep(1); continue
        t1 = datetime.now()
        secs = (t1 - t0).total_seconds()
        logger.info(f"[client] {t1} batch {len(txt)} chars {len(outs)} sentences {secs:.3f}s  ~{len(txt)/max(1e-12,secs):.4f}c/s")
        
        try:
            resp = await rpc("b", {"s": src, "p": [(pk, outs)]})
            logger.info(f"submit done. resp: {resp}")
        except Exception as e:
            logger.error(f"[client] upload error: {e}")
        gc.collect()
if __name__ == "__main__":
    asyncio.run(tcp_main())
