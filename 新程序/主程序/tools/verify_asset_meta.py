"""端到端验证：图片素材标签系统（标签/描述/文件名，assets/manifest.json）。

验证点：
  1. AssetMetaStore：预设标签、标签增删、图片元数据读写、持久化（重载）
  2. find_by_tag 按标签查找
  3. UI：AddAssetDialog 无标签禁止保存；设置文件名/描述/标签
  4. ImageManagerPanel 列表显示元数据 + 标签筛选
  5. TagManagerDialog 标签管理（新增/删除）
"""
import sys, os, tempfile, shutil
from pathlib import Path

import numpy as np
import cv2

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from PyQt5.QtWidgets import QApplication


def main():
    app = QApplication(sys.argv)
    ok, fail = 0, 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"✅ {name}")
        else:
            fail += 1
            print(f"❌ {name}  {detail}")

    # ════════════ 0. 临时目录 ════════════
    tmp = Path(tempfile.mkdtemp(prefix="meta_"))
    (tmp / "scene").mkdir(parents=True, exist_ok=True)
    (tmp / "tasks" / "_shared").mkdir(parents=True, exist_ok=True)
    # 源图片
    src = tmp / "源图.png"
    cv2.imwrite(str(src), np.full((60, 120, 3), 150, dtype=np.uint8))

    # ════════════ 1. AssetMetaStore ════════════
    print("\n── [1/5] AssetMetaStore 元数据存储 ──")
    from core.asset_meta import AssetMetaStore, DEFAULT_TAGS
    meta = AssetMetaStore(tmp)
    tags = meta.get_all_tags()
    check("预设标签含 按钮/主界面/弹窗/背景图",
          set(tags) >= {"按钮", "主界面", "弹窗", "背景图"}, str(tags))
    ok_add = meta.add_tag("挑战按钮")
    check("add_tag 新增成功", ok_add and "挑战按钮" in meta.get_all_tags())
    check("add_tag 去重", not meta.add_tag("挑战按钮"))

    # 设置图片元数据
    meta.set_image_meta("scene/主界面.png", ["主界面", "背景图"],
                        "主界面识别图", "主界面.png")
    m = meta.get_image_meta("scene/主界面.png")
    check("set/get 图片元数据", m is not None and m["tags"] == ["主界面", "背景图"]
          and m["description"] == "主界面识别图" and m["file_name"] == "主界面.png",
          str(m))

    # 持久化：重新加载
    meta2 = AssetMetaStore(tmp)
    m2 = meta2.get_image_meta("scene/主界面.png")
    check("持久化重载保留元数据", m2 is not None and m2["tags"] == ["主界面", "背景图"])
    check("持久化重载保留标签", "挑战按钮" in meta2.get_all_tags())

    # 删除标签 → 图片同步移除
    meta2.remove_tag("背景图")
    m3 = meta2.get_image_meta("scene/主界面.png")
    check("删除标签同步移除图片标签", m3["tags"] == ["主界面"], str(m3["tags"]))

    # ════════════ 2. find_by_tag ════════════
    print("\n── [2/5] find_by_tag 按标签查找 ──")
    meta2.set_image_meta("tasks/_shared/开始战斗.png", ["按钮"], "开始战斗按钮", "开始战斗.png")
    found = meta2.find_by_tag("按钮")
    check("find_by_tag(按钮) 找到控制素材",
          len(found) == 1 and found[0]["rel"] == "tasks/_shared/开始战斗.png", str(found))
    found2 = meta2.find_by_tag("主界面")
    check("find_by_tag(主界面) 找到识图素材",
          len(found2) == 1 and found2[0]["rel"] == "scene/主界面.png", str(found2))
    check("find_by_tag 不存在标签 → 空", meta2.find_by_tag("不存在") == [])

    # ════════════ 3. AddAssetDialog 校验 ════════════
    print("\n── [3/5] AddAssetDialog 添加弹窗 ──")
    # monkeypatch 模态框，避免 offscreen 卡死
    from PyQt5.QtWidgets import QMessageBox as _MB
    _MB.warning = staticmethod(lambda *a, **k: None)
    _MB.information = staticmethod(lambda *a, **k: None)
    from ui.panels.image_manager_panel import AddAssetDialog
    from ui.widgets.multi_select_combo import MultiSelectCombo
    dlg = AddAssetDialog(tags=meta2.get_all_tags(), default_name="源图.png")
    check("弹窗标签为多选下拉", isinstance(dlg.tag_combo, MultiSelectCombo))
    check("弹窗无新增标签输入框", not hasattr(dlg, 'ed_new_tag') and not hasattr(dlg, '_add_new_tag'))
    dlg.ed_source.setText(str(src))
    dlg.ed_name.setText("自定义名.png")
    dlg.ed_desc.setText("主界面式神录按钮")
    # 无标签 → 禁止保存
    dlg._on_ok()
    check("无标签时 _on_ok 拒绝", dlg.result() != 1, f"result={dlg.result()}")
    # 通过多选下拉勾选标签
    dlg.tag_combo.set_selected(["按钮"])
    check("多选下拉选中标签", dlg.selected_tags() == ["按钮"], str(dlg.selected_tags()))
    check("文件名/描述取值", dlg.file_name() == "自定义名.png"
          and dlg.description() == "主界面式神录按钮")

    # 识图素材（is_scene）弹窗含信号名字段
    dlg2 = AddAssetDialog(tags=meta2.get_all_tags(), is_scene=True)
    check("识图素材弹窗含信号名字段", hasattr(dlg2, 'ed_signal'))
    dlg2.ed_signal.setText("主界面")
    check("识图素材弹窗 signal_name 取值", dlg2.signal_name() == "主界面")
    dlg3 = AddAssetDialog(tags=meta2.get_all_tags(), is_scene=False)
    check("控制素材弹窗无信号名字段", not hasattr(dlg3, 'ed_signal')
          and dlg3.signal_name() == "")

    # ════════════ 4. ImageManagerPanel 列表 + 标签筛选 ════════════
    print("\n── [4/5] ImageManagerPanel 列表/筛选 ──")
    from ui.panels.image_manager_panel import ImageManagerPanel
    # 与真实目录一致：assets/scene + assets/tasks/_shared（保证 rel 相对 assets 无前缀）
    assets_root = tmp / "assets"
    (assets_root / "scene").mkdir(parents=True, exist_ok=True)
    (assets_root / "tasks" / "_shared").mkdir(parents=True, exist_ok=True)
    panel = ImageManagerPanel()
    panel._assets_dir = assets_root
    from core.asset_catalog import AssetCatalog
    panel._catalog = AssetCatalog(assets_root)
    panel._meta = AssetMetaStore(assets_root)
    # 准备两张图 + 元数据
    cv2.imwrite(str(assets_root / "scene" / "主界面.png"), np.full((80, 80, 3), 30, np.uint8))
    cv2.imwrite(str(assets_root / "tasks" / "_shared" / "开始战斗.png"),
                np.full((80, 80, 3), 90, np.uint8))
    panel._meta.set_image_meta("scene/主界面.png", ["主界面"], "主界面识别图", "主界面.png",
                               signal="主界面")
    panel._meta.set_image_meta("tasks/_shared/开始战斗.png", ["按钮"], "开始战斗按钮", "开始战斗.png")
    panel._refresh()
    check("识图 Tab 列表 1 张", panel.scene_list.count() == 1)
    check("控制 Tab 列表 1 张", panel.control_list.count() == 1)
    # 列表项含描述与标签
    txt = panel.control_list.item(0).text()
    check("列表项含描述+标签", "开始战斗按钮" in txt and "按钮" in txt, txt)
    # 识图列表项含信号名 ⚡
    scene_txt = panel.scene_list.item(0).text()
    check("识图列表项含信号名", "⚡主界面" in scene_txt, scene_txt)
    # 标签筛选：只显示"按钮"
    panel._tag_filter = "按钮"
    panel._refresh()
    check("筛选[按钮] 控制列表 1 张 / 识图 0 张",
          panel.control_list.count() == 1 and panel.scene_list.count() == 0,
          f"control={panel.control_list.count()} scene={panel.scene_list.count()}")
    panel._tag_filter = "🏷 全部标签"
    panel._refresh()
    check("筛选[全部] 恢复", panel.scene_list.count() == 1 and panel.control_list.count() == 1)

    # ════════════ 5. TagManagerDialog ════════════
    print("\n── [5/5] TagManagerDialog 标签管理 ──")
    from ui.panels.image_manager_panel import TagManagerDialog
    tm_dlg = TagManagerDialog(meta=panel._meta)
    check("标签管理列出全部标签", "按钮" in [tm_dlg.tag_list.item(i).text()
                                      for i in range(tm_dlg.tag_list.count())])
    tm_dlg.ed_new.setText("活动标签")
    tm_dlg._add_tag()
    check("标签管理新增标签", "活动标签" in panel._meta.get_all_tags())
    tm_dlg.tag_list.setCurrentRow(0)
    first = tm_dlg.tag_list.currentItem().text()
    tm_dlg._remove_tag()
    check("标签管理删除标签", first not in panel._meta.get_all_tags())

    shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'=' * 46}")
    print(f"🎉 素材标签系统验证 {ok}/{ok + fail} 通过")
    if fail:
        print("存在失败项，请检查。")
        sys.exit(1)


if __name__ == "__main__":
    main()
