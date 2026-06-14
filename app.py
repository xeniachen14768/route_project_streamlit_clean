from datetime import time

import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium

from route_engine import (
    get_map_summary,
    get_map_center,
    get_traffic_light_points,
    calculate_routes,
)


# =========================
# Page Setting
# =========================
st.set_page_config(
    page_title="Traffic Light Route Planning System",
    layout="wide"
)

st.title("Traffic Light Route Planning System")
st.caption(
    "Interactive route planning system considering road distance, "
    "vehicle speed, departure time, and simulated traffic light delay."
)


# =========================
# Session State
# =========================
if "start_point" not in st.session_state:
    st.session_state.start_point = None

if "goal_point" not in st.session_state:
    st.session_state.goal_point = None

if "last_click_key" not in st.session_state:
    st.session_state.last_click_key = None

if "map_key" not in st.session_state:
    st.session_state.map_key = 0

if "route_result" not in st.session_state:
    st.session_state.route_result = None


# =========================
# Sidebar
# =========================
st.sidebar.header("Control Panel")

departure_time = st.sidebar.time_input(
    "Departure Time",
    value=time(8, 30)
)

departure_seconds = (
    departure_time.hour * 3600
    + departure_time.minute * 60
    + departure_time.second
)

speed_kmh = st.sidebar.slider(
    "Vehicle Speed (km/h)",
    min_value=5,
    max_value=60,
    value=20,
    step=5
)

st.sidebar.divider()

st.sidebar.subheader("Route Selection")
st.sidebar.write("Click the map to select:")
st.sidebar.write("1. Start point")
st.sidebar.write("2. Goal point")

if st.sidebar.button("Reset Points"):
    st.session_state.start_point = None
    st.session_state.goal_point = None
    st.session_state.last_click_key = None
    st.session_state.route_result = None
    st.session_state.map_key += 1
    st.rerun()

calculate_btn = st.sidebar.button("Calculate Routes")

st.sidebar.divider()

st.sidebar.subheader("Legend")

st.sidebar.markdown("""
**Markers**

<span style='color:green; font-size:18px;'>▶</span> Start Point  
<span style='color:blue; font-size:18px;'>⚑</span> Goal Point  
<span style='color:red; font-size:18px;'>●</span> Traffic Lights  

---

**Routes**

<span style='color:red; font-size:20px;'>━━━</span> Shortest Path  
<span style='color:blue; font-size:20px;'>┅┅┅</span> Alternative Path  
<span style='color:green; font-size:20px;'>━━━━</span> Fastest Path  
""", unsafe_allow_html=True)

# =========================
# Map Summary
# =========================
st.subheader("Map Summary")

summary = get_map_summary()

col1, col2, col3, col4 = st.columns(4)

col1.metric("Nodes", summary["nodes"])
col2.metric("Edges", summary["edges"])
col3.metric("Traffic Lights", summary["traffic_lights"])
col4.metric("CRS", summary["crs"])


# =========================
# Selected Points Display
# =========================
st.subheader("Selected Points")

point_col1, point_col2, point_col3 = st.columns(3)

with point_col1:
    if st.session_state.start_point is None:
        st.info("Start Point: not selected")
    else:
        lat, lon = st.session_state.start_point
        st.success(f"Start Point: {lat:.6f}, {lon:.6f}")

with point_col2:
    if st.session_state.goal_point is None:
        st.info("Goal Point: not selected")
    else:
        lat, lon = st.session_state.goal_point
        st.success(f"Goal Point: {lat:.6f}, {lon:.6f}")

with point_col3:
    st.info(f"Departure: {departure_time} / Speed: {speed_kmh} km/h")


# =========================
# Calculate Routes
# =========================
if calculate_btn:
    if st.session_state.start_point is None or st.session_state.goal_point is None:
        st.warning("Please select both Start Point and Goal Point first.")
    else:
        start_lat, start_lon = st.session_state.start_point
        goal_lat, goal_lon = st.session_state.goal_point

        with st.spinner("Calculating routes..."):
            result = calculate_routes(
                start_lat=start_lat,
                start_lon=start_lon,
                goal_lat=goal_lat,
                goal_lon=goal_lon,
                speed_kmh=speed_kmh,
                departure_seconds=departure_seconds
            )

        st.session_state.route_result = result
        st.success("Routes calculated.")


# =========================
# Route Result Display
# =========================
if st.session_state.route_result is not None:
    result = st.session_state.route_result

    st.subheader("Route Results")

    rows = []

    for key in ["shortest", "alternative", "fastest"]:
        route = result[key]

        rows.append({
            "Route": route["name"],
            "Distance (m)": round(route["distance_m"], 1),
            "Traffic Lights": route["traffic_light_count"],
            "Driving Time (s)": round(route["driving_time_s"], 1),
            "Waiting Time (s)": round(route["waiting_time_s"], 1),
            "Total Time (s)": round(route["total_time_s"], 1),
        })

    df = pd.DataFrame(rows)
    df = df.sort_values("Total Time (s)").reset_index(drop=True)

    st.dataframe(df, width="stretch")

    best_route = df.iloc[0]["Route"]
    st.success(f"Best route by total time: {best_route}")

    with st.expander("Traffic Light Waiting Details"):
        for key in ["shortest", "alternative", "fastest"]:
            route = result[key]

            st.markdown(f"### {route['name']}")

            light_details = route["light_details"]

            if len(light_details) == 0:
                st.write("This route does not pass any simulated traffic lights.")
            else:
                light_df = pd.DataFrame(light_details)
                light_df = light_df.rename(columns={
                    "node": "Traffic Light Node",
                    "type": "Intersection Type",
                    "waiting_time_s": "Waiting Time (s)",
                })
                light_df["Waiting Time (s)"] = light_df["Waiting Time (s)"].round(1)

                st.dataframe(light_df, width="stretch")


# =========================
# Folium Map
# =========================
st.subheader("Map View")

center_lat, center_lon = get_map_center()
traffic_lights = get_traffic_light_points()

m = folium.Map(
    location=[center_lat, center_lon],
    zoom_start=15
)


# Traffic light points
for light in traffic_lights:
    folium.CircleMarker(
        location=[light["lat"], light["lon"]],
        radius=4,
        color="red",
        fill=True,
        fill_color="red",
        fill_opacity=0.8,
        tooltip=f"Traffic Light Node: {light['node']}",
        popup=f"""
        Type: {light['type']}<br>
        Cycle: {light['cycle']} s<br>
        Green: {light['green']} s<br>
        Offset: {light['offset']} s
        """
    ).add_to(m)


# Start marker
if st.session_state.start_point is not None:
    start_lat, start_lon = st.session_state.start_point
    folium.Marker(
        location=[start_lat, start_lon],
        popup="Start Point",
        tooltip="Start Point",
        icon=folium.Icon(color="green", icon="play")
    ).add_to(m)


# Goal marker
if st.session_state.goal_point is not None:
    goal_lat, goal_lon = st.session_state.goal_point
    folium.Marker(
        location=[goal_lat, goal_lon],
        popup="Goal Point",
        tooltip="Goal Point",
        icon=folium.Icon(color="blue", icon="flag")
    ).add_to(m)


def offset_coords(coords, offset):
    return [(lat + offset, lon + offset) for lat, lon in coords]


# Route lines
# Route lines
if st.session_state.route_result is not None:
    result = st.session_state.route_result

    route_styles = {
        "shortest": {
            "color": "red",
            "offset": 0.00000,
            "tooltip": "Shortest Path",
            "weight": 5,
            "dash_array": None,
        },
        "alternative": {
            "color": "blue",
            "offset": 0.00004,
            "tooltip": "Alternative Path",
            "weight": 5,
            "dash_array": "8, 8",
        },
        "fastest": {
            "color": "green",
            "offset": 0.00008,
            "tooltip": "Fastest Path",
            "weight": 6,
            "dash_array": None,
        },
    }

    for key, style in route_styles.items():
        route = result[key]

        folium.PolyLine(
            locations=offset_coords(
                route["route_coords"],
                style["offset"]
            ),
            color=style["color"],
            weight=style["weight"],
            opacity=0.9,
            tooltip=style["tooltip"],
            dash_array=style["dash_array"]
        ).add_to(m)

map_data = st_folium(
    m,
    width=1200,
    height=650,
    key=f"map_{st.session_state.map_key}"
)


# =========================
# Handle Map Click
# =========================
if map_data and map_data.get("last_clicked") is not None:
    clicked = map_data["last_clicked"]

    clicked_lat = clicked["lat"]
    clicked_lon = clicked["lng"]

    click_key = f"{clicked_lat:.6f},{clicked_lon:.6f}"

    if click_key != st.session_state.last_click_key:

        if st.session_state.start_point is None:
            st.session_state.start_point = (clicked_lat, clicked_lon)
            st.session_state.last_click_key = click_key
            st.session_state.route_result = None
            st.rerun()

        elif st.session_state.goal_point is None:
            st.session_state.goal_point = (clicked_lat, clicked_lon)
            st.session_state.last_click_key = click_key
            st.session_state.route_result = None
            st.rerun()

        else:
            st.warning("Start and Goal are already selected. Click 'Reset Points' to choose again.")


# =========================
# Hint
# =========================
if st.session_state.start_point is not None and st.session_state.goal_point is not None:
    st.success("Start and Goal selected. Click 'Calculate Routes'.")
else:
    st.info("Click the map to select start and goal points.")