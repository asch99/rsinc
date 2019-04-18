#!/usr/bin/python3

'''
merge

Copyright (c) 2019 C. J. Williams

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''

DRIVE_DIR = '/home/conor/drive/'  # where config and data files will be stored
BASE_R = 'onedrive:'
BASE_L = '/home/conor/'

DEFAULT_DIRS = ['cpp', 'test', 'cam']

CASE_INSENSATIVE = True

import argparse
import json
import os.path
import re
import subprocess
import sys
import time
import copy

from clint.textui import colored
from datetime import datetime

sys.path.insert(0, DRIVE_DIR)

import spinner


class data():
    def __init__(self, base, arg):
        self.path = base + arg + '/'

        self.d_old = {}
        self.d_tmp = {}
        self.d_dif = {}

        self.s_old = set({})
        self.s_tmp = set({})
        self.s_dif = set({})

        self.s_low = set({})

    def build_dif(self):
        self.s_old = set(self.d_old)
        self.s_tmp = set(self.d_tmp)
        self.s_low = set(k.lower() for k in self.s_tmp)

        deleted = self.s_old.difference(self.s_tmp)
        created = self.s_tmp.difference(self.s_old)

        inter = self.s_tmp.intersection(self.s_old)

        for key in created:
            self.d_dif.update({key: 3})

        for key in deleted:
            self.d_dif.update({key: 2})

        for key in inter:
            if self.d_old[key]['bytesize'] != self.d_tmp[key]['bytesize']:
                self.d_dif.update({key: 1})
            elif self.d_tmp[key]['datetime'] > self.d_old[key]['datetime']:
                self.d_dif.update({key: 1})
            else:
                self.d_dif.update({key: 0})

        self.s_dif = set(self.d_dif)


class direct():
    def __init__(self, arg):
        self.lcl = data(BASE_L, arg)
        self.rmt = data(BASE_R, arg)
        self.path = arg

    def build_dif(self):
        self.lcl.build_dif()
        self.rmt.build_dif()


def log(*args):
    if verbosity:
        print(*args)


def check_exist(path):
    if os.path.exists(path):
        log('Checked', path)
        return 0
    else:
        log('Missing', path)
        return 1


def qt(string):
    return '"' + string + '"'


def read(file):
    '''Reads json do dict and returns dict'''
    log('Reading', file)
    with open(file, 'r') as fp:
        d = json.load(fp)

    return d


def write(file, d):
    '''Writes dict to json'''
    if dry_run:
        return
    else:
        log('Writing', file)
        with open(file, 'w') as fp:
            json.dump(d, fp, sort_keys=True, indent=2)


def lsl(path):
    '''
    Runs rclone lsl on path and returns a dict containing each file with the
    size and last modified time as integers
    '''
    command = ['rclone', 'lsl', path]
    result = subprocess.Popen(
        command, stdout=subprocess.PIPE, universal_newlines=True)

    d = {}

    for line in iter(result.stdout.readline, ''):
        g = LINE_FMT.match(line)

        size = int(g.group(1))
        age = g.group(2) + ' ' + g.group(3)
        date_time = int(time.mktime(
            datetime.strptime(age, TIME_FMT).timetuple()))

        filename = g.group(5)

        d[filename] = {u'bytesize': size, u'datetime': date_time}

    return d


''' Functions for working with packed dictionary's '''


def empty():
    '''Returns dict representing empty directory'''
    return {'fold': {}, 'file': {}}


def insert(nest, chain):
    '''Inserts element in chain into packed dict, nest'''
    if len(chain) == 2:
        nest['file'].update({chain[0]: chain[1]})
    else:
        if chain[0] not in nest['fold']:
            nest['fold'].update({chain[0]: empty()})
        insert(nest['fold'][chain[0]], chain[1:])


def pack(d):
    '''Converts flat dict, d, into packed dict'''
    nest = empty()

    for chain in [k.split('/') + [v] for k, v in d.items()]:
        insert(nest, chain)

    return nest


def unpack(nest, d={}, path=''):
    '''Converts packed dict, nest, into flat dict, d'''
    for k, v in nest['file'].items():
        d.update({path + k: v})

    for k, v in nest['fold'].items():
        d.update(unpack(v, d, path + k + '/'))

    return d


def _get_branch(nest, chain):
    '''Returns packed dict at end of chain in packed dict, nest'''
    if len(chain) == 0:
        return nest
    else:
        return _get_branch(nest['fold'][chain[0]], chain[1:])


def get_branch(nest, path):
    '''Helper function for _get_branch, converts path to chain'''
    return _get_branch(nest, path.split('/'))


def _merge(nest, chain, new):
    '''Merge packed dict, new, into packed dict, nest, at end of chain'''
    if len(chain) == 1:
        nest['fold'].update({chain[0]: new})
    else:
        if chain[0] not in nest['fold']:
            nest['fold'].update({chain[0]: empty()})

        _merge(nest['fold'][chain[0]], chain[1:], new)


def merge(nest, path, new):
    '''Helper function for _merge, converts path to chain'''
    _merge(nest, path.split('/'), new)


def _have(nest, chain):
    '''Returns: true if chain is contained in packed dict, nest, else: false'''
    if len(chain) == 1:
        if chain[0] in nest['fold']:
            return 1
    else:
        if chain[0] in nest['fold']:
            return _have(nest['fold'][chain[0]], chain[1:])
    return 0


def have(master, path):
    '''Helper function for _have, converts path to chain'''
    return _have(master, path.split('/'))


def _get_min(nest, chain, min_chain):
    '''Returns the subset of chain contained in packed dict, nest'''
    if len(chain) == 1:
        return min_chain
    elif chain[0] not in nest['fold']:
        return min_chain
    else:
        min_chain.append(chain[1])
        return _get_min(nest['fold'][chain[0]], chain[1:], min_chain)


def get_min(master, path):
    '''Helper function for _get_min, converts path to chain'''
    chain = path.split('/')
    min_chain = _get_min(master, chain, [chain[0]])
    return '/'.join(min_chain)


''' Functions for moving files about '''


def cpyR(source, dest):
    global counter
    counter += 1

    if not dry_run:
        print('%d/%d' % (counter, total_jobs) + cyn(' Push: ') + source)
        subprocess.run(['rclone', 'copyto', source, dest])
    else:
        print(cyn("Push: ") + source)
    return


def cpyL(dest, source):
    global counter
    counter += 1

    if not dry_run:
        print('%d/%d' % (counter, total_jobs) + mgt(' Pull: ') + source)
        subprocess.run(['rclone', 'copyto', source, dest])
    else:
        print(mgt("Pull: ") + source)
    return


def null(*args):
    return


def conflict(source, dest):
    if skip:
        print(red('Skip conflict: ') + source)
        return
    print(red('Conflict: ') + source)

    if not dry_run:
        subprocess.run(['rclone', 'moveto', source, source + ".lcl_conflict"])
        subprocess.run(['rclone', 'moveto', dest, dest + ".rmt_conflict"])

    cpyR(source + ".lcl_conflict", dest + ".lcl_conflict")
    cpyL(source + ".rmt_conflict", dest + ".rmt_conflict")

    return


def delL(left, right):
    global counter
    counter += 1

    if not dry_run:
        print('%d/%d' % (counter, total_jobs) + ylw(' Delete: ') + left)
        subprocess.run(['rclone', 'delete', left])
    else:
        print(ylw("Delete: ") + left)
    return


def delR(left, right):
    global counter
    counter += 1

    if not dry_run:
        print('%d/%d' % (counter, total_jobs) + ylw(' Delete: ') + right)
        subprocess.run(['rclone', 'delete', right])
    else:
        print(ylw("Delete: ") + right)
    return


def sync(f, lcl_dif, rmt_dif, inter):
    for key in sorted(lcl_dif):
        if f.lcl.d_dif[key] != 2:
            if CASE_INSENSATIVE and key.lower() in f.rmt.s_low:
                print(red('ERROR,') + ' case mismatch: ' + key)
                print(red('NOT,') + ' pushing: ' + key)
            else:
                cpyR(f.lcl.path + key, f.rmt.path + key)

    for key in sorted(rmt_dif):
        if f.rmt.d_dif[key] != 2:
            if CASE_INSENSATIVE and key.lower() in f.lcl.s_low:
                print(red('ERROR,') + ' case mismatch: ' + key)
                print(red('NOT:') + ' pulling: ' + key)
            else:
                cpyL(f.lcl.path + key, f.rmt.path + key)

    if recover:
        print(ylw('Running recover'))
        for key in sorted(inter):
            if f.lcl.d_tmp[key]['bytesize'] != f.rmt.d_tmp[key]['bytesize']:
                if f.lcl.d_tmp[key]['datetime'] > f.rmt.d_tmp[key]['datetime']:
                    cpyR(f.lcl.path + key, f.rmt.path + key)
                elif f.lcl.d_tmp[key]['datetime'] < f.rmt.d_tmp[key]['datetime']:
                    cpyL(f.lcl.path + key, f.rmt.path + key)
        else:
            for key in sorted(inter):
                LOGIC[f.lcl.d_dif[key]][f.rmt.d_dif[key]](
                    f.lcl.path + key, f.rmt.path + key)


CWD = os.getcwd()
os.chdir(DRIVE_DIR)

cwd = CWD.split('/')
cwd = cwd[len(BASE_L.split('/')[:-1]):]
cwd = '/'.join(cwd)


if len(cwd) == 0:
    cwd = DEFAULT_DIRS
else:
    cwd = [cwd]

print('''
Copyright 2019 C. J. Williams (CHURCHILL COLLEGE)
This is free software with ABSOLUTELY NO WARRANTY''')

LINE_FMT = re.compile(u'\s*([0-9]+) ([\d\-]+) ([\d:]+).([\d]+) (.*)')
TIME_FMT = '%Y-%m-%d %H:%M:%S'

strtobool = {'yes': True, 'ye': True, 'y': True, 'n': False, 'no': False,
             1: 'yes', 0: 'no', 't': True, 'true': True, 'f': False,
             'false': False, 'Y': True, 'N': False, 'Yes': True, "No": False,
             '': True}

counter = 0
total_jobs = 0
folders = []
main = []

ylw = colored.yellow  # delete
cyn = colored.cyan  # push
mgt = colored.magenta  # pull
red = colored.red  # error/conflict
grn = colored.green  # normal info

swap = str.maketrans("/", '_')

LOGIC = [[null, cpyL, delL, conflict],
         [cpyR, conflict, cpyR, conflict],
         [delR, cpyL, null, cpyL],
         [conflict, conflict, cpyR, conflict]]

# read terminal arguments

parser = argparse.ArgumentParser()

parser.add_argument("folders", help="folders to sync", nargs='*')
parser.add_argument("-v", "--verbose", action="store_true", help="lots of info")
parser.add_argument("-s", "--skip", action="store_true", help="skip conflicts")
parser.add_argument("-d", "--dry", action="store_true", help="do a dry run")
parser.add_argument("-A", "--all", help="sync defaults", action="store_true")
parser.add_argument("-r", "--recovery", action="store_true",
                    help="enter recovery mode")
parser.add_argument(
    "-a", "--auto", help="don't ask permissions", action="store_true")

args = parser.parse_args()

if args.folders == []:
    folders = cwd
else:
    folders = args.folders

if args.all:
    folders = DEFAULT_DIRS

dry_run = args.dry
verbosity = args.verbose
recover = args.recovery
auto = args.auto
skip = args.skip
first_run = False

# Build main data structure
for f in folders:
    main.append(direct(f))

# get the master structures
if check_exist('master.json'):
    write('master.json', empty())

master = read('master.json')

for f in main:
    print('')

    min_path = get_min(master, f.path)

    if have(master, f.path):
        print(grn('Have:'), qt(f.path) + ', can sync')
    else:
        print(ylw('Don\'t have:'), qt(f.path) + ', entering first sync mode')
        first_run = True

    if check_exist(f.path.translate(swap) + '.tmp') == 0:
        print(red('ERROR') + ', detected crash, found a .tmp')
        recover = True

    # make and read files
    print(grn("Crawling: ") + qt(f.path), end=' ')
    spin = spinner.Spinner()
    spin.start()

    f.lcl.d_tmp = lsl(f.lcl.path)
    f.rmt.d_tmp = lsl(f.rmt.path)

    write(f.path.translate(swap) + '.tmp', {})

    spin.stop()
    print('')

    # First run
    if first_run:
        f.lcl.d_old = f.lcl.d_tmp
        f.rmt.d_old = f.rmt.d_tmp

        recover = True
    else:
        print('Reading last state')

        old = unpack(get_branch(master, f.path))

        f.lcl.d_old = copy.deepcopy(old)
        f.rmt.d_old = copy.deepcopy(old)

    f.build_dif()

    # main logic
    rmt_dif = f.rmt.s_dif.difference(f.lcl.s_dif)  # in rmt only
    lcl_dif = f.lcl.s_dif.difference(f.rmt.s_dif)  # in lcl only
    inter = f.rmt.s_dif.intersection(f.lcl.s_dif)  # in both

    mem_dry = dry_run

    print(grn('Dry pass:'))

    dry_run = True
    sync(f, lcl_dif, rmt_dif, inter)

    dry_run = mem_dry
    total_jobs = counter
    counter = 0

    if dry_run:
        print('Found:', total_jobs + 'jobs')
    elif counter == 0:
        print('Nothing to Sync')
    elif not auto and not strtobool[input('Execute? ')]:
        None
    else:
        print(grn("Live pass:"))
        sync(f, lcl_dif, rmt_dif, inter)

    print(grn('Saving:'), qt(min_path), end=' ')
    spin = spinner.Spinner()
    spin.start()

    # clean up temps
    merge(master, min_path, pack(lsl(BASE_L + min_path)))

    write('master.json', master)

    if not dry_run:
        subprocess.run(["rm", f.path.translate(swap) + '.tmp'])

    spin.stop()
    print('')

print('')
print(grn("All Done!"))