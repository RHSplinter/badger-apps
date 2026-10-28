# Badger Apps

Apps for the [GitHub Universe 2026 badge](https://github.com/badger-seds/badger2026-hardware).

## Apps

- **Contribution Graph**: View your GitHub contribution heatmap directly on the badge.

## Quick Start: Contribution Graph

The Contribution Graph app displays your GitHub contributions as the familiar yearly heatmap.

### Installation

1. **Set your GitHub username** in the badge's `secrets.py`:
   ```python
   GITHUB_USERNAME = "your-github-handle"
   ```

2. **Copy the app to your badge**:
   - Put the badge in USB Disk Mode (open the **Mass Storage** app, or double-tap RESET).
   - Copy the `badge/apps/contribution_graph/` directory to `/apps/` on the **BADGER** drive.
   - Eject the drive. The badge restarts automatically.

3. **Open the app**: Select **Contribution Graph** from the badge menu.

### First Run

The app will download your contribution data and display your stats:
- Yearly heatmap (one column per week)
- Current streak
- Longest streak
- Busiest day

**Note**: Wi-Fi must be configured on the badge (Settings app). The app caches your data locally.

### Usage

| Button | Action |
|--------|--------|
| **UP/DOWN** | Navigate days |
| **LEFT/RIGHT** | Navigate weeks |
| **SELECT** | Refresh data |
| **MENU** | Search for a different user |
| **BACK** | Jump to today |
| **HOME** | Return to badge menu |

For detailed instructions, see [`badge/apps/contribution_graph/README.md`](badge/apps/contribution_graph/README.md).
