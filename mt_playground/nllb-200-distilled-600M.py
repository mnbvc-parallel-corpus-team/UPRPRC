import datetime
import torch
from pathlib import Path
from transformers import pipeline, __version__ as transformers_version
import datasets
from collections import defaultdict
from tqdm import tqdm
import nltk
import warnings

nltk.download('punkt')
nltk.download('punkt_tab')

# --- 1. 新增：长文本翻译函数 ---
def translate_long_text(text, translator, src_lang, tgt_lang, max_chunk_tokens=400):
    """
    将长文本分块，翻译后拼接结果。
    :param text: 需要翻译的长文本。
    :param translator: transformers pipeline 对象。
    :param src_lang: 源语言NLLB代码。
    :param tgt_lang: 目标语言NLLB代码。
    :param max_chunk_tokens: 每个块的最大token数，要小于模型的最大长度限制。
    :return: 完整的翻译结果字符串。
    """
    # 使用nltk进行分句
    sentences = nltk.sent_tokenize(text)
    
    tokenizer = translator.tokenizer
    chunks = []
    current_chunk = []
    current_length = 0

    for sentence in sentences:
        # 估算句子的token长度
        # 我们使用编码后的ID数量来估算，这比直接用len(tokenizer.tokenize(sentence))更准确
        sentence_tokens = len(tokenizer.encode(sentence, add_special_tokens=False))
        
        if current_length + sentence_tokens > max_chunk_tokens:
            # 当前块已满，将其作为一个整体添加到chunks列表
            if current_chunk:
                chunks.append(" ".join(current_chunk))
            # 开始一个新的块
            current_chunk = [sentence]
            current_length = sentence_tokens
        else:
            # 将句子添加到当前块
            current_chunk.append(sentence)
            current_length += sentence_tokens
            
    # 不要忘记最后一个块
    if current_chunk:
        chunks.append(" ".join(current_chunk))

    # 如果文本很短，chunks列表可能为空或只有一个元素
    if not chunks:
        # 如果原始文本根本没有内容，返回空字符串
        if not text.strip():
            return ""
        # 否则，将整个文本作为一个块
        chunks = [text]

    # 批量翻译所有块
    # 在调用pipeline时，我们为输出设置一个较大的max_length，确保单个块的翻译不会被截断
    translated_chunks = translator(
        chunks,
        src_lang=src_lang,
        tgt_lang=tgt_lang,
        max_length=1024  # 为翻译结果设置一个足够大的上限
    )
    
    # 拼接翻译结果
    full_translation = " ".join([chunk['translation_text'] for chunk in translated_chunks])
    return full_translation


# --- 2. 配置 (基本不变) ---
try:
    WD = Path(__file__).parent.resolve()
except NameError:
    WD = Path.cwd()

DATASET_PATH = WD.parent / "DS_rework"
NUM_SAMPLES = 10
MODEL_NAME = "facebook/nllb-200-distilled-600M"

LANG_CODES = { "ar": "ara_Arab", "de": "deu_Latn", "es": "spa_Latn", "fr": "fra_Latn", "ru": "rus_Cyrl", "zh": "zho_Hans" }
TARGET_LANG_CODE = "eng_Latn"

# --- 3. 加载模型 (基本不变) ---
device = "cuda:0" if torch.cuda.is_available() else "cpu"
model_kwargs = {'dtype': torch.float16} if device.startswith("cuda") else {}

print("--- Benchmark Configuration ---")
# ... (打印配置信息部分不变) ...

print("\nLoading translation model...")
translator = pipeline( "translation", model=MODEL_NAME, device=device, **model_kwargs )
print("Model loaded successfully.")

# --- 4. 准备数据 (基本不变) ---
print("\nLoading and preparing dataset...")
ds = datasets.load_from_disk(str(DATASET_PATH))["train"].select(range(NUM_SAMPLES))
texts_by_lang = defaultdict(list)
# 保存原始文本用于结果对比
original_texts_flat = [] 

for row in tqdm(ds, desc="Extracting and grouping text"):
    for lang_code in LANG_CODES:
        if lang_code in row and row[lang_code]:
            for segment in row[lang_code].split('\n\n'):
                if segment.strip():
                    texts_by_lang[lang_code].append(segment)
                    original_texts_flat.append((lang_code, segment))

total_items = len(original_texts_flat)
# ... (打印统计信息部分不变) ...

# --- 5. 运行评测 (逻辑修改) ---
print("\nStarting benchmark...")
all_translations = []
start_time = datetime.datetime.now()

# 我们现在逐个处理原始的、未分块的文本段落
# translate_long_text 函数内部会处理分块和批量翻译
for lang_code, text_list in texts_by_lang.items():
    nllb_src_code = LANG_CODES[lang_code]
    for text in tqdm(text_list, desc=f"Translating '{lang_code}' segments"):
        # 对每个文本段落（无论长短）都使用我们的新函数
        translated_text = translate_long_text(text, translator, nllb_src_code, TARGET_LANG_CODE)
        all_translations.append({'translation_text': translated_text})

end_time = datetime.datetime.now()
total_duration = (end_time - start_time).total_seconds()

# --- 6. 报告结果 (基本不变) ---
print("\n--- Benchmark Results ---")
print(f"Total original segments translated: {total_items}")
print(f"Total time taken: {total_duration:.2f} seconds")
if total_duration > 0:
    items_per_second = total_items / total_duration
    print(f"Translation speed: {items_per_second:.2f} segments/second")
print("-------------------------\n")


# 打印前5条翻译结果以供验证
print("--- Sample Translations ---")
for i in range(min(5, len(all_translations))):
    original_lang, original_text = original_texts_flat[i]
    translated_text = all_translations[i]['translation_text']
    print(f"Original ({original_lang}): {original_text[:120]}...")
    print(f"Translated (en): {translated_text[:120]}...")
    print("-" * 10)

#     --- Benchmark Results ---
# Total original segments translated: 1836
# Total time taken: 1454.14 seconds
# Translation speed: 1.26 segments/second