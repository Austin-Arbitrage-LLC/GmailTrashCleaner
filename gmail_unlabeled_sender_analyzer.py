#!/usr/bin/env python3
"""
Gmail Unlabeled Sender Analyzer - A utility to analyze unlabeled messages in Gmail inbox.

This script connects to Gmail via IMAP and scans messages in the inbox that don't have
any user-created labels. It extracts the FROM addresses and compiles a count of how
many emails there are from each sender. Results are sorted in descending order by count.

Required permissions:
- IMAP access must be enabled in Gmail settings
- If using 2FA (recommended), an App Password must be generated

Usage:
    python gmail_unlabeled_sender_analyzer.py

Author: Your Name
License: MIT
"""

import imaplib
import os
import yaml
import sys
import argparse
import re
from collections import defaultdict
from email.utils import parseaddr


class GmailUnlabeledSenderAnalyzer:
    """
    A class to manage Gmail unlabeled sender analysis operations.
    
    This class handles IMAP operations including connection management,
    message scanning, and sender analysis. It uses a configuration file
    for credentials and operational parameters.

    Attributes:
        config (dict): Configuration settings loaded from YAML file
        imap (imaplib.IMAP4_SSL): IMAP connection to Gmail, None when disconnected
    """

    def __init__(self, config_file='config.yml'):
        """
        Initialize the Gmail Unlabeled Sender Analyzer.

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

    def get_user_labels(self):
        """
        Get all user-created labels from Gmail (excluding system labels).
        
        Returns:
            set: Set of user label names
        """
        if not self.imap:
            raise ConnectionError("Not connected to Gmail")
        
        try:
            # Get all folders/labels
            status, folders = self.imap.list()
            if status != 'OK':
                return set()
            
            user_labels = set()
            for folder in folders:
                folder_str = folder.decode('utf-8')
                # Extract label name from IMAP LIST response
                parts = folder_str.split('"')
                if len(parts) >= 3:
                    label_name = parts[-2]
                    # Only include user-created labels (not system folders)
                    if not label_name.startswith('[') and label_name not in ['INBOX', 'Sent', 'Drafts', 'Trash', 'Spam']:
                        user_labels.add(label_name)
            
            return user_labels
            
        except Exception as e:
            print(f"Error getting user labels: {str(e)}")
            return set()

    def get_unlabeled_message_uids(self):
        """
        Get UIDs of messages in inbox that don't have any user labels.
        
        Returns:
            list: List of message UIDs that are unlabeled
        """
        if not self.imap:
            raise ConnectionError("Not connected to Gmail")
        
        try:
            # Select INBOX
            status, _ = self.imap.select('INBOX', readonly=True)
            if status != 'OK':
                return []
            
            # Get all user labels
            user_labels = self.get_user_labels()
            
            # Search for all messages in inbox
            status, data = self.imap.uid('SEARCH', None, 'ALL')
            if status != 'OK' or not data or not data[0]:
                return []
            
            all_uids = data[0].split()
            unlabeled_uids = []
            
            print(f"Scanning {len(all_uids)} messages for unlabeled ones...")
            
            # Check each message for user labels
            for i, uid in enumerate(all_uids):
                try:
                    # Get labels for this message
                    status, data = self.imap.uid('FETCH', uid, '(X-GM-LABELS)')
                    if status != 'OK' or not data or not isinstance(data[0], tuple):
                        continue
                    
                    # Parse labels from response
                    labels_data = data[0][1].decode('utf-8', errors='ignore')
                    # Extract labels from the response
                    labels_match = re.search(r'X-GM-LABELS \(([^)]*)\)', labels_data)
                    if labels_match:
                        labels_str = labels_match.group(1)
                        # Parse individual labels
                        message_labels = set()
                        for label in labels_str.split():
                            # Remove quotes and parentheses
                            clean_label = label.strip('"()')
                            if clean_label and clean_label not in ['\\Inbox', '\\Sent', '\\Draft', '\\Trash', '\\Spam', '\\Important', '\\Starred']:
                                message_labels.add(clean_label)
                        
                        # Check if message has any user labels
                        has_user_label = bool(message_labels & user_labels)
                        if not has_user_label:
                            unlabeled_uids.append(uid)
                    
                    # Progress indicator
                    if (i + 1) % 100 == 0:
                        print(f"Progress: {i + 1}/{len(all_uids)} messages scanned", end='\r')
                        
                except Exception as e:
                    continue
            
            print()  # New line after progress
            return unlabeled_uids
            
        except Exception as e:
            print(f"Error getting unlabeled messages: {str(e)}")
            return []

    def analyze_senders(self, message_uids):
        """
        Analyze sender addresses from the given message UIDs.
        
        Args:
            message_uids (list): List of message UIDs to analyze
            
        Returns:
            dict: Dictionary mapping sender addresses to counts
        """
        if not self.imap:
            raise ConnectionError("Not connected to Gmail")
        
        sender_counts = defaultdict(int)
        
        print(f"Analyzing senders from {len(message_uids)} unlabeled messages...")
        
        for i, uid in enumerate(message_uids):
            try:
                # Get FROM header
                status, data = self.imap.uid('FETCH', uid, '(BODY.PEEK[HEADER.FIELDS (FROM)])')
                if status != 'OK' or not data or not isinstance(data[0], tuple):
                    continue
                
                # Parse FROM header
                header_data = data[0][1].decode('utf-8', errors='ignore')
                from_match = re.search(r'From:\s*(.+)', header_data, re.IGNORECASE)
                if from_match:
                    from_field = from_match.group(1).strip()
                    # Parse email address from the FROM field
                    name, email = parseaddr(from_field)
                    
                    if email:
                        # Normalize email address (lowercase)
                        normalized_email = email.lower()
                        sender_counts[normalized_email] += 1
                
                # Progress indicator
                if (i + 1) % 50 == 0:
                    print(f"Progress: {i + 1}/{len(message_uids)} messages analyzed", end='\r')
                    
            except Exception as e:
                continue
        
        print()  # New line after progress
        return dict(sender_counts)

    def analyze_unlabeled_senders(self):
        """
        Main method to analyze unlabeled senders in the inbox.
        """
        if not self.imap:
            raise ConnectionError("Not connected to Gmail")
        
        print("Starting analysis of unlabeled messages in inbox...")
        
        # Get unlabeled message UIDs
        unlabeled_uids = self.get_unlabeled_message_uids()
        
        if not unlabeled_uids:
            print("No unlabeled messages found in inbox.")
            return
        
        print(f"Found {len(unlabeled_uids)} unlabeled messages in inbox.")
        
        # Analyze senders
        sender_counts = self.analyze_senders(unlabeled_uids)
        
        if not sender_counts:
            print("No sender information found.")
            return
        
        # Sort by count (descending)
        sorted_senders = sorted(sender_counts.items(), key=lambda x: x[1], reverse=True)
        
        # Display results
        print("\n" + "="*80)
        print("UNLABELED MESSAGE SENDERS (Descending Order)")
        print("="*80)
        
        for email, count in sorted_senders:
            print(f"{count:>6,} messages | {email}")
        
        print("="*80)
        print(f"Total unlabeled messages: {len(unlabeled_uids):,}")
        print(f"Unique senders: {len(sender_counts):,}")
        print(f"Messages from top sender: {sorted_senders[0][1]:,}")


def main():
    """
    Main function implementing the unlabeled sender analysis functionality.

    This function:
    1. Creates a GmailUnlabeledSenderAnalyzer instance
    2. Connects to Gmail
    3. Analyzes unlabeled senders in the inbox
    4. Disconnects cleanly
    """
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Analyze unlabeled message senders in Gmail inbox')
    parser.add_argument('--config', default='config.yml', help='Path to config file (default: config.yml)')
    
    args = parser.parse_args()
    
    try:
        # Initialize the Gmail unlabeled sender analyzer
        gmail = GmailUnlabeledSenderAnalyzer(args.config)
        
        # Connect to Gmail
        if gmail.connect():
            try:
                # Analyze unlabeled senders
                gmail.analyze_unlabeled_senders()
                        
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
