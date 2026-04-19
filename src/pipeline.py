import time
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from .models import SolverConstraints, SimulationResult, CountCombination

# 初始化基础日志配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Pipeline")
from .auto_reader import GameScreenAnalyzer
from .clue_adapter import OcrToClueAdapter
from .solver import solve_valid_combinations
from .simulator import run_monte_carlo
from .data_loader import load_price_pools, load_grid_size_options_by_grade

@dataclass
class PipelineResult:
    """流水线执行结果包，向顶层业务屏蔽内部细节"""
    success: bool
    raw_ocr_data: Optional[Dict[str, Any]] = None
    constraints: Optional[SolverConstraints] = None
    valid_combos: Optional[list[CountCombination]] = None
    simulation: Optional[SimulationResult] = None
    error_message: Optional[str] = None


class BidEvaluationPipeline:
    """
    调度层：负责编排 OCR感知 -> 数据防呆转换 -> 数学求解 -> 蒙特卡洛模拟 这四个步骤
    外部只需要调用 run_image_eval 方法
    """
    def __init__(self, data_dir: str = "./data", use_gpu: bool = True, debug_ocr: bool = False):
        # 1. 预加载所有静态词典依赖，避免频繁IO
        self.price_pools = load_price_pools(data_dir)
        self.grid_opts = load_grid_size_options_by_grade(data_dir)
        
        # 2. 实例化感知引擎
        self.analyzer = GameScreenAnalyzer(use_gpu=use_gpu, debug=debug_ocr)
        
        # 3. 实例化适配器层
        self.adapter = OcrToClueAdapter(self.grid_opts)

    def run_image_eval(self, image_path: str, num_samples: int = 10000) -> PipelineResult:
        """执行完整的端到端估值流水线"""
        try:
            total_start = time.perf_counter()
            logger.info(f"=========== 开始执行估值流水线 ===========")
            logger.info(f"目标图像: {image_path}")

            # Step 1: 感知识别 (读图，返回字典)
            logger.info("[1/4] 🟢 正在执行 OCR 图像语义感知...")
            t0 = time.perf_counter()
            raw_ocr_data = self.analyzer.analyze(image_path)
            logger.info(f"[1/4] ✅ OCR 识别完毕，耗时: {time.perf_counter() - t0:.3f}秒")
            
            # Step 2: 组装数学约束 (字典 -> SolverConstraints)
            logger.info("[2/4] 🟢 正在构建底层数学求解约束...")
            t0 = time.perf_counter()
            constraints = self.adapter.build_constraints(raw_ocr_data)
            logger.info(f"[2/4] ✅ 约束转换完毕，耗时: {time.perf_counter() - t0:.3f}秒")
            logger.debug(f"[DEBUG] 当前分析目标总数: {constraints.total_count}")
            
            # Step 3: 暴力/剪枝求解合法组合
            logger.info("[3/4] 🟢 正在求解所有可能的藏品组合 (数学推演)...")
            t0 = time.perf_counter()
            valid_combos = solve_valid_combinations(constraints, self.price_pools)
            logger.info(f"[3/4] ✅ 求解完毕！找到 {len(valid_combos)} 种可能组合，耗时: {time.perf_counter() - t0:.3f}秒")
            
            if not valid_combos:
                logger.warning("⚠️ 警告：当前约束未能找到任何合法的组合！")
                return PipelineResult(
                    success=False,
                    raw_ocr_data=raw_ocr_data,
                    constraints=constraints,
                    error_message="无解: 未能找到符合当前面板数据的任何藏品数量组合。可能是 OCR 识别结果误差或是新盲盒未收录。"
                )

            # Step 4: 蒙特卡洛估值模拟
            logger.info(f"[4/4] 🟢 正在进行随机游走/蒙特卡洛模型估值 (采样样本:{num_samples})...")
            t0 = time.perf_counter()
            sim_result = run_monte_carlo(valid_combos, self.price_pools, num_samples=num_samples)
            logger.info(f"[4/4] ✅ 估值计算完毕！耗时: {time.perf_counter() - t0:.3f}秒")
            
            total_time = time.perf_counter() - total_start
            logger.info(f"🎉 流水线执行成功，总耗时: {total_time:.3f}秒")
            logger.info(f"==========================================")
            
            # 全流程成功结束
            return PipelineResult(
                success=True,
                raw_ocr_data=raw_ocr_data,
                constraints=constraints,
                valid_combos=valid_combos,
                simulation=sim_result
            )
            
        except ValueError as ve:
            # 主要用于捕捉适配器主动抛出的业务规则错误 (例如没识别到总数)
            return PipelineResult(success=False, error_message=f"数据解析受阻: {str(ve)}")
        except Exception as e:
            # 灾难级异常捕获
            import traceback
            traceback.print_exc()
            return PipelineResult(success=False, error_message=f"执行异常: {str(e)}")

# ==============================================================
#  可以直接作为独立测试脚本运行流水线
# ==============================================================
if __name__ == "__main__":
    import sys
    # 为了防止命令行运行不显示 INFO 级别以上的 log
    logging.getLogger("Pipeline").setLevel(logging.INFO)

    pipeline = BidEvaluationPipeline(use_gpu=True, debug_ocr=False)
    img_target = sys.argv[1] if len(sys.argv) > 1 else "./data/test1.jpg"
    print(f"🚀 开始执行端到端 Pipeline: {img_target}\n" + "="*40)
    
    result = pipeline.run_image_eval(img_target)
    
    if result.success:
        print("✅ 求解与估值成功！")
        print(f"  有效组合数: {len(result.valid_combos)}")
        print(f"  👉 期望估值 (Expected): {result.simulation.expected_value:,.0f}")
        print(f"  👉 95%安全出价 (Safe) : {result.simulation.safe_bid_95:,.0f}")
        print(f"  👉 悲观保底价 (Pessim.): {result.simulation.pessimistic_bid:,.0f}")
        print(f"  👉 理论最高价 (Max)   : {result.simulation.max_value:,.0f}")
    else:
        print(f"❌ 管道执行失败: {result.error_message}")