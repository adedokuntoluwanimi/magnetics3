import {fetchMapsKey} from "../api.js";
import {appState, setMapsApiKey} from "../state.js";
import {loadScript} from "../shared/loaders.js";

let mapsPromise = null;
let _currentMap = null;
let _surveyMarkers = [];
let _predictedMarkers = [];
let _infoWindow = null;

const MAP_STYLES = {
  light: [
    {elementType: "geometry", stylers: [{color: "#f5f7f6"}]},
    {elementType: "labels.text.stroke", stylers: [{color: "#ffffff"}]},
    {elementType: "labels.text.fill", stylers: [{color: "#54636b"}]},
    {featureType: "road", elementType: "geometry", stylers: [{color: "#ffffff"}]},
    {featureType: "water", elementType: "geometry", stylers: [{color: "#cfe5ee"}]},
    {featureType: "poi", elementType: "geometry", stylers: [{color: "#e9f2ea"}]},
  ],
  muted: [
    {elementType: "geometry", stylers: [{color: "#eef1ef"}]},
    {elementType: "labels.text.stroke", stylers: [{color: "#f7f7f7"}]},
    {elementType: "labels.text.fill", stylers: [{color: "#6c7b70"}]},
    {featureType: "road", elementType: "geometry", stylers: [{color: "#dfe6e1"}]},
    {featureType: "water", elementType: "geometry", stylers: [{color: "#b8d6e2"}]},
    {featureType: "poi", elementType: "labels.text.fill", stylers: [{color: "#7b8a7f"}]},
  ],
  dark: [
    {elementType: "geometry", stylers: [{color: "#1d2320"}]},
    {elementType: "labels.text.stroke", stylers: [{color: "#1f2a24"}]},
    {elementType: "labels.text.fill", stylers: [{color: "#9ab3a1"}]},
    {featureType: "road", elementType: "geometry", stylers: [{color: "#2a322d"}]},
    {featureType: "water", elementType: "geometry", stylers: [{color: "#182028"}]},
    {featureType: "poi", elementType: "geometry", stylers: [{color: "#242b26"}]},
  ],
};

export function recolorSurveyMarkers(color) {
  _surveyMarkers.forEach((m) => {
    const icon = m.getIcon();
    m.setIcon({...icon, fillColor: color, strokeColor: color});
  });
}

export function recolorPredictedMarkers(color) {
  _predictedMarkers.forEach((m) => {
    const icon = m.getIcon();
    m.setIcon({...icon, strokeColor: color});
  });
}

function getBounds(points) {
  const bounds = new google.maps.LatLngBounds();
  points.forEach((point) => bounds.extend({lat: Number(point.latitude), lng: Number(point.longitude)}));
  return bounds;
}

function filterPredictedPoints(predictedPoints, measuredPoints) {
  if (!predictedPoints?.length || !measuredPoints?.length) return predictedPoints || [];
  const lats = measuredPoints.map((p) => Number(p.latitude)).filter((v) => Number.isFinite(v));
  const lons = measuredPoints.map((p) => Number(p.longitude)).filter((v) => Number.isFinite(v));
  if (!lats.length || !lons.length) return predictedPoints || [];
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);
  const latPad = Math.max((maxLat - minLat) * 0.05, 0.002);
  const lonPad = Math.max((maxLon - minLon) * 0.05, 0.002);
  return (predictedPoints || []).filter((p) => {
    const lat = Number(p.latitude);
    const lon = Number(p.longitude);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return false;
    if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return false;
    return lat >= minLat - latPad && lat <= maxLat + latPad && lon >= minLon - lonPad && lon <= maxLon + lonPad;
  });
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
  // Use getBoundingClientRect which returns the actual rendered size regardless of
  // how the height was set (flex, %, inline) — offsetHeight can be 0 on screens
  // that just became visible.
  const rect = container.getBoundingClientRect();
  const h = rect.height > 10 ? rect.height : (container.parentElement?.getBoundingClientRect().height || 400);
  container.style.height = h + "px";
  container.style.width = "100%";

  const center = validPoints[0]
    ? {lat: Number(validPoints[0].latitude), lng: Number(validPoints[0].longitude)}
    : {lat: 0, lng: 0};

  const map = new maps.Map(container, {
    mapTypeId: "roadmap",
    streetViewControl: false,
    fullscreenControl: false,
    mapTypeControl: false,
    gestureHandling: "greedy",
    center,
    zoom,
  });
  const mapTypeSelect = document.getElementById("mapTypeSelect");
  if (mapTypeSelect) {
    mapTypeSelect.value = map.getMapTypeId() || "roadmap";
    mapTypeSelect.onchange = () => {
      const choice = mapTypeSelect.value;
      if (MAP_STYLES[choice]) {
        map.setMapTypeId("roadmap");
        map.setOptions({styles: MAP_STYLES[choice]});
      } else {
        map.setOptions({styles: null});
        map.setMapTypeId(choice);
      }
    };
  }
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

  const safePredicted = filterPredictedPoints(predictedPoints, validPoints);
  safePredicted.slice(0, 600).forEach((point, idx) => {
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
    marker.addListener("click", () => {
      const magneticVal = Number(point.magnetic);
      const hasMag = Number.isFinite(magneticVal);
      _infoWindow.setContent(`
        <div style="font-family:'Manrope',sans-serif;font-size:12px;min-width:140px">
          <div style="font-weight:700;margin-bottom:6px;color:#071a0b">Predicted station #${idx + 1}</div>
          <div style="display:flex;justify-content:space-between;gap:12px;margin-bottom:3px"><span style="color:#5a8264">Latitude</span><span style="font-family:'JetBrains Mono',monospace;font-weight:600">${Number(point.latitude).toFixed(6)}</span></div>
          <div style="display:flex;justify-content:space-between;gap:12px"><span style="color:#5a8264">Longitude</span><span style="font-family:'JetBrains Mono',monospace;font-weight:600">${Number(point.longitude).toFixed(6)}</span></div>
          ${hasMag ? `<div style="display:flex;justify-content:space-between;gap:12px;border-top:1px solid #e0e0e0;padding-top:5px;margin-top:5px"><span style="color:#5a8264">Magnetic</span><span style="font-family:'JetBrains Mono',monospace;font-weight:700;color:#1a5f8c">${magneticVal.toFixed(2)} nT</span></div>` : ""}
        </div>
      `);
      _infoWindow.open(map, marker);
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
