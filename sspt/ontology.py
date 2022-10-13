# ontology.py: Represents ontology knowledge as a Python object
#
# As of now, the global ontology is populated by loading messages.py

from .type_hints import *

from .constants import *

#TODO: Merge RegistryClass and SymbolTable into Ontology?

#class UnknownConstant(Exception):
#    pass

#Registry is a mapping index -> buffer/schema
class RegistryClass(object):
    def __init__(self):
        #Map from index to pyObj (pyObjects.SspPyObj)
        self._pyObjs = {}

        #Optimization to lookup labelled entries.
        self._labels : Dict[str, int] = {}   #Mapping label -> index
        #self.sspBin = {} #Map index -> sspBin definition

        #Map from index to SSP-ASCII representation of the value
        self.sspAScii = {}

    def has_key(self, index : int):
        return index in self._pyObjs
    def __contains__(self, index : int):
        return index in self._pyObjs
    def get(self, index : int):  #TODO: Merge into get_by_regIx() for clarity
        "Returns pyObj"
        return self._pyObjs.get(index, None)
    def get_by_regIx(self, index : RegIx):
        "Returns pyObj"
        return self._pyObjs.get(index, None)
    def get_by_label(self, label : str):
        "Returns pyObj"
        if not label in self._labels:
            return None
        return self._pyObjs[self._labels[label]]
    def get_by_c_name(self, c_name : str):
        # Not optimized!
        for obj in self._pyObjs.values():
            if obj.__dict__.get('c_name', None) == c_name:
                return obj
        return None
    def add(self, index : int, obj, label : Optional[str] = None):
        if index in self._pyObjs.keys():
            if not self._pyObjs[index] == obj:
                #Decide here whether entries may be replaced (should
                #be OK for regIx values in the temporary range)
                #print('Warning: Replacing registry entry %d' % index)
                raise obj.source.error("Can't add %s to registry as index %d, as that is already occupied by %s (from %s)" % (obj, index, self._pyObjs[index], self._pyObjs[index].source))
        self._pyObjs[index] = obj
        if obj.regIx is not None and obj.regIx != index:
            #The rest only applies the first time the object is added
            #Subsequent additions mark aliases from other entries
            assert label is None
            return
        if obj._label is not None:
            assert label is None or label == obj._label
            label = obj._label
        if label is not None:
            if label in self._labels:
                oldObj = self._pyObjs[self._labels[label]]
                print('Label "%s" already registered to %s added from %s' % \
                    (label, oldObj, repr(oldObj.source)))
            if label in self._labels:
                assert self._labels[label] == index
            else:
                self._labels[label] = index
            obj._label = label
        obj.regIx = index
    def indices(self):
        return self._pyObjs.keys()
    def find(self, obj):
        """Searches the registry for the first index whose definition is
           structurally equal to pyObject <obj>. Returns None if
           there's no match.
        """
        if index in sorted(self._pyObjs.keys()):
            if self._pyObjs[index].equals(obj):
                return index
        return None

class SymbolTable(object):
    def __init__(self):
        #self.names = {}  #map index -> string
        self.name_map = {}  #map string -> index
        self.pyObjs = {} #map index -> pyObjects.Symbol
        self.unindexed_objs = {} #map string -> pyObjects.Symbol without index

    def add(self, symbolObj):
        "Add a new symbol or update the existing symbol with more data"
        if symbolObj.index is None:
            if symbolObj.name in self.unindexed_objs and \
               self.unindexed_objs[symbolObj.name] != symbolObj:
                raise Exception("Trying to add duplicate object for symbol %s without known index" % symbolObj.name)
            self.unindexed_objs[symbolObj.name] = symbolObj
            return
        if symbolObj.name is not None and symbolObj.name in self.unindexed_objs:
            prior_def = self.unindexed_objs[symbolObj.name]
            assert prior_def.index is None
            assert prior_def.name == symbolObj.name
            prior_def.add_info(symbolObj)
            del self.unindexed_objs[symbolObj.name]
            symbolObj = prior_def
        self.pyObjs[symbolObj.index] = symbolObj
        self.name_map[symbolObj.name] = symbolObj.index

    def index_to_obj(self, index):
        #if not index in self.pyObjs:
        #    import pyObjectsS
        #    self.pyObjs[index] = pyObjects.Symbol(index=index)
        #return self.pyObjs[index]
        return self.pyObjs.get(index, None)

    def name_to_obj(self, name):
        if name.startswith("SYM"):
            index = int(name[3:])
            return self.index_to_obj(index)
        if name in self.name_map:
            return self.pyObjs[self.name_map[name]]
        if name in self.unindexed_objs:
            return self.unindexed_objs[name]
        #if create:
        #    import pyObjects
        #    obj = pyObjects.Symbol(name=name)
        #    self.unindexed_objs[name] = obj
        #    return obj
        return None

    def indices(self):
        return self.pyObjs.keys()

    def unindexed_names(self):
        return self.unindexed_objs.keys()


class Ontology(object):
    """An ontology is all or a subset of the global set of symbols and
       constants, stored in pyObj format"""
    def __init__(self, inherits=None):
        "<inherits> is an optional list of ontologies where lookups are tried"
        self.registry = RegistryClass()
        self.symtable = SymbolTable()
        if inherits is None:
            self.inherits = []
        elif isinstance(inherits, list):
            self.inherits = inherits
        else:
            self.inherits = [inherits]
        self.name = '?'
    def add_file(self, filename, ignore_files=None):
        from . import parse_ontology
        if ignore_files is None:
            ignore_files = []
        parse_ontology.parse(filename, self, ignore_files)

    def add_entry(self, index, obj, label=None):
        #TODO: Check if already existing
        self.registry.add(index, obj, label)
    def add_entries(self, entries):
        #TODO: Check if already existing
        for (index, obj) in entries.items():
            self.registry.add(index, obj)
    def get_by_regIx(self, index):
        obj = self.registry.get_by_regIx(index)
        if obj:
            return obj
        for o in self.inherits:
            obj = o.get_by_regIx(index)
            if obj:
                return obj
        return None
    def add_symbol(self, symbolObj):
        #TODO: Check if already existing
        #print 'add_symbol', symbolObj.index, symbolObj.name, 'to', self.name
        self.symtable.add(symbolObj)
    def create_symbol_from_name(self, name):
        "Creates a symbol without knowing the index"
        from . import pyObjects
        #print 'create_symbol_from_name', name
        if name.startswith("SYM"):
            index = int(name[3:])
            obj = pyObjects.Symbol(index=index)
        else:
            obj = pyObjects.Symbol(name=name)
        self.add_symbol(obj)
        return obj
    def name_to_symbol(self, name, create=False):
        "Returns None if not found"
        obj = self.symtable.name_to_obj(name)
        if obj:
            return obj
        for o in self.inherits:
            obj = o.name_to_symbol(name)
            if obj:
                return obj
            #print "No sym ", name, "in parent", o.name
        if not create:
            return None
        #print "Didn't find sym", name, "in", self.symtable.name_map.keys(), 'in', self.name
        return self.create_symbol_from_name(name)
    def ix_to_symbol(self, index):
        assert index > 0
        obj = self.symtable.index_to_obj(index)
        if obj:
            return obj
        for o in self.inherits:
            obj = o.ix_to_symbol(index)
            if obj:
                return obj
        return None
    def label_to_registry_entry(self, label):
        "Returns pyObj"
        entry = self.registry.get_by_label(label)
        if entry:
            return entry
        for o in self.inherits:
            entry = o.label_to_registry_entry(label)
            if entry:
                return entry
        return None
    def get_registry_entry_by_c_name(self, c_name):
        entry = self.registry.get_by_c_name(c_name)
        if entry:
            return entry
        for o in self.inherits:
            entry = o.get_registry_entry_by_c_name(c_name)
            if entry:
                return entry
        return None

    def iterate_over_symbol_type(self, symbol_type):
        """Returns all Symbols that have <symbol_type>. <symbol_type> is
           string 'metadata' or 'event'. Only returns Symbols that
           have a regIx.
        """
        for o in self.inherits:
            yield from o.iterate_over_symbol_type(symbol_type)
        for symbol in self.symtable.pyObjs.values():
            if symbol.symbol_type == symbol_type:
                yield symbol

class Locale:
    """A locale maps symbols to units, display name and value formatting
       based on ontology and user preferences, for use in user
       interaction. Locales are not used in internal encoding or
       processing.
    """
    def get_long_name(self, symbol : str) -> str:
        "Default implementation -- may override"
        symObj = global_ontology.symtable.name_to_obj(symbol)
        if symObj is None:
            return symbol
        if symObj.long_name is None:
            return symbol
        return symObj.long_name
    def get_unit_name(self, symbol : str) -> str:
        symObj = global_ontology.symtable.name_to_obj(symbol)
        if symObj is None:
            return ''
        if symObj.unit is None:
            return ''
        return symObj.unit
    def format_as_user_unit(self, symbol : str, value : Any) -> str:
        "Do unit translation to the users preferred choice and format as string"
        # TODO: Could consider the SSP type as fixpoints have
        # information on significant digits.
        return str(value)
        raise NotImplementedError()
    def from_user_unit(self, symbol : str, user_value : str) -> Any:
        """Translate a value from the locales representation of <symbol> to
           the standard numerical value"""
        raise NotImplementedError()
    def get_documentation(self, symbol : str) -> str:
        symObj = global_ontology.symtable.name_to_obj(symbol)
        if symObj is None:
            return ''
        if symObj.doc is None:
            return ''
        return symObj.doc

# The inheritance of global_ontology will change as more ontology
# objects are added. global_ontology is not changed, to allows others
# to use the same reference
global_ontology = Ontology()

# TODO: 'Ontology' is not the best place for locale
global_locale = Locale()

def inherit_ontology():
    """Inserts and returns a new Ontology object in the inheritance chain,
       just before global_ontology (which is always the top object)"""
    #Doesn't replace global_ontology, in case there's other references
    #to the object.
    ont = Ontology(inherits=global_ontology.inherits[:])
    global_ontology.inherits = [ont]
    return ont
