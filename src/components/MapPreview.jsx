import { useEffect, useRef } from "react";
import tour from "../data/tour_optimized.json";

const MapPreview = () => {
  const mapRef = useRef(null);
  const stops = tour.stops || [];

  useEffect(() => {
    const initMap = async () => {
      const fullStops = stops.filter((stop) => stop.coordinates);
      if (fullStops.length < 2) return;

      // Initialize the map without center/zoom — we’ll fit bounds manually
      const map = new window.google.maps.Map(mapRef.current, {
        mapId: "1bac80cbc0c75eb3",
        mapTypeControl: false,
        streetViewControl: false,
      });

      // Fit map to include all POIs
      const bounds = new window.google.maps.LatLngBounds();
      fullStops.forEach((stop) => {
        bounds.extend({
          lat: stop.coordinates.lat,
          lng: stop.coordinates.lon,
        });
      });
      map.fitBounds(bounds);

      const directionsService = new window.google.maps.DirectionsService();
      const directionsRenderer = new window.google.maps.DirectionsRenderer({
        suppressMarkers: true,
        preserveViewport: false, // allow auto-center based on route
        polylineOptions: {
          strokeColor: "#49454F",
          strokeOpacity: 0.8,
          strokeWeight: 5,
        },
      });

      directionsRenderer.setMap(map);

      const waypoints = fullStops.slice(1, -1).map((stop) => ({
        location: {
          lat: stop.coordinates.lat,
          lng: stop.coordinates.lon,
        },
        stopover: true,
      }));

      const result = await directionsService.route({
        origin: {
          lat: fullStops[0].coordinates.lat,
          lng: fullStops[0].coordinates.lon,
        },
        destination: {
          lat: fullStops[fullStops.length - 1].coordinates.lat,
          lng: fullStops[fullStops.length - 1].coordinates.lon,
        },
        waypoints,
        travelMode: window.google.maps.TravelMode.WALKING,
      });

      directionsRenderer.setDirections(result);

      fullStops.forEach((stop, index) => {
        const color =
          index === 0
            ? "#8C8CFF"
            : index === fullStops.length - 1
            ? "#787878"
            : "#49454F";

        const marker = new window.google.maps.marker.AdvancedMarkerElement({
          map,
          position: {
            lat: stop.coordinates.lat,
            lng: stop.coordinates.lon,
          },
          title: stop.name,
          content: createMarkerContent(index + 1, color),
        });

        marker.addEventListener("gmp-click", () => {
          alert(stop.name);
        });
      });
    };

    const createMarkerContent = (label, color) => {
      const div = document.createElement("div");
      div.innerText = label;
      Object.assign(div.style, {
        background: color,
        borderRadius: "50%",
        width: "30px",
        height: "30px",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "white",
        fontWeight: "bold",
        fontSize: "14px",
      });
      return div;
    };

    const loadGoogleMapsScript = () => {
      if (window.google && window.google.maps) {
        initMap();
        return;
      }

      if (document.querySelector('script[src*="maps.googleapis.com"]')) return;

      window.initMap = initMap;

      const script = document.createElement("script");
      script.src = `https://maps.googleapis.com/maps/api/js?key=${
        import.meta.env.VITE_GOOGLE_API_KEY
      }&callback=initMap&libraries=marker&v=beta&loading=async`;
      document.head.appendChild(script);
    };

    loadGoogleMapsScript();
  }, []);

  return <div ref={mapRef} style={{ height: "100%", width: "100%" }} />;
};

export default MapPreview;
