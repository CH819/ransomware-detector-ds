import os
import json
import base64
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from dotenv import load_dotenv

load_dotenv()


TEMP_DIR = os.environ.get("TEMP_DIR", "tmp")


def decrypt_files():
    # Load decryption key
    key_path = os.path.join(TEMP_DIR, "decryption_key.json")
    print(key_path)
    try:
        with open(key_path, "r") as f:
            key_data = json.load(f)
    except FileNotFoundError:
        print("decryption_key.json not found")
        return

    # Decode key (32 bytes for AES-256)
    key = base64.b64decode(key_data["decryption_key"])

    # Decrypt each file
    decrypted_count = 0
    for file_path in key_data["encrypted_files"]:
        if not os.path.exists(file_path):
            print(f"File not found: {file_path}")
            continue

        try:
            # Read encrypted data
            with open(file_path, "rb") as f:
                encrypted_data = f.read()

            # Extract IV (first 16 bytes) and ciphertext
            iv = encrypted_data[:16]
            ciphertext = encrypted_data[16:]

            # Create AES-256-CTR cipher for decryption
            cipher = Cipher(
                algorithms.AES(key),
                modes.CTR(iv),
                backend=default_backend()
            )
            decryptor = cipher.decryptor()
            decrypted_data = decryptor.update(ciphertext) + decryptor.finalize()

            # Write back decrypted data
            with open(file_path, "wb") as f:
                f.write(decrypted_data)

            # Delete ransom note
            ransom_path = file_path + ".README_TO_DECRYPT.txt"
            if os.path.exists(ransom_path):
                os.remove(ransom_path)

            print(f"Decrypted: {os.path.basename(file_path)}")
            decrypted_count += 1

        except Exception as e:
            print(f"Failed to decrypt {file_path}: {e}")

    print(f"Decrypted {decrypted_count} files")


if __name__ == "__main__":
    decrypt_files()
