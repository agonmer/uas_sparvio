# parse_ontology.py: Parse Sparvio ontology text files to Ontology and pyObjects

# Could be merged into sspascii_pyobj.py

import os
import typing
from . import ascii
from .source import Source

include_paths : typing.List[str] = []

verbose = False

#Do after defining no_source to avoid recursive imports:
from .pyObjects import Symbol

default_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "ontology")

def find_file(curr_dir, filename):
    "Looks for <filename> in <curr_dir>, in include paths, etc."
    if os.path.exists(filename):
        return filename  #Absolute path
    if os.path.exists(os.path.join(curr_dir, filename)):
        return os.path.join(curr_dir, filename)  #In current directory
    for path in include_paths:
        if os.path.exists(os.path.join(path, filename)):
            return os.path.join(path, filename)
    #Last, look in the default directory with this script
    if os.path.exists(os.path.join(default_dir, filename)):
        return os.path.join(default_dir, filename)
    #print 'file_dir', file_dir, os.path.join(file_dir, filename)
    msg = 'Could not find file "%s" (curr_dir=%s, abs=%s, include=%s)' % \
        (filename, curr_dir, os.path.abspath(curr_dir), include_paths)
    print(msg)
    raise Exception(msg)

class Context:
    "State relevant when parsing ontologies without complete index assignments"
    # Used when filling in unspecified indices
    def __init__(self):
        self.lowest_suggested_symbol_ix : int = None
        self.lowest_suggested_reg_ix : int = None


def assignments_to_dict(s, source):
    "Parses the form aa=bb, cd=ef to a dictionary of strings"
    dic = {}
    for assignment in s.split(','):
        if not '=' in assignment:
            raise source.error('Wrong format in "%s"' % s)
        key, value = assignment.split('=', 1)
        dic[key.strip()] = value.strip()
    return dic

def parse_line(source, infile, line, ontology, ignore_files, context=None):
    "When context is != None, fill in missing indices and return the new line. If the line is unchanged, None is returned"
    line = line.strip()
    if line == '' or line.startswith('#'):
        return

    if line.startswith("include "):
        curr_dir = os.path.dirname(infile)
        filename = line.split()[1]
        resolved_file = find_file(curr_dir, filename)
        parse(resolved_file, ontology, ignore_files, context)
        return

    if line.startswith("scope "):
        if context is None:
            return  # Ignore
        dic = assignments_to_dict(line[len("scope "):], source)
        if 'sym' in dic:
            lower = dic['sym'].split('-', 1)[0] #Discard upper limit
            context.lowest_suggested_symbol_ix = int(lower)
        if 'reg' in dic:
            lower = dic['reg'].split('-', 1)[0] #Discard upper limit
            context.lowest_suggested_reg_ix = int(lower)
        return

    if line.startswith("SYM"):
        ix, rest = line[3:].split(' ', 1)
        if ix == 'x' and context:
            if context.lowest_suggested_symbol_ix is None:
                raise source.error("No known symbol index to suggest")
            newIx = context.lowest_suggested_symbol_ix
            context.lowest_suggested_symbol_ix += 1
            return "SYM%s %s" % (newIx, rest)
        try:
            ix = int(ix)
        except:
            raise source.error('Invalid symbol index')
        try:
            name, rest = rest.split(':', 1)
        except:
            source.print_warning('Cannot parse "%s"' % line)
            return
        name = name.strip()
        if ' ' in name:
            (name, symbol_type) = name.split(' ', 1)
            name = name.strip()
            symbol_type = symbol_type.strip()
        else:
            symbol_type = None
        if symbol_type == '':
            symbol_type = None
        if symbol_type not in [None, 'metadata', 'event']:
            raise source.error('Invalid symbol type %s' % symbol_type)
        parts = rest.split(',')
        define = ''
        if len(parts) > 0:
            define = parts[0].strip()
        if define == '':
            #Default
            define = name
        prior_def = ontology.ix_to_symbol(ix)
        if prior_def:
            raise source.error('Would redefine symbol index %d ("%s" added in %s)' % \
                               (ix, prior_def.name, prior_def.source))
        if len(parts) < 2:
            raise source.error('Not enough parts in "%s"' % line)
        if len(parts) >= 3:
            unit = parts[2]
        else:
            unit = None
        if len(parts) >= 4:
            doc = parts[3]
        else:
            doc = None
        s = Symbol(index=ix, name=name, _type=symbol_type,
                   unit=unit, long_name=parts[1], doc=doc)
        s.source = source
        s.c_name = define
        ontology.add_symbol(s)
        if context:
            context.lowest_suggested_symbol_ix = ix + 1
        return

    if line.startswith("REF"):
        ix, rest = line[3:].split(' ', 1)
        if ix == 'x' and context:
            if context.lowest_suggested_reg_ix is None:
                raise source.error("No known regIx to suggest")
            newIx = context.lowest_suggested_reg_ix
            context.lowest_suggested_reg_ix += 1
            return "REF%s %s" % (newIx, rest)
        #if ix == ''
        try:
            ix = int(ix)
        except:
            raise source.error('Cannot parse %s as REF number' % str(ix))
        before_colon, rest = rest.split(':', 1)
        before_colon_parts = before_colon.split(' ')
        if len(before_colon_parts) == 1:
            c_name = before_colon_parts[0].strip()
            label = None
        elif len(before_colon_parts) == 2:
            c_name = before_colon_parts[0].strip()
            label = before_colon_parts[1].strip()
        else:
            raise source.error('Syntax error')
        prior_def = ontology.registry.get_by_regIx(ix)
        if prior_def:
            raise source.error('Cannot redefine constant %d (defined in %s)' %
                               (ix, prior_def.source))
        #Instead checked in ontology:
        #if label is not None:
        #    for constant in constants:
        #        if constant['label'] == label:
        #            print 'Error: %s redefines label "%s"' % (repr(source), label)
        definition = rest.strip()
        #Since we don't need to support forward references, just parse at once
        obj = ascii.to_pyObj(definition, source, follow_ref=False)
        obj.c_name = c_name
        existing_entry = ontology.registry.get_by_c_name(c_name)
        if existing_entry:
            raise source.error('c_name %s already defined in %s' % (c_name, existing_entry.source))
        #Store in registry:
        ontology.add_entry(ix, obj, label)
        if context:
            context.lowest_suggested_reg_ix = ix + 1

        return

    print('Unknown line %s: %s' % (repr(source), line))

def parse(infile, ontology, ignore_files, context=None):
    "Fills <knowledge> with data parsed from infile"
    resolved_file = find_file(os.path.dirname(infile), os.path.basename(infile))
    if resolved_file in ignore_files:
        if verbose:
            print('Skipping already included file', resolved_file)
        return #Already added
    if verbose:
        print('Parsing file', resolved_file)
    #Add early, in case an 'include' chain tries to include it again:
    ignore_files.append(resolved_file)
    f = open(resolved_file, 'r')
    for line_nr, line in enumerate(f.readlines(), 1):
        #try:
        source = Source(resolved_file, line_nr)
        parse_line(source, resolved_file, line,
                   ontology, ignore_files, context)
        #except:
        #    print 'Error parsing %s:%d:' % (infile, line_nr)
        #    print '  ' + line
        #    raise Exception

    f.close()
