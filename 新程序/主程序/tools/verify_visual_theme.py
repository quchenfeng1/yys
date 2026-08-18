"""验证：节点内嵌控件透明化 + 深色主题（与节点卡片统一）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QImage

app = QApplication(sys.argv)
from ui.visual_builder.graph_canvas import GraphCanvas

c = GraphCanvas()
c.resize(900, 600)
c.show()
node = c.add_node("clicker")
node.set_selected(False)  # 未选中态，body 为纯卡片背景色 (13,18,23)
app.processEvents()

# 1. 属性检查：透明 + 深色 QSS + label 颜色
w = node.get_widget("template")
group = w.widget()
print("[1] 内嵌控件容器属性")
print("  WA_TranslucentBackground:", bool(group.testAttribute(Qt.WA_TranslucentBackground)))
assert group.testAttribute(Qt.WA_TranslucentBackground), "应透明背景"
lab = group.layout().itemAt(0).widget()
print("  label 样式:", lab.styleSheet()[:40])
assert "9aa4b2" in lab.styleSheet(), "label 应为浅灰"
print("  容器 QSS 深色:", "#1b2026" in group.styleSheet())
assert "#1b2026" in group.styleSheet()
print("  ✅ 透明 + 深色 QSS")

# 1.5 列宽检查：属性名列宽一致(80，右对齐) + 输入框列宽一致(150)
print("[1.5] 固定列宽（label=80 / input=170）")
row_ok = True
for name in ("template",):
    w2 = node.get_widget(name)
    if w2 is None:
        continue
    g2 = w2.widget()
    lab2 = g2.layout().itemAt(0).widget()
    inp2 = g2.layout().itemAt(1).widget()
    lw, iw = lab2.width(), inp2.width()
    print(f"  {lab2.text()}: label={lw} input={iw}")
    if lw != 80 or iw != 170:
        row_ok = False
assert row_ok, "列宽不一致"
print("  ✅ 属性名/输入框列宽统一（左右对齐）")

# 1.6 proxy 宽度一致：combo/spinbox/lineedit 的 proxy 都应全宽(246)，
#     而非 NodeGraphQt 默认给 spinbox/lineedit/checkbox 的 140 限制
print("[1.6] proxy 占位宽度一致（应都=246，非 140）")
proxy_ok = True
for n in (node, c.add_node("set_var"), c.add_node("dragger")):
    n.set_selected(False)
    for name in ("var_name", "var_value", "template", "threshold", "timeout"):
        w3 = n.get_widget(name)
        if w3 is None:
            continue
        bw = w3.boundingRect().width()
        if abs(bw - 266) > 2:
            proxy_ok = False
        print(f"  {n.type_.split('.')[-1]:9s} {w3.widget().layout().itemAt(0).widget().text():8s} proxy={bw:.0f}")
assert proxy_ok, "proxy 宽度不一致（可能有 140 限制残留）"
print("  ✅ 所有控件类型 proxy 全宽一致")

# 2. 像素采样：节点区域非白（深色）
view = c._graph.viewer()
scene = view.scene()
node_rect = node.view.sceneBoundingRect()
# 渲染场景区域
img = QImage(int(node_rect.width()), int(node_rect.height()), QImage.Format_RGB888)
img.fill(0xFFFFFF)
from PyQt5.QtCore import QRectF
from PyQt5.QtGui import QImage, QPainter
p = QPainter(img)
scene.render(p, QRectF(img.rect()), node_rect)
p.end()
# 采样几个点（label 区 + 控件区中间偏左）
samples = []
for fx in (0.3, 0.5, 0.7):
    px = int(img.width() * fx)
    py = int(img.height() * 0.5)
    col = img.pixelColor(px, py)
    samples.append((col.red(), col.green(), col.blue()))
print("[2] 节点内嵌区采样（网格，覆盖 label 空白/控件/行间）")
samples = []
for fy in (0.25, 0.5, 0.75):
    py = int(img.height() * fy)
    for fx in (0.08, 0.15, 0.3, 0.5, 0.7, 0.9):
        px = int(img.width() * fx)
        col = img.pixelColor(px, py)
        samples.append((col.red(), col.green(), col.blue()))
# 只列出若干代表点
print("  采样数:", len(samples), "示例:", samples[::4])
# 1) 任何点都不应接近纯白（旧 bug 是整块白色面板）
white_like = [s for s in samples if sum(s) > 640]
print("  近白点数:", len(white_like))
assert not white_like, f"存在近白点: {white_like}"
# 2) 应存在接近节点卡片背景 (13,18,23) 的采样点 —— 证明容器真正透明透出卡片
node_bg = (13, 18, 23)
close = [s for s in samples if sum(abs(a - b) for a, b in zip(s, node_bg)) <= 12]
print("  接近节点背景(13,18,23)的点数:", len(close))
assert close, f"内嵌区应透出节点卡片背景色，采样: {samples}"
print("  ✅ 容器透明，透出节点卡片背景，非白块、无单独灰面板")

# 3. 控件中心颜色：spinbox/lineedit/combo 都应为深色（防 NodeGraphQt
#    自带半透明浅色 QSS 覆盖导致"白色输入框"）
print("[3] 输入控件中心渲染颜色（应深色非浅色）")
from PyQt5.QtWidgets import QGraphicsScene, QGraphicsView
view2 = c._graph.viewer()
scene2 = view2.scene()
node2 = c.add_node("set_var")
node2.set_selected(False)
app.processEvents()
img3 = QImage(int(node2.view.sceneBoundingRect().width()),
              int(node2.view.sceneBoundingRect().height()), QImage.Format_RGB888)
img3.fill(0x000000)
from PyQt5.QtCore import QRectF
p3 = QPainter(img3)
scene2.render(p3, QRectF(img3.rect()), node2.view.sceneBoundingRect())
p3.end()
ctrl_ok = True
for name in ("var_name", "var_value"):
    w4 = node2.get_widget(name)
    g4 = w4.widget()
    inp4 = g4.layout().itemAt(1).widget()
    off = inp4.mapTo(g4, inp4.rect().center())
    gp = w4.mapToScene(off)
    px = int(gp.x() - node2.view.sceneBoundingRect().x())
    py = int(gp.y() - node2.view.sceneBoundingRect().y())
    col = img3.pixelColor(px, py)
    rgb = (col.red(), col.green(), col.blue())
    print(f"  {type(inp4).__name__}: {rgb}")
    if sum(rgb) > 400:  # 浅色(如 137,139,141) → 失败
        ctrl_ok = False
assert ctrl_ok, "输入控件背景应为深色"
print("  ✅ 所有输入控件深色背景")

print("\n🎉 节点内嵌控件主题统一验证通过")
