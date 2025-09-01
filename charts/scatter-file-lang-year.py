import matplotlib.pyplot as plt
import numpy as np
import matplotlib
import matplotlib as mpl
import random

# 您提供的统计数据
data = {
    # "1974": {"zh": 1}, "1983": {"ar": 1, "de": 1}, "1985": {"es": 18, "fr": 21}, 
    # "1986": {"es": 14, "fr": 6}, "1992": {"ar": 28, "en": 3, "es": 27, "fr": 17, "ru": 3}, 
    # "1993": {"ar": 196, "en": 88, "es": 200, "fr": 121, "ru": 40}, 
    # "1994": {"ar": 8, "en": 10, "es": 11, "fr": 10, "ru": 7}, 
    # "1995": {"ar": 2, "en": 1, "es": 1, "fr": 1, "ru": 2}, 
    # "1996": {"ar": 3, "en": 6, "es": 3, "fr": 4, "ru": 5, "zh": 2}, 
    # "1997": {"ar": 14, "en": 15, "es": 12, "fr": 14, "ru": 14, "zh": 4}, 
    # "1998": {"ar": 35, "en": 34, "es": 35, "fr": 34, "ru": 35, "zh": 36}, 
    # "1999": {"ar": 508, "de": 9, "en": 513, "es": 513, "fr": 515, "ru": 519, "zh": 494}, 
    "2000": {"ar": 7546, "de": 426, "en": 7526, "es": 7516, "fr": 7556, "ru": 7556, "zh": 7447}, 
    "2001": {"ar": 7417, "de": 399, "en": 7350, "es": 7404, "fr": 7408, "ru": 7400, "zh": 7409}, 
    "2002": {"ar": 7837, "de": 502, "en": 7805, "es": 7832, "fr": 7812, "ru": 7848, "zh": 7848}, 
    "2003": {"ar": 7358, "de": 632, "en": 7348, "es": 7346, "fr": 7349, "ru": 7367, "zh": 7383}, 
    "2004": {"ar": 7184, "de": 464, "en": 7195, "es": 7192, "fr": 7192, "ru": 7189, "zh": 7207}, 
    "2005": {"ar": 6881, "de": 442, "en": 6903, "es": 6878, "fr": 6887, "ru": 6889, "zh": 6900}, 
    "2006": {"ar": 7126, "de": 447, "en": 7135, "es": 7114, "fr": 7111, "ru": 7119, "zh": 7148}, 
    "2007": {"ar": 6787, "de": 384, "en": 6819, "es": 6796, "fr": 6811, "ru": 6826, "zh": 6840}, 
    "2008": {"ar": 7087, "de": 353, "en": 7117, "es": 7098, "fr": 7113, "ru": 7088, "zh": 7138}, 
    "2009": {"ar": 6762, "de": 219, "en": 6798, "es": 6802, "fr": 6769, "ru": 6769, "zh": 6843}, 
    "2010": {"ar": 7465, "de": 289, "en": 7553, "es": 7478, "fr": 7535, "ru": 7514, "zh": 7543}, 
    "2011": {"ar": 7626, "de": 547, "en": 7791, "es": 7654, "fr": 7771, "ru": 7774, "zh": 7797}, 
    "2012": {"ar": 7479, "de": 382, "en": 7616, "es": 7481, "fr": 7608, "ru": 7617, "zh": 7626}, 
    "2013": {"ar": 7427, "de": 532, "en": 7608, "es": 7408, "fr": 7538, "ru": 7561, "zh": 7625}, 
    "2014": {"ar": 7305, "de": 328, "en": 7543, "es": 7188, "fr": 7559, "ru": 7473, "zh": 7457}, 
    "2015": {"ar": 3005, "de": 279, "en": 2800, "es": 2483, "fr": 2799, "ru": 2653, "zh": 2842}, 
    "2016": {"ar": 2768, "de": 220, "en": 2885, "es": 2652, "fr": 2969, "ru": 2719, "zh": 2950}, 
    "2017": {"ar": 7397, "de": 214, "en": 7566, "es": 7403, "fr": 7520, "ru": 7542, "zh": 7562}, 
    "2018": {"ar": 6924, "de": 176, "en": 7115, "es": 6925, "fr": 7091, "ru": 7093, "zh": 7103}, 
    "2019": {"ar": 7051, "de": 217, "en": 7187, "es": 7055, "fr": 7158, "ru": 7179, "zh": 7183}, 
    "2020": {"ar": 6165, "de": 195, "en": 6301, "es": 6178, "fr": 6300, "ru": 6281, "zh": 6294}, 
    "2021": {"ar": 6942, "de": 165, "en": 7061, "es": 6974, "fr": 7050, "ru": 7048, "zh": 7070}, 
    "2022": {"ar": 6987, "de": 159, "en": 7172, "es": 7000, "fr": 7069, "ru": 7148, "zh": 7145}, 
    "2023": {"ar": 3323, "de": 51, "en": 3439, "es": 3364, "fr": 3350, "ru": 3409, "zh": 3439}, 
    # "2024": {"ar": 1, "en": 1, "es": 1, "fr": 1, "ru": 1, "zh": 1}, 
    # "2025": {"ar": 1, "en": 2, "es": 2, "fr": 2, "ru": 2, "zh": 2}
}

# 1. 数据处理：计算每种语言的文件总数
languages = set()
for year_data in data.values():
    languages.update(year_data.keys())
languages = sorted(languages)  # 排序语言列表

# 计算每种语言的总文件数
language_totals = {lang: 0 for lang in languages}
for year_data in data.values():
    for lang, count in year_data.items():
        language_totals[lang] += count

# 2. 创建图表
plt.figure(figsize=(16, 10))
ax1 = plt.gca()  # 主坐标轴（左侧Y轴）
ax2 = ax1.twinx()  # 右侧Y轴

# 设置位置和宽度
x_pos = np.arange(len(languages))
bar_width = 0.65

# 绘制条形图（左侧Y轴）
bars = ax1.bar(x_pos, [language_totals[lang] for lang in languages], 
               width=bar_width, color='#1f77b4', alpha=0.7, edgecolor='grey')
ax1.set_xlabel('Languages', fontsize=14, labelpad=15)
ax1.set_ylabel('Total Files (Sum)', fontsize=14, color='#1f77b4')
ax1.tick_params(axis='y', labelcolor='#1f77b4')
ax1.set_title('Language File Statistics by Year (2000-2023)', fontsize=16, pad=20)
ax1.grid(axis='y', linestyle='--', alpha=0.7)

# 3. 准备年份颜色映射
all_years = sorted(data.keys(), key=int)
years_numeric = [int(year) for year in all_years]
norm = mpl.colors.Normalize(vmin=min(years_numeric), vmax=max(years_numeric))
cmap = matplotlib.colormaps.get_cmap('plasma')  # 使用反向的Viridis色图，使早期年份颜色更深

# 4. 绘制散点图（右侧Y轴）
scatter_handles = []
max_scatter_value = 0

for i, lang in enumerate(languages):
    # 收集该语言所有年份的数据
    lang_years = []
    lang_counts = []
    
    for year, year_data in data.items():
        if lang in year_data:
            lang_years.append(int(year))
            lang_counts.append(year_data[lang])
            if year_data[lang] > max_scatter_value:
                max_scatter_value = year_data[lang]
    
    # 为每个点生成颜色
    colors = [cmap(norm(year)) for year in lang_years]
    
    # 在条形宽度内随机分布x坐标
    x_scatter = [x_pos[i] + random.uniform(-bar_width/2.5, bar_width/2.5) 
                 for _ in range(len(lang_years))]
    
    # 绘制散点
    sc = ax2.scatter(x_scatter, lang_counts, c=colors, s=60, 
                    alpha=0.85, edgecolor='white', zorder=5)
    
    # 保存第一个点用于图例
    if lang == languages[0]:
        scatter_handles.append(sc)

# 5. 设置坐标轴
ax1.set_xticks(x_pos)
ax1.set_xticklabels(languages, fontsize=12)

# 设置右侧Y轴范围，确保所有散点可见
ax2.set_ylim(0, max_scatter_value * 1.25)
ax2.set_ylabel('Files per Year', fontsize=14, color='#d62728')
ax2.tick_params(axis='y', labelcolor='#d62728')

# 6. 添加颜色条
cbar = plt.colorbar(mpl.cm.ScalarMappable(norm=norm, cmap=cmap), 
                   ax=ax2, orientation='vertical', pad=0.08)
cbar.set_label('Year', fontsize=12)
cbar.ax.tick_params(labelsize=10)

# 7. 添加图例和注释
plt.figtext(0.5, 0.01, '', 
            ha='center', fontsize=10, color='#555555')

# 8. 调整布局
plt.tight_layout()
plt.subplots_adjust(bottom=0.1)
# plt.show()
plt.savefig(__file__.replace(".py",".svg"), format="svg")