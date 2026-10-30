import networkx as nx
import orjson
from pathlib import Path


def save_graph(G: nx.MultiDiGraph, path: str):
    data = nx.node_link_data(G)
    with open(path, "wb") as f:
        f.write(orjson.dumps(data, default=str))


def load_graph(path: str) -> nx.MultiDiGraph:
    with open(path, "rb") as f:
        data = orjson.loads(f.read())
    return nx.node_link_graph(data, directed=True, multigraph=True)