import os
import io
import uuid
from flask import Flask, request, send_from_directory, url_for
from pptx import Presentation
from pptx.util import Inches

import pandas as pd
import geopandas as gpd
import folium

# `unary_union` is deprecated in Shapely 2.1 in favor of `union_all`.  Fall
# back to `unary_union` for older versions so the code runs regardless of the
# installed Shapely release.
try:
    from shapely import union_all
except ImportError:  # pragma: no cover - Shapely < 2.1
    from shapely.ops import unary_union as union_all
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

app = Flask(__name__)
app.config['SERVER_NAME'] = 'caas-map-old.link-smart-home.com'
app.config['APPLICATION_ROOT'] = '/'
app.config['PREFERRED_URL_SCHEME'] = 'https'

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

# Create a unified geometry for all Group 1 states using union_all
group1_union_geom = union_all(
    us_states.loc[us_states["CaaS Group"] == "Group 1", "geometry"]
)
group1_union_gdf = gpd.GeoDataFrame(geometry=[group1_union_geom], crs=us_states.crs)

GROUP_COLORS = {"Group 1": "#0056b8", "Group 2": "#00a1e0", "Group 3": "#a1d0f3"}


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
        required_cols = {
            "Location Name",
            "ZIP/Postal Code",
            "Electrification Candidates",
        }
        if not required_cols.issubset(df.columns):
            return "Error: Missing required columns.", 400

        # Format ZIP codes
        def format_zip(value):
            """Return zero-padded 5 digit ZIP or empty string."""
            if pd.isna(value) or value == "":
                return ""
            try:
                # Handle values coming in as floats/strings
                return f"{int(float(value)):05d}"
            except (ValueError, TypeError):
                return ""

        df["ZIP/Postal Code"] = df["ZIP/Postal Code"].apply(format_zip)

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
        local_pin_url = selected_pin_data["url"]  # For non-numbered pins
        numbered_pin = selected_pin_data["numbered"]
        label_template = selected_pin_data["label"]

        # Build the Folium map
        m = folium.Map(
            location=[39.8283, -98.5795],
            zoom_start=5,
            tiles="https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png",
            attr="©OpenStreetMap contributors ©CartoDB",
            zoomSnap=0.01,
            zoomDelta=0.01,
        )

        # State layer
        folium.GeoJson(
            data=us_states.__geo_interface__,
            style_function=lambda feat: {
                "fillColor": GROUP_COLORS.get(feat["properties"]["CaaS Group"], "gray"),
                "color": "black",
                "weight": 1,
                "fillOpacity": 1.0,
                "className": (
                    "group1-state"
                    if feat["properties"].get("CaaS Group") == "Group 1"
                    else ""
                ),
            },
            tooltip=folium.features.GeoJsonTooltip(fields=["name"], aliases=["State:"]),
        ).add_to(m)

        # Overlay unified Group 1 geometry to apply a drop shadow only around the group's outer border
        folium.GeoJson(
            data=group1_union_gdf.__geo_interface__,
            style_function=lambda feat: {
                # Use a slightly transparent fill so the drop shadow filter has an
                # element to work with without obscuring the underlying states.
                "fillColor": "#ffffff",
                "color": "#ffffff",
                "weight": 1,
                "fillOpacity": 0.05,
                "opacity": 0.01,
                "className": "group1-union",
            },
        ).add_to(m)

        # Legend
        legend_html = """
        <div style="position: fixed; bottom: 50px; left: 50px; width:auto; height:auto;
        background-color: white; border:2px solid grey; z-index:9999; border-radius:5px;
        padding: 10px; white-space:nowrap; text-align: center;">
          <h4 style="margin-top:0; margin-bottom: 10px; font-weight: bold; font-family: Calibri">State Grouping Color Guide</h4>
          <div style="margin-bottom:5px; display: flex; align-items: center;">
            <i style="background:#0056b8;width:40px;height:20px;display:inline-block;margin-right:8px;"></i>
            Group 1 (Best Parity Probability)
          </div>
          <div style="margin-bottom:5px; display: flex; align-items: center;">
            <i style="background:#00a1e0;width:40px;height:20px;display:inline-block;margin-right:8px;"></i>
            Group 2 (Better Parity Probability)
          </div>
          <div style="display: flex; align-items: center;">
            <i style="background:#a1d0f3;width:40px;height:20px;display:inline-block;margin-right:8px;"></i>
            Group 3 (Good Parity Probability)
          </div>
        </div>
        """
        m.get_root().html.add_child(folium.Element(legend_html))

        # Geocoder
        geolocator = Nominatim(user_agent="grouped_map", timeout=10)
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

        # Geocode each row, fallback to state centroid if all else fails
        lat_list, lon_list = [], []
        for _, row in df.iterrows():
            addr_str = build_address_string(row)
            loc = geocode(addr_str)
            lat, lon = None, None
            if loc is None and row["Street Address"].strip():
                # fallback to just ZIP
                zip_loc = geocode(row["ZIP/Postal Code"] + ", USA")
                if zip_loc:
                    lat, lon = zip_loc.latitude, zip_loc.longitude
            elif loc:
                lat, lon = loc.latitude, loc.longitude

            # Fallback to state centroid if geocoding failed
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

        # Add markers and labels directly to the map in Python
        for _, row in df.iterrows():
            lat, lon = row["Latitude"], row["Longitude"]
            if pd.notnull(lat) and pd.notnull(lon):
                # Build label text (no border, no box-shadow, centered below pin, no background)
                label_html = f"""
                    <div class='custom-label-text'>{row['Location Name']}</div>
                """
                if numbered_pin:
                    svg_path = os.path.join('static', 'img', os.path.basename(local_pin_url))
                    injected_svg = load_and_inject_svg(svg_path, row['Electrification Candidates'])
                    icon = folium.DivIcon(
                        html=injected_svg,
                        icon_size=(65, 80),
                        icon_anchor=(32, 80),
                        class_name='custom-numbered-pin'
                    )
                else:
                    icon = folium.CustomIcon(
                        icon_image=local_pin_url,
                        icon_size=(50, 50),
                        icon_anchor=(25, 50)
                    )

                # Create marker and add to map
                marker = folium.Marker(
                    location=[lat, lon],
                    icon=icon,
                    tooltip=folium.Tooltip(
                        label_html,
                        permanent=True,
                        sticky=False,
                        direction='top',  # Place label above pin
                        offset=[0, -5],   # Move label closer to pin tip
                        class_name='always-visible-label'
                    )
                )
                marker.add_to(m)

        # Label styling
        label_style = """
        <style>
        /* Remove background, border, and box-shadow from always-visible-label tooltips */
        .leaflet-tooltip.always-visible-label {
            background: none !important;
            border: none !important;
            box-shadow: none !important;
            padding: 0 !important;
            margin: 0 !important;
        }
        .leaflet-tooltip.always-visible-label .leaflet-tooltip-tip,
        .leaflet-tooltip.always-visible-label:before,
        .leaflet-tooltip.always-visible-label:after {
            display: none !important;
        }
        /* Custom label text: rounded, no border, no box, centered, no background */
        .custom-label-text {
            background: none !important;
            border-radius: 8px;
            font-size: 14px;
            font-family: 'Calibri', sans-serif;
            font-weight: normal;
            color: #000;
            text-align: center;
            white-space: nowrap;
            padding: 2px 8px 2px 8px;
            margin: 0 auto;
            border: none;
            box-shadow: none;
            display: inline-block;
        }
        .custom-numbered-pin {
            background: none;
            border: none;
            filter: drop-shadow(3px 3px 5px rgba(0,0,0,0.4));
        }
        .group1-state {
            filter: brightness(1.05);
        }
        .group1-union {
            pointer-events: none;
            stroke: transparent;
            fill: #ffffff;
            fill-opacity: 0.05;
            filter:
                drop-shadow(-2px -2px 3px rgba(255, 255, 255, 0.8))
                drop-shadow(6px 6px 8px rgba(0, 0, 0, 0.7));
        }
        </style>
        """
        m.get_root().add_child(folium.Element(label_style))

        # Title
        title_html = """
        <div style="position: fixed; top: 10px; left: 50%; transform: translateX(-50%);
            z-index: 9999; font-size: 24px; font-weight: bold; font-family: Calibri; background-color: white;
            padding: 10px; border: 2px solid black; border-radius: 10px; text-align: center;">
            <span>Electrification TCO Parity Map</span>
        </div>
        """
        m.get_root().add_child(folium.Element(title_html))

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

        link = url_for("serve_map", map_id=unique_id, _external=True)
        return f"Map generated! <a href='{link}' target='_blank'>View Map</a>"


@app.route("/map/<map_id>")
def serve_map(map_id):
    return send_from_directory("static/maps", f"{map_id}.html")


@app.route("/ppt/<map_id>")
def download_ppt(map_id):
    html_path = os.path.join("static", "maps", f"{map_id}.html")
    if not os.path.isfile(html_path):
        return "Error: Map not found.", 404

    link = url_for("serve_map", map_id=map_id, _external=True)
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    title = slide.shapes.title
    if title:
        title.text = "Interactive Map"

    try:
        # Attempt to embed the HTML map directly as an OLE object so it can be
        # interacted with when the slide is presented.  This requires PowerPoint
        # on Windows and may not function on other platforms.
        slide.shapes.add_ole_object(
            html_path,
            prog_id="htmlfile",
            left=Inches(0.5),
            top=Inches(1.5),
            width=Inches(9),
            height=Inches(5),
        )
    except Exception:
        # Fallback: just provide a hyperlink if embedding fails
        box = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(8), Inches(1))
        tf = box.text_frame
        p = tf.paragraphs[0]
        run = p.add_run()
        run.text = "Open Map"
        run.hyperlink.address = link

    ppt_filename = f"{map_id}.pptx"
    ppt_path = os.path.join("static", "maps", ppt_filename)
    prs.save(ppt_path)
    return send_from_directory("static/maps", ppt_filename, as_attachment=True)


@app.route("/download_template")
def download_template():
    template_path = "location_pins_template.xlsx"
    if not os.path.isfile(template_path):
        return "Error: location_pins_template.xlsx not found.", 404
    return send_from_directory(".", "location_pins_template.xlsx", as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True, port=5050)
