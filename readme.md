# Backup Copy

This Python script automates the process of copying backups from a Xen Orchestra (XO) server from the mode "Delta" and only FULL images to a destination directory, which is encrypted with `gocryptfs`. The backup information is fetched from the XO server using its API, and the details of the backups are stored in a SQLite database. The database is used to track which backups have already been copied, avoiding redundant operations.

## Requirements

- Python 3
- Paramiko for SSH connection
- SQLite3 for database operations
- TQDM for progress bars
- PSUtil for manage usb disks
- Pexpect for interacting with `gocryptfs`
- [`gocryptfs`](https://github.com/rfjakob/gocryptfs/tree/master) for encrypted backups


## How to Use

1. Update the following settings according to your environment:

The `copy_delta.py` script requires the setup of some constant variables at the beginning of the code. These variables are used to define settings for the SQLite database, authorized devices, SSH connection settings, and encryption settings.

#### SQLite Database Configuration

The `database_file` variable defines the path to the SQLite database file.

```python
database_file = 'backup_copy.db'
```

#### Authorized Devices Configuration

The `AUTHORIZED_DEVICES` list contains the serial numbers of USB devices authorized to receive backup copies.

```python
AUTHORIZED_DEVICES = [
    '0000000000000a',  # Disk number 001
    '0000000000000b'   # Disk number 002
]
```

#### SSH Connection Configuration to the XO Server

The following variables are used to define the SSH connection settings to the XO server.

- `host`: The IP address of the XO server.
- `username`: The SSH username.
- `key_filename`: The path to the SSH private key file.

```python
host = '192.168.1.10'
username = 'username'
key_filename = './ssh/id_rsa'
```

#### XO Credentials

The following variables are used to store the XO admin credentials.

- `xo_username`: The XO admin username.
- `xo_password`: The XO admin password.

```python
xo_username = 'admin@admin.net'
xo_password = 'xxxxxxxxx'
```

#### Gocryptfs Settings

The following variables are used to define the Gocryptfs encryption settings.

- `GOCRYPTFS_PATH`: The path to the Gocryptfs executable.
- `CRYPT_PASSWORD`: The password to decrypt the directory.
- `CRYPT_MOUNTPOINT`: The point of mount of the encrypted directory.

```python
GOCRYPTFS_PATH = '/volume1/backup/scripts/bin/gocryptfs'
CRYPT_PASSWORD = 'xxxxxxxxxxxxxxxxxxxxx'
CRYPT_MOUNTPOINT = '/tmp/crypto'
```

2. Install the required Python packages:

    ```
    sudo pip3 install paramiko tqdm pexpect psutil
    ```

3. Run the script with the following command:

    ```
    sudo python3 copy_delta.py --progress
    ```

    The `--progress` flag is optional and shows a progress bar during the copying of backup files.

## How it Works

1. The script starts by creating a SQLite database to store information about the backups.
2. It then connects to the XO server via SSH and fetches the backup information using the XO API.
3. The backup information is filtered to include only delta mode backups from the current day that have a status of 'success'.
4. The script then calculates the MD5 hash of each backup file.
5. If the destination directory is encrypted with `gocryptfs`, the script mounts the encrypted directory.
6. The backup files are then copied to the destination directory, and the details of the operation are logged in the database.
7. After all backups have been copied, the script unmounts the encrypted directory.

## Notes

- Ensure that the destination directory exists and is writable.
- The destination directory must be configured with encryption using the tool `gocryptfs`, [See here how to configure](gocryptfs.md)
