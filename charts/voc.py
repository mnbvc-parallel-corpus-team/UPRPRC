# import pickle
# with open("每种语言的词汇_总数.pkl", "rb") as f:
#     j = pickle.load(f)

# print(j.keys())

# print(sorted(j['ar'].items(),key=lambda x:-x[1])[:200])
# print(sorted(j['de'].items(),key=lambda x:-x[1])[:200])
# print(sorted(j['fr'].items(),key=lambda x:-x[1])[:200])
# print(sorted(j['en'].items(),key=lambda x:-x[1])[:200])
# print(sorted(j['es'].items(),key=lambda x:-x[1])[:200])
# print(sorted(j['ru'].items(),key=lambda x:-x[1])[:200])
# print(sorted(j['zh'].items(),key=lambda x:-x[1])[:200])
# [(' ', 832168105), ('|', 60618719), ('\n', 60530580), ('的', 37446488), ('，', 30609376), ('。', 18754342), ('和', 17527268), ('、', 11547845), ('.', 9665373), ('在', 8507393), ('/', 7695185), (')', 7012498), ('(', 6993816), ('年', 5703159), ('=', 5587062), ('了', 4376486), ('第', 4085385), ('月', 3558750), ('是', 3511685), ('；', 3487466), ('》', 3197622), ('《', 3197518), ('委员会', 3148545), ('-', 3143079), (',', 3109429), ('对', 3106627), ('并', 2904343), ('1', 2899836), ('与', 2856539), ('会议', 2725146), ('日', 2694106), ('国家', 2644903), ('问题', 2498055), ('[', 2439142), ('：', 2438325), (']', 2438277), ('联合国', 2433365), ('为', 2327267), ('将', 2274958), ('中', 2230468), ('报告', 2219545), ('国际', 2073668), ('或', 2036590), ('2', 2035698), ('发展', 1942209), ('关于', 1911859), ('提供', 1877685), ('其', 1851945), ('包括', 1801941), ('3', 1768714), ('）', 1764596), ('（', 1758666), ('以及', 1751601), ('以', 1719421), ('组织', 1710226), ('the', 1701519), ('号', 1700140), ('“', 1656737), ('工作', 1628003), ('”', 1563546), ('有', 1556217), ('决议', 1526488), ('通过', 1510101), ('—', 1494234), ('不', 1476884), ('其他', 1450103), ('4', 1446154), ('方案', 1434048), ('执行', 1433967), ('社会', 1428232), ('到', 1424124), ('情况', 1410256), ('特别', 1378125), ('5', 1360267), ('该', 1359537), ('进行', 1331678), ('6', 1320601), ('这些', 1290944), ('人权', 1289318), ('of', 1288550), ('A', 1287457), ('所', 1282529), ('可', 1271881), ('安全', 1247566), ('方面', 1241361), ('机构', 1223174), ('公约', 1212269), ('上', 1186532), ('有关', 1184455), ('建议', 1172302), ('一个', 1169137), ('行动', 1166536), ('大会', 1137525), ('理事会', 1132611), ('妇女', 1126005), ('所有', 1122277), ('7', 1117306), ('活动', 1110593), ('向', 1099475), ('政府', 1084294), ('and', 1060177), ('区域', 1058778), ('我们', 1054765), ('12', 1049460), ('还', 1045234), ('根据', 1041988), ('项目', 1041121), ('10', 1001354), ('人', 992261), ('支持', 983143), ('及', 957037), ('a', 949977), ('9', 947090), ('合作', 928161), ('经济', 920420), ('儿童', 918987), ('就', 918215), ('决定', 912177), ('规定', 911902), ('应', 911271), ('8', 901510), ('这', 899178), ('代表', 885890), ('被', 882053), ('也', 867896), ('而', 866182), ('段', 864363), ('促进', 857761), ('秘书长', 851077), ('下', 840922), ('权利', 840151), ('确保', 821597), ('地', 819140), ('加强', 814344), ('和平', 810313), ('提出', 807598), ('提交', 802754), ('继续', 799357), ('目标', 793211), ('法律', 793062), ('保护', 787280), ('11', 780817), ('技术', 778459), ('需要', 772308), ('持续', 758377), ('政策', 755385), ('个', 754029), ('条', 752230), ('采取', 742888), ('于', 732300), ('时', 731282), ('他', 730046), ('缔约国', 725447), ('影响', 725020), ('措施', 723703), ('各', 720751), ('没有', 702370), ('相关', 692317), ('必须', 690245), ('to', 688448), ('主席', 687288), ('审议', 682829), ('但', 679368), ('管理', 677631), ('注意', 674292), ('草案', 672189), ('能力', 670580), ('可能', 666815), ('努力', 654275), ('行为', 641225), ('议程', 638565), ('已', 637477), ('要求', 636861), ('资源', 634984), ('服务', 634608), ('文件', 633780), (':', 633496), ('先生', 629179), ('开展', 625591), ('·', 620548), ('新', 619380), ('系统', 618008), ('由', 616662), ('信息', 613578), ('本', 611177), ('使', 605772), ('实现', 603802), ('计划', 603552), ('使用', 593867), ('期间', 593816), ('各国', 591530), ('作为', 588333), ('举行', 585252), ('全球', 580793), ('实施', 580553), ('成员', 578313), ('任何', 574924), ('审查', 573673), ('认为', 571338), ('都', 567766)]

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import pickle
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from string import punctuation, digits
from itertools import chain

# ========== 配置区 ==========
# 取每种语言的前 N 个高频词
TOP_N = 50

# 在这里指定每种语言所用的字体文件路径，示例中只是占位，
# 请根据你系统中字体文件实际位置修改：
FONT_PATHS = {
    'zh': r'C:\WINDOWS\FONTS\SIMHEI.TTF',     # 宋体/雅黑等
    'en': r'C:\WINDOWS\FONTS\ARIAL.TTF',
    'de': r'C:\WINDOWS\FONTS\ARIAL.TTF',
    'fr': r'C:\WINDOWS\FONTS\ARIAL.TTF',
    'es': r'C:\WINDOWS\FONTS\ARIAL.TTF',
    'ru': r'C:\WINDOWS\FONTS\ARIAL.TTF',
    'ar': r'D:\ae_AlMothnna Bold.ttf',
    # …如果有其它语言，继续添加
}

# 如果某个语言没有指定或字体文件不存在，就用这个默认字体
DEFAULT_FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'

# 输出目录
OUTPUT_DIR = 'figures'
# =============================

def get_font(lang_code):
    """根据语言代码返回 FontProperties，找不到文件就用默认并打印警告。"""
    path = FONT_PATHS.get(lang_code, DEFAULT_FONT)
    if not os.path.exists(path):
        print(f'Warning: 字体文件不存在 `{path}`，{lang_code} 使用默认字体。')
        path = DEFAULT_FONT
    return FontProperties(fname=path)

def plot_top_words(data_dict, top_n=TOP_N, out_dir=OUTPUT_DIR):
    os.makedirs(out_dir, exist_ok=True)
    # for lang in ['zh']:
        # freq_map:dict = data_dict[lang]
        # 取排序后的前 top_n 个
    for lang, freq_map in data_dict.items():
        freq_map.pop(" ", None)
        freq_map.pop("。", None)
        freq_map.pop("，", None)
        freq_map.pop("/", None)
        freq_map.pop("\\", None)
        freq_map.pop("（", None)
        freq_map.pop("）", None)
        freq_map.pop("、", None)
        freq_map.pop("；", None)
        freq_map.pop("：", None)
        freq_map.pop("《", None)
        freq_map.pop("》", None)
        freq_map.pop("=", None)
        freq_map.pop("“", None)
        freq_map.pop("”", None)
        freq_map.pop("-", None)
        freq_map.pop("—", None)
        freq_map.pop("——", None)
        freq_map.pop("–", None)
        for p in chain(digits, punctuation):
            freq_map.pop(p, None)

        top_items = sorted(freq_map.items(), key=lambda x: x[1], reverse=True)[:top_n]
        if not top_items:
            continue
        print(top_items)
        words, counts = zip(*top_items)
        
        fp = get_font(lang)
        plt.figure(figsize=(10, 6))
        plt.bar(range(len(words)), counts)
        plt.xticks(
            ticks=range(len(words)),
            labels=words,
            rotation=60,
            ha='right',
            fontproperties=fp
        )
        plt.title(f'Top {top_n} words in {lang}', fontproperties=fp, fontsize=16)
        plt.ylabel('Frequency')
        plt.tight_layout()
        
        out_path = os.path.join(out_dir, f'top_{lang}.pdf')
        plt.savefig(out_path, format="pdf")
        plt.close()
        print(f'✅ 已保存: {out_path}')

if __name__ == '__main__':
    # 1. 读取 pickle
    with open("每种语言的词汇_总数.pkl", "rb") as f:
        data = pickle.load(f)
    print("找到语言：", list(data.keys()))
    
    # 2. 画图并保存
    plot_top_words(data)
