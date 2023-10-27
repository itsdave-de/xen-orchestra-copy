#!/bin/env python3

import os
import sqlite3
import argparse
from cryptography.fernet import Fernet
from tqdm import tqdm

database_file = 'backup_copy.db' # Path to the database file

def decrypt_file(file_path, key, chunk_size=4096):
    """
    Decrypts a file using a given encryption key.

    Args:
        file_path (str): The path to the file to be decrypted.
        key (bytes): The encryption key to use for decryption.
        chunk_size (int, optional): The size of the chunks to read from the file. Defaults to 4096.

    Yields:
        bytes: The decrypted data.
    """
    cipher_suite = Fernet(key)
    with open(file_path, 'rb') as file:
        while True:
            chunk = file.read(chunk_size)
            if len(chunk) == 0:
                break
            decrypted_chunk = cipher_suite.decrypt(chunk)
            yield decrypted_chunk

def recover_copy(source_path, destination_directory):
    """
    Decrypts and copies a backup file to a specified destination directory.

    Args:
        source_path (str): The path to the encrypted backup file.
        destination_directory (str): The path to the directory where the decrypted file will be copied.
    """
    filename = os.path.basename(source_path)
    
    # Read the encryption key from the database
    conn = sqlite3.connect(database_file)
    c = conn.cursor()
    c.execute('''
        SELECT encryption_key FROM backup_log
        WHERE filename = ?
    ''', (filename,))
    row = c.fetchone()
    conn.close()
    
    if row is None:
        print(f'Cripto key not found for file {filename}')
        return
    
    encryption_key = row[0]
    
    # Verify if destination directory exists
    if not os.path.exists(destination_directory):
        print(f'Destination directory {destination_directory} does not exist.')
        return
    
    destination_path = os.path.join(destination_directory, filename)
    
    # Decrypt and copy the file
    total_size = os.path.getsize(source_path)
    with open(destination_path, 'wb') as file:
        with tqdm(total=total_size, unit='B', unit_scale=True, desc='Decryption/copy') as pbar:
            for decrypted_chunk in decrypt_file(source_path, encryption_key):
                file.write(decrypted_chunk)
                pbar.update(len(decrypted_chunk))
    
    print(f'File decryption and copy to {destination_path} complete.')

# Parse arguments
parser = argparse.ArgumentParser(description='Decrypt and copy backup.')
parser.add_argument('source_path', help='Path of the encrypted file.')
parser.add_argument('destination_directory', help='Destination directory for the decrypted file.')
args = parser.parse_args()

# Execute the copy function
recover_copy(args.source_path, args.destination_directory)
