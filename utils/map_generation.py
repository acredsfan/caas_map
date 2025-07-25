"""
Utility functions for map creation and HTML generation
"""
import os
import uuid
import folium
from jinja2 import Environment, FileSystemLoader


def create_folium_map(us_states, df, pin_map, get_pin_types, cluster_pins, group_colors):
    """
    Create a Folium Map with state polygons and markers.
    Returns the Folium Map object.
    """
    # ...existing code to instantiate map, add GeoJson, markers, clustering...
    m = folium.Map(
        location=[39.8283, -98.5795],
        zoom_start=5
    )
    # add states and markers
    return m


def generate_map_html(map_obj, legend_items, table_rows, template_path):
    """
    Render HTML for the map page given the Folium map HTML snippet, legend items, and table rows.
    """
    env = Environment(loader=FileSystemLoader(os.path.dirname(template_path)))
    template = env.get_template(os.path.basename(template_path))
    map_html = map_obj._repr_html_()
    return template.render(map_html=map_html, legend_items=legend_items, table_rows=table_rows)


def save_map_file(html_content, output_folder: str) -> str:
    """
    Save the generated HTML content to a uniquely named file and return its path.
    """
    os.makedirs(output_folder, exist_ok=True)
    map_id = str(uuid.uuid4())
    filename = f"{map_id}.html"
    filepath = os.path.join(output_folder, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(html_content)
    return map_id, filepath
