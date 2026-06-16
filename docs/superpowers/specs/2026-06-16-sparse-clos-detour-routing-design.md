# SparseClos 固定绕路路由设计

## 范围

在现有 `sparse-clos` 拓扑、最短路径路由和带宽效率计算基础上，新增一种固定绕路路由模式，用于改善部分通信域 EP 下的低效率问题。第一版聚焦 `k=2, lambda=1, fullmesh-plus-switch` 这类规则 SparseClos，优先覆盖当前观察到的两个低效场景：

- 小通信域：`EP < 8`，最短路径只使用少量 8P fullmesh 边，端口利用率很低。
- 多 cluster 通信域：`EP > cluster_size` 且不是整网 all2all，最短路径会把跨 cluster 流量集中到 cluster pair 共享的交换机上。

整网 all2all 不作为绕路优化目标。整网场景已经覆盖所有 cluster，绕路会引入额外流量并且更容易造成中转链路竞争，第一版保持使用最短路径。

## 目标

新增路由模式：

```text
detour-routing
```

该模式应满足：

- 路由是固定的、可复现的，不依赖运行时拥塞状态。
- 对同一类源目的关系使用同一组候选路径和分流比例。
- 绕路模式的效率计算必须考虑通信域内所有有向链路的负载，不能只看 focus-card 第一跳。
- 报告继续保留现有 focus-card 指标，同时新增 all-link 指标用于判断绕路是否真的降低全域瓶颈。
- 路由报告可以输出候选路径，便于检查绕路是否按预期工作。
- 第一版不追求所有 EP 的全局最优。当前实现覆盖 `EP < 8` 的卡绕路和 `EP > cluster_size` 的 cluster 绕路；整网 all2all 自动回退 shortest-path。

## 非目标

第一版不实现以下能力：

- 动态拥塞感知路由。
- 对任意 `(v, r, k, lambda)` 的通用最优线性规划求解。
- 对整网 all2all 的绕路。
- 交换机内部排队、时变链路状态或包级仿真。
- 修改拓扑生成规则。

## 背景：当前效率为什么低

当前 shortest-path 对每个源目的卡对返回所有等价最短路径并均分流量。

对 `r=7, k=2, switch_port_num=128, fullmesh-plus-switch`：

- `cluster_size = 64`
- `v = 8`
- `b = 28`
- 每张卡有 `7` 条 cluster 内 8P fullmesh 相邻边，加 `7` 条上联交换机边，focus card 相邻端口共 `14` 条。

### EP=2

如果通信域只有 `node0-card0` 和 `node0-card1`，最短路径为：

```text
node0-card0 -> node0-card1
```

focus card 只使用 1 条 fullmesh 边，效率为：

```text
1 / 14 = 0.071429
```

### EP=128

如果通信域覆盖两个 64-card cluster，两个 cluster 之间在 `k=2, lambda=1` 下只共享一个交换机。最短路径跨 cluster 流量会集中到这个共享交换机，导致一条上联边成为热点。

绕路的基本思路是让流量先进入其它中转 cluster，再由中转 cluster 转发到目的 cluster。这样源 cluster 的多个上联交换机都能被使用，但中转 cluster 的入链路和出链路也会承担额外流量，因此需要固定分流而不是简单增加路径。

## 路径模板

### Cluster 布局兼容性

SparseClos 后续支持两种 cluster 布局：

- `contiguous`：逻辑 cluster 等于图中的 compute node，当前实现方式。
- `same-index-across-nodes`：物理形态为 `cluster_size` 个节点、每节点 `v` 张卡；所有物理节点的同号卡组成一个逻辑 cluster。

因此 detour-routing 不能继续假设 `compute_index == cluster_index`。所有跨 cluster 判断、共享 switch 查询和中转 cluster 选择都必须使用卡节点上的 `cluster_index` 属性；物理节点内 fullmesh 判断则使用 `compute_index`。

在 `same-index-across-nodes` 下：

- 绕路只在物理 8P 内的小通信域有意义。`EP <= cards_per_physical_node` 且通信域落在同一个物理节点内时，可使用 `card_detour`，候选中转卡来自同一个物理节点的其它卡。
- `EP > cards_per_physical_node` 时不启用 `cluster_detour`。该布局下每个物理节点内已经包含全部 `v` 个逻辑 cluster 的一张卡；当通信域超过一个 8P 后，流量天然覆盖多个物理节点和所有逻辑 cluster，每张卡通过其同号卡 cluster 能连接到完整的 SparseClos 上方交换机集合，继续绕到第三方 cluster 会引入额外共享链路和时延，预期收益不大。
- 对 `EP > cards_per_physical_node` 的通信域，`detour-routing` 应回退为 `shortest-path`，报告中的 `route_types` / `detour_types` 输出 `none`。
- 如果后续仍需要实验跨 cluster 绕路，应作为单独显式实验选项，而不是 `same-index-across-nodes` 的默认 detour 行为。

因此，下面的中转 cluster 选择规则只适用于 `contiguous` 布局下的 `cluster_detour`。如果未来开启 `same-index-across-nodes` 的实验性跨 cluster 绕路，中转卡选择需要输出物理节点和卡槽均确定的 card id。推荐规则为：

```text
relay_physical_node = (source_physical_node + destination_physical_node + intermediate_cluster_id) % cluster_size
relay_card = node{relay_physical_node}-card{intermediate_cluster_id}
```

这样每个中转逻辑 cluster 的流量会分散到不同物理节点上的同号卡，避免集中到单一 relay card。

### EP < 8：cluster 内小通信域卡绕路

对同一 8P fullmesh 小组内的两张卡 `src` 和 `dst`，候选路径分三类：

1. 直接 fullmesh：

```text
src -> dst
```

2. 经同 cluster 其它 8P fullmesh 卡绕路：

```text
src -> mid_card -> dst
```

其中 `mid_card` 从同一个 8P 小组中除 `src` 和 `dst` 之外的卡中选择。

3. 经上方交换机绕路：

```text
src -> switch_i -> dst
```

其中 `switch_i` 是该 cluster 的任意上联交换机。

第一版不能只均衡第一跳。对 `r=7` 且 8P fullmesh 的 EP=2，候选第一跳共：

```text
1 direct + 6 mid_card + 7 switch = 14
```

如果只看 focus card 侧，每条相邻出链路可以承载 `1/14`。但这不是最终效率，因为绕路会占用其它共享链路：

```text
src -> mid_card -> dst
```

会使用 `mid_card -> dst`，而通信域内本来还存在 `mid_card -> dst` 这条直接需求。因此 `mid_card -> dst` 的流量会叠加。交换机绕路也类似，`switch_i -> dst` 会承载多条经该交换机回到 `dst` 的绕路流量。第一版的固定分流表必须按全通信域有向链路负载计算权重，而不是简单把 focus card 的 14 个出口均分。

`EP < 8` 的实现应先枚举通信域内所有有向需求：

```text
src -> dst
dst -> src
```

再对每个方向生成相同类型的候选绕路路径，汇总所有路径对全域有向链路的贡献。权重选择以降低全域 `all_link_L_max` 为目标。

### EP > cluster_size：跨 cluster 绕路

对不同 cluster `A` 和 `B` 之间的流量，候选路径分两类：

1. 直接共享交换机：

```text
A.card -> switch(A,B) -> B.card
```

2. 经过第三方中转 cluster `X`：

```text
A.card -> switch(A,X) -> X.relay_card -> switch(X,B) -> B.card
```

其中 `X` 遍历除 `A`、`B` 以外的其它 cluster。对于 `v=8`，可选中转 cluster 数为 `6`。

第一版不应默认直接路径和所有 `via X` 路径完全均分。均分能打散源 cluster 出口，但可能把中转 cluster 的入链路、出链路或 relay card 周边链路推成新热点。对于 `r=7`，候选方向数为：

```text
1 direct + 6 via-cluster = 7
```

最终权重需要按全通信域链路贡献计算。第一版可以先用一个小规模确定性 min-max 搜索或线性规划式枚举来求固定权重；如果暂不引入外部 LP 依赖，则用有边界的网格搜索，例如步长 `1/64` 或 `1/128`，在候选权重空间内选择最大有向链路负载最低的一组。

中转卡选择采用确定性规则：根据源卡 index、目的卡 index 和中转 cluster id 在中转 cluster 内选一个 relay card，避免所有绕路流量集中到中转 cluster 的同一张卡。规则必须可复现，例如：

```text
relay_card_index = (source_card_index + destination_card_index + intermediate_cluster_id) % cluster_size
```

如果 relay card 与某条需要的交换机连接无关，这不影响 SparseClos，因为同一 cluster 内每张卡都连接该 cluster 的全部 `r` 个上联交换机。

## 固定分流表

新增一个内部数据结构描述绕路策略：

```text
DetourPlan
  route_type
  paths
  weights
```

约束：

- `len(paths) == len(weights)`
- `sum(weights) == 1`
- 权重使用浮点数即可，测试使用近似比较。

第一版可不暴露复杂配置，只新增一个路由模式：

```text
RoutingMode.DETOUR_ROUTING = "detour-routing"
```

`route_between_cards(..., mode=DETOUR_ROUTING)` 返回 `RouteResult.paths`，同时需要能表达权重。现有 `RouteResult` 只有 paths，没有权重。为了兼容旧代码，设计上有两种选择：

1. 扩展 `RouteResult`，增加可选字段 `path_weights`，默认等权。
2. 保持 `RouteResult` 不变，把权重通过重复 path 近似表达。

推荐选择 1。重复 path 会让报告变大，也无法准确表达 `1/14` 这类权重。

## 仿真计算

当前仿真逻辑默认把一份流量在 `route.paths` 中等分：

```text
traffic_share = 1.0 / len(route.paths)
```

改造为：

```text
for path, weight in route.weighted_paths():
    add traffic with weight
```

`RouteResult.weighted_paths()` 负责在没有显式权重时返回等权，保证已有 routing mode 行为不变。

shortest-path 的 focus-only 剪枝继续保留。对 SparseClos detour-routing，不能只统计 focus card 出方向路径，因为绕路共享链路会影响真实瓶颈。第一版需要新增一个 all-link 计算路径：

- 对当前通信域内所有有向需求生成 detour paths。
- 按 `path_weights` 累加所有路径上的有向链路 traffic。
- 计算全域最大链路负载 `all_link_L_max`。
- 同时从完整 `link_traffic` 中抽取现有 focus-card 相邻链路指标，保持旧报告可读。

为避免 EP=128 全量枚举过慢，可以利用 SparseClos 规则按链路类别聚合；但语义上必须等价于完整有向 all2all 链路计数。测试中先用小规模完整枚举校验聚合结果。

## 效率公式

报告保留现有 focus-card 公式，作为局部观察指标：

```text
S = EP - 1
L_max = max(traffic(edge) / bandwidth(edge), for focus card outgoing adjacent edges)
denominator =
    traffic(max_loaded_edge)
    + sum(L_max * bandwidth(edge), for each other focus-card outgoing edge)
efficiency = S / denominator
```

同时新增绕路优化使用的 all-link 公式：

```text
all_link_L_max = max(traffic(edge) / bandwidth(edge), for all directed links used by the communication domain)
all_link_denominator = all_link_L_max * sum(bandwidth(edge), for source-side available outgoing capacity proxy)
all_link_efficiency = ideal_sent_flows / all_link_denominator
```

第一版为了和现有报告口径衔接，`ideal_sent_flows` 仍使用 focus card 的 `EP - 1`，但 `all_link_L_max` 必须来自全通信域链路。这样 EP=2 中 `mid_card -> dst` 的共享流量会反映到效率上，结果会小于只看 focus 出口时的 1.0。

更严格的全局效率可以在后续扩展为：

```text
global_efficiency = total_all2all_flows / (all_link_L_max * total_modeled_capacity)
```

但第一版先输出 `all_link_L_max`、`all_link_efficiency`，并用它们比较 detour-routing 与 shortest-path。

## 预期结果

### EP=2

`r=7`、8P fullmesh 时，focus card 有 14 个相邻端口。如果只看 focus card 第一跳，可以把出方向流量打散到 14 条相邻链路；但这不是最终效率。最终瓶颈需要把全通信域两条有向需求以及所有绕路共享链路都算进去。

```text
1 -> 2 的绕路: 1 -> 3 -> 2
3 -> 2 的原始需求: 3 -> 2
共享链路: 3 -> 2
```

因此 EP=2 的 `all_link_efficiency` 预期小于 1.0。验收标准改为：

- detour-routing 的 `all_link_L_max` 低于 shortest-path 的 `all_link_L_max`。
- focus card 出方向不再只有一条链路有流量。
- 报告明确显示共享链路导致的最大负载位置。

### EP=128

跨两个 cluster 的热点应从单个共享交换机方向扩散到多个方向。但 via-cluster 绕路会在中转 cluster 上形成入链路、relay card、出链路的共享，因此最终权重必须以全通信域最大链路负载为准。

第一版验收不要求 EP=128 达到 1.0，而要求：

- 相比 shortest-path，`all_link_L_max` 下降。
- 报告中的 `focus_card_link_traffic` 不再出现单个 switch 方向远高于其它 switch 方向的极端热点。
- 如果中转 cluster 链路成为新瓶颈，报告能显示该瓶颈，而不是误判为 focus 侧已经最优。

## CLI 与配置

新增 routing mode：

```text
--routing-mode detour-routing
```

JSON 配置继续使用：

```json
{
  "routing": {
    "mode": "detour-routing"
  }
}
```

第一版不新增绕路权重配置项。权重由拓扑和通信关系确定。

报告新增绕路类型字段：

```text
route_types: card_detour | cluster_detour | none
detour_types: card_detour | cluster_detour | none
```

`card_detour` 表示通过同 8P fullmesh 小组内其它卡或同 cluster 上联交换机绕路；`cluster_detour` 表示跨 cluster 流量通过第三方 cluster 的 relay card 绕路。整网 all2all 输出 `none`。

## 测试

新增测试覆盖：

- `RouteResult` 无显式权重时保持旧的等权行为。
- `EP < 8` 同 8P 小组内通信时，detour-routing 返回 direct、mid-card、switch 三类路径，报告输出 `card_detour`。
- `EP < 8` 报告能体现绕路共享链路，`all_link_efficiency` 不应被断言为 1.0。
- `EP > cluster_size` 且不是整网 all2all 时，跨 cluster detour-routing 返回 direct 和 via-cluster 两类路径，报告输出 `cluster_detour`。
- `same-index-across-nodes` 布局下，`EP <= cards_per_physical_node` 的物理 8P 内通信可输出 `card_detour`；`EP > cards_per_physical_node` 时不输出 `cluster_detour`，应回退 shortest-path 并输出 `none`。
- 整网 all2all 使用 shortest-path，报告输出 `none`。
- 如果中转 cluster 产生新热点，报告能定位到对应 directed link。
- 既有 shortest-path、source-node-jump、destination-node-jump 测试不变。

## 实施顺序

1. 扩展 `RoutingMode` 和 `RouteResult`，增加可选权重支持。
2. 改造仿真层使用 path 权重，保持旧模式等权兼容。
3. 实现 SparseClos detour-routing 的 EP=2 路径模板。
4. 实现 SparseClos detour-routing 的跨 cluster via-cluster 路径模板。
5. 增加 all-link 负载报告字段和测试。
6. 增加典型参数生成验证。
7. 用 `r=7,k=2,switch_port_num=128,fullmesh` 重新输出 detour-routing 和 shortest-path 对比报告。

## 风险

- EP=2 不能只看 focus-card 侧效率；共享链路会让真实效率小于第一跳均衡的理想值。
- EP=128 的 via-cluster 绕路增加路径长度，若后续引入时延指标，需要单独解释带宽效率和时延之间的权衡。
- all-link 统计会比 focus-only 慢，需要使用规则聚合和小规模完整枚举测试来兼顾速度与正确性。

## 后续扩展

后续可以将固定均衡策略升级为按链路类别的 min-max 求解：

```text
minimize max_link_load
subject to:
  each demand's path weights sum to 1
  all path weights >= 0
```

由于 SparseClos 结构规则，变量可以按路径类别聚合，不需要枚举所有卡对。该扩展适合在第一版 detour-routing 行为稳定后再做。
