# Build an arena with the CLI

Install the plugin and open the example project first. Run from the repository
root. Choose a new scene name and snapshot directory on reruns.

```sh
godotctl --project examples/3d_demo scene create res://scenes/cli_arena.tscn --root Node3D
godotctl --project examples/3d_demo 3d create-box --name Floor --size 14 0.25 14 --position 0 -0.125 0
godotctl --project examples/3d_demo 3d create-box --name NorthWall --size 14 2 0.3 --position 0 1 -7
godotctl --project examples/3d_demo 3d create-box --name SouthWall --size 14 2 0.3 --position 0 1 7
godotctl --project examples/3d_demo 3d create-box --name WestWall --size 0.3 2 14 --position -7 1 0
godotctl --project examples/3d_demo 3d create-box --name EastWall --size 0.3 2 14 --position 7 1 0
godotctl --project examples/3d_demo 3d create-box --name ObstacleA --size 2 1.5 2 --position -3 0.75 -2 --color 0.9 0.38 0.18 1
godotctl --project examples/3d_demo 3d create-box --name ObstacleB --size 1.5 3 1.5 --position 1 1.5 1 --color 0.2 0.65 0.75 1
godotctl --project examples/3d_demo 3d create-box --name ObstacleC --size 3 1 1 --position 3 0.5 -3 --color 0.65 0.45 0.82 1
godotctl --project examples/3d_demo 3d create-light --name Sun --energy 1.4
godotctl --project examples/3d_demo 3d create-camera --position 15 13 18
godotctl --project examples/3d_demo scene save
godotctl --project examples/3d_demo project validate --json
godotctl --project examples/3d_demo scene close
godotctl --project examples/3d_demo scene open res://scenes/cli_arena.tscn
godotctl --project examples/3d_demo scene tree --json
godotctl --project examples/3d_demo scene snapshot --output-dir snapshots/cli-arena --json
```

Collision and materials are enabled by default. Each helper is one undo action,
including its body and shape. The full arena is multiple actions; cross-command
atomic transactions are not provided.
