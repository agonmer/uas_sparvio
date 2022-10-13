# config_interactive.py: Configures Sparvio Toolbox for a specific use case
#
# This file is imported as a python module, making the settings
# globally available in Sparvio toolbox

##############################
# What network interface and port to serve the HTTP interface on.
# Set either to None to disable HTTP server.
web_hostname = 'localhost'
web_port = 8080

python_run = []
python_eval = []

##############################
# Default settings of InfluxDB:
influx_host = 'localhost'
influx_port = 8086   #Default InfluxDB port
influx_user = 'admin'
influx_password = 'admin'
# Settings as accessed by default Sparvio Grafana dashboards:
influx_database = 'Sparvio'
influx_dbname = 'live'

##############################
# Only used when Toolbox is asked to launch Grafana as a convenience
# for the user. Must correspond to the Grafana port (Grafana uses 3000
# as default).
grafana_port = 3000
grafana_auto_launch = False

##############################
# Default serial/USB ports to try to connect to:
#serial_ports = ['COM1:56800bps,hex,probe,keepalive=3000',
#         'COM2:RR1']
# If defined, RX/TX ports for UDP link
#udp_ports.append( (2000,2001) )

##############################
# Software components

local.append('core.systemview.DynamicViewerComponent(name="visualizer",serial=1,priority=45)')
