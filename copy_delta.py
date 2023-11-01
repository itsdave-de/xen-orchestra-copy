#!/bin/env python3

import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from sys import exit
import paramiko
import sqlite3
import hashlib
import argparse
from tqdm import tqdm
import pexpect
import psutil

# SQLite database settings
database_file = 'backup_copy.db' # Path to the database file

# Devices authorized to copy backups
AUTHORIZED_DEVICES = [
    '0000' # Serial number of the USB drive
]

# XO Server SSH connection settings
host = '192.168.1.10'           # IP address of the XO server
username = 'username'           # SSH username
key_filename = './ssh/id_rsa'   # SSH private key
# XO credentials
xo_username = 'admin@admin.net' # XO username (admin)
xo_password = 'xxxxxxxxx'       # XO password

# Gocryptfs settings
GOCRYPTFS_PATH = '/volume1/backup/scripts/bin/gocryptfs'
CRYPT_PASSWORD = 'xxxxxxxxxxxxxxxxxxxxx'
CRYPT_MOUNTPOINT = '/tmp/crypto'

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


def usb_devices_authorized():
    """
    Returns the path of an authorized USB device connected to the system.
    The function checks all devices in the '/dev' directory that match the pattern 'sd[a-z]+$', and uses the 'udevadm'
    command to check if the device is USB and get its serial number. If the serial number is authorized, the function
    returns the path of the device with a partition number of 1 (e.g. '/dev/sdq1').

    Returns:
        str: The path of an authorized USB device with a partition number of 1, or None if no authorized device is found.
    """
    # Use the module 'os' to list the devices in the '/dev' directory
    devices = [d for d in os.listdir('/dev') if re.match(r'sd[a-z]+$', d)]
    return_device = None
    # For each device, use the 'udevadm' command to check if it is USB and get the serial
    for dev in devices:
        result = subprocess.run(
            ['udevadm', 'info', '--query=all', '--name=/dev/' + dev],
            capture_output=True,
            text=True
        )
        info = result.stdout
        # Check if the device is USB
        if 'SYNO_DEV_DISKPORTTYPE=USB' in info:
            serial = None
            for line in info.splitlines():
                # Get the serial number
                if 'SYNO_ATTR_SERIAL=' in line:
                    serial = line.split('=')[1]
                    break
            # Check if the serial number is authorized
            if serial in AUTHORIZED_DEVICES:
                return_device = f'/dev/{dev}1'
    return return_device


def get_usb_mountpoint(usb_device):
    """
    Returns the mountpoint of a USB device, given its device path.

    If the USB device is not already mounted, it will be mounted to '/tmp/usb'.

    Args:
        usb_device (str): The device path of the USB device.

    Returns:
        str: The mountpoint of the USB device.
    """
    # Verify if the USB device is mounted with psutil
    mountpoint = None
    for part in psutil.disk_partitions():
        if part.device == usb_device:
            mountpoint = part.mountpoint
            break
    if mountpoint is None:
        # if not mounted, mount it
        mountpoint = '/tmp/usb'
        os.makedirs(mountpoint, exist_ok=True)
        subprocess.run(['/bin/mount', usb_device, mountpoint], check=True)
    return mountpoint


def umount_usb(usb_device):
    """
    Unmounts a USB device if it is currently mounted.

    Args:
        usb_device (str): The path to the USB device.

    Raises:
        subprocess.CalledProcessError: If the unmount command fails.

    Returns:
        None
    """
    # Verify if the USB device is mounted with psutil
    mountpoint = None
    for part in psutil.disk_partitions():
        if part.device == usb_device:
            mountpoint = part.mountpoint
            break
    if mountpoint is not None:
        # if mounted, unmount it
        subprocess.run(['/bin/umount', mountpoint], check=True)
        print(f'USB device {usb_device} unmounted.')


def mount_gocryptfs(source, target, password):
    """
    Mounts a directory encrypted with gocryptfs.

    Args:
        source (str): The path to the encrypted directory.
        target (str): The path to the mount point.
        password (str): The password to decrypt the directory.
    """
    if not os.path.exists(GOCRYPTFS_PATH):
        print(f"ERROR: File {GOCRYPTFS_PATH} does not exist.")
        exit(1)
    command = f"{GOCRYPTFS_PATH} {source} {target}"
    child = pexpect.spawn(command)
    child.expect("Password:")
    child.sendline(password)
    child.expect(pexpect.EOF)
    output = child.before.decode("utf-8")
    if "Filesystem mounted and ready." in output:
        print(f"Filesystem {target} mounted and ready.")
    else:
        raise Exception("Error mounting filesystem")


def unmount_gocryptfs(target):
    """
    Unmounts a directory encrypted with gocryptfs.

    Args:
        target (str): The path to the mount point.
    """
    command = ['/bin/umount', target]
    try:
        subprocess.run(command, check=True)
        print(f"Filesystem encrypted {target} unmounted.")
    except subprocess.CalledProcessError:
        print(f"Error unmounting filesystem {target}.")


def get_api_info():
    """
    Gets the backup information from the XO server and stores it in a SQLite database.
    """
    # Creates an SSH connection
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=username, key_filename=key_filename)
    # Register XO CLI
    _, stdout, _ = ssh.exec_command(f'/opt/xen-orchestra/node_modules/.bin/xo-cli --register http://localhost "{xo_username}" "{xo_password}"')
    stdout.channel.recv_exit_status()
    # Get backups from XO CLI and export to output as JSON
    command = f'/opt/xen-orchestra/node_modules/.bin/xo-cli backupNg.getAllLogs --json'
    _, stdout, _ = ssh.exec_command(command)
    stdout.channel.recv_exit_status()
    # Reads the output and converts it to a JSON object
    backups = json.loads(stdout.read().decode().strip())
    # Unregister XO CLI
    _, stdout, _ = ssh.exec_command('/opt/xen-orchestra/node_modules/.bin/xo-cli --unregister')
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
                WHERE jobid = ? AND jobname = ? AND DATE(timestamp) = DATE('now', 'localtime')
            ''', (entry['jobId'], entry['jobName']))
            if c.fetchone() is None:
                c = conn.cursor()
                c.execute('''
                    INSERT INTO api (jobid, jobname, json, copied)
                    VALUES (?, ?, ?, ?)
                ''', (entry['jobId'], entry['jobName'], json.dumps(entry), False))
                conn.commit()
        conn.close()


def calculate_md5(file_path, show_progress=False):
    """
    Calculates the MD5 hash of a file.

    Args:
        file_path (str): The path to the file to hash.
        show_progress (bool): Whether to show the progress bar or not.

    Returns:
        str: The MD5 hash of the file.
    """
    hash_md5 = hashlib.md5()
    file_size = os.path.getsize(file_path)
    # Read the file in chunks to avoid memory issues
    with open(file_path, 'rb') as f:
        if show_progress:
            progress = tqdm(
                total=file_size,
                unit='B',
                unit_scale=True,
                desc=f'Calculating MD5 ({os.path.basename(file_path)})'
            )
        else:
            progress = None
        while True:
            chunk = f.read(4096)
            if not chunk:
                break
            hash_md5.update(chunk)
            if progress is not None:
                progress.update(len(chunk))
        if show_progress:
            progress.close()
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
        INSERT INTO backup_log (jobid, filename, source_path, destination_path, hash_md5)
        VALUES (?, ?, ?, ?, ?)
    ''', (jobid, filename, source_path, destination_path, hash_md5))
    conn.commit()
    conn.close()


def copy_delta_backups(source_directory, destination_directory, usb_device, jobid, show_progress=False):
    """
    Copy delta mode backups from source_directory to destination_directory.
    
    :param source_directory: Path of the source directory containing the backups.
    :param destination_directory: Path of the destination directory.
    :param usb_device: Path of the USB device.
    :param jobid: The jobid of the backup job to copy.
    :param show_progress: If True, shows the progress bar during copy.
    """
    # Verify if the destination directory exists
    if not os.path.exists(destination_directory):
        print(f'Directory {destination_directory} does not exist. Create it first.')
        os.makedirs(destination_directory, exist_ok=True)
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
    # Verify if the json file exists
    if json_array_filename is []:
        print(f'File .json for jobid {jobid} not found.')
        return False
    # For each json file, find the image file associated with the full backup
    for json_filename in json_array_filename:
        # Read the json file content
        with open(os.path.join(*json_filename), 'r') as file:
            content = json.load(file)
            # Verify if the backup is delta type
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
                        # If the file has not been copied, copy it
                        if row is None:
                            total_size = os.path.getsize(image_filepath)
                            # first mount usb drive
                            usb_sourcedir = os.path.join(
                                get_usb_mountpoint(usb_device),
                                'backup'
                            )
                            os.makedirs(usb_sourcedir, exist_ok=True)
                            # Verify if disk have enough space
                            if psutil.disk_usage(usb_sourcedir).free < total_size:
                                print(f'Not enough space on {usb_sourcedir}. Need {total_size} bytes, disk has {psutil.disk_usage(usb_sourcedir).free} bytes.')
                                return False
                            # Second mount the encrypted directory
                            mount_gocryptfs(usb_sourcedir), destination_directory, CRYPT_PASSWORD)
                            # Create directory if not exists on destination
                            os.makedirs(os.path.join(destination_directory, os.path.dirname(vhd)), exist_ok=True)
                            if show_progress:
                                with open(destination_image_filepath, 'wb') as file:
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
                            hash_md5 = calculate_md5(image_filepath, show_progress)
                            log_backup(
                                jobid,
                                os.path.basename(vhd),
                                os.path.join(image_filepath, os.path.dirname(vhd)),
                                destination_image_filepath,
                                hash_md5
                            )
                            # Unmount the encrypted directory
                            unmount_gocryptfs(destination_directory)
                            # umount usb drive
                            umount_usb(usb_device)
                            print(f'Copy Image backup: {os.path.basename(vhd)} -> {destination_image_filepath}')
                        else:
                            # Verify if the file has been modified
                            current_hash_md5 = calculate_md5(image_filepath)
                            if current_hash_md5 != row[3]:
                                # first mount usb drive
                                usb_sourcedir = os.path.join(
                                    get_usb_mountpoint(usb_device),
                                    'backup'
                                )
                                os.makedirs(usb_sourcedir, exist_ok=True)
                                # Verify if disk have enough space
                                if psutil.disk_usage(usb_sourcedir).free < total_size:
                                    print(f'Not enough space on {usb_sourcedir}. Need {total_size} bytes, disk has {psutil.disk_usage(usb_sourcedir).free} bytes.')
                                    return False
                                # Second mount the encrypted directory
                                mount_gocryptfs(CRYPT_SOURCE, destination_directory, CRYPT_PASSWORD)
                                if show_progress:
                                    with open(destination_image_filepath, 'wb') as file:
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
                                # Calculate the new MD5 hash
                                hash_md5 = calculate_md5(image_filepath, show_progress)
                                log_backup(
                                    jobid,
                                    os.path.basename(vhd),
                                    os.path.join(image_filepath, os.path.dirname(vhd)),
                                    destination_image_filepath,
                                    hash_md5
                                )
                                # Unmount the encrypted directory
                                unmount_gocryptfs(destination_directory)
                                # Umount usb drive
                                umount_usb(usb_device)
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
        # Verify if device authorized is connected
        usb_device = usb_devices_authorized()
        if usb_device is None:
            print('No authorized USB device connected.')
            exit(1)
        if copy_delta_backups(
            '/volume1/backup/xo-vm-backups',
            CRYPT_MOUNTPOINT,
            usb_device,
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
