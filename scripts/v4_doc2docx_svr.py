import asyncio
import itertools
import time
import re
from pathlib import Path

from fastapi.responses import FileResponse
import uvicorn
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
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
        dest_fp = const.CONVERT_DOCX_CACHE_DIR / FILENAME_REPLACE_PATTERN.sub('.docx', task_id)
        if dest_fp.exists():
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


@app.get("/t", summary="获取一个待处理的任务文件")
async def get_task():
    """
    为客户端分配一个文件转换任务。采用高效的生成器模式。
    """
    global task_generator

    # 如果生成器不存在（首次运行），则创建它
    if task_generator is None:
        task_generator = create_task_generator()

    # --- 第一轮尝试：从当前生成器获取任务 ---
    for task_id, task_path in task_generator:
        # 此时的task_id已经经过生成器的筛选，是有效的
        tasks_in_progress[task_id] = time.time()
        logger.info(f"Assigning task from initial pass: {task_id}")
        return FileResponse(
            path=task_path,
            media_type='application/octet-stream',
            filename=task_id
        )

    # --- 如果代码运行到这里，说明上面的 for 循环正常结束，生成器已耗尽 ---
    logger.info("Task generator exhausted. Checking for timed-out tasks...")
    check_timeouts()

    # --- 第二轮尝试：创建新生成器，查找刚被释放的超时任务 ---
    task_generator = create_task_generator()  # 重置生成器
    for task_id, task_path in task_generator:
        # 分配找到的第一个可用任务
        tasks_in_progress[task_id] = time.time()
        logger.info(f"Assigning re-queued task after timeout check: {task_id}")
        return FileResponse(
            path=task_path,
            media_type='application/octet-stream',
            filename=task_id
        )
        
    # --- 如果第二轮尝试仍然没有任务 ---
    logger.warning("No tasks available after re-scan. Instructing client to shutdown.")
    raise HTTPException(status_code=404, detail="No tasks available. You can shut down.")

@app.post("/s", summary="提交一个已完成的任务")
async def submit_task(task_id: str = Form(...), file: UploadFile = File(...)):
    """
    客户端提交一个任务的结果。它会上传转换后的 .docx 文件。
    """
    if not file.filename.endswith('.docx'):
        raise HTTPException(status_code=400, detail="Invalid file type. Only .docx files are accepted.")

    dest_filename = FILENAME_REPLACE_PATTERN.sub('.docx', task_id)
    dest_path = const.CONVERT_DOCX_CACHE_DIR / dest_filename

    try:
        contents = await file.read()
        with open(dest_path, 'wb') as f:
            f.write(contents)

        if tasks_in_progress.pop(task_id, None) is not None:
             logger.info(f"Task completed and submitted: {task_id}")
        else:
             logger.warning(f"Submitted task '{task_id}' was not in progress list (might have timed out).")

        return {"status": "success", "message": f"Task {task_id} submitted successfully.", "saved_to": str(dest_path)}

    except Exception as e:
        logger.error(f"Error saving submitted task {task_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to save the submitted file.")
    finally:
        await file.close()



if __name__ == "__main__":
    # 推荐使用命令行运行: uvicorn server:app --host 0.0.0.0 --port 8000
    uvicorn.run(app, host="0.0.0.0", port=48482)