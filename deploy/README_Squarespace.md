# Configuring DNS for `arkfarms.store` in Squarespace

Follow these instructions in your Squarespace account to point your domain name to your new GCP virtual machine.

---

### Step 1: Access your Domain Settings
1. Log into your [Squarespace Account](https://account.squarespace.com/).
2. Select your domain `arkfarms.store` from the Dashboard.
3. Click on **DNS** (or **DNS Settings**).

---

### Step 2: Configure Custom DNS Records
Delete default/parking records and add custom records pointing to your GCP VM's static external IP address (e.g. `34.123.45.67`).

Add the following two records:

| Type | Host / Name | IP Address / Value | TTL | Note |
|---|---|---|---|---|
| **A** | `@` | *[Your GCE External IP Address]* | Default (1 Hour) | Directs `arkfarms.store` to your VM |
| **A** | `www` | *[Your GCE External IP Address]* | Default (1 Hour) | Directs `www.arkfarms.store` to your VM |

*Alternatively, you can configure `www` as a CNAME pointing to `arkfarms.store`, but creating two A records is fully supported and recommended for Certbot compatibility.*

---

### Step 3: Wait for DNS Propagation
* DNS updates typically propagate in 5 to 15 minutes, though in rare cases it can take up to 24 hours globally.
* You can check if the mapping is active by opening terminal on your Mac and running:
  ```bash
  ping arkfarms.store
  ```
  It should print response packets returned from your GCE Static IP address.

---

### Step 4: Run the SSL Setup
Once the ping resolves successfully to your GCE IP, execute the SSL generation step on your VM (automatic if you ran the GCE setup script, or run: `sudo certbot --nginx -d arkfarms.store -d www.arkfarms.store`).
