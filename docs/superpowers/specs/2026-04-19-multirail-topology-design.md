# Multi-Rail Topology Design

## Scope

Build the first part of a multi-rail network bandwidth efficiency tool: topology construction and interactive visualization. Routing policy configuration and traffic simulation are intentionally deferred, but the project structure should leave clear extension points for them.

## User Inputs

- `M`: number of compute nodes.
- `N`: number of network cards per compute node.
- `X`: number of switches.
- `intra_bandwidth`: bandwidth of links between cards inside the same compute node.
- `switch_bandwidth`: bandwidth of links between a card and a switch.
- `output`: path of the generated interactive HTML topology graph.

## Topology Rules

Each compute node owns `N` cards.

Inside each compute node, all cards are connected with a full mesh. Every intra-node card-to-card edge uses `intra_bandwidth`.

Between compute nodes, connectivity is represented through `X` switches. For every compute node, its cards are divided into `X` groups as evenly as possible. Group `i` connects to switch `i`. If `N` is not divisible by `X`, earlier groups receive one extra card until all cards are assigned.

The graph contains three node types:

- `compute`: logical compute node.
- `card`: network card attached to a compute node.
- `switch`: shared switch for one rail group.

The compute node objects are shown in the visualization for readability, but bandwidth-carrying network links are card-to-card and card-to-switch links.

## Visualization

Generate a standalone interactive HTML file using Plotly. The visualization should show:

- Compute nodes, cards, and switches with distinct styles.
- Intra-node full mesh links and card-to-switch links with distinct visual treatments.
- Hover text for nodes, including type, owner compute node, card index, and switch group where relevant.
- Hover text for links, including link type, endpoints, and bandwidth.

The layout should be deterministic enough for repeated parameter changes to remain understandable. Compute nodes and their cards should be visually grouped, while switches should appear as a separate rail layer.

## Project Structure

- `multirail_topology/config.py`: topology configuration dataclass and validation.
- `multirail_topology/topology.py`: graph construction and topology metadata.
- `multirail_topology/visualize.py`: Plotly HTML visualization.
- `multirail_topology/routing.py`: placeholder for later routing policy work.
- `multirail_topology/simulation.py`: placeholder for later traffic simulation and efficiency calculations.
- `main.py`: command-line entry point for generating the topology HTML.
- `requirements.txt`: Python dependencies.

## Validation And Errors

Reject invalid values early:

- `M`, `N`, and `X` must be positive integers.
- `X` cannot exceed `N`, because every switch group should receive at least one card per compute node.
- Bandwidth values must be positive numbers.

## Verification

Initial verification should include:

- A small default topology generation command.
- A graph summary showing expected counts:
  - compute nodes: `M`
  - card nodes: `M * N`
  - switch nodes: `X`
  - intra-node links: `M * N * (N - 1) / 2`
  - card-switch links: `M * N`
- HTML file existence after generation.

