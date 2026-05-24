#!/usr/bin/env python3
"""Print the maintenance graph structure for documentation."""
from app.graph.builder import build_maintenance_graph


def main() -> None:
    graph = build_maintenance_graph()
    try:
        drawable = graph.get_graph()
        print("Nodes:", list(drawable.nodes))
        print("Edges:", list(drawable.edges))
        print("\nMermaid:\n")
        print(drawable.draw_mermaid())
    except Exception as exc:
        print(f"Graph compiled OK. Visualization requires graphviz: {exc}")


if __name__ == "__main__":
    main()
