import os
import threading
from datetime import datetime, timedelta, timezone

import swisseph as swe
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EPHE_PATH = os.path.join(BASE_DIR, "ephe")

# Point Swiss Ephemeris to the local .se1 files.
swe.set_ephe_path(EPHE_PATH)

print("EPHE_PATH =", EPHE_PATH)
print("EPHE EXISTS =", os.path.isdir(EPHE_PATH))
print("EPHE FILES =", os.listdir(EPHE_PATH) if os.path.isdir(EPHE_PATH) else [])
# ============================================================
# JPS ASTRO RESEARCH - SWISS EPHEMERIS LOCAL API
#
# Settings:
#   Zodiac      : Sidereal
#   Ayanamsha   : Lahiri
#   Observation : Geocentric
#   Rahu/Ketu   : TRUE NODE
#
# Run:
#   uvicorn app:app --reload
#
# Open:
#   http://127.0.0.1:8000/docs
# ============================================================


app = FastAPI(
    title="JPS Astro Research - Swiss Ephemeris API",
    version="1.0.0",
)


# ------------------------------------------------------------
# CORS - LOCAL TESTING
# Later, when you deploy the frontend, add its real domain here.
# ------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://jayaprakash3195.github.io",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ------------------------------------------------------------
# Swiss Ephemeris is stateful.
# Keep one lock so every request uses Lahiri consistently.
# ------------------------------------------------------------
SWE_LOCK = threading.RLock()


# ------------------------------------------------------------
# Swiss Ephemeris calculation flags
# ------------------------------------------------------------
PLANET_FLAGS = (
    swe.FLG_SWIEPH
    | swe.FLG_SIDEREAL
    | swe.FLG_SPEED
)

HOUSE_FLAGS = swe.FLG_SIDEREAL


# ------------------------------------------------------------
# Names
# ------------------------------------------------------------
RASI_NAMES = [
    "Mesham",
    "Rishabam",
    "Mithunam",
    "Kadagam",
    "Simmam",
    "Kanni",
    "Thulam",
    "Viruchigam",
    "Dhanusu",
    "Makaram",
    "Kumbam",
    "Meenam",
]

NAKSHATRAS = [
    "Ashwini",
    "Bharani",
    "Krittika",
    "Rohini",
    "Mrigashirsha",
    "Ardra",
    "Punarvasu",
    "Pushya",
    "Ashlesha",
    "Magha",
    "Purva Phalguni",
    "Uttara Phalguni",
    "Hasta",
    "Chitra",
    "Swati",
    "Vishakha",
    "Anuradha",
    "Jyeshtha",
    "Mula",
    "Purva Ashadha",
    "Uttara Ashadha",
    "Shravana",
    "Dhanishta",
    "Shatabhisha",
    "Purva Bhadrapada",
    "Uttara Bhadrapada",
    "Revati",
]


# ------------------------------------------------------------
# Planets
#
# IMPORTANT:
# Rahu = TRUE NODE
# Ketu is calculated exactly 180 degrees opposite Rahu.
# ------------------------------------------------------------
PLANETS = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mercury": swe.MERCURY,
    "Venus": swe.VENUS,
    "Mars": swe.MARS,
    "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN,
    "Rahu": swe.TRUE_NODE,
}


# ------------------------------------------------------------
# Request model
# ------------------------------------------------------------
class AstroInput(BaseModel):
    year: int = Field(..., ge=-5000, le=5000)
    month: int = Field(..., ge=1, le=12)
    day: int = Field(..., ge=1, le=31)

    hour: int = Field(0, ge=0, le=23)
    minute: int = Field(0, ge=0, le=59)
    second: int = Field(0, ge=0, le=59)

    # Geographic latitude: north positive, south negative
    latitude: float = Field(..., ge=-90, le=90)

    # Geographic longitude: east positive, west negative
    longitude: float = Field(..., ge=-180, le=180)

    # India = +5.5
    timezone: float = Field(5.5, ge=-14, le=14)


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def normalize_degree(value: float) -> float:
    return value % 360.0


def degree_to_dms(value: float) -> dict:
    value = normalize_degree(value)

    degree = int(value)
    minute_float = (value - degree) * 60.0
    minute = int(minute_float)
    second = (minute_float - minute) * 60.0

    return {
        "degree": degree,
        "minute": minute,
        "second": second,
        "text": f'{degree:03d}° {minute:02d}\' {second:06.3f}"',
    }


def degree_in_rasi_to_dms(value: float) -> dict:
    value = normalize_degree(value) % 30.0

    degree = int(value)
    minute_float = (value - degree) * 60.0
    minute = int(minute_float)
    second = (minute_float - minute) * 60.0

    return {
        "degree": degree,
        "minute": minute,
        "second": second,
        "text": f'{degree:02d}° {minute:02d}\' {second:06.3f}"',
    }


def get_rasi_nakshatra_pada(longitude: float) -> dict:
    longitude = normalize_degree(longitude)

    rasi_index = int(longitude // 30.0)

    # 360 / 108 = 3°20' per pada
    pada_length = 360.0 / 108.0

    global_pada = int(longitude // pada_length) + 1
    global_pada = max(1, min(global_pada, 108))

    nakshatra_index = (global_pada - 1) // 4
    pada = ((global_pada - 1) % 4) + 1

    return {
        "rasiIndex": rasi_index + 1,
        "rasi": RASI_NAMES[rasi_index],
        "nakshatraIndex": nakshatra_index + 1,
        "nakshatra": NAKSHATRAS[nakshatra_index],
        "pada": pada,
        "globalPada": global_pada,
    }


def actual_ephemeris_name(return_flags: int) -> str:
    if return_flags & swe.FLG_JPLEPH:
        return "JPL"

    if return_flags & swe.FLG_SWIEPH:
        return "Swiss Ephemeris"

    if return_flags & swe.FLG_MOSEPH:
        return "Moshier"

    return "Unknown"


def calculate_planet(jd_ut: float, body: int) -> dict:
    result, return_flags = swe.calc_ut(
        jd_ut,
        body,
        PLANET_FLAGS,
    )

    longitude = normalize_degree(result[0])

    latitude = result[1]
    distance = result[2]

    # result[3] = longitudinal speed in degree/day
    speed_longitude = result[3]

    retrograde = speed_longitude < 0

    position = get_rasi_nakshatra_pada(
        longitude
    )

    return {
        "fullDegree": longitude,

        "degreeDMS": degree_to_dms(
            longitude
        ),

        "degreeInRasi": longitude % 30.0,

        "degreeInRasiDMS": degree_in_rasi_to_dms(
            longitude
        ),

        "latitude": latitude,

        "distanceAU": distance,

        "longitudeSpeed": speed_longitude,

        "retrograde": retrograde,

        "ephemerisUsed": actual_ephemeris_name(
            return_flags
        ),

        **position,
    }


# ------------------------------------------------------------
# Basic endpoints
# ------------------------------------------------------------
@app.get("/")
def home():
    return {
        "app": "JPS Astro Research",
        "engine": "Swiss Ephemeris",
        "zodiac": "Sidereal",
        "ayanamsha": "Lahiri",
        "node": "True Node",
        "observation": "Geocentric",
        "status": "working",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "engine": "Swiss Ephemeris",
    }


@app.get("/debug-ephe")
def debug_ephe():
    expected_files = ["sepl_18.se1", "semo_18.se1"]

    files = {}
    for filename in expected_files:
        filepath = os.path.join(EPHE_PATH, filename)
        files[filename] = {
            "exists": os.path.isfile(filepath),
            "sizeBytes": os.path.getsize(filepath) if os.path.isfile(filepath) else None,
            "fullPath": filepath,
        }

    with SWE_LOCK:
        swe.set_ephe_path(EPHE_PATH)
        swe.set_sid_mode(swe.SIDM_LAHIRI)

        # Same date used in your JPS test: 31-01-1995 10:20 IST = 04:50 UTC.
        jd_test = swe.julday(
            1995,
            1,
            31,
            4.0 + 50.0 / 60.0,
            swe.GREG_CAL,
        )

        result, return_flags = swe.calc_ut(
            jd_test,
            swe.SUN,
            PLANET_FLAGS,
        )

    return {
        "ephePath": EPHE_PATH,
        "folderExists": os.path.isdir(EPHE_PATH),
        "files": files,
        "testEngine": actual_ephemeris_name(return_flags),
        "returnFlags": int(return_flags),
        "testSunLongitude": result[0],
    }


# ------------------------------------------------------------
# Main calculation
# ------------------------------------------------------------
@app.post("/calculate")
def calculate(data: AstroInput):

    # --------------------------------------------------------
    # LOCAL TIMEZONE
    # --------------------------------------------------------
    local_tz = timezone(
        timedelta(
            hours=data.timezone
        )
    )

    local_datetime = datetime(
        data.year,
        data.month,
        data.day,
        data.hour,
        data.minute,
        data.second,
        tzinfo=local_tz,
    )


    # --------------------------------------------------------
    # LOCAL TIME -> UTC
    # --------------------------------------------------------
    utc_datetime = local_datetime.astimezone(
        timezone.utc
    )


    decimal_utc_hour = (
        utc_datetime.hour
        + utc_datetime.minute / 60.0
        + utc_datetime.second / 3600.0
        + utc_datetime.microsecond / 3600000000.0
    )


    # --------------------------------------------------------
    # JULIAN DAY
    # --------------------------------------------------------
    jd_ut = swe.julday(
        utc_datetime.year,
        utc_datetime.month,
        utc_datetime.day,
        decimal_utc_hour,
        swe.GREG_CAL,
    )


    # ========================================================
    #
    # IMPORTANT
    #
    # Force Lahiri inside EVERY request.
    #
    # Swiss Ephemeris sidereal mode is global state.
    #
    # ========================================================
    with SWE_LOCK:

        # Re-apply the ephemeris path for every request.
        # FLG_SWIEPH silently falls back to Moshier if the files cannot be read.
        swe.set_ephe_path(EPHE_PATH)

        swe.set_sid_mode(
            swe.SIDM_LAHIRI
        )


        # ----------------------------------------------------
        # AYANAMSHA
        # ----------------------------------------------------
        ayanamsha_degree = swe.get_ayanamsa_ut(
            jd_ut
        )


        # ----------------------------------------------------
        # PLANETS
        #
        # Geocentric
        # Sidereal
        # Lahiri
        # True Node
        # ----------------------------------------------------
        output = {}

        for name, swiss_body in PLANETS.items():

            output[name] = calculate_planet(
                jd_ut,
                swiss_body,
            )


        # ----------------------------------------------------
        # KETU
        #
        # Always exactly 180° from TRUE RAHU
        # ----------------------------------------------------
        ketu_longitude = normalize_degree(
            output["Rahu"]["fullDegree"]
            + 180.0
        )


        ketu_position = get_rasi_nakshatra_pada(
            ketu_longitude
        )


        output["Ketu"] = {

            "fullDegree":
                ketu_longitude,

            "degreeDMS":
                degree_to_dms(
                    ketu_longitude
                ),

            "degreeInRasi":
                ketu_longitude % 30.0,

            "degreeInRasiDMS":
                degree_in_rasi_to_dms(
                    ketu_longitude
                ),

            "longitudeSpeed":
                output["Rahu"]["longitudeSpeed"],

            "retrograde":
                output["Rahu"]["retrograde"],

            "ephemerisUsed":
                output["Rahu"]["ephemerisUsed"],

            **ketu_position,
        }


        # ----------------------------------------------------
        # LAGNA / ASCENDANT
        #
        # Latitude + Longitude are used here.
        #
        # P = Placidus
        #
        # ascmc[0] = Ascendant
        # ----------------------------------------------------

        # Re-confirm Lahiri immediately before houses.
        swe.set_sid_mode(
            swe.SIDM_LAHIRI
        )


        cusps, ascmc = swe.houses_ex(
            jd_ut,
            data.latitude,
            data.longitude,
            b"P",
            HOUSE_FLAGS,
        )


        lagna_longitude = normalize_degree(
            ascmc[0]
        )


        lagna_position = get_rasi_nakshatra_pada(
            lagna_longitude
        )


        output["Ascendant"] = {

            "fullDegree":
                lagna_longitude,

            "degreeDMS":
                degree_to_dms(
                    lagna_longitude
                ),

            "degreeInRasi":
                lagna_longitude % 30.0,

            "degreeInRasiDMS":
                degree_in_rasi_to_dms(
                    lagna_longitude
                ),

            "retrograde":
                False,

            **lagna_position,
        }


        # ----------------------------------------------------
        # FINAL AYANAMSHA CHECK
        # ----------------------------------------------------
        ayanamsha_confirmation = swe.get_ayanamsa_ut(
            jd_ut
        )


    # --------------------------------------------------------
    # RESPONSE
    # --------------------------------------------------------
    return {

        "settings": {

            "zodiac":
                "sidereal",

            "ayanamsha":
                "Lahiri",

            "ayanamshaModeId":
                int(
                    swe.SIDM_LAHIRI
                ),

            "node":
                "true",

            "observation":
                "geocentric",

            "houseSystem":
                "Placidus",
        },


        "input": {

            "localDateTime":
                local_datetime.isoformat(),

            "utcDateTime":
                utc_datetime.isoformat(),

            "latitude":
                data.latitude,

            "longitude":
                data.longitude,

            "timezone":
                data.timezone,

            "julianDayUT":
                jd_ut,
        },


        "ayanamshaDegree":
            ayanamsha_degree,


        "ayanamshaDMS":
            degree_to_dms(
                ayanamsha_degree
            ),


        "ayanamshaConfirmationDegree":
            ayanamsha_confirmation,


        "output":
            output,
    }
