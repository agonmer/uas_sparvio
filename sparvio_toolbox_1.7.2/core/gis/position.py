import math
from . import utm

class Position:
    d2r = math.pi / 180.0

    def __init__(self, lat : float, lon : float):
        self.lat = lat
        self.lon = lon

    def is_valid(self):
        return True

    def distance_to(self, pos : 'Position') -> float:
        "Great-circle distance in meters to another position, using haversine formula"
        #Formula copied from http://stackoverflow.com/questions/365826/calculate-distance-between-2-gps-coordinates
        if not isinstance(pos, Position):
            raise Exception("Invalid position")
        d2r = Position.d2r
        dlon = (pos.lon - self.lon) * d2r
        dlat = (pos.lat - self.lat) * d2r
        a = math.pow(math.sin(dlat / 2.0), 2) + \
            math.cos(self.lat * d2r) * math.cos(pos.lat * d2r) * math.pow(math.sin(dlon / 2.0), 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        d = 6367000.0 * c
        return d

    def angle_to(self, pos : 'Position') -> float:
        """The direction to travel to get to pos.
           Returns unit is degrees, 0 means north, 90 means east."""
        #Formula modified from http://stackoverflow.com/questions/3809179/angle-between-2-gps-coordinates
        if not isinstance(pos, Position):
            raise Exception("Invalid position")
        dy = pos.lat - self.lat
        dx = math.cos(math.pi / 180.0 * self.lat) * (pos.lon - self.lon)
        angle = math.atan2(dx, dy)
        degrees = math.degrees(angle)
        if degrees < 0:
            return degrees + 360.0
        return degrees

    def move(self, distance : float, direction : float) -> 'Position':
        "Returns a new Position <distance> meters in <direction> degrees"
        #Adapted, bugfixed from http://stackoverflow.com/questions/5403455/gps-coordinates-meters

        distance_lon = distance * math.sin(math.radians(direction))
        distance_lat = distance * math.cos(math.radians(direction))

        equator_circumference = 40075160.0  #6371000.0 #meters
        polar_circumference = 40008000  #6356800.0   #meters
        deg_lat_per_m = 360.0 / polar_circumference

        deg_lon_per_m = 360.0 / (math.cos(math.radians(self.lat)) * equator_circumference)

        #Number of degrees longitude as you move east/west along the line of latitude
        deg_diff_long = distance_lon * deg_lon_per_m
        #Number of degrees latitude as you move north/south along the line of longitude:
        deg_diff_lat = distance_lat * deg_lat_per_m

        return Position(self.lat + deg_diff_lat, self.lon + deg_diff_long)

    def __repr__(self):
        return "(lat=%f, lon=%f)" % (self.lat, self.lon)

    def format_as_UTM(self) -> str:
        return utm.getUtm(self.lat, self.lon)

    def format_as_D(self) -> str:
        return "%.6f %.6f" % (self.lat, self.lon)

    def format_as_DM(self) -> str:
        if self.lat < 0:
            lat_sign = 'S'
        else:
            lat_sign = 'N'
        lat_minutes = (self.lat - int(self.lat)) * 60.0
        lat_text = u"%i\u00B0%.4f%s" % (int(abs(self.lat)), abs(lat_minutes), lat_sign)
        if self.lon < 0:
            lon_sign = 'W'
        else:
            lon_sign = 'E'
        lon_minutes = (self.lon - int(self.lon)) * 60.0
        lon_text = u"%i\u00B0%.4f%s" % (int(abs(self.lon)), abs(lon_minutes), lon_sign)
        return lat_text + ' ' + lon_text

    def format_as_DMS(self) -> str:
        if self.lat < 0:
            lat_sign = 'S'
            lat = -self.lat
        else:
            lat_sign = 'N'
            lat = self.lat
        lat_minutes = (lat - int(lat)) * 60.0
        lat_sec = (lat_minutes - int(lat_minutes)) * 60.0
        lat_minutes = int(lat_minutes)
        lat_text = u"%i\u00B0%02i'%02i\"%s" % (int(lat), lat_minutes, lat_sec, lat_sign)
        if self.lon < 0:
            lon_sign = 'W'
            lon = -self.lon
        else:
            lon_sign = 'E'
            lon = self.lon
        lon_minutes = (lon - int(lon)) * 60.0
        lon_sec = (lon_minutes - int(lon_minutes)) * 60.0
        lon_minutes = int(lon_minutes)
        lon_text = u"%i\u00B0%02i'%02i\"%s" % (int(lon), lon_minutes, lon_sec, lon_sign)
        return lat_text + ' ' + lon_text

    def equals(self, pos : 'Position') -> bool:
        return (math.isclose(self.lon, pos.lon) and
                math.isclose(self.lat, pos.lat))
