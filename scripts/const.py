import os
from pathlib import Path

GET_LIST_FROM_YEAR = 2025
GET_LIST_TO_YEAR = 2025

WORK_DIR = Path(__file__).parent

DOWNLOAD_FILELIST_CACHE_DIR = WORK_DIR / 'dlcache_filelist'
DOWNLOAD_DOC_CACHE_DIR = WORK_DIR / 'dlcache_doc'
CONVERT_DOCX_CACHE_DIR = WORK_DIR / 'cvcache_docx'
CONVERT_TEXT_CACHE_DIR = WORK_DIR / 'cvcache_txt'
CONVERT_TEXT_ERR_DIR = WORK_DIR / 'cvcache_txt_err'
CONVERT_TEXT_FLATTEN_TABLE_CACHE_DIR = WORK_DIR / 'cvcache_flatten_table_txt'
CONVERT_TEXT_FLATTEN_TABLE_ERR_DIR = WORK_DIR / 'cvcache_flatten_table_txt_err'
CONVERT_DATASET_CACHE_DIR = WORK_DIR / 'cvcache_dataset'

TRANSLATION_CACHE_DIR = WORK_DIR / 'trcache_pkl'
TRANSLATION_OUTPUT_DIR = WORK_DIR / 'trresult_dataset'

ALIGN_OUTPUT_DIR = WORK_DIR / 'alresult_dataset'

FILEWISE_JSONL_OUTPUT_DIR = WORK_DIR / 'filewise_result.jsonl'
BLOCKWISE_JSONL_OUTPUT_DIR = WORK_DIR / 'blockwise_result.jsonl' # 单文件

DBG_LOG_OUTPUT_FILE1 = WORK_DIR / 'dbglog1.txt'
DBG_LOG_OUTPUT_FILE2 = WORK_DIR / 'dbglog2.txt'
DBG_LOG_OUTPUT_FILE3 = WORK_DIR / 'dbglog3.txt'
DBG_LOG_OUTPUT_FILE4 = WORK_DIR / 'dbglog4.txt'

# candidate config

TRANSLATION_SERVER_PORT = 29999

# v4 script config

V4_AUTH_CSV = WORK_DIR / "2025_check_results.csv"
V4_DOCUMENT_CACHE = WORK_DIR / "doc_search_cache"
V4_TR_DIR = WORK_DIR / "v4_tr"
V4_SBD_DIR = WORK_DIR / "v4_sbd"
# V4_SBD_DIR = Path(r"F:\v4_sbdwithlang")
V4_FTXT_DIR = WORK_DIR / "v4_ftxt"
# V4_FTXT_DIR = Path(r"F:\v4_ftxt")
V4_BILINGUAL_ALIGN_CACHE = WORK_DIR / "v4_bi"