# Changelog

All notable changes to this project will be documented in this file.

The format is inspired by [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

<br>

## [1.1.0] - Unreleased

### Added

- **Global 3D Cursor Transform:** Move and rotate the 3D Cursor when nothing is selected, without switching to the 3D Cursor tool.
  - Use G and R to move and rotate the 3D Cursor.
  - Use Alt+G and Alt+R to reset the cursor's location and rotation.
  - Available in Object Mode, Pose Mode, and supported Edit Modes.
- **Global transform gizmos:** Access the 3D Cursor's Move and Rotate gizmos without activating the 3D Cursor tool.
  - Gizmos automatically hide when a selection is present.
  - Visibility follows Blender's native Move and Rotate gizmo toggles.
- Separate preferences to enable or disable global transform shortcuts and gizmos.

### Changed

- Updated the add-on preferences with a dedicated **Global 3D Cursor Transform** section and descriptions.
- Improved constraint line rendering to match Blender's native transforms more closely.
- Improved GPU state handling and cleaned up gizmo rendering.
- Updated trackball rotation arrows to use the corresponding axis colors.
- Refined trackball rotation calculations and cleaned up internal transform code.

### Fixed

- Fixed stale trackball state when handing off between rotation modes.
- Fixed incomplete cleanup when cancelling modal transformations.
- Fixed transformation overlays rendering incorrectly across different 3D Viewports.
- Fixed rotation snapping not updating immediately when modifier keys change.
- Fixed precision issues with small-angle rotations to better match Blender's native behavior.

<br>

## [1.0.0] - 2026-09-26

### Added

- Initial public release of 3D Cursor Transform.
- Native-style transform system for the 3D Cursor:
  - Move and rotate support using G and R.
  - Axis and plane constraints.
  - Global and Local transform orientations.
  - Orientation switching by pressing an axis key twice.
  - MMB axis selection.
  - Numeric input.
  - Arrow key adjustments during transformations.
  - Precision control.
  - Snapping support.
  - Move, Rotate, and combined transform gizmos.
  - Reset location with Alt+G.
  - Reset rotation with Alt+R.
- Compatible with Blender 4.5 and later.
- Open-source release under GPL-3.0-or-later.
