# geo_log.py: Referencing all measurements to a geographical location
# consisting of Position (lat and lon) and altitude (above the WGS-84 ellipsoid)

from reactive.observable import ListState, Scheduler
from reactive.indexeddict import Entry
from .log import ValuesLog
from .position import Position
from typing import *

def get_lat(entry : Entry) -> Optional[float]:
    # All Positions are required to be valid, so further test is not needed
    if 'pos' in entry.data: # and entry.data['pos'].lat is not None:
        return entry.data['pos'].lat
    if 'lat' in entry.data:
        return entry.data['lat']
    return None

def get_lon(entry : Entry) -> Optional[float]:
    # All Positions are required to be valid, so further test is not needed
    if 'pos' in entry.data: # and entry.data['pos'].lon is not None:
        return entry.data['pos'].lon
    if 'lon' in entry.data:
        return entry.data['lon']
    return None

def interpolate(earlier_key : float, earlier_value : float,
                later_key : float, later_value : float,
                key) -> float:
    "Generic linear interpolation"
    if later_key == earlier_key:
        return earlier_value
    return (earlier_value +
            (key - earlier_key) *
            (later_value - earlier_value) / (later_key - earlier_key))

# Actually this Log should not be directly mutable as its derived from another Log
class DerivedGeoLog(ValuesLog):
    """Replicates the entries of <source>, but adds 'pos' and 'alt' for
       entries that lack them, by interpolation. Source entries are
       not added until such interpolation is possible. All entries
       will thus have 'pos' and 'alt'.
    """
    def __init__(self, scheduler : Scheduler[Callable], source : ValuesLog):
        super().__init__()
        self._source = source
        self._source.add_observer((scheduler, self._on_change),
                                  initial_notify = True)
        self._source_state = ListState()
        # Entries in source:
        self._earlier_lat_entry : Entry = None  #lat or pos
        self._earlier_lon_entry : Entry = None  #lon or pos
        self._earlier_alt_entry : Entry = None  #alt

    def _on_change(self):
        diff = self._source.diff(self._source_state)
        if diff.mutations:
            # Some entries changed. Recalculate all of them, for simplicity.
            self.clear()
            diff = self._source_state.as_diff()
            self._earlier_lat_entry = None
            self._earlier_lon_entry = None
            self._earlier_alt_entry = None
        else:
            # Must set the revision for future source.diff() to work
            self._source_state.revision = self._source.revision.get()

        later_lat_entry = None
        later_lon_entry = None
        later_alt_entry = None

        changed = False
        for entry in self._source.diff_to_entries(diff):
            # Optimization when an entry can be used as-is
            if 'pos' in entry.data and entry.data.get('alt', None) is not None:
                self._earlier_lat_entry = entry
                self._earlier_lon_entry = entry
                self._earlier_alt_entry = entry
                later_lat_entry = None
                later_lon_entry = None
                later_alt_entry = None
                self._append_entry(entry)
                self._source_state.entry_count = entry.get_ix(self._source) + 1

                changed = True
                continue

            pos : Optional[Position] = None
            if 'pos' in entry.data:
                self._earlier_lat_entry = entry
                self._earlier_lon_entry = entry
                later_lat_entry = entry
                later_lon_entry = entry
                pos = entry.data['pos']  #No need to create a new Position
            else:
                if get_lat(entry) is not None:
                    self._earlier_lat_entry = entry
                    later_lat_entry = entry
                if get_lon(entry) is not None:
                    self._earlier_lon_entry = entry
                    later_lon_entry = entry

            if entry.data.get('alt', None) is not None:
                self._earlier_alt_entry = entry
                later_alt_entry = entry

            if later_lat_entry is None:
                for later_entry in self._source[entry.get_ix(self._source) + 1:]:
                    if get_lat(later_entry) is not None:
                        later_lat_entry = later_entry
                        break
                if later_lat_entry is None:
                    #No later 'lat' found, so we can't process more entries yet
                    break

            if later_lon_entry is None:
                for later_entry in self._source[entry.get_ix(self._source) + 1:]:
                    if get_lon(later_entry) is not None:
                        later_lon_entry = later_entry
                        break
                if later_lon_entry is None:
                    #No later 'lon' found, so we can't process more entries yet
                    break

            if later_alt_entry is None:
                for later_entry in self._source[entry.get_ix(self._source) + 1:]:
                    if later_entry.data.get('alt', None) is not None:
                        later_alt_entry = later_entry
                        break
                if later_alt_entry is None:
                    #No later 'alt' found, so we can't process more entries yet
                    break

            if (self._earlier_lat_entry is not None and
                self._earlier_lon_entry is not None and
                self._earlier_alt_entry is not None):

                if pos is None:
                    lat = interpolate(self._earlier_lat_entry.key,
                                      get_lat(self._earlier_lat_entry),
                                      later_lat_entry.key,
                                      get_lat(later_lat_entry),
                                      entry.key)
                    lon = interpolate(self._earlier_lon_entry.key,
                                      get_lon(self._earlier_lon_entry),
                                      later_lon_entry.key,
                                      get_lon(later_lon_entry),
                                      entry.key)
                    pos = Position(lat, lon)
                if later_alt_entry == entry:
                    alt = entry.data['alt']
                else:
                    alt = interpolate(self._earlier_alt_entry.key,
                                      self._earlier_alt_entry.data['alt'],
                                      later_alt_entry.key,
                                      later_alt_entry.data['alt'],
                                      entry.key)

                new_entry = entry.copy()
                if 'lat' in new_entry.data:
                    del new_entry.data['lat']
                if 'lon' in new_entry.data:
                    del new_entry.data['lon']
                new_entry.data['alt'] = alt
                new_entry.data['pos'] = pos
                self._append_entry(new_entry)
                self._source_state.entry_count = entry.get_ix(self._source) + 1
                changed = True

            if later_lat_entry == entry:
                self._earlier_lat_entry = entry
                later_lat_entry = None  # Need a new later entry
            if later_lon_entry == entry:
                self._earlier_lon_entry = entry
                later_lon_entry = None  # Need a new later entry
            if later_alt_entry == entry:
                self._earlier_alt_entry = entry
                later_alt_entry = None  # Need a new later entry

        if changed:
            self.notify_observers()
