"""Builds modules/clock/zones.json, the time zone areas of the clock's world map. A developer tool: run it on a PC, not on the Pi.

Input: combined-now.json from timezone-boundary-builder (https://github.com/evansiroky/timezone-boundary-builder, release asset
timezones-now.geojson.zip, data (c) OpenStreetMap contributors, ODbL). Its "now" set has one area per group of zones that keep
the same clock time from now on, each named by one IANA zone (its "tzid"), so the web service can ask that zone for the offset
with summer time.

    pip install shapely
    python3 tools/build_clock_zones.py combined-now.json [release name]
    python3 tools/build_clock_zones.py --restyle          simplify the existing zones.json further (no shapely, no download)

The map is a plain longitude/latitude grid: x = longitude + 180 (0..360), y = TOP - latitude (latitude TOP at the top, BOTTOM at
the bottom); the page (modules/clock/page.js) uses the same numbers. The map is stylised: areas are simplified to about a degree
(restyle() does the same to a finished file) and small islands are left out, so the shapes are plain and the file stays small
(it is fetched when the map is first opened). The page shows the hour per 15-degree stripe, not per area, so there are no labels.
"""
import json
import os
import sys

TOP, BOTTOM = 78.0, -60.0          # the latitudes the map shows (keep in step with page.js)
SIMPLIFY = 1.0                     # degrees
MIN_AREA = 6.0                     # square degrees: smaller pieces are left out (keep each area's largest piece anyway)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "modules", "clock", "zones.json")


try:
    from shapely.geometry import box, shape, Polygon, MultiPolygon
    from shapely.ops import unary_union
except ImportError:       # only --restyle works without it
    pass


def parts(geom):
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]


def ring(poly):
    """The outer ring in map units, flat [x, y, x, y, ...] rounded to 0.1 (holes - lakes, enclaves - are left out)."""
    pts = list(poly.exterior.coords)[:-1]
    out = []
    for lon, lat in pts:
        out += [round(lon + 180, 1), round(TOP - lat, 1)]
    return out


def _dist(p, a, b):
    """How far point p is from the line through a and b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    if not dx and not dy:
        return ((p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2) ** 0.5
    return abs(dy * p[0] - dx * p[1] + b[0] * a[1] - b[1] * a[0]) / (dx * dx + dy * dy) ** 0.5


def _rdp(pts, eps):
    """Douglas-Peucker on an open polyline."""
    if len(pts) < 3:
        return pts
    far, at = max((_dist(p, pts[0], pts[-1]), i) for i, p in enumerate(pts[1:-1], 1))
    if far <= eps:
        return [pts[0], pts[-1]]
    return _rdp(pts[:at + 1], eps)[:-1] + _rdp(pts[at:], eps)


def _area(pts):
    return abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))) / 2


def restyle(eps=SIMPLIFY, min_area=MIN_AREA):
    """Simplify the finished zones.json further: every outline to about eps map units (degrees), pieces smaller than min_area square
    degrees dropped (each area keeps its largest), the hour labels dropped. Pure Python."""
    with open(OUT) as f:
        data = json.load(f)
    for z in data["zones"]:
        pieces = []
        for flat in z["p"]:
            pts = [(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)]
            half = len(pts) // 2
            ring = _rdp(pts[:half + 1], eps)[:-1] + _rdp(pts[half:] + pts[:1], eps)[:-1]      # a ring is two open lines
            if len(ring) >= 3:
                pieces.append((_area(ring), ring))
        pieces.sort(key=lambda x: -x[0])
        z["p"] = [[round(c, 1) for pt in ring for c in pt] for i, (a, ring) in enumerate(pieces) if a >= min_area or i == 0]
        z.pop("l", None)
    with open(OUT, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    print("%d areas, %d pieces, %d points, %d bytes" % (len(data["zones"]), sum(len(z["p"]) for z in data["zones"]),
          sum(len(r) // 2 for z in data["zones"] for r in z["p"]), os.path.getsize(OUT)))


def main(src, release):
    with open(src) as f:
        data = json.load(f)
    frame = box(-180, BOTTOM, 180, TOP)
    zones = []
    for feat in data["features"]:
        tz = feat["properties"]["tzid"]
        geom = shape(feat["geometry"]).buffer(0).intersection(frame)
        if geom.is_empty:
            continue
        geom = unary_union(geom).simplify(SIMPLIFY, preserve_topology=True)
        ps = sorted((p for p in parts(geom) if not p.is_empty), key=lambda p: -p.area)
        keep = [p for i, p in enumerate(ps) if p.area >= MIN_AREA or i == 0]
        keep = [p for p in keep if len(p.exterior.coords) >= 4]
        if not keep:
            continue
        zones.append({"tz": tz, "p": [ring(p) for p in keep]})
    zones.sort(key=lambda z: z["tz"])
    out = {"source": "timezone-boundary-builder %s (timezones-now), data (c) OpenStreetMap contributors, ODbL 1.0" % release,
           "top": TOP, "bottom": BOTTOM, "zones": zones}
    with open(OUT, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print("%d areas, %d pieces, %d points, %d bytes -> %s" % (len(zones), sum(len(z["p"]) for z in zones),
          sum(len(r) // 2 for z in zones for r in z["p"]), os.path.getsize(OUT), os.path.normpath(OUT)))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--restyle"]:
        restyle()
        sys.exit(0)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "?")
