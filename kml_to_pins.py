#!/usr/bin/env python3
"""
KML to Location Pins Converter CLI

Command-line interface for converting KML files to location pins format.
"""

import argparse
import sys
import os
from pathlib import Path

# Add the utils directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'utils'))

try:
    from utils.kml_converter import convert_kml_to_location_pins
    from utils.template_generator import create_enhanced_template
except ImportError:
    from kml_converter import convert_kml_to_location_pins
    from template_generator import create_enhanced_template


def main():
    parser = argparse.ArgumentParser(
        description="Convert KML files to location pins format for CaaS mapping application",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert KML to Excel format
  python kml_to_pins.py convert network.kml output_locations

  # Convert KML to CSV format with custom candidates count
  python kml_to_pins.py convert network.kml output_locations --candidates 5 --format csv

  # Create enhanced template
  python kml_to_pins.py template --output enhanced_template.xlsx

  # Get help for convert command
  python kml_to_pins.py convert --help
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Convert command
    convert_parser = subparsers.add_parser(
        'convert', 
        help='Convert KML file to location pins format'
    )
    convert_parser.add_argument(
        'kml_file', 
        help='Path to the input KML file'
    )
    convert_parser.add_argument(
        'output_file', 
        help='Output file path (without extension)'
    )
    convert_parser.add_argument(
        '--candidates', 
        type=int, 
        default=1,
        help='Default number of electrification candidates (default: 1)'
    )
    convert_parser.add_argument(
        '--format', 
        choices=['excel', 'csv'], 
        default='excel',
        help='Output format (default: excel)'
    )
    convert_parser.add_argument(
        '--force', 
        action='store_true',
        help='Overwrite output file if it exists'
    )
    
    # Template command
    template_parser = subparsers.add_parser(
        'template',
        help='Create enhanced location pins template'
    )
    template_parser.add_argument(
        '--output', 
        default='location_pins_enhanced_template.xlsx',
        help='Output template file path (default: location_pins_enhanced_template.xlsx)'
    )
    template_parser.add_argument(
        '--force',
        action='store_true', 
        help='Overwrite template file if it exists'
    )
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    try:
        if args.command == 'convert':
            return handle_convert(args)
        elif args.command == 'template':
            return handle_template(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def handle_convert(args):
    """Handle the convert command."""
    
    # Validate input file
    kml_path = Path(args.kml_file)
    if not kml_path.exists():
        print(f"Error: KML file not found: {kml_path}", file=sys.stderr)
        return 1
    
    if not kml_path.suffix.lower() == '.kml':
        print(f"Warning: Input file doesn't have .kml extension: {kml_path}")
    
    # Determine output file path
    output_ext = '.xlsx' if args.format == 'excel' else '.csv'
    output_path = Path(args.output_file)
    
    # Add extension if not provided
    if not output_path.suffix:
        output_path = output_path.with_suffix(output_ext)
    
    # Check if output file exists
    if output_path.exists() and not args.force:
        print(f"Error: Output file already exists: {output_path}")
        print("Use --force to overwrite")
        return 1
    
    # Convert the file
    print(f"Converting {kml_path} to {args.format} format...")
    print(f"Default electrification candidates: {args.candidates}")
    
    try:
        result_file = convert_kml_to_location_pins(
            str(kml_path),
            str(output_path.with_suffix('')),  # Remove extension since function adds it
            args.candidates,
            args.format
        )
        
        print(f"✓ Successfully converted KML to location pins format")
        print(f"✓ Output file: {result_file}")
        
        # Show some statistics
        try:
            import pandas as pd
            df = pd.read_excel(result_file) if args.format == 'excel' else pd.read_csv(result_file)
            print(f"✓ Total locations: {len(df)}")
            if 'Category Name' in df.columns:
                categories = df['Category Name'].value_counts()
                print(f"✓ Categories found: {len(categories)}")
                for category, count in categories.head(5).items():
                    print(f"  - {category}: {count} locations")
                if len(categories) > 5:
                    print(f"  - ... and {len(categories) - 5} more categories")
        except Exception:
            pass  # Statistics are optional
            
        return 0
        
    except Exception as e:
        print(f"Error during conversion: {e}", file=sys.stderr)
        return 1


def handle_template(args):
    """Handle the template command."""
    
    output_path = Path(args.output)
    
    # Check if output file exists
    if output_path.exists() and not args.force:
        print(f"Error: Template file already exists: {output_path}")
        print("Use --force to overwrite")
        return 1
    
    # Create the template
    print(f"Creating enhanced location pins template...")
    
    try:
        result_file = create_enhanced_template(str(output_path))
        print(f"✓ Successfully created enhanced template")
        print(f"✓ Template file: {result_file}")
        print(f"✓ The template includes:")
        print(f"  - Instructions sheet with usage guidelines")
        print(f"  - Support for both address-based and coordinate-based locations")
        print(f"  - Data validation for coordinates and candidates")
        print(f"  - Sample data showing proper format")
        return 0
        
    except Exception as e:
        print(f"Error creating template: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
