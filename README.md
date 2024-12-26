# GmailTrashCleaner

A Python utility specifically designed to automatically clean up your Gmail trash folder. This tool connects to your Gmail account via IMAP and permanently deletes messages from your trash folder in batches, with progress tracking.

## Features

- Automatic connection to Gmail via IMAP
- Batch deletion of trash messages with configurable batch size
- Progress bar showing deletion status
- Automatic retry on failed operations
- Continuous monitoring mode with configurable intervals
- Fully configurable settings via YAML config file

## Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/gmail-trash-cleaner.git
cd gmail-trash-cleaner
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Copy the template config file and edit it with your credentials:
```bash
cp config.template.yml config.yml
```

4. Edit `config.yml` with your settings:
```yaml
# Gmail credentials
email: "your.email@gmail.com"
password: "your-app-specific-password"

# Cleaning settings
batch_size: 25  # Number of messages to delete in each batch
max_retries: 3  # Number of retry attempts for failed operations
check_interval: 300  # Time in seconds to wait between trash checks (300 = 5 minutes)
```

**Note:** For security, you should use an [App Password](https://support.google.com/accounts/answer/185833) instead of your main Gmail password. This requires 2-factor authentication to be enabled on your Google account.

## Usage

Simply run the script:
```bash
python gmail_trash_cleaner.py
```

The script will:
1. Connect to your Gmail account
2. Check your trash folder
3. If there are messages in trash, delete them in batches
4. Wait for the configured interval before the next check

To stop the script, press Ctrl+C.

## Configuration

All settings can be configured in `config.yml`:

- `email`: Your Gmail address
- `password`: Your Gmail App Password
- `batch_size`: Number of messages to delete in each batch (default: 25)
- `max_retries`: Number of retry attempts for failed operations (default: 3)
- `check_interval`: Time in seconds to wait between trash checks (default: 300)

## Security

- Never commit your `config.yml` file to version control
- Use App Passwords instead of your main Gmail password
- The `.gitignore` file is configured to exclude sensitive files

## License

MIT License - feel free to use and modify as needed. 