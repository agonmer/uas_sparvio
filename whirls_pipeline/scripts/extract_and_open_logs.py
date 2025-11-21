import subprocess
import pandas as pd

DacCon_jar_path = "/home/lorenzo/uas_sparvio/whirls_pipeline/src/DatCon/DatCon.4.3.0.jar"
ExtractDJI_jar_path = "/home/lorenzo/uas_sparvio/whirls_pipeline/src/DatCon/ExtractDJI.jar"

subprocess.run(["java", "-jar", ExtractDJI_jar_path])
subprocess.run(["java", "-jar", DacCon_jar_path])

pd.read_csv("/indian/UAS_project_data/2025_11_03_Arluno/M300/Logs/FLY032.csv")
