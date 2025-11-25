#!/usr/bin/env python3
"""
Gmail Label Lister - A utility to list all Gmail labels with inbox message counts.

This script connects to Gmail via IMAP and lists all available labels,
showing how many messages with each label are still in the inbox.
Results are sorted in descending order by inbox message count.

Required permissions:
- IMAP access must be enabled in Gmail settings
- If using 2FA (recommended), an App Password must be generated

Usage:
    python gmail_label_lister.py

Author: Your Name
License: MIT
"""

import imaplib
import os
import yaml
import sys
import argparse
import re
import time
from collections import defaultdict


class GmailLabelLister:
    """
    A class to manage Gmail label listing operations.
    
    This class handles IMAP operations including connection management,
    folder navigation, and label counting. It uses a configuration file
    for credentials and operational parameters.

    Attributes:
        config (dict): Configuration settings loaded from YAML file
        imap (imaplib.IMAP4_SSL): IMAP connection to Gmail, None when disconnected
    """

    def __init__(self, config_file='config.yml'):
        """
        Initialize the Gmail Label Lister.

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
        Establish connection to Gmail IMAP server.

        Creates an SSL connection to Gmail's IMAP server and authenticates
        using the credentials from the configuration file.

        Returns:
            bool: True if connection successful, False otherwise

        Note:
            If using 2FA, the password should be an App Password, not
            the main Gmail password.
        """
        try:
            self.imap = imaplib.IMAP4_SSL('imap.gmail.com', 993)
            self.imap.login(self.config['email'], self.config['password'])
            return True
        except Exception as e:
            print(f"Failed to connect to Gmail: {str(e)}")
            return False
    
    def disconnect(self):
        """
        Close the IMAP connection.
        
        Safely closes the connection to Gmail's IMAP server.
        """
        if self.imap:
            try:
                self.imap.logout()
            except:
                pass
            self.imap = None

    def get_all_labels(self):
        """
        Get all available labels from Gmail.
        
        Returns:
            list: List of label names
        """
        if not self.imap:
            raise ConnectionError("Not connected to Gmail")
        
        try:
            # Get all folders/labels
            status, folders = self.imap.list()
            if status != 'OK':
                return []
            
            labels = []
            for folder in folders:
                folder_str = folder.decode('utf-8')
                # Extract label name from IMAP LIST response
                parts = folder_str.split('"')
                if len(parts) >= 3:
                    label_name = parts[-2]
                    # Skip system folders
                    if not label_name.startswith('[') and label_name not in ['INBOX', 'Sent', 'Drafts', 'Trash', 'Spam']:
                        labels.append(label_name)
            
            return labels
            
        except Exception as e:
            print(f"Error getting labels: {str(e)}")
            return []

    def count_inbox_messages_for_label(self, label_name):
        """
        Count messages with a specific label that are still in the inbox.
        Retries indefinitely until successful to handle disconnections.
        
        Args:
            label_name (str): The name of the label to count
            
        Returns:
            int: Number of messages with this label in the inbox
        """
        while True:
            try:
                # Check if we need to reconnect
                if not self.imap:
                    print(f"Reconnecting for label '{label_name}'...")
                    if not self.connect():
                        print(f"Failed to reconnect for label '{label_name}', retrying...")
                        time.sleep(5)
                        continue
                
                # Select INBOX
                status, _ = self.imap.select('INBOX', readonly=True)
                if status != 'OK':
                    print(f"Failed to select INBOX for label '{label_name}', retrying...")
                    time.sleep(2)
                    continue
                
                # Search for messages with this label in inbox
                raw_query = f'"label:{label_name} in:inbox"'
                status, data = self.imap.uid('SEARCH', None, 'X-GM-RAW', raw_query)
                
                if status == 'OK' and data and data[0]:
                    return len(data[0].split())
                else:
                    return 0
                    
            except Exception as e:
                print(f"Error counting messages for label '{label_name}': {str(e)}")
                print(f"Retrying label '{label_name}' in 5 seconds...")
                # Disconnect to force reconnection
                self.disconnect()
                time.sleep(5)
                continue

    def list_labels_with_counts(self):
        """
        List all labels with their inbox message counts, sorted by count (descending).
        """
        if not self.imap:
            raise ConnectionError("Not connected to Gmail")
        
        print("Fetching all labels...")
        labels = self.get_all_labels()
        
        if not labels:
            print("No labels found or error occurred.")
            return
        
        print(f"Found {len(labels)} labels. Counting inbox messages...")
        
        # Count messages for each label
        label_counts = []
        for i, label in enumerate(labels, 1):
            count = self.count_inbox_messages_for_label(label)
            label_counts.append((label, count))
            print(f"Progress: {i}/{len(labels)} - {label}: {count} messages", end='\r')
        
        print()  # New line after progress
        
        # Sort by count (descending)
        label_counts.sort(key=lambda x: x[1], reverse=True)
        
        # Display results
        print("\n" + "="*60)
        print("LABELS WITH INBOX MESSAGE COUNTS (Descending Order)")
        print("="*60)
        
        for label, count in label_counts:
            if count > 0:
                print(f"{count:>6,} messages | {label}")
            else:
                print(f"{count:>6,} messages | {label}")
        
        print("="*60)
        print(f"Total labels: {len(labels)}")
        print(f"Labels with inbox messages: {sum(1 for _, count in label_counts if count > 0)}")


def main():
    """
    Main function implementing the label listing functionality.

    This function:
    1. Creates a GmailLabelLister instance
    2. Connects to Gmail
    3. Lists all labels with their inbox message counts
    4. Disconnects cleanly
    """
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='List all Gmail labels with inbox message counts')
    parser.add_argument('--config', default='config.yml', help='Path to config file (default: config.yml)')
    
    args = parser.parse_args()
    
    try:
        # Initialize the Gmail label lister
        gmail = GmailLabelLister(args.config)
        
        # Connect to Gmail
        if gmail.connect():
            try:
                # List labels with counts
                gmail.list_labels_with_counts()
                        
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
