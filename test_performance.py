import time
from pathlib import Path

from src.data_loader import load_grid_size_options_by_grade, load_price_pools
from src.models import SolverConstraints
from src.solver import solve_valid_combinations
from src.simulator import run_monte_carlo

def main():
    data_dir = str((Path(__file__).parent / "data").resolve())
    print("正在加载数据...")
    pools = load_price_pools(data_dir)
    grid_size_options = load_grid_size_options_by_grade(data_dir)
    print("数据加载完成。\n")

    # 定义五轮的线索追加过程
    rounds = [
        {
            "name": "第1轮: 仅基础数量和总格数 (总件数20, 总格数38)",
            "constraints": {
                "total_count": 20,
                "global_total_grid": 38,
                "grid_size_options_by_grade": grid_size_options,
                "avg_grid_half_tolerance": 0.2,
            }
        },
        {
            "name": "第2轮: 追加橙色平均格数 3.6",
            "constraints": {
                "total_count": 20,
                "global_total_grid": 38,
                "avg_grid_o": 3.6,
                "grid_size_options_by_grade": grid_size_options,
                "avg_grid_half_tolerance": 0.2,
            }
        },
        {
            "name": "第3轮: 追加紫色平均格数 2.29",
            "constraints": {
                "total_count": 20,
                "global_total_grid": 38,
                "avg_grid_o": 3.6,
                "avg_grid_p": 2.29,
                "grid_size_options_by_grade": grid_size_options,
                "avg_grid_half_tolerance": 0.2,
            }
        },
        {
            "name": "第4轮: 追加蓝色平均格数 1.5",
            "constraints": {
                "total_count": 20,
                "global_total_grid": 38,
                "avg_grid_o": 3.6,
                "avg_grid_p": 2.29,
                "avg_grid_b": 1.50,
                "grid_size_options_by_grade": grid_size_options,
                "avg_grid_half_tolerance": 0.2,
            }
        },
        {
            "name": "第5轮: 追加绿白总件数",
            "constraints": {
                "total_count": 20,
                "global_total_grid": 38,
                "avg_grid_o": 3.6,
                "avg_grid_p": 2.29,
                "avg_grid_b": 1.50,
                "gw_count": 8,  # 假设绿白总数为8
                "grid_size_options_by_grade": grid_size_options,
                "avg_grid_half_tolerance": 0.2,
            }
        }
    ]

    total_samples = 1000

    print("开始性能测试...\n")
    
    for i, r in enumerate(rounds):
        print(f"--- {r['name']} ---")
        
        # 1. 求解合法组合
        constraints = SolverConstraints(**r["constraints"])
        sc_start = time.perf_counter()
        valid_combinations = solve_valid_combinations(constraints, pools)
        sc_end = time.perf_counter()
        
        print(f"合法组合数: {len(valid_combinations)}")
        print(f"求解组合耗时: {sc_end - sc_start:.4f}s")
        
        # 2. 如果存在合法组合，运行蒙特卡洛模拟
        if valid_combinations:
            mc_start = time.perf_counter()
            result = run_monte_carlo(
                combinations=valid_combinations,
                price_pools=pools,
                num_samples=total_samples,
                seed=42, # 给定随机数种子以便于复现
                safe_bid_mode="equal",
                safe_bid_confidence_pct=95.0,
                filter_extreme_red=True,
                red_extreme_percentile=95.0,
                max_red_extreme_count=1,
                filter_extreme_orange=True,
                orange_extreme_percentile=95.0,
                max_orange_extreme_count=2,
                use_count_dependency=True,
            )
            mc_end = time.perf_counter()
            print(f"蒙特卡洛估值耗时 ({total_samples} 采样次/组合): {mc_end - mc_start:.4f}s")
            print(f"结果: 期望价值={result.expected_value:.2f}, Safe_Bid_95={result.safe_bid_95:.2f}")
        else:
            print("因无合法组合，跳过模拟。")
            
        print("-" * 40 + "\n")

if __name__ == "__main__":
    main()