import os
import json
import base64
from cryptography.fernet import Fernet

def decrypt_files():
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Load decryption key
    key_path = os.path.join(script_dir, 'decryption_key.json')
    try:
        with open(key_path, 'r') as f:
            key_data = json.load(f)
    except FileNotFoundError:
        print("decryption_key.json not found")
        return
    
    # Initialize cipher
    key = base64.b64decode(key_data['decryption_key'])
    cipher = Fernet(key)
    
    # Decrypt each file
    decrypted_count = 0
    for file_path in key_data['encrypted_files']:
        if not os.path.exists(file_path):
            print(f"File not found: {file_path}")
            continue
            
        try:
            # Read encrypted data
            with open(file_path, 'rb') as f:
                encrypted_data = f.read()
            
            # Decrypt
            decrypted_data = cipher.decrypt(encrypted_data)
            
            # Write back decrypted data
            with open(file_path, 'wb') as f:
                f.write(decrypted_data)
            
            # Delete ransom note
            ransom_path = file_path + '.README_TO_DECRYPT.txt'
            if os.path.exists(ransom_path):
                os.remove(ransom_path)
            
            print(f"Decrypted: {os.path.basename(file_path)}")
            decrypted_count += 1
            
        except Exception as e:
            print(f"Failed to decrypt {file_path}: {e}")
    
    print(f"Decrypted {decrypted_count} files")

if __name__ == "__main__":
    decrypt_files()