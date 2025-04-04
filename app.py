import os
import io
import json
import uuid
import base64
from flask import Flask, request, send_from_directory, url_for

import pandas as pd
import geopandas as gpd
import folium
from shapely.geometry import Point
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

app = Flask(__name__)
app.config['SERVER_NAME'] = 'localhost:5001'
app.app_context().push()

# Directories
os.makedirs("static/maps", exist_ok=True)
os.makedirs("static/img", exist_ok=True)

# Preload tiers & shapefile
state_tiers = pd.read_csv(r"./input_csv_files/tier_by_state.csv")
us_states = gpd.read_file(r"./us_state_boundary_shapefiles/ne_10m_admin_1_states_provinces_lakes.shp")
us_states = us_states[us_states['admin'] == 'United States of America']
us_states["StateAbbr"] = us_states["iso_3166_2"].str.split("-").str[-1]
us_states = us_states.merge(state_tiers, left_on="StateAbbr", right_on="State", how="left")

TIER_COLORS = {
    "Tier 1": "#0056b8",
    "Tier 2": "#00a1e0",
    "Tier 3": "#a1d0f3"
}

# ------------------------------------------
# Helper function to load an SVG and inject the row's candidate number
# ------------------------------------------
def load_and_inject_svg(svg_path, number_value):
    with open(svg_path, "r", encoding="utf-8") as f:
        svg_content = f.read()
    # Replace the placeholder {{NUMBER}} with the actual numeric value
    svg_content = svg_content.replace("{{NUMBER}}", str(number_value))
    return svg_content

# Pin definitions
PIN_TYPES = {
    "primary_dark_blue_sphere": {
        "url": url_for('static', filename='img/sphere_pin_primary_dark_blue.svg'),
        "numbered": False,
        "label": "Location Name - Candidates"
    },
    "primary_dark_blue_number": {
        "url": url_for('static', filename='img/number_pin_primary_dark_blue.svg'),
        "numbered": True,
        "label": "Location Name"
    },
    "primary_light_blue_sphere": {
        "url": url_for('static', filename='img/sphere_pin_primary_light_blue.svg'),
        "numbered": False,
        "label": "Location Name - Candidates"
    },
    "primary_light_blue_number": {
        "url": url_for('static', filename='img/number_pin_primary_light_blue.svg'),
        "numbered": True,
        "label": "Location Name"
    },
    "green_sphere": {
        "url": url_for('static', filename='img/sphere_pin_green.svg'),
        "numbered": False,
        "label": "Location Name - Candidates"
    },
    "green_number": {
        "url": url_for('static', filename='img/number_pin_green.svg'),
        "numbered": True,
        "label": "Location Name"
    },
    "secondary_dark_blue_sphere": {
        "url": url_for('static', filename='img/sphere_pin_secondary_dark_blue.svg'),
        "numbered": False,
        "label": "Location Name - Candidates"
    },
    "secondary_dark_blue_number": {
        "url": url_for('static', filename='img/number_pin_secondary_dark_blue.svg'),
        "numbered": True,
        "label": "Location Name"
    },
    "teal_sphere": {
        "url": url_for('static', filename='img/sphere_pin_teal.svg'),
        "numbered": False,
        "label": "Location Name - Candidates"
    },
    "teal_number": {
        "url": url_for('static', filename='img/number_pin_teal.svg'),
        "numbered": True,
        "label": "Location Name"
    }
}

# Nicer form template with updated styling
FORM_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Map Uploader</title>
    <style>
      body {
        margin: 0;
        padding: 0;
        font-family: Calibri, sans-serif;
        background: #f4f7fa; /* Soft page background */
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
        border-color: #00a1e0; /* highlight border color when selected */
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
    <h1>Upload CSV/XLS/XLSX to Plot Pins</h1>
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
        document.querySelector(`.pin-option[data-pin-type="${selectedPinType}"]`).classList.remove("selected-pin");
      }
      pinOption.classList.add("selected-pin");
      selectedPinType = key;
      document.getElementById("selected_pin_type").value = key;
    });

    pinSelectionDiv.appendChild(pinOption);
  }

  // Automatically select the first pin type
  const firstPinKey = Object.keys(pinTypes)[0];
  document.querySelector(`.pin-option[data-pin-type="${firstPinKey}"]`).click();
</script>
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def upload_form():
    if request.method == "GET":
        return FORM_TEMPLATE

    if request.method == "POST":
        uploaded_file = request.files.get("file")
        if not uploaded_file:
            return "Error: No file uploaded.", 400

        filename = uploaded_file.filename.lower()
        # Read CSV or Excel
        if filename.endswith(".csv"):
            df = pd.read_csv(io.StringIO(uploaded_file.read().decode("utf-8")))
        elif filename.endswith(".xls") or filename.endswith(".xlsx"):
            df = pd.read_excel(uploaded_file)
        else:
            return "Error: Only .csv, .xls, or .xlsx supported.", 400

        # Check required columns
        required_cols = {"Location Name", "ZIP/Postal Code", "Electrification Candidates"}
        if not required_cols.issubset(df.columns):
            return "Error: Missing required columns.", 400

        # Format ZIP
        df["ZIP/Postal Code"] = df["ZIP/Postal Code"].apply(lambda z: f"{int(z):05d}")

        # Ensure optional columns exist, even if empty
        for optional_col in ["Street Address", "City", "State"]:
            if optional_col not in df.columns:
                df[optional_col] = ""
            else:
                df[optional_col] = df[optional_col].fillna("")

        # Get selected pin type
        pin_type_key = request.form.get("pin_type")
        if not pin_type_key or pin_type_key not in PIN_TYPES:
            return "Error: No pin type selected or invalid pin type.", 400

        selected_pin_data = PIN_TYPES[pin_type_key]
        local_pin_url = selected_pin_data["url"]   # For non-numbered pins
        numbered_pin = selected_pin_data["numbered"]
        label_template = selected_pin_data["label"]

        # Build the Folium map
        m = folium.Map(
            location=[39.8283, -98.5795],
            zoom_start=5,
            tiles='https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png',
            attr='©OpenStreetMap contributors ©CartoDB'
        )

        # State layer
        folium.GeoJson(
            data=us_states.__geo_interface__,
            style_function=lambda feat: {
                'fillColor': TIER_COLORS.get(feat['properties']['CaaS Tier'], 'gray'),
                'color': 'black',
                'weight': 1,
                'fillOpacity': 1.0
            },
            tooltip=folium.features.GeoJsonTooltip(fields=['name'], aliases=['State:'])
        ).add_to(m)

        # Legend
        legend_html = """
        <div style="position: fixed; bottom: 50px; left: 50px; width:auto; height:auto;
        background-color: white; border:2px solid grey; z-index:9999; border-radius:5px;
        padding: 10px; white-space:nowrap; text-align: center;">
          <h4 style="margin-top:0; margin-bottom: 10px; font-weight: bold; font-family: Calibri">State Grouping Color Guide</h4>
          <div style="margin-bottom:5px; display: flex; align-items: center;">
            <i style="background:#9EC1F7;width:40px;height:20px;display:inline-block;margin-right:8px;"></i>
            Group 1 (Best Parity Probability)
          </div>
          <div style="margin-bottom:5px; display: flex; align-items: center;">
            <i style="background:#4C84C4;width:40px;height:20px;display:inline-block;margin-right:8px;"></i>
            Group 2 (Better Parity Probability)
          </div>
          <div style="display: flex; align-items: center;">
            <i style="background:#1C4E80;width:40px;height:20px;display:inline-block;margin-right:8px;"></i>
            Group 3 (Good Parity Probability)
          </div>
        </div>
        """
        m.get_root().html.add_child(folium.Element(legend_html))

        # Geocoder
        geolocator = Nominatim(user_agent="tiered_map", timeout=10)
        geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1, max_retries=3)

        def build_address_string(row):
            # Priority: Street/City/State if present, else fallback to ZIP
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

        # Geocode each row
        lat_list, lon_list = [], []
        for _, row in df.iterrows():
            addr_str = build_address_string(row)
            loc = geocode(addr_str)
            if loc is None and row["Street Address"].strip():
                # fallback to just ZIP
                zip_loc = geocode(row["ZIP/Postal Code"] + ", USA")
                lat_list.append(zip_loc.latitude if zip_loc else None)
                lon_list.append(zip_loc.longitude if zip_loc else None)
            else:
                lat_list.append(loc.latitude if loc else None)
                lon_list.append(loc.longitude if loc else None)

        df["Latitude"] = lat_list
        df["Longitude"] = lon_list

        # Build geometry and label arrays
        geometry = []
        labels = []
        marker_svgs = []  # This will hold per-row injected SVG (only for numbered pins)

        for _, row in df.iterrows():
            lat, lon = row["Latitude"], row["Longitude"]
            if pd.notnull(lat) and pd.notnull(lon):
                geometry.append(Point(lon, lat))

                # Build label text
                if numbered_pin:
                    # Bold label if it's a numbered pin
                    label_str = f"""
                        <div style="
                            background-color: rgba(255, 255, 255, 0.7);
                            padding: 4px 8px;
                            border-radius: 18px;
                            font-size: 13px;
                            font-family: 'Calibri';
                            font-weight: bold;
                            color: #000000;
                            text-align: center;
                            margin-top: 5px;
                            box-shadow: 1px 1px 3px rgba(0,0,0,0.2);
                            white-space: nowrap;
                        ">
                            {row['Location Name']}
                        </div>
                    """
                else:
                    # Non-numbered pin label
                    label_str = f"""
                        <div style="
                            background-color: rgba(255, 255, 255, 0.85);
                            padding: 6px 12px;
                            border-radius: 18px;
                            font-size: 14px;
                            font-family: 'Calibri';
                            font-weight: normal;
                            color: #000000;
                            text-align: center;
                            border: 1.5px solid #b3b3b3;
                            box-shadow: 2px 2px 4px rgba(0,0,0,0.2);
                            white-space: nowrap;
                        ">
                            {label_template.replace("Location Name", row['Location Name'])
                                           .replace("Candidates", str(row['Electrification Candidates']))}
                        </div>
                    """
                labels.append(label_str)

                # For numbered pins, inject the correct candidate count into the chosen SVG
                if numbered_pin:
                    svg_path = os.path.join("static", "img", os.path.basename(local_pin_url))
                    svg_injected = load_and_inject_svg(svg_path, row["Electrification Candidates"])
                    marker_svgs.append(svg_injected)
                else:
                    marker_svgs.append(None)
            else:
                geometry.append(None)
                labels.append(None)
                marker_svgs.append(None)

        # Build the GeoDataFrame
        marker_gdf = gpd.GeoDataFrame({
            "label": labels,
            "ElectrificationCandidates": df["Electrification Candidates"],
            "svgIcon": marker_svgs  # store final per-row SVG here
        }, geometry=geometry, crs="EPSG:4326")

        marker_gdf.dropna(subset=["geometry"], inplace=True)

        # Convert to JSON so we can pass it to JavaScript
        marker_data_json = json.dumps(marker_gdf.__geo_interface__)

        # Inline the collision plugin
        collision_js_path = os.path.join("static", "js", "L.LabelTextCollision.js")
        if not os.path.isfile(collision_js_path):
            return "Error: L.LabelTextCollision.js not found in static/js/ folder.", 400

        with open(collision_js_path, "r", encoding="utf-8") as f:
            collision_js = f.read()

        map_var = m.get_name()

        # Custom JS that uses the per-row injected SVG for numbered pins
        custom_js = f"""
        {collision_js}

        window.addEventListener("load", function() {{
            var markerData = {marker_data_json};
            var pinIconUrl = "{local_pin_url}";
            var numberedPin = {"true" if numbered_pin else "false"};

            var markerCollisionLayer = L.geoJson(markerData, {{
                renderer: new L.LabelTextCollision({{collisionFlg: true, labelPadding: 0}}),
                pointToLayer: function(feature, latlng) {{
                    if (numberedPin) {{
                        // Use the injected SVG from our 'svgIcon' property
                        const svgIcon = feature.properties.svgIcon;
                        var pinIcon = L.divIcon({{
                            html: svgIcon,
                            className: 'custom-numbered-pin',
                            iconSize: [65, 80],
                            iconAnchor: [32.5, 80]
                        }});
                        var labelContent = feature.properties.label;
                        var marker = L.marker(latlng, {{ icon: pinIcon }});
                        marker.bindTooltip(labelContent, {{
                            permanent: true,
                            direction: 'bottom',
                            offset: [0, -50],
                            className: 'always-visible-label-below'
                        }});
                        return marker;
                    }} else {{
                        // Non-numbered pins use standard Leaflet Icon with iconUrl
                        var pinIcon = L.icon({{
                            iconUrl: pinIconUrl,
                            iconSize: [50, 50],
                            iconAnchor: [25, 50]
                        }});
                        var labelContent = feature.properties.label;
                        var marker = L.marker(latlng, {{icon: pinIcon}});
                        marker.bindTooltip(labelContent, {{
                            permanent: true,
                            direction: 'right',
                            offset: [0, 0],
                            className: 'always-visible-label'
                        }});
                        return marker;
                    }}
                }}
            }});

            markerCollisionLayer.addTo({map_var});
        }});
        """
        m.get_root().script.add_child(folium.Element(custom_js))

        # Label styling
        label_style = """
        <style>
        /* Turn off Leaflet's bubble for these tooltip classes */
        .leaflet-tooltip.always-visible-label,
        .leaflet-tooltip.always-visible-label-below {
            margin-top: 0 !important;
            background: none !important;
            border: none !important;
            box-shadow: none !important;
            padding: 0 !important;
        }
        .leaflet-tooltip.always-visible-label:before,
        .leaflet-tooltip.always-visible-label:after,
        .leaflet-tooltip.always-visible-label-below:before,
        .leaflet-tooltip.always-visible-label-below:after {
            content: none !important;
            display: none !important;
        }

        /* Non-numbered label styling */
        .always-visible-label {
            border-radius: 18px;
            font-size: 14px;
            font-family: 'Calibri';
            font-weight: normal;
            color: #000;
            text-align: center;
            white-space: nowrap;
        }

        /* Numbered label styling */
        .always-visible-label-below {
            border-radius: 14px;
            font-size: 13px;
            font-family: 'Calibri';
            font-weight: bold;
            color: #000;
            text-align: center;
            white-space: nowrap;
            margin-top: 0;
        }

        /* Slight drop-shadow behind the numbered pins */
        .custom-numbered-pin .leaflet-marker-icon div {
            background: none;
            border: none;
            box-shadow: 5px 5px 10px #666;
            padding: 0;
        }
        </style>
        """
        m.get_root().html.add_child(folium.Element(label_style))

        # Title
        title_html = """
        <div style="position: fixed; top: 10px; left: 50%; transform: translateX(-50%);
            z-index: 9999; font-size: 24px; font-weight: bold; font-family: Calibri; background-color: white;
            padding: 10px; border: 2px solid black; border-radius: 10px; text-align: center;">
            <span>Electrification TCO Parity Map</span>
        </div>
        """
        m.get_root().html.add_child(folium.Element(title_html))

        # Save new map, remove old
        unique_id = str(uuid.uuid4())
        output_filename = f"{unique_id}.html"
        map_path = os.path.join("static", "maps", output_filename)
        m.save(map_path)

        # Remove older .html
        for old_file in os.listdir("static/maps"):
            full_path = os.path.join("static", "maps", old_file)
            if old_file.endswith(".html") and old_file != output_filename:
                os.remove(full_path)

        link = url_for('serve_map', map_id=unique_id, _external=True)
        return f"Map generated! <a href='{link}' target='_blank'>View Map</a>"

@app.route("/map/<map_id>")
def serve_map(map_id):
    return send_from_directory("static/maps", f"{map_id}.html")

@app.route('/download_template')
def download_template():
    template_path = "location_pins_template.xlsx"
    if not os.path.isfile(template_path):
        return "Error: location_pins_template.xlsx not found.", 404
    return send_from_directory('.', 'location_pins_template.xlsx', as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True, port=5001)
