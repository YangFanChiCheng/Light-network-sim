# 典型并行域带宽效率计算说明

本文说明工具中“关注卡带宽效率”的计算思路，并给出几个典型并行域场景，方便对照模拟输出理解。

## 基本定义

设关注卡为 `c`，通常为 `node0-card0`。

并行域大小记为 `D`，域内采用有向 All2All：

```text
c 向域内其他 D - 1 张卡各发送 1 份流量
```

因此关注卡发送流量份数为：

```text
S = D - 1
```

拓扑中的物理链路按双工链路处理。也就是说：

```text
A -> B 和 B -> A 是两个方向的流量记录
traffic(A -> B) 不与 traffic(B -> A) 叠加
```

关注卡的出方向相邻链路集合记为：

```text
E_out(c) = {c -> n1, c -> n2, ..., c -> nk}
```

每条链路有：

```text
traffic(e): 该方向链路承载流量
bandwidth(e): 链路带宽
load(e) = traffic(e) / bandwidth(e)
```

带宽效率只按关注卡出方向端口计算，找到关注卡出方向相邻链路中负载最重的链路：

```text
e_max = argmax load(e), e in E_out(c)
L_max = load(e_max)
```

为了考虑不同链路带宽和流量不均衡，带宽效率分母按以下方式折算：

```text
denominator =
    traffic(e_max)
    + sum(L_max * bandwidth(e), for e in E_out(c), e != e_max)
```

最终关注卡带宽效率为：

```text
efficiency = S / denominator
```

直观理解：

- 负载最重的出方向链路是真实瓶颈，使用它真实承载的出方向流量。
- 其他出方向链路按“如果也达到同样瓶颈负载，理论可承载多少流量”进行折算。
- 如果各端口负载越均衡，分母越接近有效总承载能力。
- 如果某条链路特别重，其他链路很空，效率会下降。
- 接收方向流量会记录在反向链路中，但不参与关注卡发送带宽效率计算。

## 场景一：并行域小于等于每节点卡数

条件示例：

```text
D <= 每节点卡数 N
```

常见情况是通信域完全落在一个节点内部，例如：

```text
node0-card0, node0-card1, ..., node0-card(D-1)
```

此时路由主要使用节点内 FullMesh：

```text
node0-card0 -> node0-cardi
```

对关注卡 `node0-card0`：

```text
S = D - 1
```

关注卡出方向相邻链路中，主要有 `D - 1` 条节点内链路承载发送流量。域内反向通信会记录在反方向链路中，不与出方向相加。

若每条节点内链路带宽相同，且负载均匀，则：

```text
L_max = max traffic(node0-card0 -> node0-cardi) / intra_bandwidth
denominator = L_max * sum(bandwidth(e), e in E_out(node0-card0))
efficiency = (D - 1) / denominator
```

注意：工具会使用关注卡所有相邻链路参与分母折算，包括未承载流量的端口。这反映了“可用端口是否被有效利用”。

## 场景二：并行域在同一个 2DFM 域内

条件示例：

```text
并行域跨多个节点，但所有节点位于同一个 2DFM 域
```

2DFM 域内，同号卡跨节点 FullMesh。例如：

```text
node0-card0 -- node1-card0 -- node2-card0 ...
node0-card1 -- node1-card1 -- node2-card1 ...
```

典型路由：

若源卡和目的卡不在同一节点，但在同一 2DFM 域：

```text
source_card
  -> 源节点内的目标同号卡
  -> 通过 2DFM 同号卡 FullMesh 到目的卡
```

例如：

```text
node0-card0 -> node0-card3 -> node1-card3
```

关注卡 `node0-card0` 的相邻链路可能包括：

```text
节点内 FullMesh 链路
2DFM 同号卡跨节点链路
交换机链路
```

效率仍按统一公式：

```text
S = D - 1
load(e) = traffic(e) / bandwidth(e), e in E_out(node0-card0)
L_max = max load(e), e in E_out(node0-card0)
denominator = traffic(e_max) + sum(L_max * bandwidth(e), e in E_out(node0-card0), e != e_max)
efficiency = S / denominator
```

这个场景下，如果节点内链路和 2DFM 链路都能均衡承载，效率通常会比只压在某一类链路上更高。

## 场景三：并行域跨不同 2DFM 域

条件示例：

```text
并行域中的卡分布在多个 2DFM 域
```

此时跨域流量必须经过 Clos 交换机层，工具支持两种 2D 跨域路由模式。

### 源 2DFM 跳转

模式：

```text
--routing-mode source-2dfm-jump
```

路由思路：

```text
源卡
  -> 源 2DFM 域内与目标卡同交换机分组的候选卡
  -> 交换机
  -> 目标卡
```

若候选卡有多张，则形成多条等价路径，单份流量均分：

```text
每条路径承载 = 1 / 路径条数
```

### 目的 2DFM 跳转

模式：

```text
--routing-mode destination-2dfm-jump
```

路由思路：

```text
源卡
  -> 源卡连接的交换机
  -> 目标 2DFM 域内与源卡同交换机分组的候选卡
  -> 在目标 2DFM 域内继续路由
```

目标 2DFM 域内路由方式：

```text
先走同节点内 FullMesh
再走不同节点间同号卡 FullMesh
```

该模式也可能有多条等价路径，工具同样会均分流量。

跨 2DFM 域时，关注卡的瓶颈通常可能出现在：

- 卡到交换机链路；
- 节点内 FullMesh 链路；
- 2DFM 同号卡跨节点链路。

因此效率公式中使用最重负载链路进行折算：

```text
denominator =
    traffic(e_max)
    + sum(L_max * bandwidth(e), for e in E_out(c), e != e_max)
```

这可以反映跨域通信中链路负载不均衡带来的效率损失。

## 如何对照工具输出

主模拟报告中每个通信域会打印：

```text
domain_size
focus_card_sent_flows
focus_card_port_count
focus_card_efficiency_denominator
focus_card_bandwidth_efficiency
focus_card_link_loads
max_loaded_adjacent_link
max_adjacent_link_load
```

全链路报告中会打印每条链路：

```text
link | traffic=... | load=...
```

建议阅读顺序：

1. 先看 `focus_card_link_loads`，确认关注卡哪些端口最重。
2. 再看 `max_loaded_adjacent_link`，找到瓶颈链路。
3. 用瓶颈链路负载 `max_adjacent_link_load` 回代分母公式。
4. 最后对照 `focus_card_bandwidth_efficiency`。

## 指定配置一：1DFM + Clos，32 节点，每节点 8 卡，2 个交换机

配置：

```text
topology_type = 1d-fm-clos
M = 32
N = 8
X = 2
intra_bandwidth = 200
switch_bandwidth = 1400
routing_mode = source-node-jump
focus_card = node0-card0
```

总卡数：

```text
total_cards = M * N = 32 * 8 = 256
```

默认会计算 `256` 的所有因数，并跳过通信域大小 `1`：

```text
D in {2, 4, 8, 16, 32, 64, 128, 256}
```

关注卡 `node0-card0` 的相邻链路为：

```text
7 条节点内 FullMesh 链路，带宽均为 200：
node0-card0 -> node0-card1
...
node0-card0 -> node0-card7

1 条 Clos 链路，带宽为 1400：
node0-card0 -> switch0
```

因此关注卡共有：

```text
focus_card_port_count = 7 + 1 = 8
```

### D = 8：通信域刚好等于一个节点

通信域为：

```text
node0-card0 ... node0-card7
```

所有通信都在节点内完成。对关注卡来说，它向其他 7 张卡各发送 1 份流量。由于链路按双工方向记录，`node0-card0 -> node0-cardi` 和 `node0-cardi -> node0-card0` 分开统计，所以每条相关出方向节点内链路承载：

```text
traffic(node0-card0 -> node0-cardi) = 1, i = 1..7
```

Clos 链路不承载流量：

```text
traffic(node0-card0 -> switch0) = 0
```

最重负载链路是任意一条节点内链路：

```text
L_max = 1 / 200 = 0.005
```

分母为：

```text
denominator
  = traffic(e_max)
    + 其他 6 条节点内链路按 L_max 折算
    + 1 条 Clos 链路按 L_max 折算

  = 1 + 6 * (0.005 * 200) + 1 * (0.005 * 1400)
  = 1 + 6 + 7
  = 14
```

发送流量份数：

```text
S = D - 1 = 8 - 1 = 7
```

带宽效率：

```text
efficiency = S / denominator = 7 / 14 = 0.5
```

### D = 16：通信域跨 2 个节点

通信域为 `node0` 和 `node1` 的 16 张卡。对关注卡相邻链路，仿真得到：

```text
node0-card0 -> node0-card1/2/3: traffic = 1
node0-card0 -> node0-card4/5/6/7: traffic = 2
node0-card0 -> switch0:          traffic = 8
```

对应负载：

```text
node0-card0 -> node0-card1/2/3: load = 1 / 200 = 0.005
node0-card0 -> node0-card4/5/6/7: load = 2 / 200 = 0.01
node0-card0 -> switch0:          load = 8 / 1400 = 0.005714
```

所以瓶颈仍是节点内链路：

```text
L_max = 0.01
traffic(e_max) = 2
```

分母为：

```text
denominator
  = 2
    + 6 * (0.01 * 200)
    + 1 * (0.01 * 1400)
  = 2 + 12 + 14
  = 28
```

发送流量份数：

```text
S = 16 - 1 = 15
```

带宽效率：

```text
efficiency = 15 / 28 = 0.535714
```

这里 `node0-card0 -> switch0` 的出方向流量不仅来自 `node0-card0` 自己发送的流量，也可能来自同节点其他卡在 `source-node-jump` 路由中把 `node0-card0` 作为中转卡后继续向交换机发出的流量。

### 1DFM + Clos 默认通信域汇总

下表中的 `denominator` 和 `efficiency` 可直接用上面的统一公式复算：

| 通信域 D | S = D - 1 | 瓶颈链路 | L_max | denominator | efficiency |
|---:|---:|---|---:|---:|---:|
| 2 | 1 | 节点内链路 | 0.005000 | 14 | 0.071429 |
| 4 | 3 | 节点内链路 | 0.005000 | 14 | 0.214286 |
| 8 | 7 | 节点内链路 | 0.005000 | 14 | 0.500000 |
| 16 | 15 | 节点内链路 | 0.010000 | 28 | 0.535714 |
| 32 | 31 | 节点内链路 | 0.020000 | 56 | 0.553571 |
| 64 | 63 | 节点内链路 | 0.040000 | 112 | 0.562500 |
| 128 | 127 | Clos 链路 | 0.085714 | 240 | 0.529167 |
| 256 | 255 | Clos 链路 | 0.177143 | 496 | 0.514113 |

当通信域扩大到 `128` 和 `256` 时，`node0-card0 -> switch0` 的出方向负载超过节点内链路，瓶颈从节点内 FullMesh 转移到 Clos 链路。

## 指定配置二：2DFM + Clos，32 节点，每节点 8 卡，2 个交换机

配置：

```text
topology_type = 2d-fm-clos
M = 32
N = 8
X = 2
fm2d_domain_size = 8
intra_bandwidth = 100
fm2d_bandwidth = 100
switch_bandwidth = 1400
routing_mode = source-2dfm-jump
focus_card = node0-card0
```

总卡数仍为：

```text
total_cards = 32 * 8 = 256
```

2DFM 域规模为：

```text
fm2d_domain_size = 8 个节点
每个 2DFM 域包含 8 * 8 = 64 张卡
```

关注卡 `node0-card0` 的相邻链路为：

```text
7 条节点内 FullMesh 链路，带宽均为 100：
node0-card0 -> node0-card1
...
node0-card0 -> node0-card7

7 条第二维 FullMesh 同号卡链路，带宽均为 100：
node0-card0 -> node1-card0
...
node0-card0 -> node7-card0

1 条 Clos 链路，带宽为 1400：
node0-card0 -> switch0
```

因此关注卡共有：

```text
focus_card_port_count = 7 + 7 + 1 = 15
```

### D = 8：通信域仍在单节点内

通信域只包含 `node0` 的 8 张卡，此时 2DFM 链路和 Clos 链路都不承载关注卡相关流量：

```text
node0-card0 -> node0-card1..7: traffic = 1
node0-card0 -> node1-card0..node7-card0: traffic = 0
node0-card0 -> switch0: traffic = 0
```

瓶颈负载：

```text
L_max = 1 / 100 = 0.01
```

分母：

```text
denominator
  = 1
    + 13 * (0.01 * 100)
    + 1 * (0.01 * 1400)
  = 1 + 13 + 14
  = 28
```

注意这里虽然 2DFM 和 Clos 链路没有真实流量，但它们是关注卡的可用端口，所以仍会按瓶颈负载参与分母折算。

发送流量份数：

```text
S = 8 - 1 = 7
```

带宽效率：

```text
efficiency = 7 / 28 = 0.25
```

### D = 64：通信域刚好等于一个 2DFM 域

通信域包含 `node0..node7` 的所有卡。此时路由在同一个 2DFM 域内完成：

```text
若目的卡与源卡同号：
source_card -> destination_card

若目的卡与源卡不同号：
source_card -> 源节点内的目的同号卡 -> 目的节点目的卡
```

对关注卡 `node0-card0`，仿真得到：

```text
7 条节点内链路 traffic = 8
7 条第二维同号卡链路 traffic = 8
Clos 链路 traffic = 0
```

瓶颈负载：

```text
L_max = 8 / 100 = 0.08
```

分母：

```text
denominator
  = 8
    + 13 * (0.08 * 100)
    + 1 * (0.08 * 1400)
  = 8 + 104 + 112
  = 224
```

发送流量份数：

```text
S = 64 - 1 = 63
```

带宽效率：

```text
efficiency = 63 / 224 = 0.28125
```

### D = 128：通信域跨 2 个 2DFM 域

通信域包含 `node0..node15` 的所有卡，也就是两个 2DFM 域。跨 2DFM 域流量需要经过 Clos。

对关注卡相邻链路，仿真得到：

```text
7 条节点内链路 traffic = 16
7 条第二维同号卡链路 traffic = 16
Clos 链路 traffic = 64
```

对应负载：

```text
节点内链路 load = 16 / 100 = 0.16
第二维链路 load = 16 / 100 = 0.16
Clos 链路 load = 64 / 1400 = 0.045714
```

瓶颈仍是 100 带宽链路：

```text
L_max = 0.16
traffic(e_max) = 16
```

分母：

```text
denominator
  = 16
    + 13 * (0.16 * 100)
    + 1 * (0.16 * 1400)
  = 16 + 208 + 224
  = 448
```

发送流量份数：

```text
S = 128 - 1 = 127
```

带宽效率：

```text
efficiency = 127 / 448 = 0.283482
```

### 2DFM + Clos 默认通信域汇总

| 通信域 D | S = D - 1 | 瓶颈链路 | L_max | denominator | efficiency |
|---:|---:|---|---:|---:|---:|
| 2 | 1 | 节点内链路 | 0.010000 | 28 | 0.035714 |
| 4 | 3 | 节点内链路 | 0.010000 | 28 | 0.107143 |
| 8 | 7 | 节点内链路 | 0.010000 | 28 | 0.250000 |
| 16 | 15 | 第二维同号卡链路 | 0.080000 | 224 | 0.066964 |
| 32 | 31 | 第二维同号卡链路 | 0.080000 | 224 | 0.138393 |
| 64 | 63 | 节点内或第二维链路 | 0.080000 | 224 | 0.281250 |
| 128 | 127 | 节点内或第二维链路 | 0.160000 | 448 | 0.283482 |
| 256 | 255 | 节点内或第二维链路 | 0.320000 | 896 | 0.284598 |

该配置下节点内链路和 2DFM 链路带宽都是 `100`，远小于 Clos 链路 `1400`。因此即使跨域通信会使用 Clos，最终瓶颈仍通常落在 100 带宽的节点内或第二维 FullMesh 链路上。

## 单次 RTT 静态时延计算

如果配置了时延参数，程序会在每个通信域下计算一列 `single_rtt_latency_ns`。该值表示通信域内任意两张卡之间单次 RTT 的最大静态时延。

### 输入参数

```text
switch_forward_latency_ns      交换机转发时延
card_forward_latency_ns        中转卡转发时延
optical_module_latency_ns      单个光模块时延
npu_processing_latency_ns      NPU 卡处理时延
intra_1dfm_link_length_m       节点内 1DFM 链路长度
fm2d_link_length_m             2DFM 同号卡链路长度
switch_link_length_m           卡到交换机光纤长度
```

链路传播时延统一按：

```text
link_latency = length_m * 5ns
```

只有经过交换机的链路需要计算光模块时延。每一段 `卡 -> 交换机` 或 `交换机 -> 卡` 链路两端各经过一次光模块，因此：

```text
switch_link_latency = switch_link_length_m * 5 + 2 * optical_module_latency_ns
```

节点内 1DFM 链路和 2DFM 同号卡链路不计算光模块：

```text
intra_1dfm_link_latency = intra_1dfm_link_length_m * 5
fm2d_link_latency = fm2d_link_length_m * 5
```

### 示例：A 卡通过交换机到 B 卡

路径：

```text
A -> switch -> B
```

单向时延：

```text
one_way
  = (optical_module + switch_link + optical_module)
    + switch_forward_latency
    + (optical_module + switch_link + optical_module)
```

单次 RTT：

```text
single_rtt
  = one_way * 2 + npu_processing_latency
```

例如：

```text
switch_forward_latency_ns = 10
optical_module_latency_ns = 2
npu_processing_latency_ns = 100
switch_link_length_m = 4
```

则：

```text
switch_link = 4 * 5 = 20
one_switch_segment = 2 + 20 + 2 = 24
one_way = 24 + 10 + 24 = 58
single_rtt = 58 * 2 + 100 = 216ns
```

### 示例：同节点内直连

路径：

```text
A -> B
```

若：

```text
intra_1dfm_link_length_m = 3
npu_processing_latency_ns = 100
```

则：

```text
one_way = 3 * 5 = 15
single_rtt = 15 * 2 + 100 = 130ns
```

### 通信域静态时延

对某个通信域 `D`，程序会遍历该通信域中的卡对，计算每个卡对的单次 RTT。如果不同卡对的时延不同，则取最大值：

```text
single_rtt_latency_ns(D) = max(RTT(card_i, card_j))
```

如果一对卡之间有多条等价路径，则先取这些等价路径中最大的一条作为该卡对的 RTT，再参与通信域最大值计算。输出详情中会记录触发最大值的卡对和路径。
