import cv2
import numpy as np
import re
import os
from typing import Dict, List, Tuple
from paddleocr import PaddleOCR

# ==========================================
# 🔧 1. 配置层 (Configuration Layer)
# ==========================================
class RegionConfig:
    """管理截图区域坐标。使用相对比例(0.0~1.0)，自动适配任意分辨率。"""
    def __init__(self):
        # ✅ 已根据调试图校准：
        # player_list: y_end 从 0.58 -> 0.85 (覆盖到底部玩家)
        # info_panel:  y_end 从 0.62 -> 0.72 (多留一行余量)
        # loot_panel:  x_end 从 0.98 -> 1.00, y_end 从 0.62 -> 0.90 (覆盖右下角估价)
        self.regions = {
            "player_list": (0.010, 0.08, 0.24, 0.85),   # 左侧：宽一点，深到底
            "info_panel":  (0.250, 0.08, 0.580, 0.72),  # 中部：高一点，防漏行
            "loot_panel":  (0.600, 0.08, 1.000, 0.90),  # 右侧：拉满右边，深到估价
            "bottom_bar":  (0.000, 0.88, 1.000, 0.98)   # 底部：专门抓预估价
        }

    def get_abs_coords(self, img_shape: Tuple[int, int], region_name: str) -> Tuple[int, int, int, int]:
        h, w = img_shape[:2]
        x1_r, y1_r, x2_r, y2_r = self.regions[region_name]
        return (int(x1_r * w), int(y1_r * h), int(x2_r * w), int(y2_r * h))

    def update_region(self, name: str, ratios: Tuple[float, float, float, float]):
        self.regions[name] = ratios


# ==========================================
# 🧩 2. 解析层 (Parser Layer)
# ==========================================
class BaseParser:
    def parse(self, text_lines: List[str]) -> Dict:
        raise NotImplementedError("子类必须实现 parse 方法")

class InfoPanelParser(BaseParser):
    """中部信息面板解析器"""
    def __init__(self):
        self.patterns = {
            "round_num": re.compile(r"第\s*(\d+)\s*轮"),
            "total_count": re.compile(r"总藏品数量.*?(\d+).*?件"),
            "avg_grid_o": re.compile(r"橙色.*?平均格数.*?([\d.]+)\s*格"),
            "avg_grid_p": re.compile(r"紫色.*?平均格数.*?([\d.]+)\s*格"),
            "avg_grid_b": re.compile(r"蓝色.*?平均格数.*?([\d.]+)\s*格"),
            "purple_value": re.compile(r"紫色.*?平均价值.*?(\d+)"),
        }

    def parse(self, text_lines: List[str]) -> Dict:
        full_text = " ".join(text_lines)
        result = {}
        for key, pattern in self.patterns.items():
            match = pattern.search(full_text)
            if match:
                result[key] = match.group(1)
            elif key == "avg_grid_b":
                for line in text_lines:
                    if "蓝色" in line and "格" in line:
                        nums = re.findall(r"([\d.]+)\s*格", line)
                        if nums:
                            result[key] = nums[-1]
                            break
        return result

class PlayerListParser(BaseParser):
    """左侧玩家列表解析器"""
    def __init__(self):
        self.slot_pattern = re.compile(r"(\d)\s*巅峰收藏家")
        self.bid_pattern = re.compile(r"([\d,]+\.?\d*)\s*([Kk]?)")

    def parse(self, text_lines: List[str]) -> Dict:
        players = {}
        current_slot = None
        for line in text_lines:
            slot_m = self.slot_pattern.search(line)
            if slot_m:
                current_slot = f"slot_{slot_m.group(1)}"
                players[current_slot] = {"name": "", "bids": []}
                continue
            if not current_slot:
                continue

            if not players[current_slot]["name"]:
                name_clean = re.sub(r"[^\u4e00-\u9fa5a-zA-Z·]", "", line)
                if 2 <= len(name_clean) <= 8:
                    players[current_slot]["name"] = name_clean
                    continue

            for amount, unit in self.bid_pattern.findall(line):
                if len(amount) < 2: continue
                val = amount.replace(",", "")
                if unit.upper() == "K": val = str(int(float(val) * 1000))
                players[current_slot]["bids"].append(val)
        return players

class LootPanelParser(BaseParser):
    """右侧战利品解析器"""
    def __init__(self):
        self.price_pattern = re.compile(r"当前预估最低价格[:：]\s*([\d,]+)")

    def parse(self, text_lines: List[str]) -> Dict:
        full_text = " ".join(text_lines)
        result = {}
        match = self.price_pattern.search(full_text)
        if match:
            result["estimated_value"] = match.group(1).replace(",", "")
        return result


# ==========================================
# ⚙️ 3. 核心引擎 (Core Engine)
# ==========================================
class GameScreenAnalyzer:
    def __init__(self, use_gpu: bool = True, debug: bool = False):
        self.debug = debug
        if self.debug:
            os.makedirs("debug_crops", exist_ok=True)
            
        self.ocr = PaddleOCR(
            use_angle_cls=True, lang="ch", use_gpu=use_gpu,
            show_log=False, det_db_thresh=0.3, det_db_box_thresh=0.4
        )
        
        self.config = RegionConfig()
        self.parsers: Dict[str, BaseParser] = {
            "info_panel": InfoPanelParser(),
            "player_list": PlayerListParser(),
            "loot_panel": LootPanelParser(),
        }

    def _crop_and_ocr(self, img: np.ndarray, region_name: str) -> List[str]:
        x1, y1, x2, y2 = self.config.get_abs_coords(img.shape, region_name)
        roi = img[y1:y2, x1:x2]
        
        if self.debug:
            cv2.imwrite(f"debug_crops/{region_name}.jpg", roi)
            
        result = self.ocr.ocr(roi, cls=True)
        return [line[1][0] for line in result[0]] if result and result[0] else []

    def analyze(self, img_path: str) -> Dict:
        img = cv2.imread(img_path)
        if img is None:
            raise FileNotFoundError(f"无法读取图片: {img_path}")

        h, w = img.shape[:2]
        print(f"📐 分辨率: {w}x{h} | 模式: {'DEBUG' if self.debug else 'RELEASE'}")

        final_result = {"resolution": f"{w}x{h}", "regions": {}}
        
        for region_name in ["info_panel", "player_list", "loot_panel"]:
            if region_name not in self.parsers:
                continue
                
            texts = self._crop_and_ocr(img, region_name)
            parsed_data = self.parsers[region_name].parse(texts)
            final_result["regions"][region_name] = parsed_data
            
            if parsed_data:
                for k, v in parsed_data.items():
                    print(f"  ✅ {region_name}.{k}: {v}")

        if self.debug:
            self._save_debug_overlay(img, w, h)
            
        return final_result

    def _save_debug_overlay(self, img: np.ndarray, w: int, h: int):
        overlay = img.copy()
        for name, (x1_r, y1_r, x2_r, y2_r) in self.config.regions.items():
            x1, y1 = int(x1_r * w), int(y1_r * h)
            x2, y2 = int(x2_r * w), int(y2_r * h)
            color = (0, 255, 0) if name != "bottom_bar" else (255, 0, 0)
            cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 3)
            cv2.putText(overlay, name, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        cv2.imwrite("debug_crops/overlay_regions.jpg", overlay)
        print("💡 调试图已保存至 debug_crops/overlay_regions.jpg")


# ==========================================
# 🚀 4. 入口与测试
# ==========================================
if __name__ == "__main__":
    import sys
    import json

    analyzer = GameScreenAnalyzer(use_gpu=True, debug=True)

    try:
        if len(sys.argv) > 1:
            target = sys.argv[1]
            print(f"🚀 开始分析: {target}\n" + "="*40)
            res = analyzer.analyze(target)
            print("\n" + "="*40 + "📊 结构化结果:")
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print("用法: python src/auto_reader.py ./data/test1.jpg")
    except Exception as e:
        print(f"❌ 运行失败: {e}")
        import traceback
        traceback.print_exc()