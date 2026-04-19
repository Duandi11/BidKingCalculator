from typing import Dict, Any, List
from .models import SolverConstraints, PriceAvgClue

class OcrToClueAdapter:
    """
    适配层：负责将 OCR 感知层提取到的非结构化/半结构化字典数据，
    清洗并转换为底层求解器可以理解的严格数据模型（SolverConstraints）。
    """
    def __init__(self, grid_size_options_by_grade: Dict[int, List[int]]):
        self.grid_opts = grid_size_options_by_grade

    def build_constraints(self, raw_ocr_data: Dict[str, Any]) -> SolverConstraints:
        regions = raw_ocr_data.get("regions", {})
        info = regions.get("info_panel", {})
        
        # 提取关键总数约束
        total_count_str = info.get("total_count")
        if not total_count_str:
            raise ValueError("OCR未识别到总数量(total_count)，无法进行求解。")
            
        total_count = int(total_count_str)
        if total_count <= 0:
            raise ValueError("识别到的总数量不能小于或等于0。")

        # 提取平均格数（可为空）
        avg_grid_o_str = info.get("avg_grid_o")
        avg_grid_p_str = info.get("avg_grid_p")
        avg_grid_b_str = info.get("avg_grid_b")
        purple_value_str = info.get("purple_value")
        
        avg_grid_o = float(avg_grid_o_str) if avg_grid_o_str else None
        avg_grid_p = float(avg_grid_p_str) if avg_grid_p_str else None
        avg_grid_b = float(avg_grid_b_str) if avg_grid_b_str else None
        purple_value = float(purple_value_str) if purple_value_str else None

        # 构建均价线索约束
        price_clues = []
        if purple_value:
            # 默认假设为紫色(grade=4)的均价
            price_clues.append(PriceAvgClue(grade=4, avg_price=purple_value, exact_reachable=False))

        # 组装返回最终的求解约束模型
        constraints = SolverConstraints(
            total_count=total_count,
            gw_count=None,
            avg_grid_o=avg_grid_o,
            avg_grid_p=avg_grid_p,
            avg_grid_b=avg_grid_b,
            grid_size_options_by_grade=self.grid_opts,
            price_avg_clues=price_clues,
            avg_grid_half_tolerance=0.2  # 适度放宽容差防止OCR截断或游戏四舍五入导致无解
        )

        return constraints
