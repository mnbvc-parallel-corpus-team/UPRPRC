import matplotlib.pyplot as plt
import math

# 数据
data = {"ar": 160646, "de": 8032, "en": 162306, "es": 160058, "fr": 162071, "ru": 161690, "zh": 162339}
labels = list(data.keys())
sizes = list(data.values())

# 颜色
colors = plt.cm.tab20.colors[:len(labels)]

# 绘制饼图
fig, ax = plt.subplots(figsize=(8, 6))
wedges, _ = ax.pie(
    sizes,
    colors=colors,
    startangle=90,
    labels=None
)
ax.axis('equal')

# 在饼图外侧添加语言与数量的注释
for i, wedge in enumerate(wedges):
    angle = (wedge.theta2 + wedge.theta1) / 2.0
    x = math.cos(math.radians(angle))
    y = math.sin(math.radians(angle))
    ha = 'left' if x >= 0 else 'right'
    ax.text(x * 1.1, y * 1.1, f"{labels[i]}: {sizes[i]}", ha=ha, va='center')

# 英文标题
plt.title("Number of Documents per Language")

plt.tight_layout()
# plt.show()
plt.savefig(__file__.replace(".py",".svg"), format="svg")