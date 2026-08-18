
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"d:\yys\新程序\主程序")
from PyQt5.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
class FakeStore:
    def save(self, task): self.saved = task; return True
class FakeBridge:
    def __init__(self):
        self._store = FakeStore()
        self.current_game = "yys"
        self._assets_dir = r"d:\yys\_tmp_assets"
        os.makedirs(self._assets_dir, exist_ok=True)
        self._saved_global = None
    def get_ocr(self): return None
    def capture_screen(self): return None
    def icon_items(self, game_id=None): return ["btn_ok"]
    def scene_list(self): return [{"id": "scene_courtyard", "name": "庭院"}]
    def ocr_items(self, game_id=None): return ["ocr_gold"]
    def signal_options(self): return [("sig_a", "信号A")]
    def compound_list(self, game_id=None): return []
    def load_compound(self, name, game_id=None): return None
    def save_compound(self, node_def, game_id=None): pass
    def global_task_load(self): return {}
    def global_task_save(self, task): self._saved_global = task; return True
    def load_task(self, name):
        return {"name": name, "game": "yys", "kind": "task", "nodes": [
            {"id": "n1", "type": "scene_judge", "name": "场景判定", "params": {}, "pos": [0, 0]}], "edges": []}
from ui.visual_builder.visual_builder_panel import VisualBuilderPanel
fb = FakeBridge()
p = VisualBuilderPanel(fb)
print("panel ok", flush=True)
p._save_global_task()
print("save ok saved=", fb._saved_global is not None, flush=True)
p.open_task_and_select("t1", "n1")
print("open ok hl=", p._canvas._hl_node_id, flush=True)
