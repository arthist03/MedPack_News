# AI Healthcare News Scraper

This is a fully automated, zero-cost Python pipeline that scrapes global healthcare news, filters it using Google Gemini AI, and pushes the best articles to your Firebase Firestore database.

## How it works
1. Runs daily at 8:00 AM IST via GitHub Actions.
2. Pulls RSS feeds for Healthcare, PMJAY, AI in Medicine, etc.
3. Uses Gemini AI to rate the articles out of 10.
4. Uploads only the top 3-5 articles (Rating 8+) to Firestore.

---

## 🛠️ Setup Instructions (Getting the Secrets)

To make this repository work, you need to add **two** secrets to your GitHub Repository settings.

### Step 1: Push this code to GitHub
1. Open your terminal in this `news_scraper` folder.
2. Run the following commands:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   ```
3. Create a new repository on GitHub and follow the instructions to push this code.

### Step 2: Add Secrets to GitHub
Go to your GitHub Repository page -> **Settings** -> **Secrets and variables** -> **Actions** -> **New repository secret**.

You need to add these two exact secrets:

#### 1. `FIREBASE_SERVICE_ACCOUNT_KEY`
*   **Where to get it:**
    1. Go to your [Firebase Console](https://console.firebase.google.com/).
    2. Open your project.
    3. Click the **Gear icon** (Project settings) -> **Service accounts**.
    4. Click **Generate new private key**.
    5. It will download a `.json` file. 
*   **How to add it:** Open that downloaded `.json` file in Notepad, copy **all** the text inside it, and paste it as the value for the `FIREBASE_SERVICE_ACCOUNT_KEY` secret.

#### 2. `GEMINI_API_KEY`
*   **Where to get it:**
    1. Go to [Google AI Studio](https://aistudio.google.com/).
    2. Sign in with your Google account.
    3. Click **Get API Key** on the left menu.
    4. Click **Create API Key**.
*   **How to add it:** Copy the generated key and paste it as the value for the `GEMINI_API_KEY` secret. (It's 100% free).

---

## 🚀 Testing it manually
Once the secrets are added, go to the **Actions** tab in your GitHub repository, click on **Daily Healthcare News Scraper** on the left, and click the **Run workflow** button to test it immediately!
