#!/usr/bin/env python3
"""
Gmail Trash Cleaner - A utility to automatically clean Gmail's trash folder.

This script provides functionality to connect to a Gmail account via IMAP and
permanently delete messages from the trash folder. It includes features like:
- Batch processing to handle large numbers of messages efficiently
- Progress tracking with a progress bar
- Automatic retry mechanism for failed operations
- Continuous monitoring mode with configurable intervals
- Configurable settings via YAML config file

The script is designed to run continuously, checking the trash folder at regular
intervals and cleaning it when messages are found. It can be stopped safely
with Ctrl+C at any time.

Required permissions:
- IMAP access must be enabled in Gmail settings
- If using 2FA (recommended), an App Password must be generated

Author: Your Name
License: MIT
"""

import imaplib
import os
import yaml
import time
from tqdm import tqdm


class GmailTrashCleaner:
    """
    A class to manage Gmail trash folder cleaning operations.
    
    This class handles all IMAP operations including connection management,
    folder navigation, and message deletion. It uses a configuration file
    for credentials and operational parameters.

    Attributes:
        config (dict): Configuration settings loaded from YAML file
        imap (imaplib.IMAP4_SSL): IMAP connection to Gmail, None when disconnected
    """

    def __init__(self, config_file='config.yml'):
        """
        Initialize the Gmail Trash Cleaner.

        Args:
            config_file (str): Path to the YAML configuration file.
                             Defaults to 'config.yml' in the current directory.

        Raises:
            FileNotFoundError: If the specified config file doesn't exist.
        """
        self.config = self._load_config(config_file)
        self.imap = None
        
    def _load_config(self, config_file):
        """
        Load and validate configuration from YAML file.

        Loads the configuration file and sets default values for optional
        parameters if they're not specified in the file.

        Args:
            config_file (str): Path to the YAML configuration file

        Returns:
            dict: Configuration dictionary with all required parameters

        Raises:
            FileNotFoundError: If the config file doesn't exist
            yaml.YAMLError: If the config file is not valid YAML
        """
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"Config file {config_file} not found")
        
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
            
        # Set default values for optional parameters
        config.setdefault('batch_size', 25)  # Number of messages to process at once
        config.setdefault('max_retries', 3)  # Maximum retry attempts for failed operations
        config.setdefault('check_interval', 300)  # Seconds between trash checks (5 minutes)
        
        return config
    
    def connect(self):
        """
        Establish a secure connection to Gmail's IMAP server.

        Attempts to create an SSL connection to Gmail's IMAP server and
        authenticate using the credentials from the config file.

        Returns:
            bool: True if connection successful, False otherwise

        Note:
            If using 2FA, the password should be an App Password, not
            the main Gmail password.
        """
        try:
            self.imap = imaplib.IMAP4_SSL('imap.gmail.com')
            self.imap.login(self.config['email'], self.config['password'])
            return True
        except Exception as e:
            print(f"Connection failed: {str(e)}")
            return False
    
    def disconnect(self):
        """
        Safely close the IMAP connection.

        Attempts to logout properly, but ensures the connection is marked
        as closed even if logout fails. This prevents resource leaks and
        ensures clean shutdown.
        """
        if self.imap:
            try:
                self.imap.logout()
            except:
                # If logout fails, just set imap to None
                pass
            finally:
                self.imap = None

    def list_folders(self):
        """
        List all available folders/labels in the Gmail account.

        Retrieves and parses the list of all folders (labels in Gmail terminology)
        available in the account. Handles the special character encoding used
        by Gmail's IMAP implementation.

        Returns:
            list: List of folder names as strings

        Raises:
            ConnectionError: If not connected to Gmail
        """
        if not self.imap:
            raise ConnectionError("Not connected to Gmail")
        
        _, folders = self.imap.list()
        clean_folders = []
        for folder in folders:
            # Decode the folder name from bytes to string
            decoded = folder.decode()
            # Extract the folder name (last part after the delimiter)
            if '"/"' in decoded:
                folder_name = decoded.split('"/"')[-1].strip('" ')
            else:
                folder_name = decoded.split()[-1].strip('" ')
            clean_folders.append(folder_name)
        return clean_folders

    def get_unread_count(self, folder="INBOX"):
        """
        Get the number of unread messages in the specified folder.

        Args:
            folder (str): Name of the folder to check. Defaults to "INBOX".
                         Special characters and spaces are handled automatically.

        Returns:
            int: Number of unread messages, 0 if folder is empty or on error

        Note:
            This method properly handles folder names with spaces and special
            characters, which is common in Gmail's IMAP implementation.
        """
        if not self.imap:
            raise ConnectionError("Not connected to Gmail")
        
        try:
            # Handle folder names with spaces and special characters
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
        """
        Get the total number of messages in the specified folder.

        Args:
            folder (str): Name of the folder to check. Defaults to "INBOX".
                         Special characters and spaces are handled automatically.

        Returns:
            int: Total number of messages, 0 if folder is empty or on error

        Note:
            This method uses the SELECT response to get the message count,
            which is more efficient than searching all messages.
        """
        if not self.imap:
            raise ConnectionError("Not connected to Gmail")
        
        try:
            # Handle folder names with spaces and special characters
            folder = folder.strip('" ')
            if ' ' in folder or '[' in folder or '/' in folder:
                folder = f'"{folder}"'
            
            # Select the folder in readonly mode
            status, data = self.imap.select(folder, readonly=True)
            if status != 'OK':
                print(f"Could not select folder: {folder}")
                return 0
            
            # Get the total number directly from select response
            try:
                return int(data[0])
            except (IndexError, ValueError) as e:
                print(f"Error parsing message count: {str(e)}")
                return 0
            
        except Exception as e:
            print(f"Error getting message count for folder {folder}: {str(e)}")
            return 0

    def delete_messages_from_trash(self, total=None):
        """
        Delete messages from trash folder with progress tracking.

        This method implements the core trash cleaning functionality. It:
        - Processes messages in batches to handle large numbers efficiently
        - Shows a progress bar for visual feedback
        - Implements retry logic for failed operations
        - Handles connection drops and other errors gracefully

        Args:
            total (int, optional): Number of messages to delete. If None,
                                 will count messages in trash first.

        Note:
            The actual deletion is permanent and cannot be undone, as these
            messages are already in the trash folder.
        """
        if not self.imap:
            raise ConnectionError("Not connected to Gmail")
        
        try:
            # Select trash folder in write mode
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
                    
                    # Process messages in batches
                    message_nums = messages[0].split()[:self.config['batch_size']]
                    if not message_nums:
                        break
                    
                    # Delete messages in this batch
                    for num in message_nums:
                        retry_count = 0
                        while retry_count < self.config['max_retries']:
                            try:
                                # Mark message for deletion
                                self.imap.store(num, '+FLAGS', '\\Deleted')
                                deleted_count += 1
                                pbar.update(1)
                                break  # Success, exit retry loop
                                
                            except Exception as e:
                                retry_count += 1
                                if retry_count >= self.config['max_retries']:
                                    pbar.write(f"Error on message {num} after {self.config['max_retries']} retries: {str(e)}")
                                else:
                                    # Wait before retry and check connection
                                    time.sleep(1)
                                    try:
                                        self.imap.noop()
                                    except:
                                        # Reconnect if connection was lost
                                        if self.connect():
                                            self.imap.select('[Gmail]/Trash', readonly=False)
                
                            time.sleep(0.1)  # Small delay to prevent overwhelming the server
                    
                    # Permanently remove messages marked for deletion
                    try:
                        self.imap.expunge()
                    except Exception as e:
                        pbar.write(f"Error during expunge: {str(e)}")
                        # Attempt to reconnect and continue
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
    """
    Main function implementing the continuous cleaning loop.

    This function:
    1. Creates a GmailTrashCleaner instance
    2. Enters a continuous loop that:
       - Connects to Gmail
       - Checks trash folder
       - Deletes messages if found
       - Waits for configured interval
    3. Handles interrupts gracefully
    
    The loop continues until interrupted with Ctrl+C.
    """
    while True:  # Continuous loop
        try:
            # Initialize the Gmail trash cleaner
            gmail = GmailTrashCleaner()
            
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
            
            # Wait for configured interval before next run
            print(f"\nWaiting {gmail.config['check_interval']} seconds before next run...")
            time.sleep(gmail.config['check_interval'])
            print("\n" + "="*50 + "\n")  # Visual separator between runs
            
        except KeyboardInterrupt:
            print("\nScript stopped by user")
            break
        except Exception as e:
            print(f"\nError in main loop: {str(e)}")
            print(f"Retrying in {gmail.config['check_interval']} seconds...")
            time.sleep(gmail.config['check_interval'])


if __name__ == "__main__":
    main() 