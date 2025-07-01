import os
import io
import uuid
from flask import Flask, request, send_from_directory, url_for, jsonify, render_template_string
import pandas as pd
import geopandas as gpd
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

app = Flask(__name__)

# Directories
os.makedirs("static/maps", exist_ok=True)
os.makedirs("static/img", exist_ok=True)

# Preload groups & shapefile
state_groups = pd.read_csv(r"./input_csv_files/group_by_state.csv")
us_states = gpd.read_file(
    r"./us_state_boundary_shapefiles/ne_10m_admin_1_states_provinces_lakes.shp"
)
us_states = us_states[us_states["admin"] == "United States of America"]
us_states["StateAbbr"] = us_states["iso_3166_2"].str.split("-").str[-1]
us_states = us_states.merge(
    state_groups, left_on="StateAbbr", right_on="State", how="left"
)

GROUP_COLORS = {"Group 1": "#0056b8", "Group 2": "#00a1e0", "Group 3": "#a1d0f3"}

# Pin definitions (same as before)
PIN_TYPES = {
    "primary_dark_blue_sphere": {
        "url": "/static/img/sphere_pin_primary_dark_blue.svg",
        "numbered": False,
        "label": "Location Name - Candidates",
    },
    "primary_dark_blue_number": {
        "url": "/static/img/number_pin_primary_dark_blue.svg",
        "numbered": True,
        "label": "Location Name",
    },
    "primary_light_blue_sphere": {
        "url": "/static/img/sphere_pin_primary_light_blue.svg",
        "numbered": False,
        "label": "Location Name - Candidates",
    },
    "primary_light_blue_number": {
        "url": "/static/img/number_pin_primary_light_blue.svg",
        "numbered": True,
        "label": "Location Name",
    },
    "green_sphere": {
        "url": "/static/img/sphere_pin_green.svg",
        "numbered": False,
        "label": "Location Name - Candidates",
    },
    "green_number": {
        "url": "/static/img/number_pin_green.svg",
        "numbered": True,
        "label": "Location Name",
    },
    "secondary_dark_blue_sphere": {
        "url": "/static/img/sphere_pin_secondary_dark_blue.svg",
        "numbered": False,
        "label": "Location Name - Candidates",
    },
    "secondary_dark_blue_number": {
        "url": "/static/img/number_pin_secondary_dark_blue.svg",
        "numbered": True,
        "label": "Location Name",
    },
    "teal_sphere": {
        "url": "/static/img/sphere_pin_teal.svg",
        "numbered": False,
        "label": "Location Name - Candidates",
    },
    "teal_number": {
        "url": "/static/img/number_pin_teal.svg",
        "numbered": True,
        "label": "Location Name",
    },
}

# Google Maps API Key (set your key here or via environment variable)
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "YOUR_GOOGLE_MAPS_API_KEY")


# HTML template for embeddable Google Map (no upload form, just map)
GOOGLE_MAPS_EMBED_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset=\"UTF-8\">
    <title>Google Maps Electrification Map</title>
    <style>
      html, body, #map { height: 100%; margin: 0; padding: 0; }
      #legend {
        background: white; padding: 10px; border: 2px solid #888; border-radius: 8px;
        position: absolute; left: 20px; bottom: 40px; z-index: 5;
      }
      .legend-color {
        display: inline-block;
        width: 24px;
        height: 16px;
        margin-right: 8px;
        border-radius: 3px;
        /* Opacity matches state polygons (0.75) */
        opacity: 1;
      }
      /* Remove custom label styling for default Google Maps labels */
    </style>
</head>
<body>
<div id=\"map\"></div>
<div id=\"legend\">
  <b>State Grouping Color Guide</b><br>
  <div><span class=\"legend-color\" style=\"background:rgba(0,86,184,0.75)\"></span>Group 1 (Best Parity Probability)</div>
  <div><span class=\"legend-color\" style=\"background:rgba(0,161,224,0.75)\"></span>Group 2 (Better Parity Probability)</div>
  <div><span class=\"legend-color\" style=\"background:rgba(161,208,243,0.75)\"></span>Group 3 (Good Parity Probability)</div>
</div>
<script src="https://maps.googleapis.com/maps/api/js?key={{api_key}}"></script>
<!-- MarkerClusterer library -->
<script src="https://unpkg.com/@googlemaps/markerclusterer/dist/index.min.js"></script>
<script>
const statePolygons = {{ state_polygons|safe }};
const pins = {{ pins|safe }};
const pinType = {{ pin_type|tojson }};

// Per-pin-type anchor and labelOrigin offsets (pixels from top-left of image)
// These values should be set so the anchor is at the exact tip of the pin in the SVG/PNG
const PIN_ANCHORS = {
  // Format: [anchorX, anchorY, labelOffsetY]
  // Numbered pins: SVG 65x82, tip at (32,80)
  'primary_dark_blue_number':   [32, 80, 10],
  'primary_light_blue_number':  [32, 80, 10],
  'green_number':               [32, 80, 10],
  'secondary_dark_blue_number': [32, 80, 10],
  'teal_number':                [32, 80, 10],
  // Spheres: rendered 50x50, anchor at bottom center (25,50)
  'primary_dark_blue_sphere':   [25, 50, 10],
  'primary_light_blue_sphere':  [25, 50, 10],
  'green_sphere':               [25, 50, 10],
  'secondary_dark_blue_sphere': [25, 50, 10],
  'teal_sphere':                [25, 50, 10],
};

function getPinAnchor(pinType, iconSize) {
  // Returns [anchorX, anchorY, labelOffsetY]
  if (PIN_ANCHORS[pinType]) return PIN_ANCHORS[pinType];
  // Default: bottom center
  return [Math.floor(iconSize.w/2), iconSize.h, 10];
}

function initMap() {
  // Custom map style: remove city labels, keep state/country boundaries
  const customMapStyle = [
    { featureType: 'administrative.locality', elementType: 'labels', stylers: [{ visibility: 'off' }] },
    { featureType: 'administrative.neighborhood', elementType: 'labels', stylers: [{ visibility: 'off' }] },
    { featureType: 'poi', elementType: 'labels', stylers: [{ visibility: 'off' }] },
    { featureType: 'road', elementType: 'labels', stylers: [{ visibility: 'off' }] },
    { featureType: 'transit', elementType: 'labels', stylers: [{ visibility: 'off' }] },
    { featureType: 'water', elementType: 'labels', stylers: [{ visibility: 'off' }] },
    { featureType: 'administrative.province', elementType: 'labels', stylers: [{ visibility: 'on' }] },
    { featureType: 'administrative.country', elementType: 'labels', stylers: [{ visibility: 'on' }] }
  ];
  const map = new google.maps.Map(document.getElementById('map'), {
    center: {lat: 39.8283, lng: -98.5795},
    zoom: 5,
    mapTypeId: 'roadmap',
    streetViewControl: false,
    fullscreenControl: true,
    mapTypeControl: false,
    styles: customMapStyle
  });
  // Draw state polygons
  statePolygons.forEach(function(poly) {
    const polygon = new google.maps.Polygon({
      paths: poly.paths,
      strokeColor: '#000',
      strokeOpacity: 0.7,
      strokeWeight: 1,
      fillColor: poly.color,
      fillOpacity: 0.75 // Slightly opaque
    });
    polygon.setMap(map);
  });
  // Add pins with clustering
  const markers = pins.map(function(pin) {
    let icon, iconSize, anchorX, anchorY;
    if (pin.numbered && pin.svg_data) {
      iconSize = {w:65, h:82};
      anchorX = 32;
      anchorY = 41;
      icon = {
        url: 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(pin.svg_data),
        scaledSize: new google.maps.Size(iconSize.w, iconSize.h),
        anchor: new google.maps.Point(anchorX, anchorY)
      };
    } else {
      iconSize = {w:50, h:50};
      anchorX = 25;
      anchorY = 50;
      icon = {
        url: pin.icon_url,
        scaledSize: new google.maps.Size(iconSize.w, iconSize.h),
        anchor: new google.maps.Point(anchorX, anchorY)
      };
    }
    return new google.maps.Marker({
      position: {lat: pin.lat, lng: pin.lng},
      icon: icon,
      title: pin.label,
      label: {
        text: pin.label,
        color: '#000',
        fontWeight: 'bold',
        fontSize: '16px',
        fontFamily: 'Calibri'
      }
    });
  });
  // Cluster the markers
  new markerClusterer.MarkerClusterer({
    map,
    markers
  });
  map.controls[google.maps.ControlPosition.LEFT_BOTTOM].push(document.getElementById('legend'));
}
window.onload = initMap;
</script>
</body>
</html>
"""

import json
import uuid

# In-memory map data store (for demo; use a DB or persistent store for production)
MAP_DATA = {}

@app.route("/google_maps", methods=["GET", "POST"])
def google_maps_form():
    if request.method == "GET":
        # Use the same HTML/CSS/JS as the Folium version for UI consistency
        return render_template_string(
            '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Map Uploader (Google Maps Version)</title>
    <style>
      body {
        margin: 0;
        padding: 0;
        font-family: Calibri;
        background: #f4f7fa;
      }
      .container {
        max-width: 800px;
        margin: 40px auto;
        background: #fff;
        border-radius: 8px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.15);
        padding: 20px 30px;
      }
      h1 {
        margin-top: 0;
        color: #333;
      }
      label {
        font-weight: bold;
      }
      .pin-selection {
        display: flex;
        flex-wrap: wrap;
        margin-bottom: 20px;
        gap: 10px;
      }
      .pin-option {
        display: inline-flex;
        flex-direction: column;
        align-items: center;
        cursor: pointer;
        transition: transform 0.2s ease;
        border: 2px solid transparent;
        border-radius: 5px;
        padding: 5px;
      }
      .pin-option:hover {
        background: #f0f4f8;
        transform: translateY(-2px);
      }
      .selected-pin {
        border-color: #00a1e0;
        background: #e8f6fe;
      }
      .pin-image {
        width: 40px;
        margin-bottom: 5px;
      }
      button {
        background: #0056b8;
        color: #fff;
        border: none;
        border-radius: 4px;
        padding: 10px 16px;
        cursor: pointer;
        font-size: 14px;
      }
      button:hover {
        background: #004494;
      }
      a {
        color: #0056b8;
        text-decoration: none;
        margin-left: 8px;
      }
      a:hover {
        text-decoration: underline;
      }
      .footer-links {
        margin-top: 10px;
      }
    </style>
</head>
<body>
<div class="container">
    <h1>Upload CSV/XLS/XLSX to Plot Pins (Google Maps Version)</h1>
    <p><strong>Required columns:</strong> Location Name, ZIP/Postal Code, Electrification Candidates</p>
    <p><strong>Optional columns:</strong> Street Address, City, State</p>
    <p><strong>Accepted file types:</strong> .csv, .xls, .xlsx</p>

    <form method="POST" enctype="multipart/form-data">
      <label>Choose File:</label><br>
      <input type="file" name="file" accept=".csv,.xls,.xlsx" required/><br><br>

      <label>Select Pin Type:</label>
      <div class="pin-selection" id="pinSelectionContainer"></div>

      <input type="hidden" name="pin_type" id="selected_pin_type" required>

      <button type="submit">Upload & Generate Map</button>
      <div class="footer-links">
        <a href="/download_template" download="location_pins_template.xlsx">Download Excel Template</a>
      </div>
    </form>
</div>

<script>
  const pinTypes = {
    "primary_dark_blue_sphere": { "url": "/static/img/sphere_pin_primary_dark_blue.svg", "label": "Location Name - Candidates" },
    "primary_dark_blue_number": { "url": "/static/img/number_pin_primary_dark_blue.svg", "label": "Location Name" },
    "primary_light_blue_sphere": { "url": "/static/img/sphere_pin_primary_light_blue.svg", "label": "Location Name - Candidates" },
    "primary_light_blue_number": { "url": "/static/img/number_pin_primary_light_blue.svg", "label": "Location Name" },
    "green_sphere": { "url": "/static/img/sphere_pin_green.svg", "label": "Location Name - Candidates" },
    "green_number": { "url": "/static/img/number_pin_green.svg", "label": "Location Name" },
    "secondary_dark_blue_sphere": { "url": "/static/img/sphere_pin_secondary_dark_blue.svg", "label": "Location Name - Candidates" },
    "secondary_dark_blue_number": { "url": "/static/img/number_pin_secondary_dark_blue.svg", "label": "Location Name" },
    "teal_sphere": { "url": "/static/img/sphere_pin_teal.svg", "label": "Location Name - Candidates" },
    "teal_number": { "url": "/static/img/number_pin_teal.svg", "label": "Location Name" }
  };

  const pinSelectionDiv = document.getElementById("pinSelectionContainer");
  let selectedPinType = null;

  for (const [key, pinData] of Object.entries(pinTypes)) {
    const pinOption = document.createElement("div");
    pinOption.className = "pin-option";
    pinOption.dataset.pinType = key;

    const pinImage = document.createElement("img");
    pinImage.src = pinData.url;
    pinImage.alt = key;
    pinImage.className = "pin-image";

    const pinLabel = document.createElement("span");
    pinLabel.textContent = key.replace(/_/g, " ");
    pinLabel.style.fontSize = "12px";

    pinOption.appendChild(pinImage);
    pinOption.appendChild(pinLabel);
    pinOption.addEventListener("click", () => {
      if (selectedPinType) {
        document.querySelector(`.pin-option[data-pin-type=\"${selectedPinType}\"]`).classList.remove("selected-pin");
      }
      pinOption.classList.add("selected-pin");
      selectedPinType = key;
      document.getElementById("selected_pin_type").value = key;
    });

    pinSelectionDiv.appendChild(pinOption);
  }

  // Automatically select the first pin type
  const firstPinKey = Object.keys(pinTypes)[0];
  document.querySelector(`.pin-option[data-pin-type=\"${firstPinKey}\"]`).click();
</script>
</body>
</html>'''
        )

    if request.method == "POST":
        uploaded_file = request.files.get("file")
        if not uploaded_file:
            return "Error: No file uploaded.", 400
        filename = uploaded_file.filename.lower()
        if filename.endswith(".csv"):
            df = pd.read_csv(io.StringIO(uploaded_file.read().decode("utf-8")))
        elif filename.endswith(".xls") or filename.endswith(".xlsx"):
            df = pd.read_excel(uploaded_file)
        else:
            return "Error: Only .csv, .xls, or .xlsx supported.", 400
        required_cols = {"Location Name", "ZIP/Postal Code", "Electrification Candidates"}
        if not required_cols.issubset(df.columns):
            return "Error: Missing required columns.", 400
        def format_zip(value):
            if pd.isna(value) or value == "":
                return ""
            try:
                return f"{int(float(value)):05d}"
            except (ValueError, TypeError):
                return ""
        df["ZIP/Postal Code"] = df["ZIP/Postal Code"].apply(format_zip)
        for optional_col in ["Street Address", "City", "State"]:
            if optional_col not in df.columns:
                df[optional_col] = ""
            else:
                df[optional_col] = df[optional_col].fillna("")
        pin_type_key = request.form.get("pin_type")
        if not pin_type_key or pin_type_key not in PIN_TYPES:
            return "Error: No pin type selected or invalid pin type.", 400
        selected_pin_data = PIN_TYPES[pin_type_key]
        local_pin_url = selected_pin_data["url"]
        numbered_pin = selected_pin_data["numbered"]
        # Geocode
        geolocator = Nominatim(user_agent="grouped_map", timeout=10)
        geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1, max_retries=3)
        from shapely.geometry import Point
        def build_address_string(row):
            # Always use City, State, ZIP if available
            city = row["City"].strip()
            state = row["State"].strip()
            zipc = str(row["ZIP/Postal Code"]).strip()
            addr = ""
            if city and state and zipc:
                addr = f"{city}, {state} {zipc}, USA"
            elif city and state:
                addr = f"{city}, {state}, USA"
            elif zipc:
                addr = f"{zipc}, USA"
            else:
                addr = "USA"
            return addr
        lat_list, lon_list = [], []
        for _, row in df.iterrows():
            addr_str = build_address_string(row)
            loc = geocode(addr_str)
            lat, lon = None, None
            if loc:
                lat, lon = loc.latitude, loc.longitude
            elif row["ZIP/Postal Code"].strip():
                zip_loc = geocode(str(row["ZIP/Postal Code"]).strip() + ", USA")
                if zip_loc:
                    lat, lon = zip_loc.latitude, zip_loc.longitude
            # Fallback: state centroid
            if lat is None or lon is None:
                state_abbr = row["State"] if "State" in row and row["State"] else None
                if state_abbr and state_abbr in us_states["StateAbbr"].values:
                    state_geom = us_states[us_states["StateAbbr"] == state_abbr].geometry.values[0]
                    centroid = state_geom.centroid
                    lat, lon = centroid.y, centroid.x
                else:
                    lat, lon = None, None
            # Validate: is point in intended state?
            state_abbr = row["State"] if "State" in row and row["State"] else None
            if lat is not None and lon is not None and state_abbr and state_abbr in us_states["StateAbbr"].values:
                state_geom = us_states[us_states["StateAbbr"] == state_abbr].geometry.values[0]
                pt = Point(lon, lat)
                if not state_geom.contains(pt):
                    # Snap to state centroid
                    centroid = state_geom.centroid
                    lat, lon = centroid.y, centroid.x
            lat_list.append(lat)
            lon_list.append(lon)
        df["Latitude"] = lat_list
        df["Longitude"] = lon_list
        # Prepare pins for JS
        pins = []
        for _, row in df.iterrows():
            lat, lon = row["Latitude"], row["Longitude"]
            if pd.notnull(lat) and pd.notnull(lon):
                label = row["Location Name"]
                pin = {
                    "lat": lat,
                    "lng": lon,
                    "label": label,
                    "icon_url": local_pin_url,
                    "numbered": numbered_pin,
                    "svg_data": None
                }
                if numbered_pin:
                    svg_path = os.path.join('static', 'img', os.path.basename(local_pin_url))
                    if os.path.isfile(svg_path):
                        with open(svg_path, "r", encoding="utf-8") as f:
                            svg_content = f.read().replace("{{NUMBER}}", str(row['Electrification Candidates']))
                        pin["svg_data"] = svg_content
                pins.append(pin)
        # Prepare state polygons for JS
        state_polygons = []
        for _, row in us_states.iterrows():
            color = GROUP_COLORS.get(row["CaaS Group"], "#cccccc")
            geom = row["geometry"]
            if geom.geom_type == "Polygon":
                paths = [[[y, x] for x, y in geom.exterior.coords]]
            elif geom.geom_type == "MultiPolygon":
                paths = []
                for poly in geom.geoms:
                    paths.append([[y, x] for x, y in poly.exterior.coords])
            else:
                continue
            state_polygons.append({"paths": [
                [{"lat": pt[0], "lng": pt[1]} for pt in path] for path in paths
            ], "color": color})
        # Save map data to in-memory store
        map_id = str(uuid.uuid4())
        MAP_DATA[map_id] = {
            "pins": pins,
            "state_polygons": state_polygons,
            "pin_type": pin_type_key
        }
        # Redirect to embeddable map page
        return f'<div style="font-family:Calibri;font-size:18px;margin:2em;">Map generated! <a href="/google_map/{map_id}" target="_blank">View Map</a></div>'

# Embeddable map page
@app.route("/google_map/<map_id>")
def serve_google_map(map_id):
    data = MAP_DATA.get(map_id)
    if not data:
        return "Error: Map not found.", 404
    import json
    # Ensure booleans are lowercase for JS (true/false, not True/False)
    state_polygons_json = json.dumps(data["state_polygons"]).replace("True", "true").replace("False", "false")
    pins_json = json.dumps(data["pins"]).replace("True", "true").replace("False", "false")
    return render_template_string(
        GOOGLE_MAPS_EMBED_TEMPLATE,
        api_key=GOOGLE_MAPS_API_KEY,
        state_polygons=state_polygons_json,
        pins=pins_json,
        pin_type=json.dumps(data["pin_type"])
    )

    if request.method == "POST":
        uploaded_file = request.files.get("file")
        if not uploaded_file:
            return "Error: No file uploaded.", 400
        filename = uploaded_file.filename.lower()
        if filename.endswith(".csv"):
            df = pd.read_csv(io.StringIO(uploaded_file.read().decode("utf-8")))
        elif filename.endswith(".xls") or filename.endswith(".xlsx"):
            df = pd.read_excel(uploaded_file)
        else:
            return "Error: Only .csv, .xls, or .xlsx supported.", 400
        required_cols = {"Location Name", "ZIP/Postal Code", "Electrification Candidates"}
        if not required_cols.issubset(df.columns):
            return "Error: Missing required columns.", 400
        def format_zip(value):
            if pd.isna(value) or value == "":
                return ""
            try:
                return f"{int(float(value)):05d}"
            except (ValueError, TypeError):
                return ""
        df["ZIP/Postal Code"] = df["ZIP/Postal Code"].apply(format_zip)
        for optional_col in ["Street Address", "City", "State"]:
            if optional_col not in df.columns:
                df[optional_col] = ""
            else:
                df[optional_col] = df[optional_col].fillna("")
        pin_type_key = request.form.get("pin_type")
        if not pin_type_key or pin_type_key not in PIN_TYPES:
            return "Error: No pin type selected or invalid pin type.", 400
        selected_pin_data = PIN_TYPES[pin_type_key]
        local_pin_url = selected_pin_data["url"]
        numbered_pin = selected_pin_data["numbered"]
        label_template = selected_pin_data["label"]
        # Geocode
        geolocator = Nominatim(user_agent="grouped_map", timeout=10)
        geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1, max_retries=3)
        def build_address_string(row):
            address_parts = []
            if row["Street Address"].strip():
                address_parts.append(row["Street Address"].strip())
            if row["City"].strip():
                address_parts.append(row["City"].strip())
            if row["State"].strip():
                address_parts.append(row["State"].strip())
            if address_parts:
                return ", ".join(address_parts) + ", USA"
            else:
                return row["ZIP/Postal Code"] + ", USA"
        lat_list, lon_list = [], []
        for _, row in df.iterrows():
            addr_str = build_address_string(row)
            loc = geocode(addr_str)
            lat, lon = None, None
            if loc is None and row["Street Address"].strip():
                zip_loc = geocode(row["ZIP/Postal Code"] + ", USA")
                if zip_loc:
                    lat, lon = zip_loc.latitude, zip_loc.longitude
            elif loc:
                lat, lon = loc.latitude, loc.longitude
            if lat is None or lon is None:
                state_abbr = row["State"] if "State" in row and row["State"] else None
                if state_abbr and state_abbr in us_states["StateAbbr"].values:
                    state_geom = us_states[us_states["StateAbbr"] == state_abbr].geometry.values[0]
                    centroid = state_geom.centroid
                    lat, lon = centroid.y, centroid.x
                else:
                    lat, lon = None, None
            lat_list.append(lat)
            lon_list.append(lon)
        df["Latitude"] = lat_list
        df["Longitude"] = lon_list
        # Prepare pins for JS
        pins = []
        for _, row in df.iterrows():
            lat, lon = row["Latitude"], row["Longitude"]
            if pd.notnull(lat) and pd.notnull(lon):
                label = row["Location Name"]
                pin = {
                    "lat": lat,
                    "lng": lon,
                    "label": label,
                    "icon_url": local_pin_url,
                    "numbered": numbered_pin,
                    "svg_data": None
                }
                if numbered_pin:
                    svg_path = os.path.join('static', 'img', os.path.basename(local_pin_url))
                    if os.path.isfile(svg_path):
                        with open(svg_path, "r", encoding="utf-8") as f:
                            svg_content = f.read().replace("{{NUMBER}}", str(row['Electrification Candidates']))
                        pin["svg_data"] = svg_content
                pins.append(pin)
        # Prepare state polygons for JS
        state_polygons = []
        for _, row in us_states.iterrows():
            color = GROUP_COLORS.get(row["CaaS Group"], "#cccccc")
            geom = row["geometry"]
            if geom.geom_type == "Polygon":
                paths = [[[y, x] for x, y in geom.exterior.coords]]
            elif geom.geom_type == "MultiPolygon":
                paths = []
                for poly in geom.geoms:
                    paths.append([[y, x] for x, y in poly.exterior.coords])
            else:
                continue
            # Google Maps expects lat/lng order
            state_polygons.append({"paths": [
                [{"lat": pt[0], "lng": pt[1]} for pt in path] for path in paths
            ], "color": color})
        # Render map page
        return render_template_string(GOOGLE_MAPS_TEMPLATE,
            api_key=GOOGLE_MAPS_API_KEY,
            state_polygons=state_polygons,
            pins=pins,
            pin_type=pin_type_key
        )

if __name__ == "__main__":
    app.run(debug=True, port=5051)
