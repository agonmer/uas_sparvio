import pandas as pd

def PreprocessFlightRecord(
        file:str,
        vars_to_keep:list=[ # [] == keep all 
            'OSD.latitude',
            'OSD.longitude',
            'OSD.height',
            'OSD.altitude',
            'OSD.xSpeed',
            'OSD.ySpeed',
            'OSD.zSpeed',
            'OSD.pitch',
            'OSD.roll',
            'OSD.yaw',
            'CUSTOM.dateTime_dt'
            ],
        itime_int:list=[None,None], # Index interval to consider
        ) -> pd.DataFrame:
    
    import numpy as np
    import pandas as pd

    fr_df = pd.read_csv(file[:-3] + "csv")

    # Convert to datetime
    fr_df['CUSTOM.dateTime_dt'] = pd.to_datetime(fr_df['CUSTOM.dateTime'], format='ISO8601',utc=True)
    fr_df['CUSTOM.dateTime_dt']

    # Drop useless vars
    if vars_to_keep != []:
        fr_df = fr_df[vars_to_keep]
    
    # Reduce period
    fr_df = fr_df[itime_int[0]:itime_int[1]]

    # Filter sampling errors.
    median_time = fr_df['CUSTOM.dateTime_dt'].median()
    i_to_drop = fr_df.loc[(fr_df['CUSTOM.dateTime_dt'] > median_time+pd.Timedelta(1,'day')) | (fr_df['CUSTOM.dateTime_dt'] < median_time-pd.Timedelta(1,'day'))].index
    print(f"Dropping {len(i_to_drop)} rows with datetime errors.")
    fr_df.drop(axis=0, index=i_to_drop,inplace=True)

    return fr_df


def PlotFlightRecord(
        fr_df:pd.DataFrame,
):
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import seaborn as sns
    sns.set_theme(style="darkgrid")

    # Plot trajectory
    fig,axes=plt.subplots(1,3,figsize=(18,5))
    sns.scatterplot(
            data=fr_df,
            x='OSD.longitude',
            y='OSD.latitude',
            hue='CUSTOM.dateTime_dt',
            legend=False,
            ax=axes[0],
            edgecolor=None,
            alpha=0.3,
            palette='viridis',
        )

    sns.scatterplot(
            data=fr_df,
            x='CUSTOM.dateTime_dt',
            y='OSD.height',
            hue='CUSTOM.dateTime_dt',
            legend=False,
            ax=axes[1],
            edgecolor=None,
            alpha=0.3,
            palette='viridis',    
        )
    
    sns.scatterplot(
            data=fr_df,
            x='CUSTOM.dateTime_dt',
            y='OSD.yaw',
            hue='CUSTOM.dateTime_dt',
            legend=False,
            ax=axes[2],
            edgecolor=None,
            alpha=0.3,
            palette='viridis',    
        )

    axes[1].set_xlabel('Time (UTC)')
    fig.autofmt_xdate(rotation=30, ha='right')

    plt.plot()

    return 
