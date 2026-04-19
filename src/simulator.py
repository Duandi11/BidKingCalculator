import math
import os
import logging
from typing import Callable, Dict, List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np

from .models import CountCombination, SimulationResult

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Simulator")

# ==========================================
# 🚀 1. 自动设备探测与降级机制
# ==========================================
try:
    import cupy as cp
    HAS_CUDA = True
    logger.info("✅ 检测到 CUDA 环境，已启用 CuPy GPU 加速")
except ImportError:
    import numpy as cp
    HAS_CUDA = False
    logger.info("ℹ️ 使用 CPU 模式 (建议 pip install cupy-cuda12x 开启硬件加速)")

# ==========================================
# 📐 2. 纯数学辅助函数 (跨平台一致)
# ==========================================
GRADE_PRIOR = {1: 32, 2: 32, 3: 16, 4: 8, 5: 2, 6: 1}
_PRIOR_SUM = float(sum(GRADE_PRIOR.values()))
GRADE_PROB = {g: (w / _PRIOR_SUM) for g, w in GRADE_PRIOR.items()}

def _combo_log_weight(combo: CountCombination) -> float:
    by_grade = combo.by_grade()
    n = combo.total
    log_coeff = math.lgamma(n + 1) - sum(math.lgamma(by_grade[g] + 1) for g in by_grade)
    log_prob = sum(by_grade[g] * math.log(GRADE_PROB[g]) for g in by_grade)
    return log_coeff + log_prob

def _weighted_quantile(values: np.ndarray, weights: np.ndarray, quantile: float) -> float:
    """精确加权分位数 (金融级 CPU 计算)"""
    order = np.argsort(values)
    sorted_values = values[order]
    sorted_weights = weights[order]
    cdf = np.cumsum(sorted_weights)
    threshold = quantile * cdf[-1]
    idx = np.searchsorted(cdf, threshold, side="left")
    idx = min(idx, len(sorted_values) - 1)
    return float(sorted_values[idx])

def _inverse_price_probs(pool: np.ndarray) -> np.ndarray:
    prices = pool.astype(np.float64)
    prices = np.where(prices > 0, prices, 1.0)
    inv = 1.0 / prices
    return inv / inv.sum()

# ==========================================
# ⚙️ 3. 核心计算 Worker (支持单线程/多线程)
# ==========================================
def _simulate_worker(
    combos: List[CountCombination],
    weights: np.ndarray,
    price_pools: Dict[int, np.ndarray],
    effective_samples: int,
    tail_quantile: float,
    safe_bid_mode: str,
    equal_weight: float,
    red_thr: float, max_red_ext: int,
    orange_thr: float, max_orange_ext: int,
    filter_red: bool, filter_orange: bool,
    seed_base: int
) -> Dict:
    xp = cp if HAS_CUDA else np
    rng = np.random.default_rng(seed_base)
    
    # 预构建抽样缓存 (grade, count)
    unique_gc = set()
    for c in combos:
        for g, cnt in c.by_grade().items():
            if cnt > 0: unique_gc.add((g, cnt))
            
    gc_cache = {}
    for g, cnt in unique_gc:
        pool = price_pools[g]
        probs = _inverse_price_probs(pool)
        
        # 🔧 核心修复：NumPy RNG 需 CPU 数组，采样后转回 Device
        pool_cpu = cp.asnumpy(pool) if HAS_CUDA else pool
        probs_cpu = cp.asnumpy(probs) if HAS_CUDA else probs
        picks = rng.choice(pool_cpu, size=(effective_samples, cnt), replace=True, p=probs_cpu)
        picks_dev = xp.asarray(picks)
        
        sums = picks_dev.sum(axis=1)
        mask = xp.ones(effective_samples, dtype=bool)
        if g == 6 and filter_red:
            mask &= (picks_dev >= xp.asarray([red_thr])).sum(axis=1) <= max_red_ext
        elif g == 5 and filter_orange:
            mask &= (picks_dev >= xp.asarray([orange_thr])).sum(axis=1) <= max_orange_ext
        gc_cache[(g, cnt)] = (sums, mask)

    n = len(combos)
    means = xp.empty(n, dtype=xp.float64)
    safe_qs = xp.empty(n, dtype=xp.float64)
    pess_qs = xp.empty(n, dtype=xp.float64)
    theo_maxs = xp.empty(n, dtype=xp.float64)
    
    all_vals = [None] * n
    all_wts = [None] * n

    for idx, combo in enumerate(combos):
        totals = xp.zeros(effective_samples, dtype=xp.float64)
        valid_mask = xp.ones(effective_samples, dtype=bool)
        theoretical_max = 0
        by_grade = combo.by_grade()

        for g, c in by_grade.items():
            if c == 0: continue
            sums, mask = gc_cache[(g, c)]
            totals += sums
            valid_mask &= mask
            theoretical_max += int(price_pools[g].max()) * c

        used = totals[valid_mask]
        if used.size == 0: used = totals
        
        # 分位数回退 CPU 保证精度
        used_cpu = cp.asnumpy(used) if HAS_CUDA else used
        means[idx] = used_cpu.mean()
        safe_qs[idx] = np.quantile(used_cpu, tail_quantile)
        pess_qs[idx] = np.quantile(used_cpu, 0.01)
        theo_maxs[idx] = theoretical_max
        
        w = weights[idx] if safe_bid_mode == "prior" else equal_weight
        all_vals[idx] = used_cpu
        all_wts[idx] = np.full(used_cpu.size, w / used_cpu.size, dtype=np.float64)

    if HAS_CUDA:
        cp.get_default_memory_pool().free_all_blocks()
        
    return {
        "means": cp.asnumpy(means) if HAS_CUDA else means,
        "safe_qs": cp.asnumpy(safe_qs) if HAS_CUDA else safe_qs,
        "pess_qs": cp.asnumpy(pess_qs) if HAS_CUDA else pess_qs,
        "theo_maxs": cp.asnumpy(theo_maxs) if HAS_CUDA else theo_maxs,
        "all_vals": all_vals,
        "all_wts": all_wts
    }

# ==========================================
# 🌐 4. 智能调度器 (自适应并行 + 降采样)
# ==========================================
def run_monte_carlo(
    combinations: List[CountCombination],
    price_pools: Dict[int, np.ndarray],
    num_samples: int = 10_000,
    seed: int | None = None,
    safe_bid_mode: str = "equal",
    safe_bid_confidence_pct: float = 95.0,
    filter_extreme_red: bool = False,
    red_extreme_percentile: float = 95.0,
    max_red_extreme_count: int = 1,
    filter_extreme_orange: bool = False,
    orange_extreme_percentile: float = 95.0,
    max_orange_extreme_count: int = 1,
    use_count_dependency: bool = False,
    red_additional_decay: float = 0.25,
    orange_additional_decay: float = 0.5,
    max_red_count: int = -1,
    max_orange_count: int = -1,
    progress_callback: Callable[[int, int], bool | None] | None = None,
    progress_every: int = 20,
    max_workers: Optional[int] = None,
) -> SimulationResult:
    if not combinations: raise ValueError("无合法组合")
    if num_samples <= 0: raise ValueError("num_samples 必须大于 0")
    
    total_combos = len(combinations)
    tail_quantile = (100.0 - float(safe_bid_confidence_pct)) / 100.0

    # 🚀 自适应采样衰减
    effective_samples = num_samples
    if total_combos > 8000: effective_samples = min(num_samples, 1500)
    elif total_combos > 3000: effective_samples = min(num_samples, 2500)

    # 权重计算
    combo_logs = np.array([_combo_log_weight(c) for c in combinations], dtype=np.float64)
    combo_logs -= combo_logs.max()
    combo_weights = np.exp(combo_logs)
    
    if use_count_dependency or max_red_count >= 0 or max_orange_count >= 0:
        penalties = np.ones(total_combos, dtype=np.float64)
        for i, c in enumerate(combinations):
            bg = c.by_grade()
            r, o = bg.get(6, 0), bg.get(5, 0)
            if max_red_count >= 0 and r > max_red_count: penalties[i] = 0.0; continue
            if max_orange_count >= 0 and o > max_orange_count: penalties[i] = 0.0; continue
            if use_count_dependency:
                if r > 1: penalties[i] *= red_additional_decay ** (r - 1)
                if o > 1: penalties[i] *= orange_additional_decay ** (o - 1)
        combo_weights *= penalties
    combo_weights /= combo_weights.sum()
    equal_weight = 1.0 / total_combos

    red_thr = float(np.percentile(price_pools[6], red_extreme_percentile)) if (filter_extreme_red and 6 in price_pools) else 0.0
    orange_thr = float(np.percentile(price_pools[5], orange_extreme_percentile)) if (filter_extreme_orange and 5 in price_pools) else 0.0

    # 🌐 智能并行策略
    # Windows 下 ProcessPool 序列化开销极大，改用 ThreadPool (NumPy/CuPy 自动释放 GIL)
    # 组合数 < 2万 时单线程最快（缓存局部性+零拷贝），>2万 时自动多线程
    n_workers = max_workers if max_workers is not None else (1 if total_combos < 20000 else min(4, os.cpu_count() or 4))
    chunk_size = max(1, total_combos // n_workers)
    chunks = [combinations[i:i + chunk_size] for i in range(0, total_combos, chunk_size)]
    chunk_weights = [combo_weights[i:i + chunk_size] for i in range(0, total_combos, chunk_size)]

    agg_means, agg_safe, agg_pess, agg_max, agg_vals, agg_wts = [], [], [], [], [], []
    
    executor_cls = ThreadPoolExecutor if n_workers > 1 else None
    
    if executor_cls:
        with executor_cls(max_workers=n_workers) as exe:
            futs = {exe.submit(_simulate_worker, chunk, cw, price_pools, effective_samples,
                               tail_quantile, safe_bid_mode, equal_weight,
                               red_thr, max_red_extreme_count, orange_thr, max_orange_extreme_count,
                               filter_extreme_red, filter_extreme_orange, (seed or 42)+i*999): i 
                    for i, (chunk, cw) in enumerate(zip(chunks, chunk_weights))}
            
            completed = 0
            for fut in as_completed(futs):
                res = fut.result()
                for k, lst in [("means", agg_means), ("safe_qs", agg_safe), ("pess_qs", agg_pess), ("theo_maxs", agg_max)]:
                    lst.append(res[k])
                agg_vals.extend(res["all_vals"])
                agg_wts.extend(res["all_wts"])
                completed += 1
                if progress_callback: progress_callback(completed * chunk_size, total_combos)
    else:
        # 单线程直跑 (最快路径)
        for i, (chunk, cw) in enumerate(zip(chunks, chunk_weights)):
            res = _simulate_worker(chunk, cw, price_pools, effective_samples,
                                   tail_quantile, safe_bid_mode, equal_weight,
                                   red_thr, max_red_extreme_count, orange_thr, max_orange_extreme_count,
                                   filter_extreme_red, filter_extreme_orange, (seed or 42)+i*999)
            for k, lst in [("means", agg_means), ("safe_qs", agg_safe), ("pess_qs", agg_pess), ("theo_maxs", agg_max)]:
                lst.append(res[k])
            agg_vals.extend(res["all_vals"])
            agg_wts.extend(res["all_wts"])
            if progress_callback: progress_callback((i + 1) * len(chunk), total_combos)

    # 📊 最终聚合
    means_arr = np.concatenate(agg_means)
    safe_arr = np.concatenate(agg_safe)
    pess_arr = np.concatenate(agg_pess)
    max_arr = np.concatenate(agg_max)
    all_vals = np.concatenate(agg_vals)
    all_wts = np.concatenate(agg_wts)

    expected_value = float(np.dot(means_arr, combo_weights))
    safe_bid_95 = _weighted_quantile(all_vals, all_wts, tail_quantile)
    pessimistic_bid = _weighted_quantile(all_vals, all_wts, 0.01)
    max_value = float(np.max(max_arr))

    expected_idx = int(np.argmin(np.abs(means_arr - expected_value)))
    safe_idx = int(np.argmin(np.abs(safe_arr - safe_bid_95)))
    pessimistic_idx = int(np.argmin(np.abs(pess_arr - pessimistic_bid)))
    max_idx = int(np.argmax(max_arr))

    return SimulationResult(
        expected_value=expected_value, safe_bid_95=safe_bid_95, pessimistic_bid=pessimistic_bid,
        expected_combo=combinations[expected_idx], expected_combo_value=float(means_arr[expected_idx]),
        safe_bid_combo=combinations[safe_idx], safe_bid_combo_value=float(safe_arr[safe_idx]),
        pessimistic_combo=combinations[pessimistic_idx], pessimistic_combo_value=float(pess_arr[pessimistic_idx]),
        max_combo=combinations[max_idx], max_combo_value=float(max_arr[max_idx]),
        max_value=max_value, combination_count=total_combos,
    )