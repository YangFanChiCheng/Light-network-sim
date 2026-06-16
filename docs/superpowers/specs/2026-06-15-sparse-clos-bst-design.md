# SparseClos BST 拓扑设计

## 范围

在现有多轨网络带宽效率工具中新增第三种拓扑类型：`sparse-clos`。该拓扑用于建模 SparseClos / BST 平衡稀疏树，当前只考虑一层上方交换机。实现时应尽量复用现有的图构建、路由、All2All 流量仿真、带宽效率、时延、CLI 和 HTML 导出路径。

第一版只支持最短路径路由。绕路路由不在本设计范围内，也不应暴露为可工作的模式。

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

在现有图模型中，SparseClos 的一个 cluster 映射为一个逻辑 compute node。因此 `sparse-clos` 下的等价拓扑维度为：

```text
M = v
N = cluster_size
X = b
```

## Cluster 内部模式

SparseClos cluster 支持两种内部连接模式。

`fullmesh-plus-switch`：

每个 cluster 按连续的 8 张卡切成若干 8P 小组。每个 8P 小组内部使用 `intra_bandwidth` 建 fullmesh。所有卡同时连接到其所属的 `r` 个 SparseClos 上方交换机，链路带宽使用 `switch_bandwidth`。

该模式要求 `cluster_size` 能被 `8` 整除。如果不能整除，拓扑构建应报校验错误。

`switch-only`：

cluster 内不添加 fullmesh 边。卡只连接到其所属的 `r` 个 SparseClos 上方交换机，链路带宽使用 `switch_bandwidth`。

## SparseClos 交换机边

每个生成出的 BST block 对应一个 SparseClos switch 节点。一个 block 包含 `k` 个 cluster id。对于 block 内的每个 cluster，该 cluster 的每张卡都连接到这个 switch。

由于每个 cluster 出现在 `r` 个 block 中，所以每张卡都有恰好 `r` 条上方 switch 边。

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

绕路路由本阶段不实现。

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
```

继续复用现有带宽参数：

```text
--intra-bandwidth
--switch-bandwidth
```

JSON 配置中可以在 `topology` 下新增 `sparse_clos` 对象，也可以支持与 CLI 同名的扁平字段。命令执行 summary 中应打印推导出的 BST 参数和 cluster 规模。

## 校验

需要尽早拒绝非法配置：

- `bst_r`、`bst_k` 和 `switch_port_num` 必须是正整数。
- `bst_k` 至少为 `2`。
- `bst_lambda` 第一版必须为 `1`。
- 推导出的 `bst_v` 和 `bst_b` 必须是整数。
- 显式传入的 `bst_v` 或 `bst_b` 必须与推导值一致。
- `cluster_size` 必须为正数。
- `fullmesh-plus-switch` 要求 `cluster_size % 8 == 0`。
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
- shortest-path 路由返回所有等价最短路径，并在仿真中均分流量。
- SparseClos 默认 domain sizes 符合 cluster divisor 与 cluster multiple 规则。
- 带宽效率报告包含 SparseClos 推导出的 BST 元数据。
- SparseClos 配置时延参数后输出 latency 字段。
- HTML 导出包含 cluster 间视图和 cluster 内代表视图。
