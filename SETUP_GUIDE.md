# Setup Guide - Hybrid Variation Evaluation Prototype

**Date:** May 7, 2026  
**Status:** ✅ Fully Operational

This guide will get you running the complete project (frontend + backend) in minutes.

---

## 📋 Prerequisites

Before starting, ensure you have:

1. **Python 3.10 or newer** 
   - Check: `python --version`
   - Download from: https://www.python.org/downloads/

2. **Node.js 18 or newer**
   - Check: `node --version` and `npm --version`
   - Download from: https://nodejs.org/

3. **Git** (for cloning/version control)
   - Check: `git --version`
   - Download from: https://git-scm.com/

4. **Groq API Key**
   - Sign up at: https://console.groq.com
   - Create an API key in your account settings

5. **Text Editor/IDE** (recommended)
   - VS Code: https://code.visualstudio.com/
   - PyCharm: https://www.jetbrains.com/pycharm/
   - WebStorm: https://www.jetbrains.com/webstorm/

---

## ✅ Verification Checklist

Run these commands to verify prerequisites:

```bash
python --version          # Should be 3.10+
node --version            # Should be 18+
npm --version             # Should be 8+
git --version             # Should be 2+
```

Expected output:
```
Python 3.13.7
v18.17.0 or higher
8.19.0 or higher
git version 2.x.x
```

---

## 🚀 Quick Start (5 minutes)

### Step 1: Navigate to Project Directory

```bash
cd c:\Chatbot\Wickramasingha\ SP\Hybrid-Chatbot-for-Evaluation-of-Variation-Proposals
```

Or however you've cloned/downloaded the project.

### Step 2: Install Backend Dependencies

```bash
pip install -r backend/requirements.txt
```

This installs FastAPI, pandas, SQLAlchemy, and all other required packages.

**Tip:** Use a virtual environment (optional but recommended):
```bash
python -m venv venv
venv\Scripts\activate  # On Windows
source venv/bin/activate  # On Mac/Linux
pip install -r backend/requirements.txt
```

### Step 3: Configure Backend

Create or verify `backend/.env`:
```env
GROQ_API_KEY=your_groq_api_key_here
```

### Step 4: Start Backend (Terminal 1)

```bash
cd backend
python -m backend.main
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
```

**✅ Backend is ready!** Leave this terminal open.

### Step 5: Install Frontend Dependencies (Terminal 2)

```bash
cd frontend
npm install
```

This installs React, Vite, Tailwind CSS, and all frontend packages.

### Step 6: Configure Frontend

Verify `frontend/.env` exists with:
```env
VITE_API_BASE_URL=http://localhost:8000
GROQ_API_KEY=your_groq_api_key_here
```

### Step 7: Start Frontend

In the same terminal (frontend directory):

```bash
npm run dev
```

You should see:
```
VITE v7.3.1  ready in 515 ms
➜  Local:   http://localhost:5174/
```

**✅ Frontend is ready!** Keep this terminal open.

### Step 8: Open Application

Open your web browser and go to:
```
http://localhost:5174
```

---

## 🧪 Verify Everything is Working

### Test Backend Health Check

Open a new terminal and run:
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{"status": "healthy", "timestamp": "2026-05-07 12:46:58 PM"}
```

Or visit: `http://localhost:8000/health` in your browser.

### Test Frontend

In your browser, you should see:
- Clean, modern UI with gradient background
- "Welcome to Variation Evaluation" heading
- "Create New Project" button
- "My Sessions" link

---

## 🔑 Environment Variables Explained

### Backend (.env)
```env
# Required for AI-powered extraction
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxx
```

### Frontend (.env)
```env
# Points to backend API (must match where backend is running)
VITE_API_BASE_URL=http://localhost:8000

# Optional: For client-side features
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxx
```

---

## 📂 Project Structure Overview

```
project-root/
├── backend/                    # Python FastAPI backend
│   ├── main.py                # Main application
│   ├── requirements.txt        # Python dependencies
│   └── .env                   # Backend configuration
│
├── frontend/                   # React frontend
│   ├── src/                   # Source code
│   ├── package.json           # npm dependencies
│   ├── vite.config.ts         # Vite configuration
│   └── .env                   # Frontend configuration
│
├── test_data/                 # Sample files for testing
├── README.md                  # Main documentation
└── PROJECT_STATUS.md          # Project status
```

---

## 🛠️ Common Tasks

### Stop the Servers

- **Backend:** Press `Ctrl+C` in the backend terminal
- **Frontend:** Press `Ctrl+C` in the frontend terminal

### Restart Servers

1. Stop both servers (Ctrl+C)
2. In backend terminal: `python -m backend.main`
3. In frontend terminal: `npm run dev`

### Update Dependencies

```bash
# Backend
pip install -r backend/requirements.txt --upgrade

# Frontend
npm update
npm install
```

### Clear Cache & Reinstall

```bash
# Backend
pip cache purge
pip install -r backend/requirements.txt

# Frontend
rm -r node_modules package-lock.json
npm install
```

### Check API Documentation

While backend is running, visit:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

---

## 🐛 Troubleshooting

### "Cannot reach backend" error in frontend

**Problem:** Frontend shows error trying to reach backend

**Solutions:**
1. Verify backend is running: `curl http://localhost:8000/health`
2. Check `frontend/.env` has correct `VITE_API_BASE_URL`
3. Restart frontend dev server: `npm run dev`

### "ModuleNotFoundError" for Python packages

**Problem:** `ImportError: No module named 'fastapi'`

**Solutions:**
```bash
# Reinstall all dependencies
pip install -r backend/requirements.txt

# Or install individual package
pip install fastapi uvicorn
```

### "Cannot find module" for npm packages

**Problem:** `Module not found: axios` or similar

**Solutions:**
```bash
# Reinstall dependencies
npm install

# Clear cache and reinstall
npm cache clean --force
rm -r node_modules
npm install
```

### Port Already in Use

**Problem:** "Address already in use: 0.0.0.0:8000" or similar

**Solutions:**
```bash
# Find process using port 8000
netstat -ano | findstr :8000  # Windows
lsof -i :8000                  # Mac/Linux

# Kill the process (replace PID)
taskkill /PID <PID> /F         # Windows
kill -9 <PID>                  # Mac/Linux

# Or use different ports:
# Backend: Change main.py uvicorn.run(port=8001)
# Frontend: Change vite.config.ts server.port to 5175
```

### API Key Issues

**Problem:** `"InvalidRequestError: Missing or invalid API key"`

**Solutions:**
1. Get a fresh API key from https://console.groq.com
2. Update `backend/.env` with correct key
3. Restart backend server
4. Don't commit API keys to Git

---

## 📊 File Upload Testing

Once both servers are running:

1. Navigate to http://localhost:5174
2. Click "Create New Project"
3. Use sample files from `test_data/`:
   - `sample_boq.csv` - Bill of Quantities
   - `sample_rate_breakdown.csv` - Cost rates
   - `sample_schedule.csv` - Project schedule
4. Follow the FIDIC workflow to evaluate variations

---

## 🐳 Docker Alternative (Optional)

If you prefer Docker:

```bash
# Build and run with Docker
docker-compose up --build

# For subsequent runs
docker-compose up

# Stop services
docker-compose down
```

---

## ✨ Next Steps

Once everything is running:

1. **Explore the UI**
   - Navigate through Welcome, Upload, and Chat pages
   - Try uploading sample files

2. **Review API Documentation**
   - Visit http://localhost:8000/docs
   - Test endpoints with Swagger UI

3. **Read User Documentation**
   - See `USER_MANUAL.md` for detailed workflows
   - See `USER_FLOW.md` for example scenarios

4. **Test Features**
   - Create projects
   - Upload files
   - Run variations
   - Generate reports

---

## 📞 Getting Help

If you encounter issues:

1. **Check logs** - Look at terminal output for error messages
2. **Review docs** - See README.md and PROJECT_STATUS.md
3. **Verify prerequisites** - Ensure Python 3.10+, Node 18+ installed
4. **Check network** - Ensure ports 8000 and 5174 are accessible

---

## 🎉 Success Indicators

You'll know everything is working when:

✅ Backend terminal shows "Application startup complete"  
✅ Frontend terminal shows "VITE vX.X.X ready"  
✅ Browser loads http://localhost:5174 without errors  
✅ `curl http://localhost:8000/health` returns "healthy"  
✅ You can see the Welcome page with "Create New Project" button  

---

**Happy evaluating! 🚀**

Last updated: May 7, 2026
