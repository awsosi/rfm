#!/usr/bin/env python3
"""
Modular File Manager - WebUI Server
Serves static files and proxies API requests to backend
"""
import os
import logging
from flask import Flask, send_from_directory, request, jsonify, Response
from flask_cors import CORS
import requests

# Configure logging
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO').upper(),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__, static_folder='frontend', static_url_path='')

# Enable CORS for API requests
CORS(app, resources={
    r"/api/*": {"origins": "*"},
    r"/ws/*": {"origins": "*"}
})

# Configuration
API_URL = os.getenv('API_URL', 'http://api:8000')
API_URL_PUBLIC = os.getenv('API_URL_PUBLIC', '')  # Public-facing API URL for browser
WEBUI_PORT = int(os.getenv('WEBUI_PORT', 3000))
WEBUI_HOST = os.getenv('WEBUI_HOST', '0.0.0.0')

logger.info(f"WebUI Server starting on {WEBUI_HOST}:{WEBUI_PORT}")
logger.info(f"API Backend URL (internal): {API_URL}")
logger.info(f"API Backend URL (public): {API_URL_PUBLIC or 'auto-detect'}")

# ------------------------------------------------------------------------------
# Static File Routes
# ------------------------------------------------------------------------------

@app.route('/')
def index():
    """Serve index.html with injected configuration"""
    # Read index.html
    with open('frontend/index.html', 'r', encoding='utf-8') as f:
        html = f.read()

    # Inject API_URL_PUBLIC configuration before closing </head> tag
    config_script = f'''
    <script>
        // API URL configuration (injected by backend)
        window.API_URL_PUBLIC = {f'"{API_URL_PUBLIC}"' if API_URL_PUBLIC else 'null'};
    </script>
</head>'''

    html = html.replace('</head>', config_script)

    return Response(html, mimetype='text/html')

@app.route('/pages/<path:filename>')
def pages(filename):
    """Serve pages"""
    return send_from_directory('frontend/pages', filename)

@app.route('/js/<path:filename>')
def javascript(filename):
    """Serve JavaScript files"""
    return send_from_directory('frontend/js', filename)

@app.route('/css/<path:filename>')
def stylesheets(filename):
    """Serve CSS files"""
    return send_from_directory('frontend/css', filename)

@app.route('/assets/<path:filename>')
def assets(filename):
    """Serve assets"""
    return send_from_directory('frontend/assets', filename)

# ------------------------------------------------------------------------------
# Health Check
# ------------------------------------------------------------------------------

@app.route('/health')
def health():
    """Health check endpoint"""
    try:
        # Check if API is reachable
        response = requests.get(f"{API_URL}/health", timeout=5)
        api_healthy = response.status_code == 200
    except Exception as e:
        logger.error(f"API health check failed: {e}")
        api_healthy = False

    return jsonify({
        'status': 'healthy' if api_healthy else 'degraded',
        'webui': 'running',
        'api': 'connected' if api_healthy else 'disconnected'
    }), 200 if api_healthy else 503

# ------------------------------------------------------------------------------
# API Proxy Routes (optional - client can call API directly)
# ------------------------------------------------------------------------------

@app.route('/auth/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
def auth_proxy(path):
    """
    Proxy authentication requests to backend API
    Maps /auth/* to /api/auth/* on backend
    """
    try:
        # Build target URL - map /auth/* to /api/auth/*
        target_url = f"{API_URL}/api/auth/{path}"

        # Forward request
        response = requests.request(
            method=request.method,
            url=target_url,
            headers={key: value for key, value in request.headers if key.lower() != 'host'},
            data=request.get_data(),
            params=request.args,
            allow_redirects=False,
            timeout=30
        )

        # Return response
        return (response.content, response.status_code, response.headers.items())

    except requests.exceptions.RequestException as e:
        logger.error(f"Auth proxy error: {e}")
        return jsonify({'error': 'Backend API unavailable'}), 503


@app.route('/api/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
def api_proxy(path):
    """
    Proxy API requests to backend
    This is optional - the frontend can call the API directly
    """
    try:
        # Build target URL
        target_url = f"{API_URL}/api/{path}"

        # Forward request
        response = requests.request(
            method=request.method,
            url=target_url,
            headers={key: value for key, value in request.headers if key.lower() != 'host'},
            data=request.get_data(),
            params=request.args,
            allow_redirects=False,
            timeout=30
        )

        # Return response
        return (response.content, response.status_code, response.headers.items())

    except requests.exceptions.RequestException as e:
        logger.error(f"API proxy error: {e}")
        return jsonify({'error': 'Backend API unavailable'}), 503

# ------------------------------------------------------------------------------
# Error Handlers
# ------------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors - serve index.html for SPA routing"""
    if request.path.startswith('/api/') or request.path.startswith('/ws/'):
        return jsonify({'error': 'Not found'}), 404
    # For all other routes, serve index.html (SPA routing)
    return send_from_directory('frontend', 'index.html')

@app.errorhandler(500)
def internal_error(e):
    """Handle 500 errors"""
    logger.error(f"Internal server error: {e}")
    return jsonify({'error': 'Internal server error'}), 500

# ------------------------------------------------------------------------------
# Run Server
# ------------------------------------------------------------------------------

if __name__ == '__main__':
    # Use gunicorn in production, Flask dev server for development
    if os.getenv('FLASK_ENV') == 'development':
        app.run(
            host=WEBUI_HOST,
            port=WEBUI_PORT,
            debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
        )
    else:
        logger.info("Starting production server with gunicorn")
        # gunicorn will be started by entrypoint script
        pass
