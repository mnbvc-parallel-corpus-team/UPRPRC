# fetch("https://documents.un.org/api/search?l=en&rid=9406dcc2-db5f-4d52-a5b7-e8e6f1dff45d", {
#   "headers": {
#     "accept": "*/*",
#     "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
#     "authorization": "Access 146795157230121",
#     "cache-control": "public, max-age=0",
#     "content-type": "application/json",
#     "pragma": "no-cache",
#     "priority": "u=1, i",
#     "sec-ch-ua": "\"Not;A=Brand\";v=\"99\", \"Microsoft Edge\";v=\"139\", \"Chromium\";v=\"139\"",
#     "sec-ch-ua-mobile": "?0",
#     "sec-ch-ua-platform": "\"Windows\"",
#     "sec-fetch-dest": "empty",
#     "sec-fetch-mode": "cors",
#     "sec-fetch-site": "same-origin"
#   },
#   "referrer": "https://documents.un.org/",
#   "body": "{\"symbol\":\"\",\"jobNumber\":\"*\",\"publicationDate\":\"* TO *\",\"releaseDate\":\"* TO *\",\"title\":\"\",\"subject\":\"\",\"session\":\"\",\"agenda\":\"\",\"truncation\":\"right\",\"fullTextSearch\":{\"language\":\"en\",\"searchText\":\"\",\"type\":\"Find this phrase\",\"exact\":false},\"sortOptions\":{\"sortField\":\"Sort by date - descending\"},\"pagination\":{\"currentPage\":5,\"itemsPerPage\":20},\"screenLanguage\":\"en\",\"tcodes\":[]}",
#   "method": "POST",
#   "mode": "cors",
#   "credentials": "include"
# });

# pip install aiohttp tqdm
import pickle
import asyncio
import json
import math
import datetime
import csv
import os
import hashlib
import base64
from pathlib import Path

import aiohttp
import datasets
from tqdm import tqdm

def read_secret(key: str) -> str:
    v = os.environ[key] = os.environ.get(key) or input(f"Please input {key}:")    
    return v


# --- 配置区域 ---

WD = Path(__file__).parent

DOCUMENT_SEARCH_CACHE_DIR = WD / "doc_search_cache"
DOCUMENT_SEARCH_CACHE_DIR.mkdir(exist_ok=True)
# API 端点 URL
API_URL = "https://documents.un.org/api/search?l=en&rid=4b0d557a-9dfb-48e3-81c2-9f3780c9e246"

# 并发请求数量 (Worker 数量)
WORKERS = 1  # 你可以根据你的网络情况和服务器的承受能力调整这个值

# 基础请求头，Authorization 会被动态生成
BASE_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
    "Content-Type": "application/json",
    "Sec-Ch-Ua": "\"Not;A=Brand\";v=\"99\", \"Microsoft Edge\";v=\"139\", \"Chromium\";v=\"139\"",
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": "\"Windows\"",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Referer": "https://documents.un.org/",
}

# 基础请求体，分页信息会被动态修改
BASE_BODY = {
    "symbol": "",
    "jobNumber": "*",
    "publicationDate": "* TO *",
    "releaseDate": "* TO *",
    "title": "",
    "subject": "",
    "session": "",
    "agenda": "",
    "truncation": "right",
    "fullTextSearch": {"language": "en", "searchText": "", "type": "Find this phrase", "exact": False},
    "sortOptions": {"sortField": "Sort by date - ascending"},
    "pagination": {"currentPage": 1, "itemsPerPage": 20}, # 这个每页数量不能调大，他会每跳是固定20个，会搜到重复的记录
    "screenLanguage": "en",
    "tcodes": [],
}

SEARCH_CONFIG_HASH = base64.b32encode(hashlib.md5(json.dumps(BASE_BODY, sort_keys=True, ensure_ascii=True).encode('ascii')).digest()).decode()

# 输出文件名
OUTPUT_DS = WD / 'documents.un.org_search_result'
OUTPUT_JSON_FOR_PREVIEW = WD / 'documents.un.org_preview.json'

AUTH_TOKEN_DICT = {}
# 打表文件
with open(WD / "2025_check_results.csv", "r", encoding="utf-8") as f:
    dr = csv.DictReader(f)
    for row in dr:
        AUTH_TOKEN_DICT[(int(row["Month"]), int(row["Day"]), int(row["Hour"]), int(row["Minute"]))] = row["CheckResult"]

# --- 脚本核心逻辑 ---

def get_auth_token() -> str:
    """
    生成与当前时间相关的 Authorization Token。
    
    !!! 重要: 请在这里实现你自己的真实逻辑 !!!
    
    下面是一个基于当前时间戳（毫秒）的示例。
    你提供的 token "Access 146795157230121" 看起来像是 "Access " 加上一个数字。
    这个数字很可能是一个时间戳。
    请根据你获取 token 的方法，替换下面的实现。
    """
    d = datetime.datetime.now(datetime.timezone.utc)
    
    return f"Access {AUTH_TOKEN_DICT[(d.month, d.day, d.hour, d.minute)]}"

async def fetch_page_data(session: aiohttp.ClientSession, page: int) -> list:
    """
    异步获取单个页面的数据。

    Args:
        session: aiohttp 的客户端会话。
        page: 要获取的页码。

    Returns:
        一个包含该页数据的列表，如果失败则返回空列表。
    """
    # 构造当前页的请求体
    body = BASE_BODY.copy()
    body["pagination"]["currentPage"] = page

    # 构造当前请求的头，包含动态生成的 token
    headers = BASE_HEADERS.copy()
    headers["Authorization"] = get_auth_token()

    cache_file = DOCUMENT_SEARCH_CACHE_DIR / f"{SEARCH_CONFIG_HASH}-{BASE_BODY['pagination']['itemsPerPage']}-{page}.pkl"
    if cache_file.exists():
        with cache_file.open("rb") as f:
            pkl = pickle.load(f)
            if pkl and len(pkl) == BASE_BODY["pagination"]["itemsPerPage"]:
                return pkl
            else:
                print("refetch", page)
    try:
        async with session.post(API_URL, headers=headers, json=body) as response:
            if response.status == 200:
                data = await response.json()

                if data.get("status") == 1 and "data" in data.get("body", {}):
                    return_val = data["body"]["data"]
                    with cache_file.open("wb") as f:
                        pickle.dump(return_val, f)
                    return 
                else:
                    print(f"警告: 第 {page} 页返回的数据格式不正确: {data}")
                    return []
            else:
                print(f"警告: 第 {page} 页请求失败，状态码: {response.status}")
                return []
    except aiohttp.ClientError as e:
        print(f"警告: 第 {page} 页请求时发生网络错误: {e}")
        return []
    except asyncio.TimeoutError:
        print(f"警告: 第 {page} 页请求超时")
        return []

async def main():
    """
    主执行函数
    """
    print("开始下载数据...")
    
    
    all_data = []

    async with aiohttp.ClientSession() as session:
        # 1. 发送第一个请求以获取元数据（总条目数）
        print("正在获取元信息 (总条目数)...")
        initial_data = await fetch_page_data(session, 1)

        if not initial_data:
            # 这里需要一个同步的、单独的请求来确保能拿到元信息
            # 为了简单起见，我们假设fetch_page_data在获取第一页时总能成功
            # 如果依然失败，需要一个更鲁棒的同步重试逻辑
            # 但为了脚本简洁，我们先用异步版本获取
            print("错误: 无法获取元信息，请检查网络或授权 Token 逻辑。脚本终止。")
            
            # 我们需要一个同步的请求来获取总数，因为上面的异步函数可能被信号量限制
            # 重新进行一次同步请求以获取总数
            body = BASE_BODY.copy()
            headers = BASE_HEADERS.copy()
            headers["Authorization"] = get_auth_token()
            try:
                async with session.post(API_URL, headers=headers, json=body) as resp:
                    if resp.status == 200:
                        first_page_json = await resp.json()
                    else:
                        first_page_json = {}
            except Exception:
                 first_page_json = {}
                 
            if not first_page_json.get("body", {}).get("meta"):
                return
        else: # 如果第一次异步请求成功了，也需要获取总数
            body = BASE_BODY.copy()
            headers = BASE_HEADERS.copy()
            headers["Authorization"] = get_auth_token()
            async with session.post(API_URL, headers=headers, json=body) as resp:
                first_page_json = await resp.json()


        total_items = first_page_json.get("body", {}).get("meta", {}).get("numberOfGroups", 0)
        items_per_page = BASE_BODY["pagination"]["itemsPerPage"]

        if total_items == 0:
            print("没有找到任何数据。")
            return
            
        total_pages = math.ceil(total_items / items_per_page)
        print(f"总共找到 {total_items} 条数据，共 {total_pages} 页。将以 {WORKERS} 个并发任务开始下载。")
        
        all_data.extend(first_page_json.get("body",{}).get("data",[]))

        # 2. 创建从第 2 页到最后一页的所有请求任务
        # tasks = [
        #     fetch_page_data(session, page)
        #     for page in range(2, total_pages + 1)
        # ]

        # 3. 使用 tqdm.gather 执行所有任务并显示进度条
        # page_results = await tqdm.gather(*tasks, desc="下载进度")
        page_results = [
            (await fetch_page_data(session, page)) for page in tqdm(range(2, total_pages)) # 少拿一页，以免之后更新最后一页有缓存要手动删掉
        ]

        data_dedup_set = set()
        # 4. 合并所有结果
        for ridx, result in enumerate(page_results):
            for r in result:
                jstr = json.dumps(r,sort_keys=True)
                if jstr not in data_dedup_set:
                    data_dedup_set.add(jstr)
                    all_data.append(r)
    
    # 5. 将所有数据写入文件
    print(f"\n数据下载完成，共获取 {len(all_data)} 条记录。")
    print(f"正在将数据写入到文件: {OUTPUT_DS}...")
    ds = datasets.DatasetDict({"train": datasets.Dataset.from_list(all_data)})
    ds.save_to_disk(OUTPUT_DS)
    ds.push_to_hub("documents.un.org_search_result", token=read_secret("HF_TOKEN"))
    try:
        with open(OUTPUT_JSON_FOR_PREVIEW, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, indent=2, ensure_ascii=False)
        print(f"成功！全量数据已保存至 {OUTPUT_JSON_FOR_PREVIEW}")
    except IOError as e:
        print(f"写入文件时出错: {e}")


if __name__ == "__main__":
    # 在 Windows 上运行 aiohttp 可能需要这个策略
    # asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())