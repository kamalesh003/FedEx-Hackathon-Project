from flask import Flask, render_template, request, jsonify
import folium
import requests
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import time
import threading
import logging
from config import GRAPHHOPPER_API_KEY, OPENWEATHER_API_KEY, AQICN_API_KEY, TOM_TOM_API_KEY


# Flask app initialization
app = Flask(__name__)
geolocator = Nominatim(user_agent="real_time_route_optimizer")



# Global variables to track real-time location updates
current_location = None
stop_tracking = False
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




# Helper: Fetch real-time data (weather, air quality, traffic) with error handling
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





# Helper: Fetch route data with error handling
def fetch_route_data(start_coords, end_coords, vehicle_type):
    try:
        url = (
            f"https://graphhopper.com/api/1/route?point={start_coords[0]},{start_coords[1]}"
            f"&point={end_coords[0]},{end_coords[1]}&vehicle={vehicle_type}&locale=en"
            f"&key={GRAPHHOPPER_API_KEY}&points_encoded=false&algorithm=alternative_route&alternative_route=3"
        )
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"Error fetching route data: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching route data: {e}")
        return None





# Helper: Calculate emissions
def calculate_emissions(distance, vehicle_type, weather_data, aqi_data, traffic_data, load_factor):
    # Default emission factors (in grams of CO2 per kilometer)
    emission_factors = {'truck': 400,'small_truck':300,'car': 150,'bike':100}
    base_emission = emission_factors.get(vehicle_type, 150)  # Default to 'car' if not found

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
    return (distance / 1000) * adjusted_emissions  # Multiply by distance in km






# Helper: Plot real-time route map with markers for start, end, and current location
def plot_route_map(route_data, start_coords, end_coords, current_coords=None):
    m = folium.Map(location=start_coords, zoom_start=12)
    folium.Marker(start_coords, popup="Start", icon=folium.Icon(color='green')).add_to(m)
    folium.Marker(end_coords, popup="End", icon=folium.Icon(color='red')).add_to(m)

    if current_coords:
        folium.Marker(current_coords, popup="Current Location", icon=folium.Icon(color='blue')).add_to(m)

    for path in route_data.get('paths', []):
        coords = path.get('points', {}).get('coordinates', [])
        folium.PolyLine([(lat, lon) for lon, lat in coords], color="blue", weight=3).add_to(m)

    return m





# Real-time tracking thread with proper termination and error handling
def track_route(start_coords, end_coords, vehicle_type, load_factor):
    global current_location, stop_tracking, latest_updates
    current_location = start_coords
    while not stop_tracking:
        # Simulate movement towards destination
        lat_diff = (end_coords[0] - current_location[0]) / 10
        lon_diff = (end_coords[1] - current_location[1]) / 10
        current_location = (current_location[0] + lat_diff, current_location[1] + lon_diff)

        # Fetch real-time data for current location
        weather_data, aqi_data, traffic_data = fetch_real_time_data(*current_location)
        if not weather_data or not aqi_data or not traffic_data:
            logging.error("Failed to fetch real-time data for tracking.")
            break

        # Calculate emissions and scores for updated location
        emissions = calculate_emissions(1000, vehicle_type, weather_data, aqi_data, traffic_data, load_factor)

        # Update global latest updates dictionary
        latest_updates = {
            "location": current_location,
            "weather": weather_data,
            "emissions": emissions,
            "aqi": aqi_data,
            "traffic": traffic_data,
        }

        time.sleep(2)  # Update every 2 seconds





# Flask routes
@app.route('/', methods=['GET', 'POST'])
def home():
    global stop_tracking
    if request.method == 'POST':
        start_address = request.form['start_address']
        end_address = request.form['end_address']
        vehicle_type = request.form['vehicle_type']
        load_factor = float(request.form['load_factor'])

        start_coords = get_coordinates(start_address)
        end_coords = get_coordinates(end_address)

        if start_coords and end_coords:
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
    start_address = request.json.get('start_address')
    end_address = request.json.get('end_address')
    vehicle_type = request.json.get('vehicle_type')
    load_factor = request.json.get('load_factor')

    start_coords = get_coordinates(start_address)
    end_coords = get_coordinates(end_address)

    if start_coords and end_coords:
        route_data = fetch_route_data(start_coords, end_coords, vehicle_type)
        if route_data:
            stop_tracking = False
            threading.Thread(target=track_route, args=(start_coords, end_coords, vehicle_type, load_factor), daemon=True).start()
            return jsonify({
                "message": "Tracking started successfully.",
                "start_coords": start_coords,
                "end_coords": end_coords,
                "route_data": route_data
            })
        else:
            return jsonify({"error": "Failed to fetch route data."}), 500
    return jsonify({"error": "Invalid coordinates."}), 400



@app.route('/live-updates', methods=['GET'])
def live_updates():
    global latest_updates
    if latest_updates:
        return jsonify(latest_updates)
    return jsonify({"error": "No updates available yet."})

@app.route('/stop', methods=['POST'])
def stop():
    global stop_tracking
    stop_tracking = True
    return jsonify({"message": "Real-time tracking stopped."})


if __name__ == "__main__":
    app.run(debug=True)
