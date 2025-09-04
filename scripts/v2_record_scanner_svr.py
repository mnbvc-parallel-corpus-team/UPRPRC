import asyncio
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from loguru import logger

# --- 配置常量 ---
# 任务ID的范围
WD = Path(__file__).parent
TOTAL_TASKS_RANGE = range(100_000, 4_100_000)
# 任务超时时间（秒），如果一个任务被客户端领取后超过这个时间未提交，则重新放回任务池
TASK_TIMEOUT_SECONDS = 600
# 存储客户端提交结果的目录
STORAGE_DIR = WD / "recorddmp_html"
# 服务器日志
SERVER_LOG_FILE = __file__.replace(".py",".log")

# --- 全局状态变量 ---
# 待处理的任务集合
tasks_todo = set()
# 正在处理的任务: {task_id: assignment_timestamp}
tasks_in_progress = {}
# 已完成的任务集合
tasks_done = set()
# 用于保护对上述集合访问的异步锁
lock = asyncio.Lock()

# 配置日志
logger.add(SERVER_LOG_FILE, rotation="10 MB", retention="7 days")

# 创建FastAPI应用
app = FastAPI(title="Distributed Task Server")


@app.on_event("startup")
async def startup_event():
    """服务器启动时执行的初始化操作"""
    STORAGE_DIR.mkdir(exist_ok=True)
    logger.info("Initializing task sets...")

    # 扫描已存在的结果，以恢复状态
    for f in STORAGE_DIR.iterdir():
        # 从文件名（如 "123", "X123", "N123"）中解析出任务ID
        task_id_str = ''.join(filter(str.isdigit, f.name))
        if task_id_str:
            tasks_done.add(int(task_id_str))
    
    logger.info(f"Found {len(tasks_done)} completed tasks from storage.")

    # 初始化待办任务列表
    initial_todo = set(TOTAL_TASKS_RANGE)
    global tasks_todo
    tasks_todo = initial_todo - tasks_done

    logger.info(f"Server started. {len(tasks_todo)} tasks to do.")
    logger.info(f"Task timeout is set to {TASK_TIMEOUT_SECONDS} seconds.")


async def check_timeouts():
    """检查并处理超时的任务"""
    now = time.time()
    timed_out_tasks = []
    # 查找超时的任务
    for task_id, assigned_time in tasks_in_progress.items():
        if now - assigned_time > TASK_TIMEOUT_SECONDS:
            timed_out_tasks.append(task_id)

    # 将超时的任务重新放回待办列表
    if timed_out_tasks:
        for task_id in timed_out_tasks:
            del tasks_in_progress[task_id]
            tasks_todo.add(task_id)
        logger.warning(f"Re-queued {len(timed_out_tasks)} timed-out tasks: {timed_out_tasks}")


@app.get("/t")
async def get_task():
    """客户端获取一个任务"""
    async with lock:
        # 1. 检查并回收超时的任务
        await check_timeouts()

        # 2. 分配一个新任务
        if not tasks_todo:
            if not tasks_in_progress:
                logger.info("All tasks have been completed.")
                return {"message": "All tasks completed"}
            else:
                logger.warning("No tasks available right now, but some are in progress.")
                # 告知客户端稍后再试
                raise HTTPException(status_code=404, detail="No tasks available at the moment, please try again later.")

        # 从待办集合中取出一个任务
        task_id = tasks_todo.pop()
        # 记录到处理中集合
        tasks_in_progress[task_id] = time.time()
        
        logger.info(f"Assigned task {task_id}. Remaining tasks: {len(tasks_todo)}")
        return {"task_id": task_id}


@app.post("/s")
async def submit_task(task_id: int = Form(...), file: UploadFile = File(...)):
    """客户端提交一个任务的结果"""
    async with lock:
        # 1. 验证任务ID是否正在处理中
        if task_id not in tasks_in_progress:
            # 可能是一个已经超时后被别人完成的任务，或者是一个无效的ID
            if task_id in tasks_done:
                logger.warning(f"Received submission for already completed task: {task_id}")
                return {"message": f"Task {task_id} was already completed."}
            else:
                logger.error(f"Received submission for an unknown or timed-out task: {task_id}")
                raise HTTPException(status_code=400, detail=f"Task {task_id} is not in progress or is unknown.")

        # 2. 保存文件
        # 使用 UploadFile.filename 作为服务器端保存的文件名，这样客户端可以控制状态前缀（如X, N等）
        file_path = STORAGE_DIR / file.filename
        try:
            content = await file.read()
            with open(file_path, "wb") as f:
                f.write(content)
        except Exception as e:
            logger.error(f"Failed to save file for task {task_id}. Error: {e}")
            # 如果文件保存失败，不将任务标记为完成，以便它超时后可以被重新分配
            raise HTTPException(status_code=500, detail="Failed to save file.")

        # 3. 更新任务状态
        del tasks_in_progress[task_id]
        tasks_done.add(task_id)

        logger.info(f"Task {task_id} completed and file '{file.filename}' saved. In progress: {len(tasks_in_progress)}, Done: {len(tasks_done)}")
        return {"message": f"Task {task_id} submitted successfully"}


if __name__ == "__main__":
    # 推荐使用命令行运行: uvicorn server:app --host 0.0.0.0 --port 8000
    uvicorn.run(app, host="0.0.0.0", port=48000)