import unittest

import rawdatx.read_TOA5 as read_raw_data
import rawdatx.process_XML as process_XML

import glob, sys, os, hashlib, zipfile
try: import ConfigParser as configparser # Python 2
except ImportError: import configparser # Python 3


cfg="""
[RawData]
raw_data_path       = ./raw_data/
mask                = CR1000_mock*.dat
logger_time_zone    = UTC+1

[Metadata]
Project      = rawdatx
Web Page     = https://github.com/cpetrich/rawdatx
File Content = Functional test
Contact      = Chris Petrich
Comment      = Data are provided without warranty of fitness for a particular purpose.

[Files]
data_path           = %s
raw_data            = %s_raw_data.npy
processed_data_xlsx = %s_processed_data.xlsx
processed_data_npy  = %s_processed_data.npy
xml_dtd_out         = dtd_of_data_map.dtd
xml_map_path        = ./
xml_map             = %s
"""


class Tests(unittest.TestCase):
    def test_all(self):
        
        os.chdir( os.path.dirname(os.path.realpath(__file__)) )
        path_test_out = './output/'
        path_test_cfg = './output_cfg/'

        fns = glob.glob(os.path.join(path_test_out,'*'))
        for fn in fns:
            os.remove(fn)

        try: os.mkdir(path_test_cfg)
        except: pass

        def cfg_get_string(cfg, section, item):
            string = config.get(section,item)
            string = string.strip()
            if string[0] == '"': strpathing = string.strip('"')
            elif string[0] == "'": string = string.strip("'")
            return string
            
        
        # get config file from command line or use the one in current
        #   directory if there is only file ending in .cfg
        if len(sys.argv)==1:
            xml_file_names = glob.glob('*.xml')
        else:
            xml_file_names = glob.glob(sys.argv[1])

        self.assertNotEqual(len(xml_file_names),0)
        
        if len(xml_file_names)==0:
            ValueError('Missing XML Data File. Specify as command line parameter or place .xml file in this directory.')
            


        for xml_file_name in xml_file_names:

            print('Processing %s...' % xml_file_name)
            # generate config file:
            out = cfg % ((path_test_out,)+(xml_file_name,)*4)
            config_file_name = os.path.join(path_test_cfg,'test_config.cfg')
            with open(config_file_name,'wt') as f:
                f.write(out)

            #print('Processing %s...' % config_file_name)

            # get the data_path in [Files]
            #  if it exists, remove content of that path
            config = configparser.SafeConfigParser()
            config.read(config_file_name)
            path_out = cfg_get_string(config,'Files','data_path')
            xlsx_file = cfg_get_string(config,'Files','processed_data_xlsx')

            xml_file = cfg_get_string(config,'Files','xml_map')
            xml_path = cfg_get_string(config,'Files','xml_map_path')
            
            # figure out what the expected hash is. We stroe this in the comments
            #   of the .cfg files used for testing.
            
            with open(os.path.join(xml_path, xml_file),'rt') as f:
                data = f.read()
            try: expected_primitive_hash = data.split('hash of the result is: ')[1].split(' ')[0]
            except IndexError: expected_primitive_hash = None

            # do the actual processing
            read_raw_data.main(config_file_name)
            process_XML.main(config_file_name)

            # check numerical cell content
            #   by calculating a primitive hash function
            #   that should be robust against changes in external libraries
            #   and Py2/Py3 data formats
            # the whole thing here should be improved
            fn = os.path.join(path_out,xlsx_file)
            with zipfile.ZipFile(fn,'r') as f:        
                sheet = str(f.read('xl/worksheets/sheet1.xml'))            
            values = [e.split('<v>')[1].split('</v>')[0] if len(e.split('<v>'))==2 else '' for e in sheet.split('<c ')[1:]]
            cells = [e.split('r="')[1].split('"')[0] for e in sheet.split('<c ')[1:]]    
            number_type = [True if 't="' not in e.split('>')[0] else False for e in sheet.split('<c ')[1:]]

            self.assertEqual((len(values),len(values)),(len(cells), len(number_type)))
            
            if (len(values),len(values)) != (len(cells), len(number_type)):
                raise ValueError('unexpected formatting of spread sheet')
            
            true_numbers = [value for num_t, value in zip(number_type, values) if num_t and (value != '')]
            true_cells = [cell for num_t, value, cell in zip(number_type, values, cells) if num_t and (value != '')]

            primitive_hash = '%X' % (len(true_numbers) + sum([(i % 13+1)*(ord(c)-ord('0')) for i,c in enumerate(''.join(true_numbers))]))


            self.assertEqual(expected_primitive_hash, primitive_hash)

            if expected_primitive_hash is not None:
                if primitive_hash != expected_primitive_hash:
                    raise ValueError('Unexpected numerical content of the spread sheet:\n  expected: %s, found: %s' % (
                        expected_primitive_hash, primitive_hash))                
                print('pass')
            else:    
                print('no hash to verify. Hash of file is %s' % primitive_hash)
                raise ValueError('Did not find hash to verify in .cgf file.')
        
if __name__=='__main__':
    unittest.main()
