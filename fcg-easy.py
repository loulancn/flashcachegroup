#!/usr/bin/env python
import sys, os, commands, tempfile, argparse

def parse_args(cmdline):
    parser = argparse.ArgumentParser(description='This is a description of %(prog)s', epilog='This is a epilog of %(prog)s', prefix_chars='-+', fromfile_prefix_chars='@', formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    subparsers  = parser.add_subparsers(help='sub-command help')

    create_parser = subparsers.add_parser('create', help='fcg-easy create -h')
    create_parser.add_argument('-g', '--group', type=str)
    create_parser.add_argument('-d', '--disk', nargs='+', type=str)
    create_parser.add_argument('-c', '--cachedev', nargs='+', type=str)
    create_parser.add_argument('-y', '--yes', action='store_true', default=False)
    create_parser.set_defaults(func=main_create)

    delete_parser = subparsers.add_parser('delete', help='fcg-easy delete -h')
    delete_parser.add_argument('-g', '--group', type=str)
    delete_parser.add_argument('-y', '--yes', action='store_true', default=False)
    delete_parser.set_defaults(func=main_delete)

    rep_ssd_parser = subparsers.add_parser('rep-ssd', help='fcg-easy rep-ssd -h')
    rep_ssd_parser.add_argument('-g', '--group', type=str)
    rep_ssd_parser.add_argument('-c', '--cachedev', nargs='+', type=str)
    rep_ssd_parser.set_defaults(func=main_rep_ssd)

    args = parser.parse_args(cmdline)
    args.func(args)

def _ask_user():
    print 'Continue to execute? (yes/no):'
    while(True):
        userInput = raw_input()
        if userInput in ('y', 'Y', 'yes', 'Yes', 'YES'):
            return True
        elif userInput in ('n', 'N', 'no', 'No', 'NO'):
            return False
        else:
            print 'Please input yes or no...'
            continue

def _os_execute(cmd):
    ret, output = commands.getstatusoutput(cmd)
    if ret == '0' or ret == 0:
        return output
    else:
        raise Exception(output)

def _ask_to_execute(cmd):
    if _ask_user() == True:
        _os_execute(cmd)
    else:
        raise 'User Interrupted'

def _execute(cmd, isYes):
    if isYes:
        _os_execute(cmd)
    else:
        _ask_to_execute(cmd)

def _get_dev_sector_count(dev):
    # try /dev/block/xxx/size
    cmd = 'blockdev --getsz %s'%dev
    devSector = _os_execute(cmd)
    if type(devSector) != int:
        try:
            devSector = int(devSector)
        except:
            return 0
    return devSector

def _sectors2MB(sectors):
    return str(sectors*512/1024/1024) + 'M'

def _linear_map_table(devices):
    table = ''
    startSector = 0
    for device in devices:
        if not os.path.exists(device):
            raise Exception('Device %s does NOT exist...' % device)
        sector = _get_dev_sector_count(device)
        if sector <= 0:
            raise Exception('Device %s is EMPTY...' % device)
        table +=  '%d %d linear %s 0\n' % (startSector, sector, device)
        startSector += sector
    return table

def _write2tempfile(content):
    temp = tempfile.NamedTemporaryFile(delete=False)
    temp.write(content)
    temp.close()
    #print 'Write table to temporary file %s, content is:' % temp.name
    #print content
    return temp.name

def _create_table(name, table, isYes):
    tmpTableFile = _write2tempfile(table)
    cmd = 'dmsetup create %s %s' % (name, tmpTableFile)
    print 'Create table: %s' % cmd
    print 'Table content is:'
    print table,
    _execute(cmd, isYes)

def _delete_table(name, isYes):
    cmd = 'dmsetup remove %s' % name
    print 'Delete table: %s' % cmd
    _execute(cmd, isYes)

def _get_table(name):
    cmd = 'dmsetup table %s' % name
    try:
        table = _os_execute(cmd)
        return table
    except Exception, ErrMsg:
        print cmd + ': ',
        print ErrMsg
        return None

def _rename_table(oldName, newName):
    cmd = 'dmsetup rename %s %s' % (oldName, newName)
    try:
        _os_execute(cmd)
        return True
    except Exception, ErrMsg:
        print cmd + ': ', ErrMsg
        return False

def _reload_table(name, table):
    print 'Reload table %s' % name
    print 'New table content is: \n', table,
    #if _ask_user() == False:
    #    raise "User Interrupted"

    cmd = 'dmsetup suspend %s'%name
    try:
        _os_execute(cmd)
    except Exception, ErrMsg:
        print cmd + ': ',
        print ErrMsg
    tmpTableFile = _write2tempfile(table)
    cmd = 'dmsetup reload %s %s' % (name, tmpTableFile)
    try:
        _os_execute(cmd)
    except Exception, ErrMsg:
        print cmd + ': ',
        print ErrMsg
    cmd = 'dmsetup resume %s'%name
    try:
        _os_execute(cmd)
    except Exception, ErrMsg:
        print cmd + ': ',
        print ErrMsg

def _create_flashcache(cacheName, cacheDevice, groupDevice, isYes):
    cmd = 'flashcache_destroy -f %s' % cacheDevice
    try:
        _os_execute(cmd)
    except :
        pass

    cacheSize = _sectors2MB(_get_dev_sector_count(cacheDevice))
    cmd = 'flashcache_create -p back -b 4k -s %s %s %s %s' % (cacheSize, cacheName, cacheDevice, groupDevice)
    print 'Create flashcache: %s' % cmd
    _execute(cmd, isYes)

def _delete_flashcache(cacheName, cacheDevice, isYes):
    print 'Delete flashcache'
    ret = _delete_table(cacheName, isYes)
    if ret == False:
        return False
    cmd = 'flashcache_destroy -f %s' % cacheDevice
    print 'Execute command: %s' % cmd
    _execute(cmd, isYes)

def _get_cache_ssd_dev(cacheName):
        cmd = "dmsetup table %s|grep ssd|grep dev|awk '{print $3}'" % cacheName
        ssd_dev = _os_execute(cmd)[1:-2]
        return ssd_dev

def _get_device_name(device):
    name = device.split('/')[-1:][0]
    return name

def _cached_tables(devices, cacheGroupDevice):
    names = []
    tables = []
    startSector = 0
    for device in devices:
        name = 'cached-' + _get_device_name(device) 
        names.append(name)
        sector = _get_dev_sector_count(device)
        table = '0 %d linear %s %d\n' % (sector, cacheGroupDevice, startSector)
        tables.append(table)
        startSector += sector
    assert len(names) == len(tables), 'Something BAD happened when try to get cached tables...'
    return names, tables

def _get_devname_from_major_minor(majorMinor):
    return '/dev/' + os.readlink('/dev/block/%s' % majorMinor)[3:]

def _is_device_busy(device):
    cmd = 'fuser %s' % device
    try:
        output = _os_execute(cmd)
        if output == '':
            return False
        else:
            return True
    except Exception, e:
        return False

def _get_hdd_devices(groupName):
    groupTable = _get_table(groupName)
    if groupTable == None:
        print "Group %s dose NOT exist..." % groupName
        return
    hddDevices = []
    for line in groupTable.split('\n'):
        if line == '':
            continue
        line = line.split()
        while '' in line:
            line.remove('')
        if len(line) == 5:
            hddDevice = line[3]
            try:
                major, minor = [int(x) for x in hddDevice.split(':')]
                hddDevice = _get_devname_from_major_minor(hddDevice)
            except Exception, e:
                pass
            hddDevices.append(hddDevice)
    return hddDevices

def _get_cached_names(hddDevs):
    cachedNames = [ 'cached-' + _get_device_name(hdd) for hdd in hddDevs]
    return cachedNames

def main_create(args):
    if args.group == None or args.disk == None or args.cachedev == None:
        return
    create_group(args.group, args.disk, args.cachedev, args.yes)

def create_group(groupName, hddDevs, cacheDevs, isYes):
    #create linear device group
    groupTable = ''
    try:
        groupTable = _linear_map_table(hddDevs)
    except Exception, e:
        print e
        return

    cacheDevTable = ''
    try:
        cacheDevTable = _linear_map_table(cacheDevs)
    except Exception, e:
        print e
        return

    cacheDevName = 'cachedevices-%s' % groupName

    try:
        _create_table(groupName, groupTable, isYes)
    except Exception, e:
        print e
        return
    try:
        _create_table(cacheDevName, cacheDevTable, isYes)
    except Exception, e:
        print e
        print 'Try to roll back...'
        _delete_table(groupName, True)
        return

    #create flashcache
    groupDevice = '/dev/mapper/%s' % groupName
    cacheDevice = '/dev/mapper/%s' % cacheDevName
    cacheName = 'cachegroup-%s' % groupName
    try:
        _create_flashcache(cacheName, cacheDevice, groupDevice, isYes)
    except Exception, e:
        print e
        print 'Try to roll back...'
        _delete_table(groupName, True)
        _delete_table(cacheDevName, True)
        return

    #create cached devices
    cacheGroupDevice = '/dev/mapper/%s' % cacheName
    cachedNames, cachedTables = _cached_tables(hddDevs, cacheGroupDevice)
    for i in range(len(cachedNames)):
        try:
            _create_table(cachedNames[i], cachedTables[i], isYes)
        except Exception, e:
            print e
            print 'Try to roll back...'
            for j in range(i):
                _delete_table(cachedNames[j], True)
            _delete_flashcache(cacheName, cacheDevice, True)
            _delete_table(groupName, True)
            _delete_table(cacheDevName, True)
            return

def main_delete(args):
    if args.group == None:
        return
    delete_group(args.group, args.yes)

def delete_group(groupName, isYes):
    groupTable = _get_table(groupName)
    if groupTable == None:
        print "Group %s dose NOT exist..." % groupName
        return
    hddDevices = []
    hddNames = []
    cachedNames = []
    hddDevices = _get_hdd_devices(groupName)
    cachedNames = _get_cached_names(hddDevices)

    isbusy = False
    busyDev = ''
    for cachedDev in cachedNames:
        if _is_device_busy('/dev/mapper/' + cachedDev):
            isbusy = True
            busyDev = cachedDev
            break
    if isbusy:
        print "Delete group %s failed, %s is busy..." % (groupName, busyDev)
        return

    cacheName = 'cachegroup-%s' % groupName
    ssd = _get_cache_ssd_dev(cacheName)

    for i in range(len(cachedNames)):
        cachedDev = cachedNames[i]
        try:
            _delete_table(cachedDev, isYes)
        except Exception, e:
            print e
            print 'Try to roll back...'
            cacheGroupDevice = '/dev/mapper/%s' % cacheName
            names, tables = _cached_tables(hddDevices, cacheGroupDevice)
            for j in range(i):
                _create_table(names[j], tables[j], True)
            return
            
    _delete_flashcache(cacheName, ssd, True)
    _delete_table(groupName, True)
    _delete_table(ssd, True)

def main_rep_ssd(args):
    if args.group == None or args.cachedev == None:
        return
    rep_ssd(args.group, args.cachedev)

def rep_ssd(groupName, cacheDevs):
    groupDevice = '/dev/mapper/%s' % groupName
    hddDevs = _get_hdd_devices(groupName)
    cacheName = 'cachegroup-%s' % groupName

    trashCacheName = cacheName+'-old'
    _rename_table(cacheName, trashCacheName)
    cacheDevName = 'cachedevices-%s' % groupName
    trashCacheDevName = cacheDevName + '-old'
    _rename_table(cacheDevName, trashCacheDevName)
    oldSsd = '/dev/mapper/%s' % trashCacheDevName
    
    cacheDevTable = ''
    try:
        cacheDevTable = _linear_map_table(cacheDevs)
    except Exception, e:
        print e
        return
    _create_table(cacheDevName, cacheDevTable, True)
    cacheDevice = '/dev/mapper/%s' % cacheDevName
    _create_flashcache(cacheName, cacheDevice, groupDevice, True)

    cacheGroupDevice = '/dev/mapper/%s' % cacheName
    cachedNames, cachedTables = _cached_tables(hddDevs, cacheGroupDevice)
    for i in range(len(cachedNames)):
        _reload_table(cachedNames[i], cachedTables[i])
    _delete_flashcache(trashCacheName, oldSsd, True)
    _delete_table(trashCacheDevName, True)
    
if __name__ == '__main__':
    parse_args(sys.argv[1:])
