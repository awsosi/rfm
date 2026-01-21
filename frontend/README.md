# File Manager - Frontend

A vanilla JavaScript web UI for remote file management with dual-pane explorer.

## Features

- **Dual-Pane File Explorer**: Side-by-side view of Path A and Path B
- **Real-time Updates**: WebSocket integration for live operation status
- **File Operations**: Copy, move, delete, rename, create folders
- **Search**: Recursive file search in both panes
- **Admin Panel**: User management, worker management, configuration, logs
- **Responsive Design**: Mobile-friendly layout
- **Session Management**: Secure token-based authentication

## Technology Stack

- **HTML5**: Semantic markup
- **CSS3**: Modern styling with CSS variables
- **Vanilla JavaScript**: No frameworks (KISS principle)
- **ES6 Modules**: Clean module structure
- **WebSocket**: Real-time communication

## Project Structure

```
frontend/
├── index.html              # Landing page (redirects to login)
├── pages/
│   ├── login.html         # Login page
│   ├── explorer.html      # Main file explorer
│   └── admin.html         # Admin panel
├── css/
│   ├── style.css          # Main styles
│   └── responsive.css     # Mobile-responsive styles
├── js/
│   ├── app.js            # Main application controller
│   ├── api.js            # API calls and WebSocket
│   ├── auth.js           # Authentication and session
│   ├── ui.js             # DOM updates and UI interactions
│   └── utils.js          # Helper functions
├── assets/
│   └── icons/            # Icons and images
└── README.md             # This file
```

## Getting Started

### Prerequisites

- Modern web browser (Chrome, Firefox, Safari, Edge)
- Backend API server running (see ../backend/README.md)

### Installation

No build process required! Simply serve the files using any web server:

#### Option 1: Python HTTP Server

```bash
cd frontend
python3 -m http.server 8080
```

Then open: http://localhost:8080

#### Option 2: Node.js HTTP Server

```bash
npm install -g http-server
cd frontend
http-server -p 8080
```

#### Option 3: Use with Backend

The backend FastAPI server can serve the frontend:

```bash
# Backend serves frontend from /
cd ../backend
python -m uvicorn central_api.main:app --host 0.0.0.0 --port 8000
```

Then open: http://localhost:8000

### Configuration

The frontend automatically detects the API endpoint:
- **Localhost**: Uses `http://localhost:8000`
- **Production**: Uses current origin

To change the API endpoint, edit `js/auth.js`:

```javascript
const API_BASE_URL = 'https://your-api-server.com';
```

## Usage

### Login

1. Navigate to the login page
2. Enter your username and password
3. Click "Sign In"

Default admin credentials (if using local auth):
- Username: `admin`
- Password: See backend configuration

### File Explorer

**Dual Panes**:
- Left pane: Path A
- Right pane: Path B

**Navigation**:
- Double-click folders to open
- Use breadcrumb input to jump to any path
- Search box for recursive file search

**Operations**:
- Select files using checkboxes
- Use operation buttons: "Copy A→B", "Move A→B", etc.
- Right-click for context menu (admin only)

**Real-time Updates**:
- Progress bar shows operation status
- Operation queue displays active operations
- WebSocket provides live updates

### Admin Panel

Only accessible to users with `admin` role.

**Tabs**:
1. **Users**: Manage user accounts
2. **Workers**: Approve/manage worker nodes
3. **Configuration**: System settings
4. **Logs**: View and search system logs

## Module Documentation

### auth.js

Handles authentication and session management:
- `login(username, password)` - Authenticate user
- `logout()` - Clear session
- `checkAuth()` - Verify authentication
- `getToken()` - Get auth token
- `getCurrentUser()` - Get user data
- `isAdmin()` - Check admin role

### api.js

API communication and WebSocket:
- `listFiles(path)` - List directory contents
- `searchFiles(path, pattern)` - Search files
- `copyFiles(sources, dest)` - Copy operation
- `moveFiles(sources, dest)` - Move operation
- `deleteFiles(paths)` - Delete files
- `connectWebSocket()` - Connect for real-time updates

### ui.js

DOM manipulation and UI updates:
- `renderFileList(paneId, files)` - Render file listing
- `updateOperationStatus(message, type)` - Update status
- `updateProgress(percent)` - Update progress bar
- `showError/Success/Info(message)` - Show notifications

### utils.js

Helper functions:
- `formatFileSize(bytes)` - Human-readable sizes
- `formatDate(date)` - Relative dates
- `showModal/Confirm/Prompt()` - Dialogs
- `debounce/throttle()` - Performance helpers

## Browser Support

- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

Features used:
- ES6 Modules
- CSS Variables
- Fetch API
- WebSocket
- Session Storage

## Security

- Tokens stored in sessionStorage (not localStorage)
- Auto-logout on token expiration
- Auto-refresh for long sessions
- 401 responses redirect to login
- XSS protection via escapeHtml()

## Performance

- Lazy loading (50 files per page)
- Debounced search input
- Efficient DOM updates
- WebSocket for real-time (no polling overhead)
- Fallback polling if WebSocket unavailable

## Accessibility

- Semantic HTML
- ARIA labels (future enhancement)
- Keyboard navigation support
- Reduced motion support
- Touch-friendly on mobile (44px touch targets)

## Troubleshooting

**Login fails**:
- Check backend is running
- Verify API_BASE_URL in auth.js
- Check browser console for errors

**Files not loading**:
- Verify authentication token
- Check network tab for API errors
- Ensure proper path permissions

**WebSocket not connecting**:
- Check WebSocket URL (ws:// or wss://)
- Verify firewall allows WebSocket
- Fallback polling should activate automatically

**Operations not working**:
- Check user has proper permissions
- Verify paths exist and are accessible
- Review operation queue for errors

## Development

### Code Style

- Use ES6+ features
- 4-space indentation
- JSDoc comments for functions
- Descriptive variable names
- Single responsibility principle

### Adding Features

1. Add UI elements in HTML
2. Add styles in CSS
3. Add business logic in appropriate JS module
4. Wire up event handlers in app.js

### Testing

Test in multiple browsers:
```bash
# Chrome
open -a "Google Chrome" http://localhost:8080

# Firefox
open -a Firefox http://localhost:8080

# Safari
open -a Safari http://localhost:8080
```

Test responsive design:
- Chrome DevTools (Cmd+Opt+I)
- Use device toolbar (Cmd+Shift+M)
- Test on actual mobile devices

## License

See main project LICENSE file.

## Contributing

See main project CONTRIBUTING.md.

## Support

For issues and questions:
1. Check this README
2. Check backend documentation
3. Review browser console errors
4. Open GitHub issue with details
