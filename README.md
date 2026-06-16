# 多轨组网带宽效率模拟工具

这是一个用于构建多轨组网拓扑、设置路由方式、模拟 All2All 流量并计算卡带宽效率的 Python 小工具。当前支持 `1d-fm-clos` 和 `2d-fm-clos` 两类拓扑。工具会生成交互式拓扑网页、任意两张卡之间的路由记录、关注卡的带宽效率报告，以及全链路流量明细。

## 功能概览

### 1. 拓扑构建与可视化

可配置：

- 计算节点数量 `M`
- 每个节点的网卡数量 `N`
- 交换机数量 `X`
- 节点内卡间链路带宽
- 卡到交换机链路带宽

`1d-fm-clos` 拓扑规则：

- 每个节点内的 `N` 张卡两两相连，形成 FULLMesh。
- 每个节点的卡按交换机数量 `X` 尽量均匀分组。
- 每组卡连接到对应交换机。
- 如果 `N` 不能被 `X` 整除，前面的交换机分组会多分到一张卡。
- 交互式拓扑图中，每个节点内的卡按环形展示，方便观察节点内 FULLMesh。

`2d-fm-clos` 拓扑在 `1d-fm-clos` 基础上增加一层 2D FullMesh：

- 将计算节点按 `--fm2d-domain-size` 分成多个 2D FM 域。
- 默认 `--fm2d-domain-size` 等于每节点卡数 `--cards`。
- 每个 2D FM 域内，不同节点之间的同号卡两两相连。
- 例如 `--nodes 4 --cards 4 --fm2d-domain-size 2` 时，节点 `0,1` 是一个 2D FM 域，节点 `2,3` 是另一个 2D FM 域。
- 在每个域内，`node0-card0` 和 `node1-card0` 相连，`node0-card1` 和 `node1-card1` 相连，依此类推。

可视化默认使用 `simplified` 简略模式：

- 交换机放在中间一行。
- 计算节点上下交错摆放。
- 节点内卡按环形展示，卡号放在节点内 FullMesh 拓扑周围，减少文字和连线重叠。
- 节点内一维 FullMesh 在主图中完整画出。
- 交换机使用长方形展示，交换机名称写在框内。
- 2D FM 链路默认不画在主图中，而是在左上角用示意图说明“第二维 FullMesh 连接，一维同号卡互连，规模是 `--fm2d-domain-size`”。
- 对交换机连线做抽样展示，底层拓扑和流量模拟仍使用完整链路。
- 如果需要画出完整链路，可设置 `--visualization-detail full`。

输出：

- `topology.html`：Plotly 交互式拓扑网页。

### 2. 路由方式

任意源卡到目的卡之间按以下规则路由：

1. 源卡和目的卡在同一节点内：直接走节点内卡到卡链路。
2. 源卡和目的卡连接同一个交换机：直接走 `源卡 -> 交换机 -> 目的卡`。
3. 源节点跳转模式 `source-node-jump`：
   - 当源卡和目的卡不在同一个交换机时，先找到目的卡所在交换机。
   - 在源节点中找到所有连接该交换机的卡。
   - 生成多条等价路径：`源卡 -> 源节点内候选卡 -> 目的交换机 -> 目的卡`。
   - 多条等价路径在流量模拟时均分流量。
4. 目的节点跳转模式 `destination-node-jump`：
   - 当源卡和目的卡不在同一个交换机时，先通过源卡所在交换机到达目的节点中的同号卡。
   - 再在目的节点内从同号卡跳到目的卡。
   - 路径为：`源卡 -> 源交换机 -> 目的节点同号卡 -> 目的卡`。

2D 拓扑额外支持两种路由模式：

5. 源 2DFM 跳转模式 `source-2dfm-jump`：
   - 源卡和目的卡不在同一 2D FM 域时，先在源 2D FM 域内找到与目的卡连接同一交换机的候选卡。
   - 先通过节点内 FM 和节点间同号卡 2D FM 跳到候选卡。
   - 再通过交换机跳到目的卡。
   - 如果候选卡有多张，则形成多条等价路径，流量模拟时均分流量。
6. 目的 2DFM 跳转模式 `destination-2dfm-jump`：
   - 源卡和目的卡不在同一 2D FM 域时，先通过源交换机跳到目的 2D FM 域内与源卡同交换机分组的候选卡。
   - 再在目的 2D FM 域内路由，方式为先走同节点内 FM，再走不同节点间同号卡 FM。
   - 该模式也可能产生多条等价路径，流量模拟时同样均分流量。

输出：

- `routes.txt`：任意两张卡之间的有向路由记录。

### 3. 流量模拟与卡带宽效率

通信域内采用有向 All2All：

- 通信域内任意两张不同卡之间发送 1 份流量。
- 如果一对源目的卡之间有多条等价路径，则这 1 份流量在等价路径之间均分。
- 每条路径经过的每条有向链路都会累加承载流量。
- 物理链路按双工处理，`A -> B` 和 `B -> A` 的流量与负载分开记录，不互相叠加。
- 每条有向链路负载为：`该方向链路承载流量 / 链路带宽`。

通信域大小：

- 默认使用集群总卡数的所有因数，但不记录通信域大小为 1 的结果。
- 也可以用 `--domain-size` 指定一个或多个通信域大小。
- 指定的通信域大小必须能整除集群总卡数。

关注卡：

- 默认关注 `node0-card0`。
- 可通过 `--focus-card` 修改。
- 主模拟报告重点打印关注卡的带宽效率和关注卡出方向相连链路的负载数组。

带宽效率计算：

1. 只查看关注卡出方向链路，例如 `node0-card0 -> neighbor`。
2. 找到关注卡出方向链路中负载最重的链路，负载记为 `max_load`。
3. 负载最重链路的分母项使用它真实承载的出方向流量。
4. 其他出方向链路的分母项使用：`max_load * 该链路带宽`。
5. 将所有分母项相加，得到 `focus_card_efficiency_denominator`。
6. 带宽效率为：

```text
focus_card_bandwidth_efficiency =
    focus_card_sent_flows / focus_card_efficiency_denominator
```

其中 `focus_card_sent_flows = domain_size - 1`。

输出：

- `simulation.txt`：关注卡带宽效率报告。
- `all_link_traffic.txt`：所有有向链路的流量和负载明细。

## 安装依赖

```powershell
pip install -r requirements.txt
```

依赖包括：

- `networkx`：拓扑图建模。
- `plotly`：交互式 HTML 拓扑可视化。
- `pytest`：测试。

## 快速开始

生成默认拓扑和关注卡带宽效率模拟报告：

```powershell
python main.py
```

使用源节点跳转模式：

```powershell
python main.py --nodes 3 --cards 4 --switches 2 --routing-mode source-node-jump
```

使用目的节点跳转模式，并指定通信域大小为 4：

```powershell
python main.py --nodes 3 --cards 4 --switches 2 --routing-mode destination-node-jump --domain-size 4
```

生成 2D FullMesh + Clos 拓扑：

```powershell
python main.py --topology-type 2d-fm-clos --nodes 4 --cards 4 --switches 2 --fm2d-domain-size 2 --routing-mode destination-2dfm-jump
```

指定多个通信域大小：

```powershell
python main.py --nodes 3 --cards 4 --switches 2 --domain-size 3 --domain-size 6
```

也可以把拓扑、路由、输出和时延参数放到 JSON 配置文件中：

```powershell
python main.py --config run_config.json
```

示例：

```json
{
  "topology": {
    "type": "2d-fm-clos",
    "nodes": 256,
    "cards": 8,
    "switches": 2,
    "intra_bandwidth": 100,
    "switch_bandwidth": 1400,
    "fm2d_domain_size": 128,
    "fm2d_bandwidth": 100
  },
  "routing_mode": "source-2dfm-jump",
  "domain_sizes": [128, 2048],
  "focus_card": "node0-card0",
  "outputs": {
    "topology": "topology.html",
    "simulation": "simulation.txt"
  },
  "latency": {
    "switch_forward_latency_ns": 300,
    "card_forward_latency_ns": 80,
    "optical_module_latency_ns": 5,
    "npu_processing_latency_ns": 1000,
    "intra_1dfm_link_length_m": 1,
    "fm2d_link_length_m": 2,
    "switch_link_length_m": 10
  }
}
```

指定输出文件。注意：`--simulation-output` 默认只计算关注卡相关链路，使用快速聚合算法，不展开全网所有等价路径，也不会遍历与关注卡无关的卡对。`--routes-output` 默认只写代表性路由样本；全量路由需要额外加 `--all-routes`，大规模拓扑不建议开启。`--all-links-output` 会写全有向链路明细，需要完整统计全网链路，大规模拓扑也不建议开启。

```powershell
python main.py `
  --nodes 3 `
  --cards 4 `
  --switches 2 `
  --routing-mode source-node-jump `
  --output topology.html `
  --routes-output routes_source_node_jump.txt `
  --simulation-output simulation_source_node_jump.txt `
  --all-links-output all_link_traffic_source_node_jump.txt
```

大规模仿真会默认在命令行打印进度条，例如当前通信域、已处理卡对数和百分比。可以用 `--progress-interval` 控制慢进度刷新间隔，用 `--no-progress` 关闭进度输出。仿真默认使用当前机器 CPU 核数并行计算，也可以用 `--workers` 手动指定进程数。

例如 2048 总卡、通信域 EP=128 时，建议只输出关注卡带宽效率报告：

```bash
python main.py --topology-type 2d-fm-clos --nodes 256 --cards 8 --switches 2 --fm2d-domain-size 128 --domain-size 128 --routing-mode source-2dfm-jump --simulation-output simulation_ep128.txt
```

## 输入参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--config` | 未指定 | JSON 运行配置文件，可同时指定拓扑、路由、输出、通信域和时延参数。 |
| `--nodes` | `4` | 计算节点数量，即拓扑参数 `M`。 |
| `--cards` | `8` | 每个节点的网卡数量，即拓扑参数 `N`。 |
| `--switches` | `2` | 交换机数量，即拓扑参数 `X`。要求 `X <= N`。 |
| `--topology-type` | `1d-fm-clos` | 拓扑类型，可选 `1d-fm-clos` 或 `2d-fm-clos`。 |
| `--intra-bandwidth` | `200.0` | 同一节点内卡到卡 FULLMesh 链路带宽。 |
| `--switch-bandwidth` | `100.0` | 卡到交换机链路带宽。 |
| `--fm2d-domain-size` | 等于 `--cards` | 2D FM 域内包含的计算节点数量，仅 `2d-fm-clos` 使用。 |
| `--fm2d-bandwidth` | `200.0` | 2D FM 域内跨节点同号卡链路带宽。 |
| `--visualization-detail` | `simplified` | 可视化详细程度，可选 `simplified` 或 `full`。 |
| `--routing-mode` | `source-node-jump` | 路由模式，可选 `source-node-jump`、`destination-node-jump`、`source-2dfm-jump`、`destination-2dfm-jump`。 |
| `--domain-size` | 未指定 | 通信域大小。可重复传入多个值；未指定时使用总卡数的所有因数并跳过 1。 |
| `--focus-card` | `node0-card0` | 带宽效率报告关注的网卡。 |
| `--output` | `topology.html` | 交互式拓扑图输出路径；当总卡数 `M * N > 256` 时自动跳过生成。 |
| `--routes-output` | 未指定 | 代表性路由记录输出路径。默认采样两个 1DFM 或 2DFM 域，避免大规模拓扑写出全量卡对。 |
| `--all-routes` | `False` | 与 `--routes-output` 配合使用，写出任意两张卡之间的全量路由记录。大规模拓扑慎用。 |
| `--simulation-output` | `simulation.txt` | 关注卡带宽效率报告输出路径；默认使用快速聚合算法，只统计关注卡相关链路。 |
| `--all-links-output` | 未指定 | 全有向链路流量与负载明细输出路径。大规模拓扑慎用。 |
| `--latency-config` | 未指定 | 独立 JSON 时延配置文件；若同时存在，会覆盖 `--config` 中的 `latency` 配置块。 |
| `--no-progress` | `False` | 关闭命令行仿真进度输出。 |
| `--progress-interval` | `5.0` | 慢进度刷新间隔，单位秒；百分比里程碑仍会输出。 |
| `--workers` | 当前机器 CPU 核数 | 仿真使用的工作进程数；Linux 上可直接利用多核，受限环境无法创建进程池时会自动回退到单进程批处理。 |

## 输出文件说明

典型并行域下的带宽效率公式和计算示例见：

[parallel_domain_efficiency_examples.md](parallel_domain_efficiency_examples.md)

### 拓扑图 HTML

默认文件：

```text
topology.html
```

内容：

- 计算节点、网卡、交换机的交互式图。
- 节点内网卡按环形展示。
- 简略模式下，交换机位于中间，节点上下交错摆放，并省略部分重复边用于示意。
- 鼠标悬停可查看节点类型、所属节点、卡编号、交换机分组、链路带宽等信息。
- 当总卡数 `M * N` 超过 256 时，程序默认不生成拓扑图，只继续输出仿真结果和可选的路由样本，避免大规模图形生成拖慢运行且难以阅读。

### 路由记录文件

默认文件：

```text
routes.txt
```

示例：

```text
node0-card0 -> node1-card3 | source_node_jump | node0-card0 -> node0-card2 -> switch1 -> node1-card3 ; node0-card0 -> node0-card3 -> switch1 -> node1-card3
```

字段含义：

- 第一段：源卡到目的卡。
- 第二段：路由类型。
- 第三段：具体路径。多条等价路径用 `;` 分隔。

### 带宽效率报告

默认文件：

```text
simulation.txt
```

示例：

```text
routing_mode: source-node-jump
focus_card: node0-card0

| 通信域 D | S = D - 1 | 瓶颈链路 | L_max | denominator | efficiency | focus_card_link_traffic |
|---:|---:|---|---:|---:|---:|---|
| 2 | 1 | N0_C0 -> N0_C1 | 0.005000 | 7.500000 | 0.133333 | [1, 0, 0, 0, 0, 0, 0, 0] |
| 4 | 3 | N0_C0 -> N0_C1 | 0.005000 | 7.500000 | 0.400000 | [1, 1, 1, 0, 0, 0, 0, 0] |

domain_size: 4
focus_card_sent_flows: 3
focus_card_port_count: 8
focus_card_efficiency_denominator: 7.500000
focus_card_bandwidth_efficiency: 0.400000
focus_card_link_loads: [N0_C0->N0_C1=0.005, N0_C0->N0_C2=0.005, N0_C0->N0_C3=0.005, N0_C0->N0_C4=0, N0_C0->N0_C5=0, N0_C0->N0_C6=0, N0_C0->N0_C7=0, N0_C0->S0=0]
focus_card_link_traffic: [1, 1, 1, 0, 0, 0, 0, 0]
max_loaded_adjacent_link: N0_C0 -> N0_C1
max_adjacent_link_load: 0.005000
```

其中 `focus_card_link_traffic` 按固定顺序排列：先列关注卡到同节点内其他卡的出方向流量，卡序号由小到大；再列关注卡到交换机的出方向流量，交换机序号由小到大。

如果指定了时延配置，表格会额外增加 `single_rtt_latency_ns` 列，表示该通信域内任意两张卡单次 RTT 的最大静态时延。每个通信域的详情中还会输出触发最大时延的卡对和路径：

```text
single_rtt_latency_ns: 216.000000
single_rtt_latency_pair: node0-card0 -> node1-card0
single_rtt_latency_path: node0-card0 -> switch0 -> node1-card0
```

时延单位均为 ns。链路传播时延按 `链路长度(m) * 5ns` 计算；只有经过交换机的链路会计算光模块时延，且每段卡到交换机链路两端各加一次光模块时延。单次 RTT 计算方式为：

```text
single_rtt = one_way_path_latency * 2 + npu_processing_latency
```

### 全链路流量文件

默认文件：

```text
all_link_traffic.txt
```

示例：

```text
domain_size: 12
  node0-card0 -> node0-card1 | traffic=1.000000 | load=0.005000
  node0-card1 -> node0-card0 | traffic=1.000000 | load=0.005000
  node0-card0 -> switch0 | traffic=8.000000 | load=0.080000
```

字段含义：

- `traffic`：该方向链路承载的流量份数。
- `load`：该方向链路承载流量除以链路带宽。

## 参数合法性

程序会检查以下条件：

- `--nodes`、`--cards`、`--switches` 必须为正整数。
- `--switches` 不能大于 `--cards`。
- `2d-fm-clos` 模式下，`--nodes` 必须能被 `--fm2d-domain-size` 整除。
- `--intra-bandwidth`、`--switch-bandwidth` 必须为正数。
- `--fm2d-bandwidth` 必须为正数。
- `--domain-size` 必须为正数，且能整除集群总卡数。
- `--focus-card` 必须是拓扑中存在的卡，例如 `node0-card0`。

## 测试

运行全部测试：

## SparseClos / BST 配置示例

`sparse-clos` 拓扑使用 BST 五元组 `(v, r, b, k, lambda)` 表征，其中 `b` 是实际 switch block 数量。当前实现支持 `lambda = 1`、`k = 2`，以及 `k = 3` 且 `v = 6t + 3` 的 Steiner Triple System 生成方式。

`switch_port_num` 和 `k` 用于推导 cluster 规模：

```text
cluster_size = floor(switch_port_num / k)
```

例如 `switch_port_num = 16, k = 2` 时，`cluster_size = 8`。下面配置会推导出 `v = 3`、`b = 3`，并输出 `D = 8` 和非整除总卡数的 `D = 16`：

```json
{
  "topology": {
    "type": "sparse-clos",
    "sparse_clos": {
      "bst_r": 2,
      "bst_k": 2,
      "bst_lambda": 1,
      "bst_v": 3,
      "bst_b": 3,
      "switch_port_num": 16,
      "cluster_internal_mode": "fullmesh-plus-switch"
    },
    "intra_bandwidth": 50.0,
    "switch_bandwidth": 100.0
  },
  "routing_mode": "shortest-path",
  "domain_sizes": [8, 16],
  "focus_card": "node0-card0",
  "outputs": {
    "topology": "topology_sparseclos.html",
    "simulation": "simulation_sparseclos.txt"
  },
  "latency": {
    "switch_forward_latency_ns": 10.0,
    "card_forward_latency_ns": 7.0,
    "optical_module_latency_ns": 2.0,
    "npu_processing_latency_ns": 100.0,
    "intra_1dfm_link_length_m": 3.0,
    "fm2d_link_length_m": 5.0,
    "switch_link_length_m": 4.0
  }
}
```

运行：

```powershell
python main.py --config sparse_clos_config.json
```

如果不显式配置 `domain_sizes`，SparseClos 默认先输出 cluster 内可整除的 EP，再输出 cluster 规模的倍数，直到最大规模。例如 `cluster_size = 64` 时默认为：

```text
2, 4, 8, 16, 32, 64, 128, 192, 256, ...
```

```powershell
python -m pytest tests -v
```

当前测试覆盖：

- 拓扑参数校验。
- FULLMesh 和交换机链路构建。
- 环形可视化布局。
- 四类路由规则。
- 2D FullMesh + Clos 拓扑和 2D 路由规则。
- All2All 流量模拟。
- 等价路径流量均分。
- 卡带宽效率计算。
- CLI 输出文件生成。
