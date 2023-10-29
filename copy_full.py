#!/bin/env python3

import json
import os
from datetime import datetime
import paramiko
import sqlite3
import hashlib
import argparse
from tqdm import tqdm

database_file = 'backup_copy.db'

# SSH connection settings
host = '192.168.1.10'
username = 'username'
key_filename = './ssh/id_rsa'

xo_username = 'admin@admin.net'
xo_password = 'xxxxxxxxx'

def create_database():
    conn = sqlite3.connect(database_file)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS api (
              id INTEGER PRIMARY KEY,
              jobid TEXT,
              jobname TEXT,
              json TEXT,
              copied INTEGER DEFAULT 0,
              timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS backup_log (
              id INTEGER PRIMARY KEY,
              filename TEXT,
              source_path TEXT,
              destination_path TEXT,
              hash_md5 TEXT,
              timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def get_api_info():
    # Creates an SSH connection
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=username, key_filename=key_filename)

    stdin, stdout, stderr = ssh.exec_command(f'/opt/xen-orchestra/node_modules/.bin/xo-cli --register http://localhost "{xo_username}" "{xo_password}"')
    stdout.channel.recv_exit_status()

    command = f'/opt/xen-orchestra/node_modules/.bin/xo-cli backupNg.getAllLogs --json'
    stdin, stdout, stderr = ssh.exec_command(command)
    stdout.channel.recv_exit_status()

    backups = json.loads(stdout.read().decode().strip())

    stdin, stdout, stderr = ssh.exec_command('/opt/xen-orchestra/node_modules/.bin/xo-cli --unregister')
    stdout.channel.recv_exit_status()

    ssh.close()

    backups_today = [backups[i] for i in backups.keys() if (
        (backups[i]['data']['mode'] == 'full') and (
            datetime.fromtimestamp(backups[i]['start'] // 1000).date() == datetime.today().date()
        ) and (backups[i]['status'] == 'success')
    )]

    if backups_today:
        conn = sqlite3.connect(database_file)
        for entry in backups_today:
            c = conn.cursor()
            c.execute('''
            SELECT * FROM api
                WHERE jobid = ? AND jobname = ?
            ''', (entry['jobId'], entry['jobName']))
            if c.fetchone() is None:
                c = conn.cursor()
                c.execute('''
                    INSERT INTO api (jobid, jobname, json, copied)
                    VALUES (?, ?, ?, ?)
                ''', (entry['jobId'], entry['jobName'], json.dumps(entry), False))
                conn.commit()
        conn.close()

def calculate_md5(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def log_backup(filename, source_path, destination_path, hash_md5):
    conn = sqlite3.connect(database_file)
    c = conn.cursor()
    c.execute('''
        INSERT INTO backup_log (filename, source_path, destination_path, hash_md5)
        VALUES (?, ?, ?, ?)
    ''', (filename, source_path, destination_path, hash_md5))
    conn.commit()
    conn.close()

def copy_full_backups(source_directory, destination_directory, jobid, show_progress=False):
    if not os.path.exists(destination_directory):
        print(f'Directory {destination_directory} does not exist.')
        return False
    
    json_array_filename = []
    for root, dirs, files in os.walk(source_directory):
        for filename in files:
            if filename.endswith('.json'):
                filepath = os.path.join(root, filename)
                with open(filepath, 'r') as file:
                    content = json.load(file)
                    if 'jobId' in content and content['jobId'] == jobid:
                        json_array_filename.append((os.path.dirname(filepath), filename))
                        break
    
    if json_array_filename is []:
        print(f'File .json for jobid {jobid} not found.')
        return False
    
    for json_filename in json_array_filename:
        json_filepath = os.path.join(*json_filename)
        with open(json_filepath, 'r') as file:
            content = json.load(file)
            
            if 'mode' in content and content['mode'] == 'full':
                base_name = os.path.splitext(json_filename[1])[0]
                image_filename = None
                for file in files:
                    if file.startswith(base_name) and (file.endswith('.vhd') or file.endswith('.xva')):
                        image_filename = file
                        break
                if image_filename is None and 'xva' in content:
                    image_filename = content['xva']
                
                if image_filename is not None:
                    image_filepath = os.path.join(json_filename[0], image_filename)
                    destination_image_filepath = os.path.join(destination_directory, image_filename)
                    
                    conn = sqlite3.connect(database_file)
                    c = conn.cursor()
                    c.execute('''
                        SELECT * FROM backup_log
                        WHERE filename = ? AND source_path = ? AND destination_path = ?
                    ''', (image_filename, image_filepath, destination_image_filepath))
                    row = c.fetchone()
                    
                    if row is None:
                        total_size = os.path.getsize(image_filepath)
                        destination_image_filepath = os.path.join(destination_directory, image_filename)
                        with open(destination_image_filepath, 'wb') as file:
                            if show_progress:
                                with tqdm(
                                    total=total_size,
                                    unit='B',
                                    unit_scale=True,
                                    desc=f'Copying ({image_filename})'
                                ) as pbar:
                                    with open(image_filepath, 'rb') as source_file:
                                        while True:
                                            chunk = source_file.read(4096)
                                            if not chunk:
                                                break
                                            file.write(chunk)
                                            pbar.update(len(chunk))
                            else:
                                from shutil import copyfile
                                copyfile(image_filepath, destination_image_filepath)
                        hash_md5 = calculate_md5(image_filepath)
                        log_backup(image_filename, image_filepath, destination_image_filepath, hash_md5)
                        print(f'Copy full backup: {image_filepath} -> {destination_image_filepath}')
                    else:
                        current_hash_md5 = calculate_md5(image_filepath)
                        if current_hash_md5 != row[3]:
                            from shutil import copyfile
                            copyfile(image_filepath, destination_image_filepath)
                            
                            log_backup(image_filename, image_filepath, destination_image_filepath, current_hash_md5)
                            print(f'Backup full file {image_filepath} -> {destination_image_filepath} has been modified.')
                        else:
                            print(f'Backup full file {image_filepath} -> {destination_image_filepath} already exists and is up to date.')

                    conn.close()
                else:
                    print(f'File {image_filepath} not found for jobid {jobid}')
            else:
                print(f'The backup for jobid {jobid} is not full type.')
    return True

parser = argparse.ArgumentParser(description='Copies backups.')
parser.add_argument('--progress', action='store_true', help='Shows the progress bar during copy.')
args = parser.parse_args()

if __name__ == '__main__':
    create_database()
    get_api_info()
    conn = sqlite3.connect(database_file)
    c = conn.cursor()
    c.execute('''
        SELECT * FROM api
        WHERE copied = 0
    ''')
    rows = c.fetchall()
    conn.close()
    for row in rows:
        if copy_full_backups(
            '/volume1/backup/xo-vm-backups',
            '/volumeUSB1/usbshare/backup',
            row[1],
            args.progress
        ):
            conn = sqlite3.connect(database_file)
            c = conn.cursor()
            c.execute('''
                UPDATE api
                SET copied = 1
                WHERE id = ?
            ''', (row[0],))
            conn.commit()
            conn.close()
