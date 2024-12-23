import imaplib
import email
from email.header import decode_header
import os
from datetime import datetime, timedelta
import yaml
import time
from tqdm import tqdm

class GmailManager:
    def __init__(self, config_file='config.yml'):
        self.config = self._load_config(config_file)
        self.imap = None
        
    def _load_config(self, config_file):
        """Load Gmail credentials from config file"""
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"Config file {config_file} not found")
        
        with open(config_file, 'r') as f:
            return yaml.safe_load(f)
    
    def connect(self):
        """Establish connection to Gmail IMAP server"""
        try:
            self.imap = imaplib.IMAP4_SSL('imap.gmail.com')
            self.imap.login(self.config['email'], self.config['password'])
            return True
        except Exception as e:
            print(f"Connection failed: {str(e)}")
            return False
    
    def disconnect(self):
        """Safely close the IMAP connection"""
        if self.imap:
            try:
                self.imap.logout()
            except:
                # If logout fails, just set imap to None
                pass
            finally:
                self.imap = None

    def list_folders(self):
        """List all available folders/labels in the Gmail account"""
        if not self.imap:
            raise ConnectionError("Not connected to Gmail")
        
        _, folders = self.imap.list()
        clean_folders = []
        for folder in folders:
            # Decode the folder name
            decoded = folder.decode()
            # Extract the folder name (last part after the delimiter)
            if '"/"' in decoded:
                folder_name = decoded.split('"/"')[-1].strip('" ')
            else:
                folder_name = decoded.split()[-1].strip('" ')
            clean_folders.append(folder_name)
        return clean_folders

    def get_unread_count(self, folder="INBOX"):
        """Get the number of unread messages in the specified folder"""
        if not self.imap:
            raise ConnectionError("Not connected to Gmail")
        
        try:
            # Handle folder names with spaces and special characters
            # Remove any existing quotes first
            folder = folder.strip('" ')
            if ' ' in folder or '[' in folder or '/' in folder:
                folder = f'"{folder}"'
            
            # Select the folder
            status, _ = self.imap.select(folder)
            if status != 'OK':
                print(f"Could not select folder: {folder}")
                return 0
            
            # Search for unread messages
            status, messages = self.imap.search(None, 'UNSEEN')
            if status != 'OK':
                return 0
            
            if messages[0]:
                return len(messages[0].split())
            return 0
        except Exception as e:
            print(f"Error getting unread count for folder {folder}: {str(e)}")
            return 0

    def get_total_messages(self, folder="INBOX"):
        """Get the total number of messages in the specified folder"""
        if not self.imap:
            raise ConnectionError("Not connected to Gmail")
        
        try:
            # Handle folder names with spaces and special characters
            folder = folder.strip('" ')
            if ' ' in folder or '[' in folder or '/' in folder:
                folder = f'"{folder}"'
            
            # Select the folder
            status, data = self.imap.select(folder, readonly=True)
            if status != 'OK':
                print(f"Could not select folder: {folder}")
                return 0
            
            # Get the total number directly from select response
            # The select command returns [b'exists_count']
            try:
                return int(data[0])
            except (IndexError, ValueError) as e:
                print(f"Error parsing message count: {str(e)}")
                return 0
            
        except Exception as e:
            print(f"Error getting message count for folder {folder}: {str(e)}")
            return 0

    def delete_messages_from_trash(self, batch_size=25, total=None, max_retries=3):
        """Delete messages from trash one by one with progress updates"""
        if not self.imap:
            raise ConnectionError("Not connected to Gmail")
        
        try:
            # Select trash folder
            status, data = self.imap.select('[Gmail]/Trash', readonly=False)
            if status != 'OK':
                print("Could not access trash folder")
                return
            
            if total is None:
                total = int(data[0])
            
            if total == 0:
                print("Trash is already empty")
                return
            
            print(f"Found {total:,d} messages to delete...")
            deleted_count = 0
            
            # Create progress bar for overall deletion
            with tqdm(total=total, desc="Deleting messages", unit='msg') as pbar:
                while True:
                    # Search for ALL messages in trash
                    status, messages = self.imap.search(None, 'ALL')
                    if status != 'OK' or not messages[0]:
                        break
                    
                    message_nums = messages[0].split()[:batch_size]
                    if not message_nums:
                        break
                    
                    # Delete messages in this batch
                    for num in message_nums:
                        retry_count = 0
                        while retry_count < max_retries:
                            try:
                                self.imap.store(num, '+FLAGS', '\\Deleted')
                                deleted_count += 1
                                pbar.update(1)
                                break  # Success, exit retry loop
                                
                            except Exception as e:
                                retry_count += 1
                                if retry_count >= max_retries:
                                    pbar.write(f"Error on message {num} after {max_retries} retries: {str(e)}")
                                else:
                                    time.sleep(1)  # Wait before retry
                                    try:
                                        self.imap.noop()
                                    except:
                                        if self.connect():
                                            self.imap.select('[Gmail]/Trash', readonly=False)
                
                            time.sleep(0.1)
                    
                    # Expunge after each batch
                    try:
                        self.imap.expunge()
                    except Exception as e:
                        pbar.write(f"Error during expunge: {str(e)}")
                        if self.connect():
                            self.imap.select('[Gmail]/Trash', readonly=False)
                    
                    # Check if we've deleted everything
                    if deleted_count >= total:
                        break
            
            print(f"\nCompleted! Deleted {deleted_count:,d} messages from trash.")
            
        except Exception as e:
            print(f"\nError deleting messages: {str(e)}")
            print(f"Successfully deleted {deleted_count:,d} messages before error")

def main():
    """Main function to demonstrate Gmail manager usage"""
    while True:  # Continuous loop
        try:
            # Initialize the Gmail manager
            gmail = GmailManager()
            
            # Connect to Gmail
            if gmail.connect():
                try:
                    # Get initial trash count
                    trash_count = gmail.get_total_messages('[Gmail]/Trash')
                    if trash_count > 0:
                        print(f"You have {trash_count:,d} messages in your trash")
                        gmail.delete_messages_from_trash(total=trash_count)
                    else:
                        print("Your trash is empty")
                            
                finally:
                    # Ensure we disconnect properly
                    gmail.disconnect()
            else:
                print("Failed to connect to Gmail")
            
            # Wait 5 minutes before next run
            print("\nWaiting 5 minutes before next run...")
            time.sleep(300)  # 300 seconds = 5 minutes
            print("\n" + "="*50 + "\n")  # Visual separator between runs
            
        except KeyboardInterrupt:
            print("\nScript stopped by user")
            break
        except Exception as e:
            print(f"\nError in main loop: {str(e)}")
            print("Retrying in 5 minutes...")
            time.sleep(300)

if __name__ == "__main__":
    main()