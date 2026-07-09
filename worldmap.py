"""
Stylized Unicode world map for the dashboard's Globe panel.

This is not an atlas -- it's a coarse, deterministic land/ocean grid built
from a handful of continent bounding boxes, rendered with a night-lights
color treatment to evoke the reference design's satellite globe. Good enough
to drop a pin on the right landmass for a given country, not for anything
that needs real cartographic accuracy.

The country the pin lands on is driven by whatever sheet/tab name is
selected in the dashboard (see `resolve_country`), not a manual dropdown --
so the map title always matches the sheet.
"""

import difflib
import random

from rich.text import Text

WIDTH = 48
HEIGHT = 14

# Rough (lat_min, lat_max, lon_min, lon_max) boxes, several stacked per
# continent so tapering shapes (South America, Africa) read as tapering
# instead of a single rectangle.
_LAND_BOXES = [
    # North America
    (58, 72, -168, -130),   # Alaska
    (25, 60, -128, -58),    # Canada / continental US
    (7, 25, -107, -77),     # Mexico / Central America
    (60, 83, -55, -20),     # Greenland
    # South America
    (0, 13, -82, -35),
    (-20, 0, -81, -35),
    (-38, -20, -74, -48),
    (-56, -38, -73, -63),
    # Europe
    (36, 71, -10, 40),
    # Africa
    (15, 38, -17, 52),
    (-5, 15, -18, 52),
    (-35, -5, 10, 42),
    # Asia
    (45, 78, 40, 180),
    (5, 45, 40, 150),
    (-11, 10, 95, 141),     # Indonesian archipelago
    (30, 46, 129, 146),     # Japan
    # Australia / Oceania
    (-39, -10, 113, 154),
    (-47, -34, 166, 179),
]

# name -> (flag emoji, lat, lon). Centroids are coarse (country-scale, not
# city-scale) -- enough to land the pin on the right landmass/region.
COUNTRIES = {
    "Afghanistan": ("\U0001F1E6\U0001F1EB", 33.9, 67.7),
    "Albania": ("\U0001F1E6\U0001F1F1", 41.2, 20.2),
    "Algeria": ("\U0001F1E9\U0001F1FF", 28.0, 2.6),
    "Argentina": ("\U0001F1E6\U0001F1F7", -38.4, -63.6),
    "Armenia": ("\U0001F1E6\U0001F1F2", 40.1, 45.0),
    "Australia": ("\U0001F1E6\U0001F1FA", -25.3, 133.8),
    "Austria": ("\U0001F1E6\U0001F1F9", 47.5, 14.6),
    "Azerbaijan": ("\U0001F1E6\U0001F1FF", 40.1, 47.6),
    "Bahrain": ("\U0001F1E7\U0001F1ED", 26.0, 50.6),
    "Bangladesh": ("\U0001F1E7\U0001F1E9", 23.7, 90.4),
    "Belarus": ("\U0001F1E7\U0001F1FE", 53.7, 27.9),
    "Belgium": ("\U0001F1E7\U0001F1EA", 50.5, 4.5),
    "Bolivia": ("\U0001F1E7\U0001F1F4", -16.3, -63.6),
    "Bosnia and Herzegovina": ("\U0001F1E7\U0001F1E6", 43.9, 17.7),
    "Brazil": ("\U0001F1E7\U0001F1F7", -14.2, -51.9),
    "Bulgaria": ("\U0001F1E7\U0001F1EC", 42.7, 25.5),
    "Cambodia": ("\U0001F1F0\U0001F1ED", 12.6, 104.9),
    "Cameroon": ("\U0001F1E8\U0001F1F2", 5.7, 12.7),
    "Canada": ("\U0001F1E8\U0001F1E6", 56.1, -106.3),
    "Chile": ("\U0001F1E8\U0001F1F1", -35.7, -71.5),
    "China": ("\U0001F1E8\U0001F1F3", 35.0, 105.0),
    "Colombia": ("\U0001F1E8\U0001F1F4", 4.6, -74.3),
    "Costa Rica": ("\U0001F1E8\U0001F1F7", 9.7, -83.8),
    "Croatia": ("\U0001F1ED\U0001F1F7", 45.1, 15.2),
    "Cuba": ("\U0001F1E8\U0001F1FA", 21.5, -77.8),
    "Cyprus": ("\U0001F1E8\U0001F1FE", 35.1, 33.4),
    "Czech Republic": ("\U0001F1E8\U0001F1FF", 49.8, 15.5),
    "Denmark": ("\U0001F1E9\U0001F1F0", 56.3, 9.5),
    "Dominican Republic": ("\U0001F1E9\U0001F1F4", 18.7, -70.2),
    "Ecuador": ("\U0001F1EA\U0001F1E8", -1.8, -78.2),
    "Egypt": ("\U0001F1EA\U0001F1EC", 26.8, 30.8),
    "El Salvador": ("\U0001F1F8\U0001F1FB", 13.8, -88.9),
    "Estonia": ("\U0001F1EA\U0001F1EA", 58.6, 25.0),
    "Ethiopia": ("\U0001F1EA\U0001F1F9", 9.1, 40.5),
    "Finland": ("\U0001F1EB\U0001F1EE", 61.9, 25.7),
    "France": ("\U0001F1EB\U0001F1F7", 46.6, 2.2),
    "Georgia": ("\U0001F1EC\U0001F1EA", 42.3, 43.4),
    "Germany": ("\U0001F1E9\U0001F1EA", 51.2, 10.4),
    "Ghana": ("\U0001F1EC\U0001F1ED", 7.9, -1.0),
    "Greece": ("\U0001F1EC\U0001F1F7", 39.1, 21.8),
    "Guatemala": ("\U0001F1EC\U0001F1F9", 15.8, -90.2),
    "Honduras": ("\U0001F1ED\U0001F1F3", 15.2, -86.2),
    "Hong Kong": ("\U0001F1ED\U0001F1F0", 22.3, 114.2),
    "Hungary": ("\U0001F1ED\U0001F1FA", 47.2, 19.5),
    "Iceland": ("\U0001F1EE\U0001F1F8", 64.9, -19.0),
    "India": ("\U0001F1EE\U0001F1F3", 22.0, 79.0),
    "Indonesia": ("\U0001F1EE\U0001F1E9", -0.8, 113.9),
    "Iran": ("\U0001F1EE\U0001F1F7", 32.4, 53.7),
    "Iraq": ("\U0001F1EE\U0001F1F6", 33.2, 43.7),
    "Ireland": ("\U0001F1EE\U0001F1EA", 53.4, -8.2),
    "Israel": ("\U0001F1EE\U0001F1F1", 31.0, 34.8),
    "Italy": ("\U0001F1EE\U0001F1F9", 41.9, 12.6),
    "Ivory Coast": ("\U0001F1E8\U0001F1EE", 7.5, -5.5),
    "Jamaica": ("\U0001F1EF\U0001F1F2", 18.1, -77.3),
    "Japan": ("\U0001F1EF\U0001F1F5", 36.2, 138.3),
    "Jordan": ("\U0001F1EF\U0001F1F4", 30.6, 36.2),
    "Kazakhstan": ("\U0001F1F0\U0001F1FF", 48.0, 66.9),
    "Kenya": ("\U0001F1F0\U0001F1EA", -0.0, 37.9),
    "Kuwait": ("\U0001F1F0\U0001F1FC", 29.3, 47.5),
    "Kyrgyzstan": ("\U0001F1F0\U0001F1EC", 41.2, 74.8),
    "Latvia": ("\U0001F1F1\U0001F1FB", 56.9, 24.6),
    "Lebanon": ("\U0001F1F1\U0001F1E7", 33.9, 35.9),
    "Libya": ("\U0001F1F1\U0001F1FE", 26.3, 17.2),
    "Lithuania": ("\U0001F1F1\U0001F1F9", 55.2, 23.9),
    "Luxembourg": ("\U0001F1F1\U0001F1FA", 49.8, 6.1),
    "Malaysia": ("\U0001F1F2\U0001F1FE", 4.2, 101.9),
    "Malta": ("\U0001F1F2\U0001F1F9", 35.9, 14.4),
    "Mexico": ("\U0001F1F2\U0001F1FD", 23.6, -102.5),
    "Moldova": ("\U0001F1F2\U0001F1E9", 47.4, 28.4),
    "Mongolia": ("\U0001F1F2\U0001F1F3", 46.9, 103.8),
    "Montenegro": ("\U0001F1F2\U0001F1EA", 42.7, 19.4),
    "Morocco": ("\U0001F1F2\U0001F1E6", 31.8, -7.1),
    "Myanmar": ("\U0001F1F2\U0001F1F2", 21.9, 95.9),
    "Nepal": ("\U0001F1F3\U0001F1F5", 28.4, 84.1),
    "Netherlands": ("\U0001F1F3\U0001F1F1", 52.1, 5.3),
    "New Zealand": ("\U0001F1F3\U0001F1FF", -41.0, 174.9),
    "Nicaragua": ("\U0001F1F3\U0001F1EE", 12.9, -85.2),
    "Nigeria": ("\U0001F1F3\U0001F1EC", 9.1, 8.7),
    "North Korea": ("\U0001F1F0\U0001F1F5", 40.3, 127.5),
    "North Macedonia": ("\U0001F1F2\U0001F1F0", 41.6, 21.7),
    "Norway": ("\U0001F1F3\U0001F1F4", 60.5, 8.5),
    "Oman": ("\U0001F1F4\U0001F1F2", 21.5, 55.9),
    "Pakistan": ("\U0001F1F5\U0001F1F0", 30.4, 69.3),
    "Panama": ("\U0001F1F5\U0001F1E6", 8.5, -80.8),
    "Paraguay": ("\U0001F1F5\U0001F1FE", -23.4, -58.4),
    "Peru": ("\U0001F1F5\U0001F1EA", -9.2, -75.0),
    "Philippines": ("\U0001F1F5\U0001F1ED", 12.9, 121.8),
    "Poland": ("\U0001F1F5\U0001F1F1", 51.9, 19.1),
    "Portugal": ("\U0001F1F5\U0001F1F9", 39.4, -8.2),
    "Puerto Rico": ("\U0001F1F5\U0001F1F7", 18.2, -66.6),
    "Qatar": ("\U0001F1F6\U0001F1E6", 25.4, 51.2),
    "Romania": ("\U0001F1F7\U0001F1F4", 45.9, 24.9),
    "Russia": ("\U0001F1F7\U0001F1FA", 61.5, 105.0),
    "Saudi Arabia": ("\U0001F1F8\U0001F1E6", 23.9, 45.1),
    "Serbia": ("\U0001F1F7\U0001F1F8", 44.0, 21.0),
    "Singapore": ("\U0001F1F8\U0001F1EC", 1.4, 103.8),
    "Slovakia": ("\U0001F1F8\U0001F1F0", 48.7, 19.7),
    "Slovenia": ("\U0001F1F8\U0001F1EE", 46.1, 14.8),
    "South Africa": ("\U0001F1FF\U0001F1E6", -30.6, 22.9),
    "South Korea": ("\U0001F1F0\U0001F1F7", 35.9, 127.8),
    "Spain": ("\U0001F1EA\U0001F1F8", 40.5, -3.7),
    "Sri Lanka": ("\U0001F1F1\U0001F1F0", 7.9, 80.8),
    "Sweden": ("\U0001F1F8\U0001F1EA", 60.1, 18.6),
    "Switzerland": ("\U0001F1E8\U0001F1ED", 46.8, 8.2),
    "Syria": ("\U0001F1F8\U0001F1FE", 34.8, 39.0),
    "Taiwan": ("\U0001F1F9\U0001F1FC", 23.7, 121.0),
    "Tajikistan": ("\U0001F1F9\U0001F1EF", 38.9, 71.3),
    "Thailand": ("\U0001F1F9\U0001F1ED", 15.9, 100.9),
    "Tunisia": ("\U0001F1F9\U0001F1F3", 33.9, 9.5),
    "Turkey": ("\U0001F1F9\U0001F1F7", 38.9, 35.2),
    "Turkmenistan": ("\U0001F1F9\U0001F1F2", 38.9, 59.6),
    "Ukraine": ("\U0001F1FA\U0001F1E6", 48.4, 31.2),
    "United Arab Emirates": ("\U0001F1E6\U0001F1EA", 23.4, 53.8),
    "United Kingdom": ("\U0001F1EC\U0001F1E7", 54.0, -2.0),
    "United States": ("\U0001F1FA\U0001F1F8", 39.8, -98.6),
    "Uruguay": ("\U0001F1FA\U0001F1FE", -32.5, -55.8),
    "Uzbekistan": ("\U0001F1FA\U0001F1FF", 41.4, 64.6),
    "Venezuela": ("\U0001F1FB\U0001F1EA", 6.4, -66.6),
    "Vietnam": ("\U0001F1FB\U0001F1F3", 14.1, 108.3),
    "Yemen": ("\U0001F1FE\U0001F1EA", 15.6, 48.0),
}

# Aliases / shorthand / common misspellings -> canonical COUNTRIES key.
# Sheet tab names rarely match ISO names exactly, so this is checked before
# falling back to fuzzy matching.
_ALIASES = {
    "usa": "United States",
    "us": "United States",
    "u.s.a.": "United States",
    "u.s.": "United States",
    "america": "United States",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "britain": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",
    "uae": "United Arab Emirates",
    "emirates": "United Arab Emirates",
    "korea": "South Korea",
    "south korea": "South Korea",
    "republic of korea": "South Korea",
    "north korea": "North Korea",
    "dprk": "North Korea",
    "russia federation": "Russia",
    "russian federation": "Russia",
    "cote d'ivoire": "Ivory Coast",
    "ivory coast": "Ivory Coast",
    "czechia": "Czech Republic",
    "holland": "Netherlands",
    "macedonia": "North Macedonia",
    "bosnia": "Bosnia and Herzegovina",
    "viet nam": "Vietnam",
    "hongkong": "Hong Kong",
}

DEFAULT_COUNTRY = "United States"


def resolve_country(name: str | None) -> str:
    """Best-effort match of an arbitrary label (typically a sheet/tab name)
    to a canonical entry in COUNTRIES.

    Tries, in order: exact match, alias table, then fuzzy string matching
    (handles typos/partial names like "Phillipines" or "Deutschland"-free
    minor variants) so that whatever a sheet tab happens to be called still
    lands the pin on the right country instead of always falling back to
    the default.
    """
    if not name:
        return DEFAULT_COUNTRY

    cleaned = name.strip()
    if cleaned in COUNTRIES:
        return cleaned

    lowered = cleaned.lower()
    for key in COUNTRIES:
        if key.lower() == lowered:
            return key

    if lowered in _ALIASES:
        return _ALIASES[lowered]

    names_lower = {key.lower(): key for key in COUNTRIES}
    matches = difflib.get_close_matches(lowered, names_lower.keys(), n=1, cutoff=0.6)
    if matches:
        return names_lower[matches[0]]

    # Substring match as a last resort (e.g. "USA - West Coast" tabs).
    for key in COUNTRIES:
        if key.lower() in lowered or lowered in key.lower():
            return key

    return DEFAULT_COUNTRY

_OCEAN_CHAR = "·"
_LAND_CHARS = ("▓", "▒")  # dense / edge shading
_CITY_LIGHT_CHAR = "•"
_MARKER_CHAR = "◉"

_OCEAN_STYLE = "#2a3a52"
_LAND_STYLE = "#3fae8a"
_LAND_EDGE_STYLE = "#2d7d63"
_CITY_LIGHT_STYLE = "bold #ffd166"
_MARKER_STYLE = "bold #ff6b47"


def project(lat: float, lon: float) -> tuple[int, int]:
    """Equirectangular lat/lon -> (row, col) on the map grid."""
    col = int((lon + 180) / 360 * WIDTH)
    row = int((90 - lat) / 180 * HEIGHT)
    return max(0, min(HEIGHT - 1, row)), max(0, min(WIDTH - 1, col))


def _cell_latlon(row: int, col: int) -> tuple[float, float]:
    """Lat/lon at the *center* of grid cell (row, col)."""
    lon = (col + 0.5) / WIDTH * 360 - 180
    lat = 90 - (row + 0.5) / HEIGHT * 180
    return lat, lon


def _is_land(row: int, col: int) -> bool:
    if row < 0 or row >= HEIGHT or col < 0 or col >= WIDTH:
        return False
    lat, lon = _cell_latlon(row, col)
    for lat_min, lat_max, lon_min, lon_max in _LAND_BOXES:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return True
    return False


def _build_grid():
    """Deterministic land grid with softened (jagged) coastline edges."""
    rng = random.Random(1337)
    grid = [[False] * WIDTH for _ in range(HEIGHT)]
    for row in range(HEIGHT):
        for col in range(WIDTH):
            if not _is_land(row, col):
                continue
            interior = (
                _is_land(row - 1, col)
                and _is_land(row + 1, col)
                and _is_land(row, col - 1)
                and _is_land(row, col + 1)
            )
            grid[row][col] = True if interior else rng.random() > 0.3
    return grid


def _build_city_lights(grid):
    lights = set()
    for row in range(HEIGHT):
        for col in range(WIDTH):
            if not grid[row][col]:
                continue
            if random.Random((row * 1000 + col) ^ 0x5EED).random() > 0.82:
                lights.add((row, col))
    return lights


_GRID = _build_grid()
_CITY_LIGHTS = _build_city_lights(_GRID)


def render_map(selected: str | None = None) -> Text:
    """Render the globe as a Rich Text block with the selected country pinned."""
    name = resolve_country(selected)
    _, lat, lon = COUNTRIES[name]
    marker_row, marker_col = project(lat, lon)

    text = Text(no_wrap=True, overflow="crop")
    for row in range(HEIGHT):
        for col in range(WIDTH):
            if row == marker_row and col == marker_col:
                text.append(_MARKER_CHAR, style=_MARKER_STYLE)
            elif _GRID[row][col]:
                if (row, col) in _CITY_LIGHTS:
                    text.append(_CITY_LIGHT_CHAR, style=_CITY_LIGHT_STYLE)
                else:
                    interior = (
                        _GRID[row - 1][col] if row > 0 else False,
                        _GRID[row + 1][col] if row < HEIGHT - 1 else False,
                        _GRID[row][col - 1] if col > 0 else False,
                        _GRID[row][col + 1] if col < WIDTH - 1 else False,
                    )
                    if all(interior):
                        text.append(_LAND_CHARS[0], style=_LAND_STYLE)
                    else:
                        text.append(_LAND_CHARS[1], style=_LAND_EDGE_STYLE)
            else:
                text.append(_OCEAN_CHAR, style=_OCEAN_STYLE)
        if row < HEIGHT - 1:
            text.append("\n")
    return text


_LATLON_LABELS = {
    "en": ("Lat", "Lon"),
    "zh": ("纬度", "经度"),
}


def country_info(selected: str | None = None, lang: str = "en") -> str:
    """Textual-markup info line for the country below the map."""
    name = resolve_country(selected)
    flag, lat, lon = COUNTRIES[name]
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    lat_label, lon_label = _LATLON_LABELS.get(lang, _LATLON_LABELS["en"])
    return (
        f"{flag} [bold]{name}[/bold]\n"
        f"[dim]{lat_label} {abs(lat):.1f}°{ns}   {lon_label} {abs(lon):.1f}°{ew}[/dim]"
    )
