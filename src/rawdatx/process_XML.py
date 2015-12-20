#!/usr/bin/env python
from __future__ import division # used for function evaluator

import xlsxwriter
import numpy as np
import datetime, re
import sys, os, copy

is_python_3 = sys.version_info[0] == 3
if is_python_3:
    from io import StringIO
    import configparser
    xrange=range
    unicode = lambda a,b: str(a)
else:
    from StringIO import StringIO
    import ConfigParser as configparser

_using = []
_using.append('Python '+sys.version)

try:
    from asteval import Interpreter
    _using.append('asteval')
except ImportError:
    _using.append('no asteval')
    # Note: this class and ASTEVAL produce the same results in Python 2
    #   only if this script uses
    #   from __future__ import division
    
    class Interpreter(object):
        def __init__(self, **kwargs):
            self.symtable={}
            self.error=[]
            # define attribute to distinguish this class from asteval
            self.unsafe_evaluation_environment = True            
        def __call__(self, source):
            self.symtable['__builtins__']=None
            return eval(source.replace('\r\n','\n'), self.symtable)
        def add(self, source):            
            exec(source.replace('\r\n','\n'), self.symtable)

# note: xml.etree.ElementTree does not allow access to parent. use lxml instead
#   since lxml depends on an external library, we use our own
#   xml parser if lxml is not found. Use of lxml is recommended.
try:
    import lxml.etree as ET
    ET_tostring = ET.tostring
    ET_DTD = ET.DTD
    ET_parse = ET.parse
    _using.append('lxml')
except ImportError:
    _using.append('no lxml')
    from ._xml_parser import DTD, parse  # minimal implementation -- does not validate DTD
    import xml
    def ET_tostring(root, encoding, pretty_print):
        return tree._text
    ET_DTD = DTD
    ET_parse = parse

# this is the interpreter revision
#  we change this when the XML syntax changes
REVISION='20150613'

# 20 Dec 2015: write mock-asteval class to allow script to run on
#              Python 3.5
#              (there is some unresolved incompatibility in asteval 0.9.5)
# 13 Dec 2015: facilitate tox testing: remove scipy dependency,
#              implement custom xml parser in case lxml is not installed
# 12 Dec 2015: turn processing scripts into Python modules
# 13 Jun 2015: fix errors in UNTIL handling and introduce
#              global XML_attr_until_mode state
#              (until was missing the last entry).
#              Force until_mode to be defined at top-level only if until
#              or except_until are present.
#              options are: inclusive, exclusive, and disallowed (default)
#              * this will break all previous definitions that use some form
#                of UNTIL *
# 22 Mar 2015: change from openpyxl to xlsxwriter
# 22 Mar 2015: introduce DTD. Note: <group> element
#              MUST have a name="" attibute argument now (can be empty, though)
# 22 Mar 2015: introduce except_from and except_until attributes to mask out
#              time ranges
# 22 Mar 2015: introduce <set> </set> element to apply from/until or
#              except_from/except_until to several elements
# 21 Mar 2015: define unique variable for MAP elements that do not define
#              var explicitly
#          --> converting a MAP element into a vector, regardless of
#              attributes, is now done only exactly once (to simplify code path)
# 21 Mar 2015: allow both SRC and IS attributes in the same MAP element
#              provided the IS attribute refers to the SRC attribute
#          --> var assignment is to IS expression, using SRC.
# 21 Mar 2015: fix WHERE function by casting all arguments to vectors
# 28 Feb 2015: add replace_time_with_NaN() function
# 27 Feb 2015: change treatment of variable and function definitions internally
#  4 Feb 2015: add remove_spikes() function
# 22 Jan 2015: XML interpreter and spread sheet generator are working


# XML Tags
XML_main = 'measurements' # main
XML_set = 'set' # logical unit containing group/map/def elements, used to propagate attributes (from/except-from etc) to a set of children
XML_group = 'group' # group, mostly for grouping data in user-visible output
XML_map = 'map' # define user-visible result of an expression
XML_def = 'def' # like MAP but don't produce XLSX output
# XML attributes
# form, until, except_from, except_until exist because they are
#   very common operations: almost every file will have to limit the
#   date range extracted from a raw data file.
XML_attr_until_mode = 'until-limit' # global state. until is: inclusive/exclusive
XML_attr_from = 'from' # start valid date range
XML_attr_until = 'until' # end valid date range
XML_attr_except_from = 'except-from' # start invalid date range
XML_attr_except_until = 'except-until' # end invalid date range
XML_attr_unit = 'unit' # variable unit used in XML_map (or inherited)
XML_attr_name = 'name' # name of XML_group or XML_map used for clear text output
XML_attr_var = 'var' # name of XML_group or XML_map or XML_def used for internal variable/function definition (var of XML_group is used as a prefix for that group)
XML_attr_src = 'src' # reference to CR1000 data table. Retrieve corresponding data and format to vector of length master_dates
#                      'src' data vectors are directly added to the dictionary w/o def statement
XML_attr_expr = 'is' # expression to be part of the evaluated statement
#                     def "var": return ("is")
#                    if var does not contain brackets, then assume assignment:
#                     var = np.array(  is  )
XML_attr_comment = 'comment' # comment. ignored, may be added to XLSX cells in future versions
#
# NB: code assumes that these flags are defined in lower case:
XML_flag_until_inclusive = 'inclusive'
XML_flag_until_exclusive = 'exclusive'
XML_flag_until_disallowed = 'disallowed'

global_until_mode_default = XML_flag_until_disallowed
global_until_mode = None # global state variable


# Document Type Definition
DTD_list=[]
#DTD_list.append("<!DOCTYPE %s [" % XML_main)
DTD_list.append('<!ELEMENT %s ((%s|%s)*)>' % (XML_main,XML_set,XML_group))
DTD_list.append('<!ELEMENT %s ((%s|%s|%s|%s)*)>' % (XML_set,XML_set,XML_group,XML_map,XML_def)) # XML_group,
DTD_list.append('<!ELEMENT %s ((%s|%s|%s)*)>' % (XML_group,XML_set,XML_map,XML_def))
DTD_list.append("<!ELEMENT %s EMPTY>" % XML_map)
DTD_list.append("<!ELEMENT %s EMPTY>" % XML_def)
DTD_list.append('<!ENTITY %% may-have-name "%s CDATA #IMPLIED">' % (XML_attr_name))
DTD_list.append('<!ENTITY %% must-have-name "%s CDATA #REQUIRED">' % (XML_attr_name))
DTD_list.append('<!ENTITY %% until-mode "%s CDATA #IMPLIED">' % (XML_attr_until_mode))
DTD_list.append('<!ENTITY %% inheritable "%s CDATA #IMPLIED %s CDATA #IMPLIED %s CDATA #IMPLIED %s CDATA #IMPLIED">' %
                (XML_attr_from,XML_attr_until,XML_attr_except_from,XML_attr_except_until))
DTD_list.append('<!ENTITY %% definition "%s CDATA #IMPLIED %s CDATA #IMPLIED %s CDATA #IMPLIED %s CDATA #IMPLIED">' %
                (XML_attr_var,XML_attr_expr,XML_attr_src,XML_attr_unit))
DTD_list.append('<!ENTITY %% common "%%inheritable; %s CDATA #IMPLIED">' %
                (XML_attr_comment))
DTD_list.append('<!ATTLIST %s %%may-have-name; %%until-mode; %%common;>' % XML_main)
DTD_list.append('<!ATTLIST %s %%must-have-name; %%common;>' % XML_group)
DTD_list.append('<!ATTLIST %s %%may-have-name; %%common;>' % XML_set)
DTD_list.append('<!ATTLIST %s %%must-have-name; %%definition; %%common;>' % XML_map)
DTD_list.append('<!ATTLIST %s %%may-have-name; %%definition; %%common;>' % XML_def)
#DTD_list.append("]>")
DTD_declaration = '\n'.join(DTD_list)

show_errors = False


# if the following symbol appears in XML_attr_expr, subsitute with variable referenced by XML_attr_src
XML_SRC_SUBSTITUTION_SYMBOL = 'SRC'
# text formats -- try in this order
XML_date_formats = ['%Y/%m/%d %H:%M:%S',
                    '%Y/%m/%d %H:%M',
                    '%Y/%m/%d',
                    '%Y%m%dT%H%M%S',
                    '%Y%m%d']


def find_datetime_idx(dt, db, check_until=False):
    #if dt in db: return db[dt] # until 12 June 2015
    
    if not check_until: # since 13 June 2013
        # shortcut only if we are looking for FROM
        if dt in db: return db[dt]
    elif global_until_mode == XML_flag_until_exclusive:
        # shortcut only if we are looking for UNTIL and mode is
        #  exclusive
        if dt in db: return db[dt]
        
    
    dbk = list(db.keys())
    dbk.sort()
    dbk=np.array(dbk)

    if global_until_mode == XML_flag_until_inclusive:
        until_is_inclusive = True
    elif global_until_mode == XML_flag_until_exclusive:
        until_is_inclusive = False
    else:
        if check_until:
            raise ValueError(('Encountered specification of an upper time limit '+
                              '(attributes "%s" or "%s" or through a function) '+
                              'while attribute "%s" is "%s". '+
                              'Legal values for "%s" are: "%s", "%s", "%s" (default).') %
                             (XML_attr_until, XML_attr_except_until, XML_attr_until_mode, XML_attr_until_mode,
                              global_until_mode,
                              XML_flag_until_inclusive,XML_flag_until_exclusive,XML_flag_until_disallowed))        
    
    if True:
        # version of 13 June 2015
        or_earlier = check_until
        if or_earlier:            
            if until_is_inclusive:
                # UNTIL: we return the first index AFTER the requested end
                # --> until will be INCLUSIVE
                ok = np.nonzero(dbk>dt)[0]
            else:
                # UNTIL: we return the first index AT or AFTER the requested end
                # --> until will be EXCLUSIVE
                # (note the shortcut for AT at the beginning of the function)
                ok = np.nonzero(dbk>=dt)[0]
            try:
                return db[dbk[np.min(ok)]]
            except:
                return -1 # -1 indicates that date is after dataset ends (-> usually nothing to do)
        else:
            # FROM: we return the first index AFTER or AT the requested time
            # note that the 'AT' case is handled by the shortcut at the
            # beginning of the function
            ok = np.nonzero(dbk>=dt)[0]
            try:
                return db[dbk[np.min(ok)]]
            except:
                return -1 # -1 indicates that date is after dataset end
        
        

###################################################################
# numerical environment

def _mask_values_with_datetime(values, from_datetime=None, until_datetime=None):    
    from_idx, until_idx = _get_idx_range_from_datetime(from_datetime, until_datetime)
    values = _mask_values_with_date_index(values,from_idx,until_idx)
    return values

def _mask_values_with_except_date_index(values, from_idx=None, until_idx=None, no_copy=False):
    return _mask_values_with_date_index(values, from_idx, until_idx, no_copy=no_copy, mask_inside=True)
            
def _mask_values_with_date_index(values, from_idx=None, until_idx=None, no_copy=False, mask_inside=False):
    if not no_copy: values = np.array(values).copy() # useful to skip if we call this function repeatedly
        
    if np.sum(values.flatten().shape) != len(datetime_idx_db):
        if np.sum(values.flatten().shape) != 1:
            raise ValueError('Unexpected size of input values. Expect scalar or properly sized vector.')
        # we're dealing with a scalar
        values = np.repeat(values, len(datetime_idx_db))
    # use make float() for NaN
    values = values.astype(np.float64) # was: float
    
    # NB: in Python 2, None > 0 evaluates to False.
    #     in Python 3, None > 0 raises TypeError exception.
    if not mask_inside:
        # mask outside given range
        #if (from_idx == -1) or (until_idx == -1): # until 12 June 2015
        #    either from a date in future, or until a time in the past:
        #    values[:]= np.nan
        if (from_idx is not None) and (from_idx == -1): # from 13 June 2015
            # from a date in future
            values[:]= np.nan
    
        if (from_idx is not None) and (from_idx >= 0):
            # if from_idx <= 0 we don't have to blank out anything (13 June 2015)
            values[:from_idx] = np.nan # until 12 June 2015            
        #if until_idx > 0: # until 12 June 2015
        if (until_idx is not None) and (until_idx >= 0): # from 13 June 2015
            values[until_idx:] = np.nan
    else:        
        if True:
            # Version from 13 June 2015
            if (from_idx is not None) and (from_idx==-1):
                # we blank out an iterval after the end of the dataset
                #  ignore
                pass
            else:
                if from_idx is None: from_idx = 0 # start of record
                if (until_idx==-1) or (until_idx is None):
                    until_idx = len(values) # end after dataset
                
                values[from_idx:until_idx] = np.nan

    if values is None: raise ValueError('Unexpected result: None.')
    if len(values) != len(datetime_idx_db):
        raise ValueError('result vector wrong length in apply_datetime_mask()')
    
    
    return values

def _get_idx_range_from_datetime(from_datetime=None, until_datetime=None):
    if from_datetime is not None:
        from_idx  = find_datetime_idx(from_datetime ,datetime_idx_db,False)
    else: from_idx = None
    if until_datetime is not None:
        until_idx = find_datetime_idx(until_datetime,datetime_idx_db,True)
    else: until_idx = None
    return from_idx, until_idx
    
def apply_datetime_mask(function, from_datetime=None, until_datetime=None,
                        except_from_datetime_list=None,
                        except_until_datetime_list=None):
    """mask data including 'from', excluding 'until'"""
    if except_from_datetime_list is None: except_from_datetime_list = []
    if except_until_datetime_list is None: except_until_datetime_list = []
    from_idx, until_idx = _get_idx_range_from_datetime(from_datetime, until_datetime)
    
    except_ranges_idx = [_get_idx_range_from_datetime(f,u) for (f,u) in zip(except_from_datetime_list, except_until_datetime_list)]   
    
    #@functools.wraps(function)  # does not work with asteval
    def wrapper(*args, **kwargs):
        return_value = function(*args, **kwargs)
        # turn scalars into vectors and apply time mask
        return_value = _mask_values_with_date_index(return_value,from_idx,until_idx)        
        for (efrom_idx, euntil_idx) in except_ranges_idx:
            return_value = _mask_values_with_except_date_index(return_value,efrom_idx,euntil_idx,no_copy=True)
        return return_value
    return wrapper


def make_data_vector(key):
    # keep all keys in a list in the order in which they are called
    if key not in make_data_vector_log: make_data_vector_log.append(key)
    dates=data[key]['dates']
    values=data[key]['values']    
    out = np.nan*np.ones((len(datetime_idx_db),))
    for idx,date in enumerate(dates):        
        try: idx_out = datetime_idx_db[date]
        except KeyError: continue  # date probably of test before deployment
        out[idx_out]=values[idx]        
    return out


def len_general(x):
    """returns 1 for scalars or None"""
    if np.array(x).ndim>0: return len(np.array(x))    
    return 1

def merge(v1,v2):
    """merge v2 into v1 at places where v1==NaN"""
    return np.where(v1==v1,v1,v2)

def _nan_helper(y):
    """Helper to handle indices and logical indices of NaNs.

    Input:
        - y, 1d numpy array with possible NaNs
    Output:
        - nans, logical indices of NaNs
        - index, a function, with signature indices= index(logical_indices),
          to convert logical indices of NaNs to 'equivalent' indices
    Example:
        >>> # linear interpolation of NaNs
        >>> nans, x= nan_helper(y)
        >>> y[nans]= np.interp(x(nans), x(~nans), y[~nans])
    """
    return np.isnan(y), lambda z: z.nonzero()[0]

def interpolate_over_NaN(data):
    data_out=data.copy()    
    nans, x= _nan_helper(data_out)    
    data_out[nans]= np.interp(x(nans), x(~nans), data_out[~nans])
    return data_out

def _nanmedian(data):
    return np.median(data.flatten()==data.flatten())

def _detrend(y):
    """Detrending without scipy"""
    s=y.shape
    y=y.flatten()
    x=np.arange(len(y))
    p=np.polyfit(x,y, 1)
    return (y-np.polyval(p, x)).reshape(s)

def remove_spikes(data,threshold=None,window=12):
    """remove everything that deviates more than 500kPa from the median of a detrended 1-hour (12 points) window"""    
    # note that trends of 100kPa/hour are absolutely realistic
    #  so anything that departs by more than 500kPa from the trend should
    #  be pretty massive
    # (there are 2000 kPa spikes coming from one of the sensors)
    # TODO: maybe change to detection of singular spikes
    #   since we do have sudden jumps from tension -> -100kPa
    #   that give high STD but are perfecty correct
    
    # ignore the beginning, so data length is multiples of the window size
    skip = len(data)-window*(len(data)//window)    
    
    a=data[skip:]    

    if True:
        # remove any Inf
        a[a==np.inf]=np.nan
        a[a==-np.inf]=np.nan
        # remember where we had NaN/Inf
        NaN_idx = a!=a
        # interpolate over NaN:        
        a=interpolate_over_NaN(a)        

    b = a.reshape((len(a)//window,window))    

    # this will fail if there are NaN (or Inf) in the arrary    
    c = _detrend(b) # simulating scipy.signal.detrend(b,axis=1)

    median = np.median(c,axis=1)
    
    if threshold is None:
        # if there is only a single peak in an array of length WINDOW
        #   then this peak will be N times the standard deviation of
        #   that WINDOW above the median.
        #   For a window of 12, this is N=3.6
        n = float(window)/(window-1.)**.5

        enhance = 100. # constantrelating the typical spike height to
        #  to the typical noise floor (and window size?)
        #   and the noise floor variability to the noise floor median
        std = np.std(c,axis=1)        
        # note: do not use mean, spikes of 1e16 reading would
        #  cause tremendous errors.

        # note: would be better to use 75-percentile rather than median
        threshold = n * enhance * _nanmedian(std) #_nanmedian( std )
        
    median = np.repeat(median[:,None],window,axis=1)
    err = (np.fabs(c-median)>threshold).flatten()
    a[err] = np.nan # overwrite outliers

    a[NaN_idx] = np.nan # overwrite original NaN/Inf
    
    # merge unfiltered with filtered data
    data_out = np.hstack((data[:skip],a))
    return data_out
    
def replace_value_with_NaN(data, value):
    data=data.copy()
    data[data==value]=np.nan
    return data

def replace_time_with_NaN(data, rep_time):
    data=data.copy()
    if (isinstance(rep_time, str) or isinstance(rep_time, unicode)):
        rep_time = [rep_time,]

    for rt in rep_time:        
        date = date_string_to_datetime(rt)
        if date == 'error':
            raise ValueError('Could not decode date: %s' % rt)        
        if date not in datetime_idx_db:
            # unknown date, silently ignore
            #  (could be that the XML file is covering events in the future)
            # raise ValueError('Date does not exist: %s' % rt)
            continue
        index = datetime_idx_db[date]
        data[index] = np.nan
    return data


def in_date_range(start, end):
    """returns True for dates from (incl) until (excl)"""    
    return 1==_mask_values_with_datetime(np.ones((len(all_dates),)), date_string_to_datetime(start), date_string_to_datetime(end))
    

def forced_array_where(x,y,z):
    values = np.array(x)
    if np.sum(values.flatten().shape) != len(datetime_idx_db):
        values = np.repeat(values, len(datetime_idx_db))
    x=values
    values = np.array(y)
    if np.sum(values.flatten().shape) != len(datetime_idx_db):
        values = np.repeat(values, len(datetime_idx_db))
    y=values
    values = np.array(z)
    if np.sum(values.flatten().shape) != len(datetime_idx_db):
        values = np.repeat(values, len(datetime_idx_db))
    z=values
    
    return np.where(x,y,z)

default_symtable={'ln':np.log,'log10':np.log10,'exp':np.exp,
                  'fabs':np.fabs,'abs':np.fabs,
                  'sign':np.sign,                
                  'sin':np.sin,'cos':np.cos,'tan':np.tan,
                  'arctan':np.arctan,'arctan2':np.arctan2,
                  'mean':np.nanmean,
                  'sum':np.nansum,'min':np.nanmin,'max':np.nanmax,
                  'round':np.round,
                  'where':forced_array_where, #np.where, # does not work as intended: comparison with scalar seems to fail
                  'isnan':np.isnan,                  
                  'len':len_general,
                  'merge':merge,                  
                  'remove_spikes':remove_spikes,
                  'replace_NaN_value':replace_value_with_NaN, # obsolete
                  'replace_value_with_NaN':replace_value_with_NaN,
                  'replace_time_with_NaN':replace_time_with_NaN,
                  'in_date_range':in_date_range, # for use with where()
                  'float':float, # type casting (and to define NaN)
                  '_a':np.array,
                  '_datetime':datetime,                  
                  'None': None}
default_symtable['_apply_datetime_mask']=apply_datetime_mask
default_symtable['_make_data_vector']=make_data_vector
# Note: there are also two variables defined, NaN and PI, when the
#   environment is set up

def dump_symbols(symtable, default_symtable=None):
    keys = list(symtable.keys())
    keys.sort()
    for key in keys:
        if default_symtable is not None:
            if key in default_symtable: continue
        print(key, symtable[key])

def _turn_user_symbols_into_function_calls(test_string, user_vars):
    return _symbol_convert(test_string, user_vars,
                           sub_symbol=None, substitute=None)

def _substitute_symbol(test_string, symbol, substitute):
    return _symbol_convert(test_string, None,sub_symbol=symbol,
                           substitute=substitute)

def _symbol_convert(test_string, user_vars,sub_symbol=None,substitute=None):
    debug = False
     
    string=test_string.strip()
    out = ''
    substituted = False

    if ("'" in test_string) and ('"' in test_string):
        raise ValueError("Symbol search will get confused by presence of both \" and ' in string %s" % test_string)
            
    if debug: print('input: '+string)

    while True:        
        #found = re.search('[_a-zA-Z][_a-zA-Z0-9]* *',string)
        # ignores symbols unless there is an even number of " (or none) to follow
        #found = re.search('([_a-zA-Z][_a-zA-Z0-9]* *)(?=(?:[^"]|"[^"]*")*$)',string)
        # allows " or ' for quotation but assumes that string does not contain both
        found = re.search('([_a-zA-Z][_a-zA-Z0-9]* *)(?=(?:[^"\']|("|\')[^"\']*("|\'))*$)',string)
        if found == None:
            out += string
            break

        symbol = found.group().strip()
        if debug: print('"'+symbol+'"')
        ignore = False
        if found.start()>0:
            if (string[found.start()-1]>='0') and (string[found.start()-1]<='9'):
                if debug: print('leading digit, not valid.')
                ignore = True
        if found.end()<len(string):
            if string[found.end()] == '(':
                if debug: print('already declared as function, not interesting')
                ignore = True

        if user_vars is not None:            
            out += string[:found.end()]
            if not ignore:            
                if symbol in user_vars:
                    out += '()'
                else:
                    if debug: print('not user variable, ignore.')
                    
        elif (sub_symbol is not None) and (substitute is not None):
            if not ignore:
                if sub_symbol == symbol:
                    # substitute
                    out += string[:found.start()]
                    out += substitute
                    substituted = True
                else:
                    # copy
                    out += string[:found.end()]
            else:
                out += string[:found.end()]
                                

        string = string[found.end():]    

    if debug: print('result: '+out)
    
    if user_vars is None: return out, substituted
    return out



def _datetime_str(dt):
    if dt is None: return 'None'   
    out = '_datetime.datetime('
    out += '%i,%i,%i,%i,%i)' % (dt.year,dt.month,dt.day,dt.hour,dt.minute)
    return out

def _datetime_list_str(dts):
    out = []
    for dt in dts:
        out.append(_datetime_str(dt))
    return '['+','.join(out)+']'
        

def log_errors(env):
    if len(env.error)>0:
        env_errors.append('\t'.join(env.error[1].get_error()))

def add_env(env,txt):
    #print 'add>>>', txt
    if hasattr(env, 'unsafe_evaluation_environment'):
        env.add(txt)
    else:
        env(txt,show_errors=show_errors)
    log_errors(env)    
        

def is_None_or_empty(x):
    return (x is None) or (x=='')

def _make_expression(expr,src,user_vars):
    # assumes that at least one of expr and src is not None
            
    if not is_None_or_empty(src):
        # postpone calculation and treat variable like function
        #   like all other variables.
        src_expr = "_make_data_vector('%s')" % src

    if (not is_None_or_empty(expr)) and (not is_None_or_empty(src)):
        # new 21 Mar 2015
        expr, did_substitute = _substitute_symbol(expr, XML_SRC_SUBSTITUTION_SYMBOL, src_expr)
        if not did_substitute:
            raise ValueError('Found expression "%s" and source "%s" in the same element but expression does not refer to source (using variable %s).' % (
                expr, src, XML_SRC_SUBSTITUTION_SYMBOL))

    if is_None_or_empty(expr):
        expr = src_expr
            
    # replace all user-defined constants/symbols with functions
    # find all symbols not followed by "("
    #   if user-defined, replace with symbol followed by ()
    # repeat
    
    expr=_turn_user_symbols_into_function_calls(expr, user_vars)
    return expr

def _sanitized_var_name(name):
    try: name = unicode(name,'utf-8') # should be UTF-8
    except UnicodeDecodeError:
        try: name = unicode(name,'latin1') # if function is called directly, may be other code page
        except UnicodeDecodeError:
            raise            
    name = name.replace(' ','_')
    return re.subn('[^0-9a-zA-Z_]','_',name)[0]

def _make_global_var_name(element):
    """creates a global name for the MAP element"""
    if element.tag != XML_map:
        raise ValueError('Expected element <%s> for variable name definition, found <%s>' % (XML_map,element.tag))
        
    base_name = _get_attrib_or_None(element,XML_attr_name)
    if base_name is None:
        # a MAP element needs to have a name
        raise ValueError('Element <%s> is missing attribute "%s".' % (XML_map,XML_attr_name))

    # walk up in the hirachy until we find the group element
    total_group_name = ''
    while True:
        element = element.find('..')
        if element is None:
            # no group element --> we could raise an exception
            if total_group_name =='': total_group_name = 'NO_GROUP'
            break
        if element.tag == XML_group:
            group_name = _get_attrib_or_None(element,XML_attr_name)
            if group_name is None:
                # perfectly legal case
                group_name = 'EMPTY_GROUP_NAME'
            total_group_name = group_name+'_'+total_group_name
            #... and keep looking in case there are nested groups
    h=str(hash(total_group_name+base_name)) # we calculate the hash in case somebody uses names in non-ASCII characters only
    if h[0]=='-': h='M'+h[1:]
    name= '_VAR_'+total_group_name+base_name+'_'+h
    return _sanitized_var_name(name)
        
def make_environment(measurements,env=None):
    # 3. walk through <MEASUREMENT> and <GROUP> elements to find all <MAP> and <DEF> elements
    # 3a.  extract var/src pairs and keep in list. do not add to dictionary
    # 3b.  extract var/is pairs and evaluate 'def' statement (check for var name space collisions)
    #        account for from/until by extracting from/until range and adding decorators (decorators should test for scalar: in this case, no from/until adjustment should be performed)
    if env == None:
        env=Interpreter(use_numpy=False)
        env.symtable=default_symtable.copy()
        add_env(env,'NaN=float("nan")')
        add_env(env,'PI=3.14159265359')        

    # find all tags, regardless of nesting:
    elements = ( get_all_XML_tags(measurements,XML_def) +
                 get_all_XML_tags(measurements,XML_map) )

    for element in elements:
        var = _get_attrib_or_None(element,XML_attr_var)

        if var is None:
            # 21 Mar 2015: we define a (unique) variable ALWAYS
            var = _make_global_var_name(element)
            
        real_var = var
        
        src = _get_attrib_or_None(element,XML_attr_src)
        expr = _get_attrib_or_None(element,XML_attr_expr)
        if (src is None) and (expr is None):
            raise ValueError('Neither %s nor %s defined for %s="%s".' %
                             (XML_attr_src,XML_attr_expr,XML_attr_var,real_var))
        
        expr0 = expr
        real_var0 = real_var

        if '(' not in real_var:
            real_var=real_var.strip() + '()'
    
        expr = _make_expression(expr,src,user_vars)

        if True:
            if True:
                # define function
                real_fn_name = real_var.split('(')[0]
                txt ='def %s: return %s' % (real_var,expr)
                add_env(env,txt)                
                
                # find smallest time range
                start, end = get_defined_date_range(element)
                start_dt=_datetime_str(start)
                end_dt=_datetime_str(end)
                # find exclueded elements
                starts, ends = get_defined_except_date_range(element)
                starts_dt=_datetime_list_str(starts)
                ends_dt=_datetime_list_str(ends)
                # decorate with from/until time range function
                txt =('%s=_apply_datetime_mask(%s,%s,%s,%s,%s)' %
                      (real_fn_name,real_fn_name,
                       start_dt,end_dt,
                       starts_dt,ends_dt))
                add_env(env,txt)
                
                # store debug information
                # we replace ' with " to avoid a syntax error. expr0/expr can be None but they cannot be numbers (0)
                txt = ("%s.__name__='%s given %s defined %s from %s until %s'" %
                       (real_fn_name,real_var0,
                        (expr0 or 'None').replace("'",'"'), (expr or 'None').replace("'",'"'),
                        start,end))
                add_env(env,txt)
                                
    return env


#####################################################################
# XML processing

def get_all_XML_tags(root, tag_name):
    """Return list of tag elements or list of self"""    
    if root.tag == tag_name: return [root]    
    return root.findall('.//'+tag_name)

def _get_attrib_or_None(element, attribute):
    """Return attribute or empty string"""
    try:
        return element.attrib[attribute]
    except KeyError:
        # attribute not defined
        return None

def date_string_to_datetime(date):
    for fmt in XML_date_formats:
        try:
            date_date = datetime.datetime.strptime(date,fmt)
            break
        except ValueError:
            date_date = 'error'
            pass
    return date_date

def _get_xml_date(element, attribute):
    """Return date or None"""    
    try:
        date = element.attrib[attribute]
        if len(date.strip())==0: date = None
    except KeyError:
        date = None

    date_date = None
    
    if date != None:
        date_date = date_string_to_datetime(date)

    if date_date == 'error':
        raise ValueError('Invalid format for date: %s' % date)
            
    return date_date

def _get_date_interval_of_all_parents(root, except_interval=False):
    if except_interval:
        attr_from, attr_until = XML_attr_except_from, XML_attr_except_until
    else:
        attr_from, attr_until = XML_attr_from, XML_attr_until
    intervals = [[],[]]
    while root.find('..') is not None:
        root = root.find('..')
        f = _get_xml_date(root, attr_from)
        u = _get_xml_date(root, attr_until)
        if (f is not None) or (u is not None):
            intervals[0].append( f )
            intervals[1].append( u )
    return intervals    

def get_defined_date_range(element):
    
    # get date range specified by parents            
    starts,ends = _get_date_interval_of_all_parents(element)

    # add date range specified in current element
    starts.append(_get_xml_date(element,XML_attr_from))
    ends.append(_get_xml_date(element,XML_attr_until))

    start = None
    for s in starts:
        if s != None:
            if start == None: start = s
            else: start = max((start, s))
    end = None
    for e in ends:
        if e != None:
            if end == None: end = e
            else: end = min((end, e))

    return start, end

def get_defined_except_date_range(element):
    """return list of all except_from / except_until pairs upward"""
    intervals = _get_date_interval_of_all_parents(element, except_interval=True)
    starts = intervals[0]
    ends = intervals[1]

    # add date range specified in current element
    efrom = _get_xml_date(element,XML_attr_except_from)
    euntil = _get_xml_date(element,XML_attr_except_until)
    if (efrom is not None) or (euntil is not None):
        starts.append(efrom)
        ends.append(euntil)

    return starts, ends
    

def _dates_in_range(dates, start_list, end_list):
    """Returns boolean array of dates in range"""
    ok = np.ones(dates.shape)
    for i in xrange(len(start_list)):
        if start_list[i] is not None:
            ok = ok * (dates>=start_list[i])
            
        if global_until_mode == XML_flag_until_inclusive:
            if end_list[i] is not None:
                ok = ok * (dates<=end_list[i])
            
        elif global_until_mode == XML_flag_until_exclusive:
            if end_list[i] is not None:
                ok = ok * (dates<end_list[i])

        else:
            if end_list[i] is not None:
                raise ValueError(('Until range "%s" specified while definition of '+
                                  'until is neither "%s" nor "%s".') %
                                 (end_list[i], XML_flag_until_inclusive, XML_flag_until_exclusive))
    return ok>0


def get_all_mapped_dates(data, root):
    """Returns the complete list of actual dates to be mapped"""
    all_dates = set()
    start_global = _get_xml_date(root, XML_attr_from)
    end_global = _get_xml_date(root, XML_attr_until)
    # go through every mapping entry   
    maps = get_all_XML_tags(root,XML_map) + get_all_XML_tags(root,XML_def)
    sources = {}
    for entry in maps:
        try: key = entry.attrib[XML_attr_src]
        except: continue # does not have SRC attribute --> does not access data

        sources[key]=entry
        
        # get date range specified by parents            
        starts,ends = _get_date_interval_of_all_parents(entry)

        # add date range specified in current element
        starts.append(_get_xml_date(entry,XML_attr_from))
        ends.append(_get_xml_date(entry,XML_attr_until))
        
        # get measured dates
        dates = data[key]['dates']
        # get valid measured dates as specified by mapping
        #  --> connect through AND
        ok = _dates_in_range(dates,starts, ends)
        
        # unite with current list (use sets for speed)
        #  --> connect through OR
        all_dates = all_dates.union( dates[ok] )

    # sort
    all_dates = np.array(list(all_dates))
    all_dates = np.sort(all_dates)
        
    return all_dates, sources


###########################################################
# XLSX creation

def make_header(sheet, datetime_string=None):

    if datetime_string is None: datetime_string = datetime.datetime.today().strftime('%Y/%m/%d %H:%M')
    info = metadata_header
    info.append(["File Time:", datetime_string])

    meta = {}    
    for row in xrange(len(info)):
        sheet.write_row(row,0,info[row])
        meta[info[row][0]]=info[row][1]

    # return 1-based index to last row written
    return len(info), meta


def _write_dates(sheet, row0, all_dates):    
    number_format='yyyy/m/d h:mm'
    for row in xrange(len(all_dates)):
        sheet['A%i' % (row+row0)] = all_dates[row]        
        sheet['A%i' % (row+row0)].number_format = number_format

def cell_apply_style(cell, style):    
    for key in style.__dict__:
        exec('cell.%s=style.%s' % (key,key)) #XYZ


def write_all(workbook,sheet, row0, groups, all_dates, data):
    structure={}
    structure['_var']={}

    row_group = row0
    row_name = row0+1
    row_units = row0+2 # or None
    row_data = row0+3
    date_col = 0
    col_group = date_col+1

    if True:
        # define formats
        s_header=workbook.add_format({'bold':True})
        s_header1=workbook.add_format({'bold':True})
        s_header1.set_left()
        s_unit=workbook.add_format({'bold':True})
        s_unit.set_bottom()
        s_unit1=workbook.add_format({'bold':True})
        s_unit1.set_bottom()
        s_unit1.set_left()

        if row_units is None:
            # units not displayed
            s_header.set_bottom()
            s_header1.set_bottom()

        date_format='yyyy/mm/dd hh:mm'
        s_date=workbook.add_format()
        s_date.set_num_format(date_format)

        s_header_group = workbook.add_format({'bold':True})
        s_header_group.set_align('center')
        s_header_group.set_left()
        
        data_format='0.00'
        s_data=workbook.add_format()
        s_data1=workbook.add_format()
        s_data.set_num_format(data_format)
        s_data1.set_num_format(data_format)        
        s_data1.set_left()        

    N_dates = len(all_dates)

    if True:        
        # Time column
        #logger_time_unit should be defined in configuration file
        sheet.write(row_name,date_col,'Time',s_header)
        if row_units is not None:
            sheet.write(row_units,date_col,logger_time_unit,s_unit)

        if True:
            # write dates            
            for y in xrange(len(all_dates)):
                sheet.write_datetime(row_data+y,date_col, all_dates[y], s_date)
            sheet.set_column(date_col,date_col,16) # set column width for YYYY/MM/DD HH:MM

        structure['Time']={'unit':logger_time_unit,'values':all_dates.copy()}

    for group in groups:
        # walk through MAP and SET elements
        maps=extract_MAPs_in_order(group)
        if len(maps) == 0: continue # nothing to output in this group
        # write group headers        
        g_name = _get_attrib_or_None(group, XML_attr_name)
        if g_name is None: g_name = '' # should not be None per DTD
        if len(maps)>1:
            sheet.merge_range(row_group,col_group,row_group,col_group+len(maps)-1,g_name,s_header_group)
        else:
            sheet.write(row_group,col_group,g_name,s_header_group)

        if g_name in structure:
            raise ValueError('Multiple occurrences of group name "%s".' % g_name)
        structure[g_name]={}

        # write variable headers of this group
        for idx in xrange(len(maps)):
            element = maps[idx]
            col = col_group+idx

            name = _get_attrib_or_None(element, XML_attr_name)
            if name is None: name = ''
            sheet.write(row_name,col,name,s_header if idx>0 else s_header1)

            u_name = _get_attrib_or_None(element, XML_attr_unit)
            if u_name is None: u_name = ''
            if row_units is not None:
                sheet.write(row_units,col,u_name,s_unit if idx>0 else s_unit1)
                
        # write data of this group
        for idx in xrange(len(maps)):
            element = maps[idx]
            name = _get_attrib_or_None(element, XML_attr_name)
            if name is None: name = ''
            col = col_group+idx

            # get function returing this variable possibly by
            #   pulling automatically generated name
            var = _get_attrib_or_None(element, XML_attr_var)            
            if var is None:
                var = _make_global_var_name(element)
                
            # simply call function with this variable name
            var = _make_expression(var,None,user_vars)
            values = env(var)

            if values is None:
                # DEBUG. This will lead to an error in loop...
                print('evaluating var "%s" returned None' % var)
                print(' defined:\n%s' % '\n'.join([key for key in user_vars]))
                
                      
            
            # write all data of this element
            # INF or NAN cannot be written, so we do this one-by-one
            for idx2 in xrange(len(values)):

                if values[idx2]==values[idx2]: #TEST FOR INF XYZ
                    # don't write NaN -- this causes Excel to emit a warning during opening
                    sheet.write_number(row_data+idx2,col,values[idx2], s_data if idx>0 else s_data1)
                else:
                    # write blank so we can store format
                    sheet.write_blank(row_data+idx2,col,None, s_data if idx>0 else s_data1)
                
                #out_values[idx2]=values[idx2]
            
            if name in structure[g_name]:
                raise ValueError('Multiple use of element name "%s" in group "%s".' % (
                    name, g_name))
                                 
            structure[g_name][name]={'unit':u_name,'values':values.copy()}


        col_group += len(maps)    

    return structure        

def extract_MAPs_in_order(group):
    """get all MAP elements, including those in nested SET elements"""    

    # flatten the group and inspect all elements separately
    children=group.getiterator()
    maps=[]
    for child in children:
        if child.tag in (XML_map,): maps.append(child)

    return maps 

def write_sources(workbook, sheet, sources):
    s_title=workbook.add_format({'bold':True})
    s_header=workbook.add_format({'bold':True})
    s_header.set_bottom()
    row,col = 0,0
    sheet.write(row,col,
                'Datalogger output referred to in data definition',
                s_title)
    row += 1
    if variable_order is None:
        sheet.write(row,col,
                    'Data are sorted in processing order.')
    else:
        sheet.write(row,col,
                    'Data are ordered according to logger table definition.')
        
    row += 1
    row += 1
    
    col = 1 # first data column    
    all_keys = list(sources.keys())
    all_keys.sort()
    keys = make_data_vector_log[:] # create copy    
    for key in all_keys:
        if key not in keys: keys.append(key)

    # use the input order to output data
    #  -- while we don't have control over the order of tables,
    #     at least variables within a table will come in a somewhat
    #     logical order defined in the CR1000 logger program
    if variable_order is not None:
        ordered_keys=[]
        for key in variable_order:
            if key in keys:
                ordered_keys.append(key)
                keys.remove(key)
        ordered_keys += keys # in case there is anything left
        keys = ordered_keys
    
    inf,m_inf = float('inf'), float('-inf')
    sheet.write_row(row,col,keys,s_header)
    sheet.write(row,col-1,'TIMESTAMP',s_header)
    row += 1
    
    if True:
        # write dates
        number_format='yyyy/m/d h:mm'
        fmt_date=workbook.add_format()
        fmt_date.set_num_format(number_format)
        for y in xrange(len(all_dates)):
            sheet.write_datetime(row+y,col-1, all_dates[y], fmt_date)
        sheet.set_column(col-1,col-1,16)
            
    for x,key in enumerate(keys):
        v=make_data_vector(key)
        for y,value in enumerate(v):
            if ((value==value) and
                (value != inf) and
                (value != m_inf)): sheet.write(row+y,col+x, value)
        
def write_DTD(workbook, sheet):
    col = 0
    row = 0
    s_header=workbook.add_format({'bold':True})
    
    sheet.write(row,col,
                'Document Type Definition (DTD) of XML definition',
                s_header)
    row +=1
    row +=1
    for line in DTD_list:
        sheet.write(row,col,line.strip())
        row += 1
    
def write_XML_file(workbook, sheet, filename, root):
    text = ET_tostring(root,encoding='unicode',pretty_print=True)
    fn = os.path.basename(filename)
    col = 0
    row = 0
    s_header=workbook.add_format({'bold':True})
    
    sheet.write(row,col,
                'XML definition describing the relationship between raw data from the logger and displayed data',
                s_header)
                
    row +=1
    sheet.write(row,col,'Filename:',s_header)
    sheet.write(row,col+1,fn,s_header)

    row +=1
    row +=1
    indent_fmt = {}
    for line in text.split('\n'):
        # we strip both ends since lxml ignored spaces but keept tab,
        #  so the result would be inconsistent to say the least
        
        # check generated indentation level
        level=0
        while (len(line)>0) and (line[0]=='\t'):
            level +=1
            line=line[1:]

        if level not in indent_fmt:
            indent_fmt[level]=workbook.add_format()
            indent_fmt[level].set_indent(level)
        fmt = indent_fmt[level]
        
        l = line.strip()
        if len(l) < 250:
            sheet.write(row,col,l,fmt)
            row += 1
        else:
            # Excel cells are limited in size to something like 255 characters
            #  --> break long lines
            for i0 in xrange(0,len(l),250):
                sheet.write(row,col,l[i0:i0+250],fmt)
                row += 1

def set_workbook_properties(workbook):
    workbook.set_properties({        
        'category': 'Data',
        'comments': 'rawdatx XML processor %s with %s' % (REVISION,
                                                          ', '.join(_using))
        })

###########################################################
# main

def _parse_config(config_file):
    global path_in, path_out, fn_in_npy
    global fn_in_xml_definition, xml_path
    global fn_out_excel, fn_out_structure
    global fn_path_output_DTD
    global metadata_header
    
    def cfg_get_string(cfg, section, item):
        string = config.get(section,item)
        string = string.strip()
        if string[0] == '"': string = string.strip('"')
        elif string[0] == "'": string = string.strip("'")
        return string


    # read configuration file
    config = configparser.SafeConfigParser()
    _default_optionxform = config.optionxform
    config.read(config_file)

    CFG_fn_path='Files'    
    path_in = cfg_get_string(config,CFG_fn_path,'data_path')
    path_out = cfg_get_string(config,CFG_fn_path,'data_path')
    
    try: xml_path = cfg_get_string(config,CFG_fn_path,'xml_map_path')
    except configparser.NoOptionError: xml_path = path_in
    
    fn_in_npy = cfg_get_string(config,CFG_fn_path,'raw_data')
    fn_in_xml_definition = cfg_get_string(config,CFG_fn_path,'xml_map')    
    fn_out_excel = cfg_get_string(config,CFG_fn_path,'processed_data_xlsx')
    fn_out_structure = cfg_get_string(config,CFG_fn_path,'processed_data_npy')

    try:
        fn_path_output_DTD=cfg_get_string(config,CFG_fn_path,'xml_dtd_out')
        fn_path_output_DTD=os.path.join(path_out,fn_path_output_DTD)
    except:
        fn_path_output_DTD= None
    

    CFG_metadata='Metadata'
    # remove section and reload in a case-sensitive manner
    config.remove_section(CFG_metadata)
    config.optionxform = str
    config.read(config_file)
    items = list(config.items(CFG_metadata))
    for idx,i in enumerate(items):
        items[idx]=list([i[0]+':',i[1]])
    metadata_header = items


def main(config_file, file_time_string=None):
    global datetime_idx_db
    global make_data_vector_log
    global variable_order
    global env_errors
    #
    global user_vars, env
    global logger_time_unit
    global data, all_dates
    #
    global global_until_mode
    #
    global tree
    
    _parse_config(config_file)

    # init globals
    
    # dates are handled as datettime objects so we won't introduce problems with rounding
    datetime_idx_db={} # dictionary holding assignment <datetime object> -> <entry number>
    # used to find index for from/until decorators

    # list of all raw data variables that are actually being used to
    #   process output
    #   these may be output as raw data dump on a separate shett
    make_data_vector_log = []
    variable_order = None # order we want to output raw data. This is the order we read them in.

    # init log
    env_errors=[]


    if fn_path_output_DTD is not None:
        out = ''
        out += '<!-- generated by parser version %s -->\r\n' % REVISION        
        out += '\r\n'.join(DTD_list)
        out += '\r\n'        
        
        with open(fn_path_output_DTD,'wt') as f:
            f.write(out)
        
    # reading data
    data = np.load(path_in+fn_in_npy).item()
    if True:
        # extract order raw data were read in
        header_order_key_name = '__header_order_encountered__'
        if header_order_key_name in data:
            variable_order = data[header_order_key_name][:]
            del data[header_order_key_name]        
        else:
            variable_order = None
        
    logger_time_unit = data[list(data.keys())[0]]['time zone']

    dtd=ET_DTD(StringIO(DTD_declaration))
    # read spreadheet data definition
    
    #parser=ET.XMLParser(dtd_validation=True)    
    
    tree = ET_parse(xml_path+fn_in_xml_definition) #,parser=parser)
    valid = dtd.validate(tree)
    if not valid:
        print('Error. XML definition is not valid.')
        print()
        print(DTD_declaration)
        print()
        print(dtd.error_log.filter_from_errors()[0])
        print()
        sys.exit(1)

    # get root element
    m=get_all_XML_tags(tree.getroot(),XML_main)
    if len(m)!=1:
        raise SyntaxError('Expect exactly one <%s> tag, %i found.' % (
                 XML_main, len(m)))
    measurements = m[0]

    if True:
        # new 13 June 2015
        # get global UNTIL mode flag
        # DTD does not enforce presence of this flag, so we use default if not present
        #global_until_mode = (_get_attrib_or_None(measurements,XML_attr_until_mode)
        #                     or global_until_mode_default)
        global_until_mode = _get_attrib_or_None(measurements,XML_attr_until_mode)
        if global_until_mode is None:
            global_until_mode=global_until_mode_default
            print('WARNING: Attribute "%s" not specified, implying "%s".' % (XML_attr_until_mode,global_until_mode))
            
        global_until_mode = global_until_mode.lower()
        # if specified it had better be valid
        if global_until_mode not in (XML_flag_until_inclusive,XML_flag_until_exclusive,XML_flag_until_disallowed):
            raise ValueError('Attribute %s must be one of %s, %s, or %s (default).' %
                             (XML_attr_until_mode,
                              XML_flag_until_inclusive, XML_flag_until_exclusive,
                              XML_flag_until_disallowed))
        
    if True:
        all_dates, sources = get_all_mapped_dates(data,measurements)
        for idx, date in enumerate(all_dates):
            datetime_idx_db[date] = idx

    if True:
        # make list of user-defined symbols
        
        # find all tags, regardless of nesting:
        elements = ( get_all_XML_tags(measurements,XML_def) +
                     get_all_XML_tags(measurements,XML_map) )

        user_vars = set({})
        for element in elements:
            # get name...
            var = _get_attrib_or_None(element,XML_attr_var)
            if (var is None) and (element.tag == XML_map):
                # or make name (if MAP element -- new 21 Mar 2015)
                var = _make_global_var_name(element)
            elif var is None:
                continue # there's nothing defined by this tag
            real_var = var.split('(')[0].strip() # if function, keep just name.
            user_vars.add(real_var)


    env=make_environment(measurements)
    if len(env_errors)>0:
        # create an EXCEL spread sheet that dumps
        #   all error messages,
        #   then terminate program
        print('ERROR PROCESSING XML FILE')
        print(env_errors)
        env_errors = [] # clear list

#    dump_symbols(env.symtable,default_symtable)

    groups = get_all_XML_tags(measurements,XML_group)
        
    if True:
        # make sure that
        # (a) no two groups have the same name (except empty)
        # (b) no group has a reserved name

        group_names = ['Time','metadata','_var']
        for group in groups:
            name = _get_attrib_or_None(group, XML_attr_name)
            if name == None: continue
            if name == "": continue # (we allow multiple empty names this)
            try:
                idx = group_names.index(name)
                error = True
            except ValueError:
                group_names.append(name)
                error = False

            if error:
                raise ValueError('Found multiple occurrences of group name "%s" or use of reserved group name.' % name)
            
    # make new workbook
    wb = xlsxwriter.Workbook(path_out+fn_out_excel+'-temp',
                             {'strings_to_numbers':  False,
                              'strings_to_formulas': True,
                              'strings_to_urls':     False})

    set_workbook_properties(wb)
    
    sheet = wb.add_worksheet('Data')    
    
    row,metadata = make_header(sheet, file_time_string)
    row_group_name = row+2
    
    structure = write_all(wb,sheet, row_group_name, groups, all_dates, data)
    structure['metadata']=metadata
    structure['Program_Version']=REVISION
    
    if True:
        # copy XML file used to create XLSX file        
        sheet_XML = wb.add_worksheet('Data Definition')        
        write_XML_file(wb,sheet_XML, xml_path+fn_in_xml_definition, tree.getroot())
        sheet_DTD = wb.add_worksheet('DTD')
        write_DTD(wb,sheet_DTD)

    if True:
        # output raw data
        sheet_sources = wb.add_worksheet('Raw Data')
        write_sources(wb,sheet_sources, sources)
        
        
    np.save(path_out+fn_out_structure,structure)

    # we write to a temporary file and rename since the writing process
    #  may literally take a minute or two.
    wb.close()
    if 'posix' in os.name:
        # Linux
        os.rename(path_out+fn_out_excel+'-temp',path_out+fn_out_excel)
    else:
        # Windows
        if os.path.exists(path_out+fn_out_excel):
            os.remove(path_out+fn_out_excel)
        os.rename(path_out+fn_out_excel+'-temp',path_out+fn_out_excel)


    if len(env_errors)>0:
        # create an EXCEL spread sheet that dumps
        #   all error messages,
        #   then terminate program
        print('ERROR PROCESSING XML FILE')
        print(env_errors)


##############################
#
#  test

def _test_detrend():
    # this is a unit test function
    try: import scipy.signal as ss
    except: ss=None
    if ss is None:
        raise NotImplementedError('Scipy not imported successfully.')
    N=100
    np.random.seed(1234)
    
    y=np.cumsum(np.random.random(N))
    a=_detrend(y)
    b=ss.detrend(y)
    print(np.max(np.fabs(a-b)))
    # 2.13162820728e-14
    
    y=y[None,:]
    a=_detrend(y)
    b=ss.detrend(y,axis=1)
    print(np.max(np.fabs(a-b)))
    # 2.13162820728e-14



if __name__=='__main__':
    config_file = './config.cfg'

    if len(sys.argv) == 2:
        config_file = sys.argv[1]

    main(config_file)
    
