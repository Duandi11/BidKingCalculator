# BidKing Calculator
《竞拍之王》本地实时估值辅助工具。 简单来说是艾哈迈德对仓库宝具，能做到小本稳赚。
https://github.com/snkrsubscriberdqh/BidKingCalculator.git
经过一下午的游玩感受到了竞拍的魅力，同时也思考是否有绝对理性的打法——我关注到角色艾哈迈德在低倍场有机会获取到丰富信息，并且角色特有的逐轮获取信息的特点，使得玩家手动录入数据成为可能，因此基于艾哈迈德的玩法VibeCoding了一个模拟器，用于逐轮收集信息来估计仓库总价值。这项工作的主要贡献如下：
- 花费我的生命抄写了4.18日停服前的全部藏品价格与格数
- 构建了一个蒙特卡洛模拟器——用于帮助领完救济金的哥们快速摆脱低倍场
- 为模拟器搭建了基于Streamlit的GUI，在简单的虚拟环境中即可使用
模拟器核心是「约束求解 + 蒙特卡洛模拟」：先根据线索筛掉不可能的数量组合，再对剩余组合做快速估值。模拟器做了两版update，但是主播有论文要赶真得跑路了，目前模拟器的问题包括但不限于：第四轮之前信息少的时候算得慢、GUI没那么好用、最低价值能估计准但是数学期望看运气、算一半被掐掉有可能无法重新开始运算等等，有无绝活哥，快快滴fork帮主播迭代一下！

## 快速上手（3 分钟）

### Windows + Git Bash（推荐）

1. 进入仓库根目录，执行初始化（自动创建 conda 环境并安装依赖）

```bash
bash scripts/setup.sh --env-name bidking --python-version 3.11
```

2. 一键启动 UI

```bash
bash scripts/start.sh --env-name bidking
```

3. 如果需要 OCR 依赖

```bash
bash scripts/setup.sh --env-name bidking --python-version 3.11 --with-ocr
```

### 通用命令行方式（Linux/macOS/Windows）

1. 安装依赖

```bash
pip install -r requirements.txt
```

2. 启动 UI

```bash
streamlit run app.py
```

3. 在左侧输入线索并点击 `开始估值`

- `总数量 N_total`
- （可选）`N_G + N_W`
- （可选）蓝/紫/橙平均格数
- （可选）附加线索（等级上下限、精确个数、总格数等）

## 主要输出指标

- `Expected_Value`：期望估值（均值）
- `Safe_Bid_xx`：可配置置信度下的保守出价参考（默认 95）
- `Pessimistic_Bid_99`：最悲观参考（1% 分位）
- `Max_Value`：理论上限
- `估值对应价格组合`：四个指标各自的代表数量组合（W/G/B/P/O/R）

## 数据文件说明

### 1) 运行时基础数据

- 目录：`data/`
- 按等级拆分文件：
  - `item_list_w.csv`
  - `item_list_g.csv`
  - `item_list_b.csv`
  - `item_list_p.csv`
  - `item_list_o.csv`
  - `item_list_r.csv`

支持以下行格式（自动兼容）：

- `价格`
- `价格,格数`
- `名称,价格`
- `名称,价格,格数`

### 2) 合并总表（推荐保留）

- 文件：`data/items_data.csv`
- 字段：`Item_ID,Item_Name,Grade,Price,Grid_Size`
- 作用：统一索引与后续扩展（如 item_id 线索映射）

自动生成命令：

```bash
python scripts/build_items_data.py
```

### 3) 轮廓字典（可选）

- 示例：`data/silhouette_dict.example.json`
- 正式使用：复制为 `data/silhouette_dict.json`

## 线索使用建议

- 平均格数建议配合 `平均格数容差(±)` 一起使用。默认 `0.05` 更贴近实战显示误差。
- 当某等级数量可能为 0 时，该等级平均格数可以填 `0`。
- 若出现“无合法组合”，优先检查：
  - 总数量与 `N_GW` 是否矛盾
  - 平均格数是否过严（可适当放宽容差）
  - 附加线索是否互相冲突

## 高级参数（红/橙）

UI 里已将红/橙相关配置放到单独区域，并默认折叠：

- 极端高价样本过滤（红/橙）
- 单箱高价红/橙最多件数
- 红/橙数量依赖抑制（第二件起衰减）
- 单箱红/橙数量上限

这些参数用于抑制“同箱高价值红橙过于集中”的不合理极端样本。

## 概率模型说明

- 等级先验权重：`32:32:16:8:2:1`
- 同等级内部：物品出现概率与价格成反比（价格越高，出现概率越低）
- 采样机制：有放回采样

## 项目结构

```text
BidKing/
├── app.py
├── requirements.txt
├── data/
├── scripts/
│   └── build_items_data.py
└── src/
    ├── constraints.py
    ├── data_loader.py
    ├── models.py
    ├── simulator.py
    └── solver.py
```

## 常见问题

### Q1: 明明有线索却无解？

通常不是程序崩溃，而是约束真的互斥。先放宽 `平均格数容差(±)`，再逐条删除最近新增线索排查。

### Q2: 为什么 Safe_Bid 和最悲观值差很多？

两者是不同分位数：`Safe_Bid_xx` 用你设定的置信度，`Pessimistic_Bid_99` 是更保守的 1% 分位。

### Q3: 估值偏高怎么办？

开启红/橙高级配置里的过滤与依赖抑制，并提高保守置信度（如 98 或 99）。

## 推送到 GitHub（仓库首次）

```bash
cd /home/dingqh/workspace/BidKing
git init
git add .
git commit -m "Initial commit: BidKing calculator"
git branch -M main
git remote add origin https://github.com/snkrsubscriberdqh/BidKingCalculator.git
git push -u origin main
```
