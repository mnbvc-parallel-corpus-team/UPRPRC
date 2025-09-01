import matplotlib.pyplot as plt

# 数据
data = {
    "1974": 1, "1983": 1, "1985": 31, "1986": 14, "1992": 63, "1993": 277, "1994": 14,
    "1995": 3, "1996": 7, "1997": 15, "1998": 38, "1999": 530, "2000": 7652, "2001": 7483,
    "2002": 7921, "2003": 7418, "2004": 7253, "2005": 6937, "2006": 7167, "2007": 6859,
    "2008": 7151, "2009": 6881, "2010": 7595, "2011": 7836, "2012": 7677, "2013": 7644,
    "2014": 7680, "2015": 3780, "2016": 3611, "2017": 7612, "2018": 7137, "2019": 7206,
    "2020": 6321, "2021": 7101, "2022": 7205, "2023": 3456, "2024": 1, "2025": 2
}

# 按年份排序
years = sorted(data.keys(), key=lambda x: int(x))
counts = [data[year] for year in years]

# 绘制直方图
fig, ax = plt.subplots(figsize=(14, 6))
bars = ax.bar(years, counts)

# 在每个条形顶部标注数量
for bar, count in zip(bars, counts):
    ax.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height(),
        str(count),
        ha='center',
        va='bottom'
    )

# 添加轴标签和标题
ax.set_xlabel('Year')
ax.set_ylabel('Number of Unique Document Symbols')
ax.set_title('Number of Unique Document Symbols per Year')

# 调整 x 轴刻度……让年份显示清晰
plt.xticks(rotation=45)
plt.tight_layout()
# plt.show()
plt.savefig(__file__.replace(".py",".svg"), format="svg")
