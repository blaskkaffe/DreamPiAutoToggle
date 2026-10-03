"""Builds modules/clock/zones.json, the time zone areas of the clock's world map. A developer tool: run it on a PC, not on the Pi.

Input: combined-now.json from timezone-boundary-builder (https://github.com/evansiroky/timezone-boundary-builder, release asset
timezones-now.geojson.zip, data (c) OpenStreetMap contributors, ODbL). Its "now" set has one area per group of zones that keep
the same clock time from now on, each named by one IANA zone (its "tzid"), so the web service can ask that zone for the offset
with summer time.

    pip install shapely
    python3 tools/build_clock_zones.py combined-now.json [release name]

The map is a plain longitude/latitude grid: x = longitude + 180 (0..360), y = TOP - latitude (latitude TOP at the top, BOTTOM at
the bottom); the page (modules/clock/page.js) uses the same numbers. Areas are simplified to about a third of a degree and tiny
islands are left out, so the file stays small (it is fetched when the map is first opened).
"""
import json
import os
import sys

from shapely.geometry import box, shape, Polygon, MultiPolygon
from shapely.ops import unary_union

TOP, BOTTOM = 78.0, -60.0          # the latitudes the map shows (keep in step with page.js)
SIMPLIFY = 0.35                    # degrees
MIN_AREA = 0.6                     # square degrees: smaller pieces are left out (keep each area's largest piece anyway)
LABEL_AREA = 45.0                  # square degrees: pieces this big get an hour label
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "modules", "clock", "zones.json")


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
        labels = []
        for p in keep:
            if p.area >= LABEL_AREA or (not labels and p is keep[0] and p.area >= 4):
                pt = p.representative_point()
                labels.append([round(pt.x + 180, 1), round(TOP - pt.y, 1)])
        zones.append({"tz": tz, "p": [ring(p) for p in keep], "l": labels})
    zones.sort(key=lambda z: z["tz"])
    out = {"source": "timezone-boundary-builder %s (timezones-now), data (c) OpenStreetMap contributors, ODbL 1.0" % release,
           "top": TOP, "bottom": BOTTOM, "zones": zones}
    with open(OUT, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print("%d areas, %d pieces, %d points, %d bytes -> %s" % (len(zones), sum(len(z["p"]) for z in zones),
          sum(len(r) // 2 for z in zones for r in z["p"]), os.path.getsize(OUT), os.path.normpath(OUT)))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "?")
