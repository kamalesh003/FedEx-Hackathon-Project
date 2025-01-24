from flask import Flask, render_template, request, jsonify
import folium
import requests
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import geopy.distance
import time
import threading
import logging
from config import GRAPHHOPPER_API_KEY, OPENWEATHER_API_KEY, AQICN_API_KEY, TOM_TOM_API_KEY
import math
import logging
# Flask app initialization
app = Flask(__name__)
geolocator = Nominatim(user_agent="real_time_route_optimizer")



# Global variables to track real-time location updates
current_location = None
stop_tracking = True
latest_updates = {}



# Set up logging
logging.basicConfig(level=logging.INFO)



# Helper: Get coordinates with retries and error handling
def get_coordinates(address, retries=3):
    for attempt in range(retries):
        try:
            location = geolocator.geocode(address, timeout=10)
            if location:
                return location.latitude, location.longitude
        except GeocoderTimedOut:
            logging.warning(f"Geocoder timed out, retrying ({attempt + 1}/{retries})...")
            if attempt < retries - 1:
                time.sleep(2)
    logging.error(f"Failed to geocode address: {address}")
    return None





# Helper: Fetch real-time data (weather, air quality, traffic)
def fetch_real_time_data(lat, lon):
    try:
        weather_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
        aqi_url = f"https://api.waqi.info/feed/geo:{lat};{lon}/?token={AQICN_API_KEY}"
        traffic_url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json?point={lat},{lon}&key={TOM_TOM_API_KEY}"

        weather_data = requests.get(weather_url).json()
        aqi_data = requests.get(aqi_url).json()
        traffic_data = requests.get(traffic_url).json()

        return weather_data, aqi_data, traffic_data
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching real-time data: {e}")
        return None, None, None





# Real-time route fetching with correct vehicle profile
def fetch_route_data(start_coords, end_coords, vehicle_type):
    try:
        # Ensure the vehicle_type is mapped to a valid GraphHopper profile
        vehicle_profiles = {
            'car_delivery': 'car_delivery',
            'truck': 'truck',
            'small_truck_delivery': 'small_truck_delivery',
            'bike':'bike'
        }
        
        # Default to 'car' if the vehicle type is unknown
        vehicle_profile = vehicle_profiles.get(vehicle_type)

        if not vehicle_profile:
            logging.error(f"Invalid vehicle type '{vehicle_type}' provided.")
            return None

        # Construct the URL for the GraphHopper API request
        url = (
            f"https://graphhopper.com/api/1/route?"
            f"point={start_coords[0]},{start_coords[1]}"
            f"&point={end_coords[0]},{end_coords[1]}"
            f"&vehicle={vehicle_profile}"  # Use the appropriate profile here
            f"&locale=en&key={GRAPHHOPPER_API_KEY}&points_encoded=false"
        )

        # Send the request to GraphHopper
        response = requests.get(url)
        
        # Check for successful response
        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"Error fetching route data from GraphHopper: {response.status_code} - {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching route data from GraphHopper: {e}")
        return None






# Emissions calculation based on vehicle type and real-time data
def calculate_emissions(distance, vehicle_type, weather_data, aqi_data, traffic_data, load_factor):
    # Define emission factors for different vehicle types
    emission_factors = {
        'truck': 400,  # Emission factor for a truck
        'small_truck': 300,  # Emission factor for a small truck
        'car_delivery': 150, 
        'bike': 80,
    }

    # Get base emission factor for the given vehicle type
    base_emission = emission_factors.get(vehicle_type, 150)  # Default to 'car_delivery' if not found

    # Ensure weather_data contains necessary fields, providing defaults where needed
    wind_speed = weather_data.get('wind', {}).get('speed', 0)  # Wind speed in m/s
    visibility = weather_data.get('visibility', 10000)  # Visibility in meters
    
    # Adjust weather emissions based on wind and visibility
    weather_adj = 1 + wind_speed * 0.03  # Adjust based on wind speed
    weather_adj += (1 - (visibility / 10000))  # Adjust based on visibility (scaled to [0,1])

    # Ensure AQI data contains the necessary 'aqi' field
    aqi = max(aqi_data.get('data', {}).get('aqi', 0), 0)  # Ensure non-negative AQI
    aqi_adj = 1 + (max(aqi - 50, 0) / 100)  # Adjust based on AQI (only if AQI > 50)

    # Ensure traffic data contains the necessary fields and handle invalid values
    traffic_speed = traffic_data.get('flowSegmentData', {}).get('currentSpeed', 50)  # Current traffic speed (default: 50)
    free_speed = traffic_data.get('flowSegmentData', {}).get('freeFlowSpeed', 50)  # Free-flow traffic speed (default: 50)

    # Prevent division by zero or invalid calculations
    if free_speed == 0:
        traffic_adj = 1  # Default to no adjustment if free_speed is zero (to avoid division by zero)
    else:
        traffic_adj = 1 + (1 - traffic_speed / free_speed)  # Adjust based on current vs. free-flow speed

    # Adjust emissions for load factor (handling the case where load_factor is invalid)
    if not isinstance(load_factor, (int, float)) or load_factor < 1:
        load_factor = 1  # Default to 1 if the load_factor is invalid

    load_adj = 1 + 0.1 * (load_factor - 1)  # Adjustment based on load factor

    # Calculate the final emissions
    adjusted_emissions = base_emission * weather_adj * aqi_adj * traffic_adj * load_adj

    # Return the emissions for the given distance (in kilometers)
    return (distance / 1000) * adjusted_emissions





def plot_route_map(route_data, start_coords, end_coords, current_coords=None):
    # Create a map centered on the starting coordinates
    m = folium.Map(location=start_coords, zoom_start=12)

    # Add markers for start and end points
    folium.Marker(start_coords, popup="Start", icon=folium.Icon(color='green')).add_to(m)
    folium.Marker(end_coords, popup="End", icon=folium.Icon(color='red')).add_to(m)

    # Optionally add a marker for the current location
    if current_coords:
        folium.Marker(current_coords, popup="Current Location", icon=folium.Icon(color='blue')).add_to(m)

    # Loop through the paths and plot them
    for path in route_data.get('paths', []):
        coords = path.get('points', {}).get('coordinates', [])
        # Convert coordinates from [longitude, latitude] to [latitude, longitude] for folium
        coords_lat_lon = [(lat, lon) for lon, lat in coords]
        folium.PolyLine(coords_lat_lon, color="blue", weight=3).add_to(m)

    return m





# Calculate estimated time based on traffic data
def calculate_estimated_time(distance, traffic_data, traffic_adjustment_factor=None):
    # Convert distance from meters to kilometers
    distance_km = distance / 1000.0

    # Get current and free-flow speeds, using default values if missing
    current_speed = traffic_data.get('flowSegmentData', {}).get('currentSpeed', 35)
    free_flow_speed = traffic_data.get('flowSegmentData', {}).get('freeFlowSpeed', 35)

    # Ensure speeds are non-zero to avoid division by zero
    if free_flow_speed == 0:
        free_flow_speed = 1  # Use 1 as a safe default to avoid division by zero

    # Calculate baseline time assuming free-flow speed
    baseline_time = (distance_km / free_flow_speed) * 60  # Time in minutes

    # Calculate the traffic ratio based on current speed vs. free-flow speed
    if free_flow_speed > 0:
        traffic_ratio = current_speed / free_flow_speed
    else:
        traffic_ratio = 1  # Default traffic ratio to 1 if free-flow speed is 0

    # Adjust time based on the traffic ratio (slow traffic will increase time)
    adjusted_time = baseline_time * (1 / traffic_ratio) if traffic_ratio > 0 else baseline_time

    # Apply traffic adjustment factor if provided, else use default of 1.1 (for safety margin)
    if traffic_adjustment_factor is None:
        traffic_adjustment_factor = 1.1  # Default safety factor if not provided

    adjusted_time *= traffic_adjustment_factor

    # Prevent overly short times by setting a reasonable minimum threshold 
    min_time = 5  # Minimum time threshold
    if adjusted_time < min_time:
        adjusted_time = min_time

    return adjusted_time






# Real-time tracking thread
def track_route(start_coords, end_coords, vehicle_type, load_factor):
    global current_location, stop_tracking, latest_updates
    current_location = start_coords
    total_distance = geopy.distance.distance(start_coords, end_coords).m

    # Map the vehicle_type to the appropriate GraphHopper profile
    vehicle_profiles = {
        'car_delivery': 'car_delivery',
        'truck': 'truck',
        'small_truck_delivery': 'small_truck_delivery',
         'bike':'bike'
    }

    vehicle_profile = vehicle_profiles.get(vehicle_type)

    if not vehicle_profile:
        logging.error(f"Invalid vehicle type '{vehicle_type}' provided. Stopping tracking.")
        stop_tracking = True
        return

    # Start tracking loop
    while not stop_tracking:
        # Calculate the movement towards the destination (1/10th of the remaining distance for each iteration)
        lat_diff = (end_coords[0] - current_location[0]) / 10
        lon_diff = (end_coords[1] - current_location[1]) / 10
        current_location = (current_location[0] + lat_diff, current_location[1] + lon_diff)

        # Fetch real-time data based on current location
        weather_data, aqi_data, traffic_data = fetch_real_time_data(*current_location)

        if not weather_data or not aqi_data or not traffic_data:
            logging.error("Failed to fetch real-time data for tracking.")
            break

        # Calculate emissions using the vehicle profile
        emissions = calculate_emissions(1000, vehicle_type, weather_data, aqi_data, traffic_data, load_factor)

        # Calculate remaining distance and estimated time
        remaining_distance = geopy.distance.distance(current_location, end_coords).m
        estimated_time = calculate_estimated_time(remaining_distance, traffic_data)

        # Ensure the estimated time and other relevant data are included in the updates
        latest_updates = {
            "location": current_location,
            "weather": weather_data,
            "emissions": emissions,
            "aqi": aqi_data,
            "traffic": traffic_data,
            "estimated_time": estimated_time  # Ensure estimated time is being updated
        }

        time.sleep(2)



@app.route('/', methods=['GET', 'POST'])
def home():
    global stop_tracking
    if request.method == 'POST':
        start_address = request.form['start_address']
        end_address = request.form['end_address']
        vehicle_type = request.form['vehicle_type']
        load_factor = float(request.form['load_factor'])

        # Validate vehicle_type
        if vehicle_type not in ['car_delivery', 'truck', 'small_truck_delivery','bike']:
            return render_template('index.html', error="Invalid vehicle type selected.")

        # Get coordinates for start and end addresses
        start_coords = get_coordinates(start_address)
        end_coords = get_coordinates(end_address)
        
        if start_coords and end_coords:
            # Fetch route data based on vehicle type
            route_data = fetch_route_data(start_coords, end_coords, vehicle_type)
            if route_data:
                stop_tracking = False
                threading.Thread(target=track_route, args=(start_coords, end_coords, vehicle_type, load_factor), daemon=True).start()
                route_map = plot_route_map(route_data, start_coords, end_coords, start_coords)
                return render_template('index.html', map_html=route_map._repr_html_())
            else:
                return render_template('index.html', error="Failed to fetch route data.")
        else:
            return render_template('index.html', error="Unable to fetch coordinates.")
    return render_template('index.html')

@app.route('/startTracking', methods=['POST'])
def start_tracking():
    global stop_tracking
    
    # Extracting the input data from the request
    start_address = request.json.get('start_address')
    end_address = request.json.get('end_address')
    vehicle_type = request.json.get('vehicle_type')
    load_factor = request.json.get('load_factor')

    # Validate vehicle_type
    if vehicle_type not in ['car_delivery', 'truck', 'small_truck_delivery','bike']:
        return jsonify({"error": "Invalid vehicle type."}), 400

    # Get coordinates for start and end addresses
    start_coords = get_coordinates(start_address)
    end_coords = get_coordinates(end_address)

    # Check if coordinates are valid
    if not start_coords or not end_coords:
        return jsonify({"error": "Invalid coordinates. Could not geocode addresses."}), 400

    # Fetch route data from GraphHopper based on vehicle type
    route_data = fetch_route_data(start_coords, end_coords, vehicle_type)
    
    if route_data:
        stop_tracking = False
        # Start the route tracking in a separate thread
        threading.Thread(target=track_route, args=(start_coords, end_coords, vehicle_type, load_factor), daemon=True).start()

        # Extract route coordinates from GraphHopper's response
        route_coords = route_data.get('paths', [])[0].get('points', {}).get('coordinates', [])
        
        if not route_coords:
            return jsonify({"error": "No valid route found."}), 500

        # Convert [lon, lat] to [lat, lon] as needed by Leaflet
        route_coords = [(lat, lon) for lon, lat in route_coords]

        # Fetch live data (weather, air quality, traffic) for the start location
        weather_data, aqi_data, traffic_data = fetch_real_time_data(start_coords[0], start_coords[1])

        # Check if real-time data is available
        if not weather_data or not aqi_data or not traffic_data:
            return jsonify({"error": "Failed to fetch real-time data."}), 500

        try:
            # Calculate emissions (using current distance, vehicle type, load factor, and real-time data)
            emissions = calculate_emissions(1000, vehicle_type, weather_data, aqi_data, traffic_data, load_factor)  # 1000 meters as an example
        except Exception as e:
            return jsonify({"error": f"Error calculating emissions: {str(e)}"}), 500

        # Ensure emissions value is valid
        if emissions is None:
            return jsonify({"error": "Failed to calculate emissions."}), 500

        # Calculate estimated time (using the real-time traffic data)
        remaining_distance = geopy.distance.distance(start_coords, end_coords).m
        estimated_time = calculate_estimated_time(remaining_distance, traffic_data)

        return jsonify({
            "message": "Tracking started successfully.",
            "start_coords": start_coords,
            "end_coords": end_coords,
            "route_coords": route_coords,  # Send route coordinates for frontend use
            "estimated_time": estimated_time,  # Estimated time in minutes
            "emissions": emissions  # Emissions in grams
        })
    else:
        return jsonify({"error": "Failed to fetch route data."}), 500




# Route for getting live updates (e.g., emissions, traffic, location)
@app.route('/live-updates', methods=['GET'])
def live_updates():
    global latest_updates
    # Check if the latest updates are available
    if latest_updates:
        return jsonify(latest_updates)  # Return the updates in JSON format
    return jsonify({"error": "No updates available yet."})  # Return an error message if no updates yet




# Route to stop the live tracking
@app.route('/stop', methods=['POST'])
def stop():
    global stop_tracking
    stop_tracking = True  # Set the flag to stop the tracking thread
    return jsonify({"message": "Real-time tracking stopped."})  # Return a success message




if __name__ == "__main__":
    app.run(debug=True)  # Start the Flask app with debug mode enabled
