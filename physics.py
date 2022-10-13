import math

# Formulas from http://keisan.casio.com/exec/system/1224585971
def msl_pressure_from_alt(alt, pressure, temp=None):
    """Calculate pressure at sea level from
       pressure at specific altitude"""
    # (T + 273.15) / 0.0065 = 44330 if T=15
    if alt >= 44330:
        alt = 44329
        # TODO: Add a warning here
    T = temp if temp is not None else 15.
    return pressure * pow(((alt * 0.0065) / (T + 273.15)) + 1, 5.257)

#Not used any more, since hypsometric altitude model is more accurate
def alt_from_pressure(msl_pressure, pressure, temp=None):
    """Calculates an altitude from the difference of two pressure levels"""
    T = temp if temp is not None else 15.
    altitude = (T + 273.15) / 0.0065 * (pow(float(msl_pressure) / pressure, 1 / 5.257) - 1)
    # altitude = int(altitude * 10) / 10.0  #Round to one decimal
    return altitude

#Not used any more, since hypsometric altitude model is more accurate
def pressure_at_alt(msl_pressure, alt, temp=None):
    """Calculates pressure at specific altitude from pressure at sea level"""
    if msl_pressure is None or alt is None:
        return None
    T = temp if temp is not None else 15.
    return msl_pressure / pow(((alt * 0.0065) / (T + 273.15)) + 1, 5.257)

#Formulas from http://www.gribble.org/cycling/air_density.html

def saturation_water_pressure(temp):
    #T = air temperature (degrees Celsius)
    T = temp
    eso = 6.1078
    c0 = 0.99999683
    c1 = -0.90826951e-2
    c2 = 0.78736169e-4
    c3 = -0.61117958e-6
    c4 = 0.43884187e-8
    c5 = -0.29883885e-10
    c6 = 0.21874425e-12
    c7 = -0.17892321e-14
    c8 = 0.11112018e-16
    c9 = -0.30994571e-19
    p = c0 + T * (c1 + T * (c2 + T * (c3 + T * (c4 + T * (c5 + T * (c6 + T * (c7 + T * (c8 + T * c9))))))))
    #Es = Saturation water pressure, in hPa
    Es = eso / math.pow(p, 8)
    return Es

def saturation_mixing_ratio(temp, pressure):
    #T = air temperature (degrees Celsius)
    #pressure = station pressure
    if temp is None or pressure is None:
        return None

    E = saturation_water_pressure(temp)
    Psta = pressure/100.
    if abs(Psta - E) < 0.00001:
        return None
    W = 621.97 * E / (Psta - E)
    return W

def mixing_ratio(dew_point, pressure):
    #dew_point = dewpoint temperature (degrees Celsius)
    #pressure = station pressure
    return saturation_mixing_ratio(dew_point, pressure)

# a formula to verify relative humidity based on mixing ratio
def relative_humidity(mixing_ratio, saturation_mising_ratio):
    if mixing_ratio is None or saturation_mising_ratio is None or saturation_mising_ratio < 0.00001:
        return None
    return float(mixing_ratio)/saturation_mising_ratio * 100.

def get_dewpoint(temp, rh):
    "Temperature in C, relative humidity in percent (0-100)"
    # Uses Magnus approximation
    # From http://en.wikipedia.org/wiki/Dew_point#Calculating_the_dew_point
    #and http://www.calcunation.com/calculators/nature/dew-point.php
    b = 17.62
    c = 243.12
    try:
        gamma = math.log(rh / 100.0, math.e) + b * temp / (c + temp)
        return c * gamma / (b - gamma)
    except:
        return None

def get_virtual_temperature(temp, rh, pressure):
    dew_point = get_dewpoint(temp, rh)
    w = mixing_ratio(dew_point, pressure)
    temp_k = temp + 274.15 #Kelvin
    #Convert mixing ratio from g/kg till kg/kg (0.001)
    v_temp_k = (1 + 0.61 * 0.001 * w) * temp_k
    v_temp = v_temp_k - 274.15
    return v_temp

######################################################################

def get_dry_density(msl_pressure, alt, temp, humidity):
    "Density of the air (Rho), calculated from pressure, temperature and humidity"
    # From http://en.wikipedia.org/wiki/Density_of_air
    #Density of dry air:
    alt_pressure = pressure_at_alt(msl_pressure, alt, temp)
    temp_kelvin = temp + 273.15
    density_dry = alt_pressure / (287.058 * temp_kelvin)
    return density_dry


def get_density(temp, humidity, pressure):
    "Calculates Rho (kg/m3)"
    if temp is None or humidity is None or pressure is None:
        return None
    dewpoint = get_dewpoint(temp, humidity)
    if dewpoint is None:
        return None
    pressure_vapor = saturation_water_pressure(dewpoint) * 100
    pressure_dry_air = pressure - pressure_vapor
    temp_kelvin = temp + 273.15
    Rv = 461.4964
    Rd = 287.0531
    # Rho (kg/m3)
    return (pressure_dry_air / (Rd * temp_kelvin)) + \
           (pressure_vapor / (Rv * temp_kelvin))

######################################################################

# http://mc-computing.com/Science_Facts/Water_Vapor/Relative_Humidity.html
# " In meteorological practice, relative humidity is given over liquid water"

# "The equations by Hyland and Wexler, the nearly identical equation
# by Wexler, and the equation by Sonntag are the most commonly used
# equations among radiosonde manufacturers and should be used in upper
# air applications to avoid inconsistencies."

#TODO: Use this:
def saturation_water_pressure_hyland_wexler(temp):
    "Uses Hyland-Wexler algorithm as is standard for radiosonde"
    # See for example http://cires1.colorado.edu/~voemel/vp.pro
    T = temp + 274.15  #celcius to kelvin
    return math.exp(-0.58002206e4 / T
                    + 0.13914993e1
                    - 0.48640239e-1 * T
                    + 0.41764768e-4 * T * T
                    - 0.14452093e-7 * T * T * T
                    + 0.65459673e1 * math.log(T))
