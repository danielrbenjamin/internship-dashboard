import {useEffect, useMemo, useRef, useState} from "react";
import L from "leaflet";
import "leaflet.markercluster";
import "leaflet/dist/leaflet.css";
import {api} from "./api";

type Point = [number, number];
type Country = Point[][][];
type City = [name: string, ascii: string, country: string, region: string, lat: number, lon: number, population: number];
type Role = {id: string; title: string; company: string; location: string};
type LocationGroup = {label: string; lat: number; lon: number; roles: Role[]};
type Region = "world" | "north-america";
const regionBounds: Record<Region, L.LatLngBoundsExpression> = {
  world: [[-57, -174], [77, 174]],
  "north-america": [[23, -136], [59, -57]],
};
const us = ("AL Alabama|AK Alaska|AZ Arizona|AR Arkansas|CA California|CO Colorado|CT Connecticut|DE Delaware|" +
  "DC District of Columbia|FL Florida|GA Georgia|HI Hawaii|ID Idaho|IL Illinois|IN Indiana|IA Iowa|KS Kansas|" +
  "KY Kentucky|LA Louisiana|ME Maine|MD Maryland|MA Massachusetts|MI Michigan|MN Minnesota|MS Mississippi|" +
  "MO Missouri|MT Montana|NE Nebraska|NV Nevada|NH New Hampshire|NJ New Jersey|NM New Mexico|NY New York|" +
  "NC North Carolina|ND North Dakota|OH Ohio|OK Oklahoma|OR Oregon|PA Pennsylvania|RI Rhode Island|" +
  "SC South Carolina|SD South Dakota|TN Tennessee|TX Texas|UT Utah|VT Vermont|VA Virginia|WA Washington|" +
  "WV West Virginia|WI Wisconsin|WY Wyoming").split("|");
const ca = [
  "01 AB Alberta", "02 BC British Columbia", "03 MB Manitoba", "04 NB New Brunswick",
  "05 NL Newfoundland and Labrador", "07 NS Nova Scotia", "08 ON Ontario", "09 PE Prince Edward Island",
  "10 QC Quebec", "11 SK Saskatchewan", "12 YT Yukon", "13 NT Northwest Territories", "14 NU Nunavut",
];
const normalize = (value: string) => value.normalize("NFD").replace(/\p{Diacritic}/gu, "").trim().toLowerCase();
const usRegions = new Map(us.flatMap(rule => [[rule.slice(0, 2).toLowerCase(), rule.slice(0, 2)],
  [normalize(rule.slice(3)), rule.slice(0, 2)]]));
const caRegions = new Map(ca.flatMap(rule => [[rule.slice(3, 5).toLowerCase(), rule.slice(0, 2)],
  [normalize(rule.slice(6)), rule.slice(0, 2)]]));
const countryAliases = new Map([
  ["usa", "US"], ["united states", "US"], ["united states of america", "US"], ["us", "US"],
  ["canada", "CA"], ["united kingdom", "GB"], ["uk", "GB"], ["england", "GB"], ["india", "IN"],
  ["china", "CN"], ["japan", "JP"], ["singapore", "SG"], ["hong kong", "HK"], ["taiwan", "TW"],
  ["germany", "DE"], ["france", "FR"], ["spain", "ES"], ["switzerland", "CH"], ["austria", "AT"],
  ["italy", "IT"], ["ireland", "IE"], ["australia", "AU"], ["sweden", "SE"], ["south korea", "KR"],
  ["korea, south", "KR"], ["poland", "PL"], ["czechia", "CZ"], ["israel", "IL"],
]);

function locate(location: string, index: Map<string, City[]>) {
  const clean = normalize(location.replace(/\s*\([^)]*\)\s*/g, "").replace(/\s+/g, " "));
  const [name, ...labels] = clean.split(/,\s*/);
  if (!name || /remote|multiple locations|united states|canada|worldwide|bay area|greater los angeles/.test(name)) return;
  const aliases: Record<string, string> = {"austin-met": "austin", "new york": "new york city"};
  const candidates = index.get(aliases[name] || name);
  if (!candidates) return;
  const regionNames = [...labels, labels.join(", ")];
  const country = regionNames.map(label => countryAliases.get(label)).find(Boolean);
  const usRegion = labels.map(label => usRegions.get(label)).find(Boolean);
  const caRegion = labels.map(label => caRegions.get(label)).find(Boolean);
  const inCountry = country ? candidates.filter(city => city[2] === country) : candidates;
  if (usRegion || caRegion) {
    return inCountry.find(city => (city[2] === "US" && city[3] === usRegion)
      || (city[2] === "CA" && city[3] === caRegion)) ?? (country && !["US", "CA"].includes(country) ? inCountry[0] : undefined);
  }
  if (country || inCountry.length === 1 || inCountry[0]?.[6] > (inCountry[1]?.[6] ?? 0) * 6) {
    return inCountry[0];
  }
}

function icon(className: string, count: number) {
  const size = className === "job-cluster" ? 40 : 30;
  return L.divIcon({className, html: `<span>${count}</span>`, iconSize: [size, size]});
}

export default function LocationMap({roles, onRole, capped}: {
  roles: Role[]; onRole: (id: string) => void; capped: boolean;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const tiles = useRef<L.TileLayer | null>(null);
  const markers = useRef<L.MarkerClusterGroup | null>(null);
  const markerCounts = useMemo(() => new WeakMap<L.Marker, number>(), []);
  const [data, setData] = useState<{countries: Country[]; cities: Map<string, City[]>}>();
  const [error, setError] = useState("");
  const [region, setRegion] = useState<Region>("north-america");
  const [streets, setStreets] = useState(true);
  const [selected, setSelected] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      api<Country[]>("/map/world.json", "GET", undefined, controller.signal),
      api<City[]>("/map/cities.json", "GET", undefined, controller.signal),
    ]).then(([countries, cityRows]) => {
      const cities = new Map<string, City[]>();
      for (const city of cityRows.sort((a, b) => b[6] - a[6])) {
        for (const key of new Set([normalize(city[0]), normalize(city[1])])) {
          const listed = cities.get(key) || [];
          listed.push(city);
          cities.set(key, listed);
        }
      }
      setData({countries, cities});
    }).catch(() => {if (!controller.signal.aborted) setError("Map data could not be loaded.");});
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!data || !viewport.current) return;
    const instance = L.map(viewport.current, {
      minZoom: 1, maxZoom: 16, maxBounds: [[-85, -180], [85, 180]], maxBoundsViscosity: .8,
      zoomSnap: .5, zoomDelta: 1, scrollWheelZoom: true, preferCanvas: true,
    });
    map.current = instance;
    instance.fitBounds(regionBounds["north-america"], {padding: [16, 16]});
    instance.createPane("offline-map").style.zIndex = "180";
    for (const country of data.countries) {
      L.polygon(country.map(polygon => polygon.map(ring => ring.map(([lon, lat]): L.LatLngTuple => [lat, lon]))), {
        pane: "offline-map", interactive: false, color: "#9aaba3", weight: .8,
        fillColor: "#d8e2d7", fillOpacity: 1,
      }).addTo(instance);
    }
    tiles.current = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      noWrap: true, maxZoom: 16, referrerPolicy: "strict-origin-when-cross-origin",
    });
    L.control.scale({position: "bottomleft"}).addTo(instance);
    markers.current = L.markerClusterGroup({
      maxClusterRadius: 42, showCoverageOnHover: false, animate: false,
      iconCreateFunction: cluster => icon("job-cluster", cluster.getAllChildMarkers().reduce(
        (total, marker) => total + (markerCounts.get(marker) || 0), 0)),
    }).addTo(instance);
    const observer = new ResizeObserver(() => instance.invalidateSize({pan: false}));
    observer.observe(viewport.current);
    return () => {
      observer.disconnect();
      instance.remove();
      map.current = null;
    };
  }, [data, markerCounts]);

  useEffect(() => {
    if (!map.current || !tiles.current) return;
    if (streets) tiles.current.addTo(map.current);
    else tiles.current.remove();
  }, [data, streets]);

  const {groups, unmapped} = useMemo(() => {
    const groups = new Map<string, LocationGroup>();
    const unmapped: Role[] = [];
    if (data) for (const role of roles) {
      const locations = new Set(role.location.split(/\s*[;|]\s*|\s+\/\s+/)
        .map(location => locate(location, data.cities)).filter(city => city !== undefined));
      if (!locations.size) unmapped.push(role);
      for (const city of locations) {
        const key = `${city[4]},${city[5]}`;
        const group = groups.get(key) || {label: `${city[0]}, ${city[2]}`, lat: city[4], lon: city[5], roles: []};
        if (!group.roles.some(item => item.id === role.id)) group.roles.push(role);
        groups.set(key, group);
      }
    }
    return {groups, unmapped};
  }, [data, roles]);

  useEffect(() => {
    const layer = markers.current;
    if (!layer) return;
    layer.clearLayers();
    const pins = [...groups].map(([key, group]) => {
      const count = group.roles.length;
      const pin = L.marker([group.lat, group.lon], {
        icon: icon("job-location", count), riseOnHover: true,
        title: `${group.label}, ${count} ${count === 1 ? "role" : "roles"}`,
      });
      markerCounts.set(pin, count);
      pin.on("click", () => setSelected(key));
      return pin;
    });
    layer.addLayers(pins);
  }, [groups, markerCounts]);

  function switchRegion(value: Region) {
    setRegion(value);
    setSelected("");
    map.current?.fitBounds(regionBounds[value], {padding: [16, 16]});
  }

  function list(items: Role[]) {
    return <ul className="map-results">{items.map(role => <li key={role.id}>
      <button data-job={role.id} onClick={() => onRole(role.id)}><strong>{role.title}</strong><span>{role.company} · {role.location || "Location unspecified"}</span></button>
    </li>)}</ul>;
  }

  const group = groups.get(selected);
  return <section className="map-panel" aria-label="Job locations">
    <div className="map-toolbar">
      <div><strong>Job locations</strong>
        <span className="muted">{capped ? ` First ${roles.length.toLocaleString()} matches` : ` ${roles.length.toLocaleString()} matching roles`}</span></div>
      <div className="map-controls">
        <div className="segmented" role="group" aria-label="Map region">
          {(["north-america", "world"] as const).map(value =>
            <button key={value} aria-pressed={region === value} onClick={() => switchRegion(value)}>
              {value === "world" ? "World" : "North America"}</button>)}
        </div>
        <button aria-pressed={streets} onClick={() => setStreets(!streets)}>Street map</button>
      </div>
    </div>
    {error ? <p role="alert" className="map-message">{error}</p> : !data ? <p role="status" className="map-message">Loading map…</p> :
      <>
        <div ref={viewport} className="map-viewport" aria-label="Interactive map. Use arrow keys to pan and plus or minus to zoom." />
        {group ? <div className="map-selection"><h3>{group.label}</h3>{list(group.roles)}</div> :
          <p className="map-message">{groups.size ? "Select a city to see its roles." : "No city-level locations in these results."}</p>}
        {!!unmapped.length && <details className="map-unmapped"><summary>Remote, broad or unmapped locations ({unmapped.length})</summary>
          {list(unmapped)}</details>}
        <p className="map-credit">Boundaries by <a href="https://www.naturalearthdata.com/" target="_blank" rel="noreferrer">Natural Earth</a>
          {" · "}Cities from <a href="https://www.geonames.org/" target="_blank" rel="noreferrer">GeoNames</a>
          {" · "}<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">CC BY 4.0</a></p>
      </>}
  </section>;
}

