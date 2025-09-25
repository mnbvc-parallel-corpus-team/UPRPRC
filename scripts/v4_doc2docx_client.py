import argparse
import multiprocessing as mp
import os
from pathlib import Path
import time
from queue import Empty
import traceback
import winreg
from pathlib import Path

import psutil
import requests
from pywinauto import Application
import win32com.client as win32
from win32com.client import constants
from loguru import logger
import zstandard

import const

# --- 配置 ---
# !!! 重要: 将这里的 IP 地址改为你的服务器地址 !!!
SERVER_URL = "http://127.0.0.1:48482"
# 工作进程处理单个任务的超时时间（秒）
WORKER_TIMEOUT = 5
REQ_TIMEOUT = 300
# --- 临时文件路径 ---
workdir = const.CONVERT_DOCX_CACHE_DIR
workdir.mkdir(exist_ok=True)

# Recommand use RamDisk https://sourceforge.net/projects/imdisk-toolkit/
TEMP_DOC = str((Path(r"R:\\") / 'temp.doc').absolute())
TEMP_DOCX = str((Path(r"R:\\") / 'temp.docx').absolute())
TEMP_DOC_LOCKFILE = str((Path(r"R:\\") / '~$temp.doc').absolute())
TEMP_DOCX_LOCKFILE = str((Path(r"R:\\") / '~$temp.docx').absolute())

OFFICE_VERSION = "16.0"  # Office 2019/365 共用 16.0；如需改版本，修改此处
RELATIVE_KEY = fr"Software\Microsoft\Office\{OFFICE_VERSION}\Word\Resiliency\DisabledItems"

# 64位/32位视图标志；在 64 位系统上可能两边都有
VIEW_FLAGS = [
    0,  # 默认为当前 Python 进程视图
    getattr(winreg, "KEY_WOW64_64KEY", 0),
    getattr(winreg, "KEY_WOW64_32KEY", 0),
]

# --- 结果代码 ---
ACCEPTED = 202  # 主进程已收到任务并交给工作进程
OK = 200      # 工作进程成功完成任务
ERR = 500       # 工作进程处理失败

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

def delete_all_values(hkey):
    """删除当前键下的所有值（先枚举再删除，避免索引变化）"""
    names = []
    i = 0
    while True:
        try:
            name, _, _ = winreg.EnumValue(hkey, i)
            names.append(name)
            i += 1
        except OSError:
            break
    for name in names:
        try:
            winreg.DeleteValue(hkey, name)
            print(f"  [值] 已删除: {name}")
        except OSError as e:
            print(f"  [值] 删除失败: {name} -> {e}")

def delete_subkey_recursive(root, sub_path, sam_desired):
    """
    递归删除子键（含其下所有子内容）
    注意：必须从叶子往上删
    """
    try:
        with winreg.OpenKey(root, sub_path, 0, winreg.KEY_READ | winreg.KEY_WRITE | sam_desired) as hkey:
            # 先删子键
            subkeys = []
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(hkey, i)
                    subkeys.append(subkey_name)
                    i += 1
                except OSError:
                    break
        # 递归删子键
        for sk in subkeys:
            delete_subkey_recursive(root, sub_path + "\\" + sk, sam_desired)
        # 再删自身所有值
        with winreg.OpenKey(root, sub_path, 0, winreg.KEY_READ | winreg.KEY_WRITE | sam_desired) as hkey:
            delete_all_values(hkey)
        # 最后删除当前这个键
        winreg.DeleteKeyEx(root, sub_path, sam_desired, 0)
        print(f"[键] 已删除: {sub_path}")
    except FileNotFoundError:
        # 子路径不存在就算了
        pass
    except OSError as e:
        print(f"[键] 删除失败: {sub_path} -> {e}")

def clear_disabled_items(view_flag):
    """
    清空指定注册表视图下的 DisabledItems：
    - 删除其下所有值
    - 删除其下所有子键
    结束后，如键仍存在，会保留一个“空壳键”
    """
    hive = winreg.HKEY_CURRENT_USER
    sam = winreg.KEY_READ | winreg.KEY_WRITE | view_flag
    try:
        with winreg.OpenKey(hive, RELATIVE_KEY, 0, sam) as hkey:
            print(f"\n=== 处理视图 {view_flag}：{RELATIVE_KEY} ===")
            # 先删除所有子键（必须递归）
            subkeys = []
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(hkey, i)
                    subkeys.append(subkey_name)
                    i += 1
                except OSError:
                    break
            for sk in subkeys:
                delete_subkey_recursive(hive, RELATIVE_KEY + "\\" + sk, view_flag)

            # 再删除该键下所有值
            try:
                with winreg.OpenKey(hive, RELATIVE_KEY, 0, sam) as h2:
                    delete_all_values(h2)
            except FileNotFoundError:
                pass

            print("完成：该视图下 DisabledItems 内容已清空。")
            return True
    except FileNotFoundError:
        # 该视图下可能不存在该键（例如只装了 64 位 Office）
        return False
    except PermissionError:
        print("权限不足：请确保以有权访问 HKCU 的用户运行（通常无需管理员）。")
        return False
    except Exception:
        print("出现异常：")
        traceback.print_exc()
        return False

def force_clear_disable_items_reg():
    any_found = False
    for flag in VIEW_FLAGS:
        ok = clear_disabled_items(flag)
        any_found = any_found or ok
    if any_found:
        print("Clear DisabledItems")

def eliminate_top_window(app: Application):
    try:
        dialog = app.top_window()
        if dialog.texts() == ['显示修复']:
            dialog.close()
            return True

        for i in dialog.children():
            if "安全模式中启动" in ''.join(i.texts()):
                dialog.N.click()
                return True
            if "是否仍要打开它" in ''.join(i.texts()):
                dialog.Y.click()
                return True
            if "是否要指定子文档的路径" in ''.join(i.texts()):
                dialog.N.click()
                return True
    except RuntimeError as e:
        pass
        # traceback.print_exc()
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
            close_top_window()
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
def main(use_compression=False):
    zstd_compressor = zstandard.ZstdCompressor()
    zstd_decompressor = zstandard.ZstdDecompressor()
    logger.info("Client starting...")
    kill_word()  # 启动时清理环境
    force_clear_disable_items_reg()

    mgr = mp.Manager()
    q_result = mgr.Queue()
    q_task = mgr.Queue()

    worker_process = mp.Process(target=save_as_docx_worker, args=(q_result, q_task), daemon=True)
    worker_process.start()
    
    active_task_id = None
    session = requests.Session()
    def report_err(task_id):
        resp = session.get(f"{SERVER_URL}/e?t={task_id}", timeout=REQ_TIMEOUT)
        resp.raise_for_status()
    
    while True:
        # 1. 从服务器获取新任务
        logger.info("Requesting a new task from the server...")
        try:
            response = session.get(SERVER_URL + ("/t" if not use_compression else "/z"), timeout=REQ_TIMEOUT)
            
            if response.status_code == 404:
                logger.info("Server returned 404. No more tasks available. Shutting down.")
                break
            
            response.raise_for_status() # 抛出其他HTTP错误

            # 从响应头中获取任务ID (文件名)
            task_id = response.headers.get('T')
            file_content = response.content
            if use_compression:
                file_content = zstd_decompressor.decompress(file_content)
            
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
                    if use_compression:
                        docx_content = zstd_compressor.compress(docx_content)
                    logger.success(f"Task '{res_task_id}' converted successfully.")
                    
                    # 提交结果到服务器
                    try:
                        files = {'file': (res_task_id, docx_content)}
                        while 1:
                            try:
                                submit_response = session.post(SERVER_URL + ("/s" if not use_compression else "/r"), files=files, timeout=REQ_TIMEOUT)
                                break
                            except Exception as e:
                                print(f"Fail upload, {e} Retrying.")
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
                    report_err(res_task_id)
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
                force_clear_disable_items_reg()
                
                # 重启工作进程
                worker_process = mp.Process(target=save_as_docx_worker, args=(q_result, q_task), daemon=True)
                worker_process.start()
                logger.info("Worker process has been restarted.")
                report_err(active_task_id)
                if active_task_id:
                    logger.warning(f"Task '{active_task_id}' is considered failed due to timeout. The server will re-queue it.")
                    active_task_id = None
                break # 跳出内层while，去获取下一个任务

    # 循环结束后，清理
    logger.info("Client shutting down. Cleaning up processes.")
    worker_process.kill()
    worker_process.join()
    kill_word()
    force_clear_disable_items_reg()
    logger.info("Cleanup complete. Goodbye.")

if __name__ == '__main__':
    # 在Windows上使用 'spawn' 启动方式更稳定
    mp.set_start_method('spawn', force=True)
    parser = argparse.ArgumentParser(description="Run the file conversion client.")
    parser.add_argument(
        '-c',
        action='store_true',
        help="Enable zstd compression for network traffic (for slow connections)."
    )
    args = parser.parse_args()
    main(args.c)