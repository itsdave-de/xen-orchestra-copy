# Backup Copy

This Python script automates the process of copying backups from a Xen Orchestra (XO) server from the mode "Delta" and only FULL images to a destination directory, which is encrypted with `gocryptfs`. The backup information is fetched from the XO server using its API, and the details of the backups are stored in a SQLite database. The database is used to track which backups have already been copied, avoiding redundant operations.

## Requirements

- Python 3
- Paramiko for SSH connection
- SQLite3 for database operations
- TQDM for progress bars
- Pexpect for interacting with `gocryptfs`
- [`gocryptfs`](https://github.com/rfjakob/gocryptfs/tree/master) for encrypted backups


## How to Use

1. Update the following settings according to your environment:

    - SQLite database settings
    - XO Server SSH connection settings ([need to generate SSH keys](ssh.md))
    - XO credentials
    - `gocryptfs` settings

2. Install the required Python packages:

    ```
    sudo pip3 install paramiko tqdm pexpect
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
