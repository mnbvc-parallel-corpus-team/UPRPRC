import os
import asyncio
import aiohttp
import httpx
from loguru import logger
import traceback # 导入 traceback 模块用于记录详细异常
"""
pip3 install loguru aiohttp httpx -i https://pypi.tuna.tsinghua.edu.cn/simple
tmux new -t r

"""

# --- 配置常量 ---
SERVER_URL = f"http://{os.environ.get('UPRPRC_SVR_HOST','127.0.0.1')}:48000"  # 替换为你的服务器地址
WORKER_NUM = 1  # 在这个客户端进程中启动的并发协程数
RETRIES = 5  # 抓取单个URL的重试次数
SLEEP202 = 300  # 遇到HTTP 202状态码时的等待时间

# 日志配置
logger.add("client_{time}.log", rotation="10 MB", retention="3 days")

# 原始脚本中的常量和头部信息
res_not_ex_str = b"Requested record does not seem to exist."
HEADERS = {
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
}

# 移除了函数签名中的类型注解以确保兼容性
async def get_task_from_server(client):
    """从服务器获取一个任务ID"""
    while 1:
        try:
            response = await client.get(SERVER_URL + "/t", timeout=10)
            response.raise_for_status()  # 如果状态码是 4xx 或 5xx，则抛出异常
            
            data = response.json()
            if "task_id" in data:
                return data["task_id"]
            elif data.get("message") == "All tasks completed":
                logger.info("Server indicates all tasks are completed.")
                return None
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.info("No tasks available from server, will retry after a short wait.")
                await asyncio.sleep(10) # 如果暂时没有任务，等待10秒再试
            else:
                logger.error("Error getting task from server: {e}", e=e)
                await asyncio.sleep(5)
        except httpx.RequestError as e:
            logger.error("Could not connect to server to get task: {e}", e=e)
            await asyncio.sleep(5)

# 移除了函数签名中的类型注解以确保兼容性
async def submit_task_to_server(client, task_id, filename, content):
    """向服务器提交任务结果"""
    data_payload = {'task_id': str(task_id)}
    files_payload = {'file': (filename, content, 'application/octet-stream')}
    
    try:
        response = await client.post(SERVER_URL + "/s", data=data_payload, files=files_payload, timeout=60)
        response.raise_for_status()
        logger.info("Successfully submitted task {task_id} as '{filename}'.", task_id=task_id, filename=filename)
    except httpx.RequestError as e:
        logger.error("Failed to submit task {task_id}: {e}", task_id=task_id, e=e)
    except httpx.HTTPStatusError as e:
        logger.error("Server returned an error on submission for task {task_id}: {text}", task_id=task_id, text=e.response.text)

# 移除了函数签名中的类型注解以确保兼容性
async def worker(worker_id):
    """单个工作协程，循环获取、处理、提交任务"""
    logger.info("Worker {id} started.", id=worker_id)
    # httpx 和 aiohttp 的异步上下文管理器在 Python 3.6 中受支持
    async with httpx.AsyncClient() as http_client, aiohttp.ClientSession(headers=HEADERS) as aio_session:
        while True:
            task_id = await get_task_from_server(http_client)
            if task_id is None:
                logger.info("Worker {id} received no task, shutting down.", id=worker_id)
                break

            logger.info("Worker {id} got task: {task_id}", id=worker_id, task_id=task_id)
            url = 'https://digitallibrary.un.org/record/' + str(task_id)
            
            filename = None
            content = b''

            for retry in range(RETRIES):
                try:
                    async with aio_session.get(url, timeout=120) as resp:
                        if resp.status == 200:
                            bin_content = await resp.read()
                            if res_not_ex_str in bin_content:
                                filename = "X" + str(task_id)
                                content = bin_content
                                logger.warning("Task {task_id}: resource not exists.", task_id=task_id)
                            else:
                                filename = str(task_id)
                                content = bin_content
                                logger.info('Task {task_id}: download done.', task_id=task_id)
                            # await asyncio.sleep(5)
                            break
                        elif resp.status == 202:
                            logger.warning("Task {task_id}: Detect 202, sleep {sleep}s, retry: {retry}", task_id=task_id, sleep=SLEEP202, retry=retry)
                            await asyncio.sleep(SLEEP202)
                            continue
                        elif resp.status == 404:
                            logger.error("Task {task_id}: 404 NOT FOUND.", task_id=task_id)
                            filename = "N" + str(task_id)
                            content = b''
                            break
                        elif resp.status == 410:
                            content = await resp.read()
                            logger.info("410 Gone {task_id}", task_id=task_id)
                            filename = "D" + str(task_id)
                            break
                        else:
                            resp_text = await resp.text()
                            logger.error("Task {task_id}: ERR FETCH {status}, retry: {retry}", task_id=task_id, status=resp.status, retry=retry)
                            if retry == RETRIES - 1:
                                logger.error("Task {task_id}: Skip after max retries. Status: {status}", task_id=task_id, status=resp.status)
                                filename = "E" + str(task_id)
                                content = ("[HTTP_STATUS]\n{status}\n\n[HEADERS]\n{headers}\n\n[CONTENT]\n{text}".format(
                                    status=resp.status, headers=resp.headers, text=resp_text
                                )).encode("utf-8")
                except Exception as e:
                    logger.warning("Task {task_id}: EXCEPTION {exc_type}, RETRY: {retry}", task_id=task_id, exc_type=type(e).__name__, retry=retry)
                    if retry == RETRIES - 1:
                        # 使用 traceback 模块记录完整的异常信息
                        exc_details = traceback.format_exc()
                        logger.error("Task {task_id}: TOO MANY EXCEPTIONS, SKIP. Error: \n{details}", task_id=task_id, details=exc_details)
                        filename = "R" + str(task_id)
                        content = ("[EXCEPTION]\n" + exc_details).encode("utf-8")
                        break
            
            if filename is not None:
                await submit_task_to_server(http_client, task_id, filename, content)
            else:
                logger.error("Task {task_id} finished processing loop without a result. It will time out on server.", task_id=task_id)

async def main():
    workers = [worker(i) for i in range(WORKER_NUM)]
    await asyncio.gather(*workers)
    logger.info("All workers have finished.")

# --- 兼容 Python 3.6 的启动方式 ---
if __name__ == "__main__":
    # 使用 Python 3.6 的标准方式来运行 asyncio 事件循环
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()