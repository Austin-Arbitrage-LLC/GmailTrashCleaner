#!/usr/bin/env python3
"""
Gmail Label Archiver - A utility to automatically archive messages with a specific label from the inbox.

This script provides functionality to connect to a Gmail account via IMAP and
archive messages that have a specific label and are still in the inbox. It includes features like:
- Batch processing to handle large numbers of messages efficiently
- Progress tracking with a progress bar
- Automatic retry mechanism for failed operations
- Command line argument for specifying the label to archive
- Configurable settings via YAML config file

The script searches for messages in the inbox that have the specified label
and archives them (moves them out of the inbox while preserving the label).

Required permissions:
- IMAP access must be enabled in Gmail settings
- If using 2FA (recommended), an App Password must be generated

Usage:
    python gmail_label_archiver.py <label_name>

Author: Your Name
License: MIT
"""

import imaplib
import os
import yaml
import time
import sys
import argparse
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm


class GmailLabelArchiver:
    """
    A class to manage Gmail label archiving operations.
    
    This class handles all IMAP operations including connection management,
    folder navigation, and message archiving. It uses a configuration file
    for credentials and operational parameters.

    Attributes:
        config (dict): Configuration settings loaded from YAML file
        imap (imaplib.IMAP4_SSL): IMAP connection to Gmail, None when disconnected
    """

    def __init__(self, config_file='config.yml'):
        """
        Initialize the Gmail Label Archiver.

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

    def find_all_mail_folder(self):
        """
        Find the correct name for Gmail's All Mail folder.
        
        Gmail folder names can vary by locale, so we need to search for it.
        Common names are '[Gmail]/All Mail', '[Gmail]/Tous les messages', etc.
        
        Returns:
            str: The correct folder name for All Mail, or '[Gmail]/All Mail' as fallback
        """
        if not self.imap:
            raise ConnectionError("Not connected to Gmail")
        
        try:
            # List all folders to find All Mail
            _, folders = self.imap.list()
            
            for folder in folders:
                decoded = folder.decode()
                # Look for folders containing "All Mail" or similar
                if 'All Mail' in decoded or 'Tous les messages' in decoded or 'Todos los mensajes' in decoded:
                    # Extract the folder name properly
                    if '"/"' in decoded:
                        folder_name = decoded.split('"/"')[-1].strip('" ')
                    else:
                        folder_name = decoded.split()[-1].strip('" ')
                    return folder_name
            
            # Fallback to default name
            return '[Gmail]/All Mail'
            
        except Exception as e:
            print(f"Error finding All Mail folder: {str(e)}")
            return '[Gmail]/All Mail'

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

    def process_single_message(self, inbox_uid, label_name, all_mail_folder, email, app_password):
        """
        Process a single message for archiving (thread-safe with retries).
        Returns True if successfully archived, False otherwise.
        """
        max_retries = 3
        
        for attempt in range(max_retries):
            thread_imap = None
            try:
                # Create a new IMAP connection for this thread
                thread_imap = imaplib.IMAP4_SSL('imap.gmail.com', 993)
                thread_imap.login(email, app_password)
                
                # Small delay to be respectful to Gmail servers
                time.sleep(0.1)
            
                # Select INBOX first (required before FETCH)
                status, _ = thread_imap.select('INBOX', readonly=False)
                if status != 'OK':
                    continue
                
                # Get Message-ID for global identification
                status, hdr = thread_imap.uid('FETCH', inbox_uid, '(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])')
                if status != 'OK' or not hdr or not isinstance(hdr[0], tuple):
                    continue
                
                h = hdr[0][1].decode('utf-8', errors='ignore')
                m = re.search(r'Message-ID:\s*<([^>]+)>', h, re.I)
                if not m:
                    continue
                
                msgid = m.group(1)
                
                # Find the same message in All Mail
                quoted_folder = f'"{all_mail_folder}"'
                status, _ = thread_imap.select(quoted_folder, readonly=False)
                if status != 'OK':
                    continue
                
                status, data = thread_imap.uid('SEARCH', None, 'X-GM-RAW', f'"rfc822msgid:{msgid}"')
                if status != 'OK' or not data or not data[0]:
                    continue
                
                all_mail_uids = data[0].split()
                if not all_mail_uids:
                    continue
                
                all_mail_uid = all_mail_uids[0]
                
                # Remove \Inbox label from All Mail UID (canonical archive method)
                status, resp = thread_imap.uid('STORE', all_mail_uid, '-X-GM-LABELS', r'(\Inbox)')
                
                # Mark as read in All Mail
                if status == 'OK':
                    thread_imap.uid('STORE', all_mail_uid, '+FLAGS', r'(\Seen)')
                
                # Verify archiving worked by checking if still in INBOX
                status, _ = thread_imap.select('INBOX', readonly=True)
                status, data = thread_imap.uid('SEARCH', None, 'X-GM-RAW', f'"in:inbox rfc822msgid:{msgid}"')
                post_inbox = data[0].split() if data and data[0] else []
                
                if not post_inbox:
                    # Successfully archived - no longer in INBOX
                    return True
                else:
                    # Still in INBOX, try fallback UID MOVE
                    status, _ = thread_imap.select('INBOX', readonly=False)
                    status, resp = thread_imap.uid('MOVE', inbox_uid, all_mail_folder)
                    if status == 'OK':
                        # Mark as read after successful move
                        thread_imap.uid('STORE', all_mail_uid, '+FLAGS', r'(\Seen)')
                        return True
                
                # If we get here, archiving failed, try again
                continue
                
            except Exception as e:
                # Log the error but continue to retry
                if attempt == max_retries - 1:  # Last attempt
                    print(f"Failed to archive UID {inbox_uid} after {max_retries} attempts: {e}")
                continue
            finally:
                if thread_imap:
                    try:
                        thread_imap.logout()
                    except:
                        pass
            
            # Wait before retry (exponential backoff)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s delays
        
        return False

    def archive_messages_with_label(self, label_name):
        """
        Archive messages from inbox that have the specified label.

        This method implements the core archiving functionality using the working method from sanitycheck.py:
        - Finds messages in INBOX by Gmail RAW query
        - Gets their Message-ID headers for global identification
        - Locates the same messages in All Mail
        - Removes the \\Inbox label from the All Mail UID (canonical archive method)
        - Falls back to UID MOVE if needed

        Args:
            label_name (str): The name of the label to search for and archive

        Note:
            Archiving removes messages from the inbox but preserves the label.
            Messages remain accessible through the label but are no longer in the inbox.
        """
        if not self.imap:
            raise ConnectionError("Not connected to Gmail")
        
        try:
            import re
            
            # Find All Mail folder
            all_mail_folder = self.find_all_mail_folder()
            
            # 1) Find messages in INBOX with the label
            status, _ = self.imap.select('INBOX', readonly=False)
            if status != 'OK':
                print("Could not access INBOX")
                return
            
            raw_query = f'"label:{label_name} in:inbox"'
            status, data = self.imap.uid('SEARCH', None, 'X-GM-RAW', raw_query)
            if status != 'OK' or not data or not data[0]:
                print(f"No messages in INBOX with label '{label_name}'")
                return
            
            inbox_uids = data[0].split()
            total = len(inbox_uids)
            print(f"Found {total:,d} messages with label '{label_name}' in INBOX")
            
            archived = 0
            
            # Use threading to process messages in parallel (reduced workers to avoid Gmail rate limiting)
            with tqdm(total=total, desc=f"Archiving '{label_name}'", unit='msg') as pbar:
                with ThreadPoolExecutor(max_workers=3) as executor:
                    # Submit all tasks
                    future_to_uid = {
                        executor.submit(self.process_single_message, inbox_uid, label_name, all_mail_folder, self.config['email'], self.config['password']): inbox_uid 
                        for inbox_uid in inbox_uids
                    }
                    
                    # Process completed tasks
                    for future in as_completed(future_to_uid):
                        inbox_uid = future_to_uid[future]
                        try:
                            success = future.result()
                            if success:
                                archived += 1
                        except Exception as e:
                            pbar.write(f"Error processing message {inbox_uid}: {e}")
                        finally:
                            pbar.update(1)
            
            print(f"\nCompleted! Archived {archived:,d} messages with label '{label_name}'.")
            
            # Second pass: Mark any remaining unread messages with this label as read
            print(f"\nChecking for additional unread messages with label '{label_name}'...")
            try:
                # Search for unread messages with this label (anywhere, not just inbox)
                raw_query = f'"label:{label_name} is:unread"'
                status, data = self.imap.uid('SEARCH', None, 'X-GM-RAW', raw_query)
                
                if status == 'OK' and data and data[0]:
                    unread_uids = data[0].split()
                    total_unread = len(unread_uids)
                    print(f"Found {total_unread:,d} additional unread messages with label '{label_name}'")
                    
                    if total_unread > 0:
                        # Mark all unread messages with this label as read
                        # Convert bytes to strings for joining
                        uid_strings = [uid.decode() if isinstance(uid, bytes) else str(uid) for uid in unread_uids]
                        status, resp = self.imap.uid('STORE', ','.join(uid_strings), '+FLAGS', r'(\Seen)')
                        if status == 'OK':
                            print(f"Marked {total_unread:,d} additional messages as read")
                        else:
                            print(f"Failed to mark messages as read: {resp}")
                    else:
                        print("No additional unread messages found")
                else:
                    print("No additional unread messages found")
                    
            except Exception as e:
                print(f"Error checking for unread messages: {e}")
            
        except Exception as e:
            print(f"\nError archiving messages: {str(e)}")
            print(f"Successfully archived {archived:,d} messages before error")


def main():
    """
    Main function implementing the label archiving functionality.

    This function:
    1. Parses command line arguments to get the label name
    2. Creates a GmailLabelArchiver instance
    3. Connects to Gmail
    4. Archives messages with the specified label from the inbox
    5. Disconnects cleanly
    
    The script requires a label name as a command line argument.
    """
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Archive messages with a specific label from Gmail inbox')
    parser.add_argument('label', help='The label name to search for and archive')
    parser.add_argument('--config', default='config.yml', help='Path to config file (default: config.yml)')
    
    args = parser.parse_args()
    
    try:
        # Initialize the Gmail label archiver
        gmail = GmailLabelArchiver(args.config)
        
        # Connect to Gmail
        if gmail.connect():
            try:
                # Archive messages with the specified label
                gmail.archive_messages_with_label(args.label)
                        
            finally:
                # Ensure we disconnect properly
                gmail.disconnect()
        else:
            print("Failed to connect to Gmail")
            
    except KeyboardInterrupt:
        print("\nScript stopped by user")
    except Exception as e:
        print(f"\nError in main: {str(e)}")


if __name__ == "__main__":
    main()
