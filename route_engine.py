from pathlib import Path
from functools import lru_cache
import random
import heapq

import osmnx as ox
import networkx as nx


BASE_DIR = Path(__file__).resolve().parent
MAP_PATH = BASE_DIR / "data" / "map.osm"

RANDOM_SEED = 42
PASS_TIME_S = 5


def neighbor_count(G, node):
    return len(set(G.predecessors(node)).union(set(G.successors(node))))


def assign_traffic_lights(G, seed=42):
    """
    將 OSM 中 highway=traffic_signals 的節點設定：
    cycle / green / offset / type
    """
    rng = random.Random(seed)

    for node, data in G.nodes(data=True):
        if data.get("highway") != "traffic_signals":
            continue

        degree = neighbor_count(G, node)

        if degree >= 4:
            cycle, green, light_type = 120, 50, "large"
        elif degree == 3:
            cycle, green, light_type = 80, 30, "medium"
        else:
            cycle, green, light_type = 60, 20, "small"

        data["cycle"] = cycle
        data["green"] = green
        data["offset"] = rng.randint(0, cycle - 1)
        data["type"] = light_type
        data["degree"] = degree


@lru_cache(maxsize=1)
def load_map():
    if not MAP_PATH.exists():
        raise FileNotFoundError(f"找不到地圖檔案：{MAP_PATH}")

    G = ox.graph_from_xml(str(MAP_PATH))
    assign_traffic_lights(G, RANDOM_SEED)
    return G


def get_map_summary():
    G = load_map()

    traffic_light_nodes = [
        node
        for node, data in G.nodes(data=True)
        if data.get("highway") == "traffic_signals"
    ]

    return {
        "nodes": len(G.nodes),
        "edges": len(G.edges),
        "traffic_lights": len(traffic_light_nodes),
        "crs": str(G.graph.get("crs")),
    }


def get_map_center():
    G = load_map()

    lat_list = [data["y"] for _, data in G.nodes(data=True)]
    lon_list = [data["x"] for _, data in G.nodes(data=True)]

    center_lat = sum(lat_list) / len(lat_list)
    center_lon = sum(lon_list) / len(lon_list)

    return center_lat, center_lon


def get_traffic_light_points():
    G = load_map()

    traffic_lights = []

    for node, data in G.nodes(data=True):
        if data.get("highway") == "traffic_signals":
            traffic_lights.append({
                "node": node,
                "lat": data["y"],
                "lon": data["x"],
                "type": data.get("type", "unknown"),
                "cycle": data.get("cycle"),
                "green": data.get("green"),
                "offset": data.get("offset"),
            })

    return traffic_lights


def find_nearest_node(lat, lon):
    G = load_map()

    node = ox.distance.nearest_nodes(
        G,
        X=lon,
        Y=lat
    )

    node_data = G.nodes[node]

    return {
        "node": node,
        "lat": node_data["y"],
        "lon": node_data["x"],
    }


def get_min_edge_data(G, u, v):
    edge_data = G.get_edge_data(u, v)

    if edge_data is None:
        raise ValueError(f"找不到道路 edge：{u} -> {v}")

    return min(
        edge_data.values(),
        key=lambda x: x.get("length", float("inf"))
    )


def route_length(G, route):
    total = 0

    for u, v in zip(route[:-1], route[1:]):
        edge = get_min_edge_data(G, u, v)
        total += edge["length"]

    return total


def route_to_latlon(G, route):
    coords = []

    for u, v in zip(route[:-1], route[1:]):
        edge = get_min_edge_data(G, u, v)

        if "geometry" in edge:
            edge_coords = list(edge["geometry"].coords)
            edge_latlon = [(lat, lon) for lon, lat in edge_coords]
        else:
            edge_latlon = [
                (G.nodes[u]["y"], G.nodes[u]["x"]),
                (G.nodes[v]["y"], G.nodes[v]["x"]),
            ]

        if coords:
            edge_latlon = edge_latlon[1:]

        coords.extend(edge_latlon)

    return coords


def traffic_delay(G, node, arrival_time_s):
    """
    根據抵達時間判斷紅綠燈等待時間。
    arrival_time_s 是一天中的第幾秒 + 行駛累積時間。
    """
    data = G.nodes[node]

    if "cycle" not in data:
        return 0.0

    cycle = data["cycle"]
    green = data["green"]
    offset = data["offset"]

    if green >= cycle:
        green = int(cycle * 0.5)

    phase = (arrival_time_s + offset) % cycle

    if phase < green:
        return float(PASS_TIME_S)

    return float(cycle - phase)


def edge_time(G, u, v, current_time_s, speed_mps):
    edge = get_min_edge_data(G, u, v)

    distance = edge["length"]
    driving_time = distance / speed_mps

    arrival_time = current_time_s + driving_time
    wait_time = traffic_delay(G, v, arrival_time)

    return driving_time + wait_time


def time_dependent_dijkstra(G, start_node, goal_node, speed_kmh, departure_seconds):
    """
    考慮紅綠燈等待時間的 Dijkstra。
    """
    speed_mps = speed_kmh / 3.6

    pq = [(departure_seconds, start_node, [])]
    best_time = {start_node: departure_seconds}

    while pq:
        current_time, node, path = heapq.heappop(pq)

        if current_time > best_time.get(node, float("inf")):
            continue

        path = path + [node]

        if node == goal_node:
            total_trip_time = current_time - departure_seconds
            return path, total_trip_time

        for nxt in G.successors(node):
            try:
                travel_time = edge_time(G, node, nxt, current_time, speed_mps)
            except Exception:
                continue

            new_time = current_time + travel_time

            if new_time < best_time.get(nxt, float("inf")):
                best_time[nxt] = new_time
                heapq.heappush(pq, (new_time, nxt, path))

    return None, float("inf")


def route_traffic_summary(G, route, speed_kmh, departure_seconds):
    """
    計算固定路線的：
    距離、行駛時間、紅綠燈數、等待時間、總時間
    """
    speed_mps = speed_kmh / 3.6

    current_time = float(departure_seconds)
    driving_time_total = 0.0
    waiting_time_total = 0.0
    light_details = []

    for u, v in zip(route[:-1], route[1:]):
        edge = get_min_edge_data(G, u, v)

        driving_time = edge["length"] / speed_mps
        driving_time_total += driving_time
        current_time += driving_time

        if "cycle" in G.nodes[v]:
            wait = traffic_delay(G, v, current_time)

            waiting_time_total += wait
            current_time += wait

            light_details.append({
                "node": v,
                "type": G.nodes[v].get("type"),
                "waiting_time_s": wait,
            })

    distance_m = route_length(G, route)

    return {
        "distance_m": distance_m,
        "driving_time_s": driving_time_total,
        "traffic_light_count": len(light_details),
        "waiting_time_s": waiting_time_total,
        "total_time_s": driving_time_total + waiting_time_total,
        "light_details": light_details,
    }


def build_alternative_route(G, shortest_route, penalty=10):
    G_alt = nx.MultiDiGraph(G)

    for u, v, key, data in G_alt.edges(keys=True, data=True):
        data["weight"] = data.get("length", 1)

    for u, v in zip(shortest_route[:-1], shortest_route[1:]):
        if G_alt.has_edge(u, v):
            for key in G_alt[u][v]:
                G_alt[u][v][key]["weight"] *= penalty

    start_node = shortest_route[0]
    goal_node = shortest_route[-1]

    alternative_route = nx.shortest_path(
        G_alt,
        start_node,
        goal_node,
        weight="weight"
    )

    return alternative_route


def package_route_result(G, name, route, speed_kmh, departure_seconds):
    summary = route_traffic_summary(
        G,
        route,
        speed_kmh,
        departure_seconds
    )

    return {
        "name": name,
        "route_nodes": route,
        "route_coords": route_to_latlon(G, route),
        **summary,
    }


def calculate_routes(start_lat, start_lon, goal_lat, goal_lon, speed_kmh, departure_seconds):
    """
    計算三條路線：
    1. Shortest Path
    2. Alternative Path
    3. Fastest Path
    """
    G = load_map()

    start_info = find_nearest_node(start_lat, start_lon)
    goal_info = find_nearest_node(goal_lat, goal_lon)

    start_node = start_info["node"]
    goal_node = goal_info["node"]

    shortest_route = nx.shortest_path(
        G,
        start_node,
        goal_node,
        weight="length"
    )

    alternative_route = build_alternative_route(
        G,
        shortest_route,
        penalty=10
    )

    fastest_route, fastest_total_time = time_dependent_dijkstra(
        G,
        start_node,
        goal_node,
        speed_kmh,
        departure_seconds
    )

    if fastest_route is None:
        raise ValueError("找不到 Fastest Path")

    return {
        "start_node": start_node,
        "goal_node": goal_node,
        "start_snapped": start_info,
        "goal_snapped": goal_info,

        "shortest": package_route_result(
            G,
            "Shortest Path",
            shortest_route,
            speed_kmh,
            departure_seconds
        ),

        "alternative": package_route_result(
            G,
            "Alternative Path",
            alternative_route,
            speed_kmh,
            departure_seconds
        ),

        "fastest": package_route_result(
            G,
            "Fastest Path",
            fastest_route,
            speed_kmh,
            departure_seconds
        ),
    }


if __name__ == "__main__":
    summary = get_map_summary()
    center_lat, center_lon = get_map_center()
    traffic_lights = get_traffic_light_points()

    print("地圖讀取成功")
    print("節點數:", summary["nodes"])
    print("道路數:", summary["edges"])
    print("紅綠燈數:", summary["traffic_lights"])
    print("CRS:", summary["crs"])
    print("中心點:", center_lat, center_lon)
    print("紅綠燈點數:", len(traffic_lights))