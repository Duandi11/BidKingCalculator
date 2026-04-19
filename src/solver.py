from typing import Dict, List, Optional
import numpy as np
from .constraints import (
    check_avg_grid_rounded_feasible,
    check_divisibility,
    check_grid_total_reachable,
    check_price_bounds_feasible,
    price_bounds_to_total_range,
)
from .models import CountCombination, SolverConstraints

def _in_range(value: int, low: int, high: int) -> bool:
    return low <= value <= high

def _bounds_for_grade(grade: int, constraints: SolverConstraints) -> tuple[int, int]:
    if grade in constraints.exact_count_by_grade:
        exact = constraints.exact_count_by_grade[grade]
        return exact, exact
    low = constraints.min_count_by_grade.get(grade, 0)
    high = constraints.max_count_by_grade.get(grade, constraints.total_count)
    return low, high

def _check_grade_bounds(combo: CountCombination, constraints: SolverConstraints) -> bool:
    by_grade = combo.by_grade()
    for grade, value in by_grade.items():
        low, high = _bounds_for_grade(grade, constraints)
        if not _in_range(value, low, high):
            return False
    return True

def _check_divisibility_constraints(combo: CountCombination, constraints: SolverConstraints) -> bool:
    options = constraints.grid_size_options_by_grade
    half_tol = constraints.avg_grid_half_tolerance
    if constraints.avg_grid_o is not None:
        if options.get(5):
            if not check_avg_grid_rounded_feasible(constraints.avg_grid_o, combo.o, options.get(5, []), half_tolerance=half_tol):
                return False
        else:
            if constraints.avg_grid_o == 0:
                if combo.o != 0: return False
            elif combo.o <= 0 or not check_divisibility(constraints.avg_grid_o, combo.o):
                return False
    if constraints.avg_grid_p is not None:
        if options.get(4):
            if not check_avg_grid_rounded_feasible(constraints.avg_grid_p, combo.p, options.get(4, []), half_tolerance=half_tol):
                return False
        else:
            if constraints.avg_grid_p == 0:
                if combo.p != 0: return False
            elif combo.p <= 0 or not check_divisibility(constraints.avg_grid_p, combo.p):
                return False
    if constraints.avg_grid_b is not None:
        if options.get(3):
            if not check_avg_grid_rounded_feasible(constraints.avg_grid_b, combo.b, options.get(3, []), half_tolerance=half_tol):
                return False
        else:
            if constraints.avg_grid_b == 0:
                if combo.b != 0: return False
            elif combo.b <= 0 or not check_divisibility(constraints.avg_grid_b, combo.b):
                return False
    return True

def _check_price_avg_constraints(combo: CountCombination, constraints: SolverConstraints, price_pools: Optional[Dict[int, np.ndarray]] = None) -> bool:
    if not constraints.price_avg_clues: return True
    if price_pools is None: return False
    by_grade = combo.by_grade()
    for clue in constraints.price_avg_clues:
        grade_count = by_grade.get(clue.grade, 0) if clue.count_override is None else clue.count_override
        if grade_count <= 0: return False
        pool = price_pools.get(clue.grade)
        if pool is None or len(pool) == 0: return False
        min_price = int(pool.min())
        max_price = int(pool.max())
        if not check_price_bounds_feasible(clue.avg_price, grade_count, min_price, max_price):
            return False
        if clue.exact_reachable and not _check_price_bounds_exact_reachable(clue.avg_price, grade_count, pool):
            return False
    return True

def _check_price_bounds_exact_reachable(avg_price: float, count: int, pool: np.ndarray) -> bool:
    if count <= 0: return False
    min_total, max_total = price_bounds_to_total_range(avg_price, count)
    if min_total > max_total: return False
    pool_values = np.unique(pool.astype(np.int64))
    if len(pool_values) == 0: return False
    min_unit = int(pool_values.min())
    max_unit = int(pool_values.max())
    if max_total < min_unit * count or min_total > max_unit * count: return False
    possible = {0}
    max_state_count = 40_000
    for used in range(1, count + 1):
        remaining = count - used
        lower_need = min_total - remaining * max_unit
        upper_need = max_total - remaining * min_unit
        next_possible = set()
        for partial in possible:
            for price in pool_values:
                total = partial + int(price)
                if lower_need <= total <= upper_need:
                    next_possible.add(total)
        if not next_possible: return False
        if len(next_possible) > max_state_count: return True
        possible = next_possible
    return any(min_total <= x <= max_total for x in possible)

def _check_grid_total_clues(combo: CountCombination, constraints: SolverConstraints) -> bool:
    if not constraints.grade_grid_total_clues: return True
    by_grade = combo.by_grade()
    for clue in constraints.grade_grid_total_clues:
        count = by_grade.get(clue.grade, 0)
        if not check_grid_total_reachable(count, clue.total_grid, clue.candidate_grid_sizes):
            return False
    return True

def _grade_reachable_grid_sums(count: int, sizes: List[int], cap: int) -> set[int]:
    if count < 0: return set()
    if count == 0: return {0}
    values = sorted({int(x) for x in sizes if int(x) > 0})
    if not values: return set()
    reachable = {0}
    for _ in range(count):
        nxt = set()
        for s in reachable:
            for v in values:
                t = s + v
                if t <= cap: nxt.add(t)
        if not nxt: return set()
        reachable = nxt
    return reachable

def _check_global_total_grid_clue(combo: CountCombination, constraints: SolverConstraints) -> bool:
    target = constraints.global_total_grid
    if target is None: return True
    if target < 0: return False
    options = constraints.grid_size_options_by_grade
    if not options: return False
    by_grade = combo.by_grade()
    min_total = 0
    max_total = 0
    for grade, count in by_grade.items():
        if count <= 0: continue
        sizes = options.get(grade, [])
        if not sizes: return False
        min_total += count * min(sizes)
        max_total += count * max(sizes)
    if target < min_total or target > max_total: return False
    reachable = {0}
    for grade, count in by_grade.items():
        if count <= 0: continue
        sizes = options.get(grade, [])
        grade_sums = _grade_reachable_grid_sums(count, sizes, target)
        if not grade_sums: return False
        nxt = set()
        for a in reachable:
            for b in grade_sums:
                t = a + b
                if t <= target: nxt.add(t)
        if not nxt: return False
        reachable = nxt
    return target in reachable

def _check_silhouette_clues(combo: CountCombination, constraints: SolverConstraints) -> bool:
    if not constraints.silhouette_clues: return True
    by_grade = combo.by_grade()
    for clue in constraints.silhouette_clues:
        total = sum(by_grade.get(g, 0) for g in clue.candidate_grades)
        if total < clue.min_exist_count: return False
    return True

def _iter_count_combinations(constraints: SolverConstraints):
    total = constraints.total_count
    if total < 0: return
    grades = [6, 5, 4, 3, 2, 1]
    bounds = {g: _bounds_for_grade(g, constraints) for g in grades}

    for low, high in bounds.values():
        if low < 0 or high < low: return

    n = len(grades)
    # 1. 件数后缀和 (用于快速收缩当前等级可选数量范围)
    suf_min_cnt = [0] * (n + 1)
    suf_max_cnt = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        g = grades[i]
        lo, hi = bounds[g]
        suf_min_cnt[i] = suf_min_cnt[i+1] + lo
        suf_max_cnt[i] = suf_max_cnt[i+1] + hi

    if total < suf_min_cnt[0] or total > suf_max_cnt[0]: return

    # 2. GW 约束预检查
    target_gw = constraints.gw_count
    if target_gw is not None:
        gw_low = bounds[1][0] + bounds[2][0]
        gw_high = bounds[1][1] + bounds[2][1]
        if target_gw < gw_low or target_gw > gw_high: return

    # 3. 🚀 预计算占格数极值与安全后缀和 (彻底替代不安全的 grades[i+1] 访问)
    grid_opts = constraints.grid_size_options_by_grade
    g_min = {g: min(grid_opts.get(g, [1])) for g in grades}
    g_max = {g: max(grid_opts.get(g, [1])) for g in grades}

    tg = constraints.global_total_grid
    suf_min_grid = [0] * (n + 1)
    suf_max_grid = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        g = grades[i]
        lo, hi = bounds[g]
        suf_min_grid[i] = suf_min_grid[i+1] + lo * g_min[g]
        suf_max_grid[i] = suf_max_grid[i+1] + hi * g_max[g]

    if tg is not None and (tg < suf_min_grid[0] or tg > suf_max_grid[0]):
        return

    counts: Dict[int, int] = {}

    def _dfs(i: int, remaining: int, gw_used: int, cur_grid_min: int, cur_grid_max: int):
        if i == n:
            if remaining != 0: return
            if target_gw is not None and gw_used != target_gw: return
            yield CountCombination(
                w=counts.get(1, 0), g=counts.get(2, 0), b=counts.get(3, 0),
                p=counts.get(4, 0), o=counts.get(5, 0), r=counts.get(6, 0),
            )
            return

        grade = grades[i]
        low, high = bounds[grade]
        # 动态收紧：剩余件数必须能塞进后续等级的容量限制
        low_eff = max(low, remaining - suf_max_cnt[i+1])
        high_eff = min(high, remaining - suf_min_cnt[i+1])
        if low_eff > high_eff: return

        for value in range(low_eff, high_eff + 1):
            next_gw = gw_used + value if grade in (1, 2) else gw_used
            if target_gw is not None and next_gw > target_gw: continue

            new_gmin = cur_grid_min + value * g_min[grade]
            new_gmax = cur_grid_max + value * g_max[grade]

            # 🚀 核心修复：使用预计算后缀和精确剪枝，安全无越界
            if tg is not None:
                # 即使后续全取最小格也超目标，或全取最大格也达不到目标 -> 剪枝
                if tg < new_gmin + suf_min_grid[i+1] or tg > new_gmax + suf_max_grid[i+1]:
                    continue

            counts[grade] = value
            yield from _dfs(i + 1, remaining - value, next_gw, new_gmin, new_gmax)
            counts.pop(grade, None)

    yield from _dfs(0, total, 0, 0, 0)

def solve_valid_combinations(
    constraints: SolverConstraints,
    price_pools: Optional[Dict[int, np.ndarray]] = None,
) -> List[CountCombination]:
    valid: List[CountCombination] = []
    for combo in _iter_count_combinations(constraints):
        if (
            _check_divisibility_constraints(combo, constraints)
            and _check_price_avg_constraints(combo, constraints, price_pools)
            and _check_grid_total_clues(combo, constraints)
            and _check_global_total_grid_clue(combo, constraints)
            and _check_silhouette_clues(combo, constraints)
        ):
            valid.append(combo)
    return valid