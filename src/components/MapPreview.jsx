import { useEffect, useRef, useState } from "react";
const MAP_ID = "1bac80cbc0c75eb3";
const ACTIVE_COLOR = "#8C8CFF";
const VISITED_COLOR = "#92929C";
const DEFAULT_COLOR = "#3F3F43";
const START_COLOR = "#8C8CFF";
const END_COLOR = "#08080B";

export default function MapPreview({
  stops = [],
  userLocation,
  activeStop = 0,
  visitedStops = [],
  enableUserMarker = false,
}) {
  const mapRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const markerRefs = useRef([]);
  const userMarkerRef = useRef(null);
  const [mapReady, setMapReady] = useState(false);
  const [boundsCenter, setBoundsCenter] = useState(null);
  const [advancedMarkerElement, setAdvancedMarkerElement] = useState(null);
  const lastActiveStopRef = useRef(activeStop);

  // --- Google Maps Loader ---
  useEffect(() => {
    let cancelled = false;
    function checkGoogleMapsReady() {
      if (
        window.google &&
        window.google.maps &&
        window.google.maps.importLibrary
      ) {
        setMapReady(true);
        return true;
      }
      return false;
    }
    if (checkGoogleMapsReady()) return;
    if (!document.querySelector('script[src*="maps.googleapis.com"]')) {
      const script = document.createElement("script");
      script.src = `https://maps.googleapis.com/maps/api/js?key=${
        import.meta.env.VITE_GOOGLE_API_KEY
      }&libraries=marker&v=beta&loading=async`;
      script.async = true;
      document.head.appendChild(script);
    }
    const interval = setInterval(() => {
      if (cancelled) return;
      if (checkGoogleMapsReady()) clearInterval(interval);
    }, 50);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  // --- Load AdvancedMarkerElement Class ---
  useEffect(() => {
    let cancelled = false;
    async function loadMarkerClass() {
      if (
        window.google &&
        window.google.maps &&
        window.google.maps.importLibrary
      ) {
        const { AdvancedMarkerElement } =
          await window.google.maps.importLibrary("marker");
        if (!cancelled) {
          setAdvancedMarkerElement(() => AdvancedMarkerElement);
        }
      }
    }
    loadMarkerClass();
    return () => {
      cancelled = true;
    };
  }, [mapReady]);

  // --- Initialize the Map Once ---
  useEffect(() => {
    if (!mapReady || !mapRef.current || mapInstanceRef.current) return;
    if (!window.google || !window.google.maps || !window.google.maps.importLibrary) return;

    (async () => {
      const validStops = stops.filter(
        (s) => typeof s.lat === "number" && typeof s.lng === "number"
      );
      if (validStops.length < 2) return;
      const map = new window.google.maps.Map(mapRef.current, {
        mapId: MAP_ID,
        mapTypeControl: false,
        streetViewControl: false,
      });
      mapInstanceRef.current = map;

      // Fit bounds to all stops and remember the center
      const bounds = new window.google.maps.LatLngBounds();
      validStops.forEach((stop) =>
        bounds.extend({ lat: stop.lat, lng: stop.lng })
      );
      map.fitBounds(bounds);
      setBoundsCenter(bounds.getCenter());

      // Draw route once
      const directionsService = new window.google.maps.DirectionsService();
      const directionsRenderer = new window.google.maps.DirectionsRenderer({
        suppressMarkers: true,
        preserveViewport: true,
        polylineOptions: {
          strokeColor: "#49454F",
          strokeOpacity: 0.8,
          strokeWeight: 3,
        },
      });
      directionsRenderer.setMap(map);

      const waypoints = validStops.slice(1, -1).map((stop) => ({
        location: { lat: stop.lat, lng: stop.lng },
        stopover: true,
      }));

      const result = await directionsService.route({
        origin: { lat: validStops[0].lat, lng: validStops[0].lng },
        destination: {
          lat: validStops.at(-1).lat,
          lng: validStops.at(-1).lng,
        },
        waypoints,
        travelMode: window.google.maps.TravelMode.WALKING,
      });
      directionsRenderer.setDirections(result);

      // Draw initial markers if class is ready
      if (advancedMarkerElement) {
        updateMarkers(activeStop, visitedStops);
      }
    })();
    // eslint-disable-next-line
  }, [mapReady, advancedMarkerElement]);

  // --- Redraw all markers when relevant props change ---
  useEffect(() => {
    if (
      mapInstanceRef.current &&
      advancedMarkerElement
    ) {
      updateMarkers(activeStop, visitedStops);
    }
  }, [activeStop, visitedStops, stops, advancedMarkerElement]);

  // --- User Marker (optional, for live tour) ---
  useEffect(() => {
    if (
      enableUserMarker &&
      userLocation &&
      mapInstanceRef.current &&
      advancedMarkerElement
    ) {
      // Remove old marker
      if (userMarkerRef.current) userMarkerRef.current.map = null;
      userMarkerRef.current = new advancedMarkerElement({
        map: mapInstanceRef.current,
        position: userLocation,
        content: createUserMarkerContent(),
        zIndex: 2000,
      });
    }
    // eslint-disable-next-line
  }, [userLocation, enableUserMarker, mapReady, advancedMarkerElement]);

  // --- Pan the map to active pin ---
  useEffect(() => {
    if (
      mapInstanceRef.current &&
      stops[activeStop] &&
      typeof stops[activeStop].lat === "number" &&
      typeof stops[activeStop].lng === "number"
    ) {
      mapInstanceRef.current.panTo({
        lat: stops[activeStop].lat,
        lng: stops[activeStop].lng,
      });
      // Optionally zoom in:
      // mapInstanceRef.current.setZoom(17);
    }
  }, [activeStop, stops]);

  useEffect(() => {
  if (!mapInstanceRef.current || !stops.length) return;

  const validStops = stops.filter(
    (s) => typeof s.lat === "number" && typeof s.lng === "number"
  );
  if (validStops.length < 2) return;

  const bounds = new window.google.maps.LatLngBounds();
  validStops.forEach((stop) =>
    bounds.extend({ lat: stop.lat, lng: stop.lng })
  );
  mapInstanceRef.current.fitBounds(bounds);
  setBoundsCenter(bounds.getCenter());
}, [stops]);

  // --- Marker Update Helper ---
  function updateMarkers(activeStopIdx, visitedIdxs = []) {
    markerRefs.current.forEach((m) => m && m.setMap && m.setMap(null));
    markerRefs.current = [];
    stops.forEach((stop, index) => {
      if (typeof stop.lat !== "number" || typeof stop.lng !== "number") {
        markerRefs.current[index] = null;
        return;
      }
      let color = DEFAULT_COLOR;
      let zIndex = 1;
      if (index === 0) color = START_COLOR;
      if (index === stops.length - 1) color = END_COLOR;
      if (visitedIdxs.includes(index)) {
        color = VISITED_COLOR;
        zIndex = 10;
      }
      if (index === activeStopIdx) {
        color = ACTIVE_COLOR;
        zIndex = 1000;
      }
      const marker = new advancedMarkerElement({
        map: mapInstanceRef.current,
        position: { lat: stop.lat, lng: stop.lng },
        title: stop.name,
        content: createCircleSVG(index + 1, color, index === activeStopIdx),
        zIndex,
      });
      markerRefs.current[index] = marker;
    });
  }

  // --- SVG Circle Helper ---
  function createCircleSVG(label, color, isActive) {
    const size = isActive ? 44 : 34; // px
    const border = isActive ? 3 : 1.5;
    const radius = (size / 2) - border;
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("width", size);
    svg.setAttribute("height", size);
    svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
    svg.setAttribute("overflow", "visible");
    svg.style.display = "block";
    svg.setAttribute("data-key", `${label}-${color}-${isActive}-${Math.random()}`); // force unique DOM
    // Main circle
    const circle = document.createElementNS(ns, "circle");
    circle.setAttribute("cx", size / 2);
    circle.setAttribute("cy", size / 2);
    circle.setAttribute("r", radius);
    circle.setAttribute("fill", color);
    circle.setAttribute("stroke", isActive ? "#222" : "#aaa");
    circle.setAttribute("stroke-width", border);
    svg.appendChild(circle);
    // Text
    const text = document.createElementNS(ns, "text");
    text.setAttribute("x", "50%");
    text.setAttribute("y", "54%");
    text.setAttribute("text-anchor", "middle");
    text.setAttribute("dominant-baseline", "middle");
    text.setAttribute("font-size", isActive ? "16" : "13");
    text.setAttribute("fill", "#fff");
    text.setAttribute("font-weight", "bold");
    text.textContent = label;
    svg.appendChild(text);
    return svg;
  }

  // --- User Marker Content (Blue Dot) ---
  function createUserMarkerContent() {
    const el = document.createElement("div");
    el.style.width = "20px";
    el.style.height = "20px";
    el.style.background = "#1877F2";
    el.style.border = "2px solid #fff";
    el.style.borderRadius = "50%";
    el.style.boxShadow = "0 0 8px #1877F2cc";
    el.style.display = "block";
    return el;
  }

  // --- Center Button Handler ---
  const handleCenterMap = () => {
    if (mapInstanceRef.current && boundsCenter) {
      mapInstanceRef.current.panTo(boundsCenter);
      mapInstanceRef.current.setZoom(15);
    }
  };

  return (
    <div style={{ position: "relative", width: "100%", height: "100%", overflow:"hidden", }}>
      <div ref={mapRef} style={{ width: "100%", height: "100%", }} />
      
      {/* Center Button */}
      <button
        onClick={handleCenterMap}
        style={{
          position: "absolute",
          bottom: 16,
          right: 16,
          zIndex: 20,
          background: "#fff",
          border: "1.5px solid #333",
          borderRadius: "50%",
          width: 44,
          height: 44,
          boxShadow: "0 2px 10px #0002",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          cursor: "pointer",
        }}
        aria-label="Center Map"
      >
        <svg width={22} height={22} viewBox="0 0 22 22">
          <circle cx="11" cy="11" r="8" stroke="#333" strokeWidth="2" fill="none" />
          <circle cx="11" cy="11" r="2.7" fill="#8C8CFF" />
          <rect x="10.2" y="2.5" width="1.6" height="5" fill="#333" />
          <rect x="10.2" y="14.5" width="1.6" height="5" fill="#333" />
          <rect x="2.5" y="10.2" width="5" height="1.6" fill="#333" />
          <rect x="14.5" y="10.2" width="5" height="1.6" fill="#333" />
        </svg>
      </button>
    </div>
  );
}
