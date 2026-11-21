import { useEffect, useRef, useState } from "react";

// Needs VITE_GOOGLE_MAPS_KEY in frontend/.env (same Cloud project as the Routes API).
let mapsPromise;
function loadMaps() {
  if (window.google?.maps) return Promise.resolve(window.google.maps);
  mapsPromise ??= new Promise((resolve, reject) => {
    window.__bpMapsReady = () => resolve(window.google.maps);
    const s = document.createElement("script");
    s.src = `https://maps.googleapis.com/maps/api/js?key=${import.meta.env.VITE_GOOGLE_MAPS_KEY}&callback=__bpMapsReady&v=weekly`;
    s.async = true;
    s.onerror = () => reject(new Error("Google Maps failed to load. Check the API key and referrer restrictions."));
    document.head.appendChild(s);
  });
  return mapsPromise;
}

// Standard encoded-polyline decoder, so no geometry library is needed.
export function decodePolyline(str = "") {
  const pts = [];
  let i = 0, lat = 0, lng = 0;
  while (i < str.length) {
    for (const axis of ["lat", "lng"]) {
      let shift = 0, result = 0, b;
      do {
        b = str.charCodeAt(i++) - 63;
        result |= (b & 0x1f) << shift;
        shift += 5;
      } while (b >= 0x20);
      const d = result & 1 ? ~(result >> 1) : result >> 1;
      if (axis === "lat") lat += d; else lng += d;
    }
    pts.push({ lat: lat / 1e5, lng: lng / 1e5 });
  }
  return pts;
}

export default function RouteMap({ steps = [] }) {
  const el = useRef(null);
  const map = useRef(null);
  const overlays = useRef([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    loadMaps()
      .then((maps) => {
        if (!alive || !el.current) return;
        map.current ??= new maps.Map(el.current, {
          center: { lat: 28.0587, lng: -82.4139 },
          zoom: 12,
          disableDefaultUI: true,
          zoomControl: true,
          clickableIcons: false,
        });
        overlays.current.forEach((o) => o.setMap(null));
        overlays.current = [];
        const bounds = new maps.LatLngBounds();

        steps.forEach((step) => {
          const path = decodePolyline(step.polyline);
          if (!path.length) return;
          path.forEach((p) => bounds.extend(p));
          const walking = step.mode !== "TRANSIT";
          const line = new maps.Polyline({
            map: map.current,
            path,
            geodesic: false,
            ...(walking
              ? {
                  strokeOpacity: 0,
                  icons: [{
                    icon: { path: "M 0,-1 0,1", strokeOpacity: 1, strokeColor: "#5B6B63", scale: 3 },
                    offset: "0",
                    repeat: "10px",
                  }],
                }
              : { strokeColor: step.color || "#006747", strokeOpacity: 0.95, strokeWeight: 6 }),
          });
          overlays.current.push(line);

          if (!walking) {
            [[path[0], step.from_stop], [path[path.length - 1], step.to_stop]].forEach(([pos, title]) => {
              overlays.current.push(new maps.Marker({
                map: map.current,
                position: pos,
                title,
                icon: {
                  path: maps.SymbolPath.CIRCLE,
                  scale: 6,
                  fillColor: "#fff",
                  fillOpacity: 1,
                  strokeColor: step.color || "#006747",
                  strokeWeight: 3,
                },
              }));
            });
          }
        });

        if (!bounds.isEmpty()) map.current.fitBounds(bounds, 48);
      })
      .catch((e) => alive && setError(e.message));
    return () => { alive = false; };
  }, [steps]);

  if (error) return <div className="rm-error" role="alert">{error}</div>;
  return <div ref={el} className="rm-map" aria-label="Bus route map" />;
}
