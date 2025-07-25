import os
import io
import json
import uuid
import time
import requests
import logging
from flask import Flask, request, send_from_directory, url_for, jsonify, render_template_string, redirect, Response, render_template, send_file, session
import pandas as pd
import geopandas as gpd
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from shapely.geometry import Point
import googlemaps
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Initialize Flask app and security configs
app = Flask(__name__)
# Debug mode
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
app.config['DEBUG'] = DEBUG
# File upload limits
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB
# Allowed upload MIME types
ALLOWED_MIME_TYPES = [
    'text/csv',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
]
# CSRF protection
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
from flask_wtf import CSRFProtect
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename
csrf = CSRFProtect(app)

@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    return 'File too large. Maximum size is 10MB.', 413

# Set base directory for all file paths
basedir = os.path.abspath(os.path.dirname(__file__))

# Directories
os.makedirs(os.path.join(basedir, "static", "maps"), exist_ok=True)
os.makedirs(os.path.join(basedir, "static", "img"), exist_ok=True)

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

# Google Maps API Key (set your key here or via environment variable)
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "YOUR_GOOGLE_MAPS_API_KEY")

# In-memory map data store
MAP_DATA = {}

# Directory for hosted map JSON files
HOSTED_MAPS_DIR = os.path.join(basedir, "static", "maps")
os.makedirs(HOSTED_MAPS_DIR, exist_ok=True)

# HTML template for embeddable Google Map
GOOGLE_MAPS_EMBED_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>EV/ICE TCO Parity Probability Map (Google Maps)</title>
    <style>
      html, body { height: 100%; margin: 0; padding: 0; font-family: Calibri; }
      #map { height: 100%; min-height: 480px; }
      #legend {
        background: white;
        padding: 16px 20px 16px 20px;
        border: 2px solid #888;
        border-radius: 10px;
        position: relative;
        left: 60px;
        bottom: 40px;
        width: 300px;
        z-index: 5;
        font-size: 16.5px;
        margin-left: 0;
        box-shadow: 0 6px 24px 0 rgba(0,0,0,0.18), 0 1.5px 6px 0 rgba(0,0,0,0.10);
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
      .cluster-table-container {
        position: fixed;
        top: 80px;
        right: 10px;
        width: 350px;
        max-height: 85vh;
        background-color: white;
        border: 1px solid #ccc;
        border-radius: 5px;
        padding: 10px;
        z-index: 10001;
        overflow-y: auto;
        font-size: 14px;
        display: none;
      }
      .cluster-table {
        width: 100%;
        border-collapse: collapse;
      }
      .cluster-table th, .cluster-table td {
        border: 1px solid #ddd;
        padding: 6px 8px;
        text-align: left;
        font-size: 12px;
      }
      .cluster-table th {
        background-color: #f2f2f2;
        font-weight: bold;
      }
      .error-message {
        position: fixed;
        top: 20px;
        left: 50%;
        transform: translateX(-50%);
        background: #ff4444;
        color: white;
        padding: 10px 20px;
        border-radius: 5px;
        z-index: 10000;
        display: none;
      }
    </style>
</head>
<body>
<div id="error-message" class="error-message"></div>
<div id="map"></div>
<div class="cluster-table-container" id="clusterTableContainer">
  <h3>Location Details</h3>
  <div style="max-height: calc(85vh - 60px); overflow-y: auto;">
    <table class="cluster-table" id="clusterTable">
      <thead>
        <tr>
          <th>Location Name</th>
          <th>Electrification Candidates</th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
  </div>
</div>
<div id="legend"> 
  <b>State Grouping Color Guide</b><br>
  <div><span class="legend-color" style="background:{{ group_colors['Group 1'] }}CC"></span>Group 1 (Best Parity Probability)</div>
  <div><span class="legend-color" style="background:{{ group_colors['Group 2'] }}CC"></span>Group 2 (Better Parity Probability)</div>
  <div><span class="legend-color" style="background:{{ group_colors['Group 3'] }}CC"></span>Group 3 (Good Parity Probability)</div>
</div>
<div id="pinLegend" style="background: white; padding: 16px 20px; border: 2px solid #888; border-radius: 10px; position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); width: auto; min-width: 400px; z-index: 5; font-size: 16.5px; box-shadow: 0 6px 24px 0 rgba(0,0,0,0.18), 0 1.5px 6px 0 rgba(0,0,0,0.10); text-align: center;">
  <b>Pin Categories:</b><br>
  <div id="pinCategoryContent" style="margin-top: 10px; display: flex; justify-content: center; align-items: center; gap: 30px; flex-wrap: wrap;">
    <!-- Dynamic content will be inserted here by JavaScript -->
  </div>
</div>

<script>
// Enhanced error handling function with clustering-specific feedback
function showError(message, type = 'error', duration = 5000) {
  const errorDiv = document.getElementById('error-message');
  errorDiv.textContent = message;
  
  // Style based on error type
  if (type === 'warning') {
    errorDiv.style.background = '#ff9800';
  } else if (type === 'info') {
    errorDiv.style.background = '#2196f3';
  } else {
    errorDiv.style.background = '#ff4444';
  }
  
  errorDiv.style.display = 'block';
  setTimeout(() => {
    errorDiv.style.display = 'none';
  }, duration);
}

// Clustering-specific error handling
function handleClusteringError(error, fallbackToIndividual = true) {
  console.error('Clustering error:', error);
  
  if (fallbackToIndividual) {
    showError('Clustering library unavailable. Displaying individual markers instead.', 'warning', 7000);
    return true; // Indicate fallback should be used
  } else {
    showError('Map clustering failed. Please refresh the page to try again.', 'error');
    return false;
  }
}

// Helper function to display individual markers with error handling
function displayIndividualMarkers(markers, map) {
  let successCount = 0;
  let errorCount = 0;
  
  markers.forEach(function(marker, index) {
    try {
      if (marker && typeof marker.setMap === 'function') {
        marker.setMap(map);
        successCount++;
      } else {
        console.warn('Invalid marker at index', index, ':', marker);
        errorCount++;
      }
    } catch (markerError) {
      console.error('Error setting marker', index, 'on map:', markerError);
      errorCount++;
    }
  });
  
  if (errorCount > 0) {
    showError(`${errorCount} markers could not be displayed properly.`, 'warning', 5000);
  }
}

// Helper function to hide cluster table with error handling
function hideClusterTable() {
  try {
    const tableContainer = document.getElementById('clusterTableContainer');
    if (tableContainer) {
      tableContainer.style.display = 'none';
    }
  } catch (error) {
    console.error('Error hiding cluster table:', error);
  }
}

// Helper function to show cluster table with error handling
function showClusterTable() {
  try {
    const tableContainer = document.getElementById('clusterTableContainer');
    if (tableContainer) {
      tableContainer.style.display = 'block';
      return true;
    } else {
      console.warn('DEBUG: tableContainer not found when trying to show');
      return false;
    }
  } catch (error) {
    console.error('Error showing cluster table:', error);
    return false;
  }
}

// FIXED: Helper function to validate clustering decision logic
function validateClusteringDecision(clusteringEnabled, markers, expectedDecision) {
  console.log('DEBUG: VALIDATING CLUSTERING DECISION LOGIC');
  console.log('DEBUG: Input parameters:');
  console.log('DEBUG: - clusteringEnabled:', clusteringEnabled, 'type:', typeof clusteringEnabled);
  console.log('DEBUG: - markers.length:', markers ? markers.length : 'undefined');
  console.log('DEBUG: - expectedDecision:', expectedDecision);
  
  // Test the actual decision logic
  const actualDecision = (clusteringEnabled === true) && (markers && markers.length > 0);
  console.log('DEBUG: Actual decision result:', actualDecision);
  console.log('DEBUG: Decision matches expected:', actualDecision === expectedDecision);
  
  // Validate boolean evaluation
  const booleanTests = {
    'strict_equality': clusteringEnabled === true,
    'loose_equality': clusteringEnabled == true,
    'boolean_cast': Boolean(clusteringEnabled),
    'truthy_check': !!clusteringEnabled
  };
  
  console.log('DEBUG: Boolean evaluation tests:', booleanTests);
  
  // Check for common issues
  if (typeof clusteringEnabled !== 'boolean') {
    console.warn('DEBUG: ⚠ WARNING - clusteringEnabled is not a boolean type');
  }
  
  if (clusteringEnabled === 'true' || clusteringEnabled === 'false') {
    console.warn('DEBUG: ⚠ WARNING - clusteringEnabled appears to be a string, not boolean');
  }
  
  return actualDecision === expectedDecision;
}

// Check if Google Maps loaded
function checkGoogleMaps() {
  if (typeof google === 'undefined' || !google.maps) {
    showError('Google Maps failed to load. Please check your internet connection and API key.');
    return false;
  }
  return true;
}

const CLUSTER_COLORS = [
  {bg: 'rgba(0,86,184,0.85)', row: 'rgba(0,86,184,0.13)'},
  {bg: 'rgba(0,161,224,0.85)', row: 'rgba(0,161,224,0.13)'},
  {bg: 'rgba(107,192,75,0.85)', row: 'rgba(107,192,75,0.13)'}
];

let statePolygons, pins, clusteringEnabled, showLabels;

try {
  statePolygons = {{ state_polygons|safe }};
  pins = {{ pins|safe }};
  
  // FIXED: Enhanced template variable injection with explicit type validation
  clusteringEnabled = {{ clustering_enabled|tojson }};
  showLabels = {{ show_labels|tojson }};
  
  // DEBUG: Enhanced template variable logging with explicit boolean validation
  console.log('='.repeat(60));
  console.log('DEBUG: JAVASCRIPT TEMPLATE VARIABLES LOADED');
  console.log('='.repeat(60));
  console.log('DEBUG: clusteringEnabled value:', clusteringEnabled);
  console.log('DEBUG: clusteringEnabled type:', typeof clusteringEnabled);
  console.log('DEBUG: clusteringEnabled === true:', clusteringEnabled === true);
  console.log('DEBUG: clusteringEnabled === false:', clusteringEnabled === false);
  console.log('DEBUG: clusteringEnabled == true:', clusteringEnabled == true);
  console.log('DEBUG: clusteringEnabled == false:', clusteringEnabled == false);
  console.log('DEBUG: Boolean(clusteringEnabled):', Boolean(clusteringEnabled));
  console.log('DEBUG: !clusteringEnabled:', !clusteringEnabled);
  console.log('DEBUG: String(clusteringEnabled):', String(clusteringEnabled));
  console.log('DEBUG: JSON.stringify(clusteringEnabled):', JSON.stringify(clusteringEnabled));
  console.log('DEBUG: Template injection verification:');
  console.log('DEBUG: - Raw Python value: {{ clustering_enabled }}');
  console.log('DEBUG: - Python type: {{ clustering_enabled.__class__.__name__ if clustering_enabled is defined else "undefined" }}');
  console.log('DEBUG: - JSON filter result: {{ clustering_enabled|tojson }}');
  console.log('DEBUG: - String filter result: {{ clustering_enabled|string }}');
  
  // FIXED: Enhanced boolean validation and conversion with comprehensive error handling
  console.log('DEBUG: BOOLEAN CONVERSION - Pre-conversion analysis:');
  console.log('DEBUG: clusteringEnabled original value:', clusteringEnabled);
  console.log('DEBUG: clusteringEnabled original type:', typeof clusteringEnabled);
  console.log('DEBUG: clusteringEnabled === true:', clusteringEnabled === true);
  console.log('DEBUG: clusteringEnabled === false:', clusteringEnabled === false);
  
  if (typeof clusteringEnabled !== 'boolean') {
    console.warn('DEBUG: FIXED - clusteringEnabled is not a boolean, performing conversion...');
    console.log('DEBUG: FIXED - This indicates a potential template injection issue');
    
    const originalValue = clusteringEnabled;
    const originalType = typeof clusteringEnabled;
    
    // Handle different possible values with explicit conversion
    if (clusteringEnabled === 'true') {
      clusteringEnabled = true;
      console.log('DEBUG: FIXED - Converted string "true" to boolean true');
    } else if (clusteringEnabled === 'false') {
      clusteringEnabled = false;
      console.log('DEBUG: FIXED - Converted string "false" to boolean false');
    } else if (clusteringEnabled === true) {
      // Already true, no conversion needed
      console.log('DEBUG: FIXED - Value already boolean true');
    } else if (clusteringEnabled === false) {
      // Already false, no conversion needed
      console.log('DEBUG: FIXED - Value already boolean false');
    } else if (clusteringEnabled === null || clusteringEnabled === undefined) {
      clusteringEnabled = false;
      console.log('DEBUG: FIXED - Converted null/undefined to boolean false');
    } else {
      // Fallback to boolean conversion
      clusteringEnabled = Boolean(clusteringEnabled);
      console.log('DEBUG: FIXED - Used Boolean() conversion as fallback');
    }
    
    console.log('DEBUG: FIXED - Conversion summary:');
    console.log('DEBUG: FIXED - Original:', originalValue, 'type:', originalType);
    console.log('DEBUG: FIXED - Converted:', clusteringEnabled, 'type:', typeof clusteringEnabled);
    console.log('DEBUG: FIXED - Conversion successful:', typeof clusteringEnabled === 'boolean');
  } else {
    console.log('DEBUG: FIXED - clusteringEnabled is already a boolean, no conversion needed');
  }
  
  // FIXED: Add explicit boolean validation for showLabels too
  if (typeof showLabels !== 'boolean') {
    console.warn('DEBUG: FIXED - showLabels is not a boolean, converting...');
    console.log('DEBUG: FIXED - Original showLabels value:', showLabels, 'type:', typeof showLabels);
    
    // Handle different possible values
    if (showLabels === 'true' || showLabels === true) {
      showLabels = true;
    } else if (showLabels === 'false' || showLabels === false || showLabels === null || showLabels === undefined) {
      showLabels = false;
    } else {
      // Fallback to boolean conversion
      showLabels = Boolean(showLabels);
    }
    console.log('DEBUG: FIXED - Converted showLabels value:', showLabels, 'type:', typeof showLabels);
  }
  
  console.log('DEBUG: showLabels value:', showLabels);
  console.log('DEBUG: showLabels type:', typeof showLabels);
  console.log('DEBUG: Boolean(showLabels):', Boolean(showLabels));
  console.log('DEBUG: pins count:', pins ? pins.length : 'undefined');
  console.log('DEBUG: statePolygons count:', statePolygons ? statePolygons.length : 'undefined');
  console.log('='.repeat(60));
  
} catch (e) {
  console.error('Error parsing template data:', e);
  showError('Error loading map data. Please try refreshing the page.');
}

function initMap() {
  // Check if Google Maps failed to load
  if (window.googleMapsUnavailable) {
    console.error('DEBUG: Google Maps API unavailable, cannot initialize map');
    showError('Google Maps API is unavailable. Please refresh the page to try again.', 'error', 15000);
    return;
  }
  
  if (!checkGoogleMaps()) return;
  
  // DEBUG: Enhanced template boolean conversion verification
  console.log('='.repeat(60));
  console.log('DEBUG: TEMPLATE BOOLEAN CONVERSION CHECK');
  console.log('='.repeat(60));
  console.log('DEBUG: Raw Python clustering_enabled: {{ clustering_enabled }}');
  console.log('DEBUG: Raw Python clustering_enabled type: {{ clustering_enabled.__class__.__name__ if clustering_enabled is defined else "undefined" }}');
  console.log('DEBUG: Raw Python clustering_enabled str: {{ clustering_enabled|string if clustering_enabled is defined else "undefined" }}');
  console.log('DEBUG: JSON template clustering_enabled: {{ clustering_enabled|tojson }}');
  console.log('DEBUG: JavaScript clusteringEnabled:', clusteringEnabled);
  console.log('DEBUG: JavaScript clusteringEnabled type:', typeof clusteringEnabled);
  console.log('DEBUG: JavaScript clusteringEnabled === true:', clusteringEnabled === true);
  console.log('DEBUG: JavaScript clusteringEnabled === false:', clusteringEnabled === false);
  console.log('DEBUG: JavaScript clusteringEnabled == true:', clusteringEnabled == true);
  console.log('DEBUG: JavaScript clusteringEnabled == false:', clusteringEnabled == false);
  console.log('DEBUG: JavaScript Boolean(clusteringEnabled):', Boolean(clusteringEnabled));
  console.log('DEBUG: JavaScript String(clusteringEnabled):', String(clusteringEnabled));
  
  // FIXED: Additional boolean validation in initMap with comprehensive type checking
  console.log('DEBUG: FIXED - Pre-validation clusteringEnabled:', clusteringEnabled, 'type:', typeof clusteringEnabled);
  if (typeof clusteringEnabled !== 'boolean') {
    console.warn('DEBUG: FIXED - clusteringEnabled is not boolean in initMap, converting...');
    console.log('DEBUG: FIXED - This should not happen if template injection is working correctly');
    
    // Handle different possible values with explicit conversion
    if (clusteringEnabled === 'true' || clusteringEnabled === true) {
      clusteringEnabled = true;
    } else if (clusteringEnabled === 'false' || clusteringEnabled === false || clusteringEnabled === null || clusteringEnabled === undefined) {
      clusteringEnabled = false;
    } else {
      // Fallback to boolean conversion
      clusteringEnabled = Boolean(clusteringEnabled);
    }
    console.log('DEBUG: FIXED - Post-conversion clusteringEnabled:', clusteringEnabled, 'type:', typeof clusteringEnabled);
  }
  
  // FIXED: Add similar validation for showLabels
  console.log('DEBUG: FIXED - Pre-validation showLabels:', showLabels, 'type:', typeof showLabels);
  if (typeof showLabels !== 'boolean') {
    console.warn('DEBUG: FIXED - showLabels is not boolean in initMap, converting...');
    
    // Handle different possible values with explicit conversion
    if (showLabels === 'true' || showLabels === true) {
      showLabels = true;
    } else if (showLabels === 'false' || showLabels === false || showLabels === null || showLabels === undefined) {
      showLabels = false;
    } else {
      // Fallback to boolean conversion
      showLabels = Boolean(showLabels);
    }
    console.log('DEBUG: FIXED - Post-conversion showLabels:', showLabels, 'type:', typeof showLabels);
  }
  
  console.log('DEBUG: Raw Python show_labels: {{ show_labels }}');
  console.log('DEBUG: Raw Python show_labels type: {{ show_labels.__class__.__name__ if show_labels is defined else "undefined" }}');
  console.log('DEBUG: JSON template show_labels: {{ show_labels|tojson }}');
  console.log('DEBUG: JavaScript showLabels:', showLabels);
  console.log('DEBUG: JavaScript showLabels type:', typeof showLabels);
  console.log('='.repeat(60));
  
  console.log('DEBUG: Initializing map with', pins.length, 'pins and', statePolygons.length, 'state polygons');
  
  try {
    const customMapStyle = [
      // Hide various labels to reduce clutter
      { featureType: 'administrative.locality', elementType: 'labels', stylers: [{ visibility: 'off' }] },
      { featureType: 'administrative.neighborhood', elementType: 'labels', stylers: [{ visibility: 'off' }] },
      { featureType: 'poi', elementType: 'labels', stylers: [{ visibility: 'off' }] },
      { featureType: 'road', elementType: 'labels', stylers: [{ visibility: 'off' }] },
      { featureType: 'transit', elementType: 'labels', stylers: [{ visibility: 'off' }] },
      { featureType: 'water', elementType: 'labels', stylers: [{ visibility: 'off' }] },
      { featureType: 'administrative.province', elementType: 'labels', stylers: [{ visibility: 'on' }] },
      { featureType: 'administrative.country', elementType: 'labels', stylers: [{ visibility: 'on' }] },
      
      // Make the entire map monochromatic/grayscale
      { elementType: 'geometry', stylers: [{ saturation: -100 }, { lightness: 20 }] },
      { elementType: 'labels.text.fill', stylers: [{ saturation: -100 }, { color: '#666666' }] },
      { elementType: 'labels.text.stroke', stylers: [{ saturation: -100 }, { color: '#ffffff' }] },
      
      // Specific feature styling for monochromatic look
      { featureType: 'water', elementType: 'geometry', stylers: [{ saturation: -100 }, { lightness: 30 }] },
      { featureType: 'road', elementType: 'geometry', stylers: [{ saturation: -100 }, { lightness: 40 }] },
      { featureType: 'landscape', elementType: 'geometry', stylers: [{ saturation: -100 }, { lightness: 50 }] },
      { featureType: 'administrative.country', elementType: 'geometry.stroke', stylers: [{ saturation: -100 }, { color: '#999999' }] },
      { featureType: 'administrative.province', elementType: 'geometry.stroke', stylers: [{ saturation: -100 }, { color: '#cccccc' }] }
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
    
    // Add state polygons with error handling
    if (statePolygons && statePolygons.length > 0) {
      statePolygons.forEach(function(poly, index) {
        try {
          if (poly.paths && poly.paths.length > 0) {
            const polygon = new google.maps.Polygon({
              paths: poly.paths,
              strokeColor: '#000',
              strokeOpacity: 0.7,
              strokeWeight: 1,
              fillColor: poly.color || '#cccccc',
              fillOpacity: 0.75
            });
            polygon.setMap(map);
          }
        } catch (e) {
          console.warn('Error creating polygon', index, ':', e);
        }
      });
      console.log('Added', statePolygons.length, 'state polygons');
    }
    
    // Create markers with error handling
    const infoWindow = new google.maps.InfoWindow();
    let markers = [];
    
    if (pins && pins.length > 0) {
      pins.forEach(function(pin, index) {
        try {
          if (pin.lat && pin.lng && !isNaN(pin.lat) && !isNaN(pin.lng)) {
            const marker = new google.maps.Marker({
              position: {lat: parseFloat(pin.lat), lng: parseFloat(pin.lng)},
              icon: {
                url: pin.icon_url,
                scaledSize: new google.maps.Size(40, 40),
                anchor: new google.maps.Point(20, 20)
              },
              title: showLabels ? (pin.label || '') : ''
            });
            
            marker.addListener('click', function() {
              const content = `<div><strong>${pin.label || 'Unknown Location'}</strong><br>Candidates: ${pin.electrification_candidates || 'N/A'}</div>`;
              infoWindow.setContent(content);
              infoWindow.open(map, marker);
            });
            
            markers.push(marker);
          } else {
            console.warn('Invalid pin coordinates at index', index, ':', pin);
          }
        } catch (e) {
          console.warn('Error creating marker', index, ':', e);
        }
      });
      console.log('Created', markers.length, 'markers from', pins.length, 'pins');
    }
    
    // FIXED: Enhanced clustering decision logic with comprehensive boolean evaluation
    console.log('='.repeat(60));
    console.log('DEBUG: CLUSTERING DECISION LOGIC - COMPREHENSIVE EVALUATION');
    console.log('='.repeat(60));
    
    // Step 1: Validate clusteringEnabled variable
    console.log('DEBUG: Step 1 - Variable Analysis:');
    console.log('DEBUG: clusteringEnabled raw value:', clusteringEnabled);
    console.log('DEBUG: clusteringEnabled type:', typeof clusteringEnabled);
    console.log('DEBUG: clusteringEnabled === true:', clusteringEnabled === true);
    console.log('DEBUG: clusteringEnabled === false:', clusteringEnabled === false);
    console.log('DEBUG: clusteringEnabled == true (loose):', clusteringEnabled == true);
    console.log('DEBUG: clusteringEnabled == false (loose):', clusteringEnabled == false);
    console.log('DEBUG: Boolean(clusteringEnabled):', Boolean(clusteringEnabled));
    console.log('DEBUG: !clusteringEnabled:', !clusteringEnabled);
    
    // Step 2: Validate markers array
    console.log('DEBUG: Step 2 - Markers Analysis:');
    console.log('DEBUG: markers array:', markers);
    console.log('DEBUG: markers.length:', markers.length);
    console.log('DEBUG: markers.length > 0:', markers.length > 0);
    console.log('DEBUG: Array.isArray(markers):', Array.isArray(markers));
    
    // Step 3: Test different boolean evaluation approaches
    console.log('DEBUG: Step 3 - Boolean Evaluation Tests:');
    console.log('DEBUG: Original condition (clusteringEnabled && markers.length > 0):', clusteringEnabled && markers.length > 0);
    console.log('DEBUG: Loose equality (clusteringEnabled == true && markers.length > 0):', clusteringEnabled == true && markers.length > 0);
    console.log('DEBUG: Boolean cast (Boolean(clusteringEnabled) && markers.length > 0):', Boolean(clusteringEnabled) && markers.length > 0);
    
    // FIXED: Robust clustering decision with multiple validation layers
    let shouldEnableClustering = false;
    let decisionReason = '';
    
    // Primary condition: strict boolean check
    if (clusteringEnabled === true && markers.length > 0) {
      shouldEnableClustering = true;
      decisionReason = 'Clustering enabled: checkbox checked and markers available';
    } else if (clusteringEnabled !== true) {
      shouldEnableClustering = false;
      decisionReason = `Clustering disabled: checkbox unchecked (value: ${clusteringEnabled}, type: ${typeof clusteringEnabled})`;
    } else if (markers.length === 0) {
      shouldEnableClustering = false;
      decisionReason = 'Clustering disabled: no markers to cluster';
    } else {
      shouldEnableClustering = false;
      decisionReason = 'Clustering disabled: unknown condition';
    }
    
    console.log('DEBUG: Step 4 - Final Decision:');
    console.log('DEBUG: FIXED shouldEnableClustering (robust evaluation):', shouldEnableClustering);
    console.log('DEBUG: Decision reason:', decisionReason);
    console.log('DEBUG: Decision: Will', shouldEnableClustering ? 'ENABLE' : 'DISABLE', 'clustering');
    

    
    // Step 5: Validation against requirements
    console.log('DEBUG: Step 5 - Requirements Validation:');
    console.log('DEBUG: Requirement 1.1 - User control over clustering:', shouldEnableClustering === (clusteringEnabled === true));
    console.log('DEBUG: Requirement 1.2 - Checkbox state preservation:', typeof clusteringEnabled === 'boolean');
    console.log('DEBUG: Expected behavior: clustering should be', clusteringEnabled === true ? 'ENABLED' : 'DISABLED');
    console.log('DEBUG: Actual behavior: clustering will be', shouldEnableClustering ? 'ENABLED' : 'DISABLED');
    console.log('DEBUG: Behavior matches expectation:', (clusteringEnabled === true) === shouldEnableClustering);
    
    // FIXED: Use validation helper function
    const validationPassed = validateClusteringDecision(clusteringEnabled, markers, shouldEnableClustering);
    console.log('DEBUG: Clustering decision validation passed:', validationPassed);
    console.log('='.repeat(60));
    
    // FIXED: Execute clustering decision with enhanced validation
    if (shouldEnableClustering === true) {
      try {
        console.log('DEBUG: ENTERING CLUSTERING SETUP - User requested clustering');
        console.log('DEBUG: Clustering decision validation passed - proceeding with cluster setup');
        console.log('DEBUG: typeof markerClusterer:', typeof markerClusterer);
        console.log('DEBUG: markerClusterer object:', markerClusterer);
        console.log('DEBUG: MarkerClusterer available:', typeof markerClusterer !== 'undefined' && markerClusterer.MarkerClusterer);
        console.log('DEBUG: MarkerClusterer constructor:', markerClusterer ? markerClusterer.MarkerClusterer : 'undefined');
        
        // Enhanced clustering library availability check
        if (!window.clusteringUnavailable && typeof markerClusterer !== 'undefined' && markerClusterer && markerClusterer.MarkerClusterer) {
          try {
            const clusterer = new markerClusterer.MarkerClusterer({
              map: map,
              markers: markers,
              renderer: {
                render: function({ count, position }) {
                  try {
                    const colorIdx = (count <= 10) ? 0 : (count <= 30) ? 1 : 2;
                    const color = CLUSTER_COLORS[colorIdx].bg;
                    return new google.maps.Marker({
                      position,
                      icon: {
                        path: google.maps.SymbolPath.CIRCLE,
                        fillColor: color,
                        fillOpacity: 1,
                        strokeColor: '#fff',
                        strokeWeight: 2,
                        scale: 24 + Math.min(24, count)
                      },
                      label: {
                        text: String(count),
                        color: '#fff',
                        fontWeight: 'bold',
                        fontSize: '15px'
                      },
                      zIndex: 1000 + count
                    });
                  } catch (renderError) {
                    console.error('Error in cluster renderer:', renderError);
                    // Return a simple fallback marker
                    return new google.maps.Marker({
                      position,
                      label: String(count)
                    });
                  }
                }
              }
            });
            
            // Verify clusterer was created successfully
            if (!clusterer) {
              throw new Error('MarkerClusterer constructor returned null/undefined');
            }
            
            // Show cluster table with error handling
            console.log('DEBUG: SHOWING CLUSTER TABLE');
            const tableContainer = document.getElementById('clusterTableContainer');
            console.log('DEBUG: tableContainer element:', tableContainer);
            if (tableContainer) {
              console.log('DEBUG: Setting tableContainer display to block');
              tableContainer.style.display = 'block';
              console.log('DEBUG: tableContainer.style.display after setting:', tableContainer.style.display);
              console.log('DEBUG: Cluster table container displayed successfully');
              const tableBody = document.querySelector('#clusterTable tbody');
              console.log('DEBUG: tableBody element:', tableBody);
              if (tableBody) {
                // Clear existing rows first
                tableBody.innerHTML = '';
                console.log('DEBUG: Adding', pins.length, 'rows to cluster table');
                pins.forEach(function(pin, index) {
                  try {
                    const row = document.createElement('tr');
                    row.innerHTML = `<td>${pin.label || 'Unknown'}</td><td style="text-align: right;">${pin.electrification_candidates || 'N/A'}</td>`;
                    tableBody.appendChild(row);
                    if (index < 3) console.log('DEBUG: Added row', index + 1, ':', pin.label);
                  } catch (rowError) {
                    console.warn('Error adding table row', index, ':', rowError);
                  }
                });
                console.log('DEBUG: Successfully added', pins.length, 'rows to cluster table');
              } else {
                console.error('DEBUG: tableBody not found!');
              }
            } else {
              console.error('DEBUG: tableContainer not found!');
            }
            console.log('DEBUG: FIXED - Clustering successfully enabled with', markers.length, 'markers');
            console.log('DEBUG: FIXED - Cluster table should be visible');
            
          } catch (clustererError) {
            console.error('DEBUG: ERROR CREATING MARKERCLUSTERER INSTANCE:', clustererError);
            console.error('DEBUG: MarkerClusterer creation error stack:', clustererError.stack);
            
            // Handle specific clustering errors with user feedback
            if (handleClusteringError(clustererError, true)) {
              console.log('DEBUG: FALLBACK - Switching to individual markers due to MarkerClusterer creation error');
              displayIndividualMarkers(markers, map);
              hideClusterTable();
            }
          }
          
        } else {
          console.warn('DEBUG: MARKERCLUSTERER NOT AVAILABLE - FALLBACK TO INDIVIDUAL MARKERS');
          console.log('DEBUG: typeof markerClusterer:', typeof markerClusterer);
          console.log('DEBUG: markerClusterer:', markerClusterer);
          console.log('DEBUG: FIXED - Clustering was requested but MarkerClusterer unavailable, showing individual markers');
          
          // Provide user feedback about clustering unavailability
          handleClusteringError(new Error('MarkerClusterer library not available'), true);
          displayIndividualMarkers(markers, map);
          hideClusterTable();
        }
      } catch (e) {
        console.error('DEBUG: ERROR SETTING UP CLUSTERING:', e);
        console.error('DEBUG: Error stack:', e.stack);
        console.log('DEBUG: FALLBACK - Switching to individual markers');
        
        // Enhanced error handling with user feedback
        if (handleClusteringError(e, true)) {
          displayIndividualMarkers(markers, map);
          hideClusterTable();
        }
      }
    } else {
      // FIXED: Enhanced clustering disabled logic with detailed reasoning
      console.log('DEBUG: FIXED - CLUSTERING DISABLED - SHOWING INDIVIDUAL MARKERS');
      console.log('DEBUG: Clustering disabled reason:', decisionReason);
      console.log('DEBUG: User checkbox state (clusteringEnabled):', clusteringEnabled);
      console.log('DEBUG: Available markers count:', markers.length);
      console.log('DEBUG: shouldEnableClustering result:', shouldEnableClustering);
      
      // Validate that this matches user expectation
      if (clusteringEnabled === false) {
        console.log('DEBUG: ✓ CORRECT - User unchecked clustering checkbox, showing individual markers');
      } else if (clusteringEnabled !== true) {
        console.log('DEBUG: ⚠ WARNING - Unexpected clusteringEnabled value:', clusteringEnabled, 'type:', typeof clusteringEnabled);
      } else if (markers.length === 0) {
        console.log('DEBUG: ✓ CORRECT - No markers available for clustering');
      }
      
      // Use helper functions for consistent error handling
      hideClusterTable();
      displayIndividualMarkers(markers, map);
      
      console.log('DEBUG: FIXED - Clustering disabled, displaying', markers.length, 'individual markers');
      console.log('DEBUG: FIXED - Cluster table hidden as expected');
      console.log('DEBUG: FIXED - Individual markers should be visible on map');
    }
    
// Add state legend to left bottom
const legendElement = document.getElementById('legend');
if (legendElement) {
  legendElement.style.marginLeft = '20px';
  map.controls[google.maps.ControlPosition.LEFT_BOTTOM].push(legendElement);
}

// Add pin legend to bottom center
const pinLegendElement = document.getElementById('pinLegend');
if (pinLegendElement) {
  // Populate dynamic pin legend content first
  const pinCategoryContent = document.getElementById('pinCategoryContent');
  if (pinCategoryContent) {
    // Count pins by category and get unique pin configurations
    const categoryStats = {};
    const categoryConfigs = {};
    
    pins.forEach(function(pin) {
      const category = pin.category || 'Default';
      if (!categoryStats[category]) {
        categoryStats[category] = 0;
        categoryConfigs[category] = pin.icon_url;
      }
      categoryStats[category]++;
    });
    
    // Sort categories by pin count (most to least)
    const sortedCategories = Object.keys(categoryStats).sort((a, b) => categoryStats[b] - categoryStats[a]);
    
    // Generate legend items horizontally
    const legendItems = sortedCategories.map(function(category) {
      const count = categoryStats[category];
      const iconUrl = categoryConfigs[category];
      return `
        <div style="display: flex; align-items: center; gap: 8px;">
          <img src="${iconUrl}" style="width: 24px; height: 24px;" alt="${category} pin"/>
          <span>${category}</span>
        </div>
      `;
    });
    
    pinCategoryContent.innerHTML = legendItems.join('');
  }
  
  // FIXED: Remove from Google Maps controls to allow CSS positioning to work
  // The CSS position: fixed; bottom: 60px; left: 50%; transform: translateX(-50%); 
  // will now work properly without Google Maps controls overriding it
}
    
    // Final validation: Ensure at least some markers are visible on the map
    setTimeout(function() {
      let visibleMarkers = 0;
      markers.forEach(function(marker) {
        if (marker && marker.getMap()) {
          visibleMarkers++;
        }
      });
      
      console.log('DEBUG: Final marker visibility check - visible markers:', visibleMarkers, 'total markers:', markers.length);
      
      if (visibleMarkers === 0 && markers.length > 0) {
        console.error('DEBUG: No markers are visible on the map! Attempting emergency fallback...');
        showError('Some markers may not be displaying properly. Attempting to fix...', 'warning', 5000);
        
        // Emergency fallback: force display individual markers
        displayIndividualMarkers(markers, map);
      } else if (visibleMarkers < markers.length) {
        console.warn('DEBUG: Some markers are not visible:', markers.length - visibleMarkers, 'missing');
        showError(`${markers.length - visibleMarkers} markers may not be displaying properly.`, 'warning', 5000);
      }
    }, 1000); // Check after 1 second to allow clustering to complete
    
    console.log('='.repeat(60));
    console.log('DEBUG: MAP INITIALIZATION COMPLETE');
    console.log('='.repeat(60));
    console.log('DEBUG: Final clustering state - clusteringEnabled:', clusteringEnabled);
    console.log('DEBUG: Final clustering state type:', typeof clusteringEnabled);
    console.log('DEBUG: Final show labels state - showLabels:', showLabels);
    console.log('DEBUG: Final show labels state type:', typeof showLabels);
    console.log('DEBUG: Total markers created:', markers.length);
    console.log('DEBUG: Total state polygons:', statePolygons.length);
    console.log('DEBUG: Cluster table visibility:', document.getElementById('clusterTableContainer') ? document.getElementById('clusterTableContainer').style.display : 'element not found');
    
    // FIXED: Final validation summary with comprehensive decision verification
    const finalShouldEnableClustering = (clusteringEnabled === true) && (markers.length > 0);
    console.log('DEBUG: FINAL CLUSTERING DECISION VALIDATION');
    console.log('DEBUG: Original shouldEnableClustering:', shouldEnableClustering);
    console.log('DEBUG: Final shouldEnableClustering check:', finalShouldEnableClustering);
    console.log('DEBUG: Decision consistency:', shouldEnableClustering === finalShouldEnableClustering);
    
    // Validate against requirements
    console.log('DEBUG: Requirements validation:');
    console.log('DEBUG: - Requirement 1.1 (user control): clustering decision matches checkbox =', (clusteringEnabled === true) === shouldEnableClustering);
    console.log('DEBUG: - Requirement 1.2 (state preservation): boolean type preserved =', typeof clusteringEnabled === 'boolean');
    
    // Check actual map state
    const clusterTableVisible = document.getElementById('clusterTableContainer') && 
                                document.getElementById('clusterTableContainer').style.display !== 'none';
    console.log('DEBUG: Actual cluster table visibility:', clusterTableVisible);
    console.log('DEBUG: Expected cluster table visibility:', shouldEnableClustering);
    console.log('DEBUG: Cluster table state matches decision:', clusterTableVisible === shouldEnableClustering);
    
    // Final user-facing validation
    if (shouldEnableClustering && !clusterTableVisible) {
      console.error('DEBUG: ❌ ERROR - Clustering enabled but table not visible');
    } else if (!shouldEnableClustering && clusterTableVisible) {
      console.error('DEBUG: ❌ ERROR - Clustering disabled but table still visible');
    } else {
      console.log('DEBUG: ✅ SUCCESS - Clustering decision and UI state are consistent');
    }
    
    console.log('DEBUG: FIXED - User checkbox selection should be respected');
    console.log('DEBUG: FIXED - If clustering appears when checkbox is unchecked, check template injection');
    console.log('='.repeat(60));
    
  } catch (e) {
    console.error('Error initializing map:', e);
    showError('Error initializing map. Please try refreshing the page.');
  }
}

// Initialize when page loads
window.addEventListener('load', function() {
  console.log('='.repeat(60));
  console.log('DEBUG: WINDOW LOAD EVENT TRIGGERED');
  console.log('='.repeat(60));
  console.log('DEBUG: Starting script loading sequence');
  console.log('DEBUG: Will load MarkerClusterer first, then Google Maps');
  
  // Set up timeout for script loading
  let clustererTimeout = setTimeout(function() {
    console.warn('DEBUG: MarkerClusterer loading timeout');
    showError('Clustering library is taking too long to load. Proceeding without clustering.', 'warning', 8000);
    window.clusteringUnavailable = true;
    loadGoogleMaps();
  }, 10000); // 10 second timeout
  
  // Load MarkerClusterer first, then Google Maps
  console.log('DEBUG: Creating MarkerClusterer script element');
  const clustererScript = document.createElement('script');
  clustererScript.src = 'https://unpkg.com/@googlemaps/markerclusterer/dist/index.min.js';
  clustererScript.onload = function() {
    clearTimeout(clustererTimeout); // Cancel timeout
    console.log('='.repeat(60));
    console.log('DEBUG: MARKERCLUSTERER SCRIPT LOADED');
    console.log('='.repeat(60));
    console.log('DEBUG: MarkerClusterer loaded successfully');
    console.log('DEBUG: typeof markerClusterer:', typeof markerClusterer);
    console.log('DEBUG: markerClusterer object:', markerClusterer);
    console.log('DEBUG: markerClusterer.MarkerClusterer available:', markerClusterer ? !!markerClusterer.MarkerClusterer : false);
    console.log('='.repeat(60));
    loadGoogleMaps();
  };
  clustererScript.onerror = function(error) {
    clearTimeout(clustererTimeout); // Cancel timeout
    console.log('='.repeat(60));
    console.warn('DEBUG: MARKERCLUSTERER SCRIPT FAILED TO LOAD');
    console.log('='.repeat(60));
    console.warn('DEBUG: Failed to load MarkerClusterer, proceeding without clustering');
    console.error('DEBUG: MarkerClusterer load error:', error);
    console.log('='.repeat(60));
    
    // Provide user feedback about clustering library failure
    showError('Clustering library failed to load. Maps will display individual markers only.', 'warning', 8000);
    
    // Set a global flag to indicate clustering is unavailable
    window.clusteringUnavailable = true;
    
    loadGoogleMaps();
  };
  document.head.appendChild(clustererScript);
});

function loadGoogleMaps() {
  console.log('='.repeat(60));
  console.log('DEBUG: LOADING GOOGLE MAPS API');
  console.log('='.repeat(60));
  console.log('DEBUG: Creating Google Maps script element');
  
  // Set up timeout for Google Maps loading
  let mapsTimeout = setTimeout(function() {
    console.error('DEBUG: Google Maps API loading timeout');
    showError('Google Maps API is taking too long to load. Please check your internet connection and refresh the page.', 'error', 15000);
    window.googleMapsUnavailable = true;
  }, 15000); // 15 second timeout for Google Maps
  
  const script = document.createElement('script');
  script.src = 'https://maps.googleapis.com/maps/api/js?key={{api_key}}&callback=initMap';
  script.async = true;
  script.defer = true;
  script.onload = function() {
    clearTimeout(mapsTimeout); // Cancel timeout
    console.log('DEBUG: Google Maps API loaded successfully');
    console.log('DEBUG: typeof google:', typeof google);
    console.log('DEBUG: google.maps available:', !!(google && google.maps));
  };
  script.onerror = function(error) {
    clearTimeout(mapsTimeout); // Cancel timeout
    console.error('DEBUG: Failed to load Google Maps API');
    console.error('DEBUG: Google Maps load error:', error);
    showError('Failed to load Google Maps API. Please check your internet connection and try refreshing the page.', 'error', 10000);
    
    // Set a global flag to indicate Google Maps is unavailable
    window.googleMapsUnavailable = true;
  };
  console.log('DEBUG: Appending Google Maps script to head');
  document.head.appendChild(script);
  console.log('='.repeat(60));
}
</script>
</body>
</html>
"""

@app.route("/generate_custom_pin_svg")
def generate_custom_pin_svg():
    """Generate a custom pin SVG with specified color and type."""
    try:
        pin_type = request.args.get("type", "sphere")
        color = request.args.get("color", "#0056b8")
        number = request.args.get("number", "1")
        
        # Validate and sanitize color input
        if not color.startswith("#") or len(color) != 7:
            color = "#0056b8"  # Default fallback
        
        # Validate pin type
        if pin_type not in ["sphere", "number"]:
            pin_type = "sphere"
        
        if pin_type == "sphere":
            # Generate gradient colors with error handling
            try:
                r = int(color[1:3], 16)
                g = int(color[3:5], 16) 
                b = int(color[5:7], 16)
                r_light = min(255, r + 60)
                g_light = min(255, g + 60)
                b_light = min(255, b + 60)
                light_color = f"#{r_light:02x}{g_light:02x}{b_light:02x}"
            except ValueError:
                light_color = "#4080ff"  # Fallback light color
                
            svg_content = f'''<svg width="50" height="50" viewBox="0 0 75 75" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <radialGradient id="pinGradient_{hash(color)}" cx="30%" cy="30%" r="50%">
      <stop offset="0%" stop-color="{light_color}"/>
      <stop offset="100%" stop-color="{color}"/>
    </radialGradient>
  </defs>
  <circle cx="37.5" cy="25" r="15" fill="url(#pinGradient_{hash(color)})" stroke="#333" stroke-width="1"/>
  <circle cx="32" cy="20" r="4" fill="#ffffff" fill-opacity="0.4" />
  <path d="M37.5 40 L37.5 50" stroke="#666" stroke-width="3" stroke-linecap="round" />
</svg>'''
        else:  # number pin
            try:
                r = int(color[1:3], 16)
                g = int(color[3:5], 16)
                b = int(color[5:7], 16)
                r_stroke = min(255, r + 80)
                g_stroke = min(255, g + 80)
                b_stroke = min(255, b + 80)
                stroke_color = f"#{r_stroke:02x}{g_stroke:02x}{b_stroke:02x}"
            except ValueError:
                stroke_color = "#4080ff"  # Fallback stroke color
                
            # Sanitize number input
            try:
                num_val = int(number)
                if num_val < 1 or num_val > 99:
                    number = "1"
            except (ValueError, TypeError):
                number = "1"
                
            svg_content = f'''<svg xmlns="http://www.w3.org/2000/svg" width="50" height="60" viewBox="0 0 50 60">
  <g transform="translate(0,2)">
    <path fill="{color}" stroke="{stroke_color}" stroke-width="2"
          d="M25,0
             C15.558,0 8,7.558 8,17
             c0 12.75 17,30 17,30
             s17-17.25 17-30
             c0-9.442-7.558-17-17-17z" />
    <circle cx="25" cy="17" r="12" fill="#ffffff"/>
    <text x="25" y="22" text-anchor="middle" font-size="11" font-family="Arial, sans-serif"
          font-weight="bold" fill="#000000">{number}</text>
  </g>
</svg>'''
        
        return Response(svg_content, mimetype="image/svg+xml", headers={
            'Cache-Control': 'public, max-age=3600',  # Cache for 1 hour
            'Content-Type': 'image/svg+xml'
        })
        
    except Exception as e:
        print(f"Error generating SVG pin: {e}")
        # Return a simple fallback SVG
        fallback_svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="50" height="60" viewBox="0 0 50 60">
  <circle cx="25" cy="25" r="15" fill="#0056b8" stroke="#003d82" stroke-width="2"/>
  <circle cx="20" cy="20" r="4" fill="#ffffff" fill-opacity="0.4"/>
  <path d="M25 40 L25 50" stroke="#666" stroke-width="3" stroke-linecap="round"/>
</svg>'''
        return Response(fallback_svg, mimetype="image/svg+xml")

@app.route("/google_maps", methods=["GET", "POST"])
def google_maps_form():
    if request.method == "GET":
        return render_template('upload_form_google.html')

    elif request.method == "POST":
        uploaded_file = request.files.get("file")
        if not uploaded_file:
            return Response("Error: No file uploaded.", status=400)
        
        filename = uploaded_file.filename
        if not filename:
            return Response("Error: Uploaded file has no filename.", status=400)
        
        # Read file with better error handling
        try:
            if filename.lower().endswith(".csv"):
                df = pd.read_csv(io.StringIO(uploaded_file.read().decode("utf-8")))
                print(f"Successfully read CSV file with {len(df)} rows")
            elif filename.lower().endswith((".xls", ".xlsx")):
                df = pd.read_excel(uploaded_file)
                print(f"Successfully read Excel file with {len(df)} rows")
            else:
                return Response("Error: Only .csv, .xls, or .xlsx files are supported.", status=400)
        except UnicodeDecodeError as e:
            return Response(f"Error: File encoding issue. Please save your CSV file with UTF-8 encoding. Details: {e}", status=400)
        except Exception as e:
            return Response(f"Error reading file: {str(e)}. Please check your file format and try again.", status=400)
        
        # Validate data quality
        if len(df) == 0:
            return Response("Error: The uploaded file is empty. Please upload a file with location data.", status=400)
        
        # Check required columns with detailed feedback
        required_cols = {"Location Name", "ZIP/Postal Code", "Electrification Candidates"}
        missing_cols = required_cols - set(df.columns)
        if missing_cols:
            return Response(f"Error: Missing required columns: {', '.join(missing_cols)}. Your file must contain: {', '.join(sorted(required_cols))}", status=400)

        # Add Category Name column if it doesn't exist
        if 'Category Name' not in df.columns:
            df['Category Name'] = 'Default'
        else:
            df['Category Name'] = df['Category Name'].astype(str).fillna('Default')
        
        categories = sorted(df['Category Name'].unique())
        
        # Get form data
        custom_colors = {
            "Group 1": request.form.get("group1_color", "#0056b8"),
            "Group 2": request.form.get("group2_color", "#00a1e0"),
            "Group 3": request.form.get("group3_color", "#a1d0f3")
        }
        clustering_enabled = request.form.get("clustering_enabled") == 'on'
        show_labels = request.form.get("show_labels") == 'on'
        
        # Store data for next step
        session_data = {
            'csv_data': df.to_json(),
            'clustering_enabled': clustering_enabled,
            'show_labels': show_labels,
            'custom_colors': custom_colors
        }
        
        # If multiple categories, show pin assignment page
        if len(categories) > 1:
            return render_template('google_pin_assignment.html', categories=categories, session_data=json.dumps(session_data))
        else:
            # Single category - generate map directly
            pin_assignments = {'Default': {'type': 'sphere', 'color': '#00a1e0'}}
            return generate_google_map_from_data(df, pin_assignments, clustering_enabled, show_labels, custom_colors)

@app.route("/generate_google_map", methods=["POST"])
@csrf.exempt  # Temporarily exempt from CSRF for testing
def generate_google_map():
    session_data_str = request.form.get('session_data')
    if not session_data_str:
        return Response("Error: No session data provided.", status=400)
    
    try:
        session_data = json.loads(session_data_str)
        df = pd.read_json(io.StringIO(session_data['csv_data']))
        clustering_enabled = session_data['clustering_enabled']
        show_labels = session_data.get('show_labels', True)  # Default to True for backward compatibility
        custom_colors = session_data['custom_colors']
        
    except Exception as e:
        return Response(f"Error parsing session data: {e}", status=400)
    
    # Get pin assignments from form
    pin_assignments = {}
    for key, value in request.form.items():
        if key.startswith("pin_type_"):
            category = key[9:]  # Remove "pin_type_" prefix
            if category not in pin_assignments:
                pin_assignments[category] = {}
            pin_assignments[category]['type'] = value
        elif key.startswith("pin_color_"):
            category = key[10:]  # Remove "pin_color_" prefix
            if category not in pin_assignments:
                pin_assignments[category] = {}
            pin_assignments[category]['color'] = value
    
    return generate_google_map_from_data(df, pin_assignments, clustering_enabled, show_labels, custom_colors)

def generate_google_map_from_data(df, pin_assignments, clustering_enabled, show_labels, custom_colors):
    """Generate Google Map from processed data"""
    
    # Format ZIP codes
    def format_zip(value):
        if pd.isna(value) or value == "":
            return ""
        try:
            return f"{int(float(value)):05d}"
        except (ValueError, TypeError):
            return str(value)
    
    df["ZIP/Postal Code"] = df["ZIP/Postal Code"].apply(format_zip)
    
    # Add missing columns
    for optional_col in ["Street Address", "City", "State"]:
        if optional_col not in df.columns:
            df[optional_col] = ""
        else:
            df[optional_col] = df[optional_col].fillna("")
    
    # Helper function to build address string
    def build_address_string(row):
        parts = []
        if row.get("Street Address", "").strip():
            parts.append(row["Street Address"].strip())
        if row.get("City", "").strip():
            parts.append(row["City"].strip())
        if row.get("State", "").strip():
            parts.append(row["State"].strip())
        if row.get("ZIP/Postal Code", "").strip():
            parts.append(row["ZIP/Postal Code"].strip())
        
        if parts:
            return ", ".join(parts)
        return ""

    # Geocode locations using the official Google Maps client with improved tracking
    lat_list, lon_list = [], []
    geocoding_stats = {"full_address": 0, "zip_only": 0, "state_centroid": 0, "failed": 0}
    api_key = GOOGLE_MAPS_API_KEY
    if not api_key or api_key == "YOUR_GOOGLE_MAPS_API_KEY":
        print("FATAL: Google Maps API key is not configured in the .env file.")
        return Response("Server configuration error: Google Maps API key is missing. Please contact the administrator.", status=500)

    gmaps = googlemaps.Client(key=api_key)

    for counter, (idx, row) in enumerate(df.iterrows(), 1):
        lat, lon = None, None # Reset lat/lon for each row
        location_name = str(row.get("Location Name", f"Location {counter}"))
        
        try:
            addr_str = build_address_string(row)

            # Primary: Try full address geocoding
            if addr_str:
                geocode_result = gmaps.geocode(addr_str)
                if geocode_result:
                    loc = geocode_result[0]['geometry']['location']
                    lat, lon = loc['lat'], loc['lng']
                    geocoding_stats["full_address"] += 1

            # Fallback 1: ZIP only if the full address failed
            if lat is None and row.get("ZIP/Postal Code", "").strip():
                zip_addr = f"{row['ZIP/Postal Code']}, USA"
                geocode_result = gmaps.geocode(zip_addr)
                if geocode_result:
                    loc = geocode_result[0]['geometry']['location']
                    lat, lon = loc['lat'], loc['lng']
                    geocoding_stats["zip_only"] += 1
                    print(f"Used ZIP fallback for {location_name}")

            # Fallback 2: State centroid
            if lat is None and row.get("State", "").strip():
                state_abbr = row["State"].strip()
                if state_abbr in us_states["StateAbbr"].values:
                    state_geom = us_states[us_states["StateAbbr"] == state_abbr].geometry.iloc[0]
                    centroid = state_geom.centroid
                    lat, lon = centroid.y, centroid.x
                    geocoding_stats["state_centroid"] += 1
                    print(f"Used state centroid fallback for {location_name} in {state_abbr}")
            
            # Final check for complete failure
            if lat is None or lon is None:
                geocoding_stats["failed"] += 1
                print(f"Complete geocoding failure for {location_name} with address: '{addr_str}'")

        except Exception as e:
            geocoding_stats["failed"] += 1
            print(f"Geocoding exception for {location_name}: {e}")
            pass

        lat_list.append(lat)
        lon_list.append(lon)

    df["Latitude"] = lat_list
    df["Longitude"] = lon_list
    
    # Log detailed geocoding statistics
    total_locations = len(df)
    successful_geocoding = sum(1 for lat in lat_list if lat is not None)
    print(f"Geocoding complete: {successful_geocoding}/{total_locations} locations processed")
    print(f"Geocoding breakdown - Full address: {geocoding_stats['full_address']}, ZIP only: {geocoding_stats['zip_only']}, State centroid: {geocoding_stats['state_centroid']}, Failed: {geocoding_stats['failed']}")
    
    if geocoding_stats["failed"] > 0:
        print(f"Warning: {geocoding_stats['failed']} locations could not be geocoded and will not appear on the map")
    
    # Create pins with improved error handling
    pins = []
    pin_creation_errors = 0
    
    for index, row in df.iterrows():
        try:
            lat, lon = row["Latitude"], row["Longitude"]
            
            # Check if coordinates are valid
            if pd.notnull(lat) and pd.notnull(lon) and not pd.isna(lat) and not pd.isna(lon):
                # Ensure coordinates are numeric
                lat_float = float(lat)
                lon_float = float(lon)
                
                # Basic coordinate validation (rough bounds for Earth)
                if -90 <= lat_float <= 90 and -180 <= lon_float <= 180:
                    category = row.get("Category Name", "Default")
                    pin_config = pin_assignments.get(category, {'type': 'sphere', 'color': '#00a1e0'})
                    
                    # Ensure pin_config has required keys
                    if not isinstance(pin_config, dict):
                        pin_config = {'type': 'sphere', 'color': '#00a1e0'}
                    if 'type' not in pin_config:
                        pin_config['type'] = 'sphere'
                    if 'color' not in pin_config:
                        pin_config['color'] = '#00a1e0'
                    
                    # Create the pin
                    pin = {
                        "lat": lat_float,
                        "lng": lon_float,
                        "label": str(row.get("Location Name", f"Location {index + 1}")),
                        "electrification_candidates": str(row.get("Electrification Candidates", "0")),
                        "category": category,
                        "icon_url": f"/generate_custom_pin_svg?type={pin_config['type']}&color={pin_config['color'].replace('#', '%23')}"
                    }
                    pins.append(pin)
                else:
                    print(f"Invalid coordinates for row {index}: lat={lat_float}, lng={lon_float}")
                    pin_creation_errors += 1
            else:
                print(f"Missing or null coordinates for row {index}: lat={lat}, lng={lon}")
                pin_creation_errors += 1
                
        except Exception as e:
            print(f"Error creating pin for row {index}: {e}")
            pin_creation_errors += 1
            continue
    
    print(f"Created {len(pins)} pins successfully, {pin_creation_errors} errors")
    
    # Create state polygons with improved error handling
    state_polygons = []
    for _, row in us_states.iterrows():
        try:
            color = custom_colors.get(row.get("CaaS Group"), "#cccccc")
            geom = row["geometry"]
            
            if pd.isna(geom) or geom is None:
                continue
                
            paths = []
            if geom.geom_type == "Polygon":
                # Convert exterior coordinates to lat/lng format
                coords = list(geom.exterior.coords)
                if len(coords) > 2:  # Need at least 3 points for a polygon
                    path = [{"lat": float(y), "lng": float(x)} for x, y in coords]
                    paths = [path]
            elif geom.geom_type == "MultiPolygon":
                # Handle multiple polygons
                for poly in geom.geoms:
                    coords = list(poly.exterior.coords)
                    if len(coords) > 2:
                        path = [{"lat": float(y), "lng": float(x)} for x, y in coords]
                        paths.append(path)
            else:
                continue
            
            if paths:  # Only add if we have valid paths
                state_polygons.append({
                    "paths": paths,
                    "color": color,
                    "state": row.get("StateAbbr", "Unknown")
                })
        except Exception as e:
            print(f"Error processing state polygon for {row.get('StateAbbr', 'Unknown')}: {e}")
            continue
    
    print(f"Created {len(state_polygons)} state polygons")
    
    # Store map data with validation
    map_id = str(uuid.uuid4())
    
    # Validate data before storing
    if not pins:
        print("Warning: No valid pins created for map")
    if not state_polygons:
        print("Warning: No state polygons created for map")
    
    MAP_DATA[map_id] = {
        "pins": pins,
        "state_polygons": state_polygons,
        "clustering_enabled": clustering_enabled,
        "show_labels": show_labels,
        "group_colors": custom_colors,
        "created_at": time.time()
    }
    
    print(f"Stored map data with ID {map_id}: {len(pins)} pins, {len(state_polygons)} polygons")
    
    # Return improved success message with progress indicator
    return Response(f'''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Generating Map...</title>
        <style>
            body {{ font-family: Calibri, sans-serif; background: #f4f7fa; margin: 0; padding: 20px; }}
            .container {{ max-width: 600px; margin: 50px auto; background: #fff; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); padding: 40px; text-align: center; }}
            .spinner {{ border: 4px solid #f3f3f3; border-top: 4px solid #0056b8; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 20px auto; }}
            @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
            .status {{ font-size: 18px; color: #333; margin: 20px 0; }}
            .details {{ font-size: 14px; color: #666; }}
            .progress-bar {{ width: 100%; height: 6px; background: #f0f0f0; border-radius: 3px; margin: 20px 0; overflow: hidden; }}
            .progress-fill {{ height: 100%; background: linear-gradient(90deg, #0056b8, #00a1e0); animation: progress 3s ease-in-out infinite; }}
            @keyframes progress {{ 0% {{ width: 30%; }} 50% {{ width: 70%; }} 100% {{ width: 90%; }} }}
        </style>
        <meta http-equiv="refresh" content="2;url=/google_map/{map_id}">
    </head>
    <body>
        <div class="container">
            <div class="spinner"></div>
            <div class="status"><strong>Generating Your Map...</strong></div>
            <div class="progress-bar"><div class="progress-fill"></div></div>
            <div class="details">
                <p>Processing {len(pins)} locations with geocoding and map rendering.</p>
                <p>This may take a moment. You will be redirected automatically when ready.</p>
                <p><small>Clustering: {'Enabled' if clustering_enabled else 'Disabled'}</small></p>
            </div>
        </div>
    </body>
    </html>
    ''', mimetype="text/html")

def ensure_boolean_type(value, default=False):
    """
    FIXED: Utility function to ensure a value is a proper boolean type
    for template injection. This prevents double JSON encoding issues.
    """
    if isinstance(value, bool):
        return value
    elif value is None:
        return default
    elif isinstance(value, str):
        return value.lower() in ('true', '1', 'yes', 'on')
    else:
        return bool(value)

@app.route("/google_map/<map_id>")
def serve_google_map(map_id):
    """Serve a Google map by ID"""
    try:
        data = MAP_DATA.get(map_id)
        if not data:
            return Response("Map not found. The map may have expired or the link is invalid.", status=404)
        
        # Validate API key
        if not GOOGLE_MAPS_API_KEY or GOOGLE_MAPS_API_KEY == "YOUR_GOOGLE_MAPS_API_KEY":
            return Response("Google Maps API key is not configured. Please contact the administrator.", status=500)
        
        # Log map serving
        print(f"Serving map {map_id} with {len(data.get('pins', []))} pins and {len(data.get('state_polygons', []))} polygons")
        
        # Ensure all required data exists
        pins = data.get("pins", [])
        state_polygons = data.get("state_polygons", [])
        clustering_enabled = data.get("clustering_enabled", False)
        show_labels = data.get("show_labels", True)
        group_colors = data.get("group_colors", GROUP_COLORS)
        
        # DEBUG: Enhanced logging for template rendering values
        print("=" * 60)
        print("DEBUG: TEMPLATE RENDERING - serve_google_map()")
        print("=" * 60)
        print(f"DEBUG: Serving map_id: {map_id}")
        print(f"DEBUG: Retrieved from MAP_DATA:")
        print(f"DEBUG: - clustering_enabled: {data.get('clustering_enabled')} (type: {type(data.get('clustering_enabled'))})")
        print(f"DEBUG: - show_labels: {data.get('show_labels')} (type: {type(data.get('show_labels'))})")
        print(f"DEBUG: Template rendering clustering_enabled: {clustering_enabled}")
        print(f"DEBUG: Template rendering clustering_enabled type: {type(clustering_enabled)}")
        print(f"DEBUG: Template rendering clustering_enabled JSON: {json.dumps(clustering_enabled)}")
        print(f"DEBUG: Template rendering show_labels: {show_labels}")
        print(f"DEBUG: Template rendering show_labels type: {type(show_labels)}")
        print(f"DEBUG: Template rendering show_labels JSON: {json.dumps(show_labels)}")
        print(f"DEBUG: Template rendering pins count: {len(pins)}")
        print(f"DEBUG: Template rendering state_polygons count: {len(state_polygons)}")
        print(f"DEBUG: Template rendering group_colors: {group_colors}")
        print(f"DEBUG: Template variable injection test:")
        print(f"DEBUG: - clustering_enabled|tojson would render: {json.dumps(clustering_enabled)}")
        print(f"DEBUG: - show_labels|tojson would render: {json.dumps(show_labels)}")
        print("=" * 60)
        
        # FIXED: Ensure proper boolean type conversion for template injection
        original_clustering = clustering_enabled
        original_show_labels = show_labels
        
        clustering_enabled = ensure_boolean_type(clustering_enabled, False)
        show_labels = ensure_boolean_type(show_labels, True)
        
        # Log any conversions that were needed
        if original_clustering != clustering_enabled or type(original_clustering) != type(clustering_enabled):
            print(f"DEBUG: FIXED - clustering_enabled converted from {original_clustering} ({type(original_clustering)}) to {clustering_enabled} ({type(clustering_enabled)})")
        
        if original_show_labels != show_labels or type(original_show_labels) != type(show_labels):
            print(f"DEBUG: FIXED - show_labels converted from {original_show_labels} ({type(original_show_labels)}) to {show_labels} ({type(show_labels)})")
        
        # FIXED: Pass boolean values directly to template (not JSON-encoded)
        # The template will handle JSON conversion with |tojson filter
        return render_template_string(
            GOOGLE_MAPS_EMBED_TEMPLATE,
            api_key=GOOGLE_MAPS_API_KEY,
            state_polygons=json.dumps(state_polygons),
            pins=json.dumps(pins),
            clustering_enabled=clustering_enabled,  # FIXED: Pass boolean directly
            show_labels=show_labels,  # FIXED: Pass boolean directly
            group_colors=group_colors
        )
        
    except Exception as e:
        print(f"Error serving map {map_id}: {e}")
        return Response(f"Error loading map: {str(e)}", status=500)

@app.route("/download_template")
def download_template():
    """Download Excel template"""
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

@app.route("/")
def index():
    """Root route redirects to Google Maps form"""
    return redirect("/google_maps")

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5051, debug=app.config.get('DEBUG', False))
