#!/bin/env python3

import json
import os
import shutil
from datetime import datetime
import paramiko
import sqlite3
import hashlib
import argparse
from cryptography.fernet import Fernet
from tqdm import tqdm

database_file = 'backup_copy.db' # Path to the database file

# SSH connection settings
host = '192.168.1.10'           # IP address of the XO server
username = 'username'           # SSH username
key_filename = './ssh/id_rsa'   # SSH private key

xo_username = 'admin@admin.net' # XO username (admin)
xo_password = 'xxxxxxxxx'       # XO password

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
              jobid TEXT,
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

    # Executes the external command and redirects the output to the temporary file
    command = f'/opt/xen-orchestra/node_modules/.bin/xo-cli backupNg.getAllLogs --json'
    stdin, stdout, stderr = ssh.exec_command(command)
    stdout.channel.recv_exit_status()

    backups = json.loads(stdout.read().decode().strip())

    stdin, stdout, stderr = ssh.exec_command('/opt/xen-orchestra/node_modules/.bin/xo-cli --unregister')
    stdout.channel.recv_exit_status()

    # Closes the SSH connection
    ssh.close()

    # Get backups from today with mode delta and status success
    backups_today = [backups[i] for i in backups.keys() if (
        (backups[i]['data']['mode'] == 'delta') and (
            datetime.fromtimestamp(backups[i]['start'] // 1000).date() == datetime.today().date()
        ) and (backups[i]['status'] == 'success')
    )]

    # Add registry on database
    if backups_today:
        conn = sqlite3.connect(database_file)
        for entry in backups_today:
            # Verify if exists on database
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
    """
    Calculates the MD5 hash of a file.

    Args:
        file_path (str): The path to the file to hash.

    Returns:
        str: The MD5 hash of the file.
    """
    hash_md5 = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def log_backup(jobid, filename, source_path, destination_path, hash_md5):
    """
    Logs a backup operation to a SQLite database.

    Args:
        jobid (str): The jobid of the backup job.
        filename (str): The name of the file being backed up.
        source_path (str): The path to the file being backed up.
        destination_path (str): The path to the backup destination.
        hash_md5 (str): The MD5 hash of the file being backed up.
    """
    conn = sqlite3.connect(database_file)
    c = conn.cursor()
    c.execute('''
        INSERT INTO backup_log (filename, source_path, destination_path, hash_md5)
        VALUES (?, ?, ?, ?)
    ''', (jobid, filename, source_path, destination_path, hash_md5))
    conn.commit()
    conn.close()

# Copy delta mode backups function
def copy_delta_backups(source_directory, destination_directory, jobid, show_progress=False):
    """
    Copy delta mode backups from source_directory to destination_directory.
    
    :param source_directory: Path of the source directory containing the backups.
    :param destination_directory: Path of the destination directory (e.g., USB drive).
    :param jobid: The jobid of the backup job to copy.
    :param show_progress: If True, shows the progress bar during copy.
    """
    
    # Verify if the destination directory exists
    if not os.path.exists(destination_directory):
        print(f'Directory {destination_directory} does not exist.')
        return False
    
    # Find the .json file that corresponds to the jobid
    json_array_filename = []
    for root, dirs, files in os.walk(source_directory):
        for filename in files:
            if filename.endswith('.json'):
                filepath = os.path.join(root, filename)
                with open(filepath, 'r') as file:
                    content = json.load(file)
                    if 'jobId' in content and content['jobId'] == jobid:
                        json_array_filename.append((os.path.dirname(filepath), filename))
    
    if json_array_filename is []:
        print(f'File .json for jobid {jobid} not found.')
        return False
    
    # For each json file, find the image file associated with the full backup
    for json_filename in json_array_filename:
        # Read the json file content
        json_filepath = os.path.join(*json_filename)
        with open(json_filepath, 'r') as file:
            content = json.load(file)
            
            if 'mode' in content and content['mode'] == 'delta':
                # Deternine if the image is FULL or Incremental
                if not content['vdis'][list(
                    content['vdis'].keys()
                )[0]].get('other_config', {}):
                    # find the image file associated with the delta backup
                    for vhd in content.get('vhds', {}).values():
                        image_filepath = os.path.join(json_filename[0], vhd)
                        destination_image_filepath = os.path.join(destination_directory, vhd)
                        
                        # Verify if the file has already been copied
                        conn = sqlite3.connect(database_file)
                        c = conn.cursor()
                        c.execute('''
                            SELECT * FROM backup_log
                            WHERE jobid = ? AND filename = ? AND source_path = ? AND destination_path = ?
                        ''', (
                                jobid,
                                os.path.basename(vhd),
                                os.path.join(image_filepath, os.path.dirname(vhd)),
                                destination_image_filepath
                            )
                        )
                        row = c.fetchone()
                        
                        if row is None:
                            total_size = os.path.getsize(image_filepath)
                            # Create directory if not exists on destination
                            os.makedirs(os.path.join(destination_directory, os.path.dirname(vhd)), exist_ok=True)
                            with open(destination_image_filepath, 'wb') as file:
                                if show_progress:
                                    with tqdm(
                                        total=total_size,
                                        unit='B',
                                        unit_scale=True,
                                        desc=f'Copying ({os.path.basename(vhd)})'
                                    ) as pbar:
                                        with open(image_filepath, 'rb') as source_file:
                                            while True:
                                                chunk = source_file.read(4096)
                                                if not chunk:
                                                    break
                                                file.write(chunk)
                                                pbar.update(len(chunk))
                                else:
                                    shutil.copyfile(image_filepath, destination_image_filepath)
                            hash_md5 = calculate_md5(image_filepath)
                            log_backup(
                                jobid,
                                os.path.basename(vhd),
                                os.path.join(image_filepath, os.path.dirname(vhd)),
                                destination_image_filepath,
                                hash_md5
                            )
                            print(f'Copy Image backup: {os.path.basename(vhd)} -> {destination_image_filepath}')
                        else:
                            # Verify if the file has been modified
                            current_hash_md5 = calculate_md5(image_filepath)
                            if current_hash_md5 != row[3]:
                                shutil.copyfile(image_filepath, destination_image_filepath)
                                
                                log_backup(
                                    jobid,
                                    os.path.basename(vhd),
                                    os.path.join(image_filepath, os.path.dirname(vhd)),
                                    destination_image_filepath,
                                    hash_md5
                                )
                                print(f'Backup Image file {os.path.basename(vhd)} -> {destination_image_filepath} has been modified.')
                            else:
                                print(f'Backup Image file {os.path.basename(vhd)} -> {destination_image_filepath} already exists and is up to date.')

                        # Close the database connection
                        conn.close()

            else:
                print(f'The backup for jobid {jobid} is not delta type.')
    # always return True
    return True

# Parse arguments
parser = argparse.ArgumentParser(description='Copies backups.')
parser.add_argument('--progress', action='store_true', help='Shows the progress bar during copy.')
args = parser.parse_args()

# Main function
if __name__ == '__main__':
    create_database()
    get_api_info()
    # Select all backups that are not copied
    conn = sqlite3.connect(database_file)
    c = conn.cursor()
    c.execute('''
        SELECT * FROM api
        WHERE copied = 0
    ''')
    rows = c.fetchall()
    conn.close()
    # Copy all backups
    for row in rows:
        if copy_delta_backups(
            '/volume1/backup/xo-vm-backups',
            '/volumeUSB1/usbshare/backup',
            row[1],
            args.progress
        ):
            # Update database
            conn = sqlite3.connect(database_file)
            c = conn.cursor()
            c.execute('''
                UPDATE api
                SET copied = 1
                WHERE id = ?
            ''', (row[0],))
            conn.commit()
            conn.close()
