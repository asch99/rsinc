#!/usr/bin/env python3
# -*- coding: utf-8 -*-

print('''
Copyright 2019 C. J. Williams (CHURCHILL COLLEGE)
This is free software with ABSOLUTELY NO WARRANTY''')

import argparse
import os
import subprocess
import logging
import glob
from datetime import datetime

import ujson as json
import halo
from clint.textui import colored

import rsinc


# ****************************************************************************
# *                               Set-up/Parse                               *
# ****************************************************************************


parser = argparse.ArgumentParser()

parser.add_argument("folders", help="Folders to sync", nargs='*')
parser.add_argument("-d", "--dry", action="store_true", help="Do a dry run")
parser.add_argument("-c", "--clean", action="store_true",
                    help="Clean directories")
parser.add_argument("-D", "--default", help="Sync defaults",
                    action="store_true")
parser.add_argument("-r", "--recovery", action="store_true",
                    help="Enter recovery mode")
parser.add_argument("-a", "--auto", help="Don't ask permissions",
                    action="store_true")
parser.add_argument("-p", "--purge", help="Reset history for all folders",
                    action="store_true")
parser.add_argument("-i", "--ignore",
                    help="Find .rignore and add their contents to ignore list",
                    action="store_true")
parser.add_argument("-v", "--version",
                    help="Show version and exit", action="store_true")
parser.add_argument("--config",
                    help="Path to config file (default ~/.rsinc/config.json)")

args = parser.parse_args()

if args.version:
    print('')
    exit('Version: ' + rsinc.__version__)

dry_run = args.dry
auto = args.auto

ylw = colored.yellow   # warn
red = colored.red      # error
grn = colored.green    # info

spin = halo.Halo(spinner='dots', placement='right', color='yellow')


# ****************************************************************************
# *                                 Functions                                *
# ****************************************************************************


def qt(string):
    return '"' + string + '"'


def read(file):
    '''Reads json do dict and returns dict.'''
    with open(file, 'r') as fp:
        d = json.load(fp)

    return d


def write(file, d):
    '''Writes dict to json'''
    with open(file, 'w') as fp:
        json.dump(d, fp, sort_keys=True, indent=2)


STB = ('yes', 'ye', 'y', '1', 't', 'true', '', 'go', 'please', 'fire away',
       'punch it', 'sure', 'ok', 'hell yes', )


def strtobool(string):
    return string.lower() in STB


def empty():
    '''Returns dict representing empty directory.'''
    return {'fold': {}, 'file': {}}


def insert(nest, chain):
    '''Inserts element at the end of the chain into packed dict, nest.'''
    if len(chain) == 2:
        nest['file'].update({chain[0]: chain[1]})
        return

    if chain[0] not in nest['fold']:
        nest['fold'].update({chain[0]: empty()})

    insert(nest['fold'][chain[0]], chain[1:])


def pack(flat):
    '''Converts flat, into packed dict.'''
    nest = empty()
    for name, file in flat.names.items():
        chain = name.split('/') + [file.uid]
        insert(nest, chain)

    return nest


def unpack(nest, flat, path=''):
    '''Converts packed dict, nest, into flat.'''
    for k, v in nest['file'].items():
        flat.update(path + k, v)

    for k, v in nest['fold'].items():
        unpack(v, flat, path + k + '/')


def _get_branch(nest, chain):
    '''Returns packed dict at end of chain in packed dict, nest.'''
    if len(chain) == 0:
        return nest
    else:
        return _get_branch(nest['fold'][chain[0]], chain[1:])


def get_branch(nest, path):
    '''Helper function for _get_branch, converts path to chain.'''
    return _get_branch(nest, path.split('/'))


def _merge(nest, chain, new):
    '''Merge packed dict, new, into packed dict, nest, at end of chain.'''
    if len(chain) == 1:
        nest['fold'].update({chain[0]: new})
        return

    if chain[0] not in nest['fold']:
        nest['fold'].update({chain[0]: empty()})

    _merge(nest['fold'][chain[0]], chain[1:], new)


def merge(nest, path, new):
    '''Helper function for _merge, converts path to chain.'''
    _merge(nest, path.split('/'), new)


def _have(nest, chain):
    '''Returns: true if chain is contained in packed dict, nest, else: false.'''
    if chain[0] in nest['fold']:
        if len(chain) == 1:
            return True
        else:
            return _have(nest['fold'][chain[0]], chain[1:])

    return False


# ****************************************************************************
# *                              Configuration                               *
# ****************************************************************************


CONFIG_FILE = os.path.expanduser('~/.rsinc/config.json')  # Default config path

# Read config and assign variables.
if args.config == None:
    config = read(CONFIG_FILE)
else:
    config = read(args.config)

CASE_INSENSATIVE = config['CASE_INSENSATIVE']
DEFAULT_DIRS = config['DEFAULT_DIRS']
LOG_FOLDER = config['LOG_FOLDER']
HASH_NAME = config['HASH_NAME']
TEMP_FILE = config['TEMP_FILE']
MASTER = config['MASTER']
BASE_R = config['BASE_R']
BASE_L = config['BASE_L']

# Set up logging.
logging.basicConfig(filename=LOG_FOLDER + datetime.now().strftime('%Y-%m-%d'),
                    level=logging.DEBUG,
                    datefmt='%H:%M:%S',
                    format='%(asctime)s %(levelname)s: %(message)s',)


# ****************************************************************************
# *                               Main Program                               *
# ****************************************************************************

def main():
    '''
    Entry point for 'rsinc' as terminal command.
    '''
    recover = args.recovery

    # Decide which folder(s) to sync.
    cwd = os.getcwd()

    if args.default:
        tmp = DEFAULT_DIRS
    elif len(args.folders) == 0:
        tmp = [cwd]
    else:
        tmp = []
        for f in args.folders:
            if os.path.isabs(f):
                tmp.append(os.path.normpath(f))
            else:
                tmp.append(os.path.abspath(f))

    folders = []
    for f in tmp:
        if BASE_L not in f:
            print(ylw('Rejecting:'), f, 'not in', BASE_L)
        else:
            folders.append(f[len(BASE_L):])

    # Get & read master.
    if args.purge or not os.path.exists(MASTER):
        print(ylw('WARN:'), MASTER, 'missing, this must be your first run')
        write(MASTER, [[], [], empty()])

    history, ignores, nest = read(MASTER)

    history = set(history)

    # Find all the ignore files in lcl and save them.
    if args.ignore:
        search = os.path.normpath(BASE_L + "/**/.rignore")
        ignores = glob.glob(search, recursive=True)
        write(MASTER, (history, ignores, nest))
        regexs, plain = rsinc.build_regexs(BASE_L, ignores)
        print("Ignoring:", plain)

    # Detect crashes.
    if os.path.exists(TEMP_FILE):
        corrupt = read(TEMP_FILE)['folder']
        if corrupt in folders:
            folders.remove(corrupt)

        folders.insert(0, corrupt)
        recover = True
        print(red('ERROR') + ', detected a crash, recovering', corrupt)
        logging.warning('Detected crash, recovering %s', corrupt)

    # Main loop.
    for folder in folders:
        print('')
        path_lcl = BASE_L + folder + '/'
        path_rmt = BASE_R + folder + '/'

        # Determine if first run.
        if folder in history:
            print(grn('Have:'), qt(folder) + ', entering sync & merge mode')
        else:
            print(ylw('Don\'t have:'), qt(folder) + ', entering first_sync mode')
            recover = True

        # Build relative regular expressions
        regexs, plain = rsinc.build_regexs(path_lcl, ignores)

        # Scan directories.
        spin.start(("Crawling: ") + qt(folder))

        lcl = rsinc.lsl(path_lcl, HASH_NAME, regexs)
        rmt = rsinc.lsl(path_rmt, HASH_NAME, regexs)
        old = rsinc.Flat('old')

        spin.stop_and_persist(symbol='✔')

        # First run & recover mode.
        if recover:
            print('Running', ylw('recover/first_sync'), 'mode')
        else:
            print('Reading last state.')
            branch = get_branch(nest, folder)
            unpack(branch, old)

            rsinc.calc_states(old, lcl)
            rsinc.calc_states(old, rmt)

        print(grn('Dry pass:'))
        total = rsinc.sync(lcl, rmt, old, recover,
                           dry_run=True, case=CASE_INSENSATIVE)

        print('Found:', total, 'job(s)')

        if not dry_run and (auto or total == 0 or strtobool(input('Execute? '))):
            if total != 0 or recover:
                print(grn("Live pass:"))

                write(TEMP_FILE, {'folder': folder})
                rsinc.sync(lcl, rmt, old, recover, dry_run=dry_run,
                           total=total, case=CASE_INSENSATIVE)

                spin.start(grn('Saving: ') + qt(folder))

                # Merge into history.
                command = ['rclone', 'lsjson', '-R', '--dirs-only', path_lcl]
                result = subprocess.Popen(command, stdout=subprocess.PIPE)
                dirs = json.load(result.stdout)

                history.add(folder)
                history.update(folder + '/' + d['Path'] for d in dirs)

                # Merge into nest and clean up.
                merge(nest, folder, pack(
                    rsinc.lsl(BASE_L + folder, HASH_NAME, regexs)))
                write(MASTER, (history, ignores, nest))
                subprocess.run(["rm", TEMP_FILE])

                spin.stop_and_persist(symbol='✔')

        if args.clean:
            spin.start(grn('Pruning: ') + qt(folder))

            subprocess.run(["rclone", 'rmdirs', path_rmt])
            subprocess.run(["rclone", 'rmdirs', path_lcl])

            spin.stop_and_persist(symbol='✔')

        recover = args.recovery

    print('')
    print(grn("All synced!"))


if __name__ == '__main__':
    main()