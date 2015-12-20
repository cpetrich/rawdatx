import rawdatx.read_TOA5 as read_raw_data
import rawdatx.process_XML as process_XML

config = './config.cfg'
read_raw_data.main(config)
process_XML.main(config)
