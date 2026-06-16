# SparseClos BST 拓扑设计

## 范围

在现有多轨网络带宽效率工具中新增第三种拓扑类型：`sparse-clos`。该拓扑用于建模 SparseClos / BST 平衡稀疏树，当前只考虑一层上方交换机。实现时应尽量复用现有的图构建、路由、All2All 流量仿真、带宽效率、时延、CLI 和 HTML 导出路径。

基础 SparseClos 设计覆盖拓扑、最短路径、带宽效率、时延和可视化。固定绕路路由已经拆到独立设计文档 `2026-06-16-sparse-clos-detour-routing-design.md`，本设计中的 cluster 布局语义也需要被绕路实现复用。

## BST 参数

SparseClos 使用平衡不完全区组设计（BIBD）的五元组表示：

```text
(v, r, b, k, lambda)
```

字段含义如下：

- `v`：cluster 数量。
- `r`：每张卡连接上方交换机的端口数，也是每个 cluster 参与的 switch block 数。
- `b`：switch block 数量，也就是 SparseClos 上方交换机数量。
- `k`：每个交换机连接的 cluster 数量。
- `lambda`：任意两个 cluster 共同连接到的交换机数量。

当前阶段只支持 `lambda = 1`。这里的 `lambda = 1` 表示上方只有一层交换机，且任意两个 cluster 恰好共享一个交换机。

用户必填参数为 `r`、`k` 和 `switch_port_num`。如果配置中显式提供 `v`、`b` 或 `lambda`，则这些值作为校验项，必须和下方公式推导出的值一致。

## BST 公式

BIBD 通用关系为：

```text
r * (k - 1) = lambda * (v - 1)
b * k = v * r
b * C(k, 2) = lambda * C(v, 2)
```

当前 `lambda = 1` 时：

```text
v = r * (k - 1) + 1
b = v * r / k
b = C(v, 2) / C(k, 2)
```

`b` 表示实际需要实例化的 SparseClos switch 组合数，不是从 `v` 个 cluster 中任选 `k` 个的全部组合数。例如：

```text
r = 16
k = 3
lambda = 1
v = 16 * (3 - 1) + 1 = 33
b = 33 * 16 / 3 = 176
C(33, 3) = 5456 个可能三元组，但 BST 只使用其中 176 个合法 block。
```

所有推导值必须为整数。整数条件是必要条件，但不保证一定存在合法 block 组合。实现需要先生成支持范围内的 block，然后校验每一对无序 cluster 恰好出现 `lambda` 次，且每个 cluster 恰好出现 `r` 次。

第一版内置 block 生成至少支持：

- `k = 2, lambda = 1`：所有 cluster pair 都生成一个 switch block。
- `k = 3, lambda = 1`：使用 Steiner Triple System，覆盖合法的 `v`，包括 `v = 33`。对于 `v = 6t + 3` 的情况，可以使用 Bose construction；其他合法三元组系统可以后续增加确定性构造或有边界的 exact-cover fallback。

不支持的 `(v, r, b, k, lambda)` 组合必须报清晰错误，不能静默生成错误拓扑。

## Cluster 规模

cluster 规模由交换机端口数和 `k` 推导：

```text
cluster_size = floor(switch_port_num / k)
```

示例：

```text
switch_port_num = 128
k = 2
cluster_size = floor(128 / 2) = 64 cards
```

总卡数为：

```text
total_cards = v * cluster_size
```

在现有图模型中，第一版 SparseClos 的一个 cluster 映射为一个逻辑 compute node。因此默认布局下 `sparse-clos` 的等价拓扑维度为：

```text
M = v
N = cluster_size
X = b
```

后续需要支持另一种 cluster 到物理节点的布局方式，见下一节“Cluster 布局模式”。

## Cluster 布局模式

SparseClos 的 BST 逻辑仍然以 `v` 个 cluster、每个 cluster `cluster_size` 张卡为准。新增一个配置项用于决定这些逻辑 cluster 如何映射到图中的物理节点和网卡。

推荐配置名：

```text
--cluster-layout contiguous|same-index-across-nodes
```

JSON 中放在 `topology.sparse_clos.cluster_layout` 下。默认值为 `contiguous`，保持当前行为。

### `contiguous`：连续 cluster 布局

这是当前实现方式：

```text
physical_node_count = v
cards_per_physical_node = cluster_size
logical_cluster_id = physical_node_index
cluster_card_index = card_index
```

例如 `v = 8, cluster_size = 64` 时，图中有 8 个逻辑节点，每个节点 64 张卡。`cluster0` 包含 `node0-card0 ... node0-card63`。

`fullmesh-plus-switch` 模式下，每个 cluster 内按连续 8 张卡切分 8P fullmesh 小组：

```text
cluster0: node0-card0..7, node0-card8..15, ...
```

### `same-index-across-nodes`：同号卡跨节点布局

这是新增布局，用于表达用户常用的物理形态：

```text
physical_node_count = cluster_size
cards_per_physical_node = v
logical_cluster_id = card_index
cluster_card_index = physical_node_index
```

例如 `v = 8, cluster_size = 64` 时，图中有 64 个物理节点，每个节点 8 张卡。逻辑 cluster 不再等于物理节点，而是由所有节点的同号卡组成：

```text
cluster0 = node0-card0, node1-card0, ..., node63-card0
cluster1 = node0-card1, node1-card1, ..., node63-card1
...
cluster7 = node0-card7, node1-card7, ..., node63-card7
```

SparseClos 上方交换机连接规则保持不变：每个 BST block 仍然连接 `k` 个逻辑 cluster；当某个 switch block 包含 `cluster c` 时，该 switch 连接所有 `card_index = c` 的卡，也就是 64 个物理节点上的同号卡。

该布局下，图节点需要同时保留两组语义：

- 物理语义：`compute_index` 表示物理节点编号，`card_index` 表示物理节点内 0..v-1 的卡槽。
- SparseClos 语义：新增 `cluster_index` 表示逻辑 cluster 编号，新增 `cluster_card_index` 表示该卡在逻辑 cluster 内的位置。

后续路由、仿真、带宽效率、时延和默认 EP 序列都应基于 SparseClos 语义的 `cluster_index` / `cluster_card_index`，不能继续假设 `compute_index == cluster_index`。

### 布局选择对带宽效率的影响

两种布局的总卡数相同：

```text
total_cards = v * cluster_size
```

但物理组织不同，`same-index-across-nodes` 会把一个通信域内的连续卡分散到多个逻辑 cluster 或多个物理节点视角下的不同卡位，能更早使用更多上方交换机端口，因此在部分 EP 下带宽效率会高于 `contiguous`。

该布局下的绕路策略也应不同：物理 8P 内的小通信域仍可通过同节点内其它卡或上方交换机绕路来摊开端口；当 `EP > cards_per_physical_node` 时，通信域已经覆盖多个物理节点，每个物理节点内又包含全部 `v` 个逻辑 cluster 的卡，整体已经可以触达完整的 SparseClos 上方交换机集合。因此大于 8P 的通信域默认不需要跨 cluster 绕路，应使用 shortest-path 的等价多路径分流。

为了让对比有明确含义，报告中应输出布局元数据：

```text
cluster_layout: contiguous | same-index-across-nodes
physical_node_count
cards_per_physical_node
```

## Cluster 内部模式

SparseClos cluster 支持两种内部连接模式。

`fullmesh-plus-switch`：

所有卡同时连接到其所属逻辑 cluster 的 `r` 个 SparseClos 上方交换机，链路带宽使用 `switch_bandwidth`。8P fullmesh 的切分方式取决于 `cluster_layout`：

- `contiguous`：每个逻辑 cluster 按连续的 8 张卡切成若干 8P 小组。每个 8P 小组内部使用 `intra_bandwidth` 建 fullmesh。
- `same-index-across-nodes`：每个物理节点内的 `v` 张卡形成节点内 fullmesh。当前目标场景是 `v = 8`，即单节点 8 卡 fullmesh；这些卡分别属于 8 个不同逻辑 cluster。

该模式要求 `cluster_size` 能被 `8` 整除。如果不能整除，拓扑构建应报校验错误。

对于 `same-index-across-nodes`，还要求 `v = 8`，因为该布局第一版只覆盖“单节点 8 卡，共 `cluster_size` 个节点”的形态。如果后续需要支持单节点非 8 卡，可以把校验从 `v = 8` 扩展为 `cards_per_physical_node = v` 并明确 fullmesh 小组大小。

`switch-only`：

不添加 fullmesh 边。卡只连接到其所属逻辑 cluster 的 `r` 个 SparseClos 上方交换机，链路带宽使用 `switch_bandwidth`。

## SparseClos 交换机边

每个生成出的 BST block 对应一个 SparseClos switch 节点。一个 block 包含 `k` 个逻辑 cluster id。对于 block 内的每个 cluster，该 cluster 的每张卡都连接到这个 switch。

由于每个 cluster 出现在 `r` 个 block 中，所以每张卡都有恰好 `r` 条上方 switch 边。

在 `same-index-across-nodes` 布局下，“cluster 的每张卡”指所有物理节点上的同号卡。例如 block 包含 `cluster0` 和 `cluster3` 时，该 switch 连接 `node0-card0..node63-card0` 以及 `node0-card3..node63-card3`，总计仍为 `k * cluster_size` 张卡。

当 `switch_port_num = 128, k = 2` 时，每个 switch 连接两个 64-card cluster，正好使用 128 个下行卡端口。如果 `switch_port_num` 不能被 `k` 整除，模型使用 floor 后的 `cluster_size`，剩余端口不参与建模。

## 路由

新增路由模式：

```text
shortest-path
```

对于任意源卡和目的卡：

1. 在图中找到所有最小跳数路径。
2. 将所有等价最短路径返回到 `RouteResult.paths`。
3. 现有仿真层会把 1 份流量在这些路径间均分。

对于 `lambda = 1`，不同 cluster 之间恰好共享一个 SparseClos switch，因此跨 cluster 最短路径通常为：

```text
source_card -> shared_switch -> destination_card
```

在同一个 cluster 内，`fullmesh-plus-switch` 模式下，同一个 8P 小组内的两张卡可以直接通过 fullmesh 通信。如果两张卡位于同一 cluster 的不同 8P 小组中，则最短路径通常会通过 SparseClos switch，除非图中存在其他等长路径。

引入 `same-index-across-nodes` 后，路由判断必须改为基于 SparseClos 语义：

- 判断两张卡是否属于同一个逻辑 cluster 时使用 `cluster_index`。
- 选择某张卡连接的上方交换机时使用该卡所属逻辑 cluster 的 BST block。
- `fullmesh-plus-switch` 的直接 fullmesh 边来自物理节点内 8 卡互连，因此同一物理节点内不同 card index 的卡虽然属于不同逻辑 cluster，也可以通过节点内 fullmesh 直接通信。
- 跨逻辑 cluster 的 shortest-path 需要同时考虑两类可能路径：物理节点内 fullmesh 直连路径，以及经共同 SparseClos switch 的路径。如果两类路径跳数相同，仍按等价多路径均分。

固定绕路路由见独立设计文档；实现时同样必须使用 `cluster_index` 区分逻辑 cluster。对于 `same-index-across-nodes`，默认只在物理 8P 内启用卡绕路；`EP > cards_per_physical_node` 时不启用跨 cluster 绕路。

## Domain Size / EP 输出

SparseClos 使用拓扑专属的 EP / domain-size 序列。

定义：

```text
C = cluster_size
T = total_cards = v * C
```

当 `domain_size <= C` 时，只输出能整除 `C` 的值。

当 `domain_size > C` 时，输出 `C` 的倍数，直到 `T`。

例如 `C = 64` 时，默认 domain-size 序列为：

```text
2, 4, 8, 16, 32, 64, 128, 192, 256, ..., T
```

当前仿真器要求 domain size 必须整除总卡数。SparseClos 需要扩展这一点：对不能整除总卡数的 domain size，使用 focus-card domain 模式，只计算包含 focus card 的前 `D` 张卡形成的通信域效率。这样即使总卡数不能被 `192` 整除，`D = 192` 仍然有明确含义。

`same-index-across-nodes` 布局下，默认卡排序建议使用物理节点优先：

```text
node0-card0, node0-card1, ..., node0-card7,
node1-card0, node1-card1, ..., node1-card7,
...
```

因此 `EP = 8` 时刚好对应一个物理节点内的 8 张卡，`EP = 16` 对应两个物理节点内的 16 张卡。这种通信域选择会天然覆盖多个逻辑 cluster，相比 `contiguous` 布局更容易使用多组 SparseClos 上联交换机。报告中应保留该排序假设，避免和 `contiguous` 的 cluster 内连续卡语义混淆。

## 带宽效率

带宽效率继续复用现有公式和报告结构。

对每个 domain size，在选中的通信域内运行有向 All2All：

```text
focus_card_sent_flows = domain_size - 1
load(edge) = traffic(edge) / bandwidth(edge)
L_max = focus card 出方向相邻边中的最大 load
denominator =
    traffic(max_loaded_edge)
    + sum(L_max * bandwidth(edge), for each other focus-card outgoing edge)
efficiency = focus_card_sent_flows / denominator
```

报告继续包含现有关键字段：

- `domain_size`
- `focus_card_sent_flows`
- `focus_card_port_count`
- `focus_card_efficiency_denominator`
- `focus_card_bandwidth_efficiency`
- `focus_card_link_loads`
- `focus_card_link_traffic`
- `max_loaded_adjacent_link`
- `max_adjacent_link_load`

SparseClos 报告还应包含推导出的 BST 元数据：

```text
bst_v
bst_r
bst_b
bst_k
bst_lambda
cluster_size
total_cards
cluster_layout
physical_node_count
cards_per_physical_node
```

## 时延

SparseClos 需要复用现有时延配置，并在配置存在时输出 `single_rtt_latency_ns`。

时延实现应基于选中的 shortest path，并套用现有的链路和节点代价模型：

- 8P fullmesh 内部边使用 `intra_1dfm_link_length_m`。
- 卡到 SparseClos switch 的边使用 `switch_link_length_m`，并和现有 switch 链路一样，在两端加入光模块时延。
- 路径经过 switch 时计入 switch 转发时延。
- 路径把某张卡作为中转卡时计入 card 转发时延。
- NPU processing latency 继续按现有 single-RTT 公式加入。

报告保留现有字段：

- `single_rtt_latency_ns`
- `single_rtt_latency_pair`
- `single_rtt_latency_path`

## 可视化

SparseClos 可视化需要把 cluster 内部连接和 cluster 间连接分开展示。

cluster 间视图：

- 将 cluster 画成紧凑节点或方框。
- 将 SparseClos switch 画成 switch 节点。
- 展示 cluster 与 switch 的 membership 关系，不展开每个 cluster 内的所有卡。
- cluster 间连接图中不体现 cluster 内 64 张卡的细节。
- hover 信息展示 cluster id、cluster size、switch id 和 BST block membership。

cluster 内视图：

- 展示一个代表性 cluster。
- `fullmesh-plus-switch` 模式下，展示 cluster 内的 8P fullmesh 小组。
- `switch-only` 模式下，展示无内部 fullmesh 的卡集合。
- 通过文本或 hover 元数据标识内部模式和每卡 SparseClos 端口数 `r`。

`same-index-across-nodes` 布局需要调整可视化语义：

- cluster 间视图仍按逻辑 cluster 展示，cluster 节点数量为 `v`。
- 代表性内部视图不再展示“一个逻辑 cluster 内 64 张卡的 8P 小组”，而应展示一个物理节点内的 8 张卡 fullmesh。
- 需要在图中标识每张物理节点内卡所属的逻辑 cluster，例如 `node0-card3 -> cluster3`。
- hover 信息应同时显示 `physical_node`、`card_index`、`cluster_index`、`cluster_card_index` 和连接的 SparseClos switch 列表。

生成的 HTML 可以用一个 Plotly figure 包含两个子视图，也可以用上下两个 figure，只要 cluster 级 SparseClos 结构保持可读即可。

## CLI 与配置

新增 SparseClos 相关 CLI 参数：

```text
--topology-type sparse-clos
--bst-r <int>
--bst-k <int>
--bst-lambda <int>          # 默认 1；第一版只支持 1
--bst-v <int>               # 可选校验值
--bst-b <int>               # 可选校验值
--switch-port-num <int>
--cluster-internal-mode fullmesh-plus-switch|switch-only
--cluster-layout contiguous|same-index-across-nodes
```

继续复用现有带宽参数：

```text
--intra-bandwidth
--switch-bandwidth
```

JSON 配置中可以在 `topology` 下新增 `sparse_clos` 对象，也可以支持与 CLI 同名的扁平字段。命令执行 summary 中应打印推导出的 BST 参数和 cluster 规模。

JSON 示例：

```json
{
  "topology": {
    "type": "sparse-clos",
    "sparse_clos": {
      "bst_r": 7,
      "bst_k": 2,
      "bst_lambda": 1,
      "switch_port_num": 128,
      "cluster_internal_mode": "fullmesh-plus-switch",
      "cluster_layout": "same-index-across-nodes"
    },
    "intra_bandwidth": 50.0,
    "switch_bandwidth": 50.0
  },
  "routing": {
    "mode": "shortest-path"
  }
}
```

该示例推导：

```text
v = 8
cluster_size = 64
physical_node_count = 64
cards_per_physical_node = 8
total_cards = 512
```

## 校验

需要尽早拒绝非法配置：

- `bst_r`、`bst_k` 和 `switch_port_num` 必须是正整数。
- `bst_k` 至少为 `2`。
- `bst_lambda` 第一版必须为 `1`。
- 推导出的 `bst_v` 和 `bst_b` 必须是整数。
- 显式传入的 `bst_v` 或 `bst_b` 必须与推导值一致。
- `cluster_size` 必须为正数。
- `fullmesh-plus-switch` 要求 `cluster_size % 8 == 0`。
- `cluster_layout` 必须为 `contiguous` 或 `same-index-across-nodes`。
- `same-index-across-nodes` 第一版要求 `v = 8`，以明确表示“单节点 8 卡，共 `cluster_size` 个节点”。
- `same-index-across-nodes` 下 `cards_per_physical_node = v`，因此物理节点内卡数必须与逻辑 cluster 数一致。
- 生成出的 BST blocks 必须通过 pair-count 和 cluster-degree 校验。
- 不支持的 block 生成组合必须报清晰错误。

## 验证

新增测试覆盖：

- `(v, r, b, k, lambda)` 公式推导。
- `r = 16, k = 3` 推导出 `v = 33`、`b = 176`。
- 生成的 `k = 3, v = 33` blocks 有 176 个 switch，每个 cluster degree 为 16，且任意 cluster pair 恰好出现一次。
- `switch_port_num = 128, k = 2` 推导出 `cluster_size = 64`。
- `k = 2` 和一个小规模 `k = 3` SparseClos 图的节点数、边数。
- 两种 cluster internal mode 正确创建或省略 8P fullmesh 边。
- `cluster_layout = contiguous` 保持现有 `v` 个逻辑节点、每节点 `cluster_size` 张卡的行为。
- `cluster_layout = same-index-across-nodes` 生成 `cluster_size` 个物理节点、每节点 `v` 张卡，并正确写入 `cluster_index` 和 `cluster_card_index`。
- `same-index-across-nodes` 下同一物理节点内 8 张卡存在 fullmesh 边，而同一逻辑 cluster 的跨物理节点同号卡之间不应因为 fullmesh 模式直接相连。
- `same-index-across-nodes` 下 SparseClos switch block 连接的是对应逻辑 cluster 的所有同号卡。
- shortest-path 路由返回所有等价最短路径，并在仿真中均分流量。
- shortest-path 和 detour-routing 不再依赖 `compute_index == cluster_index`，而是读取 `cluster_index` 判断 SparseClos cluster 关系。
- `same-index-across-nodes` 下 `detour-routing` 只对物理 8P 内通信域启用 `card_detour`，当 `EP > cards_per_physical_node` 时回退 shortest-path，不输出 `cluster_detour`。
- SparseClos 默认 domain sizes 符合 cluster divisor 与 cluster multiple 规则。
- `same-index-across-nodes` 下默认卡排序为物理节点优先，`EP = 8` 覆盖一个物理节点内 8 张卡。
- 带宽效率报告包含 SparseClos 推导出的 BST 元数据。
- SparseClos 配置时延参数后输出 latency 字段。
- HTML 导出包含 cluster 间视图和 cluster 内代表视图。
