# Red Hat OpenShift Deployment Guide

## 1. Log in and Access the OpenShift Web Console
1. Open your browser and navigate to your OpenShift console URL:  
   **[OpenShift Console](https://console.cloud.rt.nyu.edu/)**
2. Log in with your **NYU SSO credentials**.

---

## 2. Select a Project
1. In the top-left corner, click **Project** (it will show all the projects you have access to).
2. Choose an existing project.

> You will be taken to that project’s overview page, often called the **Developer Perspective**.  
> If you are in the **Administrator Perspective**, switch to **Developer Perspective** in the top-left navigation for an easier application deployment process.

---

## 3. Start the Deployment Process
Inside your project, you have multiple options to add an application:
- **Import from Git**: For source-to-image (S2I) builds using your Git repository.
- **Upload a YAML/JSON**: Directly provide OpenShift or Kubernetes resource definitions (advanced use).

Below is the most common approach: **Importing from Git**.

---

## 4. Deploy an Application from a Git Repository (Source-to-Image)
1. Click on **+Add** in the left menu.
2. Select **From Git**.
3. Enter the **Git Repository URL** of your source code (e.g., a GitHub URL).
4. OpenShift will analyze the repository to detect the language/framework (e.g., Node.js, Python, Java).
   - If it detects a **Builder Image** automatically, it will be selected in the dropdown (e.g., Docker).
   - If not, manually select the correct builder image (e.g., Node.js 14, Python 3.8).
5. Provide a **Name** for your application (e.g., `my-node-app`).
6. *(Optional)* Set advanced options like environment variables, triggers, resources, etc.
7. Under the **Deploy** section:
   - Select **Deployment** as the resource type.
   - Specify the **Target Port** number as defined in the Dockerfile (e.g., `8080`).
8. Click **Create**.

> **Result:** OpenShift will start a **Build** using the selected builder image and Git repository. Once the build is successful, it automatically deploys your new application.

---

## 5. Monitor the Build and Deployment

### **Build:**
1. Go to **Builds** (under the Builds section in the Developer or Administrator perspective).
2. You should see your build running.  
   - Click on the build name → **Logs** to view real-time logs.
3. Once the build completes successfully, it transitions to a **Complete** state.

### **Deployment:**
1. Click on **Topology** view or go to **Workloads → Deployments**.
2. You will see your new application as a **Deployment row**.
3. Ensure that the **Pods** are running. You can check pod details and logs.

---

## 6. Expose the Application (Create a Route)
To access your application externally (outside the cluster), you need to create a **Route**.

1. In the **Developer Perspective**, click **Topology** and select your application.
2. If a **Route** is not created automatically, switch to the **Administrator Perspective**.
3. Navigate to **Networking → Routes**.
4. Click **Create Route** (top-right corner).
5. Provide a **Name** and select the **Service**.
6. Leave **Hostname** blank to let OpenShift auto-generate one.
7. Click **Create**.

> **Result:** A URL will be generated (e.g., `http://my-node-app-myproject.apps.cluster.example.com`).  
> You can now access your application in a browser.

---

## 7. Manage Your Application

### **Scaling:**
1. Go to **Topology** or **Workloads → Deployments**.
2. Click on your application and adjust the number of **replicas** to scale up/down.

### **Environment Variables:**
1. In the **Deployment details**, go to **Environment Variables**.
2. Add, remove, or edit variables and save changes.
3. OpenShift will redeploy the application to apply the updates.

### **Logs & Events:**
1. In **Topology**, select the application icon.
2. Click **View Logs** or **Events** in the side panel to see logs and system events.

---

## 8. (Optional) Advanced: YAML/JSON Import
If you have your own OpenShift/Kubernetes manifests or Helm charts, you can import them directly.

1. Click **+Add → Import YAML/JSON** or **Install Helm Chart**.
2. Paste your **YAML definitions** or upload a local file.
3. Review the definitions (which might contain **Deployments, Services, Routes**, etc.).
4. Click **Create**.

---

This guide covers the **end-to-end** process of deploying an application on **OpenShift** using a Git repository. 🚀  
For advanced configurations, refer to the OpenShift documentation.
