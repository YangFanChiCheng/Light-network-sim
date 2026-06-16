# SparseClos r7 k2 detour default domains run

Date: 2026-06-16

Command:

```powershell
C:\Users\ruize\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe main.py --topology-type sparse-clos --bst-r 7 --bst-k 2 --switch-port-num 128 --cluster-internal-mode fullmesh-plus-switch --routing-mode detour-routing --simulation-output simulation_sparseclos_r7_k2_detour_default_domains.txt --output topology_sparseclos_r7_k2_detour_default_domains.html --no-progress
```

No `--domain-size` argument was passed. The default domain sizes were:

```text
2, 4, 8, 16, 32, 64, 128, 192, 256, 320, 384, 448, 512
```

Elapsed time:

```text
25.032 seconds
00:00:25.0320166
```

Outputs:

```text
simulation_sparseclos_r7_k2_detour_default_domains.txt
HTML skipped because total card count 512 exceeds 256
```
