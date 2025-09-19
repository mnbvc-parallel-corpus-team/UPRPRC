import os
import datetime
from pathlib import Path
import datasets
from tqdm import tqdm
import argostranslate.package
import argostranslate.translate
from collections import defaultdict

# --- 1. 配置 ---

# 关键：取消这行的注释来尝试启用CUDA。
# 注意：需要安装支持CUDA的ctranslate2后端。pip install ctranslate2[cuda]
os.environ['ARGOS_DEVICE_TYPE'] = 'cuda'

try:
    WD = Path(__file__).parent.resolve()
except NameError:
    WD = Path.cwd()

DATASET_PATH = WD.parent / "DS_rework"
NUM_SAMPLES = 10

# Argos Translate 使用不同的语言代码
LANG_CODES_ARGO = {
    "ar": "ar", "de": "de", "es": "es",
    "fr": "fr", "ru": "ru", "zh": "zh"
}
TARGET_LANG_CODE_ARGO = "en"

# --- 2. Argos Translate 模型加载/安装辅助函数 ---

# 用一个字典缓存已加载的翻译器实例
INSTALLED_TRANSLATORS = {}

def get_or_install_translator(_from, _to):
    """获取或安装并加载一个Argos Translate翻译器"""
    if tr := INSTALLED_TRANSLATORS.get((_from, _to)):
        return tr

    try:
        tr = argostranslate.translate.get_translation_from_codes(_from, _to)
        INSTALLED_TRANSLATORS[(_from, _to)] = tr
        print(f"Loaded existing translator: {_from} -> {_to}")
        return tr
    except Exception:
        print(f"Translator for {_from} -> {_to} not found. Attempting to install...")

    argostranslate.package.update_package_index()
    available_packages = argostranslate.package.get_available_packages()
    
    package_to_install = next(
        filter(lambda x: x.from_code == _from and x.to_code == _to, available_packages), 
        None
    )
    
    if package_to_install:
        print(f"Installing package: {package_to_install}")
        package_to_install.install()
        # 重新加载
        tr = argostranslate.translate.get_translation_from_codes(_from, _to)
        INSTALLED_TRANSLATORS[(_from, _to)] = tr
        print(f"Successfully installed and loaded: {_from} -> {_to}")
        return tr
    else:
        raise RuntimeError(f"Could not find a translation package for {_from} -> {_to}")


# --- 3. 准备数据 ---

print("--- ArgosTranslate Benchmark ---")
print(f"Using device type: {os.environ.get('ARGOS_DEVICE_TYPE', 'cpu')}")
print("--------------------------------")

print("\nLoading and preparing dataset...")
ds = datasets.load_from_disk(str(DATASET_PATH))["train"].select(range(NUM_SAMPLES))

texts_by_lang = defaultdict(list)
original_texts_flat = []

for row in tqdm(ds, desc="Extracting and grouping text"):
    for lang_code in LANG_CODES_ARGO:
        if lang_code in row and row[lang_code]:
            for segment in row[lang_code].split('\n\n'):
                if segment.strip():
                    texts_by_lang[lang_code].append(segment)
                    original_texts_flat.append((lang_code, segment))

total_items = len(original_texts_flat)
if total_items == 0:
    print("No text found to translate.")
    exit()

print(f"Found {total_items} text segments to translate, grouped by language.")
for lang, texts in texts_by_lang.items():
    print(f"  - {lang}: {len(texts)} segments")


# --- 4. 运行评测 ---

print("\nStarting benchmark...")
all_translations = []
start_time = datetime.datetime.now()

# 遍历每种语言
for lang_short, texts in texts_by_lang.items():
    # 为当前语言对加载翻译器
    translator = get_or_install_translator(lang_short, TARGET_LANG_CODE_ARGO)
    
    # 对当前语言的所有文本进行翻译
    # Argos Translate 不支持真正的批处理API，所以我们只能循环调用
    translated_texts = []
    for text in tqdm(texts, desc=f"Translating '{lang_short}'"):
        # 尽管Argos Translate内部会分句，但API本身是逐条调用的
        translated_texts.append(translator.translate(text))
    
    all_translations.extend(translated_texts)

end_time = datetime.datetime.now()
total_duration = (end_time - start_time).total_seconds()


# --- 5. 报告结果 ---

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
    translated_text = all_translations[i]
    print(f"Original ({original_lang}): {original_text[:120]}...")
    print(f"Translated (en): {translated_text[:120]}...")
    print("-" * 10)

# --- Benchmark Results ---
# Total original segments translated: 1836
# Total time taken: 1235.29 seconds
# Translation speed: 1.49 segments/second