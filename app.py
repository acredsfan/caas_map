import os
import io
import uuid
from flask import Flask, request, send_from_directory, url_for, render_template_string, send_file
from pptx import Presentation
from pptx.util import Inches

import pandas as pd
import geopandas as gpd
import folium
# --- CHANGE: Import MarkerCluster ---
from folium.plugins import MarkerCluster

# `unary_union` is deprecated in Shapely 2.1 in favor of `union_all`.  Fall
# back to `unary_union` for older versions so the code runs regardless of the
# installed Shapely release.
try:
    from shapely import union_all
except ImportError:  # pragma: no cover - Shapely < 2.1
    from shapely.ops import unary_union as union_all
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

# --- FIX: Define a base directory to make all file paths absolute ---
basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config['SERVER_NAME'] = 'caas-map-old.link-smart-home.com'
app.config['APPLICATION_ROOT'] = '/'
app.config['PREFERRED_URL_SCHEME'] = 'https'
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'uploads')

# Directories
os.makedirs(os.path.join(basedir, "static", "maps"), exist_ok=True)
os.makedirs(os.path.join(basedir, "static", "img"), exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Preload groups & shapefile
state_groups = pd.read_csv(os.path.join(basedir, "input_csv_files", "group_by_state.csv"))
us_states = gpd.read_file(
    os.path.join(basedir, "us_state_boundary_shapefiles", "ne_10m_admin_1_states_provinces_lakes.shp")
)
us_states = us_states[us_states["admin"] == "United States of America"]
us_states["StateAbbr"] = us_states["iso_3166_2"].str.split("-").str[-1]
us_states = us_states.merge(
    state_groups, left_on="StateAbbr", right_on="State", how="left"
)

GROUP_COLORS = {"Group 1": "#0056b8", "Group 2": "#00a1e0", "Group 3": "#a1d0f3"}

# --- NEW: Helper function to convert hex to rgba for table row coloring ---
def hex_to_rgba(hex_color, alpha=0.2):
    if pd.isna(hex_color):
        return 'rgba(255, 255, 255, 0)' # Return transparent if color is missing
    hex_color = hex_color.lstrip('#')
    r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    return f'rgba({r}, {g}, {b}, {alpha})'

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
with app.app_context():
    PIN_TYPES = {
        "primary_dark_blue_sphere": {
            "url": url_for("static", filename="img/sphere_pin_primary_dark_blue.svg"),
            "numbered": False,
            "label": "Location Name - Candidates",
        },
        "primary_dark_blue_number": {
            "url": url_for("static", filename="img/number_pin_primary_dark_blue.svg"),
            "numbered": True,
            "label": "Location Name",
        },
        "primary_light_blue_sphere": {
            "url": url_for("static", filename="img/sphere_pin_primary_light_blue.svg"),
            "numbered": False,
            "label": "Location Name - Candidates",
        },
        "primary_light_blue_number": {
            "url": url_for("static", filename="img/number_pin_primary_light_blue.svg"),
            "numbered": True,
            "label": "Location Name",
        },
        "green_sphere": {
            "url": url_for("static", filename="img/sphere_pin_green.svg"),
            "numbered": False,
            "label": "Location Name - Candidates",
        },
        "green_number": {
            "url": url_for("static", filename="img/number_pin_green.svg"),
            "numbered": True,
            "label": "Location Name",
        },
        "secondary_dark_blue_sphere": {
            "url": url_for("static", filename="img/sphere_pin_secondary_dark_blue.svg"),
            "numbered": False,
            "label": "Location Name - Candidates",
        },
        "secondary_dark_blue_number": {
            "url": url_for("static", filename="img/number_pin_secondary_dark_blue.svg"),
            "numbered": True,
            "label": "Location Name",
        },
        "teal_sphere": {
            "url": url_for("static", filename="img/sphere_pin_teal.svg"),
            "numbered": False,
            "label": "Location Name - Candidates",
        },
        "teal_number": {
            "url": url_for("static", filename="img/number_pin_teal.svg"),
            "numbered": True,
            "label": "Location Name",
        },
    }

# Nicer form template with updated styling
UPLOAD_FORM_TEMPLATE = """
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
      .options {
        margin-top: 20px;
        margin-bottom: 20px;
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

      <div class="options">
        <label>
          <input type="checkbox" name="cluster_pins" value="true" checked> Cluster Pins
        </label>
      </div>

      <button type="submit">Upload & Generate Map</button>
      <div class="footer-links">
        <a href="/download_template" download="location_pins_template.xlsx">Download Excel Template</a>
      </div>
    </form>
</div>

<script>
  const pinTypes = {{ pin_types|tojson }};
  
  function updatePreview(index) {
      const selectEl = document.getElementById('select_' + index);
      const previewEl = document.getElementById('preview_' + index);
      const selectedPinKey = selectEl.value;
      if (pinData[selectedPinKey]) {
          previewEl.src = pinData[selectedPinKey].url;
      }
  }

  document.addEventListener('DOMContentLoaded', function() {
      const selects = document.querySelectorAll('select[id^="select_"]');
      selects.forEach((select, i) => {
          updatePreview(i + 1);
      });
  });
</script>
</body>
</html>
"""

PIN_ASSIGNMENT_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Map Uploader - Step 2</title>
    <style>
      body { font-family: Calibri, sans-serif; background: #f4f7fa; margin: 0; padding: 0; }
      .container { max-width: 800px; margin: 40px auto; background: #fff; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.15); padding: 20px 30px; }
      h1 { margin-top: 0; color: #333; }
      label { font-weight: bold; }
      button { background: #0056b8; color: #fff; border: none; border-radius: 4px; padding: 10px 16px; cursor: pointer; font-size: 14px; }
      button:hover { background: #004494; }
      .category-row { display: flex; align-items: center; margin-bottom: 15px; }
      .category-name { width: 250px; font-weight: bold; }
      select { padding: 5px; border-radius: 4px; }
      .pin-preview { width: 40px; height: 40px; margin-left: 15px; object-fit: contain; }
    </style>
</head>
<body>
<div class="container">
    <h1>Step 2: Assign a Pin to Each Category</h1>
    <p>For each category found in your file, select a pin style from the dropdown.</p>
    <form action="/generate_map" method="POST">
      <input type="hidden" name="filename" value="{{ filename }}">
      <input type="hidden" name="cluster_pins" value="{{ cluster_pins }}">
      {% for category in categories %}
      <div class="category-row">
        <div class="category-name">{{ category }}</div>
        <select name="pin_map_{{ category }}" id="select_{{ loop.index }}" onchange="updatePreview({{ loop.index }})" required>
          {% for pin_key, pin_data in pin_types.items() %}
          <option value="{{ pin_key }}">{{ pin_key.replace('_', ' ')|title }}</option>
          {% endfor %}
        </select>
        <img id="preview_{{ loop.index }}" src="" class="pin-preview">
      </div>
      {% endfor %}
      <br>
      <button type="submit">Generate Map</button>
    </form>
</div>
<script>
    const pinData = {{ pin_types|tojson }};
    
    function updatePreview(index) {
        const selectEl = document.getElementById('select_' + index);
        const previewEl = document.getElementById('preview_' + index);
        const selectedPinKey = selectEl.value;
        if (pinData[selectedPinKey]) {
            previewEl.src = pinData[selectedPinKey].url;
        }
    }

    document.addEventListener('DOMContentLoaded', function() {
        const selects = document.querySelectorAll('select[id^="select_"]');
        selects.forEach((select, i) => {
            updatePreview(i + 1);
        });
    });
</script>
</body>
</html>
"""


@app.route("/", methods=["GET"])
def upload_form():
    return render_template_string(UPLOAD_FORM_TEMPLATE)

@app.route("/assign_pins", methods=["POST"])
def assign_pins():
    try:
        uploaded_file = request.files.get("file")
        if not uploaded_file or not uploaded_file.filename:
            return "Error: No file selected.", 400
        
        # Use a unique filename to prevent conflicts
        filename = f"{uuid.uuid4()}_{uploaded_file.filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        uploaded_file.save(filepath)

        try:
            if filename.lower().endswith((".xls", ".xlsx")):
                df = pd.read_excel(filepath)
            else:
                df = pd.read_csv(filepath)
        except Exception as e:
            return f"Error reading file: {e}", 400

        required_cols = {"Location Name", "ZIP/Postal Code", "Electrification Candidates", "Category Name"}
        if not required_cols.issubset(df.columns):
            return f"Error: Missing required columns. Your file must contain: {', '.join(required_cols)}", 400
        
        df['Category Name'] = df['Category Name'].astype(str).fillna('Uncategorized')
        categories = sorted(df['Category Name'].unique())

        return render_template_string(
            PIN_ASSIGNMENT_TEMPLATE, 
            filename=filename, 
            categories=categories, 
            pin_types=PIN_TYPES,
            cluster_pins=str(request.form.get("cluster_pins") == "true").lower()
        )
    except Exception as e:
        app.logger.error(f"An unhandled exception occurred in /assign_pins: {e}", exc_info=True)
        return f"An internal server error occurred. Please check the server logs. Error: {e}", 500

@app.route("/generate_map", methods=["POST"])
def generate_map():
    filename = request.form.get("filename")
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(filepath):
        return "Error: Uploaded file not found. Please try again.", 404

    try:
        if filename.lower().endswith((".xls", ".xlsx")):
            df = pd.read_excel(filepath)
        else:
            df = pd.read_csv(filepath)
    except Exception as e:
        return f"Error reading file: {e}", 400

    df['Category Name'] = df['Category Name'].astype(str).fillna('Uncategorized')
    
    pin_map = {}
    for key, value in request.form.items():
        if key.startswith("pin_map_"):
            category_name = key[len("pin_map_"):]
            pin_map[category_name] = value

    cluster_pins = request.form.get("cluster_pins") == 'true'
    
    m = folium.Map(location=[39.8283, -98.5795], zoom_start=5, tiles="https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png", attr="©OpenStreetMap contributors ©CartoDB", zoomSnap=0.01, zoomDelta=0.01)
    
    folium.GeoJson(
        data=us_states.__geo_interface__,
        style_function=lambda feat: {
            "fillColor": GROUP_COLORS.get(feat["properties"]["CaaS Group"], "gray"),
            "color": "black",
            "weight": 1,
            "fillOpacity": 1.0,
            "className": ("group1-state" if feat["properties"].get("CaaS Group") == "Group 1" else "")
        },
        tooltip=folium.features.GeoJsonTooltip(fields=["name"], aliases=["State:"])
    ).add_to(m)

    geolocator = Nominatim(user_agent="grouped_map", timeout=10)
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1, max_retries=3)

    lat_list, lon_list = [], []
    for _, row in df.iterrows():
        address_parts = []
        if pd.notna(row.get("Street Address")) and str(row["Street Address"]).strip():
            address_parts.append(str(row["Street Address"]).strip())
        if pd.notna(row.get("City")) and str(row["City"]).strip():
            address_parts.append(str(row["City"]).strip())
        if pd.notna(row.get("State")) and str(row["State"]).strip():
            address_parts.append(str(row["State"]).strip())
        
        if address_parts:
            addr_str = ", ".join(address_parts) + ", USA"
        else:
            addr_str = str(row["ZIP/Postal Code"]) + ", USA"

        loc = geocode(addr_str)
        lat, lon = (None, None)
        if loc:
            lat, lon = loc.latitude, loc.longitude
        else:
            state_abbr = row.get("State")
            if state_abbr and state_abbr in us_states["StateAbbr"].values:
                state_geom = us_states[us_states["StateAbbr"] == state_abbr].geometry.iloc[0]
                centroid = state_geom.centroid
                lat, lon = centroid.y, centroid.x
        
        lat_list.append(lat)
        lon_list.append(lon)

    df['Latitude'] = lat_list
    df['Longitude'] = lon_list
    
    df = df.merge(us_states[['StateAbbr', 'CaaS Group']], left_on='State', right_on='StateAbbr', how='left')

    if cluster_pins:
        # Use your color scheme for clusters: dark blue, light blue, teal, green
        # We'll use the following mapping:
        # >=100: dark blue (#0056b8), >=50: light blue (#00a1e0), >=10: teal (#00bfae), else: green (#6bc04b)
        icon_create_function = """
        function(cluster) {
            var childCount = cluster.getChildCount();
            var color = '#6bc04b'; // green default
            if (childCount >= 100) {
                color = '#0056b8'; // dark blue
            } else if (childCount >= 50) {
                color = '#00a1e0'; // light blue
            } else if (childCount >= 10) {
                color = '#00bfae'; // teal
            }
            return new L.DivIcon({
                html: '<div style="background:' + color + '"><span>' + childCount + '</span></div>',
                className: 'marker-cluster',
                iconSize: new L.Point(40, 40)
            });
        }
        """
        marker_layer = MarkerCluster(icon_create_function=icon_create_function).add_to(m)
    else:
        marker_layer = m
    
    legend_items = {}

    for _, row in df.iterrows():
        lat, lon = row["Latitude"], row["Longitude"]
        if pd.notnull(lat) and pd.notnull(lon):
            category = row['Category Name']
            pin_type_key = pin_map.get(category, list(PIN_TYPES.keys())[0])
            pin_data = PIN_TYPES[pin_type_key]
            
            if category not in legend_items:
                legend_items[category] = pin_data['url']

            if pin_data['numbered']:
                svg_path = os.path.join(basedir, 'static', 'img', os.path.basename(pin_data['url']))
                injected_svg = load_and_inject_svg(svg_path, row['Electrification Candidates'])
                html = f'<div class="div-icon-container"><div class="pin-image-wrapper">{injected_svg}</div><div class="custom-label-text">{row["Location Name"]}</div></div>'
                icon = folium.DivIcon(html=html, icon_size=(150, 110), icon_anchor=(32.5, 80))
            else:
                html = f'<div class="div-icon-container"><div class="pin-image-wrapper"><img src="{pin_data["url"]}" class="sphere-pin"></div><div class="custom-label-text">{row["Location Name"]}</div></div>'
                icon = folium.DivIcon(html=html, icon_size=(150, 80), icon_anchor=(25, 50))
            
            folium.Marker(location=[lat, lon], icon=icon).add_to(marker_layer)
            
    if cluster_pins:
        table_rows = ""
        for _, row in df.iterrows():
            n = row.get('Electrification Candidates', 1)
            try:
                n = int(n)
            except Exception:
                n = 1
            if n >= 100:
                color = '#0056b8'
            elif n >= 50:
                color = '#00a1e0'
            elif n >= 10:
                color = '#00bfae'
            elif n >= 2:
                color = '#6bc04b'
            else:
                color = None
            if color:
                rgba_color = hex_to_rgba(color, alpha=0.25)
                row_style = f"background-color: {rgba_color};"
            else:
                row_style = ""
            table_rows += f"<tr style='{row_style}'><td>{row['Location Name']}</td><td>{row['Electrification Candidates']}</td></tr>"
        table_html = f"""
        <div style=\"position: fixed; top: 80px; right: 10px; width: 300px; max-height: 80vh;\"
        style=\"background-color: white; border:1px solid #ccc; z-index:9998; border-radius:5px;\"
        style=\"padding: 10px; font-family: Calibri; overflow-y: auto;\">
          <h4 style=\"margin-top:0; margin-bottom: 10px; font-weight: bold;\">Locations</h4>
          <table style=\"width: 100%; border-collapse: collapse;\">
            <thead style=\"font-weight: bold;\">
              <tr>
                <td style=\"padding: 4px; border-bottom: 1px solid #ddd;\">Location</td>
                <td style=\"padding: 4px; border-bottom: 1px solid #ddd;\">Candidates</td>
              </tr>
            </thead>
            <tbody>{table_rows}</tbody>
          </table>
        </div>
        """
        m.get_root().add_child(folium.Element(table_html))

    # --- State Group Legend (as in attached image) ---
    state_legend_html = """
    <div style='position: fixed; bottom: 20px; left: 20px; background: #fff; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.15); border: 2px solid #bbb; padding: 12px 18px; z-index: 9999; font-family: Calibri;'>
      <div style='font-weight: bold; margin-bottom: 8px;'>State Grouping Color Guide</div>
      <div style='display: flex; align-items: center; margin-bottom: 6px;'>
        <span style='display:inline-block;width:24px;height:16px;background:#0056b8;border-radius:4px;margin-right:10px;'></span>
        Group 1 (Best Parity Probability)
      </div>
      <div style='display: flex; align-items: center; margin-bottom: 6px;'>
        <span style='display:inline-block;width:24px;height:16px;background:#00a1e0;border-radius:4px;margin-right:10px;'></span>
        Group 2 (Better Parity Probability)
      </div>
      <div style='display: flex; align-items: center;'>
        <span style='display:inline-block;width:24px;height:16px;background:#a1d0f3;border-radius:4px;margin-right:10px;'></span>
        Group 3 (Good Parity Probability)
      </div>
    </div>
    """
    m.get_root().add_child(folium.Element(state_legend_html))

    # --- Pin/Category Legend (centered, single line if multiple categories) ---
    if legend_items:
        if len(legend_items) == 1:
            # Only one category
            category, pin_url = next(iter(legend_items.items()))
            pin_legend_html = f"""
            <div style='position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: #fff; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.15); border: 2px solid #bbb; padding: 10px 18px; z-index: 9999; font-family: Calibri; display: flex; align-items: center;'>
                <img src='{pin_url}' style='width:22px;height:22px;margin-right:8px;'>
                <span>{category}</span>
            </div>
            """
        else:
            # Multiple categories: show all in a single line
            pin_legend_html = "<div style='position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: #fff; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.15); border: 2px solid #bbb; padding: 10px 18px; z-index: 9999; font-family: Calibri; display: flex; align-items: center;'>"
            for category, pin_url in sorted(legend_items.items()):
                pin_legend_html += f"<span style='display: flex; align-items: center; margin-right: 18px;'><img src='{pin_url}' style='width:22px;height:22px;margin-right:6px;'><span>{category}</span></span>"
            pin_legend_html += "</div>"
        m.get_root().add_child(folium.Element(pin_legend_html))

    styles = """
    <style>
    .div-icon-container { position: relative; text-align: center; }
    .pin-image-wrapper { position: relative; display: inline-block; }
    .custom-label-text { background: white !important; border: 1px solid #ccc !important; border-radius: 8px; font-size: 14px; font-family: 'Calibri', sans-serif; font-weight: bold; color: #000; text-align: center; white-space: nowrap; padding: 4px 10px; margin-top: 5px; box-shadow: 2px 2px 5px rgba(0,0,0,0.2); display: inline-block; }
    .sphere-pin { width: 50px; height: 50px; }
    .group1-state { filter: drop-shadow(5px 5px 4px rgba(0, 0, 0, 0.5)); -webkit-filter: drop-shadow(5px 5px 4px rgba(0, 0, 0, 0.5)); }
    .marker-cluster { color: #fff; border-radius: 50%; text-align: center; font-weight: bold; font-family: Calibri, sans-serif; background: #6bc04b; border: 2px solid #fff; }
    .marker-cluster div { width: 40px; height: 40px; border-radius: 50%; line-height: 40px; font-size: 18px; display: flex; align-items: center; justify-content: center; }
    </style>
    """
    m.get_root().add_child(folium.Element(styles))

    title_html = """
    <div style="position: fixed; top: 10px; left: 50%; transform: translateX(-50%);
        z-index: 9999; font-size: 24px; font-weight: bold; font-family: Calibri; background-color: white;
        padding: 10px; border: 2px solid black; border-radius: 10px; text-align: center;">
        <span>EV/ICE Total Cost of Ownership (TCO) Parity Probability Map</span>
    </div>
    """
    m.get_root().add_child(folium.Element(title_html))

    unique_id = str(uuid.uuid4())
    output_filename = f"{unique_id}.html"
    map_path = os.path.join(basedir, "static", "maps", output_filename)
    m.save(map_path)

    os.remove(filepath)

    link = url_for("serve_map", map_id=unique_id, _external=True)
    return f"Map generated! <a href='{link}' target='_blank'>View Map</a>"


@app.route("/map/<map_id>")
def serve_map(map_id):
    return send_from_directory(os.path.join(basedir, "static", "maps"), f"{map_id}.html")


@app.route("/ppt/<map_id>")
def download_ppt(map_id):
    maps_dir = os.path.join(basedir, "static", "maps")
    html_path = os.path.join(maps_dir, f"{map_id}.html")
    if not os.path.isfile(html_path):
        return "Error: Map not found.", 404

    link = url_for("serve_map", map_id=map_id, _external=True)
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    title = slide.shapes.title
    if title:
        title.text = "Interactive Map"

    try:
        slide.shapes.add_ole_object(
            html_path,
            prog_id="htmlfile",
            left=Inches(0.5),
            top=Inches(1.5),
            width=Inches(9),
            height=Inches(5),
        )
    except Exception:
        box = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(8), Inches(1))
        tf = box.text_frame
        p = tf.paragraphs[0]
        run = p.add_run()
        run.text = "Open Map"
        run.hyperlink.address = link

    ppt_filename = f"{map_id}.pptx"
    ppt_path = os.path.join(maps_dir, ppt_filename)
    prs.save(ppt_path)
    return send_from_directory(maps_dir, ppt_filename, as_attachment=True)


@app.route("/download_template")
def download_template():
    df = pd.DataFrame({
        "Location Name": ["Example A", "Example B"],
        "Street Address": ["123 Main St", ""],
        "City": ["Anytown", ""],
        "State": ["CA", "TX"],
        "ZIP/Postal Code": ["12345", "67890"],
        "Electrification Candidates": [10, 5],
        "Category Name": ["Retail", "Warehouse"],
    })
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='locations')
    output.seek(0)
    return send_file(output, download_name="location_pins_template.xlsx", as_attachment=True)


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5050)
