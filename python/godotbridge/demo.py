"""A repeatable, explicit arena-building workflow using only public operations."""

from .client import Client


def build_arena(client: Client, scene: str = "res://scenes/arena.tscn") -> dict:
    client.call("scene.create", path=scene)
    boxes = [
        ("Floor", (14, 0.25, 14), (0, -0.125, 0), (0.23, 0.29, 0.36, 1)),
        ("NorthWall", (14, 2, 0.3), (0, 1, -7), (0.4, 0.48, 0.58, 1)),
        ("SouthWall", (14, 2, 0.3), (0, 1, 7), (0.4, 0.48, 0.58, 1)),
        ("WestWall", (0.3, 2, 14), (-7, 1, 0), (0.4, 0.48, 0.58, 1)),
        ("EastWall", (0.3, 2, 14), (7, 1, 0), (0.4, 0.48, 0.58, 1)),
        ("ObstacleA", (2, 1.5, 2), (-3, 0.75, -2), (0.9, 0.38, 0.18, 1)),
        ("ObstacleB", (1.5, 3, 1.5), (1, 1.5, 1), (0.2, 0.65, 0.75, 1)),
        ("ObstacleC", (3, 1, 1), (3, 0.5, -3), (0.65, 0.45, 0.82, 1)),
    ]
    for name, size, position, color in boxes:
        client.call("3d.create_primitive", name=name, size=size, position=position, color=color)
    client.call("3d.create_light", name="Sun", energy=1.4)
    client.call("3d.create_light", name="Fill", type="omni", position=(0, 6, 0), energy=2)
    client.call("3d.create_camera", position=(15, 13, 18), target=(0, 0, 0))
    client.call("scene.save")
    return client.call("scene.tree")
