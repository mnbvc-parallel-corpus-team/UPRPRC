import os
from pathlib import Path

WINWORD_EXE = r'C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE'

WORK_DIR = Path(os.path.dirname(os.path.abspath(__file__)))

DOWNLOAD_FILELIST_CACHE_DIR = WORK_DIR / 'dlcache_filelist'
DOWNLOAD_DOC_CACHE_DIR = WORK_DIR / 'dlcache_doc'
CONVERT_DOCX_CACHE_DIR = WORK_DIR / 'cvcache_docx'
CONVERT_TEXT_CACHE_DIR = WORK_DIR / 'cvcache_txt'
CONVERT_DATASET_CACHE_DIR = WORK_DIR / 'cvcache_dataset'

TRANSLATION_CACHE_DIR = WORK_DIR / 'trcache_pkl'
TRANSLATION_OUTPUT_DIR = WORK_DIR / 'trresult_dataset'

ALIGN_OUTPUT_DIR = WORK_DIR / 'alresult_dataset'

FILEWISE_JSONL_OUTPUT_DIR = WORK_DIR / 'filewise_result.jsonl'
BLOCKWISE_JSONL_OUTPUT_DIR = WORK_DIR / 'blockwise_result.jsonl' # 单文件

# candidate config

TRANSLATION_SERVER_PORT = 29999