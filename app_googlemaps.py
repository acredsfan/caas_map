import os
import io
import uuid
from flask import Flask, request, send_from_directory, url_for, jsonify, render_template_string, redirect
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
        position: absolute;
        left: 70px;
        bottom: 40px;
        z-index: 5;
        font-size: 16.5px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.10);
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
<div id=\"map\"></div>
<div id=\"legend\">
  <b>State Grouping Color Guide</b><br>
  <div><span class=\"legend-color\" style=\"background:rgba(0,86,184,0.75)\"></span>Group 1 (Best Parity Probability)</div>
  <div><span class=\"legend-color\" style=\"background:rgba(0,161,224,0.75)\"></span>Group 2 (Better Parity Probability)</div>
  <div><span class=\"legend-color\" style=\"background:rgba(161,208,243,0.75)\"></span>Group 3 (Good Parity Probability)</div>
</div>
<script src="https://maps.googleapis.com/maps/api/js?key={{api_key}}"></script>
<script>
const statePolygons = {{ state_polygons|safe }};
const pins = {{ pins|safe }};
const pinType = {{ pin_type|tojson }};

// Per-pin-type anchor and labelOrigin offsets (pixels from top-left of image)
// These values should be set so the anchor is at the exact tip of the pin in the SVG/PNG
const PIN_ANCHORS = {
  // Format: [anchorX, anchorY, labelOffsetY]
  // Numbered pins: SVG 65x82, tip at (32,80)
  'primary_dark_blue_number':   [32, 41, 10],
  'primary_light_blue_number':  [32, 41, 10],
  'green_number':               [32, 41, 10],
  'secondary_dark_blue_number': [32, 41, 10],
  'teal_number':                [32, 41, 10],
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
  // Add pins directly to the map (no clustering)
    pins.forEach(function(pin) {
      let icon, iconSize, anchorX, anchorY, labelOriginY;
      if (pin.numbered && pin.svg_data) {
        iconSize = {w:65, h:82};
        anchorX = 32;
        anchorY = 41;
        // Place label below the pin: y = icon height - 20px
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
        // Place label below the pin: y = icon height + 1px
        labelOriginY = iconSize.h + 1;
        icon = {
          url: pin.icon_url,
          scaledSize: new google.maps.Size(iconSize.w, iconSize.h),
          anchor: new google.maps.Point(anchorX, anchorY),
          labelOrigin: new google.maps.Point(iconSize.w/2, labelOriginY)
        };
      }
      new google.maps.Marker({
        position: {lat: pin.lat, lng: pin.lng},
        icon: icon,
        title: pin.label,
        label: {
          text: pin.label,
          color: '#000',
          fontWeight: 'bold',
          fontSize: '16px',
          fontFamily: 'Calibri, Arial, sans-serif'
        },
        map: map
      });
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

# Directory for hosted map JSON files
HOSTED_MAPS_DIR = os.path.join("static", "maps")
os.makedirs(HOSTED_MAPS_DIR, exist_ok=True)

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

      <div style="margin-bottom:12px;">
        <label style="font-size:14px;">Show Location Name label on pins?
          <input type="checkbox" id="showLocationLabel" name="show_location_label" checked>
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

      // Show sphere options only for sphere pins
      if (key.endsWith('_sphere')) {
        document.getElementById('sphereOptions').style.display = '';
      } else {
        document.getElementById('sphereOptions').style.display = 'none';
      }
    });

    pinSelectionDiv.appendChild(pinOption);
  }

  // No per-pin label logic needed

  // Automatically select the first pin type
  const firstPinKey = Object.keys(pinTypes)[0];
  document.querySelector(`.pin-option[data-pin-type=\"${firstPinKey}\"]`).click();
  updateHiddenSphereOptions();
</script>
</body>
</html>'''
        )

    if request.method == "POST":
        uploaded_file = request.files.get("file")
        if not uploaded_file:
            return "Error: No file uploaded.", 400
        filename = uploaded_file.filename
        if not filename:
            return "Error: Uploaded file has no filename.", 400
        filename = filename.lower()
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
        # Show location label for all pins?
        show_location_label = request.form.get("show_location_label") == 'on'

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
        geocode_warnings = []
        api_key = GOOGLE_MAPS_API_KEY
        for idx, row in df.iterrows():
            addr_str = build_address_string(row)
            lat, lon = google_geocode(addr_str, api_key)
            snapped = False
            failed = False
            if (lat is None or lon is None) and row["ZIP/Postal Code"].strip():
                zip_addr = f"{row['ZIP/Postal Code']}, USA"
                lat, lon = google_geocode(zip_addr, api_key)
            # Fallback: state centroid
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
            # Validate: is point in intended state?
            state_abbr = row["State"] if "State" in row and row["State"] else None
            if lat is not None and lon is not None and state_abbr and state_abbr in us_states["StateAbbr"].values:
                state_geom = us_states[us_states["StateAbbr"] == state_abbr].geometry.values[0]
                pt = Point(lon, lat)
                if not state_geom.contains(pt):
                    # Snap to state centroid
                    centroid = state_geom.centroid
                    lat, lon = centroid.y, centroid.x
                    snapped = True
            try:
                row_num = int(idx) + 2
            except Exception:
                row_num = 2  # fallback if idx is not convertible
            if failed or snapped:
                geocode_warnings.append({
                    "row": row_num,  # +2 for header and 0-index
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
        # Prepare pins for JS
        pins = []
        for _, row in df.iterrows():
            lat, lon = row["Latitude"], row["Longitude"]
            if pd.notnull(lat) and pd.notnull(lon):
                label = row["Location Name"] if show_location_label else ''
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
        # Show geocode warnings if any
        warning_html = ""
        if geocode_warnings:
            warning_html = '<div style="background:#fff3cd;color:#856404;border:1px solid #ffeeba;padding:12px 18px;border-radius:6px;margin-bottom:1.5em;font-size:16px;max-width:700px;">'
            warning_html += '<b>Warning:</b> Some locations could not be geocoded and were snapped to the state centroid:<br><ul style="margin:0 0 0 1.5em;">'
            for w in geocode_warnings:
                warning_html += f'<li>Row {w["row"]}: {w["location"]} ({w["city"]}, {w["state"]}, {w["zip"]}) &mdash; {w["reason"]}</li>'
            warning_html += '</ul></div>'
        # Offer to save for hosting with map name
        return f'''{warning_html}<div style="font-family:Calibri;font-size:18px;margin:2em;">Map generated! <a href="/google_map/{map_id}" target="_blank">View Map</a><br><br>
        <form method="POST" action="/host_map/{map_id}" style="display:inline;">
            <label for="map_name" style="font-size:15px;">Map Name:</label>
            <input type="text" id="map_name" name="map_name" maxlength="100" required style="font-size:15px;padding:4px 8px;border-radius:4px;border:1px solid #aaa;margin-right:10px;">
            <button type="submit" style="background:#0056b8;color:#fff;border:none;border-radius:4px;padding:8px 14px;font-size:15px;cursor:pointer;">Save for Hosting</button>
        </form></div>'''
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
        # Try to load from disk
        path = os.path.join(HOSTED_MAPS_DIR, f"{map_id}.json")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            return "Error: Map not found.", 404
    # Ensure booleans are lowercase for JS (true/false, not True/False)
    return render_template_string(
        GOOGLE_MAPS_EMBED_TEMPLATE,
        api_key=GOOGLE_MAPS_API_KEY,
        state_polygons=json.dumps(data["state_polygons"]).replace("True", "true").replace("False", "false"),
        pins=json.dumps(data["pins"]).replace("True", "true").replace("False", "false"),
        pin_type=json.dumps(data["pin_type"])
    )


# Root route redirects to /google_maps
@app.route("/")
def index():
    return redirect("/google_maps")


if __name__ == "__main__":
    app.run(debug=True, port=5051)
