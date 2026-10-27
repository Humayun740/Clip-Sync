# Android Setup Guide (Automated Download & Rolling Deletion)

To make your clips automatically download to your vanilla Android phone over Wi-Fi and automatically delete when they get replaced on Google Drive, use a folder sync app that supports **Download Mirroring**.

The two recommended apps from Google Play Store are:
1. **Autosync for Google Drive (DriveSync)** (Simplest UI)
2. **FolderSync** (Highly customizable, very popular)

---

## Method 1: Using "Autosync for Google Drive (DriveSync)" (Recommended)

### Step 1: Install & Link Account
1. Open Google Play Store and install **"Autosync for Google Drive"** by MetaCtrl.
2. Open the app and connect the same Google account where your clips are uploaded.

### Step 2: Create a Synced Folder Pair
1. Go to the **Synced Folders** tab and tap **"+" (Add folder pair)**.
2. **Google Drive folder**: Select `SteelSeries_Clips`.
3. **Local folder in device**: Choose where you want clips stored on your phone (e.g., `/Internal storage/Movies/Clips` or `/DCIM/Clips`).
4. **Sync method**: Choose **"Download mirror"**
   > **Why "Download mirror"?**
   > Whenever new clips appear in Google Drive, the phone downloads them.
   > Whenever the PC script deletes an oldest clip from Google Drive to stay within the storage limit, the phone **automatically deletes that file from your phone storage** too!
5. **Sync schedule & Battery**:
   - Check **"Wi-Fi only"** (Ensures it never burns mobile cellular data).
   - (Optional) Check **"Only when charging"** (Great for nighttime syncs).
   - Set sync interval to **1 hour** or your preferred frequency.
6. Tap **Save**.

---

## Method 2: Using "FolderSync"

1. Install **FolderSync** from Google Play Store.
2. Under **Accounts**, tap **Add Account** > choose **Google Drive** and sign in.
3. Under **Folderpairs**, tap **Create Folderpair**:
   - **Account**: Your Google Drive account.
   - **Sync type**: Select **"To local folder"**.
   - **Sync deletions**: Turn **ON** (so files removed from Drive are also removed locally).
   - **Remote folder**: Select `SteelSeries_Clips`.
   - **Local folder**: Select your target folder on your phone.
   - **Connection**: Set to **"Use Wi-Fi"** only.
   - **Scheduling**: Set to run periodically or when connected to specific Wi-Fi SSIDs (e.g. Home Wi-Fi).
4. Save and turn on sync.

---

### How Your Workflow Now Operates:
1. You play a game on your PC and hit the clip hotkey on SteelSeries GG Moments.
2. The PC app detects the new clip, checks your cloud limit (e.g., 14 GB):
   - If there is free space, it uploads immediately.
   - If the cloud is full, it deletes the oldest clip(s) on Google Drive and uploads the new one.
3. Your Android phone connects to your Wi-Fi, triggers the sync:
   - Downloads the new clip(s) directly to your phone storage.
   - Automatically removes the evicted clip(s) from your phone storage.
4. When you leave for university, you have the latest clips saved locally on your phone, playable offline without using cellular data!
