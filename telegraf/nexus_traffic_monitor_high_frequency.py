#! /usr/bin/python3
"""Pull stats from Cisco Nexus 9000 switches (N9K) and print output in the
desired output format"""

__author__ = "Paresh Gupta"
__version__ = "0.36"
__updated__ = "11-Oct-2024-4-PM-PDT"

import sys
import os
import argparse
import logging
from logging.handlers import RotatingFileHandler
import json
import time
import re
from datetime import datetime,timedelta
import subprocess
import requests
import urllib3

HOURS_IN_DAY = 24
MINUTES_IN_HOUR = 60
SECONDS_IN_MINUTE = 60

user_args = {}
FILENAME_PREFIX = __file__.replace('.py', '')
INPUT_FILE_PREFIX = ''

LOGFILE_LOCATION = '/var/log/telegraf/'
LOGFILE_SIZE = 10000000
LOGFILE_NUMBER = 10
logger = logging.getLogger('NTM')

# Dictionary with key as IP and value as list of user and passwd
switch_dict = {}

# Stats for all switch components are collected here before printing
# in the desired output format
stats_dict = {}

# Used to store objects returned by the stats pull. These must be processed
# to update stats_dict
raw_cli_stats = {}

proxies = {
    "http": "",
    "https": "",
    }

'''
Tracks response and parsing time
response_time_dict : {
                      'switch_ip' : [
                                        {
                                            'nxapi_start':'time',
                                            'nxapi_rsp':'time',
                                            'nxapi_parse':'time'
                                        },
                                        {
                                            'nxapi_start':'time',
                                            'nxapi_rsp':'time',
                                            'nxapi_parse':'time'
                                        },
                                        ...
                                        As many items as the # of commands
                                        ...
                                        {
                                            'nxapi_start':'time',
                                            'nxapi_rsp':'time',
                                            'nxapi_parse':'time'
                                        },
                                    ]
                      }
'''
response_time_dict = {}

###############################################################################
# BEGIN: Generic functions
###############################################################################

def run_cmd(cmd_list):
    """Generic function to run any command"""
    ret = None
    # TODO: This ret needs proper handling
    try:
        output = subprocess.run(cmd_list, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        if output.returncode != 0:
            logger.error('%s failed:%s', cmd_list, \
                         str(output.stderr.decode('utf-8').strip()))
        else:
            ret = str(output.stdout.decode('utf-8').strip())
    except Exception as e:
        logger.exception('Exception: %s', e)
    return ret

def pre_checks_passed(argv):
    """Python version check"""

    if sys.version_info[0] < 3:
        print('Unsupported with Python 2. Must use Python 3')
        logger.error('Unsupported with Python 2. Must use Python 3')
        return False
    if len(argv) <= 1:
        print('Try -h option for usage help')
        return False

    return True

def parse_cmdline_arguments():
    """Parse input arguments"""

    desc_str = \
    'Pull stats from Cisco Nexus 9000 switches and print output in \n' + \
    'formats like InfluxDB Line protocol'
    epilog_str = \
    'This file pulls stats from Cisco Nexus 9000 switch and converts them \n' + \
    'into a database insert format. The database can be used by an app like\n' + \
    'Grafana. The initial version was coded to insert into InfluxDB.\n' + \
    'Before converting into any specific format (like InfluxDB Line\n' + \
    'Protocol), the data is correlated in a hierarchical dictionary.\n' + \
    'This dictionary can be parsed to output the data into other formats.\n' +\
    'Overall, the output can be extended for other databases also.\n\n' + \
    'High level steps:\n' + \
    '  - Read access details of a Cisco N9k switches (IP Address, user\n' + \
    '    (read-only is enough) and password) from the input file\n' + \
    '  - Use NX-API or CLI/SSH to pull stats\n'+ \
    '  - Stitch the output for end-to-end traffic mapping and store\n' + \
    '    in a dictionary\n' + \
    '  - Finally, read the dictionary content to print in the desired\n' + \
    '    output format, like InfluxDB Line Protocol'

    parser = argparse.ArgumentParser(description=desc_str, epilog=epilog_str,
                formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('input_file', action='store', help='file containing \
            the switch information in the format: IP,user,password,...')
    parser.add_argument('output_format', action='store', help='specify the \
            output format', choices=['dict', 'influxdb-lp'])
    parser.add_argument('-intfstr', dest='intf_str', \
            action='store_true', default=False, help='Prebuild interface \
            string to use with show interface command')
    parser.add_argument('-intfcntrstr', dest='intf_cntr_str', \
            action='store_true', default=False, help='Use prebuilt \
            interface string with show interface counter detail \
            command')
    parser.add_argument('-burst', dest='burst', \
            action='store_true', default=False, help='Pull NX-OS command \
            show queuing burst-detect using NX-API')
    parser.add_argument('-pfcwd', dest='pfcwd', \
            action='store_true', default=False, help='Pull NX-OS command \
            show queuing pfc-queue detail using NX-API')
    parser.add_argument('-bufferstats', dest='bufferstats', \
            action='store_true', default=False, help='Pull NX-OS command \
            show hardware internal buffer info pkt-stats using NX-API and \
            clear counters buffers using SSH/Expect')
    parser.add_argument('-V', dest='verify_only', \
            action='store_true', default=False, help='verify \
            connection and stats pull but do not print the stats')
    parser.add_argument('-v', dest='verbose', \
            action='store_true', default=False, help='warn and above')
    parser.add_argument('-vv', dest='more_verbose', \
            action='store_true', default=False, help='info and above')
    parser.add_argument('-vvv', dest='most_verbose', \
            action='store_true', default=False, help='debug and above')
    parser.add_argument('-vvvv', dest='raw_dump', \
            action='store_true', default=False, help='Dump raw data')

    args = parser.parse_args()
    user_args['input_file'] = args.input_file
    user_args['output_format'] = args.output_format
    user_args['intf_str'] = args.intf_str
    user_args['intf_cntr_str'] = args.intf_cntr_str
    user_args['cli_json'] = False
    user_args['burst'] = args.burst
    user_args['pfcwd'] = args.pfcwd
    user_args['bufferstats'] = args.bufferstats
    user_args['verify_only'] = args.verify_only
    user_args['verbose'] = args.verbose
    user_args['more_verbose'] = args.more_verbose
    user_args['most_verbose'] = args.most_verbose
    user_args['raw_dump'] = args.raw_dump

    global INPUT_FILE_PREFIX
    INPUT_FILE_PREFIX = \
            ((((user_args['input_file']).split('/'))[-1]).split('.'))[0]

def setup_logging():
    """Setup logging"""

    this_filename = (FILENAME_PREFIX.split('/'))[-1]
    logfile_location = LOGFILE_LOCATION + this_filename
    logfile_prefix = logfile_location + '/' + this_filename
    try:
        os.mkdir(logfile_location)
    except FileExistsError:
        pass
    except Exception:
        # Log in local directory if can't be created in LOGFILE_LOCATION
        logfile_prefix = FILENAME_PREFIX
    finally:
        logfile_name = logfile_prefix + '_' + INPUT_FILE_PREFIX + '.log'
        rotator = RotatingFileHandler(logfile_name, maxBytes=LOGFILE_SIZE,
                                      backupCount=LOGFILE_NUMBER)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - ' \
                                        '%(message)s')
        rotator.setFormatter(formatter)
        logger.addHandler(rotator)

        if user_args.get('verbose'):
            logger.setLevel(logging.WARNING)
        if user_args.get('more_verbose'):
            logger.setLevel(logging.INFO)
        if user_args.get('most_verbose') or user_args.get('raw_dump'):
            logger.setLevel(logging.DEBUG)

###############################################################################
# END: Generic functions
###############################################################################

###############################################################################
# BEGIN: Output functions
###############################################################################

def print_output_in_influxdb_lp(switch_ip, per_switch_stats_dict):
    """
    InfluxDB Line Protocol Reference
        * Never double or single quote the timestamp
        * Never single quote field values
        * Do not double or single quote measurement names, tag keys, tag values
          and field keys
        * Do not double quote field values that are floats, integers, Booleans
        * Do double quote field values that are strings
        * Performance tips: sort by tag key
    e.g: Measurement,tag1=tag1val,tag2=tag2val Field1="testData",Field2=3 ts_ns
    """
    final_print_string = ''
    switch_prefix = 'Switches'
    buffer_prefix = 'SwitchBufferStats'
    intf_prefix = 'SwitchIntfStats'
    q_prefix = 'SwitchQStats'
    wd_prefix = 'SwitchPFCWD'
    burst_prefix = 'SwitchBurst'
    sys_ver = ''

    switch_tags = ''
    switch_fields = ''

    if 'location' in per_switch_stats_dict:
        switch_tags = switch_tags + ',location=' + \
                      per_switch_stats_dict['location']

    switch_tags = switch_tags + ',switch=' + switch_ip

    if 'switchname' in per_switch_stats_dict:
        switch_tags = switch_tags + ',switchname=' + \
                      per_switch_stats_dict['switchname']

    if 'type' in per_switch_stats_dict:
        switch_tags = switch_tags + ',type=' + \
                      per_switch_stats_dict['type']

    if 'response_time' in per_switch_stats_dict:
        switch_fields = switch_fields + ' response_time=' + \
                        str(per_switch_stats_dict['response_time'])

    if 'model' in per_switch_stats_dict:
        switch_fields = switch_fields + ',model="' + \
                        per_switch_stats_dict['model'] + '"'

    if 'cpu_kernel' in per_switch_stats_dict:
        switch_fields = switch_fields + ',cpu_kernel=' + \
                        str(per_switch_stats_dict['cpu_kernel'])

    if 'cpu_user' in per_switch_stats_dict:
        switch_fields = switch_fields + ',cpu_user=' + \
                        str(per_switch_stats_dict['cpu_user'])

    if 'mem_total' in per_switch_stats_dict:
        switch_fields = switch_fields + ',mem_total=' + \
                        str(per_switch_stats_dict['mem_total'])

    if 'mem_used' in per_switch_stats_dict:
        switch_fields = switch_fields + ',mem_used=' + \
                        str(per_switch_stats_dict['mem_used'])

    if 'sys_ver' in per_switch_stats_dict:
        switch_fields = switch_fields + ',sys_ver="' + \
                        per_switch_stats_dict['sys_ver'] + '"'
        sys_ver = per_switch_stats_dict['sys_ver']

    if 'kernel_uptime' in per_switch_stats_dict:
        switch_fields = switch_fields + ',kernel_uptime=' + \
                        str(per_switch_stats_dict['kernel_uptime'])

    switch_fields = switch_fields + '\n'
    final_print_string = final_print_string + switch_prefix + \
                         switch_tags + switch_fields

    if 'buffer_usage' in per_switch_stats_dict:
        for instance,instance_dict in \
                per_switch_stats_dict['buffer_usage'].items():
            buffer_tags = ''
            buffer_fields = ''
            buffer_tags = ',instance=' + str(instance)
            if 'location' in per_switch_stats_dict:
                buffer_tags = buffer_tags + ',location=' + \
                              per_switch_stats_dict['location']

            buffer_tags = buffer_tags + ',switch=' + switch_ip

            if 'switchname' in per_switch_stats_dict:
                buffer_tags = buffer_tags + ',switchname=' + \
                              per_switch_stats_dict['switchname']

            if 'type' in per_switch_stats_dict:
                buffer_tags = buffer_tags + ',type=' + \
                              per_switch_stats_dict['type']
            if 'peak_cell_drop_pg' in instance_dict:
                buffer_fields = buffer_fields + ' peak_cell_drop_pg=' + \
                                str(instance_dict['peak_cell_drop_pg'])
            if 'peak_cell_no_drop' in instance_dict:
                buffer_fields = buffer_fields + ',peak_cell_no_drop=' + \
                                str(instance_dict['peak_cell_no_drop'])
            if 'cell_count_drop_pg' in instance_dict:
                buffer_fields = buffer_fields + ',cell_count_drop_pg=' + \
                                str(instance_dict['cell_count_drop_pg'])
            if 'cell_count_no_drop_pg' in instance_dict:
                buffer_fields = buffer_fields + ',cell_count_no_drop_pg=' + \
                                str(instance_dict['cell_count_no_drop_pg'])

            buffer_fields = buffer_fields + '\n'
            final_print_string = final_print_string + buffer_prefix + \
                                 buffer_tags + buffer_fields

    intf_str = ''
    q_str = ''
    wd_str = ''
    burst_str = ''
    intf_dict = per_switch_stats_dict['intf']
    for intf, per_intf_dict in intf_dict.items():
        intf_tags = ''
        intf_fields = ''
        ts_ns_i = ''

        if 'location' in per_switch_stats_dict:
            intf_tags = intf_tags + ',location=' + \
                      per_switch_stats_dict['location']

        if 'meta' in per_intf_dict.keys():
            for key, val in sorted((per_intf_dict['meta']).items()):
                # Avoid null tags
                if str(val) == '':
                    continue
                if str(key) == 'modTs':
                    # TODO: Update this as per timezone
                    # CSCwk10807. Timezone adjustment not needed 10.5(1) onwards
                    #utc = datetime.fromisoformat(str(val)) + timedelta(hours=7)
                    if sys_ver == '':
                        utc = datetime.fromisoformat(str(val))
                    else:
                        if sys_ver < '10.5(1)':
                            utc = datetime.fromisoformat(str(val)) + timedelta(hours=7)
                        else:
                            utc = datetime.fromisoformat(str(val))
                    # "2024-05-18T18:04:19.900+00:00"
                    # switch returns ms. write with us. Keep ns to 1000
                    ts_ns_i = str(int(datetime.timestamp(utc) * 1000000) * 1000)
                    continue
                intf_tags = intf_tags + ',' + key + '=' + str(val)

        intf_tags = intf_tags + ',switch=' + switch_ip + \
                    ',intf=' + intf

        if 'switchname' in per_switch_stats_dict:
            intf_tags = intf_tags + ',switchname=' + \
                            str(per_switch_stats_dict['switchname'])

        if 'type' in per_switch_stats_dict:
            intf_tags = intf_tags + ',type=' + \
                          per_switch_stats_dict['type']

        if 'data' in per_intf_dict.keys():
            for key, val in sorted((per_intf_dict['data']).items()):
                sep = ' ' if intf_fields == '' else ','
                if val is None:
                    logger.warning('Skipping empty field %s for %s %s',
                            key, switch_ip, intf)
                    continue

                if key in ('description', 'down_reason'):
                    intf_fields = intf_fields + sep + key + '="' + str(val) + '"'
                else:
                    intf_fields = intf_fields + sep + key + '=' + str(val)

        ts_ns_i = ' ' + ts_ns_i + '\n'
        intf_str = intf_str + intf_prefix + intf_tags + intf_fields + ts_ns_i

        if 'out_queue' in per_intf_dict.keys():
            q_dict = per_intf_dict['out_queue']
            for q_name, per_q_dict in q_dict.items():
                q_tags = ''
                q_fields = ''
                ts_ns_q = ''

                q_tags = q_tags + ',intf=' + intf

                if 'location' in per_switch_stats_dict:
                    q_tags = q_tags + ',location=' + \
                          per_switch_stats_dict['location']

                if 'meta' in per_intf_dict.keys():
                    if 'peer' in per_intf_dict['meta']:
                        q_tags = q_tags + ',peer=' + per_intf_dict['meta']['peer']
                    if 'peer_intf' in per_intf_dict['meta']:
                        q_tags = q_tags + ',peer_intf=' + \
                                 per_intf_dict['meta']['peer_intf']
                    if 'peer_name' in per_intf_dict['meta']:
                        q_tags = q_tags + ',peer_name=' + \
                                 per_intf_dict['meta']['peer_name']
                    if 'peer_type' in per_intf_dict['meta']:
                        q_tags = q_tags + ',peer_type=' + \
                                 per_intf_dict['meta']['peer_type']

                if 'switchname' in per_switch_stats_dict:
                    q_tags = q_tags + ',switchname=' + \
                                str(per_switch_stats_dict['switchname'])

                q_tags = q_tags + ',q=' + q_name
                q_tags = q_tags + ',switch=' + switch_ip

                if 'type' in per_switch_stats_dict:
                    q_tags = q_tags + ',type=' + \
                              per_switch_stats_dict['type']
                for key, val in sorted(per_q_dict.items()):
                    if val is None:
                        logger.warning('Skipping empty field %s for %s %s %s',
                                key, switch_ip, intf, q_name)
                        continue
                    if str(key) == 'modTs':
                        # TODO: Update this as per timezone
                        utc = datetime.fromisoformat(str(val)) + \
                                                    timedelta(hours=7)
                        # "2024-05-18T18:04:19.900+00:00"
                        # switch returns ms. write with us  . Keep ns to 1000
                        ts_ns_q = str(int(datetime.timestamp(utc) * 1000000) \
                                                                     * 1000)
                        continue

                    sep = ' ' if q_fields == '' else ','
                    q_fields = q_fields + sep + key + '=' + str(val)
                #ts_ns_q = ' ' + ts_ns_q + '\n'
                q_fields = q_fields + '\n'
                #q_str = q_str + q_prefix + q_tags + q_fields + ts_ns_q
                q_str = q_str + q_prefix + q_tags + q_fields

        if 'pfcwd' in per_intf_dict.keys():
            pfcwd_dict = per_intf_dict['pfcwd']
            if not pfcwd_dict:
                # Skip interfaces the return no data for PFC WD
                continue
            wd_tags = ',intf=' + intf
            wd_fields = ''
            if 'location' in per_switch_stats_dict:
                wd_tags = wd_tags + ',location=' + \
                                    per_switch_stats_dict['location']
            for k,v in pfcwd_dict.items():
                if 'qosgrp' in k:
                    wd_tags = wd_tags + ',' + str(k) + '=' + str(v)
                else:
                    sep = ' ' if wd_fields == '' else ','
                    wd_fields = wd_fields + sep + k + '=' + str(v)
            wd_tags = wd_tags + ',switch=' + switch_ip
            if 'switchname' in per_switch_stats_dict:
                wd_tags = wd_tags + ',switchname=' + \
                            str(per_switch_stats_dict['switchname'])
            wd_fields = wd_fields + '\n'
            wd_str = wd_str + wd_prefix + wd_tags + wd_fields

        if 'burst' in per_intf_dict.keys():
            burst_list = per_intf_dict['burst']
            for burst_dict in burst_list:
                burst_tags = ',intf=' + intf
                burst_fields = ''
                ts_ns_b = ''
                if 'location' in per_switch_stats_dict:
                    burst_tags = burst_tags + ',location=' + \
                                            per_switch_stats_dict['location']
                for k,v in burst_dict.items():
                    if 'q' in k:
                        burst_tags = burst_tags + ',' + str(k) + '=' + str(v)
                    elif 'peak-time' in k:
                        # "peak-time": "2024/04/30 09:05:33:777848",
                        format_str = '%Y/%m/%d %H:%M:%S:%f'
                        utc = datetime.strptime(v, format_str)
                        # Multiple by 1000 after converting to decimal to ensure that
                        # last 3 dights are 0 and the point remains unchanged
                        # This ensures that the burst event is overwritten in InfluxDB
                        ts_ns_b = str(int(datetime.timestamp(utc) * 1000000) * 1000)
                    else:
                        sep = ' ' if burst_fields == '' else ','
                        burst_fields = burst_fields + sep + k + '=' + str(v)

                burst_tags = burst_tags + ',switch=' + switch_ip
                if 'switchname' in per_switch_stats_dict:
                    burst_tags = burst_tags + ',switchname=' + \
                                str(per_switch_stats_dict['switchname'])
                ts_ns_b = ' ' + ts_ns_b + '\n'
                burst_str = burst_str + burst_prefix + burst_tags + \
                            burst_fields + ts_ns_b

    final_print_string = final_print_string + intf_str
    final_print_string = final_print_string + q_str
    final_print_string = final_print_string + wd_str
    final_print_string = final_print_string + burst_str

    print(final_print_string)


def print_output(switch_ip, per_switch_stats_dict):
    """Print outout in the desired output format"""

    if user_args['verify_only']:
        logger.info('Skipping output in %s due to -V option',
                    user_args['output_format'])
        return
    if user_args['output_format'] == 'dict':
        current_log_level = logger.level
        logger.setLevel(logging.DEBUG)
        logger.info('Printing per_switch_stats_dict for %s', switch_ip)
        logger.debug('\n%s', json.dumps(per_switch_stats_dict, indent=2))
        logger.info('Printing output for %s DONE', switch_ip)
        logger.setLevel(current_log_level)
    if user_args['output_format'] == 'influxdb-lp':
        logger.info('Printing output in InfluxDB Line Protocol format')
        print_output_in_influxdb_lp(switch_ip, per_switch_stats_dict)
        logger.info('Printing output - DONE')

###############################################################################
# END: Output functions
###############################################################################

###############################################################################
# BEGIN: Parser functions
###############################################################################

def get_float_from_string(s):
    """
    Clean up function for dirty data. Used for transceiver stats like
    current, voltage, etc.
    """
    ret = ''.join(re.findall(r"[-+]?\d*\.\d+|\d+", s))

    if len(ret) == 0:
        return 0

    return float(ret)

def get_speed_num_from_string(speed):
    """
    Just retain the number in gbps. 100 Gbps => 100, 400Gbps => 400
    strip off gbps, etc.
    """
    if speed.isdigit():
        return (int)(speed)

    return (int)(get_float_from_string(speed))

def parse_intf(imdata_list, per_switch_stats_dict, mo):
    """Extract mostly the metadata for the interfaces"""
    intf_dict = per_switch_stats_dict['intf']
    for imdata in imdata_list:
        for mo_name, attr in imdata.items():
            for attribute, attributes in attr.items():
                if 'dn' not in attributes:
                    logger.error('dn not found %s:%s',
                            mo, json.dumps(imdata_list, indent=2))
                    continue
                dn = attributes.get('dn')
                if 'mgmt' in dn or 'lo' in dn or 'svi' in dn or '.' in dn:
                    continue
                if 'id' not in attributes:
                    logger.error('intf id not found %s:%s',
                            mo, json.dumps(imdata_list, indent=2))
                    continue
                interface = attributes.get('id')
                '''
                # This isn't needed because Grafana latest releases supports
                # sorting varibale values using Natural (asc) order. But keep
                # code just in case
                # make single digit numbers to two digits for sorting in GUI
                interface_list = interface.split('/')
                if len(interface_list) > 1:
                    port_id = interface_list[-1]
                    if len(port_id) == 1:
                        port_id = '0' + port_id
                        interface = '/'.join(interface_list[0:-1]) + '/' + port_id
                 '''

                if interface not in intf_dict:
                    intf_dict[interface] = {}
                per_intf_dict = intf_dict[interface]

                if 'data' not in per_intf_dict:
                    per_intf_dict['data'] = {}
                data_dict = per_intf_dict['data']

                data_dict['description'] = attributes.get('descr')

                if 'meta' not in per_intf_dict:
                    per_intf_dict['meta'] = {}
                meta_dict = per_intf_dict['meta']

                meta_dict['admin_state'] = attributes.get('adminSt')
                meta_dict['oper_state'] = attributes.get('operSt')
                meta_dict['oper_mode'] = attributes.get('mode')

def parse_ethpmPhysIf(imdata_list, per_switch_stats_dict, mo):
    """Extract mostly the metadata for the interfaces"""
    intf_dict = per_switch_stats_dict['intf']
    for imdata in imdata_list:
        for mo_name, attr in imdata.items():
            for attribute, attributes in attr.items():
                if 'dn' not in attributes:
                    logger.error('dn not found %s:%s',
                            mo, json.dumps(imdata_list, indent=2))
                    continue
                dn = attributes.get('dn')
                if 'mgmt' in dn or 'lo' in dn or 'svi' in dn or '.' in dn:
                    continue
                interface = dn[dn.find('[') + 1 : dn.find(']')]
                '''
                # This isn't needed because Grafana latest releases supports
                # sorting varibale values using Natural (asc) order. But keep
                # code just in case
                # make single digit numbers to two digits for sorting in GUI
                interface_list = interface.split('/')
                if len(interface_list) > 1:
                    port_id = interface_list[-1]
                    if len(port_id) == 1:
                        port_id = '0' + port_id
                        interface = '/'.join(interface_list[0:-1]) + '/' + port_id
                '''

                if interface not in intf_dict:
                    intf_dict[interface] = {}
                per_intf_dict = intf_dict[interface]

                if 'meta' not in per_intf_dict:
                    per_intf_dict['meta'] = {}
                meta_dict = per_intf_dict['meta']

                meta_dict['oper_state'] = attributes.get('operSt')

                if 'data' not in per_intf_dict:
                    per_intf_dict['data'] = {}
                data_dict = per_intf_dict['data']

                data_dict['oper_speed'] = \
                    get_speed_num_from_string(attributes.get('operSpeed'))
                if 'up' not in attributes.get('operSt'):
                    data_dict['down_reason'] = attributes.get('operStQual')

def parse_rmonEtherStats(imdata_list, per_switch_stats_dict, mo):
    """Extract stats for the interfaces"""
    intf_dict = per_switch_stats_dict['intf']
    for imdata in imdata_list:
        for mo_name, attr in imdata.items():
            for attribute, attributes in attr.items():
                if 'dn' not in attributes:
                    logger.error('dn not found %s:%s',
                            mo, json.dumps(imdata_list, indent=2))
                    continue
                dn = attributes.get('dn')
                if 'mgmt' in dn or 'lo' in dn or 'svi' in dn or '.' in dn:
                    continue
                interface = dn[dn.find('[') + 1 : dn.find(']')]
                '''
                # This isn't needed because Grafana latest releases supports
                # sorting varibale values using Natural (asc) order. But keep
                # code just in case
                # make single digit numbers to two digits for sorting in GUI
                interface_list = interface.split('/')
                if len(interface_list) > 1:
                    port_id = interface_list[-1]
                    if len(port_id) == 1:
                        port_id = '0' + port_id
                        interface = '/'.join(interface_list[0:-1]) + '/' + port_id
                '''

                if interface not in intf_dict:
                    intf_dict[interface] = {}
                per_intf_dict = intf_dict[interface]

                if 'data' not in per_intf_dict:
                    per_intf_dict['data'] = {}
                data_dict = per_intf_dict['data']

                # TODO: Need handling when an attribute is not returned,
                # which results in None, causing error on influx field type
                data_dict['rx_crc'] = attributes.get('cRCAlignErrors')
                data_dict['rx_crc_stomped'] = attributes.get('stompedCRCAlignErrors')
                data_dict['tx_jumbo'] = attributes.get('txOversizePkts')
                data_dict['rx_jumbo'] = attributes.get('rxOversizePkts')
                data_dict['rxPkts1024to1518Octets'] = attributes.get('rxPkts1024to1518Octets')
                data_dict['rxPkts512to1023Octets'] = attributes.get('rxPkts512to1023Octets')
                data_dict['rxPkts256to511Octets'] = attributes.get('rxPkts256to511Octets')
                data_dict['rxPkts128to255Octets'] = attributes.get('rxPkts128to255Octets')
                data_dict['rxPkts65to127Octets'] = attributes.get('rxPkts65to127Octets')
                data_dict['rxPkts64Octets'] = attributes.get('rxPkts64Octets')
                data_dict['txPkts1024to1518Octets'] = attributes.get('txPkts1024to1518Octets')
                data_dict['txPkts512to1023Octets'] = attributes.get('txPkts512to1023Octets')
                data_dict['txPkts256to511Octets'] = attributes.get('txPkts256to511Octets')
                data_dict['txPkts128to255Octets'] = attributes.get('txPkts128to255Octets')
                data_dict['txPkts65to127Octets'] = attributes.get('txPkts65to127Octets')
                data_dict['txPkts64Octets'] = attributes.get('txPkts64Octets')

def parse_rmonIfHCIn(imdata_list, per_switch_stats_dict, mo):
    """Extract stats for the interfaces"""
    intf_dict = per_switch_stats_dict['intf']
    for imdata in imdata_list:
        for mo_name, attr in imdata.items():
            for attribute, attributes in attr.items():
                if 'dn' not in attributes:
                    logger.error('dn not found %s:%s',
                            mo, json.dumps(imdata_list, indent=2))
                    continue
                dn = attributes.get('dn')
                if 'mgmt' in dn or 'lo' in dn or 'svi' in dn or '.' in dn:
                    continue
                interface = dn[dn.find('[') + 1 : dn.find(']')]
                '''
                # This isn't needed because Grafana latest releases supports
                # sorting varibale values using Natural (asc) order. But keep
                # code just in case
                # make single digit numbers to two digits for sorting in GUI
                interface_list = interface.split('/')
                if len(interface_list) > 1:
                    port_id = interface_list[-1]
                    if len(port_id) == 1:
                        port_id = '0' + port_id
                        interface = '/'.join(interface_list[0:-1]) + '/' + port_id
                '''

                if interface not in intf_dict:
                    intf_dict[interface] = {}
                per_intf_dict = intf_dict[interface]

                if 'data' not in per_intf_dict:
                    per_intf_dict['data'] = {}
                data_dict = per_intf_dict['data']
                data_dict['rx_broadcast_pkts'] = attributes.get('broadcastPkts')
                data_dict['rx_multicast_pkts'] = attributes.get('multicastPkts')
                data_dict['rx_ucast_pkts'] = attributes.get('ucastPkts')
                data_dict['rx_bytes'] = attributes.get('octets')
                # modTs seems to be the same for rx and tx. Just use once
                per_intf_dict['meta']['modTs'] = attributes.get('modTs')

def parse_rmonIfHCOut(imdata_list, per_switch_stats_dict, mo):
    """Extract stats for the interfaces"""
    intf_dict = per_switch_stats_dict['intf']
    for imdata in imdata_list:
        for mo_name, attr in imdata.items():
            for attribute, attributes in attr.items():
                if 'dn' not in attributes:
                    logger.error('dn not found %s:%s',
                            mo, json.dumps(imdata_list, indent=2))
                    continue
                dn = attributes.get('dn')
                if 'mgmt' in dn or 'lo' in dn or 'svi' in dn or '.' in dn:
                    continue
                interface = dn[dn.find('[') + 1 : dn.find(']')]
                '''
                # This isn't needed because Grafana latest releases supports
                # sorting varibale values using Natural (asc) order. But keep
                # code just in case
                # make single digit numbers to two digits for sorting in GUI
                interface_list = interface.split('/')
                if len(interface_list) > 1:
                    port_id = interface_list[-1]
                    if len(port_id) == 1:
                        port_id = '0' + port_id
                        interface = '/'.join(interface_list[0:-1]) + '/' + port_id
                '''

                if interface not in intf_dict:
                    intf_dict[interface] = {}
                per_intf_dict = intf_dict[interface]

                if 'data' not in per_intf_dict:
                    per_intf_dict['data'] = {}
                data_dict = per_intf_dict['data']
                data_dict['tx_broadcast_pkts'] = attributes.get('broadcastPkts')
                data_dict['tx_multicast_pkts'] = attributes.get('multicastPkts')
                data_dict['tx_ucast_pkts'] = attributes.get('ucastPkts')
                data_dict['tx_bytes'] = attributes.get('octets')
                # modTs seems to be the same for rx and tx. Just use once
                #per_intf_dict['meta']['modTs'] = attributes.get('modTs')

def parse_ipqosQueuingStats(imdata_list, per_switch_stats_dict, mo):
    """Extract queue stats for the interfaces"""
    intf_dict = per_switch_stats_dict['intf']
    for imdata in imdata_list:
        for mo_name, attr in imdata.items():
            for attribute, attributes in attr.items():
                if 'dn' not in attributes:
                    logger.error('dn not found %s:%s',
                            mo, json.dumps(imdata_list, indent=2))
                    continue
                dn = attributes.get('dn')
                if 'mgmt' in dn or 'lo' in dn or 'svi' in dn or '.' in dn:
                    continue
                interface = dn[dn.find('[') + 1 : dn.find(']')]
                '''
                # This isn't needed because Grafana latest releases supports
                # sorting varibale values using Natural (asc) order. But keep
                # code just in case
                # make single digit numbers to two digits for sorting in GUI
                interface_list = interface.split('/')
                if len(interface_list) > 1:
                    port_id = interface_list[-1]
                    if len(port_id) == 1:
                        port_id = '0' + port_id
                        interface = '/'.join(interface_list[0:-1]) + '/' + port_id
                '''

                if interface not in intf_dict:
                    intf_dict[interface] = {}
                per_intf_dict = intf_dict[interface]

                if 'out_queue' not in per_intf_dict:
                    per_intf_dict['out_queue'] = {}
                out_queue_dict = per_intf_dict['out_queue']

                if 'cmapName' not in attributes:
                    logger.error('cmapName not found %s:%s',
                            mo, json.dumps(imdata_list, indent=2))
                    continue
                queue_name = attributes.get('cmapName')
                if queue_name not in out_queue_dict:
                    out_queue_dict[queue_name] = {}
                per_out_queue_dict = out_queue_dict[queue_name]

                per_out_queue_dict['tx_bytes'] = attributes.get('txBytes')
                per_out_queue_dict['tx_pkts'] = attributes.get('txPackets')
                per_out_queue_dict['drop_bytes'] = attributes.get('dropBytes')
                per_out_queue_dict['drop_pkts'] = attributes.get('dropPackets')
                per_out_queue_dict['rx_pause'] = attributes.get('pfcRxPpp')
                per_out_queue_dict['tx_pause'] = attributes.get('pfcTxPpp')
                per_out_queue_dict['rand_drop_bytes'] = attributes.get('randDropBytes')
                per_out_queue_dict['rand_drop_pkts'] = attributes.get('randDropPackets')
                per_out_queue_dict['ecn_marked_pkts'] = attributes.get('randEcnMarkedPackets')
                per_out_queue_dict['q_depth'] = attributes.get('ucCurrQueueDepth')
                per_out_queue_dict['modTs'] = attributes.get('modTs')

def parse_lldpAdjEp(imdata_list, per_switch_stats_dict, mo):
    """Extract peer details from LLDP"""
    intf_dict = per_switch_stats_dict['intf']
    for imdata in imdata_list:
        for mo_name, attr in imdata.items():
            for attribute, attributes in attr.items():
                if 'dn' not in attributes:
                    logger.error('dn not found %s:%s',
                            mo, json.dumps(imdata_list, indent=2))
                    continue
                dn = attributes.get('dn')
                if 'mgmt' in dn or 'lo' in dn or 'svi' in dn or '.' in dn:
                    continue
                interface = dn[dn.find('[') + 1 : dn.find(']')]
                '''
                # This isn't needed because Grafana latest releases supports
                # sorting varibale values using Natural (asc) order. But keep
                # code just in case
                # make single digit numbers to two digits for sorting in GUI
                interface_list = interface.split('/')
                if len(interface_list) > 1:
                    port_id = interface_list[-1]
                    if len(port_id) == 1:
                        port_id = '0' + port_id
                        interface = '/'.join(interface_list[0:-1]) + '/' + port_id
                '''

                if interface not in intf_dict:
                    intf_dict[interface] = {}
                per_intf_dict = intf_dict[interface]

                if 'meta' not in per_intf_dict:
                    per_intf_dict['meta'] = {}
                meta_dict = per_intf_dict['meta']

                encap = attributes.get('enCap')
                sysdesc = attributes.get('sysDesc')
                # When docker is installed, Ubuntu's encap becomes router(R)
                # instead of station(S). So check for Linux in sysDesc
                if 'tatio' in encap or \
                        re.search('Linux', sysdesc, re.IGNORECASE):
                    meta_dict['peer_type'] = 'host'
                    # portDesc has name in portDesc format, portIdV has mac
                    # portDesc is "Interface  28 as enp154s0d22" by lldpad
                    # portDesc can be 'Interface  18 as enp77s0d8' or 'fabric0'
                    portDesc = attributes.get('portDesc')
                    # find enp, ens, fab, etc.
                    portDesc = ''.join(re.findall("fab\w+|en\w+", portDesc))
                    meta_dict['peer_intf'] = portDesc
                    meta_dict['peer'] = attributes.get('mgmtIp')
                    meta_dict['peer_name'] = attributes.get('sysName')
                elif 'ridg' in encap or 'oute' in encap:
                    # bridge or router
                    meta_dict['peer_type'] = 'switch'
                    # portIdV comes in 'Ethernet1/1' format
                    portidv = attributes.get('portIdV')
                    portidv1 = portidv.replace('Ethernet', 'eth')
                    meta_dict['peer_intf'] = portidv1
                    meta_dict['peer'] = attributes.get('mgmtIp')
                    meta_dict['peer_name'] = attributes.get('sysName')
                else:
                    meta_dict['peer_type'] = 'other'
                    # don't fill peer, peer_name, and peer_intf when peer_type is other

def parse_sysmgrShowVersion(imdata_list, per_switch_stats_dict, mo):
    """Extract system details"""
    for imdata in imdata_list:
        attr = imdata[mo]
        if 'attributes' not in attr:
            logger.error('attributes not found in response for %s:%s',
                         mo, json.dumps(imdata_list, indent=2))
            continue
        attributes = attr['attributes']
        per_switch_stats_dict['sys_ver'] = attributes.get('nxosVersion')

        ker_uptime_str = attributes.get('kernelUptime')
        day_str = ''.join(re.findall(r'(\d+)[ ]{1,}day', ker_uptime_str))
        days = int(get_float_from_string(day_str))
        hr_str = ''.join(re.findall(r'(\d+)[ ]{1,}hour', ker_uptime_str))
        hrs = int(get_float_from_string(hr_str))
        min_str = ''.join(re.findall(r'(\d+)[ ]{1,}min', ker_uptime_str))
        mins = int(get_float_from_string(min_str))
        sec_str = ''.join(re.findall(r'(\d+)[ ]{1,}sec', ker_uptime_str))
        secs = int(get_float_from_string(sec_str))
        uptime_secs = secs + \
                      mins * SECONDS_IN_MINUTE + \
                      hrs * MINUTES_IN_HOUR * SECONDS_IN_MINUTE + \
                      days * HOURS_IN_DAY  * MINUTES_IN_HOUR * SECONDS_IN_MINUTE

        per_switch_stats_dict['kernel_uptime'] = uptime_secs

def parse_pieCpuUsage(imdata_list, per_switch_stats_dict, mo):
    """Extract CPU usage"""
    for imdata in imdata_list:
        attr = imdata[mo]
        if 'attributes' not in attr:
            logger.error('attributes not found in response for %s:%s',
                         mo, json.dumps(imdata_list, indent=2))
            continue
        attributes = attr['attributes']
        per_switch_stats_dict['cpu_user'] = attributes.get('userPercent')
        per_switch_stats_dict['cpu_kernel'] = attributes.get('kernelPercent')

def parse_nwVdc(imdata_list, per_switch_stats_dict, mo):
    """Extract switchname"""
    for imdata in imdata_list:
        attr = imdata[mo]
        if 'attributes' not in attr:
            logger.error('attributes not found in response for %s:%s',
                         mo, json.dumps(imdata_list, indent=2))
            continue
        attributes = attr['attributes']
        per_switch_stats_dict['switchname'] = attributes.get('name')

def parse_eqptCh(imdata_list, per_switch_stats_dict, mo):
    """Extract switch model"""
    for imdata in imdata_list:
        attr = imdata[mo]
        if 'attributes' not in attr:
            logger.error('attributes not found in response for %s:%s',
                         mo, json.dumps(imdata_list, indent=2))
            continue
        attributes = attr['attributes']
        per_switch_stats_dict['model'] = attributes.get('model')

def parse_pieMemoryUsage(imdata_list, per_switch_stats_dict, mo):
    """Extract Memory usage"""
    for imdata in imdata_list:
        attr = imdata[mo]
        if 'attributes' not in attr:
            logger.error('attributes not found in response for %s:%s',
                         mo, json.dumps(imdata_list, indent=2))
            continue
        attributes = attr['attributes']
        per_switch_stats_dict['mem_total'] = attributes.get('memTotal')
        per_switch_stats_dict['mem_used'] = attributes.get('memUsed')

def parse_nxapi_common(json_data, mo):
    """Common tasks for all NX-API response handling"""
    if "error" in json_data:
        logger.error('Error in %s\n%s', mo, json_data)
        return None
    if "result" not in json_data:
        logger.error('result not found in %s\n%s', mo, json_data)
        return None
    if json_data['result'] is None:
        logger.warning('Null result in %s\n%s', mo, json_data)
        return None
    if "body" not in json_data['result']:
        logger.error('body not found in %s\n%s', mo, json_data)
        return None
    if "TABLE_module" not in json_data['result']['body']:
        logger.error('TABLE_module not found in %s\n%s', mo, json_data)
        return None
    if "ROW_module" not in json_data['result']['body']['TABLE_module']:
        logger.error('ROW_module not found in %s\n%s', mo, json_data)
        return None
    return json_data['result']['body']['TABLE_module']['ROW_module']

def parse_pfcqueuedetail(json_data, per_switch_stats_dict, mo):
    """Parser for show queuing pfc-queue details in json. This is a dirty
    parser, but still used today because DME has a bug of reporting 0.
    This function assumes that per_intf_dict is already built
    PFC watchdog stats
    """
    intf_dict = per_switch_stats_dict['intf']
    row_module = parse_nxapi_common(json_data, mo)
    if row_module is None:
        return

    if "TABLE_queuing_interface" not in row_module:
        logger.error('TABLE_queuing_interface not in %s\n%s', mo, json_data)
        return
    if "ROW_queuing_interface" not in row_module['TABLE_queuing_interface']:
        logger.error('ROW_queuing_interface not in %s\n%s', mo, json_data)
        return
    for row in row_module['TABLE_queuing_interface']['ROW_queuing_interface']:
        for k,v in row.items():
            if 'if_name_str' in k and 'Eth' in v:
                # non-greedy match (?) from Ethernet1/1/1 Interface PFC watchdo
                intf = ''.join(re.findall(r'(Eth.*?)[ ]', v, re.IGNORECASE))
                intf = intf.strip().replace('Ethernet', 'eth')
                per_intf_dict = intf_dict[intf]
                per_intf_dict['pfcwd'] = {}
                wd_dict = per_intf_dict['pfcwd']
            if 'TABLE_qosgrp_stats' in k:
                if 'ROW_qosgrp_stats' in v:
                    row_qos = v['ROW_qosgrp_stats']
                    if 'eq-qosgrp' in row_qos:
                        wd_dict['qosgrp'] = str(row_qos['eq-qosgrp'])
                    else:
                        logger.error('Not found eq-qosgrp for %s \n%s', intf, k)
                    if 'TABLE_qosgrp_stats_entry' in row_qos:
                        if 'ROW_qosgrp_stats_entry' in \
                                            row_qos['TABLE_qosgrp_stats_entry']:
                            r_qos_s = row_qos['TABLE_qosgrp_stats_entry'] \
                                             ['ROW_qosgrp_stats_entry']
                            for rs_dict in r_qos_s:
                                for key,val in rs_dict.items():
                                    if 'q-stat-type' in key:
                                        continue
                                    key_short = key.replace('q-', '')
                                    wd_dict[key_short] = val

def parse_burstdetect(json_data, per_switch_stats_dict, mo):
    """Parser for show queuing burst-detect detail in json.
    This function assumes that per_intf_dict is already built
    Burst detect stats
    """
    intf_dict = per_switch_stats_dict['intf']
    row_module = parse_nxapi_common(json_data, mo)
    if row_module is None:
        return

    if "TABLE_instance" not in row_module:
        logger.error('TABLE_instance not in %s\n%s', mo, json_data)
        return
    if "ROW_instance" not in row_module['TABLE_instance']:
        logger.error('ROW_instance not in %s\n%s', mo, json_data)
        return
    for row_dict in row_module['TABLE_instance']['ROW_instance']:
        per_intf_dict, b_list = None, []
        if 'if-str' not in row_dict:
            logger.error('if-str not in %s', row_dict)
            continue
        intf = row_dict['if-str'].lower()
        per_intf_dict = intf_dict[intf]
        if 'burst' not in per_intf_dict:
            per_intf_dict['burst'] = []
        b_list = per_intf_dict['burst']
        b_dict = {}
        if 'queue' in row_dict:
            b_dict['q'] = row_dict['queue']
        if 'threshold' in row_dict:
            b_dict['start-depth'] = str(row_dict['threshold'])
        if 'end-depth' in row_dict:
            b_dict['end-depth'] = str(row_dict['end-depth'])
        if 'peak' in row_dict:
            b_dict['peak'] = str(row_dict['peak'])
        if 'peak-time' in row_dict:
            b_dict['peak-time'] = row_dict['peak-time']
        if 'duration' in row_dict:
            if 'us' in row_dict['duration']:
                # parse "206.46 us"
                dur_us = (row_dict['duration']).replace('us', '').strip()
            elif 'ms' in row_dict['duration']:
                # parse "1.47 ms"
                dur_ms = (row_dict['duration']).replace('ms', '').strip()
                dur_us = str(int(float(dur_ms) * 1000))
            elif 's' in row_dict['duration']:
                # Must be after us and ms checks
                dur_s = (row_dict['duration']).replace('s', '').strip()
                dur_us = str(int(float(dur_s) * 1000000))
            else:
                logger.error('Unknown duration unit %s', row_dict)
                continue
            b_dict['duration'] = dur_us
        b_list.append(b_dict)

def parse_bufferpktstats(cmd_result, per_switch_stats_dict, mo):
    """Parser for show hardware internal buffer info pkt-stats in json.
    This function assumes that per_intf_dict is already built
    This information is unavailable via DME. Using NX-API is fine, but it
    creates a new vsh on the switch resulting in the following message:
    %VSHD-5-VSHD_SYSLOG_CONFIG_I: Configured from vty by admin on <ip>@nginx.18400
    This message floods the system logs and misleads the user into thinking that
    something was changed on the switch even though this is just a show command
    Therefore, use password-less ssh to get the output of a command from the
    switch, which works as fast as NX-API and the returned data is slightly
    easier to parse because NX-API headers are not added
    The user running this file must add keys to the switch
    for password-less ssh, must have necessary permissions to run the
    commands on the local host, write access to the log directors, and
    must be able to run any daemon, such as telegraf, that invokes this file
    """

    json_data = json.loads(cmd_result)

    if user_args.get('raw_dump'):
        current_log_level = logger.level
        logger.setLevel(logging.DEBUG)
        logger.debug('Printing raw Response\n%s', json.dumps(json_data, indent=2))
        logger.debug('Printing raw dump - DONE')
        logger.setLevel(current_log_level)

    intf_dict = per_switch_stats_dict['intf']
    if "TABLE_module" not in json_data:
        logger.error('TABLE_module not found in %s\n%s', mo, json_data)
        return
    if "ROW_module" not in json_data['TABLE_module']:
        logger.error('ROW_module not found in %s\n%s', mo, json_data)
        return
    #row_module = parse_nxapi_common(json_data, mo)
    row_module = json_data['TABLE_module']['ROW_module']
    if row_module is None:
        return

    if "TABLE_instance" not in row_module:
        logger.error('TABLE_instance not in %s\n%s', mo, json_data)
        return
    if "ROW_instance" not in row_module['TABLE_instance']:
        logger.error('ROW_instance not in %s\n%s', mo, json_data)
        return

    if 'buffer_usage' not in per_switch_stats_dict:
        per_switch_stats_dict['buffer_usage'] = {}
    buffer_dict = per_switch_stats_dict['buffer_usage']

    for row_dict in row_module['TABLE_instance']['ROW_instance']:
        if 'instance' not in row_dict:
            logger.error('Instance not found for buffer pkt stats %s\n%s' \
                         , mo, json_data)
            continue
        buffer_dict[row_dict['instance']] = {}
        if 'max_cell_usage_drop_pg' in row_dict and \
                'N' not in str(row_dict['max_cell_usage_drop_pg']):
            buffer_dict[row_dict['instance']]['peak_cell_drop_pg'] = \
                                            row_dict['max_cell_usage_drop_pg']
        if 'max_cell_usage_no_drop_pg' in row_dict and \
                'N' not in str(row_dict['max_cell_usage_no_drop_pg']):
            buffer_dict[row_dict['instance']]['peak_cell_no_drop'] = \
                                            row_dict['max_cell_usage_no_drop_pg']
        if 'switch_cell_count_drop_pg' in row_dict and \
                'N' not in str(row_dict['switch_cell_count_drop_pg']):
            buffer_dict[row_dict['instance']]['cell_count_drop_pg'] = \
                                            row_dict['switch_cell_count_drop_pg']
        if 'switch_cell_count_no_drop_pg' in row_dict and \
                'N' not in str(row_dict['switch_cell_count_no_drop_pg']):
            buffer_dict[row_dict['instance']]['cell_count_no_drop_pg'] = \
                                            row_dict['switch_cell_count_no_drop_pg']

def parse_nothing(cmd_result, per_switch_stats_dict, mo):
    """parse nothing"""
    return

#def parse_nxapi(imdata_list, per_switch_stats_dict, mo):
#    for i in range(len(imdata_list)):
#        n9k_nxapi_list[i](imdata_list[i], per_switch_stats_dict, mo.split(',')[i])

###############################################################################
# END: Parser functions
###############################################################################

###############################################################################
# BEGIN: Connection and Collector functions
###############################################################################

def get_switches():
    """
    Parse the input-file
    The format of the file is expected to carry:
    IP_Address,username,password,protocol,port,verify_ssl,timeout,description
    Only one entry is expected per line and only one entry per file.
    Line with prefix # is ignored
    Location is specified between []
    Initialize stats_dict
    """
    global switch_dict
    global stats_dict
    global response_time_dict
    location = ''
    input_file = user_args['input_file']
    with open(input_file, 'r') as f:
        for line in f:
            if not line.startswith('#'):
                line = line.strip()
                if line.startswith('['):
                    if not line.endswith(']'):
                        logger.error('Input file %s format error. Line starts' \
                        ' with [ but does not end with ]: %s', \
                        input_file, line)
                        return
                    line = line.replace('[', '')
                    line = line.replace(']', '')
                    line = line.strip()
                    location = line
                    continue

                if location == '':
                    logger.error('Location is mandatory in input file')
                    continue

                switch = line.split(',')
                if len(switch) < 7:
                    logger.warning('Line not in correct input format:'
                    'IP_Address,username,password,protocol,port,verify_ssl'
                    ',timeout')
                    continue
                switch_dict[switch[0]] = [switch[1], switch[2], switch[3],
                                          switch[4], switch[5], switch[6]]
                switch_dscr = switch[7] if len(switch) == 8 else ''
                logger.info('Added %s (%s) to switch dict, location:%s',
                            switch[0], switch_dscr, location)
                stats_dict[switch[0]] = {}
                stats_dict[switch[0]]['location'] = location
                stats_dict[switch[0]]['intf'] = {}
                stats_dict[switch[0]]['modules'] = {}
                stats_dict[switch[0]]['type'] = 'nexus'

                response_time_dict[switch[0]] = []

    if not switch_dict:
        logger.error('Nothing to monitor. Check input file.')

def aaa_login(username, password, switch_ip, verify_ssl, timeout):
    """
    Get auth token from N9K
    TODO: Pickle auth key instead of login and logout every time
    """

    payload = {
        'aaaUser' : {
            'attributes' : {
                'name' : username,
                'pwd' : password
                }
            }
        }

    url = "https://" + switch_ip + "/api/aaaLogin.json"
    auth_cookie = {}

    if verify_ssl == 'False':
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logger.debug('verify_ssl is set to False. Ignoring InsecureRequestWarning')
        verify = False
    else:
        logger.debug('verify_ssl is set to True.')
        verify = True

    response = requests.request("POST", url, data=json.dumps(payload),
                                verify=verify, proxies=proxies, timeout=timeout)

    if not response.ok:
        logger.error('NXAPI error from %s:%s:%s', switch_ip, \
            response.status_code, \
            requests.status_codes._codes[response.status_code])
        return None

    response_json = response.json()

    if user_args.get('raw_dump'):
        current_log_level = logger.level
        logger.setLevel(logging.DEBUG)
        logger.debug('Printing raw Response\n%s', json.dumps(response_json, indent=2))
        logger.debug('Printing raw dump - DONE')
        logger.setLevel(current_log_level)

    if 'imdata' not in response_json:
        logger.error('imdata not found in NXAPI response from %s:%s',
                switch_ip, json.dumps(response_json, indent=2))
        return None

    if not response_json['imdata']:
        logger.error('Empty imdata in NXAPI response from %s:%s',
                switch_ip, json.dumps(response_json, indent=2))
        return None

    if 'aaaLogin' not in response_json['imdata'][0]:
        logger.error('aaaLogin not found in NXAPI response from %s:%s',
                switch_ip, json.dumps(response_json, indent=2))
        return None

    if 'attributes' not in response_json['imdata'][0]['aaaLogin']:
        logger.error('attributes not found in NXAPI response from %s:%s',
                switch_ip, json.dumps(response_json, indent=2))
        return None

    if 'token' not in response_json['imdata'][0]['aaaLogin']['attributes']:
        logger.error('token not found in NXAPI response from %s:%s',
                switch_ip, json.dumps(response_json, indent=2))
        return None

    token = str(response_json['imdata'][0]['aaaLogin']['attributes']['token'])
    auth_cookie = {"APIC-cookie" : token}

    return auth_cookie

def aaa_logout(username, switch_ip, auth_cookie, verify_ssl, timeout):
    """
    Logout from N9K
    """

    payload = {
        'aaaUser' : {
            'attributes' : {
                'name' : username
            }
        }
    }

    url = "https://" + switch_ip + "/api/aaaLogout.json"

    if verify_ssl == 'False':
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logger.debug('verify_ssl is set to False. Ignoring InsecureRequestWarning')
        verify = False
    else:
        logger.debug('verify_ssl is set to True.')
        verify = True

    response = requests.request("POST", url, data=json.dumps(payload),
                                cookies=auth_cookie, verify=verify, \
                                proxies=proxies, timeout=timeout)

    if not response.ok:
        logger.error('NXAPI error from %s:%s:%s', switch_ip, \
            response.status_code, \
            requests.status_codes._codes[response.status_code])
        return

    logger.info('Successful logout from %s', switch_ip)

    if user_args.get('raw_dump'):
        response = response.json()
        current_log_level = logger.level
        logger.setLevel(logging.DEBUG)
        logger.debug('Printing raw Response\n%s', json.dumps(response, indent=2))
        logger.debug('Printing raw dump - DONE')
        logger.setLevel(current_log_level)

def dme_connect(switch_ip, auth_cookie, endpoint, payload, verify_ssl, timeout):
    """ Connect to a Cisco N9K switch and get the response
    of DME object end point"""

    url = "https://" + switch_ip + endpoint
    # endpoint's format: /api/mo/sys/sysmgrShowVersion.json
    mo = endpoint.split('/')[-1].split('.')[0]

    logger.debug('Requesting URL:%s, Payload:%s', url, payload)

    if verify_ssl == 'False':
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logger.debug('verify_ssl is set to False. Ignoring InsecureRequestWarning')
        verify = False
    else:
        logger.debug('verify_ssl is set to True.')
        verify = True

    response = requests.request("GET", url, data=json.dumps(payload),
                                cookies=auth_cookie, verify=verify,
                                proxies=proxies, timeout=timeout)

    if not response.ok:
        logger.error('DME connect error from %s:%s', switch_ip, \
            response.status_code)
        return None

    response_json = response.json()

    if user_args.get('raw_dump'):
        current_log_level = logger.level
        logger.setLevel(logging.DEBUG)
        logger.debug('Printing raw Response\n%s', json.dumps(response_json, indent=2))
        logger.debug('Printing raw dump - DONE')
        logger.setLevel(current_log_level)

    if 'imdata' not in response_json:
        logger.error('imdata not found in NXAPI response from %s:%s',
                switch_ip, json.dumps(response_json, indent=2))
        return None

    return response_json['imdata']

def nxapi_connect(switch_ip, switchuser, switchpassword, cmd, verify_ssl, \
                  timeout):
    """ Connect to a Cisco N9K switch and get the response of show command
    using NXAPI"""

    cmd_list = ['ssh', '-l', switchuser, switch_ip, cmd]
    result = run_cmd(cmd_list)
    if result is None:
        logger.error('Error: %s', cmd)
        return None
    return result

    '''
    This code using HTTP/NX-API to run show command on the switch. But not
    using it because it generates a message on the switch. Instead, use
    password-less SSH
    url = 'http://' + switch_ip + '/ins'
    myheaders={"content-type":"application/json-rpc"}
    cmd_list = cmd.split(',')

    payload_list = []
    cmd_id = 1
    for c in cmd_list:
        payload = dict(jsonrpc = "2.0",
                       method = "cli",
                       params = dict(cmd = c, version = 1),
                       id = cmd_id)
        payload_list.append(payload)
        cmd_id = cmd_id + 1

    logger.debug('Requesting URL:%s, Payload:%s', url, payload_list)
    if verify_ssl == 'False':
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logger.debug('verify_ssl is set to False. Ignoring InsecureRequestWarning')
        verify = False
    else:
        logger.debug('verify_ssl is set to True.')
        verify = True

    response = requests.post(url,data=json.dumps(payload_list), \
                    headers=myheaders, auth=(switchuser,switchpassword), \
                    proxies=proxies, timeout=timeout)

    if not response.ok:
        logger.error('NXAPI error from %s:%s', switch_ip, \
            response.status_code)
        return None

    response_json = response.json()

    if user_args.get('raw_dump'):
        current_log_level = logger.level
        logger.setLevel(logging.DEBUG)
        logger.debug('Printing raw Response\n%s', json.dumps(response_json, indent=2))
        logger.debug('Printing raw dump - DONE')
        logger.setLevel(current_log_level)

    return response_json
    '''

def connect_and_pull_stats(switch_ip):
    """
    Wrapper to connect to switches and pull stats
    This function is called once per switch
    """

    global switch_dict
    global stats_dict
    global response_time_dict
    global n9k_mo_dict

    switchuser = switch_dict[switch_ip][0]
    switchpassword = switch_dict[switch_ip][1]
    protocol = switch_dict[switch_ip][2]
    port = switch_dict[switch_ip][3]
    verify_ssl = switch_dict[switch_ip][4]
    timeout = int(switch_dict[switch_ip][5])
    idx = 0
    payload = None
    nxapi_ep = False

    for endpoint, parser in n9k_mo_dict.items():
        nxapi_start = time.time()
        mo = endpoint.split('/')[-1].split('.')[0]
        if 'aaaLogin' in endpoint:
            logger.info('Sending login request to %s', switch_ip)
            auth_cookie = aaa_login(switchuser, switchpassword,
                                    switch_ip, verify_ssl, timeout)
            if auth_cookie is None:
                logger.error('Unsuccessful auth from %s', switch_ip)
                return
            logger.info('Successful auth from %s', switch_ip)
            nxapi_rsp = time.time()
            nxapi_parse = time.time()
            response_time = dict(nxapi_start = nxapi_start,
                             nxapi_rsp = nxapi_rsp,
                             nxapi_parse = nxapi_parse)
            response_time_dict[switch_ip].insert(idx, response_time)
            idx = idx + 1
            continue
        if 'aaaLogout' in endpoint:
            logger.info('Sending logout request to %s', switch_ip)
            aaa_logout(switchuser, switch_ip, auth_cookie, verify_ssl, timeout)
            nxapi_rsp = time.time()
            nxapi_parse = time.time()
            response_time = dict(nxapi_start = nxapi_start,
                                 nxapi_rsp = nxapi_rsp,
                                 nxapi_parse = nxapi_parse)
            response_time_dict[switch_ip].insert(idx, response_time)
            idx = idx + 1
            # In n9k_mo_dict, all DME MOs are listed first and aaaLogout is the
            # last. After this, start SSH/NXAPI calls of show commands
            # order of DME and SSH/NXAPI calls must not be changed or mixed
            nxapi_ep = True
            continue

        logger.info('Run %s on %s', mo, switch_ip)

        if nxapi_ep:
            imdata_list = nxapi_connect(switch_ip, switchuser, switchpassword, \
                                        endpoint, verify_ssl, timeout)
        else:
            imdata_list = dme_connect(switch_ip, auth_cookie, endpoint, \
                                      payload, verify_ssl, timeout)

        nxapi_rsp = time.time()

        if imdata_list:
            logger.info('Received. Now parse stats for %s for %s', switch_ip, mo)

            parser(imdata_list, stats_dict[switch_ip], mo)

            logger.info('Done parsing stats for %s for %s', switch_ip, mo)
            nxapi_parse = time.time()
            response_time = dict(nxapi_start = nxapi_start,
                                 nxapi_rsp = nxapi_rsp,
                                 nxapi_parse = nxapi_parse)
            response_time_dict[switch_ip].insert(idx, response_time)
        idx = idx + 1

def get_switch_stats():
    """
    Connect to switches and pull stats

    """

    global switch_dict

    if len(switch_dict) == 0:
        logger.error('Nothing to connect')
        return

    logger.debug('Connect and pull stats: %s', switch_dict)

    nxapi_cmd = False
    if user_args['burst']:
        n9k_mo_dict["show queuing burst-detect detail"] = parse_burstdetect
        nxapi_cmd = True
    if user_args['pfcwd']:
        n9k_mo_dict["show queuing pfc-queue detail"] = parse_pfcqueuedetail
        nxapi_cmd = True
    if user_args['bufferstats']:
        n9k_mo_dict['show hardware internal buffer info pkt-stats | json'] = \
                    parse_bufferpktstats
        n9k_mo_dict['clear counters buffers'] = parse_nothing
        nxapi_cmd = True
#    if nxapi_cmd:
#        n9k_mo_dict['show clock'] = parse_nothing

    for switch_ip in switch_dict:
        try:
            connect_and_pull_stats(switch_ip)
        except Exception as excp:
            logger.exception('Exception: %s', excp)

###############################################################################
# END: Connection and Collector functions
###############################################################################

# Dictionary of N9K managed objects (MO) and their parsing functions
# First list DME objects in which aaaLogin must be the first and
# aaaLogout must be the last. Then list NXAPI commands
n9k_mo_dict = {
    "/api/aaaLogin.json": aaa_login,
    "/api/node/class/sysmgrShowVersion.json": parse_sysmgrShowVersion,
    "/api/node/class/nwVdc.json": parse_nwVdc,
    "/api/node/class/eqptCh.json": parse_eqptCh,
    "/api/node/class/pieCpuUsage.json": parse_pieCpuUsage,
    "/api/node/class/pieMemoryUsage.json": parse_pieMemoryUsage,
    "/api/node/mo/sys/intf.json?query-target=children": parse_intf,
    "/api/node/class/ethpmPhysIf.json": parse_ethpmPhysIf,
    "/api/node/class/rmonEtherStats.json": parse_rmonEtherStats,
    "/api/node/class/rmonIfHCIn.json": parse_rmonIfHCIn,
    "/api/node/class/rmonIfHCOut.json": parse_rmonIfHCOut,
    "/api/node/class/ipqosQueuingStats.json": parse_ipqosQueuingStats,
    "/api/node/class/lldpAdjEp.json": parse_lldpAdjEp,
    "/api/aaaLogout.json": aaa_logout,
}

def main(argv):
    """The beginning of the beginning"""

    # Initial tasks
    start_time = time.time()
    if not pre_checks_passed(argv):
        return
    parse_cmdline_arguments()
    setup_logging()

    logger.warning('---- START (version %s) (last update %s) ----', \
                               __version__, __updated__)

    # Read input file to get the switches
    get_switches()
    input_read_time = time.time()

    # Connect and pull stats
    try:
        get_switch_stats()
    except Exception as excp:
        logger.error('Exception with get_switch_stats:%s', str(excp))
    connect_time = time.time()

    # Print the stats as per the desired output format
    try:
        for switch_ip, switch_details in switch_dict.items():
            stats_dict[switch_ip]['response_time'] = \
                        round((connect_time - input_read_time), 3)
            print_output(switch_ip, stats_dict[switch_ip])
    except Exception as excp:
        logger.exception('Exception with print_output:%s', (str)(excp))

    output_time = time.time()

    # Final tasks

    # Print response time - total and per command set
    time_output = ''
    idx = 0
    for switch_ip, rsp_list in response_time_dict.items():
        time_output = time_output + '\n' \
            '    +--------------------------------------------------------------+\n' \
            '    |     Response time from - {:<15}                     |\n' \
            '    |--------------------------------------------------------------|'. \
            format(switch_ip)
        while idx < len(rsp_list):
            if rsp_list[idx]['nxapi_rsp'] > rsp_list[idx]['nxapi_start']:
                nxapi_rsp_time = str(round((rsp_list[idx]['nxapi_rsp'] - \
                                              rsp_list[idx]['nxapi_start']), 2))
            else:
                nxapi_rsp_time = 'N/A'

            if rsp_list[idx]['nxapi_parse'] > rsp_list[idx]['nxapi_rsp']:
                parse_time = str(round((rsp_list[idx]['nxapi_parse'] - \
                                              rsp_list[idx]['nxapi_rsp']), 2))
            else:
                parse_time = 'N/A'

            if rsp_list[idx]['nxapi_parse'] > rsp_list[idx]['nxapi_start']:
                total_time = str(round((rsp_list[idx]['nxapi_parse'] - \
                                              rsp_list[idx]['nxapi_start']), 2))
            else:
                total_time = 'N/A'

            time_output = time_output + '\n' + \
                    '    | Command set:{0: <2}'.format(idx + 1)

            cmd_str = (list(n9k_mo_dict)[idx]).split('/')[-1].split('.')[0]

            ml_cmd_str = ' : {0: <44}|'.format(' ')
            if len(cmd_str.split(',')) > 1:
                for c in cmd_str.split(','):
                    ml_cmd_str = ml_cmd_str + '\n    |      {0: <56}|'.format(c.strip())
                time_output = time_output + ml_cmd_str
            else:
                time_output = time_output + ' : {0: <44}|'.format(cmd_str)
            '''
            time_output = time_output + '\n' + \
                    '    | Command set:{0:<2}  {0: <30}|'.\
                format(idx + 1, cmd_str)
            '''

            #time_output = time_output + cmd_str

            time_output = time_output + '\n' + \
            '    |--------------------------------------------------------------|\n'\
            '    | NXAPI Response:{:>8} s | Parsing:{:>8} s               |\n'\
            '    |--------------------------------------------------------------|'.\
            format(nxapi_rsp_time, parse_time)

            idx = idx + 1

    time_output = time_output + '\n' \
                   '    |--------------------------------------------------------------|\n'\
                   '    |            Time taken to complete                            |\n'\
                   '    |--------------------------------------------------------------|\n'\
                   '    |                               Input:{:7.3f} s                |\n'\
                   '    |       Connect, pull and parse stats:{:7.3f} s                |\n'\
                   '    |                              Output:{:7.3f} s                |\n'\
                   '    |------------------------------------------------------------- |\n'\
                   '    |                               Total:{:7.3f} s                |\n'\
                   '    +--------------------------------------------------------------+'.\
                   format((input_read_time - start_time),
                          (connect_time - input_read_time),
                          (output_time - connect_time),
                          (output_time - start_time))

    logger.setLevel(logging.INFO)
    logger.info('%s', time_output)
    # DONE: Print response time - total and per command set

    logger.warning('---------- END ----------')

if __name__ == '__main__':
    main(sys.argv)
