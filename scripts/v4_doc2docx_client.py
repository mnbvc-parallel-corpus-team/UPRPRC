import multiprocessing as mp
import os
import re
import time
import datetime
from queue import Empty
from pathlib import Path

import psutil
import requests
from pywinauto import Application
import win32com.client as win32
from win32com.client import constants
from loguru import logger

import const

# --- 配置 ---
# !!! 重要: 将这里的 IP 地址改为你的服务器地址 !!!
SERVER_URL = "http://127.0.0.1:48482"
# 工作进程处理单个任务的超时时间（秒）
WORKER_TIMEOUT = 120
# 客户端日志
CLIENT_LOG_FILE = __file__.replace(".py",".log")

# --- 临时文件路径 ---
workdir = const.CONVERT_DOCX_CACHE_DIR
workdir.mkdir(exist_ok=True)

TEMP_DOC = str((workdir / 'temp.doc').absolute())
TEMP_DOCX = str((workdir / 'temp.docx').absolute())
TEMP_DOC_LOCKFILE = str((workdir / '~$temp.doc').absolute())
TEMP_DOCX_LOCKFILE = str((workdir / '~$temp.docx').absolute())

# --- 结果代码 ---
ACCEPTED = 202  # 主进程已收到任务并交给工作进程
OK = 200      # 工作进程成功完成任务
ERR = 500       # 工作进程处理失败

# --- 日志配置 ---
logger.add(CLIENT_LOG_FILE, rotation="5 MB", retention="3 days", level="INFO")

# --- Word 进程和窗口管理 (来自你的原始脚本) ---

def scan_word():
    pids = []
    for process in psutil.process_iter(attrs=['pid', 'name']):
        if process.info['name'] == "WINWORD.EXE":
            pids.append(process.info['pid'])
    return pids

def kill_word():
    logger.warning("Killing all WINWORD.EXE processes.")
    for pid in scan_word():
        try:
            p = psutil.Process(pid)
            p.kill()
        except psutil.NoSuchProcess:
            pass

def eliminate_top_window(app: Application):
    try:
        dialog = app.top_window()
        dialog_text = ''.join(dialog.texts())
        
        if '显示修复' in dialog_text:
            dialog.close()
            return True
        if "安全模式中启动" in dialog_text:
            dialog.N.click() # 点击“否”
            return True
        if "是否仍要打开它" in dialog_text:
            dialog.Y.click() # 点击“是”
            return True
    except Exception:
        pass
    return False

def close_top_window():
    pids = scan_word()
    if not pids:
        return
    logger.info("Checking for and closing any blocking Word dialogs...")
    try:
        app = Application().connect(process=pids[-1])
        while eliminate_top_window(app):
            logger.warning('Detected and closed a Word dialog window.')
            time.sleep(0.5)
    except Exception as e:
        logger.error(f"Failed to connect to Word process for closing windows: {e}")

# --- 工作进程 ---

def save_as_docx_worker(q_result: mp.Queue, q_task: mp.Queue):
    """
    易出错的工作进程，通过队列与主进程通信。
    它会启动一个Word实例并持续处理任务。
    """
    word = None
    
    def start_word_instance():
        logger.info("Starting a new WINWORD.EXE instance via COM...")
        return win32.gencache.EnsureDispatch('Word.Application')

    word = start_word_instance()

    while True:
        task_id, content = q_task.get()
        q_result.put((ACCEPTED, task_id))
        
        # 清理上一次可能留下的临时文件和锁文件
        for f_path in [TEMP_DOC, TEMP_DOCX, TEMP_DOC_LOCKFILE, TEMP_DOCX_LOCKFILE]:
            if os.path.exists(f_path):
                try:
                    os.remove(f_path)
                except PermissionError:
                    logger.error(f"PermissionError removing {f_path}. Killing Word and retrying.")
                    kill_word()
                    time.sleep(2)
                    os.remove(f_path)
                    word = start_word_instance()
                except Exception as e:
                    logger.error(f"Error removing {f_path}: {e}")


        # 将任务内容写入临时文件
        with open(TEMP_DOC, 'wb') as f:
            f.write(content)

        doc = None
        try:
            doc = word.Documents.Open(TEMP_DOC, ReadOnly=True)
            doc.SaveAs(TEMP_DOCX, FileFormat=constants.wdFormatXMLDocument)
            doc.Close(False)
            doc = None
            
            # 检查输出文件是否为空
            if not os.path.exists(TEMP_DOCX) or os.stat(TEMP_DOCX).st_size == 0:
                raise ValueError('Conversion resulted in an empty or non-existent file.')
            
            with open(TEMP_DOCX, 'rb') as f:
                docx_content = f.read()
            
            q_result.put((OK, task_id, docx_content))
            
        except win32.pywintypes.com_error as e:
            logger.error(f"COM Error on task '{task_id}': {e}")
            if doc:
                doc.Close(False)
            q_result.put((ERR, task_id))
            logger.info("Restarting Word due to COM error.")
            kill_word()
            word = start_word_instance()
        except Exception as e:
            logger.error(f"Generic Error on task '{task_id}': {e}")
            if doc:
                doc.Close(False)
            q_result.put((ERR, task_id))


# --- 主控制进程 ---
def main():
    logger.info("Client starting...")
    kill_word()  # 启动时清理环境

    mgr = mp.Manager()
    q_result = mgr.Queue()
    q_task = mgr.Queue()

    worker_process = mp.Process(target=save_as_docx_worker, args=(q_result, q_task), daemon=True)
    worker_process.start()
    
    active_task_id = None
    session = requests.Session()
    
    while True:
        # 1. 从服务器获取新任务
        logger.info("Requesting a new task from the server...")
        try:
            response = session.get(f"{SERVER_URL}/t", timeout=30)
            
            if response.status_code == 404:
                logger.info("Server returned 404. No more tasks available. Shutting down.")
                break
            
            response.raise_for_status() # 抛出其他HTTP错误

            # 从响应头中获取任务ID (文件名)
            disp = response.headers.get('content-disposition')
            task_id = re.search(r'filename="([^"]+)"', disp).group(1)
            file_content = response.content
            
            logger.info(f"Received task: {task_id}")
            q_task.put((task_id, file_content))

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error when fetching task: {e}. Retrying in 15 seconds...")
            time.sleep(15)
            continue

        # 2. 等待工作进程的结果 (带超时)
        close_window_attempts = 0
        while True:
            try:
                status, *args = q_result.get(timeout=WORKER_TIMEOUT)
                
                if status == ACCEPTED:
                    active_task_id = args[0]
                    logger.info(f"Worker accepted task: {active_task_id}")
                    close_window_attempts = 0 # 重置超时尝试
                
                elif status == OK:
                    res_task_id, docx_content = args
                    logger.success(f"Task '{res_task_id}' converted successfully.")
                    
                    # 提交结果到服务器
                    try:
                        files = {'file': (f'{res_task_id}.docx', docx_content)}
                        data = {'task_id': res_task_id}
                        submit_response = session.post(f"{SERVER_URL}/s", files=files, data=data, timeout=60)
                        submit_response.raise_for_status()
                        logger.success(f"Successfully submitted result for task '{res_task_id}'.")
                    except requests.exceptions.RequestException as e:
                        logger.error(f"Failed to submit result for '{res_task_id}': {e}")
                    
                    active_task_id = None
                    break # 跳出内层while，去获取下一个任务

                elif status == ERR:
                    res_task_id = args[0]
                    logger.error(f"Worker failed to process task '{res_task_id}'. Moving to next task.")
                    active_task_id = None
                    break # 跳出内层while，去获取下一个任务

            except Empty:
                logger.warning(f"Worker timed out after {WORKER_TIMEOUT}s on task: {active_task_id}.")
                if close_window_attempts < 2:
                    close_window_attempts += 1
                    close_top_window()
                    logger.info("Attempted to close blocking windows. Waiting for result again.")
                    continue
                
                logger.error("Worker is still unresponsive. Killing and restarting worker process.")
                worker_process.kill()
                worker_process.join()
                kill_word() # 确保Word也被杀掉
                
                # 重启工作进程
                worker_process = mp.Process(target=save_as_docx_worker, args=(q_result, q_task), daemon=True)
                worker_process.start()
                logger.info("Worker process has been restarted.")
                
                if active_task_id:
                    logger.warning(f"Task '{active_task_id}' is considered failed due to timeout. The server will re-queue it.")
                    active_task_id = None
                
                break # 跳出内层while，去获取下一个任务

    # 循环结束后，清理
    logger.info("Client shutting down. Cleaning up processes.")
    worker_process.kill()
    worker_process.join()
    kill_word()
    logger.info("Cleanup complete. Goodbye.")

if __name__ == '__main__':
    # 在Windows上使用 'spawn' 启动方式更稳定
    mp.set_start_method('spawn', force=True)
    main()