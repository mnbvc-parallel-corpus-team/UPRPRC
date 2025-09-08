import requests
import gzip
import xml.etree.ElementTree as ET
import csv  # 导入csv模块，用于保存为结构化文件
from pathlib import Path
from pprint import pprint # 导入pprint，用于更美观地打印字典和列表

WD = Path(__file__).parent

output_file = WD / "un_library_sitemap_data.csv"

def get_and_parse_sitemap(url):
    """
    获取并解析一个gzip压缩的sitemap URL。
    - 如果是Sitemap索引文件，返回子sitemap的URL列表。
    - 如果是Sitemap内容文件，返回包含loc, lastmod, changefreq, priority的字典列表。
    """
    print(f"正在处理: {url}")
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()

        decompressed_content = gzip.decompress(r.content)
        root = ET.fromstring(decompressed_content)
        
        namespace = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

        # --- 核心修改在这里 ---

        # 1. 判断是否为Sitemap索引文件 (根节点是 sitemapindex, 包含 sitemap 标签)
        sitemap_elements = root.findall('ns:sitemap', namespace)
        if sitemap_elements:
            print("检测到Sitemap索引文件，正在提取子Sitemap链接...")
            # 只提取 <loc> 标签的文本
            return [elem.find('ns:loc', namespace).text for elem in sitemap_elements]

        # 2. 判断是否为Sitemap内容文件 (根节点是 urlset, 包含 url 标签)
        url_elements = root.findall('ns:url', namespace)
        if url_elements:
            print("检测到Sitemap内容文件，正在提取详细URL数据...")
            parsed_data = []
            for url_elem in url_elements:
                # 安全地获取每个标签的文本内容，如果标签不存在则返回None
                loc = url_elem.find('ns:loc', namespace)
                lastmod = url_elem.find('ns:lastmod', namespace)
                changefreq = url_elem.find('ns:changefreq', namespace)
                priority = url_elem.find('ns:priority', namespace)

                data_entry = {
                    'loc': loc.text if loc is not None else None,
                    'lastmod': lastmod.text if lastmod is not None else None,
                    'changefreq': changefreq.text if changefreq is not None else None,
                    'priority': priority.text if priority is not None else None,
                    'from_sitemap': url
                }
                parsed_data.append(data_entry)
            return parsed_data

        # 如果两种类型都不是，返回空列表
        return []

    except requests.exceptions.RequestException as e:
        print(f"请求URL时出错: {url} - {e}")
        return []
    except gzip.BadGzipFile:
        print(f"文件不是有效的Gzip格式: {url}")
        return []
    except ET.ParseError as e:
        print(f"XML解析错误: {url} - {e}")
        return []

# --- 主程序 ---
sitemap_index_url = "https://digitallibrary.un.org/sitemap_index.xml.gz"

# 1. 获取所有子sitemap的URL
child_sitemap_urls = get_and_parse_sitemap(sitemap_index_url)

if not child_sitemap_urls:
    print("未能从索引文件中找到任何子Sitemap URL。程序终止。")
else:
    print(f"\n在索引中找到 {len(child_sitemap_urls)} 个子Sitemap。\n")

    all_page_data = []
    
    # 2. 遍历并处理每一个子sitemap
    for sitemap_url in child_sitemap_urls: 
        print(f"--- 开始处理子Sitemap: {sitemap_url} ---")
        page_data = get_and_parse_sitemap(sitemap_url)
        if page_data:
            print(f"在此Sitemap中找到 {len(page_data)} 个URL条目。")
            all_page_data.extend(page_data)
        else:
            print("未能从此Sitemap中获取数据。")
        print("-" * 50)

    print(f"\n处理完成！总共从前2个子Sitemap中提取了 {len(all_page_data)} 个URL条目。")
    
    # 打印前5个条目看看效果
    print("\n示例数据 (前5条):")
    pprint(all_page_data[:5])
        
    # 3. (强烈推荐) 将所有数据保存到CSV文件，更易于后续处理
    if all_page_data:
        WD = Path.cwd()
        
        # 定义CSV文件的列名
        fieldnames = ['loc', 'lastmod', 'changefreq', 'priority', 'from_sitemap']
        
        with open(output_file, "w", encoding="utf-8", newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            # 写入表头
            writer.writeheader()
            
            # 写入所有数据
            writer.writerows(all_page_data)
            
        print(f"\n所有数据已保存到CSV文件: {output_file}")


# RECORD_INFO_DIR = WD / ""
# r = requests.get("https://digitallibrary.un.org/api/v1/file?recid=4086877")
# print(r)
