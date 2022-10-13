# KML view. There are three way to display logs:
# * Display a single point with all most recent values
# * Display one point for each log entry (slow for many points)
# * Display a line for each log (no numeric data)

import os.path
from datetime import datetime

from reactive.observable import Scheduler, Job, SimpleScheduler
from reactive.eventthread import EventThread, CooldownObservable

from sspt.type_hints import *
from sspt.ontology import global_locale
from .log import Log, LocalizedLog

# The 'top' KML file tells Google Earth to reload the file with the
# list of components every 15 seconds, to check for new component
# files:
top_template = \
    """<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://earth.google.com/kml/2.1">
    <Document>
      <NetworkLink>
        <name>Sparvio data series</name>
        <Link>
          <href>%s</href>
          <refreshMode>onInterval</refreshMode>
        <refreshInterval>15</refreshInterval>
        </Link>
      </NetworkLink>
    </Document>
    </kml>"""

# The 'components' KML file links to one file for each component:
components_template = \
    """<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://earth.google.com/kml/2.1">
    <Document>
    %s
    </Document>
    </kml>"""

link_template = \
    """  <NetworkLink>
        <name>%s</name>
        <Link>
          <href>%s</href>
          <refreshMode>onInterval</refreshMode>
        <refreshInterval>5</refreshInterval>
        </Link>
      </NetworkLink>
    """

linestring_component_template = \
"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.1">
<Document>
  <Placemark>
    <name>{name}</name>
    <LineString>
      <extrude>1</extrude>
      <tessellate>1</tessellate>
      <altitudeMode>absolute</altitudeMode>
      <coordinates>{coordinates}
      </coordinates>
      </LineString>
  </Placemark>
</Document>
</kml>"""

single_component_template = \
"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.1">
<Document>
  <Placemark>
    <name>{name}</name>
    <Point>
      <coordinates>{lon:.6f},{lat:.6f}</coordinates>
    </Point>
    <ExtendedData>
{extra_data}
  </ExtendedData>
  </Placemark>
</Document>
</kml>"""

extra_data_template = \
"""      <Data name="%s">
        <displayName>%s</displayName>
        <value>%s</value>
      </Data>
"""

component_template = \
"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.1">
<Document>
{placemarks}
</Document>
</kml>"""

placemark_template = \
"""  <Placemark>
    <name>{name}</name>
    <Point>
      <coordinates>{lon},{lat}</coordinates>
    </Point>
    <ExtendedData>
{extra_data}
    </ExtendedData>
  </Placemark>
"""

import threading # For Lock

# Could support changing the models at runtime by accepting
# ObservableSet for the models
class KmlView:
    def __init__(self,
                 scheduler : Scheduler[Callable],
                 line_models: List[LocalizedLog]=[],
                 single_models: List[Log]=[],
                 points_models: List[LocalizedLog]=[]):
        self.linestring_models = line_models[:]
        self.single_models = single_models[:]
        self.points_models = points_models[:]
        self.directory = ""
        self.top_filename = "sparvio.kml"
        self.components_filename = "sparvio_components.kml"
        self._files = []
        self._components = {}
        self._is_first_processing = True
        #All logs with unprocessed changes
        self._changed_logs : Scheduler[Log] = SimpleScheduler()
        self._change_timer = CooldownObservable(delay_sec = 0.5,
                                                cooldown_sec = 2,
                                                flush_on_exit = True,
                                                observer=(scheduler,
                                                          self._process_logs))
        # When some Log is changed, it is posted to self._changed_logs
        # which starts _change_timer to countdown, which will trigger
        # self._process_logs() upon timeout.
        self._changed_logs.add_observer(self._change_timer.get_job(),
                                        initial_notify = True)
        all_models = self.linestring_models + \
            self.single_models + self.points_models
        for log in all_models:
            log.add_observer((self._changed_logs, log),
                             initial_notify = True)

    def _generate_top_file(self) -> None:
        path = os.path.join(self.directory, self.top_filename)
        with open(path, 'w') as f:
            f.write(top_template % self.components_filename)

    def _generate_components_file(self, components : Mapping) -> None:
        self._components = components
        text = ""
        for c in components:
            if c['name'] is not None:
                text += link_template % (c['name'], c['filename'])
        path = os.path.join(self.directory, self.components_filename)
        with open(path, 'w') as f:
            f.write((components_template % text))

    def _generate_single_file(self, c : dict) -> None:
        if c['name'] is None:
            return
        path = os.path.join(self.directory, c['filename'])
        extra_data = ''
        for var in c:   #['defParams']:
            if var in ['defParams', 'filename']:
                continue
            if not var in c:
                print('kml_view warning: No value for defParam', var, 'in', c['name'])
                continue
            extra_data += extra_data_template % (var, var, c[var])
        c['extra_data'] = extra_data
        with open(path, 'w') as f:
            f.write(single_component_template.format(**c))

    def _generate_points_file(self, path : str,
                              log : LocalizedLog) -> None:
        "Generates a KML file with one point for every entry in the log"
        placemarks = ''
        for ix in range(log.get_count()):
            extra_data = ''
            valuemap, ts = log.values_and_ts_by_ix(ix)
            if 'lat' not in valuemap or 'lon' not in valuemap:
                continue  #No position to use
            for (key, value) in valuemap.items():   #['defParams']:
                if key in ['defParams', 'filename']:
                    continue
                extra_data += extra_data_template % \
                    (key, global_locale.get_long_name(key), global_locale.format_as_user_unit(key, value))
            try:
                ts_str = datetime.fromtimestamp(ts).strftime('%Y-%m-%dZ%H:%M:%S')
                placemarks += placemark_template.format(name=ts_str,
                                                        extra_data=extra_data,
                                                        **valuemap)
            except Exception as ex:
                # Some missing key, probably
                import traceback
                traceback.print_exc()
                pass
        with open(path, 'w') as f:
            f.write(component_template.format(placemarks=placemarks))

    def _generate_linestring_file(self, path : str,
                                  name : str,
                                  log : LocalizedLog) -> None:
        "Generates a KML file with a linestring for the log"
        coordinates = ''
        for ix in range(log.get_count()):
            valuemap : Mapping[Var, Any] = log.values_by_ix(ix)
            if coordinates != '':
                coordinates += ' '  #KML needs space between entries
            coordinates += '{lon:.6f},{lat:.6f}'.format(**valuemap)
            if 'alt' in valuemap:
                coordinates += ',{alt:.2f}'.format(**valuemap)
        with open(path, 'w') as f:
            f.write(linestring_component_template.format(name=name,
                                                         coordinates=coordinates))

    def _process_logs(self):
        "Called on the internal thread when it's time to process changes"
        # Newly regenerated files
        if self._is_first_processing:
            self._is_first_processing = False
            self._generate_top_file()

        components = [] #Each entry is dict with keys 'name' and 'filename'

        changed_logs = self._changed_logs.pop_all_jobs()
        if len(changed_logs) == 0:
            return

        # A series of points
        for object_log in self.points_models:
            if object_log not in changed_logs:
                continue
            name = object_log.most_recent_value('name', 'Measurements')
            filename = 'sparvio_' + name + '_points.kml'
            path = os.path.join(self.directory, filename)
            self._generate_points_file(path, object_log)
            components.append({'name': name, 'filename': filename,
                               'path': path})

        # A linestring
        for object_log in self.linestring_models:
            if object_log not in changed_logs:
                continue
            name = object_log.most_recent_value('name', 'UAV')
            filename = 'sparvio_' + name + '_line.kml'
            path = os.path.join(self.directory, filename)
            self._generate_linestring_file(path, name + ' track', object_log)
            components.append({'name': name, 'filename': filename,
                               'path': path})

        # A single point with the most recent data
        for object_log in self.single_models:
            if object_log not in changed_logs:
                continue
            c = {}
            c['name'] = object_log.most_recent_value('name', 'UAV')
            if c['name'] == 'components':
                continue  #Illegal name due to file name conflict
            for key in object_log.all_keys():
                c[key] = object_log.most_recent_value(key)
            if c.get('lat', None) is None or c.get('lon', None) is None:
                continue
            c['filename'] = 'sparvio_' + c['name'] + '_single.kml'
            self._generate_single_file(c)
            components.append(c)
        if components != self._components:
            self._generate_components_file(components)

    def launch(self):
        "Shows the top KML file in the default application, probably Google Earth"
        import os
        # Assumes .kml is associated with Google Earth or equivalent
        path = os.path.join(self.directory, self.top_filename)
        os.startfile(path)

    def on_stop(self):
        # TODO: Cleanup files
        pass
