import os
import json
import asyncio
import re

import aiohttp

import const

from loguru import logger

const.RECORD_DUMP_DIR.mkdir(exist_ok=True)

res_not_ex_str = b"Requested record does not seem to exist."

errlog = const.RECORD_DUMP_ERR_LOG.open("a", encoding="utf-8")
logger.add(errlog)

RETRIES = 5
WORKER_NUM = 1
TASK_QUEUE_SIZE = 512
SLEEP202 = 180

task_list = asyncio.Queue(maxsize=TASK_QUEUE_SIZE)



async def get_doc():
    while 1:
        i = await task_list.get()
        if i is None: return
        url = f'https://digitallibrary.un.org/record/{i}'
        for retry in range(RETRIES):
            try:
                async with aiohttp.ClientSession() as session:
                    resp = await session.get(url, headers={
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                        'Accept-Encoding': 'gzip, deflate, br, zstd',
                        'Accept-Language': 'en-CN,en;q=0.9,zh-CN;q=0.8,zh;q=0.7,en-GB;q=0.6,en-US;q=0.5',
                        'Cache-Control': 'no-cache',
                        'Connection': 'keep-alive',
                        'DNT': '1',
                        'Host': 'digitallibrary.un.org',
                        'Pragma': 'no-cache',
                        'Sec-Fetch-Dest': 'document',
                        'Sec-Fetch-Mode': 'navigate',
                        'Sec-Fetch-Site': 'none',
                        'Sec-Fetch-User': '?1',
                        'Upgrade-Insecure-Requests': '1',
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
                        'sec-ch-ua': '"Not;A=Brand";v="99", "Google Chrome";v="139", "Chromium";v="139"',
                        'sec-ch-ua-mobile': '?0',
                        'sec-ch-ua-platform': '"Windows"',
                    }, timeout=120)
                    if resp.status == 200:
                        bin_content = await resp.content.read()
                        if res_not_ex_str in bin_content:
                            with open(const.RECORD_DUMP_DIR / ("X" + str(i)), 'wb') as f:
                                f.write(bin_content)
                            logger.warning(f"resource not exists: {i}")
                        else:
                            with open(const.RECORD_DUMP_DIR / str(i), 'wb') as f:
                                f.write(bin_content)
                            logger.info(f'download done: {i}')
                        break
                    elif resp.status == 202:
                        logger.warning(f"Detect 202 at {i}, sleep, retry: {retry}")
                        await asyncio.sleep(SLEEP202)
                        continue
                    elif resp.status == 404:
                        logger.error(f"404 NOT FOUND {i}")
                        with open(const.RECORD_DUMP_DIR / ("N" + str(i)), 'wb') as f:
                            pass
                        break
                    else:
                        if retry == RETRIES - 1:
                            logger.error(f"ERR FETCH {i}, {resp.status} {resp.headers} {await resp.text()} SKIP")
                            with open(const.RECORD_DUMP_DIR / ("E" + str(i)), 'wb') as f:
                                f.write(f"[HTTP_STATUS]\n{resp.status}\n\n[HEADERS]\n{resp.headers}\n\n[CONTENT]\n{await resp.content.read()}".encode("utf-8"))
                            break
            except Exception as e:
                logger.warning(f"EXCEPTION {e} AT {i}, RETRY: {retry}")
                if retry == RETRIES - 1:
                    logger.error(f"TOO MANY EXCEPTION {e} AT {i} SKIP")
                    with open(const.RECORD_DUMP_DIR / ("R" + str(i)), 'wb') as f:
                        f.write(f"[EXCEPTION]\n{e.with_traceback()}".encode("utf-8"))
                    break

async def enumerate_record():
    for i in range(1, 4100000):
        if (const.RECORD_DUMP_DIR / str(i)).exists():
            continue
        if (const.RECORD_DUMP_DIR / ("X" + str(i))).exists():
            continue
        if (const.RECORD_DUMP_DIR / ("R" + str(i))).exists():
            continue
        if (const.RECORD_DUMP_DIR / ("E" + str(i))).exists():
            continue
        if (const.RECORD_DUMP_DIR / ("N" + str(i))).exists():
            continue
        await task_list.put(i)
        # if task_list.qsize() >= TASK_QUEUE_SIZE:
        #     await asyncio.sleep(0)
    for i in range(WORKER_NUM):
        task_list.put(None)

async def main():
    workers = [
        get_doc() for _ in range(WORKER_NUM)
    ] + [enumerate_record()]
    await asyncio.gather(*workers)

asyncio.run(main())
