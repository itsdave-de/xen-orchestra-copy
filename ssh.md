# Generating SSH Public Keys on Synology

## Generating SSH Keys

1. Open a terminal.

2. Run the following command to generate a new SSH key pair:

> Taking into account that the script will run in the `/volume1/backup/scripts` directory, create a directory (which is already in the repository) called `ssh`

```bash
ssh-keygen -t rsa -b 2048
```

When prompted, provide the path to the file in which you want to save the key. In this case, it should be inside the `./ssh` directory, for example:

```bash
./ssh/id_rsa
```

3. Enter a passphrase for added security (optional).

## Accessing Your Public Key

Once you've generated your SSH key pair, you can access your public key with the following command:

```bash
cat ./ssh/id_rsa.pub
```

This will display your public key, which you can then copy and use in backup copy script.
