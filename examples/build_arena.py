"""Run: python examples/build_arena.py --project examples/3d_demo"""

import argparse
import json

from godotbridge.client import Client
from godotbridge.config import Config
from godotbridge.demo import build_arena

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--project", required=True)
parser.add_argument("--scene", default="res://scenes/arena.tscn")
parser.add_argument("--output-dir", default="snapshots/arena")
args = parser.parse_args()
client = Client(Config.load(args.project))
tree = build_arena(client, args.scene)
validation = client.call("project.validate")
client.call("scene.close")
client.call("scene.open", path=args.scene)
snapshot = client.call("scene.snapshot", output_dir=args.output_dir)
print(
    json.dumps(
        {
            "scene": args.scene,
            "node_count": len(tree["nodes"]),
            "validation": validation["validation"],
            "snapshot": snapshot,
        },
        indent=2,
    )
)
