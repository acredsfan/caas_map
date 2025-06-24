# CaaS Map

This project provides a small Flask application for generating interactive maps from a spreadsheet of locations.

## Features

- Upload a CSV, XLS, or XLSX file containing location information and candidate counts.
- Automatically geocode locations and plot them on a map using Folium.
- Choose different pin styles for the map markers.
- Group US states by electrification parity probability (using the data in `input_csv_files/group_by_state.csv`).
- Save the generated map to `static/maps` and open it in the browser.
- Optionally download a PowerPoint slide that links to the generated map.

## Installation

1. Clone this repository.
2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

Run the Flask app:

```bash
python app.py
```

Open your browser to [http://localhost:5001](http://localhost:5001). The page allows you to:

1. Upload a `.csv`, `.xls`, or `.xlsx` file.
2. Choose a pin type for the markers.
3. Generate the map.

The uploaded file must contain the following columns:

- `Location Name`
- `ZIP/Postal Code`
- `Electrification Candidates`

The columns `Street Address`, `City`, and `State` are optional but can improve geocoding accuracy.

After the upload completes, a link to the generated map appears. Each map is saved as an HTML file in `static/maps` with a unique ID. You can share the link or open it directly in your browser.

To download a PowerPoint slide with a link to the map, replace `/map/ID` in the link with `/ppt/ID`.

A basic Excel template is available at `/download_template`.

## What You Can Do

- Visualize candidate counts for locations on an interactive map.
- Experiment with different pin styles to emphasize data points.
- Export a PowerPoint slide for presentations.


