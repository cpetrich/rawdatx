#!/usr/bin/env python3

import datetime
import numpy as np
try: import ConfigParser as configparser # Python 2
except ImportError: import configparser # Python 3
import sys, glob, os
try: dummy = xrange(3) # Python 2
except NameError: xrange=range # Python 3

# 25 Dec 2018: allow for string data
# 19 Dec 2015: remove use of deepcopy() on dictionary to make this work
#              with currently incomplete implementation of pypy's numpy.
#              regardless, np.save() does not work with datetime objects under
#              pypy.
# 12 Jun 2015: now reads multiple files representing data for the same data table
# 22 Mar 2015: now reads time zone info from config file
#   and retains it in output file (each record)


def main(config_file):
    config = configparser.SafeConfigParser()
    config.read(config_file)


    def cfg_get_string(cfg, section, item):
        string = config.get(section,item)
        string = string.strip()
        if string[0] == '"': string = string.strip('"')
        elif string[0] == "'": string = string.strip("'")
        return string

    if True:
        CFG_raw_path='RawData'
        path_in = cfg_get_string(config,CFG_raw_path,'raw_data_path')
        logger_time_zone = cfg_get_string(config,CFG_raw_path,'logger_time_zone')

        fns_in = []
        # get file entries by mask, e.g.
        #   mask = *.dat
        if config.has_option(CFG_raw_path,'mask'):
            fns_in = glob.glob('/'.join([path_in,cfg_get_string(config,CFG_raw_path,'mask')]))
        if True:
            # file name entries start with 'file' followed by anything else
            # read specified files, e.g.
            #   file 1  = xyz.dat
            #   file 2  = abc.dat
            items= config.items(CFG_raw_path)
            for item in items:
                if item[0].startswith('file'):
                    fns_in.append('/'.join([path_in,cfg_get_string(config,CFG_raw_path,item[0])]))

    CFG_fn_path='Files'
    path_out = cfg_get_string(config,CFG_fn_path,'data_path')
    fn_out_npy = cfg_get_string(config,CFG_fn_path,'raw_data')


    def get_file_content(filename, skip_before=0, skip_after=0,
                         header_quoted=False,delimiter=','):
        """Parse data of a text file"""
        # read file all at once for the sake of performance
        f=open(filename,'rt')
        file_content = f.readlines()
        f.close()

        # skip metadata
        for times in xrange(skip_before):
            file_content.pop(0)

        # extract column names
        if header_quoted:
            # header titles are enclosed in "
            header_keys = file_content.pop(0).strip().split('"'+delimiter+'"')
            header_keys[0]=header_keys[0][1:] # remove leading "
            header_keys[-1]=header_keys[-1][:-1] # remove trailing "
        else:
            # plain header titles delimited by ,
            header_keys = file_content.pop(0).strip().split(delimiter)

        # skip metadata
        for times in xrange(skip_after):
            file_content.pop(0)


        return file_content, header_keys

    def extract_values(content, value_names, value_types=None,
                            start_date=None,end_date=None):
        """Return dictionary of numpy arrays of the form data[value_name]['dates'] and ...['values']"""
        # start_date is inclusive while end_date is exclusive

        file_content, header_keys = content

        # hard-coded name of time stamp column (usually column 0)
        dates_name = 'TIMESTAMP'
        values_name = value_names
        if value_types == None:
            type_name = ['float'] * len(values_name)
        else:
            type_name = value_types

        # start with empty dictionary
        data = {}

        if True:
            # find column index of values
            dates_idx = header_keys.index(dates_name)
            values_idx = []
            for name in values_name:
                values_idx.append(header_keys.index(name))


            while len(file_content)>0:
                line = file_content.pop(0)
                val = line.strip().split(",") # assuming that no string contains a comma

                if val[dates_idx][0]=='"': # date is quoted, remove quotes
                    val[dates_idx]=val[dates_idx][1:-1]
                this_date = datetime.datetime.strptime(val[dates_idx],'%Y-%m-%d %H:%M:%S')

                # is time out of bounds ?
                if (start_date != None) and (this_date < start_date): continue
                if (end_date != None) and (this_date >= end_date): continue

                for idx in xrange(len(values_idx)):
                    value_str = val[values_idx[idx]]
                    if type_name[idx].lower() == 'float':
                        try:
                            value = float(value_str) # also converts NAN, INF, and -INF
                            if np.fabs(value)>1e15: value = np.nan # some malfunctioning sensor
                            if np.isinf(value): value = np.nan # turn INF to NAN
                        except ValueError:
                            # use IN to capture both "NAN" and NAN
                            if 'NAN' in value_str.upper():
                                value = np.nan
                            elif 'INF' in value_str.upper():
                                value = np.inf
                                value = np.nan   # turn INF to NAN
                            elif value_str.startswith('"') and value_str.endswith('"'):
                                value = value_str[1:-1] # copy string, even though we expect a float
                            else:
                                raise ValueError('cannot interpret value %s as %s' % (
                                    value_str, type_name[idx]))
                    elif type_name[idx].lower() == 'int':
                        value = int(value_str)
                        # not sure how to deal with NAN and INF for int
                    else:
                        raise ValueError('value type %s not implemented' % type_name[idx])
                    try:
                        data[values_name[idx]]['dates'].append(this_date)
                        data[values_name[idx]]['values'].append(value)
                    except KeyError:
                        # first entry
                        data[values_name[idx]]={
                            'dates':[this_date],
                            'values':[value],
                            'time zone': logger_time_zone}

            # convert lists to arrays
            for idx in xrange(len(values_idx)):
                for key in ('dates','values'):
                    data[values_name[idx]][key]=np.array(data[values_name[idx]][key])

        # return dictionaly of results
        return data



    def get_CS_file_content(filename):
        """Parse data of a Campbell Scientific data file"""
        # Convenience function
        return get_file_content(filename,
                                skip_before=1,
                                skip_after=2,
                                delimiter=',',
                                header_quoted=True)

    def get_CS_entries_as_dict(filename, value_names, value_types=None,
                            start_date=None,end_date=None):
        """Convenience function for CR1000 data logger files"""

        # read file content
        file_content, header_keys = get_CS_file_content(filename)

        # extract value
        if value_names == None:
            value_names = header_keys[:]
            try: value_names.remove('TIMESTAMP')
            except: pass

        return (extract_values((file_content, header_keys),
                               value_names, value_types,
                               start_date,end_date),
                header_keys)

    # since 12 June 2015
    # assume we have several files for each data table
    #  with non-overlapping date ranges

    data = None
    header_keys = []
    for fn in fns_in:
        # import all data from file
        new_data, new_header_keys = get_CS_entries_as_dict(fn,None)
        header_keys+=new_header_keys
        if data is None: data = new_data
        else:
            for variable in new_data:
                if variable not in data:
                    # not yet seen: create
                    data[variable]={}
                    for key in ('dates','values'):
                        data[variable][key]=new_data[variable][key][:]
                    data[variable]['time zone']=new_data[variable]['time zone']
                else:
                    # seen before: append
                    for key in ('dates','values'):
                        data[variable][key]=np.hstack((data[variable][key],
                                                       new_data[variable][key]))
                    if data[variable]['time zone'] != new_data[variable]['time zone']:
                        raise ValueError('Time zone mismatch in file %s, variable %s' % (fn, variable))

    # now make sure all variable arrays are sorted by time
    # TODO: deal with double entries(?)
    for variable in data.keys():

        if True:
            # the obvious way, for recent versions of numpy
            dates_to_sort = data[variable]['dates']
        else:
            # work-around for pypy's numpy implementation and old numpys
            t_ref = datetime.datetime(1900,1,1)
            dates_to_sort = [(t-t_ref).total_seconds() for t in data[variable]['dates']]
        idx=np.argsort(dates_to_sort)

        for key in ('dates','values'):
            data[variable][key]=data[variable][key][idx]
    # as per 13 June 2015, keep track of the order of header entries encountered
    if '__header_order_encountered__' in data:
        raise ValueError('unexpected variable name')
    data['__header_order_encountered__'] = header_keys

    # write dictionary to disc for future use
    try: os.makedirs(path_out)
    except OSError: pass # exists already
    np.save(path_out+fn_out_npy,data)


if __name__=='__main__':

    config_file = './config.cfg'

    if len(sys.argv) == 2:
        config_file = sys.argv[1]

    main(config_file)
