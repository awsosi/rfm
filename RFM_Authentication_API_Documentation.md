# RFM Authentication API - Technical Documentation

## Overview

The RFM Authentication API provides remote authentication for PolkaSQL system users within the RFM application (https://ff.vitkac.local). The API returns JSON responses and supports case-insensitive usernames and passwords.

**Version:** 1.0  
**Date:** 2025-02-05  
**Database:** SQL Anywhere 17 (WATCOMSQL dialect)

---

## Table of Contents

1. [Endpoint Information](#endpoint-information)
2. [API Responses](#api-responses)
3. [Authentication Flow](#authentication-flow)
4. [Security Considerations](#security-considerations)
5. [Implementation Guide](#implementation-guide)
6. [Database Schema](#database-schema)
7. [Code Examples](#code-examples)
8. [Testing](#testing)
9. [Troubleshooting](#troubleshooting)

---

## Endpoint Information

### Base URL

```
GET http://{server}/RFM_Auth
```

### Query String Parameters

| Parameter | Type | Length | Required | Description |
|-----------|------|--------|----------|-------------|
| `ApiKey` | string | 30 | **Yes** | API key for request authorization |
| `UserName` | string | 10 | **Yes** | Username (case-insensitive) |
| `Password` | string | 10 | **Yes** | User password (case-insensitive) |

### Example Request

```http
GET http://polkaserver.local/RFM_Auth?ApiKey=SecureUUID1&UserName=john&Password=MyPass123
```

### Request Headers

```http
Accept: application/json
```

---

## API Responses

All responses return HTTP status `200 OK` with JSON payload.

### Successful Authentication

```json
{
  "success": true,
  "authenticated": true,
  "error": null,
  "user_id": 123,
  "username": "john"
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | Whether the API call succeeded technically |
| `authenticated` | boolean | Whether the user was successfully authenticated |
| `error` | string/null | Error message if any, null on success |
| `user_id` | integer | Employee ID in the PolkaSQL system (workers.indeks) |
| `username` | string | Username as provided in request |

### Failed Authentication

```json
{
  "success": true,
  "authenticated": false,
  "error": "Invalid username or password"
}
```

### API Error (Invalid Key)

```json
{
  "success": false,
  "authenticated": false,
  "error": "Invalid or missing API key"
}
```

### Error Codes Reference

| Code | Error Message | Description | HTTP Status |
|------|---------------|-------------|-------------|
| AUTH_001 | `Invalid or missing API key` | Missing or invalid API key | 200 |
| AUTH_002 | `Username is required` | Username parameter not provided | 200 |
| AUTH_003 | `Password is required` | Password parameter not provided | 200 |
| AUTH_004 | `Invalid username or password` | Invalid credentials | 200 |
| AUTH_005 | `User account is not active` | User account is deactivated | 200 |
| AUTH_006 | `User does not have access` | User has blocked access flag | 200 |

---

## Authentication Flow

### Validation Steps (in order)

1. **API Key Validation**
   - Checks if ApiKey is not null/empty
   - Validates against whitelist: `['SecureUUID1', 'SecureUUID2']`
   - Returns error if invalid

2. **Parameter Validation**
   - Checks if UserName is provided
   - Checks if Password is provided
   - Returns error if either is missing

3. **Password Normalization**
   - Converts password to UPPERCASE for case-insensitive comparison
   - `v_password_normalized = UPPER(Password)`

4. **User Lookup (Case-Insensitive)**
   - Queries `polka27.workers` table
   - Uses `UPPER(id_i_) = UPPER(UserName)` for case-insensitive match
   - Returns error if user not found

5. **Account Status Check**
   - Verifies `Dezakt_r` field
   - Account must be active (date = '1900-01-01')
   - Returns error if deactivated

6. **Access Permission Check**
   - Calls `polka27.PL_CheckProperty('mPolka: blokada logowania', 6, v_worker_id)`
   - Returns error if access is blocked

7. **Password Verification**
   - Calls `Polka27.PL_IfPwdIsOk(v_password_normalized, v_worker_id)`
   - Returns error if password doesn't match

8. **Success Response**
   - Returns authenticated response with user_id and username

### Flow Diagram

```
┌─────────────────┐
│  HTTP Request   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Validate API   │
│      Key        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Validate       │
│  Parameters     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Normalize      │
│  Password       │
│  (UPPERCASE)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Find User      │
│ (case-insen.)   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Check Account  │
│     Status      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Check Access   │
│   Permissions   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Verify         │
│   Password      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Return Success  │
│   Response      │
└─────────────────┘
```

---

## Security Considerations

### ⚠️ Critical Security Notes

1. **Case-Insensitive Passwords**
   - Both username and password are case-insensitive
   - This reduces password entropy significantly
   - Acceptable only for internal network use with additional security layers
   - **NOT recommended for internet-facing applications**

2. **Password Normalization**
   - Passwords are converted to UPPERCASE before verification
   - Assumes passwords in database are stored as UPPERCASE
   - If database uses LOWERCASE, change `UPPER()` to `LOWER()` in procedure

3. **API Key Management**
   - Default keys (`SecureUUID1`, `SecureUUID2`) must be changed
   - Generate strong UUID v4 keys for production
   - Store API keys securely (environment variables, secrets manager)

### Security Recommendations

#### 1. HTTPS Only

```nginx
# Nginx configuration example
server {
    listen 443 ssl;
    server_name polkaserver.local;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location /RFM_Auth {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name polkaserver.local;
    return 301 https://$server_name$request_uri;
}
```

#### 2. IP Whitelisting

```nginx
# Nginx: Allow only specific IPs
location /RFM_Auth {
    allow 192.168.1.100;  # RFM server
    allow 192.168.1.101;  # Backup server
    deny all;
    
    proxy_pass http://localhost:8080;
}
```

#### 3. Rate Limiting

```nginx
# Nginx: Rate limiting
http {
    limit_req_zone $binary_remote_addr zone=auth_limit:10m rate=10r/m;
    
    server {
        location /RFM_Auth {
            limit_req zone=auth_limit burst=5;
            proxy_pass http://localhost:8080;
        }
    }
}
```

#### 4. API Key Rotation

```sql
-- Update API keys in procedure
ALTER PROCEDURE "Polka27"."RFM_sp_Auth" ...
-- Change this line:
IF ApiKey NOT IN ('NewSecureUUID1', 'NewSecureUUID2') THEN
```

Generate new UUIDs:
```bash
# Linux/Mac
uuidgen

# Node.js
node -e "console.log(require('crypto').randomUUID())"

# Python
python3 -c "import uuid; print(uuid.uuid4())"
```

---

## Implementation Guide

### Node.js/Express Backend

#### 1. Environment Configuration

Create `.env` file:

```bash
# .env
POLKA_API_URL=https://polkaserver.local/RFM_Auth
POLKA_API_KEY=YourSecureUUID1
DATABASE_URL=postgresql://user:pass@localhost:5432/rfm_db
SESSION_SECRET=your-session-secret-here
```

#### 2. Authentication Service

```javascript
// services/polkaAuth.js

const axios = require('axios');

class PolkaAuthService {
  constructor() {
    this.apiUrl = process.env.POLKA_API_URL;
    this.apiKey = process.env.POLKA_API_KEY;
  }

  /**
   * Authenticate user against PolkaSQL database
   * @param {string} username - Username (case-insensitive)
   * @param {string} password - Password (case-insensitive)
   * @returns {Promise<Object>} Authentication result
   */
  async authenticate(username, password) {
    try {
      const params = new URLSearchParams({
        ApiKey: this.apiKey,
        UserName: username,
        Password: password
      });

      const response = await axios.get(`${this.apiUrl}?${params}`, {
        headers: {
          'Accept': 'application/json'
        },
        timeout: 5000 // 5 second timeout
      });

      const data = response.data;

      if (!data.success) {
        return {
          success: false,
          error: data.error || 'API call failed'
        };
      }

      if (!data.authenticated) {
        return {
          success: false,
          authenticated: false,
          error: data.error || 'Authentication failed'
        };
      }

      return {
        success: true,
        authenticated: true,
        userId: data.user_id,
        username: data.username
      };

    } catch (error) {
      console.error('Polka authentication error:', error.message);
      
      if (error.code === 'ECONNABORTED') {
        return {
          success: false,
          error: 'Authentication service timeout'
        };
      }

      if (error.response) {
        return {
          success: false,
          error: `HTTP ${error.response.status}: ${error.response.statusText}`
        };
      }

      return {
        success: false,
        error: 'Network error or service unavailable'
      };
    }
  }

  /**
   * Validate API key format (before sending request)
   * @param {string} apiKey - API key to validate
   * @returns {boolean} Whether key format is valid
   */
  static isValidApiKeyFormat(apiKey) {
    // UUID v4 format validation
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
    return uuidRegex.test(apiKey);
  }
}

module.exports = new PolkaAuthService();
```

#### 3. User Management Service

```javascript
// services/userService.js

const { db } = require('../database');

class UserService {
  /**
   * Find or create RFM user based on Polka authentication
   * @param {number} polkaUserId - Polka worker ID
   * @param {string} username - Username
   * @returns {Promise<Object>} RFM user object
   */
  async findOrCreateUser(polkaUserId, username) {
    // Check if user exists in RFM database
    let user = await db.users.findOne({
      where: { polka_user_id: polkaUserId }
    });

    if (!user) {
      // Create new RFM user
      user = await db.users.create({
        polka_user_id: polkaUserId,
        username: username.toLowerCase(), // Store lowercase in RFM
        created_at: new Date(),
        last_login: new Date(),
        is_active: true
      });

      console.log(`Created new RFM user: ${username} (Polka ID: ${polkaUserId})`);
    } else {
      // Update last login
      await db.users.update(
        { last_login: new Date() },
        { where: { id: user.id } }
      );
    }

    return user;
  }

  /**
   * Create session for authenticated user
   * @param {number} userId - RFM user ID
   * @returns {Promise<Object>} Session object with token
   */
  async createSession(userId) {
    const crypto = require('crypto');
    const token = crypto.randomBytes(32).toString('hex');
    const expiresAt = new Date();
    expiresAt.setHours(expiresAt.getHours() + 24); // 24 hour session

    const session = await db.sessions.create({
      user_id: userId,
      token: token,
      created_at: new Date(),
      expires_at: expiresAt,
      active: true
    });

    return session;
  }

  /**
   * Validate session token
   * @param {string} token - Session token
   * @returns {Promise<Object|null>} User object if valid, null otherwise
   */
  async validateSession(token) {
    const session = await db.sessions.findOne({
      where: {
        token: token,
        active: true
      },
      include: [{
        model: db.users,
        where: { is_active: true }
      }]
    });

    if (!session) {
      return null;
    }

    // Check if expired
    if (session.expires_at < new Date()) {
      await db.sessions.update(
        { active: false },
        { where: { id: session.id } }
      );
      return null;
    }

    return session.user;
  }

  /**
   * Invalidate session (logout)
   * @param {string} token - Session token
   */
  async invalidateSession(token) {
    await db.sessions.update(
      { active: false },
      { where: { token: token } }
    );
  }
}

module.exports = new UserService();
```

#### 4. Authentication Controller

```javascript
// controllers/authController.js

const polkaAuth = require('../services/polkaAuth');
const userService = require('../services/userService');

class AuthController {
  /**
   * Login endpoint
   * POST /api/auth/login
   */
  async login(req, res) {
    try {
      const { username, password } = req.body;

      // Validate input
      if (!username || !password) {
        return res.status(400).json({
          success: false,
          error: 'Username and password are required'
        });
      }

      // Authenticate with PolkaSQL
      const authResult = await polkaAuth.authenticate(username, password);

      if (!authResult.success || !authResult.authenticated) {
        return res.status(401).json({
          success: false,
          error: authResult.error || 'Invalid credentials'
        });
      }

      // Find or create user in RFM database
      const rfmUser = await userService.findOrCreateUser(
        authResult.userId,
        authResult.username
      );

      // Create session
      const session = await userService.createSession(rfmUser.id);

      // Return session token
      return res.json({
        success: true,
        user: {
          id: rfmUser.id,
          username: rfmUser.username,
          polka_user_id: rfmUser.polka_user_id
        },
        session: {
          token: session.token,
          expires_at: session.expires_at
        }
      });

    } catch (error) {
      console.error('Login error:', error);
      return res.status(500).json({
        success: false,
        error: 'Internal server error'
      });
    }
  }

  /**
   * Logout endpoint
   * POST /api/auth/logout
   */
  async logout(req, res) {
    try {
      const token = req.headers['x-session-token'] || req.cookies.sessionToken;

      if (token) {
        await userService.invalidateSession(token);
      }

      return res.json({
        success: true,
        message: 'Logged out successfully'
      });

    } catch (error) {
      console.error('Logout error:', error);
      return res.status(500).json({
        success: false,
        error: 'Internal server error'
      });
    }
  }

  /**
   * Get current user endpoint
   * GET /api/auth/me
   */
  async getCurrentUser(req, res) {
    try {
      // User is already attached by auth middleware
      return res.json({
        success: true,
        user: {
          id: req.user.id,
          username: req.user.username,
          polka_user_id: req.user.polka_user_id,
          created_at: req.user.created_at,
          last_login: req.user.last_login
        }
      });

    } catch (error) {
      console.error('Get current user error:', error);
      return res.status(500).json({
        success: false,
        error: 'Internal server error'
      });
    }
  }
}

module.exports = new AuthController();
```

#### 5. Authentication Middleware

```javascript
// middleware/auth.js

const userService = require('../services/userService');

/**
 * Authentication middleware
 * Validates session token and attaches user to request
 */
async function authMiddleware(req, res, next) {
  try {
    // Get token from header or cookie
    const token = req.headers['x-session-token'] || req.cookies.sessionToken;

    if (!token) {
      return res.status(401).json({
        success: false,
        error: 'No session token provided'
      });
    }

    // Validate session
    const user = await userService.validateSession(token);

    if (!user) {
      return res.status(401).json({
        success: false,
        error: 'Invalid or expired session'
      });
    }

    // Attach user to request
    req.user = user;
    next();

  } catch (error) {
    console.error('Auth middleware error:', error);
    return res.status(500).json({
      success: false,
      error: 'Internal server error'
    });
  }
}

/**
 * Optional authentication middleware
 * Attaches user if token is valid, but doesn't block if missing
 */
async function optionalAuthMiddleware(req, res, next) {
  try {
    const token = req.headers['x-session-token'] || req.cookies.sessionToken;

    if (token) {
      const user = await userService.validateSession(token);
      if (user) {
        req.user = user;
      }
    }

    next();

  } catch (error) {
    console.error('Optional auth middleware error:', error);
    next();
  }
}

module.exports = {
  authMiddleware,
  optionalAuthMiddleware
};
```

#### 6. Express Routes Setup

```javascript
// routes/auth.js

const express = require('express');
const router = express.Router();
const authController = require('../controllers/authController');
const { authMiddleware } = require('../middleware/auth');

// Public routes
router.post('/login', authController.login);
router.post('/logout', authController.logout);

// Protected routes
router.get('/me', authMiddleware, authController.getCurrentUser);

module.exports = router;
```

```javascript
// app.js

const express = require('express');
const cookieParser = require('cookie-parser');
const authRoutes = require('./routes/auth');

const app = express();

app.use(express.json());
app.use(cookieParser());

// Mount auth routes
app.use('/api/auth', authRoutes);

// Example protected route
app.get('/api/protected', authMiddleware, (req, res) => {
  res.json({
    success: true,
    message: 'This is a protected route',
    user: req.user
  });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`RFM server listening on port ${PORT}`);
});
```

---

## Database Schema

### RFM Database Schema (PostgreSQL)

```sql
-- Users table (linked to PolkaSQL workers)
CREATE TABLE rfm_users (
  id SERIAL PRIMARY KEY,
  polka_user_id INTEGER NOT NULL UNIQUE,  -- Links to polka27.workers.indeks
  username VARCHAR(10) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  last_login TIMESTAMP,
  is_active BOOLEAN DEFAULT TRUE,
  metadata JSONB DEFAULT '{}'  -- Additional user metadata
);

-- Sessions table
CREATE TABLE rfm_sessions (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES rfm_users(id) ON DELETE CASCADE,
  token VARCHAR(64) UNIQUE NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP NOT NULL,
  active BOOLEAN DEFAULT TRUE,
  ip_address INET,  -- Track IP for security
  user_agent TEXT   -- Track user agent
);

-- Indexes for performance
CREATE INDEX idx_rfm_users_polka_id ON rfm_users(polka_user_id);
CREATE INDEX idx_rfm_users_username ON rfm_users(username);
CREATE INDEX idx_rfm_sessions_token ON rfm_sessions(token);
CREATE INDEX idx_rfm_sessions_user_id ON rfm_sessions(user_id);
CREATE INDEX idx_rfm_sessions_active ON rfm_sessions(active);
CREATE INDEX idx_rfm_sessions_expires_at ON rfm_sessions(expires_at);

-- Comments
COMMENT ON TABLE rfm_users IS 'RFM application users linked to PolkaSQL workers';
COMMENT ON TABLE rfm_sessions IS 'User session tokens for authentication';
COMMENT ON COLUMN rfm_users.polka_user_id IS 'Foreign key to polka27.workers.indeks';
```

### PolkaSQL Schema Reference

```sql
-- Reference: polka27.workers table structure
-- This table exists in PolkaSQL database, included here for reference

CREATE TABLE polka27.workers (
  indeks INTEGER PRIMARY KEY,           -- Worker ID (used as polka_user_id)
  id_i_ CHAR(10),                       -- Username/Login (case-insensitive)
  nazwimie_i CHAR(100),                 -- Full name
  Dezakt_r DATE,                        -- Deactivation date ('1900-01-01' = active)
  Uprawn_x INTEGER,                     -- Permissions bitmask
  maxrabat DECIMAL(5,2),                -- Max discount
  Numer_x INTEGER,                      -- Card number
  stanow_x CHAR(1),                     -- Position code
  -- ... other fields
);
```

---

## Code Examples

### Frontend (React/Next.js)

#### Login Form Component

```jsx
// components/LoginForm.jsx

import { useState } from 'react';
import { useRouter } from 'next/router';

export default function LoginForm() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ username, password }),
      });

      const data = await response.json();

      if (!data.success) {
        setError(data.error || 'Login failed');
        return;
      }

      // Store session token
      localStorage.setItem('sessionToken', data.session.token);
      localStorage.setItem('user', JSON.stringify(data.user));

      // Redirect to dashboard
      router.push('/dashboard');

    } catch (err) {
      console.error('Login error:', err);
      setError('Network error. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-form">
      <h2>RFM Login</h2>
      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="username">Username</label>
          <input
            type="text"
            id="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="Enter username"
            required
            autoComplete="username"
          />
        </div>

        <div className="form-group">
          <label htmlFor="password">Password</label>
          <input
            type="password"
            id="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Enter password"
            required
            autoComplete="current-password"
          />
        </div>

        {error && (
          <div className="error-message">
            {error}
          </div>
        )}

        <button type="submit" disabled={loading}>
          {loading ? 'Logging in...' : 'Login'}
        </button>
      </form>
    </div>
  );
}
```

#### Auth Context Provider

```jsx
// contexts/AuthContext.jsx

import { createContext, useContext, useState, useEffect } from 'react';
import { useRouter } from 'next/router';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    checkAuth();
  }, []);

  const checkAuth = async () => {
    try {
      const token = localStorage.getItem('sessionToken');
      if (!token) {
        setLoading(false);
        return;
      }

      const response = await fetch('/api/auth/me', {
        headers: {
          'X-Session-Token': token,
        },
      });

      const data = await response.json();

      if (data.success) {
        setUser(data.user);
      } else {
        localStorage.removeItem('sessionToken');
        localStorage.removeItem('user');
      }
    } catch (error) {
      console.error('Auth check error:', error);
    } finally {
      setLoading(false);
    }
  };

  const login = async (username, password) => {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ username, password }),
    });

    const data = await response.json();

    if (!data.success) {
      throw new Error(data.error || 'Login failed');
    }

    localStorage.setItem('sessionToken', data.session.token);
    localStorage.setItem('user', JSON.stringify(data.user));
    setUser(data.user);

    return data;
  };

  const logout = async () => {
    try {
      const token = localStorage.getItem('sessionToken');
      
      await fetch('/api/auth/logout', {
        method: 'POST',
        headers: {
          'X-Session-Token': token,
        },
      });
    } catch (error) {
      console.error('Logout error:', error);
    } finally {
      localStorage.removeItem('sessionToken');
      localStorage.removeItem('user');
      setUser(null);
      router.push('/login');
    }
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, checkAuth }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
}
```

#### Protected Route Component

```jsx
// components/ProtectedRoute.jsx

import { useEffect } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';

export default function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) {
      router.push('/login');
    }
  }, [user, loading, router]);

  if (loading) {
    return <div>Loading...</div>;
  }

  if (!user) {
    return null;
  }

  return children;
}
```

### Python Implementation

```python
# services/polka_auth.py

import os
import requests
from typing import Dict, Optional
from urllib.parse import urlencode

class PolkaAuthService:
    """Service for authenticating users against PolkaSQL API"""
    
    def __init__(self):
        self.api_url = os.getenv('POLKA_API_URL', 'https://polkaserver.local/RFM_Auth')
        self.api_key = os.getenv('POLKA_API_KEY')
        self.timeout = 5  # seconds
        
    def authenticate(self, username: str, password: str) -> Dict:
        """
        Authenticate user against PolkaSQL database
        
        Args:
            username: Username (case-insensitive)
            password: Password (case-insensitive)
            
        Returns:
            Dict with keys: success, authenticated, error, user_id, username
        """
        try:
            params = {
                'ApiKey': self.api_key,
                'UserName': username,
                'Password': password
            }
            
            response = requests.get(
                self.api_url,
                params=params,
                headers={'Accept': 'application/json'},
                timeout=self.timeout
            )
            
            response.raise_for_status()
            data = response.json()
            
            if not data.get('success'):
                return {
                    'success': False,
                    'error': data.get('error', 'API call failed')
                }
                
            if not data.get('authenticated'):
                return {
                    'success': False,
                    'authenticated': False,
                    'error': data.get('error', 'Authentication failed')
                }
                
            return {
                'success': True,
                'authenticated': True,
                'user_id': data.get('user_id'),
                'username': data.get('username')
            }
            
        except requests.Timeout:
            return {
                'success': False,
                'error': 'Authentication service timeout'
            }
        except requests.RequestException as e:
            return {
                'success': False,
                'error': f'Network error: {str(e)}'
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Unexpected error: {str(e)}'
            }
```

---

## Testing

### Manual Testing with cURL

```bash
# Test successful authentication
curl -X GET "http://polkaserver.local/RFM_Auth?ApiKey=SecureUUID1&UserName=john&Password=mypass123"

# Test case-insensitive username
curl -X GET "http://polkaserver.local/RFM_Auth?ApiKey=SecureUUID1&UserName=JOHN&Password=mypass123"

# Test case-insensitive password
curl -X GET "http://polkaserver.local/RFM_Auth?ApiKey=SecureUUID1&UserName=john&Password=MYPASS123"

# Test invalid credentials
curl -X GET "http://polkaserver.local/RFM_Auth?ApiKey=SecureUUID1&UserName=john&Password=wrongpass"

# Test missing API key
curl -X GET "http://polkaserver.local/RFM_Auth?UserName=john&Password=mypass123"

# Test invalid API key
curl -X GET "http://polkaserver.local/RFM_Auth?ApiKey=InvalidKey&UserName=john&Password=mypass123"

# Test missing username
curl -X GET "http://polkaserver.local/RFM_Auth?ApiKey=SecureUUID1&Password=mypass123"

# Test missing password
curl -X GET "http://polkaserver.local/RFM_Auth?ApiKey=SecureUUID1&UserName=john"
```

### Automated Testing (Jest)

```javascript
// tests/polkaAuth.test.js

const polkaAuth = require('../services/polkaAuth');
const nock = require('nock');

describe('PolkaAuthService', () => {
  const mockApiUrl = 'https://polkaserver.local';
  const mockApiKey = 'test-api-key';

  beforeEach(() => {
    process.env.POLKA_API_URL = `${mockApiUrl}/RFM_Auth`;
    process.env.POLKA_API_KEY = mockApiKey;
  });

  afterEach(() => {
    nock.cleanAll();
  });

  test('should authenticate successfully', async () => {
    nock(mockApiUrl)
      .get('/RFM_Auth')
      .query({
        ApiKey: mockApiKey,
        UserName: 'john',
        Password: 'password123'
      })
      .reply(200, {
        success: true,
        authenticated: true,
        error: null,
        user_id: 123,
        username: 'john'
      });

    const result = await polkaAuth.authenticate('john', 'password123');

    expect(result.success).toBe(true);
    expect(result.authenticated).toBe(true);
    expect(result.userId).toBe(123);
    expect(result.username).toBe('john');
  });

  test('should handle invalid credentials', async () => {
    nock(mockApiUrl)
      .get('/RFM_Auth')
      .query(true)
      .reply(200, {
        success: true,
        authenticated: false,
        error: 'Invalid username or password'
      });

    const result = await polkaAuth.authenticate('john', 'wrongpass');

    expect(result.success).toBe(false);
    expect(result.authenticated).toBe(false);
    expect(result.error).toBe('Invalid username or password');
  });

  test('should handle API timeout', async () => {
    nock(mockApiUrl)
      .get('/RFM_Auth')
      .query(true)
      .delayConnection(10000)
      .reply(200, {});

    const result = await polkaAuth.authenticate('john', 'password123');

    expect(result.success).toBe(false);
    expect(result.error).toContain('timeout');
  });

  test('should handle network errors', async () => {
    nock(mockApiUrl)
      .get('/RFM_Auth')
      .query(true)
      .replyWithError('Network error');

    const result = await polkaAuth.authenticate('john', 'password123');

    expect(result.success).toBe(false);
    expect(result.error).toContain('Network error');
  });
});
```

### Integration Testing

```javascript
// tests/integration/auth.test.js

const request = require('supertest');
const app = require('../../app');
const { db } = require('../../database');

describe('Auth Integration Tests', () => {
  beforeAll(async () => {
    await db.sync({ force: true });
  });

  afterAll(async () => {
    await db.close();
  });

  describe('POST /api/auth/login', () => {
    test('should login successfully and create session', async () => {
      const response = await request(app)
        .post('/api/auth/login')
        .send({
          username: 'testuser',
          password: 'testpass'
        })
        .expect(200);

      expect(response.body.success).toBe(true);
      expect(response.body.user).toBeDefined();
      expect(response.body.session).toBeDefined();
      expect(response.body.session.token).toBeDefined();
    });

    test('should reject invalid credentials', async () => {
      const response = await request(app)
        .post('/api/auth/login')
        .send({
          username: 'testuser',
          password: 'wrongpass'
        })
        .expect(401);

      expect(response.body.success).toBe(false);
      expect(response.body.error).toBeDefined();
    });

    test('should handle case-insensitive username', async () => {
      const response = await request(app)
        .post('/api/auth/login')
        .send({
          username: 'TESTUSER',
          password: 'testpass'
        })
        .expect(200);

      expect(response.body.success).toBe(true);
    });
  });

  describe('GET /api/auth/me', () => {
    let sessionToken;

    beforeEach(async () => {
      const loginResponse = await request(app)
        .post('/api/auth/login')
        .send({
          username: 'testuser',
          password: 'testpass'
        });

      sessionToken = loginResponse.body.session.token;
    });

    test('should return current user with valid token', async () => {
      const response = await request(app)
        .get('/api/auth/me')
        .set('X-Session-Token', sessionToken)
        .expect(200);

      expect(response.body.success).toBe(true);
      expect(response.body.user).toBeDefined();
      expect(response.body.user.username).toBe('testuser');
    });

    test('should reject invalid token', async () => {
      const response = await request(app)
        .get('/api/auth/me')
        .set('X-Session-Token', 'invalid-token')
        .expect(401);

      expect(response.body.success).toBe(false);
    });

    test('should reject missing token', async () => {
      const response = await request(app)
        .get('/api/auth/me')
        .expect(401);

      expect(response.body.success).toBe(false);
    });
  });
});
```

---

## Troubleshooting

### Common Issues and Solutions

#### Issue: "Invalid or missing API key"

**Symptoms:**
```json
{
  "success": false,
  "authenticated": false,
  "error": "Invalid or missing API key"
}
```

**Solutions:**
1. Verify API key is included in request: `?ApiKey=YourKey`
2. Check API key matches one of the whitelisted keys in the procedure
3. Ensure API key is not empty or null
4. Verify no typos in parameter name (case-sensitive: `ApiKey`)

#### Issue: "Invalid username or password"

**Symptoms:**
```json
{
  "success": true,
  "authenticated": false,
  "error": "Invalid username or password"
}
```

**Possible Causes:**
1. Username doesn't exist in `polka27.workers` table
2. Password is incorrect
3. Case normalization issue (UPPER vs LOWER)

**Solutions:**
1. Verify user exists:
   ```sql
   SELECT indeks, id_i_ FROM polka27.workers WHERE UPPER(id_i_) = UPPER('username');
   ```
2. Test password manually:
   ```sql
   SELECT Polka27.PL_IfPwdIsOk('PASSWORD', worker_id);
   ```
3. Check if passwords in database are UPPERCASE or LOWERCASE
4. If database uses LOWERCASE, change procedure from `UPPER(Password)` to `LOWER(Password)`

#### Issue: "User account is not active"

**Symptoms:**
```json
{
  "success": true,
  "authenticated": false,
  "error": "User account is not active"
}
```

**Solution:**
Check deactivation date:
```sql
SELECT indeks, id_i_, Dezakt_r 
FROM polka27.workers 
WHERE id_i_ = 'username';
```

Active accounts should have `Dezakt_r = '1900-01-01'`. To reactivate:
```sql
UPDATE polka27.workers 
SET Dezakt_r = '1900-01-01' 
WHERE indeks = worker_id;
```

#### Issue: "User does not have access"

**Symptoms:**
```json
{
  "success": true,
  "authenticated": false,
  "error": "User does not have access"
}
```

**Solution:**
Check access flag:
```sql
SELECT polka27.PL_CheckProperty('mPolka: blokada logowania', 6, worker_id);
```

If returns `1`, access is blocked. Contact PolkaSQL administrator to modify user permissions.

#### Issue: Connection Timeout

**Symptoms:**
- Request hangs
- No response after 5 seconds
- Network timeout error

**Solutions:**
1. Verify database server is running
2. Check network connectivity: `ping polkaserver.local`
3. Test endpoint directly: `curl http://polkaserver.local/RFM_Auth?...`
4. Check firewall rules allow HTTP/HTTPS traffic
5. Verify SQL Anywhere web service is running
6. Increase timeout in client code if needed

#### Issue: Case-Insensitive Not Working

**Symptoms:**
- `john` works but `JOHN` doesn't
- Password in one case works, other case doesn't

**Solutions:**

1. **For Username**: Should work automatically with `UPPER(id_i_) = UPPER(UserName)`
   - If not working, check procedure uses `UPPER()` on both sides of comparison

2. **For Password**: 
   - Check if passwords in database are stored as UPPERCASE
   - Query to test:
     ```sql
     SELECT Polka27.PL_IfPwdIsOk('PASSWORD', worker_id);  -- Try UPPER
     SELECT Polka27.PL_IfPwdIsOk('password', worker_id);  -- Try lower
     ```
   - If lowercase works, change procedure:
     ```sql
     SET v_password_normalized = LOWER(Password);  -- Instead of UPPER
     ```

#### Issue: HTTP 404 Not Found

**Symptoms:**
```
HTTP/1.1 404 Not Found
```

**Solutions:**
1. Verify service exists:
   ```sql
   SELECT * FROM SYS.SYSWEBSERVICE WHERE service_name = 'RFM_Auth';
   ```
2. Check service is enabled
3. Verify correct URL path (service name is case-sensitive in some configurations)
4. Restart SQL Anywhere web service

#### Issue: HTTP 500 Internal Server Error

**Symptoms:**
```
HTTP/1.1 500 Internal Server Error
```

**Solutions:**
1. Check SQL Anywhere logs for procedure errors
2. Test procedure directly in database:
   ```sql
   CALL Polka27.RFM_sp_Auth('SecureUUID1', 'username', 'password');
   ```
3. Verify all referenced functions exist:
   - `Polka27.PL_IfPwdIsOk`
   - `polka27.PL_CheckProperty`
4. Check database permissions for service user (`RFM_view`)

### Debugging Checklist

Use this checklist to systematically debug authentication issues:

- [ ] API key is correct and matches whitelist
- [ ] Username exists in `polka27.workers` table
- [ ] User account is active (`Dezakt_r = '1900-01-01'`)
- [ ] User doesn't have access block flag
- [ ] Password normalization matches database (UPPER vs LOWER)
- [ ] Network connectivity to database server
- [ ] Web service is running and accessible
- [ ] Service user (`RFM_view`) has correct permissions
- [ ] All referenced functions are available
- [ ] No firewall blocking requests
- [ ] Client timeout is sufficient (>5 seconds)

### Logging for Debugging

Add logging to track authentication attempts:

```javascript
// Enhanced logging in authentication service

async authenticate(username, password) {
  const startTime = Date.now();
  console.log(`[Auth] Attempting authentication for user: ${username}`);

  try {
    const response = await axios.get(/* ... */);
    const elapsed = Date.now() - startTime;
    
    console.log(`[Auth] Response received in ${elapsed}ms`);
    console.log(`[Auth] Success: ${response.data.success}, Authenticated: ${response.data.authenticated}`);
    
    if (response.data.error) {
      console.log(`[Auth] Error: ${response.data.error}`);
    }
    
    return response.data;
    
  } catch (error) {
    const elapsed = Date.now() - startTime;
    console.error(`[Auth] Failed after ${elapsed}ms:`, error.message);
    return { success: false, error: error.message };
  }
}
```

---

## Performance Considerations

### Expected Response Times

- **Successful authentication**: 50-200ms
- **Failed authentication**: 50-200ms
- **Network timeout**: 5000ms (configurable)

### Optimization Tips

1. **Connection Pooling**: Reuse HTTP connections
   ```javascript
   const axios = require('axios');
   const http = require('http');
   const https = require('https');

   const httpAgent = new http.Agent({ keepAlive: true });
   const httpsAgent = new https.Agent({ keepAlive: true });

   axios.get(url, { httpAgent, httpsAgent });
   ```

2. **Caching**: Cache successful authentications briefly (30-60 seconds)
   ```javascript
   const NodeCache = require('node-cache');
   const authCache = new NodeCache({ stdTTL: 60 });

   async function authenticate(username, password) {
     const cacheKey = `${username}:${hashPassword(password)}`;
     const cached = authCache.get(cacheKey);
     
     if (cached) {
       return cached;
     }
     
     const result = await polkaAuth.authenticate(username, password);
     
     if (result.success && result.authenticated) {
       authCache.set(cacheKey, result);
     }
     
     return result;
   }
   ```

3. **Database Indexing**: Ensure `polka27.workers.id_i_` is indexed

4. **Rate Limiting**: Prevent brute force attacks while maintaining performance

---

## API Versioning

### Current Version: 1.0

As the API evolves, consider versioning:

```sql
-- Future: Version 2 with additional fields
CREATE SERVICE "RFM_Auth_v2" 
  TYPE 'RAW' 
  AUTHORIZATION OFF 
  USER "RFM_view" 
  METHODS 'GET' 
AS call "Polka27"."RFM_sp_Auth_v2"(:ApiKey, :UserName, :Password);
```

URL structure:
```
v1: http://server/RFM_Auth
v2: http://server/RFM_Auth_v2
```

---

## Additional Resources

### Related Documentation

- SQL Anywhere 17 Documentation: https://help.sap.com/docs/SAP_SQL_Anywhere
- Express.js Authentication: https://expressjs.com/
- JWT Best Practices: https://tools.ietf.org/html/rfc7519

### Support Contacts

- **Database Administrator**: Contact for PolkaSQL access and permissions
- **API Developer**: Contact for RFM application integration issues
- **Security Team**: Contact for API key management and security concerns

---

## Changelog

### Version 1.0 (2025-02-05)
- Initial release
- Case-insensitive username and password authentication
- JSON response format
- Basic security validations
- Integration with PolkaSQL workers table

---

## License and Usage

This API is for internal use only within the organization's local network. Not intended for public internet exposure.

**Confidential - Internal Use Only**

---

## Appendix

### SQL Procedure Source Code

```sql
CREATE PROCEDURE "Polka27"."RFM_sp_Auth"(
  IN ApiKey CHAR(30),
  IN UserName VARCHAR(10),
  IN Password VARCHAR(10)
)
RESULT (json_response LONG VARCHAR)
BEGIN
  DECLARE v_worker_id INT;
  DECLARE v_password_ok BIT;
  DECLARE v_deactivation_date DATE;
  DECLARE v_error VARCHAR(500);
  DECLARE json_result LONG VARCHAR;
  DECLARE v_password_normalized VARCHAR(10);
  
  SET v_error = NULL;
  
  -- API KEY VALIDATION
  IF ApiKey IS NULL OR ApiKey = '' OR 
     ApiKey NOT IN ('SecureUUID1', 'SecureUUID2') THEN
    SET v_error = 'Invalid or missing API key';
    SET json_result = '{"success": false, "authenticated": false, "error": "' || v_error || '"}';
    SELECT json_result AS json_response;
    RETURN;
  END IF;
  
  -- USERNAME VALIDATION
  IF UserName IS NULL OR UserName = '' THEN
    SET v_error = 'Username is required';
    SET json_result = '{"success": false, "authenticated": false, "error": "' || v_error || '"}';
    SELECT json_result AS json_response;
    RETURN;
  END IF;
  
  -- PASSWORD VALIDATION
  IF Password IS NULL OR Password = '' THEN
    SET v_error = 'Password is required';
    SET json_result = '{"success": false, "authenticated": false, "error": "' || v_error || '"}';
    SELECT json_result AS json_response;
    RETURN;
  END IF;
  
  -- NORMALIZE PASSWORD TO UPPERCASE (case-insensitive comparison)
  SET v_password_normalized = UPPER(Password);
  
  -- FIND WORKER BY USERNAME (case-insensitive via UPPER)
  SELECT indeks, Dezakt_r 
  INTO v_worker_id, v_deactivation_date
  FROM polka27.workers 
  WHERE UPPER(id_i_) = UPPER(UserName);
  
  -- CHECK IF USER EXISTS
  IF v_worker_id IS NULL THEN
    SET json_result = '{"success": true, "authenticated": false, "error": "Invalid username or password"}';
    SELECT json_result AS json_response;
    RETURN;
  END IF;
  
  -- CHECK IF USER IS ACTIVE
  IF v_deactivation_date IS NOT NULL AND v_deactivation_date <> '1900-01-01' THEN
    SET json_result = '{"success": true, "authenticated": false, "error": "User account is not active"}';
    SELECT json_result AS json_response;
    RETURN;
  END IF;
  
  -- CHECK IF USER HAS ACCESS
  IF polka27.PL_CheckProperty('mPolka: blokada logowania', 6, v_worker_id) = 1 THEN
    SET json_result = '{"success": true, "authenticated": false, "error": "User does not have access"}';
    SELECT json_result AS json_response;
    RETURN;
  END IF;
  
  -- VERIFY PASSWORD
  SET v_password_ok = Polka27.PL_IfPwdIsOk(v_password_normalized, v_worker_id);
  
  IF v_password_ok = 0 THEN
    SET json_result = '{"success": true, "authenticated": false, "error": "Invalid username or password"}';
    SELECT json_result AS json_response;
    RETURN;
  END IF;
  
  -- AUTHENTICATION SUCCESSFUL
  SET json_result = 
    '{' ||
      '"success": true,' ||
      '"authenticated": true,' ||
      '"error": null,' ||
      '"user_id": ' || CAST(v_worker_id AS VARCHAR) || ',' ||
      '"username": "' || REPLACE(REPLACE(UserName, '\', '\\'), '"', '\"') || '"' ||
    '}';
  
  SELECT json_result AS json_response;
  
END;
```

### Web Service Definition

```sql
CREATE SERVICE "RFM_Auth" 
  TYPE 'RAW' 
  AUTHORIZATION OFF 
  USER "RFM_view" 
  METHODS 'GET' 
AS call "Polka27"."RFM_sp_Auth"(:ApiKey, :UserName, :Password);
```

---

**End of Documentation**
