
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"d:\yys\新程序\主程序")
from PyQt5.QtWidgets import QApplication
app = QApplication([])
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
from ui.visual_builder.visual_builder_panel import VisualBuilderPanel
fb = FakeBridge()
p = VisualBuilderPanel(fb)
print("panel ok", flush=True)
t = p._global_canvas.export_task({})
print("export ok nodes=", len(t.get("graph", {}).get("nodes", [])), flush=True)
