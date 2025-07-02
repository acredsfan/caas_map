import os
import io
import uuid
from flask import Flask, request, send_from_directory, url_for, jsonify, render_template_string, redirect, Response
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
        background: white;
        padding: 16px 20px 16px 20px;
        border: 2px solid #888;
        border-radius: 10px;
        position: relative;
        left: 32px;
        bottom: 40px;
        width: 200px;
        z-index: 5;
        font-size: 16.5px;
        margin-left: 0;
        box-shadow: 0 6px 24px 0 rgba(0,0,0,0.18), 0 1.5px 6px 0 rgba(0,0,0,0.10);
      }
      .legend-color {
        display: inline-block;
        width: 24px;
        height: 16px;
        margin-right: 10px;
        border-radius: 4px;
        opacity: 1;
        vertical-align: middle;
      }
      /* Remove custom label styling for default Google Maps labels */
    </style>
</head>
<body>
<div style="position:relative;z-index:10;">
  <h1 style="font-family:Calibri,Arial,sans-serif;font-size:2.1em;font-weight:normal;color:#00245c;text-align:center;margin:24px 0 8px 0;letter-spacing:0.01em;">
    EV/ICE Total Cost of Ownership (TCO) Parity Probability Map
  </h1>
</div>
<div style="display:flex;flex-direction:row;align-items:flex-start;width:100%;height:80vh;min-height:480px;">
  <div id=\"map\" style="flex:1 1 0%;min-width:0;height:100%;min-height:480px;"></div>
  <div id=\"cluster-table-container\" style="flex:0 0 350px;max-width:350px;margin-left:24px;display:none;height:100%;overflow-y:auto;">
    <h2 style="font-family:Calibri,Arial,sans-serif;font-size:1.2em;font-weight:bold;color:#00245c;text-align:left;margin:12px 0 8px 0;">Clustered Locations</h2>
    <table id=\"cluster-table\" style="width:100%;border-collapse:collapse;font-family:Calibri,Arial,sans-serif;font-size:1em;">
      <thead><tr><th style='text-align:left;padding:4px 8px;border-bottom:1px solid #bbb;'>Location Name</th><th style='text-align:right;padding:4px 8px;border-bottom:1px solid #bbb;'>Electrification Candidates</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>
<div id=\"legend\"> 
  <b>State Grouping Color Guide</b><br>
  <div><span class=\"legend-color\" style=\"background:rgba(0,86,184,0.75)\"></span>Group 1 (Best Parity Probability)</div>
  <div><span class=\"legend-color\" style=\"background:rgba(0,161,224,0.75)\"></span>Group 2 (Better Parity Probability)</div>
  <div><span class=\"legend-color\" style=\"background:rgba(161,208,243,0.75)\"></span>Group 3 (Good Parity Probability)</div>
</div>
<script src="https://maps.googleapis.com/maps/api/js?key={{api_key}}"></script>
<script src="https://unpkg.com/@googlemaps/markerclustererplus/dist/index.min.js"></script>
<script>
const statePolygons = {{ state_polygons|safe }};
let pins = {{ pins|safe }};
const clusteringEnabled = {{ clustering_enabled|tojson }};
// Use info_label for info window content
pins = pins.map(function(pin) {
  if (typeof pin.info_label === 'undefined' && typeof pin.label !== 'undefined') {
    pin.info_label = pin.label;
  }
  return pin;
});
const pinType = {{ pin_type|tojson }};

const PIN_ANCHORS = {
  'primary_dark_blue_number':   [32, 41, 10],
  'primary_light_blue_number':  [32, 41, 10],
  'green_number':               [32, 41, 10],
  'secondary_dark_blue_number': [32, 41, 10],
  'teal_number':                [32, 41, 10],
  'primary_dark_blue_sphere':   [25, 50, 10],
  'primary_light_blue_sphere':  [25, 50, 10],
  'green_sphere':               [25, 50, 10],
  'secondary_dark_blue_sphere': [25, 50, 10],
  'teal_sphere':                [25, 50, 10],
};
function getPinAnchor(pinType, iconSize) {
  if (PIN_ANCHORS[pinType]) return PIN_ANCHORS[pinType];
  return [Math.floor(iconSize.w/2), iconSize.h, 10];
}

function initMap() {
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
  statePolygons.forEach(function(poly) {
    const polygon = new google.maps.Polygon({
      paths: poly.paths,
      strokeColor: '#000',
      strokeOpacity: 0.7,
      strokeWeight: 1,
      fillColor: poly.color,
      fillOpacity: 0.75
    });
    polygon.setMap(map);
  });
  const infoWindow = new google.maps.InfoWindow();
  let markers = [];
  pins.forEach(function(pin) {
    let icon, iconSize, anchorX, anchorY, labelOriginY, markerLabel = null;
    let labelText = pin.info_label || pin.label || '';
    if (pin.numbered && pin.svg_data) {
      iconSize = {w:65, h:82};
      anchorX = 32;
      anchorY = 41;
      labelOriginY = iconSize.h - 20;
      icon = {
        url: 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(pin.svg_data),
        scaledSize: new google.maps.Size(iconSize.w, iconSize.h),
        anchor: new google.maps.Point(anchorX, anchorY),
        labelOrigin: new google.maps.Point(iconSize.w/2, labelOriginY)
      };
    } else {
      iconSize = {w:50, h:50};
      anchorX = 25;
      anchorY = 50;
      labelOriginY = iconSize.h + 1;
      icon = {
        url: pin.icon_url,
        scaledSize: new google.maps.Size(iconSize.w, iconSize.h),
        anchor: new google.maps.Point(anchorX, anchorY),
        labelOrigin: new google.maps.Point(iconSize.w/2, labelOriginY)
      };
    }
    markerLabel = {
      text: labelText,
      color: '#222',
      fontWeight: 'bold',
      fontSize: '13px',
      fontFamily: 'Calibri, Arial, sans-serif',
      textShadow: '0 0 2px #fff, 0 0 2px #fff, 0 0 2px #fff, 0 0 2px #fff'
    };
    const marker = new google.maps.Marker({
      position: {lat: pin.lat, lng: pin.lng},
      icon: icon,
      title: labelText,
      label: markerLabel,
      map: map
    });
    markers.push(marker);
  });
  if (clusteringEnabled) {
    const clusterer = new markerClusterer.MarkerClusterer({
      map,
      markers,
      onClusterClick: (event) => {
        // Not used, but could zoom to cluster
      }
    });
    // Build cluster table
    const clusterTableContainer = document.getElementById('cluster-table-container');
    clusterTableContainer.style.display = '';
    const tableBody = document.getElementById('cluster-table').querySelector('tbody');
    tableBody.innerHTML = '';
    // For each cluster, list locations and candidates
    // markerClusterer does not expose clusters directly, so we list all pins
    pins.forEach(function(pin) {
      const row = document.createElement('tr');
      const nameCell = document.createElement('td');
      nameCell.textContent = pin.info_label || pin.label || '';
      nameCell.style.padding = '4px 8px';
      const candCell = document.createElement('td');
      candCell.textContent = pin.electrification_candidates || '';
      candCell.style.textAlign = 'right';
      candCell.style.padding = '4px 8px';
      row.appendChild(nameCell);
      row.appendChild(candCell);
      tableBody.appendChild(row);
    });
  }
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

# Directory for hosted map JSON files
HOSTED_MAPS_DIR = os.path.join("static", "maps")
os.makedirs(HOSTED_MAPS_DIR, exist_ok=True)

@app.route("/google_maps", methods=["GET", "POST"])
def google_maps_form():
    if request.method == "GET":
        # Add clustering checkbox to upload form
        return Response(render_template_string(
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

      <div style="margin-bottom:12px;">
        <label style="font-size:14px;">
          <input type="checkbox" id="clusteringCheckbox" name="clustering_enabled" checked>
          Enable Clustering (show cluster table)
        </label>
      </div>

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
</html>''', mimetype="text/html")
        )

    if request.method == "POST":
        uploaded_file = request.files.get("file")
        if not uploaded_file:
            return Response("Error: No file uploaded.", status=400)
        filename = uploaded_file.filename
        if not filename:
            return Response("Error: Uploaded file has no filename.", status=400)
        filename = filename.lower()
        if filename.endswith(".csv"):
            df = pd.read_csv(io.StringIO(uploaded_file.read().decode("utf-8")))
        elif filename.endswith(".xls") or filename.endswith(".xlsx"):
            df = pd.read_excel(uploaded_file)
        else:
            return Response("Error: Only .csv, .xls, or .xlsx supported.", status=400)
        required_cols = {"Location Name", "ZIP/Postal Code", "Electrification Candidates"}
        if not required_cols.issubset(df.columns):
            return Response("Error: Missing required columns.", status=400)

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
            return Response("Error: No pin type selected or invalid pin type.", status=400)
        selected_pin_data = PIN_TYPES[pin_type_key]
        local_pin_url = selected_pin_data["url"]
        numbered_pin = selected_pin_data["numbered"]
        clustering_enabled = request.form.get("clustering_enabled") == 'on' or request.form.get("clustering_enabled") == 'true' or request.form.get("clustering_enabled") == 'checked'

        import requests
        from shapely.geometry import Point

        def google_geocode(address, api_key):
            url = "https://maps.googleapis.com/maps/api/geocode/json"
            params = {"address": address, "key": api_key}
            try:
                resp = requests.get(url, params=params, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "OK" and data["results"]:
                        loc = data["results"][0]["geometry"]["location"]
                        return loc["lat"], loc["lng"]
            except Exception:
                pass
            return None, None

        def build_address_string(row):
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
        geocode_warnings = []
        api_key = GOOGLE_MAPS_API_KEY
        for idx, (row_idx, row) in enumerate(df.iterrows()):
            addr_str = build_address_string(row)
            lat, lon = google_geocode(addr_str, api_key)
            snapped = False
            failed = False
            if (lat is None or lon is None) and row["ZIP/Postal Code"].strip():
                zip_addr = f"{row['ZIP/Postal Code']}, USA"
                lat, lon = google_geocode(zip_addr, api_key)
            if lat is None or lon is None:
                state_abbr = row["State"] if "State" in row and row["State"] else None
                if state_abbr and state_abbr in us_states["StateAbbr"].values:
                    state_geom = us_states[us_states["StateAbbr"] == state_abbr].geometry.values[0]
                    centroid = state_geom.centroid
                    lat, lon = centroid.y, centroid.x
                    snapped = True
                else:
                    lat, lon = None, None
                    failed = True
            state_abbr = row["State"] if "State" in row and row["State"] else None
            if lat is not None and lon is not None and state_abbr and state_abbr in us_states["StateAbbr"].values:
                state_geom = us_states[us_states["StateAbbr"] == state_abbr].geometry.values[0]
                pt = Point(lon, lat)
                if not state_geom.contains(pt):
                    centroid = state_geom.centroid
                    lat, lon = centroid.y, centroid.x
                    snapped = True
            row_num = idx + 2
            if failed or snapped:
                geocode_warnings.append({
                    "row": row_num,
                    "location": row["Location Name"],
                    "city": row["City"],
                    "state": row["State"],
                    "zip": row["ZIP/Postal Code"],
                    "reason": "Could not geocode, snapped to state centroid" if snapped else "Could not geocode, no valid state"
                })
            lat_list.append(lat)
            lon_list.append(lon)
        df["Latitude"] = lat_list
        df["Longitude"] = lon_list
        pins = []
        for _, row in df.iterrows():
            lat, lon = row["Latitude"], row["Longitude"]
            if pd.notnull(lat) and pd.notnull(lon):
                label = str(row["Location Name"])
                pin = {
                    "lat": lat,
                    "lng": lon,
                    "label": label,
                    "info_label": label,
                    "icon_url": local_pin_url,
                    "numbered": numbered_pin,
                    "svg_data": None,
                    "electrification_candidates": str(row["Electrification Candidates"])
                }
                if numbered_pin:
                    svg_path = os.path.join('static', 'img', os.path.basename(local_pin_url))
                    if os.path.isfile(svg_path):
                        with open(svg_path, "r", encoding="utf-8") as f:
                            svg_content = f.read().replace("{{NUMBER}}", str(row['Electrification Candidates']))
                        pin["svg_data"] = svg_content
                pins.append(pin)
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
        map_id = str(uuid.uuid4())
        MAP_DATA[map_id] = {
            "pins": pins,
            "state_polygons": state_polygons,
            "pin_type": pin_type_key,
            "clustering_enabled": clustering_enabled
        }
        warning_html = ""
        if geocode_warnings:
            warning_html = '<div style="background:#fff3cd;color:#856404;border:1px solid #ffeeba;padding:12px 18px;border-radius:6px;margin-bottom:1.5em;font-size:16px;max-width:700px;">'
            warning_html += '<b>Warning:</b> Some locations could not be geocoded and were snapped to the state centroid:<br><ul style="margin:0 0 0 1.5em;">'
            for w in geocode_warnings:
                warning_html += f'<li>Row {w["row"]}: {w["location"]} ({w["city"]}, {w["state"]}, {w["zip"]}) &mdash; {w["reason"]}</li>'
            warning_html += '</ul></div>'
        return Response(f'''{warning_html}<div style="font-family:Calibri;font-size:18px;margin:2em;">Map generated! <a href="/google_map/{map_id}" target="_blank">View Map</a><br><br>
        <form method="POST" action="/host_map/{map_id}" style="display:inline;">
            <label for="map_name" style="font-size:15px;">Map Name:</label>
            <input type="text" id="map_name" name="map_name" maxlength="100" required style="font-size:15px;padding:4px 8px;border-radius:4px;border:1px solid #aaa;margin-right:10px;">
            <button type="submit" style="background:#0056b8;color:#fff;border:none;border-radius:4px;padding:8px 14px;font-size:15px;cursor:pointer;">Save for Hosting</button>
        </form></div>''', mimetype="text/html")
# Save a map for hosting (persist to disk)
@app.route("/host_map/<map_id>", methods=["POST"])
def host_map(map_id):
    data = MAP_DATA.get(map_id)
    if not data:
        return "Error: Map not found.", 404
    # Get map name from form
    map_name = request.form.get("map_name", "Untitled Map").strip()
    if not map_name:
        map_name = "Untitled Map"
    data = dict(data)  # copy to avoid mutating in-memory
    data["map_name"] = map_name
    # Save to disk as JSON
    out_path = os.path.join(HOSTED_MAPS_DIR, f"{map_id}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return redirect("/hosted_maps")

# List all hosted maps
@app.route("/hosted_maps")
def list_hosted_maps():
    files = [f for f in os.listdir(HOSTED_MAPS_DIR) if f.endswith(".json")]
    hosted = []
    for fname in files:
        map_id = fname.replace(".json", "")
        # Try to get a title from map_name, fallback to first pin label
        try:
            with open(os.path.join(HOSTED_MAPS_DIR, fname), "r", encoding="utf-8") as f:
                data = json.load(f)
            title = data.get("map_name") or (data["pins"][0]["label"] if data.get("pins") else map_id)
        except Exception:
            title = map_id
        hosted.append({"id": map_id, "title": title})
    html = '<div style="font-family:Calibri;max-width:800px;margin:2em auto;">'
    html += '<h2>Hosted Maps</h2>'
    html += '<ul style="font-size:18px;">'
    for m in hosted:
        html += f'<li><a href="/google_map/{m["id"]}" target="_blank">{m["title"]}</a> '
        html += f'<form method="POST" action="/delete_map/{m["id"]}" style="display:inline;margin-left:1em;" onsubmit="return confirm(\'Delete this map?\');"><button type="submit" style="background:#b80000;color:#fff;border:none;border-radius:4px;padding:4px 10px;font-size:14px;cursor:pointer;">Delete</button></form></li>'
    html += '</ul>'
    html += '<a href="/google_maps">Back to Upload</a>'
    html += '</div>'
    return html

# Delete a hosted map
@app.route("/delete_map/<map_id>", methods=["POST"])
def delete_map(map_id):
    path = os.path.join(HOSTED_MAPS_DIR, f"{map_id}.json")
    if os.path.isfile(path):
        os.remove(path)
    return redirect("/hosted_maps")


# Embeddable map page


# Serve a map by ID, from memory or disk
@app.route("/google_map/<map_id>")
def serve_google_map(map_id):
    data = MAP_DATA.get(map_id)
    if not data:
        path = os.path.join(HOSTED_MAPS_DIR, f"{map_id}.json")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            return "Error: Map not found.", 404
    return render_template_string(
        GOOGLE_MAPS_EMBED_TEMPLATE,
        api_key=GOOGLE_MAPS_API_KEY,
        state_polygons=json.dumps(data["state_polygons"]).replace("True", "true").replace("False", "false"),
        pins=json.dumps(data["pins"]).replace("True", "true").replace("False", "false"),
        pin_type=json.dumps(data["pin_type"]),
        clustering_enabled=json.dumps(data.get("clustering_enabled", True))
    )


# Root route redirects to /google_maps
@app.route("/")
def index():
    return redirect("/google_maps")


if __name__ == "__main__":
    app.run(debug=True, port=5051)
