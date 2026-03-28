import {fetchMapsKey} from "../api.js";
import {appState, setMapsApiKey} from "../state.js";
import {loadScript} from "../shared/loaders.js";

let mapsPromise = null;
let _currentMap = null;
let _surveyMarkers = [];
let _predictedMarkers = [];
let _baseStationMarkers = [];
let _infoWindow = null;

export function recolorSurveyMarkers(color) {
  _surveyMarkers.forEach((m) => {
    const icon = m.getIcon();
    m.setIcon({...icon, fillColor: color, strokeColor: color});
  });
}

export function recolorPredictedMarkers(color) {
  _predictedMarkers.forEach((m) => {
    const icon = m.getIcon();
    m.setIcon({...icon, strokeColor: color, fillColor: color});
  });
}

export function recolorBaseStationMarkers(color) {
  _baseStationMarkers.forEach((m) => {
    const icon = m.getIcon();
    m.setIcon({...icon, fillColor: color, strokeColor: darken(color)});
  });
}

function darken(hex) {
  try {
    const n = parseInt(hex.replace("#", ""), 16);
    const r = Math.max(0, ((n >> 16) & 0xff) - 60);
    const g = Math.max(0, ((n >> 8) & 0xff) - 60);
    const b = Math.max(0, (n & 0xff) - 60);
    return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
  } catch {
    return hex;
  }
}

// SVG paths for distinct predicted-point shapes
const SQUARE_PATH = "M -4,-4 L 4,-4 L 4,4 L -4,4 Z";   // explicit predicted target
const DIAMOND_PATH = "M 0,-6 L 5,0 L 0,6 L -5,0 Z";     // offset traverse
const TRIANGLE_DOWN = "M -5,-4 L 5,-4 L 0,5 Z";          // infill traverse

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
  const overlapThreshold = Math.max(Math.min(latPad, lonPad) * 0.18, 0.00008);
  return (predictedPoints || []).filter((p) => {
    const lat = Number(p.latitude);
    const lon = Number(p.longitude);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return false;
    if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return false;
    if (!(lat >= minLat - latPad && lat <= maxLat + latPad && lon >= minLon - lonPad && lon <= maxLon + lonPad)) return false;
    return !measuredPoints.some((measured) => {
      const mLat = Number(measured.latitude);
      const mLon = Number(measured.longitude);
      return Number.isFinite(mLat) && Number.isFinite(mLon)
        && Math.abs(mLat - lat) <= overlapThreshold
        && Math.abs(mLon - lon) <= overlapThreshold;
    });
  });
}

export async function ensureGoogleMaps() {
  if (window.google?.maps) return window.google.maps;
  if (!mapsPromise) {
    mapsPromise = (async () => {
      const payload = appState.mapsApiKey ? {apiKey: appState.mapsApiKey} : await fetchMapsKey();
      if (!payload?.apiKey) throw new Error("Google Maps API key is not configured.");
      setMapsApiKey(payload.apiKey);
      const src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(payload.apiKey)}&libraries=visualization`;
      await loadScript(src);
      for (let attempt = 0; attempt < 40; attempt += 1) {
        if (window.google?.maps) return window.google.maps;
        await new Promise((resolve) => window.setTimeout(resolve, 50));
      }
      throw new Error("Google Maps finished loading, but the Maps library is still unavailable.");
    })();
  }
  return mapsPromise;
}

export async function renderStationMap(
  container,
  points,
  {
    weighted = false,
    zoom = 10,
    predictedPoints = [],
    showLines = false,
    mapTypeSelectId = "mapTypeSelect",
    surveyColor = appState.mapColors.survey,
    predictedColor = appState.mapColors.predicted,
    baseStationColor = appState.mapColors.baseStation,
  } = {},
) {
  if (!container) return null;
  const maps = await ensureGoogleMaps();
  const validPoints = (points || []).filter(
    (p) => Number.isFinite(Number(p.latitude)) && Number.isFinite(Number(p.longitude)),
  );

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

  const mapTypeSelect = document.getElementById(mapTypeSelectId);
  if (mapTypeSelect) {
    mapTypeSelect.value = map.getMapTypeId() || "roadmap";
    mapTypeSelect.onchange = () => {
      map.setOptions({styles: null});
      map.setMapTypeId(mapTypeSelect.value || "roadmap");
    };
  }

  _currentMap = map;
  _surveyMarkers = [];
  _predictedMarkers = [];
  _baseStationMarkers = [];
  if (_infoWindow) _infoWindow.close();
  _infoWindow = new maps.InfoWindow();

  if (!validPoints.length) return map;

  const allBounds = getBounds(validPoints);
  maps.event.addListenerOnce(map, "idle", () => {
    maps.event.trigger(map, "resize");
    map.fitBounds(allBounds);
  });
  setTimeout(() => {
    maps.event.trigger(map, "resize");
    if (validPoints.length) map.fitBounds(getBounds(validPoints));
  }, 600);

  // Traverse polylines (disabled by default — overlay used for continuous surface)
  if (showLines) {
    const lineGroups = new Map();
    validPoints.forEach((p) => {
      const key = p.line_id != null ? String(p.line_id) : "all";
      if (!lineGroups.has(key)) lineGroups.set(key, []);
      lineGroups.get(key).push(p);
    });
    lineGroups.forEach((pts) => {
      if (pts.length < 2) return;
      new maps.Polyline({
        map,
        path: pts.map((p) => ({lat: Number(p.latitude), lng: Number(p.longitude)})),
        strokeColor: surveyColor,
        strokeOpacity: 0.55,
        strokeWeight: 1.5,
      });
    });
  }

  // Render measured + base station markers
  const bsColor = baseStationColor || "#e07b14";
  validPoints.slice(0, 800).forEach((point) => {
    const isBase = !!point.is_base_station;
    const valueLabel = point.display_label || "Value";
    const valueUnit = point.display_unit || "nT";
    const displayValue = Number.isFinite(Number(point.display_value))
      ? Number(point.display_value)
      : (point.magnetic != null ? Number(point.magnetic) : null);
    const showValue = displayValue != null && point.hide_value !== true;
    const pointKind = point.point_kind || (isBase ? "Base station" : "Measured data");

    const markerIcon = isBase
      ? {path: "M 0,-7 7,5 -7,5 Z", scale: 1, fillColor: bsColor, fillOpacity: 0.92, strokeColor: darken(bsColor), strokeWeight: 1.5}
      : {path: maps.SymbolPath.CIRCLE, scale: 4, fillColor: surveyColor, fillOpacity: 0.85, strokeColor: surveyColor, strokeWeight: 1};

    const marker = new maps.Marker({
      map,
      position: {lat: Number(point.latitude), lng: Number(point.longitude)},
      zIndex: isBase ? 3000 : 2200,
      icon: markerIcon,
      title: isBase ? "Base station" : pointKind,
    });
    marker.addListener("click", () => {
      const stationRow = point.station_number != null
        ? `<div style="display:flex;justify-content:space-between;gap:12px;margin-bottom:3px"><span style="color:#5a8264">Station</span><span style="font-family:'JetBrains Mono',monospace;font-weight:600">#${point.station_number}</span></div>` : "";
      _infoWindow.setContent(`
        <div style="font-family:'Manrope',sans-serif;font-size:12px;min-width:140px">
          <div style="font-weight:700;margin-bottom:6px;color:#071a0b">${isBase ? "Base station" : pointKind}</div>
          ${stationRow}
          <div style="display:flex;justify-content:space-between;gap:12px;margin-bottom:3px"><span style="color:#5a8264">Latitude</span><span style="font-family:'JetBrains Mono',monospace;font-weight:600">${Number(point.latitude).toFixed(6)}</span></div>
          <div style="display:flex;justify-content:space-between;gap:12px;margin-bottom:3px"><span style="color:#5a8264">Longitude</span><span style="font-family:'JetBrains Mono',monospace;font-weight:600">${Number(point.longitude).toFixed(6)}</span></div>
          ${showValue ? `<div style="display:flex;justify-content:space-between;gap:12px;border-top:1px solid #e0e0e0;padding-top:5px;margin-top:5px"><span style="color:#5a8264">${valueLabel}</span><span style="font-family:'JetBrains Mono',monospace;font-weight:700;color:${isBase ? darken(bsColor) : "#13401d"}">${displayValue.toFixed(2)} ${valueUnit}</span></div>` : ""}
          ${isBase ? `<div style="margin-top:5px;font-size:10px;color:${darken(bsColor)};font-weight:600">Used for diurnal correction</div>` : ""}
        </div>`);
      _infoWindow.open(map, marker);
    });
    if (isBase) _baseStationMarkers.push(marker);
    else _surveyMarkers.push(marker);
  });

  // Render predicted points with distinct shapes by type
  const safePredicted = filterPredictedPoints(predictedPoints, validPoints);
  safePredicted.slice(0, 1200).forEach((point, idx) => {
    const kind = point.point_kind || "offset";
    const traverseLabel = point.traverse_label || null;
    const stationNumber = point.station_number ?? idx + 1;
    const valueLabel = point.display_label || "Value";
    const valueUnit = point.display_unit || "nT";
    const displayValue = Number.isFinite(Number(point.display_value))
      ? Number(point.display_value)
      : (point.magnetic != null ? Number(point.magnetic) : null);

    let iconPath;
    if (kind === "predicted_target") iconPath = SQUARE_PATH;
    else if (kind === "infill") iconPath = TRIANGLE_DOWN;
    else iconPath = DIAMOND_PATH;

    const marker = new maps.Marker({
      map,
      position: {lat: Number(point.latitude), lng: Number(point.longitude)},
      zIndex: 1200,
      icon: {path: iconPath, scale: 1, fillColor: predictedColor, fillOpacity: 0.22, strokeColor: predictedColor, strokeWeight: 1.5},
      title: traverseLabel || "Predicted station",
    });
    marker.addListener("click", () => {
      const titleLine = traverseLabel || `Predicted station #${stationNumber}`;
      _infoWindow.setContent(`
        <div style="font-family:'Manrope',sans-serif;font-size:12px;min-width:140px">
          <div style="font-weight:700;margin-bottom:6px;color:#071a0b">${titleLine}</div>
          <div style="display:flex;justify-content:space-between;gap:12px;margin-bottom:3px"><span style="color:#5a8264">Latitude</span><span style="font-family:'JetBrains Mono',monospace;font-weight:600">${Number(point.latitude).toFixed(6)}</span></div>
          <div style="display:flex;justify-content:space-between;gap:12px"><span style="color:#5a8264">Longitude</span><span style="font-family:'JetBrains Mono',monospace;font-weight:600">${Number(point.longitude).toFixed(6)}</span></div>
          ${displayValue != null && point.hide_value !== true ? `<div style="display:flex;justify-content:space-between;gap:12px;border-top:1px solid #e0e0e0;padding-top:5px;margin-top:5px"><span style="color:#5a8264">${valueLabel}</span><span style="font-family:'JetBrains Mono',monospace;font-weight:700;color:${predictedColor}">${displayValue.toFixed(2)} ${valueUnit}</span></div>` : ""}
        </div>`);
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
        weight: Math.abs(Number(point.display_value ?? point.magnetic ?? 1)),
      })),
    });
    heatmap.setMap(map);
  }
  return map;
}
