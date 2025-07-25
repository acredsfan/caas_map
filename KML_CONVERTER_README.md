# KML to Location Pins Converter

This module adds the ability to convert KML (Keyhole Markup Language) files into the location pins format used by the CaaS mapping application. It supports both address-based and coordinate-based location data.

## Features

- **KML Parsing**: Extract location data from KML files with proper folder hierarchy support
- **Coordinate Support**: Handle both lat/lon coordinates and address-based locations  
- **Enhanced Template**: Generate Excel templates with validation and instructions
- **CLI Interface**: Command-line tool for easy conversion
- **Backwards Compatibility**: Works with existing location pins format

## Files Added

- `utils/kml_converter.py` - Main KML conversion functionality
- `utils/template_generator.py` - Enhanced Excel template generator
- `utils/enhanced_validation.py` - Enhanced validation for coordinate data
- `kml_to_pins.py` - Command-line interface
- `test_kml_converter.py` - Test script

## Usage

### Command Line Interface

#### Convert KML to Location Pins

```bash
# Convert to Excel format (default)
python kml_to_pins.py convert "Distribution Network.kml" "output_locations"

# Convert to CSV format with custom electrification candidates
python kml_to_pins.py convert "network.kml" "locations" --candidates 5 --format csv

# Force overwrite existing files
python kml_to_pins.py convert "network.kml" "locations" --force
```

#### Create Enhanced Template

```bash
# Create enhanced template with instructions
python kml_to_pins.py template

# Specify custom output file
python kml_to_pins.py template --output "my_template.xlsx"
```

### Python API

```python
from utils.kml_converter import convert_kml_to_location_pins, KMLConverter
from utils.template_generator import create_enhanced_template

# Simple conversion
output_file = convert_kml_to_location_pins(
    'network.kml', 
    'output_locations', 
    default_candidates=3, 
    output_format='excel'
)

# Advanced usage with custom processing
converter = KMLConverter()
placemarks = converter.parse_kml('network.kml')
df = converter.convert_to_location_pins('network.kml', default_candidates=2)

# Create enhanced template
template_path = create_enhanced_template('enhanced_template.xlsx')
```

## Enhanced Location Pins Format

The enhanced format supports both traditional address-based locations and coordinate-based locations:

### Required Columns
- `Location Name` - Descriptive name for the location
- `Electrification Candidates` - Number of vehicles/candidates (positive integer)
- `Category Name` - Category for grouping locations

### Location Data (use one or both approaches)

#### Option 1: Address-based
- `Street Address` - Physical street address (optional)
- `City` - City name (optional)  
- `State` - State abbreviation (optional)
- `ZIP/Postal Code` - ZIP or postal code (helpful for geocoding)

#### Option 2: Coordinate-based
- `Latitude` - Decimal degrees (e.g., 39.7392)
- `Longitude` - Decimal degrees (e.g., -104.9903)

### Validation Rules

1. **Location Data**: Each row must have either:
   - Latitude AND Longitude coordinates, OR
   - ZIP/Postal Code, OR
   - City AND State, OR  
   - Street Address

2. **Coordinates**: If provided, must be valid decimal degrees:
   - Latitude: -90 to 90
   - Longitude: -180 to 180

3. **Electrification Candidates**: Must be positive integers

## KML Support

The converter supports standard KML files with:

- **Placemarks**: Individual location points
- **Folders**: Hierarchical organization (mapped to categories)
- **Coordinates**: Point geometries with lat/lon/elevation
- **Address Data**: Extended data fields and address elements
- **Names**: Placemark names become location names

### Example KML Structure

```xml
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Folder>
      <name>Distribution Centers</name>
      <Placemark>
        <name>Main DC</name>
        <address>123 Industrial Blvd, Denver, CO 80202</address>
        <Point>
          <coordinates>-104.9903,39.7392,0</coordinates>
        </Point>
      </Placemark>
    </Folder>
  </Document>
</kml>
```

## Integration with Existing App

The enhanced validation can be integrated into the existing application:

```python
from utils.enhanced_validation import validate_enhanced_location_pins

# In your upload handler
is_valid, errors = validate_enhanced_location_pins(df)
if not is_valid:
    return f"Validation errors: {'; '.join(errors)}", 400
```

### Backwards Compatibility

The enhanced format is backwards compatible with existing location pins files. The validation will accept:

- Original format with required columns: `Location Name`, `ZIP/Postal Code`, `Electrification Candidates`, `Category Name`
- Enhanced format with coordinate support
- Mixed formats with some rows having coordinates and others having addresses

## Geocoding Priority

When processing location data, the system uses this priority order:

1. **Existing Coordinates** - If Latitude/Longitude are provided and valid
2. **Address Geocoding** - Geocode using street address, city, state, ZIP
3. **State Centroid Fallback** - Use state center point if geocoding fails

## Testing

Run the test script to verify functionality:

```bash
python test_kml_converter.py
```

This will:
- Parse the Distribution Network.kml file
- Show statistics about locations found
- Test conversion to DataFrame format
- Create a test output file

## Dependencies

The KML converter requires these packages (already in requirements.txt):
- `pandas` - Data manipulation
- `openpyxl` - Excel file handling
- `xml.etree.ElementTree` - XML parsing (built-in)

## Error Handling

The converter includes comprehensive error handling for:
- Invalid KML files
- Missing required data
- Invalid coordinates
- File I/O errors
- Parsing errors

Common issues and solutions:
- **No placemarks found**: Check KML namespace and structure
- **Invalid coordinates**: Ensure lat/lon are in decimal degrees
- **Geocoding failures**: Provide more complete address information
- **Template errors**: Ensure openpyxl is installed for Excel generation
