#!/usr/bin/env python3
r"""
Sanity check for Gmail IMAP archiving (works across mailboxes):
- Finds one message in INBOX by Gmail RAW: in:inbox label:<LABEL>
- Gets its RFC822 Message-ID (global id)
- Shows INBOX presence via RAW rfc822msgid:<id>
- Locates the SAME message in All Mail (mailbox-local UIDs differ!)
- Removes \\Inbox from the All Mail UID (canonical archive), verifies disappearance
- If Gmail still reports it in INBOX, falls back to UID MOVE to [Gmail]/All Mail
"""

import imaplib, argparse, sys, re

# --- EDIT THESE ---
EMAIL = "lambchopdc@gmail.com"
APP_PASSWORD = "cjcfzriodklmlcwa"  # 16-char app password
# ------------------

def die(msg): print(msg); sys.exit(1)

def connect():
    M = imaplib.IMAP4_SSL('imap.gmail.com')
    M.login(EMAIL, APP_PASSWORD)
    return M

def select_box(M, box, ro=False):
    typ, _ = M.select(box, readonly=ro)
    if typ != 'OK':
        die(f'Cannot select {box} ({typ})')

def uid_search_raw(M, raw):
    typ, data = M.uid('SEARCH', None, 'X-GM-RAW', f'"{raw}"')
    if typ != 'OK': die(f'UID SEARCH failed for RAW: {raw}')
    return data[0].split() if data and data[0] else []

def uid_fetch_msgid(M, uid):
    typ, hdr = M.uid('FETCH', uid, '(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])')
    if typ == 'OK' and hdr and isinstance(hdr[0], tuple):
        h = hdr[0][1].decode('utf-8', errors='ignore')
        m = re.search(r'Message-ID:\s*<([^>]+)>', h, re.I)
        return m.group(1) if m else None
    return None

def uid_fetch_labels(M, uid):
    return M.uid('FETCH', uid, '(X-GM-LABELS)')

def find_all_mail(M):
    typ, boxes = M.list()
    if typ != 'OK' or not boxes: return '"[Gmail]/All Mail"'
    for b in boxes:
        line = b.decode('utf-8', errors='ignore')
        if r'\All' in line or r'\AllMail' in line:
            parts = [p for p in line.split('"') if p]
            return f'"{parts[-1]}"'
    return '"[Gmail]/All Mail"'

def norm_uid(u): return u.decode() if isinstance(u, (bytes, bytearray)) else str(u)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--label', required=True, help='Exact Gmail label to target')
    args = ap.parse_args()

    M = connect()

    # 1) INBOX candidates by label
    select_box(M, 'INBOX', ro=False)
    inb_uids = uid_search_raw(M, f'in:inbox label:{args.label}')
    if not inb_uids: die(f'No INBOX messages for label:{args.label}')
    inb_uid = inb_uids[0]
    print('INBOX UID:', inb_uid)

    # 2) Global identifier (RFC822 Message-ID)
    msgid = uid_fetch_msgid(M, inb_uid)
    if not msgid: die('Could not read Message-ID header')
    print('Message-ID:', msgid)

    # 3) Prove it’s in INBOX (canonical)
    pre_inbox = uid_search_raw(M, f'in:inbox rfc822msgid:{msgid}')
    print('INBOX RAW rfc822msgid (pre):', pre_inbox)

    # 4) Find real All Mail mailbox and locate same message there
    all_mail = find_all_mail(M)
    select_box(M, all_mail, ro=False)              # RW on All Mail
    am_uids = uid_search_raw(M, f'rfc822msgid:{msgid}')
    if not am_uids: die('Message not found in All Mail (by rfc822msgid)')
    am_uid = am_uids[0]
    print('All Mail UID:', am_uid)

    # 5) Show labels in All Mail BEFORE
    st, labels_before = uid_fetch_labels(M, am_uid)
    print('All Mail labels (before):', labels_before)

    # 6) Canonical archive: remove \Inbox on the All Mail UID
    st, resp = M.uid('STORE', am_uid, '-X-GM-LABELS', r'(\Inbox)')
    print('ALL MAIL STORE -X-GM-LABELS (\\Inbox):', st, resp)

    # 7) Verify from INBOX via RAW rfc822msgid
    select_box(M, 'INBOX', ro=True)
    post_inbox = uid_search_raw(M, f'in:inbox rfc822msgid:{msgid}')
    print('INBOX RAW rfc822msgid (post STORE):', post_inbox, '(empty means archived)')

    # 8) Show labels in All Mail AFTER
    select_box(M, all_mail, ro=True)
    st, labels_after = uid_fetch_labels(M, am_uid)
    print('All Mail labels (after):', labels_after)

    # 9) Fallback: if still in INBOX, do UID MOVE from INBOX
    if post_inbox and post_inbox[0]:
        print('Still in INBOX; attempting UID MOVE to All Mail as fallback...')
        select_box(M, 'INBOX', ro=False)
        st, mv = M.uid('MOVE', inb_uid, norm_uid(all_mail).strip('"'))
        print('UID MOVE result:', st, mv)

        # Re-verify
        select_box(M, 'INBOX', ro=True)
        post_move = uid_search_raw(M, f'in:inbox rfc822msgid:{msgid}')
        print('INBOX RAW rfc822msgid (post MOVE):', post_move)

        select_box(M, all_mail, ro=True)
        st, labels_after_move = uid_fetch_labels(M, am_uid)
        print('All Mail labels (post MOVE):', labels_after_move)

    M.logout()

if __name__ == '__main__':
    main()
