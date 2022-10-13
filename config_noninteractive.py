# config_noninteractive.py: Configures Sparvio Toolbox for a specific use case
#
# This file is imported as a python module, making the settings
# globally available in Sparvio toolbox

python_run = []
python_eval = []

##############################
# Default serial/USB ports to try to connect to:
#serial_ports = ['COM1:56800bps,hex,probe,keepalive=3000',
#         'COM2:RR1']
# If defined, RX/TX ports for UDP link
#udp_ports.append( (2000,2001) )

##############################
# Software components

local.append('core.systemview.SystemViewComponent(name="view",serial=1,priority=45)')
