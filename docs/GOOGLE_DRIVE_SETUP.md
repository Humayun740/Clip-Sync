# Google Drive API Setup Guide (One-Time Setup ~ 3 mins)

Google Drive requires an OAuth 2.0 Client ID so your app can communicate directly with your Google account.

---

### Step 1: Create a Project in Google Cloud
1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Sign in with the Google Account you want to store your clips in.
3. Click the project dropdown at the top left and click **"New Project"**.
4. Name it `Passthru Clips` and click **Create**.

---

### Step 2: Enable Google Drive API
1. In the search bar at the top, type `Google Drive API` and select it.
2. Click **Enable**.

---

### Step 3: Configure OAuth Consent Screen
1. In the left sidebar, click **APIs & Services** > **OAuth consent screen**.
2. Select **External** and click **Create**.
3. Fill in:
   - **App name**: `Passthru`
   - **User support email**: Your email address
   - **Developer contact information**: Your email address
4. Click **Save and Continue** through "Scopes".
5. In **Test Users**, click **"+ Add Users"**, enter your Google email address, and click **Save and Continue**.

---

### Step 4: Generate `credentials.json`
1. In the left sidebar, click **Credentials**.
2. Click **"+ Create Credentials"** at the top and select **OAuth client ID**.
3. Under **Application type**, choose **Desktop app**.
4. Name: `Passthru Desktop Client`.
5. Click **Create**.
6. A popup will appear. Click **Download JSON**.
7. Rename the downloaded file to:
   ```
   credentials.json
   ```
8. Place this `credentials.json` file inside your app folder:
   ```
   C:\Users\Humayun\Desktop\passthru\credentials.json
   ```

---

### Step 5: Connect Your Account
1. Launch the app (`python main.py` or double-click `run_gui.bat`).
2. Click **"Connect Google Drive"** (or run `python main.py --sync-once`).
3. Your web browser will open asking you to sign in and grant access.
4. Click **Continue** (if you see a "Google hasn't verified this app" screen, click **Advanced** -> **Go to Passthru (unsafe)**).
5. Once authorized, a file named `token.json` is created automatically.
6. **You're done!** The app will now run silently and automatically in the background without needing your login ever again.
