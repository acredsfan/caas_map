#!/usr/bin/env python3
"""
Debug script for KML namespace and structure issues
"""

import xml.etree.ElementTree as ET

def debug_kml_structure():
    """Debug the KML file structure and namespaces."""
    print("Debugging KML structure...")
    
    try:
        tree = ET.parse('Distribution Network.kml')
        root = tree.getroot()
        
        print(f"Root tag: {root.tag}")
        print(f"Root attributes: {root.attrib}")
        
        # Check all immediate children
        print("\nImmediate children of root:")
        for child in root:
            print(f"  - {child.tag} (attrs: {child.attrib})")
        
        # Look for Document
        document = root.find('.//{http://www.opengis.net/kml/2.2}Document')
        if document is None:
            document = root.find('.//Document')
        
        if document is not None:
            print(f"\nFound Document: {document.tag}")
            print("Document children:")
            for child in document:
                print(f"  - {child.tag}")
                if child.tag.endswith('Folder'):
                    name_elem = child.find('.//{http://www.opengis.net/kml/2.2}name')
                    if name_elem is None:
                        name_elem = child.find('.//name')
                    if name_elem is not None:
                        print(f"    Folder name: {name_elem.text}")
        
        # Try to find any placemark
        namespaces = {'kml': 'http://www.opengis.net/kml/2.2'}
        placemarks_ns = root.findall('.//kml:Placemark', namespaces)
        placemarks_no_ns = root.findall('.//Placemark')
        
        print(f"\nPlacemarks found with namespace: {len(placemarks_ns)}")
        print(f"Placemarks found without namespace: {len(placemarks_no_ns)}")
        
        # Show first placemark structure
        placemark = None
        if placemarks_ns:
            placemark = placemarks_ns[0]
        elif placemarks_no_ns:
            placemark = placemarks_no_ns[0]
        
        if placemark is not None:
            print(f"\nFirst placemark structure:")
            print(f"Tag: {placemark.tag}")
            for child in placemark:
                print(f"  - {child.tag}: {child.text if child.text and len(child.text) < 50 else 'Content too long'}")
        
        return True
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    debug_kml_structure()
