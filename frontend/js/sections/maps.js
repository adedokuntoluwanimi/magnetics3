import {fetchMapsKey} from "../api.js";
import {appState, setMapsApiKey} from "../state.js";
import {loadScript} from "../shared/loaders.js";

let mapsPromise = null;
let _currentMap = null;
let _surveyMarkers = [];
let _predictedMarkers = [];
let _infoWindow = null;

export function recolorSurveyMarkers(color) {
  _surveyMarkers.forEach((m) => {
    const icon = m.getIcon();
    m.setIcon({...icon, fillColor: color, strokeColor: color});
  });
}

function getBounds(points) {
  const bounds = new google.maps.LatLngBounds();
  points.forEach((point) => bounds.extend({lat: Number(point.latitude), lng: Number(point.longitude)}));
  return bounds;
}

export async function ensureGoogleMaps() {
  if (window.google?.maps) {
    return window.google.maps;
  }
  if (!mapsPromise) {
    mapsPromise = (async () => {
      const payload = appState.mapsApiKey ? {apiKey: appState.mapsApiKey} : await fetchMapsKey();
      if (!payload?.apiKey) {
        throw new Error("Google Maps API key is not configured.");
      }
      setMapsApiKey(payload.apiKey);
      const src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(payload.apiKey)}&libraries=visualization`;
      await loadScript(src);
      return window.google.maps;
    })();
  }
  return mapsPromise;
}

export async function renderStationMap(container, points, {weighted = false, zoom = 10, predictedPoints = []} = {}) {
  if (!container) {
    return null;
  }
  const maps = await ensureGoogleMaps();
  const validPoints = (points || []).filter((point) => Number.isFinite(Number(point.latitude)) && Number.isFinite(Number(point.longitude)));
  // Ensure container has explicit pixel dimensions before creating the map.
  // Parse inline style first — offsetHeight can be 0 if the screen just became visible.
  const parentStyleH = parseInt(container.parentElement?.style?.height, 10);
  const parentH = parentStyleH || container.parentElement?.offsetHeight || 300;
  container.style.height = parentH + "px";
  container.style.width = "100%";

  const center = validPoints[0]
    ? {lat: Number(validPoints[0].latitude), lng: Number(validPoints[0].longitude)}
    : {lat: 0, lng: 0};

  const map = new maps.Map(container, {
    mapTypeId: "roadmap",
    streetViewControl: false,
    fullscreenControl: false,
    mapTypeControl: true,
    gestureHandling: "greedy",
    center,
    zoom,
  });
  _currentMap = map;
  _surveyMarkers = [];
  _predictedMarkers = [];
  if (_infoWindow) { _infoWindow.close(); }
  _infoWindow = new maps.InfoWindow();

  if (!validPoints.length) {
    return map;
  }

  const bounds = getBounds(validPoints);
  // Trigger resize so tiles load correctly, then fit to survey bounds
  maps.event.addListenerOnce(map, "idle", () => {
    maps.event.trigger(map, "resize");
    map.fitBounds(bounds);
  });
  // Secondary resize after layout settles — catches white-tile edge cases
  setTimeout(() => {
    maps.event.trigger(map, "resize");
    if (validPoints.length) map.fitBounds(getBounds(validPoints));
  }, 600);
  validPoints.slice(0, 600).forEach((point) => {
    const marker = new maps.Marker({
      map,
      position: {lat: Number(point.latitude), lng: Number(point.longitude)},
      icon: {
        path: maps.SymbolPath.CIRCLE,
        scale: 4,
        fillColor: "#2daa52",
        fillOpacity: 0.8,
        strokeColor: "#114d23",
        strokeWeight: 1,
      },
      title: `${Number(point.magnetic || 0).toFixed(2)} nT`,
    });
    marker.addListener("click", () => {
      _infoWindow.setContent(`
        <div style="font-family:'Manrope',sans-serif;font-size:12px;min-width:140px">
          <div style="font-weight:700;margin-bottom:6px;color:#071a0b">Survey station</div>
          <div style="display:flex;justify-content:space-between;gap:12px;margin-bottom:3px"><span style="color:#5a8264">Latitude</span><span style="font-family:'JetBrains Mono',monospace;font-weight:600">${Number(point.latitude).toFixed(6)}</span></div>
          <div style="display:flex;justify-content:space-between;gap:12px;margin-bottom:3px"><span style="color:#5a8264">Longitude</span><span style="font-family:'JetBrains Mono',monospace;font-weight:600">${Number(point.longitude).toFixed(6)}</span></div>
          ${point.magnetic != null ? `<div style="display:flex;justify-content:space-between;gap:12px;border-top:1px solid #e0e0e0;padding-top:5px;margin-top:5px"><span style="color:#5a8264">Magnetic</span><span style="font-family:'JetBrains Mono',monospace;font-weight:700;color:#13401d">${Number(point.magnetic).toFixed(2)} nT</span></div>` : ""}
        </div>
      `);
      _infoWindow.open(map, marker);
    });
    _surveyMarkers.push(marker);
  });

  (predictedPoints || []).slice(0, 600).forEach((point) => {
    const marker = new maps.Marker({
      map,
      position: {lat: Number(point.latitude), lng: Number(point.longitude)},
      icon: {
        path: maps.SymbolPath.CIRCLE,
        scale: 5,
        fillColor: "transparent",
        fillOpacity: 0,
        strokeColor: "#5ba8d4",
        strokeWeight: 2,
      },
      title: "Predicted station",
    });
    _predictedMarkers.push(marker);
  });

  if (weighted && maps.visualization?.HeatmapLayer) {
    const heatmap = new maps.visualization.HeatmapLayer({
      map,
      radius: 24,
      opacity: 0.65,
      data: validPoints.slice(0, 1500).map((point) => ({
        location: new maps.LatLng(Number(point.latitude), Number(point.longitude)),
        weight: Math.abs(Number(point.magnetic || 1)),
      })),
    });
    heatmap.setMap(map);
  }
  return map;
}
