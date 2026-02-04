import pandas as pd

def AddTiltAngle(fr_df:pd.DataFrame) -> pd.DataFrame: 
    deg_to_rad_list = ['OSD.roll','OSD.pitch']

    import numpy as np

    for var in deg_to_rad_list:
        fr_df[var+'_rad'] = np.deg2rad(fr_df[var])

    fr_df = fr_df.assign(tilt_rad = np.arctan(np.sqrt(np.cos(fr_df['OSD.roll_rad'])**2 * np.sin(fr_df['OSD.pitch_rad'])**2 + np.sin(fr_df['OSD.roll_rad'])**2)) / (np.cos(fr_df['OSD.roll_rad']) * np.cos(fr_df['OSD.pitch_rad'])))
    fr_df['tilt_deg'] = np.rad2deg(fr_df['tilt_rad'])

    return fr_df


def AddGroundSpeed(fr_df:pd.DataFrame) -> pd.DataFrame: 
    import numpy as np
    fr_df['GSpeed'] = np.sqrt(fr_df['OSD.xSpeed']**2+fr_df['OSD.ySpeed']**2)
    return fr_df