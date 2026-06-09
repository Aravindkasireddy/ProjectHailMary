# Provisioning your Google Compute Engine VM Instance

Follow these steps in the Google Cloud Console to create the VM where your job search application will run.

---

### Step 1: Navigate to Compute Engine
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Select your newly created project from the top drop-down.
3. In the left menu, select **Compute Engine** -> **VM Instances**.
4. (If prompted) Click **Enable Compute Engine API** and wait 1-2 minutes.

---

### Step 2: Create a VM Instance
1. Click **Create Instance**.
2. **Name:** `jobsearch-dashboard`
3. **Region:** Choose a region close to you (e.g. `us-central1` or `us-east1`).
4. **Machine Configuration:**
   * **Series:** `E2`
   * **Machine type:** `e2-medium` (2 vCPUs, 4 GB memory) or `e2-small` (2 vCPUs, 2 GB memory).
     * *Note: e2-medium is recommended for compiling the Next.js frontend and running local vector match scripts smoothly.*
5. **Boot Disk (OS & Size):**
   * Click **Change** to configure the OS:
     * **Operating System:** `Ubuntu`
     * **Version:** `Ubuntu 22.04 LTS` (or `Ubuntu 24.04 LTS`)
     * **Boot disk type:** `Balanced Persistent Disk`
     * **Size:** `20 GB` (plenty of room for cache files and Docker logs).
   * Click **Select**.
6. **Firewall (CRITICAL):**
   * Check **Allow HTTP traffic**.
   * Check **Allow HTTPS traffic**.
     * *This opens port 80 and 443 so your domain can access Nginx and Certbot.*
7. Click **Create** at the bottom.

---

### Step 3: Reserve a Static External IP Address
GCP instances are assigned ephemeral IPs by default, meaning the IP changes when the instance restarts. We need to lock it to a static IP so your domain stays connected.

1. In the top search bar of the Cloud Console, search for **External IP addresses** (under VPC Network).
2. You will see your VM `jobsearch-dashboard` in the list with an `Ephemeral` IP.
3. Click the type drop-down or actions and change it to **Static**.
4. Give it a name (e.g., `jobsearch-static-ip`) and click **Reserve**.
5. Copy this **External IP Address** (e.g. `34.123.45.67`). You will need this for the Squarespace DNS setup next!

---

### Step 4: Access your VM via SSH
1. Go back to **Compute Engine** -> **VM instances**.
2. In the list, click the **SSH** button next to your `jobsearch-dashboard` instance.
3. A browser window will open, logging you directly into the terminal of your VM.

---

### Step 5: Transfer Code & Run Setup Script
Once logged into your VM:
1. Clone your repository:
   ```bash
   git clone https://github.com/your-username/Gemini-jobsearch.git
   cd Gemini-jobsearch
   ```
2. Make the setup script executable and run it:
   ```bash
   chmod +x deploy/setup_gce.sh
   ./deploy/setup_gce.sh
   ```
3. Follow the instructions printed at the end of the script to set up your `.env` file and launch!
