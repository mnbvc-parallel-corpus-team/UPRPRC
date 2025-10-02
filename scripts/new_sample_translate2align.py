"""
这一步请在所有文件翻译完毕之后再做
"""
import os
from pathlib import Path
import shutil
import datasets
from collections import namedtuple
from typing import Tuple
from itertools import chain

import pylcs

import const

DROP_THRESHOLD = 0.3

print("USING DROP_THRESHOLD = ", DROP_THRESHOLD)

LCSTokenInfo = namedtuple('LCSTokenInfo', ('token', 'length', 'source_line_id'))
def tokenize_by_space_splited_word(input_lines: list[str], output_lines: list[str], offset=0) -> Tuple[list[LCSTokenInfo], list[LCSTokenInfo]]:
    """
    Encode `input_lines` and `output_lines` by space splited word as utf-8 single character, to speedup LCS procedure.
    
    Args:
        input_lines (list[str]): The list of lines from source text.
        output_lines (list[str]): The list of lines from the processed text.
        offset (int): utf-8 encoding begin offset for tokenizing.

    Returns:
        list[list[str]]: The batched lines.
    """
    word_dict = {}
    input_tokens_info = []
    output_tokens_info = []
    for input_line_id, input_line in enumerate(input_lines):
        for word in input_line.split():
            input_tokens_info.append(LCSTokenInfo(
                chr(offset + word_dict.setdefault(word, len(word_dict))),
                len(word),
                input_line_id,
                ))
    
    for output_line_id, output_line in enumerate(output_lines):
        for word in output_line.split():
            if word in word_dict: # 为子序列写的优化
                output_tokens_info.append(LCSTokenInfo(
                    chr(offset + word_dict[word]),
                    len(word),
                    output_line_id,
                    ))
    return input_tokens_info, output_tokens_info

def tokenize_by_char(input_lines: list[str], output_lines: list[str], offset=0) -> Tuple[list[LCSTokenInfo], list[LCSTokenInfo]]:
    """
    """
    char_set = set(chain(*input_lines))
    input_tokens_info = []
    output_tokens_info = []
    for input_line_id, input_line in enumerate(input_lines):
        for char in input_line:
            input_tokens_info.append(LCSTokenInfo(
                char,
                1,
                input_line_id,
                ))
    
    for output_line_id, output_line in enumerate(output_lines):
        for char in output_line:
            if char in char_set: # 为子序列写的优化
                output_tokens_info.append(LCSTokenInfo(
                    char,
                    1,
                    output_line_id,
                    ))
    return input_tokens_info, output_tokens_info

REPLACE_MAP = {
    '，': ',',
    '（': '(',
    '）': ')',
    '？': '?',
    # '。': '.',
    '：': ':',
    '；': ';',
    '“': '"',
    '”': '"',
    '‘': "'",
    '’': "'",
    '！': '!',
}
def replace_zh_punctuation(text: str) -> str:
    return ''.join(map(lambda x: REPLACE_MAP.get(x, x), text))

def tokenize_by_jieba(input_lines: list[str], output_lines: list[str], offset=0) -> Tuple[list[LCSTokenInfo], list[LCSTokenInfo]]:
    """"""
    import jieba
    word_dict = {}
    input_tokens_info = []
    output_tokens_info = []
    for input_line_id, input_line in enumerate(input_lines):
        for word in jieba.cut(replace_zh_punctuation(input_line)):
            word = word.strip()
            if word:
                input_tokens_info.append(LCSTokenInfo(
                    chr(offset + word_dict.setdefault(word, len(word_dict))),
                    len(word),
                    input_line_id,
                    ))
        
    for output_line_id, output_line in enumerate(output_lines):
        for word in jieba.cut(replace_zh_punctuation(output_line)):
            word = word.strip()
            if word in word_dict: # 为子序列写的优化
                output_tokens_info.append(LCSTokenInfo(
                    chr(offset + word_dict[word]),
                    len(word),
                    output_line_id,
                    ))
    return input_tokens_info, output_tokens_info


def gapa(paragraphs_a: list[str] , paragraphs_b: list[str], drop_th=DROP_THRESHOLD, tokenizer=tokenize_by_space_splited_word):
    """
    Graph-Aided Paragraph Alignment
    Also calculates `hit_rate` of every paragraph of input text, as sum of matched word's character count divided by sum of total character count
    这个函数同时还会计算每行输入输出的单词命中率（此行的已匹配单词总长度/此行单词总长度）。
    
    Args:
        paragraphs_a(str): Paragraph (or sentence) level splitted text a
        paragraphs_b(str): Paragraph (or sentence) level splitted text b
    
    Returns:
        list of ([aligned paragraphs from paragraph_a], [aligned paragraphs from paragraph_b], paragraph_a's hit rate, paragraph_b's hit rate)
    Example:
        input:
            lineno  paragraphs_a
            0       1. it's a beautiful
            1       day outside.
            2       2. birds are singing,
            3       flowers are
            4       blooming...
            5       3. on days like these,
            6       kids like you...
            7       4. Should
            8       be
            9       burning
            10      in hell.

            lineno  paragraphs_b
            0       1. it's a beautiful day outside.
            1       2. birds are singing, flowers are blooming...
            2       3. on days like these, kids like you...
            3       4. Should be burning in hell.

        output:
            [
                ([7, 8, 9, 10], [3], 1.0, 1.0),
                ([5, 6], [2], 1.0, 1.0),
                ([2, 3, 4], [1], 1.0, 1.0),
                ([0, 1], [0], 1.0, 1.0)
            ]

    """
    if isinstance(paragraphs_a, str):
        paragraphs_a = paragraphs_a.splitlines()
    if isinstance(paragraphs_b, str):
        paragraphs_b = paragraphs_b.splitlines()
    # 英文为内部对齐语言时可以根据词来对齐，中文为内部对齐语言时可以根据jieba分词来对齐
    # 按字符也行，效率会稍低
    tokens_info_a, tokens_info_b = tokenizer(paragraphs_a, paragraphs_b)

    # 算输入输出的每行的单词命中率，即：匹配的单词总字符数 / 单词总字符数
    hit_rate_a = [0 for _ in paragraphs_a] 
    hit_rate_b = [0 for _ in paragraphs_b]
    hit_a = [0 for _ in paragraphs_a] 
    hit_b = [0 for _ in paragraphs_b]

    tokens_a = ''.join(map(lambda x: x[0], tokens_info_a))
    tokens_b = ''.join(map(lambda x: x[0], tokens_info_b))
    aligned_indexes = pylcs.lcs_sequence_idx(tokens_a, tokens_b) # 输入的每个单词的下标对应于输出的每个单词下标，不为-1失配的情况下保证是递增的
    for token_index_a, token_index_b in enumerate(aligned_indexes):
        if token_index_b != -1:
            _, word_len_a, lineid_a = tokens_info_a[token_index_a]
            _, word_len_b, lineid_b = tokens_info_b[token_index_b]
            # 每个output_lineid对应一段input_lineid的区间，是一个2元素的列表[l, r]，代表本段包含了源文本中行号区间为[l, r]之间的行
            hit_a[lineid_a] += word_len_a
            hit_b[lineid_b] += word_len_b
            hit_rate_a[lineid_a] += word_len_a
            hit_rate_b[lineid_b] += word_len_b

    for p, _ in enumerate(hit_rate_a):
        hit_rate_a[p] /= max(sum(map(len, paragraphs_a[p].split())), 1e-12)

    for p, _ in enumerate(hit_rate_b):
        hit_rate_b[p] /= max(sum(map(len, paragraphs_b[p].split())), 1e-12)


    # 我们需要构造一个 set => set 的映射关系，这是n:m对齐的关键
    edges = {} # 化简成图
    for token_index_a, token_index_b in enumerate(aligned_indexes):
        if token_index_b != -1:
            _, _, lineid_a = tokens_info_a[token_index_a]
            _, _, lineid_b = tokens_info_b[token_index_b]
            if hit_rate_a[lineid_a] >= drop_th and hit_rate_b[lineid_b] >= drop_th:
                edges.setdefault(f"i{lineid_a}", set()).add(f"o{lineid_b}")
                edges.setdefault(f"o{lineid_b}", set()).add(f"i{lineid_a}")
    
    # bfs求连通块(其实可以直接用并查集)
    set2set = []

    while edges:
        n, e = edges.popitem()
        vis = {n}
        q = [e]
        while q:
            e = q.pop()
            for i in e:
                vis.add(i)
                if t := edges.pop(i, None):
                    q.append(t)
        il = []
        ol = []
        for k in vis:
            if k.startswith('i'):
                iid = int(k[1:])
                il.append(iid)
            else:
                oid = int(k[1:])
                ol.append(oid)
        il.sort()
        ol.sort()
        set2set.append(
            (
                il, ol, 
                sum(map(lambda x: hit_a[x], il)) / max(1e-12, sum(map(lambda x: len(''.join(paragraphs_a[x].split())), il))),
                sum(map(lambda x: hit_b[x], ol)) / max(1e-12, sum(map(lambda x: len(''.join(paragraphs_b[x].split())), ol)))
            )
        )
    return set2set


def align(ilang: str | list[str], olang: str | list[str], ilang_tr: str | list[str], olang_tr: str | list[str] = None, tokenizer=tokenize_by_space_splited_word) -> Tuple[list[Tuple[str, str]], list[str], str]:
    """
    1:n对齐，en为主文本(1)，zh为次文本(n)，en_translated为en的翻译文本。
    Args:
        ilang: text in any language except English
        olang: text in English 
        ilang_tr: text translated in English
        olang_tr: in case of some symbol missing English, you may want to align `ilang` and `olang` with their English-translated text
    Returns:
        aligned (list[Tuple[str, str]]): 对齐好的文本，每条是(英, 中)的格式
        dropped (list[Tuple[str, str]]): 对不上的英语段落文本
        preview (str): 对齐预览文本
    """
    if isinstance(ilang, str):
        ilang = ilang.splitlines()
    if isinstance(olang, str):
        olang = olang.splitlines()
    if isinstance(ilang_tr, str):
        ilang_tr = ilang_tr.splitlines()
    if isinstance(olang_tr, str):
        olang_tr = olang_tr.splitlines()

    assert len(ilang) == len(ilang_tr), f"len not eq, ilang:{len(ilang)}, ilang_tr:{len(ilang_tr)}"

    if olang_tr is not None:
        assert len(olang) == len(olang_tr), f"len not eq, olang:{len(olang)}, olang_tr:{len(olang_tr)}"


    aligned = []
    aligned_pairs = []
    preview_text = []

    ivis = set()
    ovis = set()
    set2set = gapa(olang_tr if olang_tr is not None else olang, ilang_tr, DROP_THRESHOLD, tokenizer=tokenizer)
    set2set.sort(key=lambda x: x[0][0])
    for oset, iset, irate, orate in set2set:
        aligned.append(','.join(map(str, iset)) + '|' + ','.join(map(str, oset)))
        itmp = '\n'.join(map(lambda x: ilang[x], iset))
        otmp = '\n'.join(map(lambda x: olang[x], oset))
        aligned_pairs.append((itmp, otmp, irate, orate))
        preview_text.append("")
        preview_text.append(itmp)
        preview_text.append("~" * 10)
        preview_text.append(otmp)
        preview_text.append("")
        for x in iset: ivis.add(x)
        for x in oset: ovis.add(x)

    preview_text.append('#' * 10)

    for p, i in enumerate(ilang):
        if p not in ivis:
            preview_text.append("")
            preview_text.append(i)
            preview_text.append("")
    
    preview_text.append('#' * 10)

    for p, i in enumerate(olang):
        if p not in ovis:
            preview_text.append("")
            preview_text.append(i)
            preview_text.append("")
    
    return aligned, aligned_pairs, '\n'.join(preview_text)

def read_secret(key: str) -> str:
    v = os.environ[key] = os.environ.get(key) or input(f"Please input {key}:")    
    return v

ALL_SOURCE_LANGS = ('es', 'zh', 'fr', 'ru', 'ar', 'de')
TARGET_LANG = 'en'
INPUT_DIR_TRANSLATION = const.TRANSLATION_OUTPUT_DIR # translate_poc.py输出
OUTPUT_DIR_ALIGNMENT = const.ALIGN_OUTPUT_DIR # datasets输出

if __name__ == '__main__':
    OUTPUT_DIR_ALIGNMENT.mkdir(exist_ok=True, parents=True)

    for src_lang in ALL_SOURCE_LANGS:
        dataset = datasets.load_from_disk(INPUT_DIR_TRANSLATION / f'{src_lang}2{TARGET_LANG}')

        def gen_func(): # translate和align步骤产出的数据集输出应该是按在原来数据集中顺序的，并且同一个record里是按段落顺序的，这个特性在下一个步骤合批时用到
            for rid, row in enumerate(dataset):
                rec = row['record']
                print(rid, rec)
                src = row[f'clean_{src_lang}']
                dst = row[f'clean_{TARGET_LANG}']
                tr = row[f'{src_lang}2{TARGET_LANG}']
                if src and dst:
                    aligned, pairs, preview = align(src, dst, tr)
                    for apairs, atext in zip(aligned, pairs):
                        i, o, _ir, _or = atext
                        yield {
                            'record': rec, 
                            'clean_para_index_set_pair': apairs, 
                            'src_lang': src_lang, 
                            'dst_lang': TARGET_LANG, 
                            'src_text': i, 
                            'dst_text': o, 
                            'src_rate': _ir, 
                            'dst_rate': _or
                        }

        dataset = datasets.Dataset.from_generator(gen_func, features=datasets.Features({
            'record': datasets.Value('string'),
            'clean_para_index_set_pair': datasets.Value('string'),
            'src_lang': datasets.Value('string'),
            'dst_lang': datasets.Value('string'),
            'src_text': datasets.Value('string'),
            'dst_text': datasets.Value('string'),
            'src_rate': datasets.Value('float'),
            'dst_rate': datasets.Value('float'),
        }))
        save_dir = OUTPUT_DIR_ALIGNMENT / f'{src_lang}2{TARGET_LANG}'
        shutil.rmtree(save_dir, ignore_errors=True)
        dataset.save_to_disk(save_dir)

    # ds.save_to_disk(METHOD2_PREVIEW_DS_PATH)

    # ds = datasets.load_from_disk(METHOD2_PREVIEW_DS_PATH)
    # ds.push_to_hub(repo_id=f'undl_{SRC}2{DST}_aligned', split='train', token=read_secret('HF_TOKEN'), )

