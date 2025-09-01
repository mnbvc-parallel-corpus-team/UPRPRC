import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

# 数据
data_missing = {
    # "1974": {"ar": 1, "de": 1, "en": 1, "es": 1, "fr": 1, "ru": 1},
    # "1983": {"en": 1, "es": 1, "fr": 1, "ru": 1, "zh": 1},
    # "1985": {"ar": 31, "de": 31, "en": 31, "es": 13, "fr": 10, "ru": 31, "zh": 31},
    # "1986": {"ar": 14, "de": 14, "en": 14, "fr": 8, "ru": 14, "zh": 14},
    # "1992": {"ar": 35, "de": 63, "en": 60, "es": 36, "fr": 46, "ru": 60, "zh": 63},
    # "1993": {"ar": 81, "de": 277, "en": 189, "es": 77, "fr": 156, "ru": 237, "zh": 277},
    # "1994": {"ar": 6, "de": 14, "en": 4, "es": 3, "fr": 4, "ru": 7, "zh": 14},
    # "1995": {"ar": 1, "de": 3, "en": 2, "es": 2, "fr": 2, "ru": 1, "zh": 3},
    # "1996": {"ar": 4, "de": 7, "en": 1, "es": 4, "fr": 3, "ru": 2, "zh": 5},
    # "1997": {"ar": 1, "de": 15, "es": 3, "fr": 1, "ru": 1, "zh": 11},
    # "1998": {"ar": 3, "de": 38, "en": 4, "es": 3, "fr": 4, "ru": 3, "zh": 2},
    # "1999": {"ar": 22, "de": 521, "en": 17, "es": 17, "fr": 15, "ru": 11, "zh": 36},
    "2000": {"ar": 106, "en": 126, "es": 136, "fr": 96, "ru": 96, "zh": 205},
    "2001": {"ar": 66, "en": 133, "es": 79, "fr": 75, "ru": 83, "zh": 74},
    "2002": {"ar": 84, "en": 116, "es": 89, "fr": 109, "ru": 73, "zh": 73},
    "2003": {"ar": 60, "en": 70, "es": 72, "fr": 69, "ru": 51, "zh": 35},
    "2004": {"ar": 69, "en": 58, "es": 61, "fr": 61, "ru": 64, "zh": 46},
    "2005": {"ar": 56, "en": 34, "es": 59, "fr": 50, "ru": 48, "zh": 37},
    "2006": {"ar": 41, "en": 32, "es": 53, "fr": 56, "ru": 48, "zh": 19},
    "2007": {"ar": 72, "en": 40, "es": 63, "fr": 48, "ru": 33, "zh": 19},
    "2008": {"ar": 64, "en": 34, "es": 53, "fr": 38, "ru": 63, "zh": 13},
    "2009": {"ar": 119, "en": 83, "es": 79, "fr": 112, "ru": 112, "zh": 38},
    "2010": {"ar": 130, "en": 42, "es": 117, "fr": 60, "ru": 81, "zh": 52},
    "2011": {"ar": 210, "en": 45, "es": 182, "fr": 65, "ru": 62, "zh": 39},
    "2012": {"ar": 198, "en": 61, "es": 196, "fr": 69, "ru": 60, "zh": 51},
    "2013": {"ar": 217, "en": 36, "es": 236, "fr": 106, "ru": 83, "zh": 19},
    "2014": {"ar": 375, "en": 137, "es": 492, "fr": 121, "ru": 207, "zh": 223},
    "2015": {"ar": 775, "en": 980, "es": 1297, "fr": 981, "ru": 1127, "zh": 938},
    "2016": {"ar": 843, "en": 726, "es": 959, "fr": 642, "ru": 892, "zh": 661},
    "2017": {"ar": 215, "en": 46, "es": 209, "fr": 92, "ru": 70, "zh": 50},
    "2018": {"ar": 213, "en": 22, "es": 212, "fr": 46, "ru": 44, "zh": 34},
    "2019": {"ar": 155, "en": 19, "es": 151, "fr": 48, "ru": 27, "zh": 23},
    "2020": {"ar": 156, "en": 20, "es": 143, "fr": 21, "ru": 40, "zh": 27},
    "2021": {"ar": 159, "en": 40, "es": 127, "fr": 51, "ru": 53, "zh": 31},
    "2022": {"ar": 218, "en": 33, "es": 205, "fr": 136, "ru": 57, "zh": 60},
    "2023": {"ar": 133, "en": 17, "es": 92, "fr": 106, "ru": 47, "zh": 17},
    # "2024": {"de": 1},
    # "2025": {"ar": 1, "de": 2}
}

# 构造 DataFrame
df_missing = pd.DataFrame.from_dict(data_missing, orient='index').sort_index().fillna(0)
langs = ["ar","en","es","fr","ru","zh"]
df_missing = df_missing.reindex(columns=langs, fill_value=0)

# 绘制热力图
fig, ax = plt.subplots(figsize=(14, 8))
c = ax.imshow(df_missing.T, aspect='auto', interpolation='nearest', cmap='viridis')

# 设置坐标与标签
ax.set_xticks(np.arange(len(df_missing.index)))
ax.set_xticklabels(df_missing.index, rotation=90)
ax.set_yticks(np.arange(len(langs)))
ax.set_yticklabels(langs)

# 添加数值注释
for i in range(len(langs)):
    for j in range(len(df_missing.index)):
        val = int(df_missing.iloc[j, i])
        ax.text(j, i, str(val), ha='center', va='center', fontsize=6, color='white' if val > df_missing.values.max()*0.5 else 'black')

# 添加色条
fig.colorbar(c, ax=ax, label='Count of Missing Documents')

ax.set_title('Missing File Counts per Year and Language')
ax.set_xlabel('Year')
ax.set_ylabel('Language')
plt.tight_layout()
# plt.show()
plt.savefig(__file__.replace(".py",".svg"), format="svg")