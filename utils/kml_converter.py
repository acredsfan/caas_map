"""
KML to Location Pins Converter

This module converts KML files to location pins format compatible with the CaaS mapping application.
It extracts location data from KML placemarks and converts them to the required Excel/CSV format.
"""

import xml.etree.ElementTree as ET
import pandas as pd
import re
import os
from typing import List, Dict, Tuple, Optional


class KMLConverter:
    """Converts KML files to location pins format."""
    
    def __init__(self):
        self.namespaces = {
            'kml': 'http://www.opengis.net/kml/2.2'
        }
    
    def parse_kml(self, kml_file_path: str) -> List[Dict]:
        """
        Parse KML file and extract placemark data.
        
        Args:
            kml_file_path: Path to the KML file
            
        Returns:
            List of dictionaries containing placemark data
        """
        try:
            tree = ET.parse(kml_file_path)
            root = tree.getroot()
            
            placemarks = []
            
            # Find all folders and process them recursively
            document = root.find('.//kml:Document', self.namespaces)
            if document is not None:
                self._parse_element_recursive(document, placemarks, "Root")
            else:
                # Fallback to parsing from root
                self._parse_element_recursive(root, placemarks, "Root")
            
            return placemarks
            
        except ET.ParseError as e:
            raise ValueError(f"Invalid KML file: {e}")
        except FileNotFoundError:
            raise FileNotFoundError(f"KML file not found: {kml_file_path}")
    
    def _parse_element_recursive(self, element: ET.Element, placemarks: List[Dict], current_category: str):
        """Recursively parse KML elements and extract placemarks with category context."""
        
        # If this is a folder, update the category
        if element.tag.endswith('Folder'):
            name_elem = element.find('kml:name', self.namespaces)
            if name_elem is not None and name_elem.text:
                current_category = name_elem.text.strip()
        
        # Find all direct child placemarks
        for placemark in element.findall('kml:Placemark', self.namespaces):
            placemark_data = self._extract_placemark_data(placemark, current_category)
            if placemark_data:
                placemarks.append(placemark_data)
        
        # Recursively process child folders
        for folder in element.findall('kml:Folder', self.namespaces):
            self._parse_element_recursive(folder, placemarks, current_category)
    
    def _extract_placemark_data(self, placemark: ET.Element, category: str = 'Uncategorized') -> Optional[Dict]:
        """
        Extract data from a single placemark element.
        
        Args:
            placemark: KML Placemark element
            category: Category name from folder hierarchy
            
        Returns:
            Dictionary with placemark data or None if invalid
        """
        data = {}
        
        # Extract name
        name_elem = placemark.find('kml:name', self.namespaces)
        if name_elem is not None and name_elem.text:
            data['name'] = name_elem.text.strip()
        else:
            # Skip placemarks without names
            return None
        
        # Extract coordinates
        coordinates = self._extract_coordinates(placemark)
        if coordinates:
            data['latitude'] = str(coordinates[0])
            data['longitude'] = str(coordinates[1])
        
        # Extract address information
        address_info = self._extract_address_info(placemark)
        data.update(address_info)
        
        # Use provided category
        data['category'] = category
        
        return data
    
    def _extract_coordinates(self, placemark: ET.Element) -> Optional[Tuple[float, float]]:
        """Extract latitude and longitude from placemark coordinates."""
        coordinates_elem = placemark.find('.//kml:coordinates', self.namespaces)
        if coordinates_elem is not None and coordinates_elem.text:
            coords_text = coordinates_elem.text.strip()
            # KML coordinates format: longitude,latitude,elevation (elevation optional)
            coords = coords_text.split(',')
            if len(coords) >= 2:
                try:
                    longitude = float(coords[0])
                    latitude = float(coords[1])
                    return latitude, longitude
                except ValueError:
                    pass
        return None
    
    def _extract_address_info(self, placemark: ET.Element) -> Dict:
        """Extract address information from placemark."""
        address_info = {}
        
        # Try to get address from <address> element
        address_elem = placemark.find('kml:address', self.namespaces)
        if address_elem is not None and address_elem.text:
            address_info.update(self._parse_address_string(address_elem.text))
        
        # Try to get structured data from ExtendedData
        extended_data = placemark.find('kml:ExtendedData', self.namespaces)
        if extended_data is not None:
            extended_info = self._extract_extended_data(extended_data)
            address_info.update(extended_info)
        
        # Try to parse description for address info
        description_elem = placemark.find('kml:description', self.namespaces)
        if description_elem is not None and description_elem.text:
            description_info = self._parse_description(description_elem.text)
            # Only use description data if we don't have better structured data
            for key, value in description_info.items():
                if key not in address_info or not address_info[key]:
                    address_info[key] = value
        
        return address_info
    
    def _parse_address_string(self, address: str) -> Dict:
        """Parse a free-form address string into components."""
        address_info = {}
        
        # Try to extract ZIP code (5 digits, optionally followed by -4 digits)
        zip_match = re.search(r'\b(\d{5}(?:-\d{4})?)\b', address)
        if zip_match:
            address_info['zip'] = zip_match.group(1)
        
        # Try to extract state (2-letter abbreviation)
        state_match = re.search(r'\b([A-Z]{2})\b', address)
        if state_match:
            address_info['state'] = state_match.group(1)
        
        # The rest is more complex - for now, store the full address
        address_info['full_address'] = address.strip()
        
        return address_info
    
    def _extract_extended_data(self, extended_data: ET.Element) -> Dict:
        """Extract structured data from ExtendedData element."""
        data = {}
        
        for data_elem in extended_data.findall('kml:Data', self.namespaces):
            name = data_elem.get('name', '')
            value_elem = data_elem.find('kml:value', self.namespaces)
            if value_elem is not None and value_elem.text:
                value = value_elem.text.strip()
                
                # Map KML field names to our standard names
                field_mapping = {
                    'Street': 'street',
                    'City': 'city', 
                    'State': 'state',
                    'Zip': 'zip'
                }
                
                mapped_name = field_mapping.get(name, name.lower())
                data[mapped_name] = value
        
        return data
    
    def _parse_description(self, description: str) -> Dict:
        """Parse description text for address components."""
        data = {}
        
        # Remove HTML/CDATA
        description = re.sub(r'<[^>]+>', '', description)
        description = re.sub(r'<!\[CDATA\[|\]\]>', '', description)
        
        # Look for patterns like "Street: VALUE<br>City: VALUE"
        patterns = {
            'street': r'Street:\s*([^<\n]+)',
            'city': r'City:\s*([^<\n]+)', 
            'state': r'State:\s*([^<\n]+)',
            'zip': r'Zip:\s*([^<\n]+)'
        }
        
        for field, pattern in patterns.items():
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                data[field] = match.group(1).strip()
        
        return data
    
    def convert_to_location_pins(self, kml_file_path: str, default_candidates: int = 1) -> pd.DataFrame:
        """
        Convert KML file to location pins DataFrame format.
        
        Args:
            kml_file_path: Path to the KML file
            default_candidates: Default number of electrification candidates
            
        Returns:
            DataFrame in location pins format
        """
        placemarks = self.parse_kml(kml_file_path)
        
        if not placemarks:
            raise ValueError("No valid placemarks found in KML file")
        
        # Convert to location pins format
        location_pins = []
        
        for placemark in placemarks:
            location_pin = {
                'Location Name': placemark.get('name', ''),
                'Street Address': self._build_street_address(placemark),
                'City': placemark.get('city', ''),
                'State': placemark.get('state', ''),
                'ZIP/Postal Code': placemark.get('zip', ''),
                'Latitude': placemark.get('latitude', ''),
                'Longitude': placemark.get('longitude', ''),
                'Electrification Candidates': default_candidates,
                'Category Name': placemark.get('category', 'Uncategorized')
            }
            
            location_pins.append(location_pin)
        
        return pd.DataFrame(location_pins)
    
    def _build_street_address(self, placemark: Dict) -> str:
        """Build street address from available components."""
        if 'street' in placemark and placemark['street']:
            return placemark['street']
        elif 'full_address' in placemark:
            # Try to extract just the street part from full address
            full_addr = placemark['full_address']
            # Remove city, state, zip from the end
            if 'city' in placemark and placemark['city']:
                full_addr = full_addr.replace(placemark['city'], '').strip()
            if 'state' in placemark and placemark['state']:
                full_addr = full_addr.replace(placemark['state'], '').strip()
            if 'zip' in placemark and placemark['zip']:
                full_addr = full_addr.replace(placemark['zip'], '').strip()
            return full_addr.strip().rstrip(',')
        return ''
    
    def save_to_excel(self, df: pd.DataFrame, output_path: str):
        """Save DataFrame to Excel file."""
        df.to_excel(output_path, index=False)
    
    def save_to_csv(self, df: pd.DataFrame, output_path: str):
        """Save DataFrame to CSV file."""
        df.to_csv(output_path, index=False)


def convert_kml_to_location_pins(kml_file_path: str, output_path: str, 
                                default_candidates: int = 1, 
                                output_format: str = 'excel') -> str:
    """
    Convert KML file to location pins format and save to file.
    
    Args:
        kml_file_path: Path to input KML file
        output_path: Path for output file (without extension)
        default_candidates: Default number of electrification candidates
        output_format: 'excel' or 'csv'
        
    Returns:
        Path to the created file
    """
    converter = KMLConverter()
    df = converter.convert_to_location_pins(kml_file_path, default_candidates)
    
    if output_format.lower() == 'excel':
        full_output_path = f"{output_path}.xlsx"
        converter.save_to_excel(df, full_output_path)
    else:
        full_output_path = f"{output_path}.csv"
        converter.save_to_csv(df, full_output_path)
    
    return full_output_path


if __name__ == "__main__":
    # Example usage
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python kml_converter.py <kml_file> <output_file> [candidates] [format]")
        print("Example: python kml_converter.py network.kml output_locations 1 excel")
        sys.exit(1)
    
    kml_file = sys.argv[1]
    output_file = sys.argv[2]
    candidates = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    format_type = sys.argv[4] if len(sys.argv) > 4 else 'excel'
    
    try:
        result_file = convert_kml_to_location_pins(kml_file, output_file, candidates, format_type)
        print(f"Successfully converted KML to location pins: {result_file}")
    except Exception as e:
        print(f"Error converting KML: {e}")
        sys.exit(1)
