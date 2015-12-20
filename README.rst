rawdatx
#######

rawdatx is a Python 2.7, 3.4, 3.5 converter that generates Excel xlsx files
from for Campbell Scientific TOA5 data logger files produced by LoggerNet. 
Sensor input, processing instructions, and output structure are specified 
in a single XML Definition File that also serves as documentation.

Installation
============

Make sure the following is installed:

* Python 2.7, 3.4, or 3.5
* numpy 1.9 or higher
* xlsxwriter

optionally (recommended):

* lxml
* asteval

Then install rawdatx with:

``pip install rawdatx``

Usage
=====

To convert a TOA5 file to XLSX, run the following script::

    import rawdatx.read_TOA5 as read_TOA5
    import rawdatx.process_XML as process_XML
    
    config = './config.cfg'
    read_raw_data.main(config)
    process_XML.main(config)

Input and output files are specified in an UTF-8 encoded 
configuration file ``config.cfg``:

.. code-block:: ini

    [RawData]
    raw_data_path       = ./raw-data/
    mask                = CR1000_*.dat
    logger_time_zone    = UTC+1

    [Metadata]
    Project      = My project name

    [Files]
    xml_map_path        = ./
    xml_map             = data_map.xml
    data_path           = ./    
    processed_data_xlsx = processed_data.xlsx
    xml_dtd_out         = data_map.dtd
    raw_data            = consolidated_raw_data.npy
    processed_data_npy  = processed_data.npy
    
The ``[RawData]`` section specifies the location of the logger input files,
the ``[Metadata]`` section defines metadata entries copied into the
XLSX file, and the ``[Files]`` section specifies path and file names of 
output and intermediate files (``data_path``) and input 
XML Definition File (``xml_map_path`` and ``xml_map``).

The XML Definition File (``data_map.xml``) may look like this:

.. code-block:: xml

    <?xml version="1.0" encoding="UTF-8" ?>
    <measurements from="2015/05/03 11:45">
        <group name="Logger">
            <map name="Battery Voltage" unit="V" src="Batt_V" />
            <map name="Internal Temperature" unit="°C" src="T_panel" />
        </group>
        <group name="Weather">
            <map name="Air Temperature" unit="°C" src="T_air" />
            <map name="Relative Humidity" unit="%" src="RH" />
            <map name="Wind Speed" unit="m/s" src="Wind_speed" />
            <map name="Wind Direction" unit="°" src="Wind_direction" />
        </group>
    </measurements>
