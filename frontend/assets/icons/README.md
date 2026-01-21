# Icons and Assets

This directory contains icons, images, and other static assets for the file manager UI.

## Current Implementation

The current implementation uses Unicode emoji icons:
- 📁 Folder icon
- 📄 File icon

## Future Enhancements

You can replace emoji icons with custom SVG or PNG icons by:

1. **Adding icon files** to this directory:
   - `folder.svg` - Folder icon
   - `file.svg` - Generic file icon
   - `file-pdf.svg` - PDF file icon
   - `file-image.svg` - Image file icon
   - `file-code.svg` - Code file icon
   - etc.

2. **Update CSS** in `css/style.css`:

```css
.file-icon.folder::before {
    content: "";
    background-image: url('../assets/icons/folder.svg');
    background-size: contain;
    background-repeat: no-repeat;
    display: inline-block;
    width: 20px;
    height: 20px;
}

.file-icon.file::before {
    content: "";
    background-image: url('../assets/icons/file.svg');
    background-size: contain;
    background-repeat: no-repeat;
    display: inline-block;
    width: 20px;
    height: 20px;
}
```

3. **Add file type detection** in `js/ui.js`:

```javascript
function getFileIcon(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    switch (ext) {
        case 'pdf': return 'file-pdf';
        case 'jpg':
        case 'jpeg':
        case 'png':
        case 'gif': return 'file-image';
        case 'js':
        case 'py':
        case 'java': return 'file-code';
        default: return 'file';
    }
}
```

## Icon Resources

Free icon libraries:
- [Heroicons](https://heroicons.com/) - MIT License
- [Feather Icons](https://feathericons.com/) - MIT License
- [Material Icons](https://fonts.google.com/icons) - Apache 2.0
- [Font Awesome](https://fontawesome.com/) - Free icons available
- [Tabler Icons](https://tabler-icons.io/) - MIT License

## Logo

Add your application logo:
- `logo.svg` or `logo.png`
- Recommended size: 200x200px
- Use in login page header
