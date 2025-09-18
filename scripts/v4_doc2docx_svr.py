import asyncio
import itertools
import time
import re
from pathlib import Path

import zstandard
from fastapi.responses import FileResponse
import uvicorn
from fastapi import FastAPI, Response, UploadFile, File, Form, HTTPException
from loguru import logger

import const

# --- 配置常量 ---
TASK_TIMEOUT_SECONDS = 600
# 服务器日志
SERVER_LOG_FILE = __file__.replace(".py",".log")

FILENAME_REPLACE_PATTERN = re.compile(r'\.\w+$')

# --- 全局状态变量 ---
# 正在处理的任务: {task_id: assignment_timestamp}
tasks_in_progress = {}

# 任务生成器，用于高效遍历文件，避免重复扫描
task_generator = None

# 配置日志
logger.add(SERVER_LOG_FILE, rotation="10 MB", retention="7 days")

# 创建FastAPI应用
app = FastAPI(title="v4_doc2docx", docs_url=None, redoc_url=None)
zstd_compressor = zstandard.ZstdCompressor()
zstd_decompressor = zstandard.ZstdDecompressor()

def create_task_generator():
    """
    创建一个生成器，用于按需、高效地遍历所有可能的任务文件。
    它会 yield 一个有效的、可以被分配的任务。
    """
    logger.info("Creating a new task generator. Scanning directories...")
    # 按照指定顺序遍历三个目录
    # 使用 .iterdir() 配合生成器表达式，比 .glob('*') 内存效率更高
    source_iterator = itertools.chain(
        (const.DOWNLOAD_DOC_CACHE_DIR / "doc").iterdir(),
        (const.DOWNLOAD_DOC_CACHE_DIR / "wpf").iterdir(),
        (const.DOWNLOAD_DOC_CACHE_DIR / "wpd").iterdir()
    )

    for fn in source_iterator:
        if not fn.is_file():
            continue

        task_id = fn.name  # 任务ID是文件名

        # 检查任务是否已经完成 (对应的.docx文件已存在)
        dest_fp = const.CONVERT_DOCX_CACHE_DIR / 'docx' / FILENAME_REPLACE_PATTERN.sub('.docx', task_id)
        if dest_fp.exists():
            continue
        err_fp = const.CONVERT_DOCX_CACHE_DIR / 'err' / FILENAME_REPLACE_PATTERN.sub('', task_id)
        if err_fp.exists():
            continue

        # 检查任务是否正在被处理
        if task_id in tasks_in_progress:
            continue

        # 如果任务未完成且未被处理，则将这个有效的任务yield出去
        yield task_id, fn

def check_timeouts():
    """(同步) 检查并处理超时的任务，将它们从 'in_progress' 状态中移除。"""
    now = time.time()
    timed_out_tasks = []
    # 查找超时的任务
    for task_id, assigned_time in list(tasks_in_progress.items()):
        if now - assigned_time > TASK_TIMEOUT_SECONDS:
            timed_out_tasks.append(task_id)

    # 将超时的任务重新放回待办列表（通过从 in_progress 中删除）
    if timed_out_tasks:
        for task_id in timed_out_tasks:
            tasks_in_progress.pop(task_id, None)
        logger.warning(f"Re-queued {len(timed_out_tasks)} timed-out tasks: {timed_out_tasks}")

def find_task():
    global task_generator

    if task_generator is None:
        task_generator = create_task_generator()

    for task_id, task_path in task_generator:
        tasks_in_progress[task_id] = time.time()
        logger.info(f"A {task_id}")
        return task_id, task_path

    logger.info("Task generator exhausted. Checking for timed-out tasks...")
    check_timeouts()

    task_generator = create_task_generator()
    for task_id, task_path in task_generator:
        tasks_in_progress[task_id] = time.time()
        logger.info(f"B {task_id}")
        return task_id, task_path

@app.get("/z")
async def get_zipped_task():
    t = find_task()
    if not t:
        logger.warning("No tasks available after re-scan. Instructing client to shutdown.")
        raise HTTPException(status_code=404)

    with open(t[1], 'rb') as f:
        original_data = f.read()
        compressed_data = zstd_compressor.compress(original_data)
    
    return Response(content=compressed_data, headers = {
        'T': t[0],
    })

@app.get("/t")
async def get_task():
    t = find_task()
    if not t:
        logger.warning("No tasks available after re-scan. Instructing client to shutdown.")
        raise HTTPException(status_code=404)
    return FileResponse(path=t[1],headers = {
        'T': t[0],
    })

def check_is_req_malice(t: str) -> bool:
    if not (t.endswith("doc") and (const.DOWNLOAD_DOC_CACHE_DIR / "doc" / t).exists()) and \
        not (t.endswith("wpd") and (const.DOWNLOAD_DOC_CACHE_DIR / "wpd" / t).exists()) and\
        not (t.endswith("wpf") and (const.DOWNLOAD_DOC_CACHE_DIR / "wpf" / t).exists()):
        logger.critical(f"MALICE TASKID: {t}")
        return True
    return False

@app.get("/e")
async def submit_err(t: str = None):
    if check_is_req_malice(t):
        return 1
    with (const.CONVERT_DOCX_CACHE_DIR / 'err' / FILENAME_REPLACE_PATTERN.sub("", t)).open("wb") as _: pass
    logger.warning(f"ERR {t} {tasks_in_progress.pop(t, None)}")
    return 1

@app.post("/r")
async def submit_zipped_task(file: UploadFile = File(...)):
    task_id = file.filename
    if check_is_req_malice(task_id):
        return 1
    dest_path = const.CONVERT_DOCX_CACHE_DIR / 'docx' / FILENAME_REPLACE_PATTERN.sub(".docx", task_id)

    try:
        contents = zstd_decompressor.decompress(await file.read())
        with open(dest_path, 'wb') as f:
            f.write(contents)

        if tasks_in_progress.pop(task_id, None) is not None:
             logger.info(f"Task completed and submitted: {task_id}")
        else:
             logger.warning(f"Submitted task '{task_id}' was not in progress list (might have timed out).")

        return 1

    except Exception as e:
        logger.error(f"Error saving submitted task {task_id}: {e}")
        raise HTTPException(status_code=500)
    finally:
        await file.close()

@app.post("/s")
async def submit_task(file: UploadFile = File(...)):
    task_id = file.filename 
    if check_is_req_malice(task_id):
        return 1
    dest_path = const.CONVERT_DOCX_CACHE_DIR / 'docx' / FILENAME_REPLACE_PATTERN.sub(".docx", task_id)
    try:
        contents = await file.read()
        with open(dest_path, 'wb') as f:
            f.write(contents)

        if tasks_in_progress.pop(task_id, None) is not None:
             logger.info(f"Task completed and submitted: {task_id}")
        else:
             logger.warning(f"Submitted task '{task_id}' was not in progress list (might have timed out).")

        return 1

    except Exception as e:
        logger.error(f"Error saving submitted task {task_id}: {e}")
        raise HTTPException(status_code=500)
    finally:
        await file.close()



if __name__ == "__main__":
    # 推荐使用命令行运行: uvicorn server:app --host 0.0.0.0 --port 8000
    uvicorn.run(app, host="0.0.0.0", port=48482)