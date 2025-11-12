# Open flight record
import pandas as pd
import subprocess

export_sh = "/home/lorenzo/uas_sparvio/whirls_pipeline/src/FlightRecord_txt_to_csv.sh"
input_file = "/indian/UAS_project_data/2025_11_03_Arluno/M300/Flight_record/DJIFlightRecord_2025-11-03_[11-34-21].txt"
ouput_file = "/indian/UAS_project_data/2025_11_03_Arluno/M300/Flight_record/DJIFlightRecord_2025-11-03_[11-34-21].csv"
subprocess.run([export_sh, input_file, ouput_file])


fr_df = pd.read_csv(ouput_file)
for col in fr_df.columns:
    print(col)