# 竞拍之王实时估值辅助 - 系统架构与流程文档

## 1. 系统模块调用关系图 (Call Graph)

以下是系统整体的模块调用层级，从外部入口到核心引擎的流向：

```mermaid
graph TD
    %% 外部入口层
    subgraph Interfaces [展现与交互层]
        APP[app.py\nStreamlit Web界面]
        GUI[未来的 PyQt5 悬浮窗]
        CLI[命令行直接调用]
    end

    %% 调度层
    subgraph Orchestration [调度层]
        PIPE[src/pipeline.py\nBidEvaluationPipeline]
    end

    %% 核心业务模块
    subgraph Core [核心业务层]
        PERCEPT[src/auto_reader.py\nGameScreenAnalyzer]
        ADAPTER[src/clue_adapter.py\nOcrToClueAdapter]
        SOLVER[src/solver.py\nsolve_valid_combinations]
        SIM[src/simulator.py\nrun_monte_carlo]
    end

    %% 基础与数据层
    subgraph Infrastructure [基础数据层]
        DATA[src/data_loader.py]
        MODELS[src/models.py]
        CONST[src/constraints.py]
    end

    %% 调用关系连线
    GUI --> PIPE
    CLI --> PIPE
    APP --> SOLVER
    APP --> SIM
    
    PIPE -->|1. 传图| PERCEPT
    PIPE -->|2. 传字典| ADAPTER
    PIPE -->|3. 传约束| SOLVER
    PIPE -->|4. 传组合| SIM

    PERCEPT -.使用.-> MODELS
    ADAPTER -.使用.-> MODELS
    SOLVER -.使用.-> MODELS
    SOLVER -.依赖.-> CONST
    SIM -.使用.-> MODELS

    PIPE -.加载数据.-> DATA
    APP -.加载数据.-> DATA
```

---

## 2. 核心文件职责与能力说明 (Responsibilities)

| 文件路径 | 模块名称 | 属于分层 | 核心职责说明 | 能力与特点 |
| :--- | :--- | :--- | :--- | :--- |
| `src/pipeline.py` | **估值调度器** | 调度层 | 负责将孤立的各个底层模块串联，实现“一键估值”。对外屏蔽底层复杂逻辑。 | 捕获运行时间、提供日志输出、统一异常捕获。向前端吐出 `PipelineResult`。 |
| `src/auto_reader.py` | **图像感知引擎** | 感知层 | 封装 PaddleOCR。输入游戏截图，输出纯字典结构的正则化数据信息。 | 不包含任何估值逻辑，极度解耦。内置针对截屏特定比例的 ROI（感兴趣区域）硬编码切割。 |
| `src/clue_adapter.py` | **数据适配器** | 适配层 | 将 OCR 提取的非结构化字典，清洗防呆后转换为数学引擎所需的严格 `SolverConstraints` 模型。 | 错误拦截（如缺少总数）。补全缺失的变量默认值，放宽浮点计算容忍度。 |
| `src/solver.py` | **数学求解引擎** | 计算层 | 基于用户给定的约束（总数、均格数、均价等），利用 DFS 与后缀和安全剪枝算法，推演出所有可能的藏品颜色组合情况。 | 纯 CPU 密集型任务，极高效率的排列组合算力（十万级迭代秒级完成）。 |
| `src/simulator.py` | **蒙特卡洛模拟器** | 计算层 | 对求解器输出的所有合法组合，根据本地物价库运用随机游走计算，得出平滑的期望值与风险分位数。 | 提供 1%悲观保底价、95%安全出价等统计学金融指标输出。 |
| `src/data_loader.py` | **静态数据中心** | 基础层 | 将磁盘上的 CSV/JSON 物料读取到内存字典中。 | 缓存提速设计，避免高频 IO。 |
| `src/models.py` | **数据模型约定** | 基础层 | 定义系统中流通的各种核心数据结构 (`@dataclass`)，确保全系统类型安全。 | 包含 `CountCombination`, `SolverConstraints` 等核心结构。 |

---

## 3. 端到端估值时序图 (Sequence Flow)

该图展示了当我们执行一次自动化估值 (`pipeline.run_image_eval`) 时，时间线上的操作顺延：

```mermaid
sequenceDiagram
    autonumber
    actor User as 用户/交互界面
    participant Pipe as Pipeline (调度)
    participant Reader as AutoReader (OCR)
    participant Adapt as ClueAdapter (防呆转换)
    participant Solver as Solver (算法求解)
    participant Sim as Simulator (蒙特卡洛)

    User->>Pipe: 请求执行 run_image_eval(图片路径)
    activate Pipe
    
    Pipe->>Reader: analyze(图片)
    activate Reader
    Note over Reader: 读取截屏区域分类<br/>执行PaddleOCR大模型推理<br/>运行正则匹配业务变量
    Reader-->>Pipe: 返回 raw_ocr_data (Dict明文)
    deactivate Reader
    
    Pipe->>Adapt: build_constraints(raw_ocr_data)
    activate Adapt
    Note over Adapt: 校验必填字段(如总数)<br/>封装为严格的算法入参类型
    Adapt-->>Pipe: 返回 constraints (SolverConstraints对象)
    deactivate Adapt
    
    Pipe->>Solver: solve_valid_combinations(constraints, 物价)
    activate Solver
    Note over Solver: 结合总数和格数上下限推演<br/>过滤不符合均价格数的伪解
    Solver-->>Pipe: 返回 valid_combos (List[组合对象])
    deactivate Solver
    
    %% 判断无解拦截
    alt 组合穷举为0 / 无合法解情况
        Pipe-->>User: 抛出错误 PipelineResult (失败, 提示检查OCR)
    else 找到合法排列组合
        Pipe->>Sim: run_monte_carlo(valid_combos, 价格池, 采样万次)
        activate Sim
        Note over Sim: 基于置信度权重随机游走算估值与方差
        Sim-->>Pipe: 返回 simulation_result (期望价格, 保底价等)
        deactivate Sim
        
        Pipe-->>User: 返回 PipelineResult (成功, 打包了识别原数据及估值)
    end
    
    deactivate Pipe
```
