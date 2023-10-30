# Setting Up a Directory with `gocryptfs`

`gocryptfs` is a filesystem encryption tool that protects your files with 128/256-bit AES-GCM encryption.

More informations: https://github.com/rfjakob/gocryptfs/blob/master/README.md

## Prerequisites

Before starting, make sure you have `gocryptfs` installed on your system. In the case of environments with Synology configured, you must use the static binary, as per the instructions below:

```bash
sudo mkdir -p /volume1/backup/scripts/bin
wget -O - https://github.com/rfjakob/gocryptfs/releases/download/v2.4.0/gocryptfs_v2.4.0_linux-static_amd64.tar.gz | tar -C /volume1/backup/scripts/bin/ -zxvf -
```

This will make the files in the `/volume1/backup/scripts/bin` directory available to be used manually or in the script


## Creating an Encrypted Directory

1. Create a directory that will be used to store your encrypted files:

> In the Synology env, using the USB drive, use the directory below

```bash
mkdir /volumeUSB1/usbshare/backup
```

2. Initialize `gocryptfs` in the created directory:

```bash
gocryptfs -init /volumeUSB1/usbshare/backup
```

This will create a configuration and an encryption key for the directory.

It will ask for an encryption password, it will be needed to configure in the backup copy script.

```
Your master key is:

    xxxxxxxx-xxxxxxxx-xxxxxxxx-xxxxxxxx-
    xxxxxxxx-xxxxxxxx-xxxxxxxx-xxxxxxxx

If the gocryptfs.conf file becomes corrupted or you ever forget your password,
there is only one hope for recovery: The master key. Print it to a piece of
paper and store it in a drawer. This message is only printed once.
The gocryptfs filesystem has been created successfully.
```

It will also generate a master key, which must be stored safely in case the encryption settings are lost. This key can be used to recover the files.

## Mounting the Encrypted Directory

After initialization, you need to mount the encrypted directory to be able to access and manipulate the files securely.

1. Create a mount directory:

```bash
mkdir my_mount_directory
```

2. Mount the encrypted directory:

```bash
gocryptfs /volumeUSB1/usbshare/backup my_mount_directory
```

After mounting the directory, you will be prompted to enter the password you defined during initialization.

## Working with Files

With the directory mounted, you can work with your files normally. All files added to the mount directory will be automatically encrypted and stored in the encrypted directory.

## Unmounting the Encrypted Directory

When you are done working with your files, you can unmount the encrypted directory with the following command:

```bash
umount my_mount_directory
```
