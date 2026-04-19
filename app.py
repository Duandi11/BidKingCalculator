from pathlib import Path
import time

import streamlit as st

from src.data_loader import (
    load_grid_size_options_by_grade,
    load_item_grade_mapping,
    load_price_pools,
)
from src.clue_loader import load_silhouette_dict
from src.models import GradeGridTotalClue, PriceAvgClue, SilhouetteClue, SolverConstraints
from src.simulator import CalculationCancelledError, run_monte_carlo
from src.solver import solve_valid_combinations


st.set_page_config(page_title="竞拍之王实时估值辅助", layout="wide")
st.title("竞拍之王实时估值辅助系统")


@st.cache_resource
def get_price_pools(data_dir: str):
    return load_price_pools(data_dir)


@st.cache_resource
def get_grid_size_options(data_dir: str):
    return load_grid_size_options_by_grade(data_dir)


@st.cache_resource
def get_item_grade_mapping(data_dir: str):
    return load_item_grade_mapping(data_dir)


@st.cache_resource
def get_silhouette_dict(data_dir: str):
    return load_silhouette_dict(data_dir)


default_data_dir = str((Path(__file__).parent / "data").resolve())


def _init_state() -> None:
    if "min_count_clues" not in st.session_state:
        st.session_state.min_count_clues = []
    if "max_count_clues" not in st.session_state:
        st.session_state.max_count_clues = []
    if "price_avg_clues" not in st.session_state:
        st.session_state.price_avg_clues = []
    if "grid_total_clues" not in st.session_state:
        st.session_state.grid_total_clues = []
    if "global_grid_total_clues" not in st.session_state:
        st.session_state.global_grid_total_clues = []
    if "exact_count_clues" not in st.session_state:
        st.session_state.exact_count_clues = []
    if "silhouette_clues" not in st.session_state:
        st.session_state.silhouette_clues = []
    if "calc_cancel_requested" not in st.session_state:
        st.session_state.calc_cancel_requested = False
    if "calc_running" not in st.session_state:
        st.session_state.calc_running = False


def _grade_name(grade: int) -> str:
    return {1: "白", 2: "绿", 3: "蓝", 4: "紫", 5: "橙", 6: "红"}.get(grade, str(grade))


_init_state()
with st.sidebar:
    st.subheader("全局设置")
    data_dir = st.text_input("数据目录", value=default_data_dir)
    st.caption("输入区已移动到主区域，右侧为当前线索与模拟参数。")

grid_size_options = {}
grid_size_err = None
try:
    grid_size_options = get_grid_size_options(data_dir)
except Exception as exc:
    grid_size_err = str(exc)

item_grade_mapping = {}
item_grade_mapping_err = None
try:
    item_grade_mapping = get_item_grade_mapping(data_dir)
except Exception as exc:
    item_grade_mapping_err = str(exc)

silhouette_dict = {}
silhouette_err = None
try:
    silhouette_dict = get_silhouette_dict(data_dir)
except Exception as exc:
    silhouette_err = str(exc)

st.markdown("## 输入与配置")
main_left, main_right = st.columns([2, 1], gap="large")

with main_left:
    st.markdown("### 基础线索")
    basic_col_1, basic_col_2 = st.columns(2)
    with basic_col_1:
        total_count = st.number_input("第1轮: 总数量 N_total", min_value=1, value=20, step=1)
    with basic_col_2:
        use_gw = st.checkbox("启用第5轮线索 (N_G + N_W)", value=False)
        gw_count = st.number_input("第5轮: N_GW", min_value=0, value=0, step=1, disabled=not use_gw)

    st.markdown("### 第2/3/4轮平均格数线索")
    avg_col_o, avg_col_p, avg_col_b = st.columns(3)
    with avg_col_o:
        use_o = st.checkbox("启用橙色平均格数", value=False)
        avg_grid_o = st.number_input("橙色平均格数", min_value=0.0, value=1.0, step=0.01, disabled=not use_o)
    with avg_col_p:
        use_p = st.checkbox("启用紫色平均格数", value=False)
        avg_grid_p = st.number_input("紫色平均格数", min_value=0.0, value=1.0, step=0.01, disabled=not use_p)
    with avg_col_b:
        use_b = st.checkbox("启用蓝色平均格数", value=False)
        avg_grid_b = st.number_input("蓝色平均格数", min_value=0.0, value=1.0, step=0.01, disabled=not use_b)

    avg_grid_half_tolerance = st.number_input(
        "平均格数容差(±)",
        min_value=0.001,
        max_value=0.2,
        value=0.2,
        step=0.001,
    )

    st.markdown("### 添加附加线索")
    clue_col_1, clue_col_2, clue_col_3 = st.columns([2, 1, 1])
    with clue_col_1:
        clue_type = st.selectbox(
            "线索类型",
            ["等级下限", "等级上限", "等级精确个数", "等级均价", "等级总格数(背包)", "藏品占用总格数", "轮廓候选等级"],
        )
    with clue_col_2:
        clue_grade = st.selectbox("等级", [1, 2, 3, 4, 5, 6], format_func=_grade_name)
    with clue_col_3:
        clue_value = st.number_input("线索值", min_value=0.0, value=1.0, step=1.0)

    use_override_count = st.checkbox("均价线索指定件数", value=False, disabled=clue_type != "等级均价")
    override_count = st.number_input("指定件数", min_value=1, value=1, step=1, disabled=(clue_type != "等级均价" or not use_override_count))
    exact_reachable = st.checkbox("启用精确可达过滤(较慢)", value=False, disabled=clue_type != "等级均价")
    auto_grid_sizes = grid_size_options.get(int(clue_grade), [])
    if clue_type == "等级总格数(背包)":
        if grid_size_err:
            st.warning(f"格数数据加载失败，将使用手动输入: {grid_size_err}")
        elif auto_grid_sizes:
            st.caption(f"已检测到该等级格数集合: {auto_grid_sizes}")
        else:
            st.info("该等级未检测到格数列数据，将使用手动输入。")
    if clue_type == "藏品占用总格数":
        st.caption("该线索会约束整箱所有藏品的总格数。")

    silhouette_keys = sorted(list(silhouette_dict.keys()))
    silhouette_key = st.selectbox(
        "轮廓ID",
        silhouette_keys,
        index=0,
        disabled=(clue_type != "轮廓候选等级" or not silhouette_keys),
    )
    silhouette_min_exist = st.number_input(
        "该轮廓至少出现件数",
        min_value=1,
        value=1,
        step=1,
        disabled=(clue_type != "轮廓候选等级"),
    )
    if clue_type == "轮廓候选等级":
        if silhouette_err:
            st.warning(f"轮廓字典加载失败: {silhouette_err}")
        elif not silhouette_keys:
            st.info("未找到 silhouette_dict.json，轮廓线索暂不可用。")
        else:
            current = silhouette_dict.get(silhouette_key, {})
            st.caption(
                f"候选等级: {current.get('grades', [])}，候选ItemID数: {len(current.get('item_ids', []))}"
            )
            if item_grade_mapping_err:
                st.caption(f"Item_ID->等级映射加载失败: {item_grade_mapping_err}")
    grid_sizes_text = st.text_input(
        "候选格数集合(逗号分隔)",
        value=(",".join(str(x) for x in auto_grid_sizes) if auto_grid_sizes else "1,2,3"),
        disabled=(clue_type != "等级总格数(背包)" or bool(auto_grid_sizes)),
    )
    st.caption("说明: 轮廓线索会约束“候选等级总出现次数”至少达到指定件数。")

    if st.button("添加线索", use_container_width=True):
        if clue_type == "等级下限":
            st.session_state.min_count_clues.append({"grade": int(clue_grade), "value": int(clue_value)})
        elif clue_type == "等级上限":
            st.session_state.max_count_clues.append({"grade": int(clue_grade), "value": int(clue_value)})
        elif clue_type == "等级精确个数":
            st.session_state.exact_count_clues.append({"grade": int(clue_grade), "value": int(clue_value)})
        elif clue_type == "等级均价":
            st.session_state.price_avg_clues.append(
                {
                    "grade": int(clue_grade),
                    "avg_price": float(clue_value),
                    "count_override": int(override_count) if use_override_count else None,
                    "exact_reachable": bool(exact_reachable),
                }
            )
        elif clue_type == "等级总格数(背包)":
            try:
                if auto_grid_sizes:
                    grid_sizes = auto_grid_sizes
                else:
                    grid_sizes = [int(x.strip()) for x in grid_sizes_text.split(",") if x.strip()]
                if not grid_sizes:
                    raise ValueError("候选格数不能为空")
                st.session_state.grid_total_clues.append(
                    {
                        "grade": int(clue_grade),
                        "total_grid": int(clue_value),
                        "candidate_grid_sizes": grid_sizes,
                    }
                )
            except Exception as exc:
                st.error(f"背包线索添加失败: {exc}")
        elif clue_type == "藏品占用总格数":
            st.session_state.global_grid_total_clues.append({"value": int(clue_value)})
        elif clue_type == "轮廓候选等级":
            if not silhouette_keys:
                st.error("未检测到可用轮廓字典，请先准备 data/silhouette_dict.json")
            else:
                payload = silhouette_dict.get(silhouette_key, {})
                candidate_grades = [int(x) for x in payload.get("grades", [])]
                candidate_item_ids = [int(x) for x in payload.get("item_ids", [])]
                for item_id in candidate_item_ids:
                    mapped_grade = item_grade_mapping.get(item_id)
                    if mapped_grade is not None:
                        candidate_grades.append(int(mapped_grade))
                candidate_grades = sorted(set(candidate_grades))
                if not candidate_grades:
                    st.error("该轮廓未解析到有效候选等级，无法添加。")
                else:
                    st.session_state.silhouette_clues.append(
                        {
                            "source_id": silhouette_key,
                            "candidate_grades": candidate_grades,
                            "candidate_item_ids": candidate_item_ids,
                            "min_exist_count": int(silhouette_min_exist),
                        }
                    )

with main_right:
    st.markdown("### 当前线索")
    if st.button("重置本局", use_container_width=True):
        st.session_state.min_count_clues = []
        st.session_state.max_count_clues = []
        st.session_state.exact_count_clues = []
        st.session_state.price_avg_clues = []
        st.session_state.grid_total_clues = []
        st.session_state.global_grid_total_clues = []
        st.session_state.silhouette_clues = []
        st.rerun()

    for idx, clue in enumerate(st.session_state.min_count_clues):
        c1, c2 = st.columns([6, 1])
        c1.caption(f"{_grade_name(clue['grade'])}色下限 >= {clue['value']}")
        if c2.button("删", key=f"del_min_{idx}"):
            st.session_state.min_count_clues.pop(idx)
            st.rerun()

    for idx, clue in enumerate(st.session_state.max_count_clues):
        c1, c2 = st.columns([6, 1])
        c1.caption(f"{_grade_name(clue['grade'])}色上限 <= {clue['value']}")
        if c2.button("删", key=f"del_max_{idx}"):
            st.session_state.max_count_clues.pop(idx)
            st.rerun()

    for idx, clue in enumerate(st.session_state.price_avg_clues):
        c1, c2 = st.columns([6, 1])
        if clue["count_override"] is None:
            suffix = " [精确]" if clue.get("exact_reachable") else ""
            c1.caption(f"{_grade_name(clue['grade'])}色均价 ≈ {clue['avg_price']}{suffix}")
        else:
            suffix = " [精确]" if clue.get("exact_reachable") else ""
            c1.caption(
                f"{_grade_name(clue['grade'])}色均价 ≈ {clue['avg_price']} (件数={clue['count_override']}){suffix}"
            )
        if c2.button("删", key=f"del_price_{idx}"):
            st.session_state.price_avg_clues.pop(idx)
            st.rerun()

    for idx, clue in enumerate(st.session_state.grid_total_clues):
        c1, c2 = st.columns([6, 1])
        c1.caption(
            f"{_grade_name(clue['grade'])}色总格数 = {clue['total_grid']} "
            f"(候选格数={clue['candidate_grid_sizes']})"
        )
        if c2.button("删", key=f"del_grid_{idx}"):
            st.session_state.grid_total_clues.pop(idx)
            st.rerun()

    for idx, clue in enumerate(st.session_state.global_grid_total_clues):
        c1, c2 = st.columns([6, 1])
        c1.caption(f"藏品占用总格数 = {clue['value']}")
        if c2.button("删", key=f"del_global_grid_{idx}"):
            st.session_state.global_grid_total_clues.pop(idx)
            st.rerun()

    for idx, clue in enumerate(st.session_state.exact_count_clues):
        c1, c2 = st.columns([6, 1])
        c1.caption(
            f"{_grade_name(clue['grade'])}色精确数量 = {clue['value']}"
        )
        if c2.button("删", key=f"del_exact_{idx}"):
            st.session_state.exact_count_clues.pop(idx)
            st.rerun()

    for idx, clue in enumerate(st.session_state.silhouette_clues):
        c1, c2 = st.columns([6, 1])
        c1.caption(
            f"轮廓[{clue['source_id']}] 候选等级={clue['candidate_grades']}，至少出现 {clue['min_exist_count']} 件"
        )
        if c2.button("删", key=f"del_silhouette_{idx}"):
            st.session_state.silhouette_clues.pop(idx)
            st.rerun()

    st.markdown("### 模拟参数")
    num_samples = st.number_input("每个组合采样次数", min_value=1000, max_value=50000, value=1000, step=1000)
    safe_bid_confidence_pct = st.number_input(
        "Safe_Bid 置信度(%)",
        min_value=50,
        max_value=99,
        value=95,
        step=1,
    )
    safe_bid_mode_label = st.selectbox(
        "Safe_Bid_95 计算模式",
        ["等权(推荐先用)", "先验加权(32:32:16:8:2:1)"],
        index=0,
    )
    with st.expander("红/橙高级配置（可选）", expanded=False):
        filter_extreme_red = st.checkbox("过滤极端高价红色样本", value=True)
        red_extreme_percentile = st.number_input(
            "红色高价阈值分位(%)",
            min_value=80,
            max_value=99,
            value=95,
            step=1,
            disabled=not filter_extreme_red,
        )
        max_red_extreme_count = st.number_input(
            "单箱高价红色最多件数",
            min_value=0,
            max_value=10,
            value=1,
            step=1,
            disabled=not filter_extreme_red,
        )
        filter_extreme_orange = st.checkbox("过滤极端高价橙色样本", value=True)
        orange_extreme_percentile = st.number_input(
            "橙色高价阈值分位(%)",
            min_value=80,
            max_value=99,
            value=95,
            step=1,
            disabled=not filter_extreme_orange,
        )
        max_orange_extreme_count = st.number_input(
            "单箱高价橙色最多件数",
            min_value=0,
            max_value=20,
            value=2,
            step=1,
            disabled=not filter_extreme_orange,
        )
        use_count_dependency = st.checkbox("启用红/橙数量依赖抑制", value=True)
        red_additional_decay = st.number_input(
            "第二个及以上红色衰减系数",
            min_value=0.01,
            max_value=1.0,
            value=0.25,
            step=0.01,
            disabled=not use_count_dependency,
        )
        orange_additional_decay = st.number_input(
            "第二个及以上橙色衰减系数",
            min_value=0.01,
            max_value=1.0,
            value=0.50,
            step=0.01,
            disabled=not use_count_dependency,
        )
        max_red_count = st.number_input(
            "单箱红色数量上限(-1表示不限)",
            min_value=-1,
            max_value=20,
            value=-1,
            step=1,
            disabled=not use_count_dependency,
        )
        max_orange_count = st.number_input(
            "单箱橙色数量上限(-1表示不限)",
            min_value=-1,
            max_value=30,
            value=-1,
            step=1,
            disabled=not use_count_dependency,
        )

action_col_1, action_col_2 = st.columns(2)
with action_col_1:
    run_btn = st.button(
        "开始估值",
        type="primary",
        use_container_width=True,
        disabled=st.session_state.calc_running,
    )
with action_col_2:
    cancel_btn = st.button(
        "终止计算",
        type="secondary",
        use_container_width=True,
        disabled=not st.session_state.calc_running,
    )

if cancel_btn:
    st.session_state.calc_cancel_requested = True
    st.warning("已请求终止计算，系统会在当前采样批次结束后尽快停止。")


if run_btn:
    st.session_state.calc_running = True
    st.session_state.calc_cancel_requested = False
    progress_box = st.container()
    with progress_box:
        st.markdown("### 计算进度")
        progress_text = st.empty()
        progress_bar = st.progress(0, text="准备开始...")
        progress_detail = st.empty()

    total_start_ts = time.perf_counter()
    progress_text.info("阶段 1/3: 加载数据")
    progress_bar.progress(5, text="阶段 1/3: 加载数据")
    try:
        pools = get_price_pools(data_dir)
    except Exception as exc:
        st.error(f"数据加载失败: {exc}")
        st.stop()
    progress_bar.progress(20, text="阶段 1/3: 数据加载完成")
    progress_detail.caption("已完成数据读取，正在整理线索约束。")

    progress_text.info("阶段 2/3: 求解合法组合")
    constraints_start_ts = time.perf_counter()
    min_count_by_grade = {}
    for clue in st.session_state.min_count_clues:
        grade = int(clue["grade"])
        min_count_by_grade[grade] = max(min_count_by_grade.get(grade, 0), int(clue["value"]))

    max_count_by_grade = {}
    for clue in st.session_state.max_count_clues:
        grade = int(clue["grade"])
        if grade in max_count_by_grade:
            max_count_by_grade[grade] = min(max_count_by_grade[grade], int(clue["value"]))
        else:
            max_count_by_grade[grade] = int(clue["value"])

    exact_count_by_grade = {}
    for clue in st.session_state.exact_count_clues:
        grade = int(clue["grade"])
        value = int(clue["value"])
        if grade in exact_count_by_grade and exact_count_by_grade[grade] != value:
            # Contradicting exact-count clues force an empty solution set.
            exact_count_by_grade[grade] = -1
        else:
            exact_count_by_grade[grade] = value

    price_avg_clues = [
        PriceAvgClue(
            grade=int(clue["grade"]),
            avg_price=float(clue["avg_price"]),
            count_override=(None if clue["count_override"] is None else int(clue["count_override"])),
            exact_reachable=bool(clue.get("exact_reachable", False)),
        )
        for clue in st.session_state.price_avg_clues
    ]

    grid_total_clues = [
        GradeGridTotalClue(
            grade=int(clue["grade"]),
            total_grid=int(clue["total_grid"]),
            candidate_grid_sizes=[int(x) for x in clue["candidate_grid_sizes"]],
        )
        for clue in st.session_state.grid_total_clues
    ]

    silhouette_clues = [
        SilhouetteClue(
            candidate_grades=[int(x) for x in clue.get("candidate_grades", [])],
            candidate_item_ids=[int(x) for x in clue.get("candidate_item_ids", [])],
            source_id=clue.get("source_id"),
            min_exist_count=int(clue.get("min_exist_count", 1)),
        )
        for clue in st.session_state.silhouette_clues
    ]

    global_total_grid = None
    for clue in st.session_state.global_grid_total_clues:
        value = int(clue["value"])
        if global_total_grid is None:
            global_total_grid = value
        elif global_total_grid != value:
            global_total_grid = -1

    constraints = SolverConstraints(
        total_count=int(total_count),
        gw_count=int(gw_count) if use_gw else None,
        avg_grid_o=float(avg_grid_o) if use_o else None,
        avg_grid_p=float(avg_grid_p) if use_p else None,
        avg_grid_b=float(avg_grid_b) if use_b else None,
        avg_grid_half_tolerance=float(avg_grid_half_tolerance),
        global_total_grid=global_total_grid,
        grid_size_options_by_grade=grid_size_options,
        min_count_by_grade=min_count_by_grade,
        max_count_by_grade=max_count_by_grade,
        exact_count_by_grade=exact_count_by_grade,
        price_avg_clues=price_avg_clues,
        grade_grid_total_clues=grid_total_clues,
        silhouette_clues=silhouette_clues,
    )

    valid_combinations = solve_valid_combinations(constraints, pools)
    constraints_elapsed = time.perf_counter() - constraints_start_ts
    progress_bar.progress(55, text="阶段 2/3: 合法组合求解完成")
    progress_detail.caption(
        f"合法组合数量: {len(valid_combinations)}，耗时: {constraints_elapsed:.2f}s。"
    )
    st.info(f"当前可能组合数量: {len(valid_combinations)}")

    if not valid_combinations:
        st.warning("未找到合法组合。请检查线索是否矛盾或输入有误。")
        st.stop()

    progress_text.info("阶段 3/3: 蒙特卡洛估值")
    monte_start_ts = time.perf_counter()
    last_progress_update = {"ts": 0.0}
    cancelled = False

    def _on_mc_progress(done: int, total: int) -> bool:
        if st.session_state.get("calc_cancel_requested", False):
            progress_text.warning("正在终止计算...")
            progress_detail.caption("已收到终止请求，正在安全停止。")
            return False
        now = time.perf_counter()
        if done not in (0, total) and now - last_progress_update["ts"] < 0.2:
            return True
        last_progress_update["ts"] = now
        ratio = (done / total) if total > 0 else 1.0
        pct = 55 + int(ratio * 40)
        pct = max(55, min(95, pct))
        progress_bar.progress(
            pct,
            text=f"阶段 3/3: 蒙特卡洛估值 ({done}/{total} 组合)",
        )
        progress_detail.caption(
            f"采样中: 已完成 {done}/{total} 个组合，每组合 {int(num_samples)} 次。"
        )
        return True

    safe_bid_mode = "equal" if safe_bid_mode_label.startswith("等权") else "prior"
    try:
        result = run_monte_carlo(
            combinations=valid_combinations,
            price_pools=pools,
            num_samples=int(num_samples),
            safe_bid_mode=safe_bid_mode,
            safe_bid_confidence_pct=float(safe_bid_confidence_pct),
            filter_extreme_red=bool(filter_extreme_red),
            red_extreme_percentile=float(red_extreme_percentile),
            max_red_extreme_count=int(max_red_extreme_count),
            filter_extreme_orange=bool(filter_extreme_orange),
            orange_extreme_percentile=float(orange_extreme_percentile),
            max_orange_extreme_count=int(max_orange_extreme_count),
            use_count_dependency=bool(use_count_dependency),
            red_additional_decay=float(red_additional_decay),
            orange_additional_decay=float(orange_additional_decay),
            max_red_count=int(max_red_count),
            max_orange_count=int(max_orange_count),
            progress_callback=_on_mc_progress,
        )
    except CalculationCancelledError:
        cancelled = True
        progress_bar.progress(100, text="计算已终止")
        progress_text.warning("本次计算已终止")
        progress_detail.caption("你可以调整参数后再次点击“开始估值”。")
    finally:
        st.session_state.calc_running = False
        st.session_state.calc_cancel_requested = False

    if cancelled:
        st.info("本次估值已取消，可直接重新开始。")
        st.stop()

    monte_elapsed = time.perf_counter() - monte_start_ts
    total_elapsed = time.perf_counter() - total_start_ts
    progress_text.success("计算完成")
    progress_bar.progress(100, text="全部阶段完成")
    progress_detail.caption(
        f"阶段耗时: 组合求解 {constraints_elapsed:.2f}s，蒙特卡洛 {monte_elapsed:.2f}s，总计 {total_elapsed:.2f}s。"
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Expected_Value", f"{result.expected_value:,.2f}")
    c2.metric(f"Safe_Bid_{int(safe_bid_confidence_pct)}", f"{result.safe_bid_95:,.2f}")
    c3.metric("Pessimistic_Bid_99", f"{result.pessimistic_bid:,.2f}")
    c4.metric("Max_Value", f"{result.max_value:,.2f}")

    st.markdown("### 估值对应价格组合")
    if result.expected_combo is not None:
        c = result.expected_combo
        st.write(
            "Expected 组合: "
            f"W/G/B/P/O/R = {c.w}/{c.g}/{c.b}/{c.p}/{c.o}/{c.r}，"
            f"组合估值≈ {result.expected_combo_value:,.2f}"
        )
    if result.safe_bid_combo is not None:
        c = result.safe_bid_combo
        st.write(
            f"Safe_Bid_{int(safe_bid_confidence_pct)} 组合: "
            f"W/G/B/P/O/R = {c.w}/{c.g}/{c.b}/{c.p}/{c.o}/{c.r}，"
            f"组合分位估值≈ {result.safe_bid_combo_value:,.2f}"
        )
    if result.pessimistic_combo is not None:
        c = result.pessimistic_combo
        st.write(
            "Pessimistic_Bid_99 组合: "
            f"W/G/B/P/O/R = {c.w}/{c.g}/{c.b}/{c.p}/{c.o}/{c.r}，"
            f"组合分位估值≈ {result.pessimistic_combo_value:,.2f}"
        )
    if result.max_combo is not None:
        c = result.max_combo
        st.write(
            "Max_Value 组合: "
            f"W/G/B/P/O/R = {c.w}/{c.g}/{c.b}/{c.p}/{c.o}/{c.r}，"
            f"组合理论上限≈ {result.max_combo_value:,.2f}"
        )

    st.success("估值计算完成")
else:
    st.caption("请在上方主区域输入线索并点击“开始估值”。")
