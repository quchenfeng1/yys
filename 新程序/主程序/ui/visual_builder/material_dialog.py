"""
17-可视化构建模块：素材管理弹窗（MaterialManagerDialog，2026-08-15）。

左右双 Tab 结构（左=全局库 / 右=本任务库，三分类同列）：
- 「场景识别素材」：示教保存的场景特征组（区域+标志，判断页面）
- 「操作识别素材」：右键红框保存的遮罩图标（页面中定位图标）；只有红框=随机点击素材
- 「OCR识别素材」：右键蓝框保存的 红框区域+蓝框遮罩+黄框文字位置

左右 Tab 联动：点左侧某个分类，右侧自动切到同一分类。
左侧右键 → 加入本任务；右侧选中 → 移除。
只有加入任务素材库的素材才出现在各节点下拉。
"""
from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QHBoxLayout, QListWidget, QListWidgetItem,
                             QMenu, QPushButton, QSplitter, QTabWidget,
                             QVBoxLayout, QWidget)


def _display_name(rel: str) -> str:
    """素材条目显示名：条目 json → 条目名（中文可见，去后缀）"""
    stem = Path(rel).stem
    return stem or rel


# 三个分类的 key：scene / element / ocr
_CATEGORIES = (("scene", "场景识别素材"), ("element", "操作识别素材"),
               ("ocr", "OCR识别素材"))


class MaterialManagerDialog(QDialog):
    """素材管理：左=全局库（三 Tab），右=本任务库（三 Tab，随左侧联动）"""

    def __init__(self, global_elements: list[str],
                 global_scenes: list[dict],          # [{id, name}]
                 task_scenes: list[str],
                 task_elements: list[str],
                 global_ocr: list[str] | None = None,
                 task_ocr: list[str] | None = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("📚 素材管理")
        self.resize(780, 500)
        self._global_elements = list(global_elements)
        self._global_scenes = list(global_scenes)
        self._global_ocr = list(global_ocr or [])
        self._task_scenes = list(task_scenes)
        self._task_elements = list(task_elements)
        self._task_ocr = list(task_ocr or [])

        root = QVBoxLayout(self)

        # ══ 左：全局库（三 Tab）════════════════════════════
        self._left_tabs = QTabWidget()
        self._global_lists: dict[str, QListWidget] = {}
        for key, title in _CATEGORIES:
            lst = QListWidget()
            lst.setContextMenuPolicy(Qt.CustomContextMenu)
            lst.customContextMenuRequested.connect(
                lambda pos, k=key, l=lst: self._menu_add(pos, l, k))
            lst.setToolTip(f"右键 → 加入本任务（{title}）")
            self._global_lists[key] = lst
            self._left_tabs.addTab(lst, title)
        # 左 Tab 切换 → 右侧自动跟随同一分类
        self._left_tabs.currentChanged.connect(
            lambda idx: self._right_tabs.setCurrentIndex(idx))

        # ══ 右：本任务库（三 Tab）════════════════════════════
        self._right_tabs = QTabWidget()
        self._task_lists: dict[str, QListWidget] = {}
        for key, title in _CATEGORIES:
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.setContentsMargins(4, 4, 4, 4)
            lst = QListWidget()
            lst.setToolTip("选中后点【移除】")
            self._task_lists[key] = lst
            lay.addWidget(lst, 1)
            btn = QPushButton(f"🗑 移除所选{title}")
            btn.clicked.connect(lambda _, k=key: self._remove_task(k))
            lay.addWidget(btn)
            self._right_tabs.addTab(page, title)

        body = QSplitter(Qt.Horizontal)
        body.addWidget(self._left_tabs)
        body.addWidget(self._right_tabs)
        body.setSizes([380, 380])
        root.addWidget(body, 1)

        # 底部：确定 / 取消（必须点【确定】才会写回任务素材库）
        btns = QHBoxLayout()
        btns.addStretch(1)
        ok_btn = QPushButton("✔ 确定")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        root.addLayout(btns)

        self._refresh_all()

    # ── 数据访问 ─────────────────────────────────────────
    def _task_of(self, key: str) -> list:
        return {"scene": self._task_scenes,
                "element": self._task_elements,
                "ocr": self._task_ocr}[key]

    def _scene_name(self, sid: str) -> str:
        return next((s.get("name", sid) for s in self._global_scenes
                     if s.get("id") == sid), sid)

    # ── 列表填充 ─────────────────────────────────────────
    def _refresh_all(self) -> None:
        # 全局：场景
        lst = self._global_lists["scene"]
        lst.clear()
        for s in self._global_scenes:
            sid = s.get("id", "")
            mark = " ✓已加入" if sid in self._task_scenes else ""
            it = QListWidgetItem(f"{s.get('name', sid)}（{sid}）{mark}")
            it.setData(Qt.UserRole, sid)
            lst.addItem(it)
        # 全局：图标
        lst = self._global_lists["element"]
        lst.clear()
        for e in sorted(self._global_elements):
            mark = " ✓已加入" if e in self._task_elements else ""
            it = QListWidgetItem(f"{_display_name(e)}{mark}")
            it.setData(Qt.UserRole, e)
            lst.addItem(it)
        # 全局：OCR
        lst = self._global_lists["ocr"]
        lst.clear()
        for e in sorted(self._global_ocr):
            mark = " ✓已加入" if e in self._task_ocr else ""
            it = QListWidgetItem(f"{_display_name(e)}{mark}")
            it.setData(Qt.UserRole, e)
            lst.addItem(it)
        # 本任务：三分类
        for key, _ in _CATEGORIES:
            lst = self._task_lists[key]
            lst.clear()
            for v in self._task_of(key):
                disp = self._scene_name(v) if key == "scene" \
                    else _display_name(v)
                it = QListWidgetItem(
                    f"{disp}（{v}）" if key == "scene" else disp)
                it.setData(Qt.UserRole, v)
                lst.addItem(it)

    # ── 左：右键加入 ─────────────────────────────────────
    def _menu_add(self, pos, lst: QListWidget, kind: str) -> None:
        item = lst.itemAt(pos)
        if item is None:
            return
        value = item.data(Qt.UserRole)
        if not value:
            return
        title = dict(_CATEGORIES)[kind]
        menu = QMenu(self)
        act = menu.addAction(f"➕ 加入本任务{title}")
        act.triggered.connect(lambda: self._add_to_task(kind, value))
        menu.exec_(lst.mapToGlobal(pos))

    def _add_to_task(self, kind: str, value: str) -> None:
        target = self._task_of(kind)
        if value in target:
            return
        target.append(value)
        self._refresh_all()

    # ── 右：移除 ─────────────────────────────────────────
    def _remove_task(self, kind: str) -> None:
        lst = self._task_lists[kind]
        item = lst.currentItem()
        if item is None:
            return
        v = item.data(Qt.UserRole)
        target = self._task_of(kind)
        if v in target:
            target.remove(v)
        self._refresh_all()

    # ── 结果 ─────────────────────────────────────────────
    def result_materials(self) -> dict:
        return {"scenes": list(self._task_scenes),
                "elements": list(self._task_elements),
                "ocr": list(self._task_ocr)}
