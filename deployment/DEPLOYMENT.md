# Deployment Guide

This guide explains how to set up and deploy both the frontend and backend services on your EC2 instance.

## Initial EC2 Setup (One-time)

### 1. Install Required Software

```bash
# Update system
sudo yum update -y

# Install Node.js
curl -sL https://rpm.nodesource.com/setup_18.x | sudo bash -
sudo yum install -y nodejs

# Install Python 3 and pip
sudo yum install -y python3 python3-pip

# Install Git (if not already installed)
sudo yum install -y git
```

### 2. Clone the Repository

```bash
cd /home/ec2-user
git clone https://github.com/YOUR_USERNAME/AlgoLens.git
cd AlgoLens
```

### 3. Install Dependencies

```bash
# Frontend dependencies
cd algolens-frontend
npm install
cd ..

# Backend dependencies
cd algolens-api
pip3 install -r requirements.txt
cd ..
```

### 4. Configure Environment Variables

Create a `.env` file in the `algolens-api` directory:

```bash
cd /home/ec2-user/AlgoLens/algolens-api
nano .env
```

Add your configuration:

```env
DB_HOST=13.58.153.216
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=algogators
DB_NAME=algo_data
JWT_SECRET_KEY=your-super-secret-jwt-key-change-this
```

For the frontend, create `/home/ec2-user/AlgoLens/algolens-frontend/.env` if you need to override `VITE_API_URL` or enable `VITE_DEV_MODE`.

**Important**: Generate a secure random JWT secret key. You can use:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 5. Set Up Systemd Services

```bash
# Copy service files to systemd directory
sudo cp deployment/algolens-backend.service /etc/systemd/system/
sudo cp deployment/algolens.service /etc/systemd/system/

# Edit the backend service to set a secure JWT secret
sudo nano /etc/systemd/system/algolens-backend.service
# Change: Environment="JWT_SECRET_KEY=your-secure-secret-key-change-this"
# To: Environment="JWT_SECRET_KEY=<generate-a-random-secure-key>"

# Reload systemd to recognize new services
sudo systemctl daemon-reload

# Enable services to start on boot
sudo systemctl enable algolens-backend
sudo systemctl enable algolens

# Start the services
sudo systemctl start algolens-backend
sudo systemctl start algolens
```

### 6. Verify Services are Running

```bash
# Check backend status
sudo systemctl status algolens-backend

# Check frontend status
sudo systemctl status algolens

# View backend logs
sudo journalctl -u algolens-backend -f

# View frontend logs
sudo journalctl -u algolens -f
```

## Service Management Commands

```bash
# Start services
sudo systemctl start algolens-backend
sudo systemctl start algolens

# Stop services
sudo systemctl stop algolens-backend
sudo systemctl stop algolens

# Restart services
sudo systemctl restart algolens-backend
sudo systemctl restart algolens

# View logs
sudo journalctl -u algolens-backend -f
sudo journalctl -u algolens -f
```

## Automatic Deployment

Once set up, the GitHub Actions workflow in `.github/workflows/deploy.yml` will automatically:

1. Pull the latest code from the main branch
2. Install frontend dependencies from `algolens-frontend/`
3. Build the frontend from `algolens-frontend/`
4. Install backend dependencies
5. Restart both services

This happens automatically on every push to the main branch.

## Port Configuration

- **Backend API**: Runs on port 5000
- **Frontend**: Runs on port 3000

Make sure these ports are open in your EC2 security group:
- Port 5000 (Backend API)
- Port 3000 (Frontend)
- Port 22 (SSH)

## Nginx Configuration (Optional but Recommended)

For production, it's recommended to use Nginx as a reverse proxy:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # Frontend
    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    # Backend API
    location /auth/ {
        proxy_pass http://localhost:5000/auth/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

## Troubleshooting

### Backend won't start
```bash
# Check logs
sudo journalctl -u algolens-backend -n 50

# Common issues:
# - Missing config.json file
# - Database connection failure
# - Missing Python dependencies
```

### Frontend won't start
```bash
# Check logs
sudo journalctl -u algolens -n 50

# Common issues:
# - Build failed
# - Missing node_modules
# - Port already in use
```

### Database connection issues
```bash
# Test database connection
cd /home/ec2-user/AlgoLens/algolens-api
python3 -c "from database import get_db_connection; print(get_db_connection())"
```
