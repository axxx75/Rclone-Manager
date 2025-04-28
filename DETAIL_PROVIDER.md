# Rclone Configuration Guide for Personal Cloud Services

This guide explains how to configure `rclone.conf` for common personal cloud storage services, including tips on obtaining required credentials (Client ID, Client Secret, and Token).

---

## Supported Cloud Services

### 1. Google Drive (`gdrive`)
- **Type:** `drive`
- **Requirements:**  
  - Client ID and Client Secret (recommended, but optional)
  - OAuth Token

- **Notes:**
  - If you transfer more than **750 GB/day**, using your own Client ID is strongly recommended.
  - You can create a Google OAuth App at [Google Developer Console](https://console.developers.google.com/).

---

### 2. Google Photos (`gphotos`)
- **Type:** `google photos`
- **Requirements:**  
  - OAuth Token

- **Notes:**
  - Only suitable for managing photos and videos.
  - File uploads may be subject to Google's automatic compression policies.
  - Some API limitations exist for large datasets.

---

### 3. Amazon Photos (`amazon_photos`)
- **Type:** `amazon cloud drive`
- **Requirements:**  
  - Client ID and Client Secret
  - OAuth Token

- **Notes:**
  - Amazon Drive service was discontinued, but Amazon Photos still works partially.
  - Full support may require workarounds and manual token management.

---

### 4. OneDrive (`onedrive`)
- **Type:** `onedrive`
- **Requirements:**  
  - Client ID and Client Secret
  - OAuth Token

- **Notes:**
  - Works for both Personal and Business accounts.
  - Optionally specify `drive_id` for shared drives.
  - You can register an app at [Microsoft Azure Portal](https://portal.azure.com/).

---

### 5. Dropbox (`dropbox`)
- **Type:** `dropbox`
- **Requirements:**  
  - Client ID and Client Secret
  - OAuth Token

- **Notes:**
  - Easy setup.
  - Limited to around **300 GB/day** uploads with standard free API keys.
  - You can register an app at [Dropbox App Console](https://www.dropbox.com/developers/apps).

---

### 6. Mega.nz (`mega`)
- **Type:** `mega`
- **Requirements:**  
  - Username (email)
  - Password (stored encrypted)

- **Notes:**
  - Native end-to-end encryption.
  - Uploads of large files can be slower compared to other providers.

---

## General Tips

- **Always use `rclone config`** to automatically generate your remotes.
- **Never manually edit tokens** unless absolutely necessary.
- **Protect your `rclone.conf` file** as it contains sensitive authentication details.

```bash
chmod 600 ~/.config/rclone/rclone.conf
