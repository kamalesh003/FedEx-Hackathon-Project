# Dynamic-Routing-Web-App
[WATCH MY PROJECT IN ACTION (CLICK HERE)](https://youtu.be/UAaNPMNGacE?si=Hn0j4mTli_z7fV-F)
# Real-Time Route Optimizer 🌍🚗  

A Flask-based web application that enables real-time route optimization using live data from multiple APIs. The application tracks routes dynamically, calculates emissions, and provides updates on weather, air quality, and traffic conditions.  

## Features 🚀  
- **Real-time Route Tracking:** Monitor route progress and update current location dynamically.  
- **Environmental Impact:** Calculate emissions based on vehicle type, weather, air quality, and traffic conditions.  
- **Interactive Map:** Visualize start, end, and current location along with the optimized route.  
- **Live Data Integration:**  
  - Weather updates via [OpenWeather API](https://openweathermap.org/api).  
  - Air Quality Index (AQI) updates via [AQICN API](https://aqicn.org/api/).  
  - Traffic conditions via [TomTom Traffic API](https://developer.tomtom.com/traffic-api).  
  - Route optimization via [GraphHopper API](https://www.graphhopper.com/).  

## Technologies Used 🛠  
- **Backend:** Flask  
- **Frontend:** HTML, Bootstrap, Folium for interactive maps) ,CSS ,Javascript [Single Page Application Approach] 
- **Geolocation:** Geopy  
- **Threading:** For real-time location updates  

## Prerequisites 🧰  
- Python 3.7+  
- API keys for:  
  - [OpenWeather API](https://openweathermap.org/api)  
  - [AQICN API](https://aqicn.org/api/)  
  - [TomTom Traffic API](https://developer.tomtom.com/traffic-api)  
  - [GraphHopper API](https://www.graphhopper.com/)  

## Installation ⚙️  

1. **Clone the Repository:**  
   ```bash  
   git clone https://github.com/your-username/real-time-route-optimizer.git  
   cd real-time-route-optimizer  

    Install Dependencies:

pip install -r requirements.txt  

Set API Keys:
Create a config.py file in the project directory and add your API keys:

GRAPHHOPPER_API_KEY = "your_graphhopper_api_key"  
OPENWEATHER_API_KEY = "your_openweather_api_key"  
AQICN_API_KEY = "your_aqicn_api_key"  
TOM_TOM_API_KEY = "your_tomtom_api_key"  

Run the Application:

    python app.py  

    Access the App:
    Open your browser and navigate to http://127.0.0.1:5000.

API Endpoints 🌐

    GET /
    Renders the homepage.
    POST /startTracking
    Starts real-time route tracking.
    GET /live-updates
    Fetches the latest updates, including emissions, weather, AQI, and traffic data.
    POST /stop
    Stops real-time tracking.

Usage 🗺️

    Enter the start and end addresses, select the vehicle type, and specify the load factor.
    View the optimized route on the interactive map.
    Get live updates on emissions, weather, AQI, and traffic.

Contributing 🤝

Contributions are welcome! Feel free to submit a pull request or report issues.
License 📜

This project is licensed under the MIT License. See the LICENSE file for details.
Acknowledgments 🙌

    Folium for map visualizations.
    Geopy for geocoding services.
    API providers for their valuable data services.
