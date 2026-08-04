# -----------------------------------------------------------------------------
# 3D Cursor Transform
#
# Brings Blender's native transform system to the 3D Cursor.
# Supports translation, rotation, transform constraints, snapping, and ghost previews.
#
# SPDX-License-Identifier: GPL-3.0-or-later
# -----------------------------------------------------------------------------

bl_info = {
    "name": "3D Cursor Transform",
    "author": "VertexCuriosity",
    "version": (1, 0, 0),
    "blender": (4, 5, 0),
    "location": "View3D > Cursor Tool",
    "description": "Bring Blender's native transform system to the 3D Cursor with gizmos, constraints, and snapping.",
    "category": "3D View",
}


import math

import bpy
import gpu
from bpy.app.handlers import persistent
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Quaternion, Vector


# ─────────────────────────────────────────────────────────────────────────────
# Globals
# ─────────────────────────────────────────────────────────────────────────────

# ── Module constants ─────────────────────────────────────────────────────────

# Transform constraints and orientation
AXIS_ROT = {
    "X": Matrix.Rotation(math.radians(90.0), 4, "Y"),
    "Y": Matrix.Rotation(math.radians(-90.0), 4, "X"),
    "Z": Matrix.Identity(4),
}

AXIS_INDEX = {
    "X": 0,
    "Y": 1,
    "Z": 2,
}

AXIS_CONSTRAINT = {
    "X": (True, False, False),
    "Y": (False, True, False),
    "Z": (False, False, True),
}

PLANE_CONSTRAINT = {
    "XY": (True, True, False),
    "XZ": (True, False, True),
    "YZ": (False, True, True),
}

PLANE_OFFSET = {
    "XY": Vector((5.0, 5.0, 0.0)),
    "XZ": Vector((5.0, 0.0, 5.0)),
    "YZ": Vector((0.0, 5.0, 5.0)),
}

PLANE_ROT = {
    "XY": Matrix.Identity(4),
    "XZ": Matrix.Rotation(math.radians(90.0), 4, "X"),
    "YZ": Matrix.Rotation(math.radians(90.0), 4, "Y"),
}

PLANE_NORMAL_AXIS = {
    "XY": "Z",
    "XZ": "Y",
    "YZ": "X",
}

# Modal operator identifiers and input mapping
_NATIVE_ROTATE_IDNAMES = frozenset({
    "TRANSFORM_OT_rotate",
    "TRANSFORM_OT_trackball",
})

_TRANSLATE_MODAL_IDNAMES = frozenset({
    "TRANSFORM_OT_translate",
    "CURSORTRANSFORM_OT_translate_modal",
})

_NUMERIC_DIGIT_MAP = {
    'ZERO': '0', 'ONE': '1', 'TWO': '2', 'THREE': '3', 'FOUR': '4',
    'FIVE': '5', 'SIX': '6', 'SEVEN': '7', 'EIGHT': '8', 'NINE': '9',
    'NUMPAD_0': '0', 'NUMPAD_1': '1', 'NUMPAD_2': '2', 'NUMPAD_3': '3',
    'NUMPAD_4': '4', 'NUMPAD_5': '5', 'NUMPAD_6': '6', 'NUMPAD_7': '7',
    'NUMPAD_8': '8', 'NUMPAD_9': '9',
}

# Cursor alignment
CURSOR_ALIGN_LOCATION_EPSILON = 1e-5

# Shared gizmo opacity
AXIS_IDLE_ALPHA = 0.5
AXIS_ACTIVE_ALPHA = 1.0

GHOST_AXIS_ALPHA = 0.5
GHOST_PLANE_FILL_ALPHA = 0.18
GHOST_PLANE_OUTLINE_ALPHA = 0.5

# Translation plane handles
PLANE_FILL_ALPHA = 0.30
PLANE_OUTLINE_ALPHA = 0.5
PLANE_FILL_HOVER_ALPHA = 0.55
PLANE_OUTLINE_HOVER_ALPHA = 1.0
PLANE_LINE_WIDTH = 1.04
PLANE_SCALE_BASIS = 0.14

# Rotation guide overlay
ROTATE_GUIDE_COLOR = (1.0, 1.0, 1.0, 0.85)
ROTATE_GUIDE_DASH_LENGTH = 4.0
ROTATE_GUIDE_GAP_LENGTH = 4.0
ROTATE_GUIDE_LINE_WIDTH = 1.0

ROTATE_GUIDE_SHADOW_COLOR = (0.0, 0.0, 0.0, 0.75)
ROTATE_GUIDE_SHADOW_OFFSET = Vector((3.0, -2.0))
ROTATE_GUIDE_SHADOW_LINE_WIDTH = 1.0

# Rotation sector visuals
ROTATE_SECTOR_FILL_COLOR = (1.0, 1.0, 1.0, 0.15)
ROTATE_SECTOR_STEPS = 64
ROTATE_SECTOR_START_RADIUS_WIDTH = 0.75
ROTATE_SECTOR_END_RADIUS_WIDTH = 2.0
ROTATE_VIEW_SECTOR_START_RADIUS_WIDTH = 0.5
ROTATE_VIEW_SECTOR_END_RADIUS_WIDTH = 1.75

# Rotation guide sizing
ROTATE_RING_PIXEL_RADIUS = 2.12
ROTATE_VIEW_RING_PIXEL_RADIUS = 2.12
ROTATE_RING_BASIS_SAMPLE = 0.25

# Rotation constraint guide line
ROTATE_CONSTRAINT_LINE_WIDTH = 2.0
ROTATE_CONSTRAINT_AXIS_SAMPLE = 0.25

# MMB axis pickup
# The proximity threshold is measured in screen pixels at 1x DPI.
ROTATE_MMB_AXIS_LINE_DIM_ALPHA = 0.35
ROTATE_MMB_PROXIMITY_THRESHOLD_PX = 30.0

# Rotation ring and free-rotate layout
ROTATE_SECTOR_SCALE_FACTOR = 0.97
ROTATE_VIEW_SECTOR_SCALE_FACTOR = 0.99
FREE_ROTATE_DISC_SCALE_FACTOR = 0.85
FREE_ROTATE_DISC_HOVER_ALPHA = 0.03
FREE_ROTATE_DISC_CENTER_DEADZONE_FACTOR = 0.36

# Rotation snapping and tick marks
ROTATE_SNAP_STEP = math.radians(5.0)
ROTATE_TICK_COLOR = (1.0, 1.0, 1.0, 0.95)

# Tick geometry
# Length and offset use local ring-radius units; width uses screen pixels.
ROTATE_TICK_OFFSET_LOCAL = 0.10
ROTATE_TICK_LENGTH_LOCAL = 0.10
ROTATE_TICK_WIDTH_PX = 1.0

ROTATE_VIEW_TICK_OFFSET_LOCAL = 0.10
ROTATE_VIEW_TICK_LENGTH_LOCAL = 0.10
ROTATE_VIEW_TICK_WIDTH_PX = 1.0


# ── Runtime state ────────────────────────────────────────────────────────────

# 3D Cursor alignment tracking
_CURSOR_ALIGN_KNOWN_OBJECTS = set()
_CURSOR_ALIGN_LAST_LOCATIONS = {}
_CURSOR_ALIGN_SCENE_POINTER = None
_CURSOR_ALIGN_INITIALIZED = False
_CURSOR_ALIGN_IS_RUNNING = False

# Translation modal state
_TRANSLATE_GHOST_START_LOC = None
_TRANSLATE_GHOST_START_ORIENT = None

# Rotation modal state
_ROTATE_ACTIVE_ORIENT = None
_ROTATE_ACTIVE_VIEW = None
_ROTATE_GUIDE_START_ANGLE = 0.0
_ROTATE_GUIDE_TOTAL_ANGLE = 0.0
_ROTATE_GUIDE_CTRL_PRESSED = False

# MMB axis-pickup state
_ROTATE_MMB_HELD = False

# Previous constraint restored when leaving trackball rotation
_ROTATE_PREVIOUS_AXIS = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

# ── Cursor alignment helpers ─────────────────────────────────────────────────

def get_addon_preferences(context):
    preferences = getattr(context, "preferences", None)
    if preferences is None:
        return None

    addon = preferences.addons.get(__name__)
    return addon.preferences if addon else None

def cursor_align_rotation_enabled(context):
    preferences = get_addon_preferences(context)
    return bool(
        preferences
        and preferences.align_added_snapped_to_cursor_rotation
    )


def clear_cursor_align_cache():
    """Clear the cached cursor-alignment state."""
    global _CURSOR_ALIGN_SCENE_POINTER
    global _CURSOR_ALIGN_INITIALIZED

    _CURSOR_ALIGN_KNOWN_OBJECTS.clear()
    _CURSOR_ALIGN_LAST_LOCATIONS.clear()

    _CURSOR_ALIGN_SCENE_POINTER = None
    _CURSOR_ALIGN_INITIALIZED = False


def initialize_cursor_align_cache(scene):
    """Cache the objects and their locations without modifying them."""
    global _CURSOR_ALIGN_SCENE_POINTER
    global _CURSOR_ALIGN_INITIALIZED

    current_objects = set(scene.objects)

    _CURSOR_ALIGN_KNOWN_OBJECTS.clear()
    _CURSOR_ALIGN_KNOWN_OBJECTS.update(current_objects)

    _CURSOR_ALIGN_LAST_LOCATIONS.clear()
    for obj in current_objects:
        _CURSOR_ALIGN_LAST_LOCATIONS[obj] = (
            obj.matrix_world.translation.copy()
        )

    _CURSOR_ALIGN_SCENE_POINTER = scene.as_pointer()
    _CURSOR_ALIGN_INITIALIZED = True


def initialize_cursor_align_cache_after_register():
    """
    Initialize cursor-alignment tracking after Blender has restored
    access to the active context following add-on registration.
    """
    context = bpy.context
    scene = getattr(context, "scene", None)

    if scene is None:
        # Try again shortly if Blender has not restored the active scene yet.
        return 0.1

    if cursor_align_rotation_enabled(context):
        initialize_cursor_align_cache(scene)
    else:
        clear_cursor_align_cache()

    return None


def update_cursor_align_preference(_preferences, context):
    """
    Initialize tracking immediately when cursor alignment is enabled,
    and discard it when the option is disabled.
    """
    scene = getattr(context, "scene", None)

    if scene is None:
        clear_cursor_align_cache()
        return

    if cursor_align_rotation_enabled(context):
        initialize_cursor_align_cache(scene)
    else:
        clear_cursor_align_cache()


def object_is_at_cursor_location(obj, cursor):
    distance = (
        obj.matrix_world.translation
        - cursor.location
    ).length

    return distance <= CURSOR_ALIGN_LOCATION_EPSILON


def align_object_rotation_to_cursor(obj, cursor):
    """
    Match an object's world rotation to the 3D Cursor while preserving
    its world location and scale.
    """
    location = obj.matrix_world.to_translation()
    scale = obj.matrix_world.to_scale()

    rotation = cursor.matrix.copy()
    rotation.translation = (0.0, 0.0, 0.0)

    obj.matrix_world = (
        Matrix.Translation(location)
        @ rotation
        @ Matrix.Diagonal((scale.x, scale.y, scale.z, 1.0))
    )


@persistent
def cursor_align_rotation_handler(scene, _depsgraph):
    """
    Match the rotation of objects added at or moved to the 3D Cursor
    when the alignment preference is enabled.
    """
    global _CURSOR_ALIGN_IS_RUNNING

    if _CURSOR_ALIGN_IS_RUNNING:
        return

    context = bpy.context

    # Avoid tracking scene objects while the feature is disabled.
    if not cursor_align_rotation_enabled(context):
        if _CURSOR_ALIGN_INITIALIZED:
            clear_cursor_align_cache()
        return

    scene_pointer = scene.as_pointer()

    # Initialize safely after loading or entering a different scene.
    if (
        not _CURSOR_ALIGN_INITIALIZED
        or _CURSOR_ALIGN_SCENE_POINTER != scene_pointer
    ):
        initialize_cursor_align_cache(scene)
        return

    current_objects = set(scene.objects)
    new_objects = current_objects - _CURSOR_ALIGN_KNOWN_OBJECTS
    cursor = scene.cursor

    _CURSOR_ALIGN_IS_RUNNING = True

    try:
        for obj in current_objects:
            previous_location = _CURSOR_ALIGN_LAST_LOCATIONS.get(obj)
            current_location = obj.matrix_world.translation.copy()

            location_changed = (
                previous_location is not None
                and (
                    current_location - previous_location
                ).length > CURSOR_ALIGN_LOCATION_EPSILON
            )

            added_at_cursor = (
                obj in new_objects
                and object_is_at_cursor_location(obj, cursor)
            )

            moved_to_cursor = (
                location_changed
                and object_is_at_cursor_location(obj, cursor)
            )

            if added_at_cursor or moved_to_cursor:
                align_object_rotation_to_cursor(obj, cursor)

            _CURSOR_ALIGN_LAST_LOCATIONS[obj] = (
                obj.matrix_world.translation.copy()
            )

        _CURSOR_ALIGN_KNOWN_OBJECTS.clear()
        _CURSOR_ALIGN_KNOWN_OBJECTS.update(current_objects)

        # Remove deleted objects from the location cache.
        for obj in tuple(_CURSOR_ALIGN_LAST_LOCATIONS):
            if obj not in current_objects:
                del _CURSOR_ALIGN_LAST_LOCATIONS[obj]

    finally:
        _CURSOR_ALIGN_IS_RUNNING = False


# ── Context, viewport, and modal state ───────────────────────────────────────

def active_tool_is_cursor(context):
    workspace = getattr(context, "workspace", None)
    mode = getattr(context, "mode", None)

    if workspace is None or mode is None:
        return False

    tool = workspace.tools.from_space_view3d_mode(
        mode,
        create=False,
    )

    return tool is not None and tool.idname == "builtin.cursor"


def viewport_allows_gizmo(context):
    space = getattr(context, "space_data", None)

    if space is None or space.type != 'VIEW_3D':
        return False

    return (
        getattr(space, "show_gizmo", True)
        and getattr(space, "show_gizmo_tool", True)
    )


def location_gizmo_enabled(context):
    space = getattr(context, "space_data", None)

    if space is None or space.type != 'VIEW_3D':
        return False

    return getattr(space, "show_gizmo_object_translate", True)


def rotation_gizmo_enabled(context):
    space = getattr(context, "space_data", None)

    if space is None or space.type != 'VIEW_3D':
        return False

    return getattr(space, "show_gizmo_object_rotate", True)


def modal_operator_running(context, operator_idnames):
    """Return whether one of the given modal operators is active."""
    window = getattr(context, "window", None)

    if window is None:
        return False

    return any(
        getattr(operator, "bl_idname", "") in operator_idnames
        for operator in getattr(window, "modal_operators", ())
    )


def translate_modal_running(context):
    """Return whether a native or custom translation modal is active."""
    return modal_operator_running(
        context,
        _TRANSLATE_MODAL_IDNAMES,
    )


def native_rotate_modal_running(context):
    """Return whether Blender's native rotate or trackball modal is active."""
    return modal_operator_running(
        context,
        _NATIVE_ROTATE_IDNAMES,
    )


# ── Orientation helpers ──────────────────────────────────────────────────────

def get_orient_type(context):
    slots = context.scene.transform_orientation_slots
    return slots[0].type if slots else 'GLOBAL'


def get_cursor_rot_matrix(context):
    """Return the 3D Cursor rotation as a 4×4 matrix."""
    matrix = context.scene.cursor.matrix.copy()
    matrix.translation = (0.0, 0.0, 0.0)
    return matrix


def get_view_rot_matrix(context):
    """Return the viewport rotation as a 4×4 matrix."""
    region_data = context.region_data

    if region_data is None:
        return Matrix.Identity(4)

    return region_data.view_rotation.to_matrix().to_4x4()


def build_orient_matrix(context):
    """
    Return the active transform basis used by the cursor operators.

    Global uses the identity matrix, View uses the viewport rotation,
    and unsupported orientations fall back to the cursor's local rotation.
    """
    orient_type = get_orient_type(context)

    if orient_type == 'GLOBAL':
        return Matrix.Identity(4)

    if orient_type == 'VIEW':
        return get_view_rot_matrix(context)

    return get_cursor_rot_matrix(context)


def build_alternate_orient_matrix(context):
    """Return the second-press axis-constraint orientation."""
    if get_orient_type(context) == 'GLOBAL':
        return get_cursor_rot_matrix(context)

    return Matrix.Identity(4)


def alternate_orient_label(context):
    """Return the label for the second-press axis orientation."""
    if get_orient_type(context) == 'GLOBAL':
        return "Local"

    return "Global"


# ── Cursor rotation helpers ──────────────────────────────────────────────────

def get_cursor_quaternion(cursor):
    """Return the cursor rotation as a quaternion."""
    rotation_mode = cursor.rotation_mode

    if rotation_mode == 'QUATERNION':
        return cursor.rotation_quaternion.copy()

    if rotation_mode == 'AXIS_ANGLE':
        angle = cursor.rotation_axis_angle[0]
        axis = Vector(cursor.rotation_axis_angle[1:4]).normalized()
        return Quaternion(axis, angle)

    return cursor.rotation_euler.to_quaternion()


def cache_cursor_rotation_state(cursor):
    """Cache the cursor rotation state for a modal operation."""
    rotation_mode = cursor.rotation_mode

    if rotation_mode == 'QUATERNION':
        start_rotation = cursor.rotation_quaternion.copy()
    elif rotation_mode == 'AXIS_ANGLE':
        start_rotation = tuple(cursor.rotation_axis_angle)
    else:
        start_rotation = cursor.rotation_euler.copy()

    return {
        "rot_mode": rotation_mode,
        "start_rot": start_rotation,
        "start_quat": get_cursor_quaternion(cursor),
        "start_euler_compat": cursor.rotation_euler.copy(),
    }


def set_cursor_from_quaternion(cursor, quaternion, euler_compat):
    """Apply a quaternion while preserving the cursor's rotation mode."""
    rotation_mode = cursor.rotation_mode

    if rotation_mode == 'QUATERNION':
        cursor.rotation_quaternion = quaternion
        return

    if rotation_mode == 'AXIS_ANGLE':
        axis, angle = quaternion.to_axis_angle()
        cursor.rotation_axis_angle = (
            angle,
            axis.x,
            axis.y,
            axis.z,
        )
        return

    cursor.rotation_euler = quaternion.to_euler(
        rotation_mode,
        euler_compat,
    )


def restore_cursor_rotation(cursor, rotation_mode, start_rotation):
    """Restore a previously cached cursor rotation."""
    if rotation_mode == 'QUATERNION':
        cursor.rotation_quaternion = start_rotation
    elif rotation_mode == 'AXIS_ANGLE':
        cursor.rotation_axis_angle = start_rotation
    else:
        cursor.rotation_euler = start_rotation


# ── Modal operation helpers ──────────────────────────────────────────────────

def tag_viewport_redraw(context):
    """Redraw the active viewport region and area when available."""
    if context.region is not None:
        context.region.tag_redraw()

    if context.area is not None:
        context.area.tag_redraw()


def cleanup_rotation_modal(context):
    """Clear shared rotation state and restore the viewport UI."""
    global _ROTATE_PREVIOUS_AXIS
    _ROTATE_PREVIOUS_AXIS = None

    window_manager = context.window_manager
    window_manager.cursortransform_active_rotate_axis = ""

    if context.area is not None:
        context.area.header_text_set(None)

    if context.window is not None:
        context.window.cursor_modal_restore()

    if context.workspace is not None:
        context.workspace.status_text_set(None)

    tag_viewport_redraw(context)


def handle_numeric_key(key, numeric_input, numeric_active):
    """
    Process a keypress for modal numeric input.

    Return the updated input, active state, confirmation state,
    and whether the key was consumed.
    """
    if key in _NUMERIC_DIGIT_MAP:
        return numeric_input + _NUMERIC_DIGIT_MAP[key], True, False, True

    if key in {'PERIOD', 'NUMPAD_PERIOD'}:
        if '.' not in numeric_input:
            return numeric_input + '.', True, False, True

        return numeric_input, numeric_active, False, True

    if key in {'MINUS', 'NUMPAD_MINUS'}:
        if numeric_input.startswith('-'):
            return numeric_input[1:], True, False, True

        return '-' + numeric_input, True, False, True

    if key == 'BACK_SPACE' and numeric_active:
        updated_input = numeric_input[:-1]

        if updated_input in ('', '-'):
            return '', False, False, True

        return updated_input, True, False, True

    if key in {'RET', 'NUMPAD_ENTER'}:
        return numeric_input, numeric_active, True, True

    return numeric_input, numeric_active, False, False


def parse_numeric_input(numeric_input):
    """Convert modal numeric input to a float."""
    if numeric_input in ('', '-'):
        return 0.0

    try:
        return float(numeric_input)
    except ValueError:
        return 0.0


def switch_native_rotate_to_translate(context, axis=None):
    """Finish cursor rotation and start native cursor translation."""
    cleanup_rotation_modal(context)

    if axis in {"X", "Y", "Z"}:
        bpy.ops.cursortransform.translate(
            'INVOKE_DEFAULT',
            axis=axis,
            release_confirm=False,
        )
        return

    bpy.ops.cursortransform.translate_free(
        'INVOKE_DEFAULT',
        release_confirm=False,
    )


# ── Status bar helpers ───────────────────────────────────────────────────────

def _draw_status_rotate_common(
    header,
    context,
    rotation_label,
    show_constraint_tools=True,
):
    """Draw the shared rotation shortcuts in the status bar."""
    row = header.layout.row(align=True)

    # Confirm
    row.label(text="", icon='MOUSE_LMB')
    row.label(text="Confirm")

    row.separator()

    # Cancel
    row.label(text="", icon='MOUSE_RMB')
    row.label(text="/")
    row.label(text="", icon='EVENT_ESC')
    row.label(text="   Cancel")

    row.separator()

    if show_constraint_tools:
        window_manager = context.window_manager
        has_constraint = (
            window_manager.cursortransform_active_rotate_axis
            in {"X", "Y", "Z"}
        )

        # Axis constraints
        row.label(text="", icon='EVENT_X')
        row.label(text="", icon='EVENT_Y')
        row.label(text="", icon='EVENT_Z')
        row.label(text="Axis")

        row.separator()

        # Clear constraints
        if has_constraint:
            row.label(text="", icon='EVENT_C')
            row.label(text="Clear Constraints")

            row.separator()

        # Automatic constraint
        row.label(text="", icon='MOUSE_MMB')
        row.label(text="Automatic Constraint")

        row.separator()

    # Snap
    row.label(text="", icon='EVENT_CTRL')
    row.label(text="   Snap Invert")

    row.separator()

    # Move
    row.label(text="", icon='EVENT_G')
    row.label(text="Move")

    row.separator()

    # Rotation mode
    row.label(text="", icon='EVENT_R')
    row.label(text=rotation_label)

    row.separator()

    # Precision mode
    row.label(text="", icon='KEY_SHIFT')
    row.label(text="Precision Mode")


def draw_status_rotate_axis(header, context):
    _draw_status_rotate_common(
        header,
        context,
        "Trackball",
        show_constraint_tools=True,
    )


def draw_status_rotate_free(header, context):
    _draw_status_rotate_common(
        header,
        context,
        "Rotate",
        show_constraint_tools=False,
    )


def draw_status_translate(header, context):
    """Draw the translation shortcuts in the status bar."""
    row = header.layout.row(align=True)

    window_manager = context.window_manager
    has_constraint = (
        window_manager.cursortransform_active_translate_axis != ""
    )

    # Confirm
    row.label(text="", icon='MOUSE_LMB')
    row.label(text="Confirm")

    row.separator()

    # Cancel
    row.label(text="", icon='MOUSE_RMB')
    row.label(text="/")
    row.label(text="", icon='EVENT_ESC')
    row.label(text="   Cancel")

    row.separator()

    # Axis constraints
    row.label(text="", icon='EVENT_X')
    row.label(text="", icon='EVENT_Y')
    row.label(text="", icon='EVENT_Z')
    row.label(text="Axis")

    row.separator()

    # Plane constraints
    row.label(text="", icon='KEY_SHIFT')
    row.label(text="", icon='EVENT_X')
    row.label(text="", icon='EVENT_Y')
    row.label(text="", icon='EVENT_Z')
    row.label(text="Plane")

    row.separator()

    # Clear constraints
    if has_constraint:
        row.label(text="", icon='EVENT_C')
        row.label(text="Clear Constraints")

        row.separator()

    # Snap invert
    row.label(text="", icon='EVENT_CTRL')
    row.label(text="   Snap Invert")

    row.separator()

    # Snap toggle
    row.label(text="", icon='KEY_SHIFT')
    row.label(text="", icon='EVENT_TAB')
    row.label(text="Snap Toggle")

    row.separator()

    # Rotate
    row.label(text="", icon='EVENT_R')
    row.label(text="Rotate")

    row.separator()

    # Automatic constraint
    row.label(text="", icon='MOUSE_MMB')
    row.label(text="Automatic Constraint")

    row.separator()

    # Precision mode
    row.label(text="", icon='KEY_SHIFT')
    row.label(text="Precision Mode")


# ── Gizmo appearance helpers ─────────────────────────────────────────────────

def get_theme_gizmo_colors(context):
    """Return the theme colors used by the transform gizmos."""
    theme = context.preferences.themes[0].user_interface

    return {
        "X": tuple(theme.axis_x)[:3],
        "Y": tuple(theme.axis_y)[:3],
        "Z": tuple(theme.axis_z)[:3],
        "VIEW": tuple(theme.gizmo_view_align)[:3],
    }


def axis_highlight_color(rgb):
    """Brighten an RGB color by blending it toward white."""
    factor = 0.35

    red = rgb[0] + (1.0 - rgb[0]) * factor
    green = rgb[1] + (1.0 - rgb[1]) * factor
    blue = rgb[2] + (1.0 - rgb[2]) * factor

    return (red, green, blue)


def smoothstep(edge_start, edge_end, value):
    """Return a smooth interpolation between two edge values."""
    if edge_start == edge_end:
        return 0.0

    factor = max(
        0.0,
        min(
            1.0,
            (value - edge_start) / (edge_end - edge_start),
        ),
    )

    return factor * factor * (3.0 - 2.0 * factor)


def axis_view_alpha(
    context,
    axis_vector,
    min_alpha=0.0,
    fade_start=0.88,
    fade_end=0.98,
):
    """Fade an axis as it becomes aligned with the view direction."""
    region_data = context.region_data

    if region_data is None:
        return 1.0

    view_direction = (
        region_data.view_rotation
        @ Vector((0.0, 0.0, -1.0))
    ).normalized()

    axis_vector = axis_vector.normalized()
    alignment = abs(axis_vector.dot(view_direction))

    fade = smoothstep(fade_start, fade_end, alignment)
    return (1.0 - fade) + (min_alpha * fade)


def plane_view_alpha(
    context,
    plane_normal,
    min_alpha=0.0,
    fade_start=0.16,
    fade_end=0.26,
):
    """Fade a plane handle as it becomes edge-on to the view."""
    region_data = context.region_data

    if region_data is None:
        return 1.0

    view_direction = (
        region_data.view_rotation
        @ Vector((0.0, 0.0, -1.0))
    ).normalized()

    plane_normal = plane_normal.normalized()
    alignment = abs(plane_normal.dot(view_direction))

    fade = smoothstep(fade_start, fade_end, alignment)
    return min_alpha + ((1.0 - min_alpha) * fade)


# ── 2D overlay geometry and drawing ──────────────────────────────────────────

def _build_sector_fan_vertices(a0, a1, steps):
    """
    Build triangle-fan vertices for a filled circular sector in the local XY plane.
    """
    verts = []
    center = (0.0, 0.0, 0.0)
    prev = None

    for i in range(steps + 1):
        t = i / steps
        a = a0 + (a1 - a0) * t
        p = (math.cos(a), math.sin(a), 0.0)

        if prev is not None:
            verts.extend((center, prev, p))
        prev = p

    return verts


def _build_radius_quad_vertices(angle, width):
    """
    Build triangle vertices for a thin quad that represents a sector radius line
    in the local XY plane.
    """
    half_width = width * 0.01

    direction = Vector((math.cos(angle), math.sin(angle), 0.0))
    normal = Vector((-direction.y, direction.x, 0.0)) * half_width

    p0 = Vector((0.0, 0.0, 0.0)) - normal
    p1 = Vector((0.0, 0.0, 0.0)) + normal
    p2 = direction + normal
    p3 = direction - normal

    return [
        tuple(p0), tuple(p1), tuple(p2),
        tuple(p0), tuple(p2), tuple(p3),
    ]


def _build_circle_fan_vertices(radius, segments):
    """
    Build triangle-fan vertices for a filled circle in the local XY plane.
    """
    verts = []
    center = (0.0, 0.0, 0.0)

    for i in range(segments):
        a0 = (i / segments) * math.tau
        a1 = ((i + 1) / segments) * math.tau

        p0 = (math.cos(a0) * radius, math.sin(a0) * radius, 0.0)
        p1 = (math.cos(a1) * radius, math.sin(a1) * radius, 0.0)

        verts.extend((center, p0, p1))

    return verts


def _draw_dashed_line_2d(start, end, color, dash_len, gap_len, line_width):
    """
    Draw an antialiased dashed line in screen space from `start` to `end`.

    Each dash is rendered as a short solid line through POLYLINE_UNIFORM_COLOR,
    Blender's built-in antialiased line shader. Dash and gap lengths and the
    line width are scaled by preferences.system.pixel_size so that on a
    high-DPI display the dashes don't look thinner / smaller than on a
    standard display. This matches the per-pixel coverage approach Blender's
    own gizmo lines use, eliminating the staircase aliasing the previous
    UNIFORM_COLOR + stitched-segments implementation had.
    """
    if start is None or end is None:
        return

    vec = end - start
    length = vec.length
    if length <= 1e-6:
        return

    # Scale screen-space lengths and widths by pixel_size for DPI-independence.
    # See ROTATE_TICK_WIDTH_PX / pixel_size discussion in the tick gizmo —
    # same multiplier, same reason. context retrieval here is cheap; the
    # alternative would be threading context through every caller.
    pixel_size = bpy.context.preferences.system.pixel_size
    dash_px = dash_len * pixel_size
    gap_px = gap_len * pixel_size
    width_px = line_width * pixel_size

    direction = vec.normalized()
    step = dash_px + gap_px
    if step <= 1e-6:
        return

    # Build each dash as a pair of points. Drawing the dash sequence from the
    # mouse end backward toward the center means partial dashes (when the
    # line length isn't an exact multiple of the pattern) appear at the
    # center end, where the rotation pivot covers them anyway.
    segments = []
    pos = 0.0
    while pos < length:
        seg_end = end - direction * pos
        seg_start = end - direction * min(pos + dash_px, length)
        segments.extend((seg_start, seg_end))
        pos += step

    if not segments:
        return

    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'LINES', {"pos": segments})

    gpu.state.blend_set('ALPHA')

    shader.bind()
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    shader.uniform_float("lineWidth", width_px)
    shader.uniform_float("color", color)
    batch.draw(shader)

    gpu.state.blend_set('NONE')


def _draw_translate_axis_line_op(op):
    """Draw active translate constraint axis line(s) during custom G modal."""
    context = bpy.context

    if op._mmb_held:
        axes_to_draw = ("X", "Y", "Z")
    elif op._axis in {"X", "Y", "Z"}:
        axes_to_draw = (op._axis,)
    elif op._plane_exclude_axis in {"X", "Y", "Z"}:
        axes_to_draw = tuple(
            axis for axis in ("X", "Y", "Z")
            if axis != op._plane_exclude_axis
        )
    else:
        return

    center_2d = view3d_utils.location_3d_to_region_2d(
        context.region,
        context.region_data,
        op._start_loc,
    )
    if center_2d is None:
        return

    half_length_px = float(max(context.region.width, context.region.height) * 2.0)

    axis_colors = get_theme_gizmo_colors(context)
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')

    line_width_scaled = (
        ROTATE_CONSTRAINT_LINE_WIDTH
        * context.preferences.system.pixel_size
    )

    gpu.state.blend_set('ALPHA')

    shader.bind()
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    shader.uniform_float("lineWidth", line_width_scaled)

    for axis in axes_to_draw:
        idx = AXIS_INDEX[axis]
        axis_vec = op._get_active_orient().col[idx].to_3d().normalized()

        dir_2d = _project_axis_dir_2d(
            context,
            op._start_loc,
            axis_vec,
        )
        if dir_2d is None:
            continue

        axis_rgb = axis_highlight_color(axis_colors[axis])

        if op._mmb_held:
            alpha = 1.0 if axis == op._axis else ROTATE_MMB_AXIS_LINE_DIM_ALPHA
        else:
            alpha = 1.0

        color = (axis_rgb[0], axis_rgb[1], axis_rgb[2], alpha)

        p0 = Vector((
            center_2d.x - dir_2d.x * half_length_px,
            center_2d.y - dir_2d.y * half_length_px,
        ))
        p1 = Vector((
            center_2d.x + dir_2d.x * half_length_px,
            center_2d.y + dir_2d.y * half_length_px,
        ))

        batch = batch_for_shader(shader, 'LINES', {"pos": [p0, p1]})
        shader.uniform_float("color", color)
        batch.draw(shader)

    gpu.state.blend_set('NONE')


# ── 2D ring and rotation math ────────────────────────────────────────────────

def _solve_2d_basis(vec, basis_x, basis_y):
    """
    Solve vec = basis_x * u + basis_y * v in 2D.
    Returns (u, v), or None if the basis is degenerate.
    """
    det = basis_x.x * basis_y.y - basis_x.y * basis_y.x
    if abs(det) < 1e-8:
        return None

    u = (vec.x * basis_y.y - vec.y * basis_y.x) / det
    v = (basis_x.x * vec.y - basis_x.y * vec.x) / det
    return u, v


def _wrap_pi(angle):
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _ellipse_angle_from_mouse(center, mouse, basis_x, basis_y):
    """
    Return the angular mouse position on a projected ring ellipse in screen space.

    The returned angle is measured in the local 2D basis defined by basis_x and
    basis_y, or None if the basis cannot be solved reliably.
    """
    if center is None or mouse is None or basis_x is None or basis_y is None:
        return None

    coeff = _solve_2d_basis(mouse - center, basis_x, basis_y)
    if coeff is None:
        return None

    u, v = coeff
    if abs(u) < 1e-8 and abs(v) < 1e-8:
        return None

    return math.atan2(v, u)


def _map_to_arcball(center_2d, mouse_2d, radius_px):
    """
    Map a 2D mouse position to a virtual unit sphere centered on center_2d.
    Points outside the sphere are projected onto the sphere rim.
    """
    if center_2d is None or mouse_2d is None or radius_px <= 1e-6:
        return None

    x = (mouse_2d.x - center_2d.x) / radius_px
    y = (mouse_2d.y - center_2d.y) / radius_px

    d = x * x + y * y

    if d <= 1.0:
        z = math.sqrt(1.0 - d)
        return Vector((x, y, z)).normalized()

    inv_len = 1.0 / math.sqrt(d)
    return Vector((x * inv_len, y * inv_len, 0.0)).normalized()


# ── Screen-space projection helpers ──────────────────────────────────────────

def _build_screen_space_ring_basis(context, center_2d, center_3d, ring_m, pixel_radius):
    """
    Build a 2D ellipse basis for the rotation overlay that keeps a fixed size
    in screen pixels, while still following the frozen 3D ring orientation.
    """
    if center_2d is None:
        return None, None

    sample = ROTATE_RING_BASIS_SAMPLE

    px_2d = view3d_utils.location_3d_to_region_2d(
        context.region, context.region_data,
        center_3d + ring_m.col[0].to_3d() * sample
    )
    py_2d = view3d_utils.location_3d_to_region_2d(
        context.region, context.region_data,
        center_3d + ring_m.col[1].to_3d() * sample
    )

    if px_2d is None or py_2d is None:
        return None, None

    vx = px_2d - center_2d
    vy = py_2d - center_2d

    len_x = vx.length
    len_y = vy.length

    if len_x <= 1e-6 or len_y <= 1e-6:
        return None, None

    # Keep the longest projected axis at the requested pixel radius and scale the
    # other proportionally so the ring preserves its projected ellipse shape while
    # remaining visually independent from viewport zoom.
    max_len = max(len_x, len_y)

    basis_x_2d = vx.normalized() * (pixel_radius * (len_x / max_len))
    basis_y_2d = vy.normalized() * (pixel_radius * (len_y / max_len))

    return basis_x_2d, basis_y_2d


def _project_axis_dir_2d(context, center_3d, axis_vec):
    """
    Project a 3D axis direction into a normalized 2D screen-space vector
    starting from the given world-space center.
    """
    center_2d = view3d_utils.location_3d_to_region_2d(
        context.region, context.region_data, center_3d
    )
    tip_2d = view3d_utils.location_3d_to_region_2d(
        context.region, context.region_data,
        center_3d + axis_vec.normalized() * ROTATE_CONSTRAINT_AXIS_SAMPLE
    )

    if center_2d is None or tip_2d is None:
        return None

    vec_2d = tip_2d - center_2d
    if vec_2d.length <= 1e-6:
        return None

    return vec_2d.normalized()


def _closest_axis_to_mouse(mouse_2d, center_2d, axis_dirs_2d, threshold_px):
    """
    Return the axis label ("X", "Y", "Z") of the projected axis line nearest
    to the mouse position in screen space, or None if none is within the
    threshold.

    Each axis is treated as an infinite line through center_2d in the
    direction given in axis_dirs_2d. Distance is the standard 2D point-to-
    line distance (perpendicular). When two or more axes are within the
    threshold the closest one wins; ties (rare in practice — would require
    two axes projecting to the same screen direction) are broken by axis
    enumeration order X, Y, Z.

    Used during MMB axis pickup to determine which axis the user is
    currently hovering near. axis_dirs_2d is expected to be a dict mapping
    "X"/"Y"/"Z" to a unit-length 2D Vector; entries that are None (e.g.
    when an axis projects to a degenerate direction because we're looking
    straight down it) are skipped.
    """
    if mouse_2d is None or center_2d is None:
        return None

    rel = mouse_2d - center_2d

    best_axis = None
    best_dist = float("inf")

    for axis in ("X", "Y", "Z"):
        direction = axis_dirs_2d.get(axis) if axis_dirs_2d else None
        if direction is None:
            continue

        # Perpendicular distance from rel to the line through origin with
        # direction `direction`. With direction unit-length, this is just
        # |rel.x * dir.y - rel.y * dir.x|.
        perp = abs(rel.x * direction.y - rel.y * direction.x)

        if perp < best_dist:
            best_dist = perp
            best_axis = axis

    if best_dist <= threshold_px:
        return best_axis
    return None


# ── Rotation guide drawing ───────────────────────────────────────────────────

def _draw_shortcut_axis_line(op):
    """
    Draw the constraint axis line(s) as a fallback when the gizmo system
    isn't running (master gizmo overlay toggled off, or all gizmo sub-
    toggles disabled). In that state the gizmo group's poll never passes,
    so CURSORTRANSFORM_GT_axis_line never draws — and we'd lose the
    visual feedback that tells the user "the rotation is constrained to X."

    Two distinct visual modes, mirroring the gizmo group's behavior:
      - Normal rotation (MMB not held): only the active axis line is drawn,
        fully colored. Nothing is drawn for VIEW/FREE rotation.
      - MMB axis pickup hold: all three X/Y/Z axis lines drawn together;
        the currently active axis (which switches in real time as the
        mouse approaches a different axis line — see
        _maybe_switch_axis_by_proximity) is at full alpha, the other two
        dimmed to ROTATE_MMB_AXIS_LINE_DIM_ALPHA. During VIEW rotation
        with MMB held, all three appear dimmed since no X/Y/Z is "active."

    Drawn as 2D screen-space lines because we're inside a POST_PIXEL draw
    handler. Projecting each axis direction to 2D up front via
    view3d_utils sidesteps the screen-space-vs-world-space mismatch that
    bit an earlier 3D-shader version of this function.

    Only fires when the gizmo group is NOT going to draw the axis line
    itself (i.e. the gizmo group's poll would fail).
    """
    context = bpy.context

    # Mirror the gizmo group's poll condition: the gizmo system only draws
    # axis lines when the master overlay is on AND at least one of the
    # location/rotation sub-toggles is on. If either part fails, the
    # shortcut fallback (this function) is responsible for drawing them.
    gizmo_will_draw_axis_line = (
        viewport_allows_gizmo(context)
        and (location_gizmo_enabled(context) or rotation_gizmo_enabled(context))
    )
    if gizmo_will_draw_axis_line:
        return

    # Decide which axes need drawing this frame.
    if _ROTATE_MMB_HELD:
        axes_to_draw = ("X", "Y", "Z")
    elif op.axis in {"X", "Y", "Z"}:
        axes_to_draw = (op.axis,)
    else:
        # VIEW or FREE rotation with MMB not held — no axis line.
        return

    center_2d = view3d_utils.location_3d_to_region_2d(
        context.region, context.region_data, op._start_loc
    )
    if center_2d is None:
        # Cursor pivot projects behind the camera; nothing meaningful to draw.
        return

    # Half-length larger than any reasonable region dimension guarantees
    # both endpoints exit the visible area.
    half_length_px = float(
        max(context.region.width, context.region.height) * 2.0
    )

    line_width_scaled = (
        ROTATE_CONSTRAINT_LINE_WIDTH
        * context.preferences.system.pixel_size
    )

    axis_colors = get_theme_gizmo_colors(context)
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')

    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    shader.uniform_float("lineWidth", line_width_scaled)

    for axis in axes_to_draw:
        # Project this axis from world space to a 2D screen direction.
        # We construct the world axis vector inline rather than calling
        # _get_frozen_axis_vector because that helper only knows about
        # op.axis — the currently active axis — and during MMB hold we
        # need to project all three.
        idx = AXIS_INDEX[axis]
        world_axis = op._get_active_orient().col[idx].to_3d().normalized()
        dir_2d = _project_axis_dir_2d(context, op._start_loc, world_axis)

        if dir_2d is None:
            # Axis projects to a degenerate screen direction (we're looking
            # straight along it). Skip — there's no meaningful line to draw.
            continue

        # Alpha: full for the active axis, dimmed for the others when
        # MMB is held. When MMB isn't held we only loop over the active
        # axis so the dim path is never reached in that case.
        if axis == op.axis:
            alpha = 1.0
        else:
            alpha = ROTATE_MMB_AXIS_LINE_DIM_ALPHA

        rgb = axis_highlight_color(axis_colors[axis])
        color = (rgb[0], rgb[1], rgb[2], alpha)

        p0 = Vector((
            center_2d.x - dir_2d.x * half_length_px,
            center_2d.y - dir_2d.y * half_length_px,
        ))
        p1 = Vector((
            center_2d.x + dir_2d.x * half_length_px,
            center_2d.y + dir_2d.y * half_length_px,
        ))

        batch = batch_for_shader(shader, 'LINES', {"pos": [p0, p1]})
        shader.uniform_float("color", color)
        batch.draw(shader)

    gpu.state.blend_set('NONE')


def _rotate_guide_draw_op(op):
    """
    Draw the active rotation guide overlay for the running modal operator.

    This includes the dashed mouse guide, the full-screen constraint axis line,
    and the optional Ctrl-snap tick marks.
    """
    center = op._guide_center_2d
    mouse = op._guide_mouse_2d

    if center is None or mouse is None:
        return

    # Constraint axis line — drawn here only when the master gizmo overlay
    # is OFF (gizmo system bypassed). When the overlay is on, the gizmo
    # group's CURSORTRANSFORM_GT_axis_line handles it instead, with proper
    # layering relative to the rings/wedge/ticks. Drawing the axis line
    # FIRST in this handler ensures the dashed mouse guide appears on top.
    _draw_shortcut_axis_line(op)

    # Tick marks (Ctrl-snap) are still drawn by CURSORTRANSFORM_GT_rotate_ticks
    # when the gizmo system is running. They have no shortcut-mode fallback;
    # tick marks during gizmo-disabled rotation aren't part of native Blender's
    # behavior either.

    shadow_start = center + ROTATE_GUIDE_SHADOW_OFFSET
    shadow_end = mouse + ROTATE_GUIDE_SHADOW_OFFSET

    # Dashed line
    _draw_dashed_line_2d(
        shadow_start,
        shadow_end,
        ROTATE_GUIDE_SHADOW_COLOR,
        ROTATE_GUIDE_DASH_LENGTH,
        ROTATE_GUIDE_GAP_LENGTH,
        ROTATE_GUIDE_SHADOW_LINE_WIDTH,
    )

    _draw_dashed_line_2d(
        center,
        mouse,
        ROTATE_GUIDE_COLOR,
        ROTATE_GUIDE_DASH_LENGTH,
        ROTATE_GUIDE_GAP_LENGTH,
        ROTATE_GUIDE_LINE_WIDTH,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Add-on Preferences
# ─────────────────────────────────────────────────────────────────────────────

class CURSORTRANSFORM_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    align_added_snapped_to_cursor_rotation: bpy.props.BoolProperty(
        name="Match 3D Cursor rotation",
        description=("Objects added at or snapped to the 3D Cursor will also match its rotation"),
        default=False,
        update=update_cursor_align_preference,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "align_added_snapped_to_cursor_rotation")


# ─────────────────────────────────────────────────────────────────────────────
# Rotation Operators
# ─────────────────────────────────────────────────────────────────────────────

class CURSORTRANSFORM_OT_rotate_modal(bpy.types.Operator):
    """Rotate the 3D Cursor around a frozen axis by dragging."""
    bl_idname  = "cursortransform.rotate_modal"
    bl_label   = "Cursor Rotate"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    axis: bpy.props.StringProperty(default="Z")

    def invoke(self, context, event):
        """
        Initialize the constrained rotation modal state and create the projected
        screen-space guide used during the drag.
        """
        cursor = context.scene.cursor

        # Cache the cursor position so the modal drag starts from a stable state and
        # can restore its guide origin on cancel.
        self._start_loc = cursor.matrix.translation.copy()

        rot_state = cache_cursor_rotation_state(cursor)
        self._rot_mode = rot_state["rot_mode"]
        self._start_rot = rot_state["start_rot"]
        self._start_quat = rot_state["start_quat"]
        self._start_euler_compat = rot_state["start_euler_compat"]

        # Freeze the gizmo orientation basis so the drag remains stable during the
        # modal operation. Both the header orient and the alternate orient are
        # captured here so the 3-state axis-key cycle (1st press = header,
        # 2nd press = alternate, 3rd press = VIEW) can switch between them
        # without re-reading the header at each press.
        self._start_orient = build_orient_matrix(context).copy()
        self._start_orient_alternate = build_alternate_orient_matrix(context).copy()
        self._using_alternate_orient = False
        self._start_view   = get_view_rot_matrix(context).copy()

        global _ROTATE_ACTIVE_ORIENT
        global _ROTATE_ACTIVE_VIEW
        _ROTATE_ACTIVE_ORIENT = self._start_orient.copy()
        _ROTATE_ACTIVE_VIEW = self._start_view.copy()

        # Store the initial guide center and mouse position in region space for the
        # screen-space rotation guide.
        self._guide_center_2d = view3d_utils.location_3d_to_region_2d(
            context.region, context.region_data, self._start_loc
        )
        self._guide_mouse_2d = Vector((event.mouse_region_x, event.mouse_region_y))
        self._guide_start_mouse_2d = self._guide_mouse_2d.copy()

        # Derive the projected guide radius from Blender's gizmo size preference and
        # the active frozen ring orientation.
        gizmo_pref = max(context.preferences.view.gizmo_size, 1)

        if self.axis == "VIEW":
            ring_m = self._start_view.copy()
            pixel_radius = gizmo_pref * ROTATE_VIEW_RING_PIXEL_RADIUS
        else:
            ring_m = self._get_active_orient() @ AXIS_ROT[self.axis]
            pixel_radius = gizmo_pref * ROTATE_RING_PIXEL_RADIUS

        self._guide_basis_x_2d = None
        self._guide_basis_y_2d = None
        self._guide_start_angle = 0.0
        self._guide_total_angle = 0.0

        self._guide_basis_x_2d, self._guide_basis_y_2d = _build_screen_space_ring_basis(
            context,
            self._guide_center_2d,
            self._start_loc,
            ring_m,
            pixel_radius,
        )

        # Solve the initial mouse position on the projected ring so later mouse motion
        # can accumulate angular delta from a stable starting angle.
        if self._guide_center_2d is not None and self._guide_basis_x_2d is not None and self._guide_basis_y_2d is not None:
            coeff = _solve_2d_basis(
                self._guide_start_mouse_2d - self._guide_center_2d,
                self._guide_basis_x_2d,
                self._guide_basis_y_2d,
            )
            if coeff is not None:
                u, v = coeff
                self._guide_start_angle = math.atan2(v, u)

        self._guide_last_mouse_angle = self._guide_start_angle

        global _ROTATE_GUIDE_START_ANGLE
        global _ROTATE_GUIDE_TOTAL_ANGLE
        _ROTATE_GUIDE_START_ANGLE = self._guide_start_angle
        _ROTATE_GUIDE_TOTAL_ANGLE = 0.0
        
        self._guide_axis_dir_2d = None
        self._guide_context = context

        if self.axis in {"X", "Y", "Z"}:
            axis_vec = self._get_frozen_axis_vector()
            self._guide_axis_dir_2d = _project_axis_dir_2d(
                context,
                self._start_loc,
                axis_vec,
            )

        axis_colors = get_theme_gizmo_colors(context)
        self._axis_color_rgb = axis_colors.get(self.axis, (1.0, 1.0, 1.0))

        self._guide_handler = bpy.types.SpaceView3D.draw_handler_add(
            _rotate_guide_draw_op, (self,), 'WINDOW', 'POST_PIXEL'
        )

        context.workspace.status_text_set(draw_status_rotate_axis)

        context.window.cursor_modal_set('MOVE_X')
        wm = context.window_manager
        wm.cursortransform_active_rotate_axis = self.axis
        wm.modal_handler_add(self)
        self._ctrl_pressed = False
        self._numeric_input = ""
        self._numeric_active = False

        # MMB axis-pickup state. _mmb_held is True between MIDDLEMOUSE press
        # and release; _mmb_axis_dirs_2d caches the projected screen-space
        # direction of each X/Y/Z axis from the cursor pivot for proximity
        # detection. The active rotation axis (self.axis) is updated live
        # via _switch_axis_constraint when the mouse approaches a different
        # axis line — there's no separate "preselected" state.
        self._mmb_held = False
        self._mmb_axis_dirs_2d = None
        return {'RUNNING_MODAL'}

    def _remove_guide_handler(self):
        """
        Remove the draw handler and clear all cached guide state for the modal drag.
        """
        if getattr(self, "_guide_handler", None) is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._guide_handler, 'WINDOW')
            self._guide_handler = None

        global _ROTATE_ACTIVE_ORIENT
        global _ROTATE_ACTIVE_VIEW
        _ROTATE_ACTIVE_ORIENT = None
        _ROTATE_ACTIVE_VIEW = None

        global _ROTATE_GUIDE_START_ANGLE
        global _ROTATE_GUIDE_TOTAL_ANGLE
        global _ROTATE_GUIDE_CTRL_PRESSED
        _ROTATE_GUIDE_START_ANGLE = 0.0
        _ROTATE_GUIDE_TOTAL_ANGLE = 0.0
        _ROTATE_GUIDE_CTRL_PRESSED = False

        global _ROTATE_MMB_HELD
        _ROTATE_MMB_HELD = False

        # Clear previous-axis memory used by the trackball R-toggle. The
        # _swap_to_trackball helper re-writes this AFTER calling us so the
        # swap path retains its value; non-swap exit paths (LMB confirm,
        # RMB/ESC cancel) leave the global cleared so a fresh R from idle
        # doesn't restore stale state.
        global _ROTATE_PREVIOUS_AXIS
        _ROTATE_PREVIOUS_AXIS = None

        self._guide_center_2d = None
        self._guide_mouse_2d = None
        self._guide_start_mouse_2d = None
        self._guide_basis_x_2d = None
        self._guide_basis_y_2d = None
        self._guide_start_angle = 0.0
        self._guide_total_angle = 0.0
        self._guide_last_mouse_angle = 0.0
        self._guide_axis_dir_2d = None
        self._guide_context = None

    def _get_active_orient(self):
        """
        Return the orient matrix currently in effect for X/Y/Z rotation
        (header orient on 1st-press cycle state, alternate orient on
        2nd-press). Used by the ring math, the axis-vector helper, and
        the gizmo group's draw_prepare via the _ROTATE_ACTIVE_ORIENT
        global which is kept in sync.
        """
        if self._using_alternate_orient:
            return self._start_orient_alternate
        return self._start_orient

    def _get_frozen_axis_vector(self):
        """
        Return the frozen world-space rotation axis for the active constrained mode.
        """
        if self.axis == "VIEW":
            return (self._start_view @ Vector((0.0, 0.0, 1.0))).normalized()

        idx = AXIS_INDEX[self.axis]
        return self._get_active_orient().col[idx].to_3d().normalized()

    def _update_header_text(self, context, angle):
        deg = math.degrees(angle)

        if self.axis == "VIEW":
            context.area.header_text_set(
                f"Rotation: {deg:.2f}\u00b0"
            )
            return

        if self._using_alternate_orient:
            orient_label = alternate_orient_label(context).lower()
        else:
            orient_label = get_orient_type(context).lower()

        context.area.header_text_set(
            f"Rotation: {deg:.2f}\u00b0 along {orient_label} {self.axis}"
        )

    def _switch_axis_constraint(self, context, event, new_axis, use_alternate_orient=False):
        """
        Switch the active rotation constraint while the modal rotate operator
        keeps running.

        This mimics Blender-style X/Y/Z axis switching during rotation.
        The current cursor rotation becomes the new starting rotation, so the
        switch does not jump back to the original drag start.

        new_axis can be "X", "Y", "Z", or "VIEW". The VIEW case is used by
        the 3-state axis-key cycle: pressing the same axis key three times
        in a row goes header-orient → alternate-orient → VIEW (no constraint).

        use_alternate_orient selects between the header orient (False, the
        default — used for 1st-press cycle state and for fresh axis switches
        like MMB pickup) and the alternate orient (True — used for 2nd-press
        cycle state). The flag is stored on self._using_alternate_orient
        and read by _get_active_orient().
        """
        if new_axis not in {"X", "Y", "Z", "VIEW"}:
            return

        # No-op early return: same axis AND same orient mode means nothing
        # would change. Comparing both is important because we may legitimately
        # call this with the same axis but a different orient flag (cycling
        # 1st-press X to 2nd-press X).
        if self.axis == new_axis and self._using_alternate_orient == use_alternate_orient:
            return

        cursor = context.scene.cursor

        # Use the current rotation as the new baseline.
        self._start_quat = get_cursor_quaternion(cursor)
        self._start_euler_compat = cursor.rotation_euler.copy()

        # Switch active axis and orient mode.
        self.axis = new_axis
        self._using_alternate_orient = use_alternate_orient

        # Keep the gizmo overlay in sync — _ROTATE_ACTIVE_ORIENT drives the
        # gizmo group's drawing of the rotation rings/wedge/ticks. For VIEW
        # the orient isn't used (the view_basis matrix takes its place via
        # the ROTATE_ACTIVE_VIEW global which is already set), but we still
        # keep _ROTATE_ACTIVE_ORIENT pointing at something sensible.
        global _ROTATE_ACTIVE_ORIENT
        _ROTATE_ACTIVE_ORIENT = self._get_active_orient().copy()

        # Reset accumulated angle for the new axis.
        self._guide_total_angle = 0.0

        # Rebuild the 2D guide basis for the new rotation ring. VIEW uses
        # the view-rotation matrix and the larger view-ring radius; X/Y/Z
        # use the active orient and the standard ring radius.
        gizmo_pref = max(context.preferences.view.gizmo_size, 1)
        if self.axis == "VIEW":
            ring_m = self._start_view.copy()
            pixel_radius = gizmo_pref * ROTATE_VIEW_RING_PIXEL_RADIUS
        else:
            ring_m = self._get_active_orient() @ AXIS_ROT[self.axis]
            pixel_radius = gizmo_pref * ROTATE_RING_PIXEL_RADIUS

        self._guide_basis_x_2d, self._guide_basis_y_2d = _build_screen_space_ring_basis(
            context,
            self._guide_center_2d,
            self._start_loc,
            ring_m,
            pixel_radius,
        )

        mouse_now = Vector((event.mouse_region_x, event.mouse_region_y))
        self._guide_mouse_2d = mouse_now

        mouse_angle = _ellipse_angle_from_mouse(
            self._guide_center_2d,
            mouse_now,
            self._guide_basis_x_2d,
            self._guide_basis_y_2d,
        )

        if mouse_angle is None:
            mouse_angle = 0.0

        self._guide_start_angle = mouse_angle
        self._guide_last_mouse_angle = mouse_angle

        global _ROTATE_GUIDE_START_ANGLE
        global _ROTATE_GUIDE_TOTAL_ANGLE
        _ROTATE_GUIDE_START_ANGLE = self._guide_start_angle
        _ROTATE_GUIDE_TOTAL_ANGLE = 0.0

        axis_colors = get_theme_gizmo_colors(context)
        self._axis_color_rgb = axis_colors.get(self.axis, (1.0, 1.0, 1.0))

        context.window_manager.cursortransform_active_rotate_axis = self.axis

        self._update_header_text(context, 0.0)

        tag_viewport_redraw(context)

    def _advance_axis_cycle(self, context, event, key):
        """
        3-state axis-key cycle: pressing the same axis key (X, Y, or Z)
        repeatedly cycles header-orient → alternate-orient → VIEW. Pressing
        a different axis key resets the cycle to 1st-press header-orient
        of that new axis. Native Blender's transform-modal behavior.

        Called from the modal X/Y/Z key handler instead of calling
        _switch_axis_constraint directly. MMB-pickup proximity switches
        still call _switch_axis_constraint with default args (header
        orient), which correctly resets the cycle for the new axis.
        """
        if self.axis == key and not self._using_alternate_orient:
            # 1st-press → 2nd-press: same axis, alternate orient.
            self._switch_axis_constraint(
                context, event, key, use_alternate_orient=True
            )
        elif self.axis == key and self._using_alternate_orient:
            # 2nd-press → 3rd-press: switch to VIEW (no constraint).
            # _switch_axis_constraint resets _using_alternate_orient to
            # False via the use_alternate_orient default param.
            self._switch_axis_constraint(context, event, "VIEW")
        else:
            # Different axis pressed, OR coming from VIEW: fresh cycle on
            # the new axis at 1st-press header-orient.
            self._switch_axis_constraint(context, event, key)

    def _clear_constraints(self, context, event):
        """
        Clear the active rotation constraint and return to view rotation.

        This mirrors Blender's C shortcut during transform: when an X/Y/Z
        rotation constraint is active, C clears that constraint and goes back
        to unconstrained/view rotation.
        """
        if self.axis not in {"X", "Y", "Z"}:
            return

        self._switch_axis_constraint(
            context,
            event,
            "VIEW",
            use_alternate_orient=False,
        )

    def _swap_to_trackball(self, context):
        """
        Mid-modal swap from view/axis rotation to trackball (free) rotation.

        Cleanly tears down this modal's draw handler and shared rotation
        state, records the axis we came from in _ROTATE_PREVIOUS_AXIS, then
        invokes rotate_free_modal with INVOKE_DEFAULT. The new modal
        snapshots the cursor's current location/rotation as its starting
        baseline, so rotation continues seamlessly without a jump.

        The previous-axis write happens AFTER _remove_guide_handler because
        that helper clears the same global on non-swap exit paths (LMB
        confirm, RMB cancel, etc.) — keeping the swap-only write last lets
        both code paths share the cleanup helper without interfering.

        Mirrors native Blender's behavior: pressing R during a rotation
        modal swaps to trackball, and pressing R again swaps back to
        whatever axis or view mode was active before. The round-trip is
        closed by rotate_free_modal._swap_to_view_rotation.
        """
        global _ROTATE_PREVIOUS_AXIS

        previous_axis = self.axis  # capture before cleanup blanks state

        self._remove_guide_handler()
        cleanup_rotation_modal(context)

        # Write AFTER cleanup. _remove_guide_handler clears
        # _ROTATE_PREVIOUS_AXIS as part of its normal teardown (so a
        # full LMB-confirm exit doesn't leave stale state behind for
        # the next R from idle); writing here re-asserts the value
        # specifically for the swap path.
        _ROTATE_PREVIOUS_AXIS = previous_axis

        # The cleanup above clears cursortransform_active_rotate_axis to "".
        # rotate_free_modal's invoke will set it back to "FREE", so there's
        # a one-frame gap where the gizmo group sees no active axis. That's
        # harmless — the cursor's transform has already been committed by
        # this modal up to its current state, and the new modal picks up
        # immediately on the next event.
        bpy.ops.cursortransform.rotate_free_modal('INVOKE_DEFAULT')

    def _enter_mmb_pickup(self, context):
        """
        Begin MMB axis pickup. Cache the screen-space projection of each
        world axis from the cursor pivot, so MOUSEMOVE during the hold can
        do proximity detection without reprojecting. Set the global flag
        so draw_prepare knows to show all three axis lines.

        Rotation continues normally during the hold — this routine doesn't
        freeze anything. The only effect is that subsequent MOUSEMOVE events
        also test proximity and may switch the active axis on the fly.
        """
        global _ROTATE_MMB_HELD

        self._mmb_held = True

        # Project each world axis (from the frozen orient at modal start)
        # to a 2D screen direction once. The cursor pivot doesn't move
        # during the hold, so the projected directions are constant — we
        # don't need to reproject on every MOUSEMOVE.
        center_3d = self._start_loc
        self._mmb_axis_dirs_2d = {}
        for axis in ("X", "Y", "Z"):
            idx = AXIS_INDEX[axis]
            world_axis = self._get_active_orient().col[idx].to_3d().normalized()
            self._mmb_axis_dirs_2d[axis] = _project_axis_dir_2d(
                context, center_3d, world_axis,
            )

        _ROTATE_MMB_HELD = True

        tag_viewport_redraw(context)

    def _maybe_switch_axis_by_proximity(self, context, event):
        """
        Called from MOUSEMOVE during MMB hold. If the mouse is within the
        proximity threshold of an axis line that is NOT the currently
        active one, switch the constraint to it. Returns True if a switch
        happened (so the caller knows to skip its own rotation update —
        _switch_axis_constraint already re-anchored mouse angle and will
        produce a clean continuation on the next MOUSEMOVE).
        """
        mouse_2d = Vector((event.mouse_region_x, event.mouse_region_y))
        threshold_px = (
            ROTATE_MMB_PROXIMITY_THRESHOLD_PX
            * context.preferences.system.pixel_size
        )

        new_axis = _closest_axis_to_mouse(
            mouse_2d,
            self._guide_center_2d,
            self._mmb_axis_dirs_2d,
            threshold_px,
        )

        if new_axis is not None and new_axis != self.axis:
            # Keep the current orientation cycle state during MMB pickup.
            # Example: R -> X -> X enters alternate/local X when the header
            # orientation is Global. MMB should then keep using that same
            # alternate/local basis instead of switching back to Global.
            self._switch_axis_constraint(
                context,
                event,
                new_axis,
                use_alternate_orient=self._using_alternate_orient,
            )
            return True

        return False

    def _exit_mmb_pickup(self, context):
        """
        End MMB axis pickup on MIDDLEMOUSE release. The active axis is
        whatever the proximity logic last set it to — that stays active.
        We only need to clear the hold flag so the gizmo group stops
        showing all three axis lines.
        """
        global _ROTATE_MMB_HELD

        self._mmb_held = False
        self._mmb_axis_dirs_2d = None
        _ROTATE_MMB_HELD = False

        tag_viewport_redraw(context)

    def _apply_rotation(self, context, angle):
        """
        Apply the accumulated constrained rotation angle around the frozen axis.
        """
        cursor = context.scene.cursor
        axis_vec = self._get_frozen_axis_vector()

        # Build one delta quaternion around the frozen gizmo axis.
        delta_q = Quaternion(axis_vec, angle)

        # Apply that delta to the frozen starting orientation.
        new_quat = delta_q @ self._start_quat

        # Write it back in the cursor's current rotation mode.
        set_cursor_from_quaternion(
            cursor,
            new_quat,
            self._start_euler_compat,
        )

    def modal(self, context, event):
        """
        Update the constrained rotation from mouse motion and handle confirm/cancel.
        """
        global _ROTATE_GUIDE_TOTAL_ANGLE
        global _ROTATE_GUIDE_CTRL_PRESSED
        self._ctrl_pressed = event.ctrl
        _ROTATE_GUIDE_CTRL_PRESSED = event.ctrl

        # Numeric input
        if event.value == 'PRESS':
            key = event.type

            self._numeric_input, self._numeric_active, confirm, consume = handle_numeric_key(
                key, self._numeric_input, self._numeric_active
            )

            if confirm:
                self._remove_guide_handler()
                cleanup_rotation_modal(context)
                return {'FINISHED'}

            if key == 'G' and not event.is_repeat:
                self._remove_guide_handler()
                switch_native_rotate_to_translate(
                    context,
                    self.axis if self.axis in {"X", "Y", "Z"} else None,
                )
                return {'FINISHED'}

            if key in {"X", "Y", "Z"} and not event.is_repeat:
                self._advance_axis_cycle(context, event, key)
                return {'RUNNING_MODAL'}
            
            if key == 'C' and not event.is_repeat:
                self._clear_constraints(context, event)
                return {'RUNNING_MODAL'}
            
            if key == 'R' and not event.is_repeat:
                # Swap from view/axis rotation to trackball. The cursor's
                # current rotation becomes the new modal's starting point,
                # so rotation continues seamlessly. Native Blender works
                # this way for object-mode rotation; we mirror that.
                self._swap_to_trackball(context)
                return {'FINISHED'}

            if self._numeric_active:
                angle = math.radians(parse_numeric_input(self._numeric_input))
                _ROTATE_GUIDE_TOTAL_ANGLE = angle
                orient_label = get_orient_type(context).capitalize()
                context.area.header_text_set(
                    f"Rotation: {self._numeric_input}°  {orient_label}"
                )
                self._apply_rotation(context, angle)
                tag_viewport_redraw(context)
                return {'RUNNING_MODAL'}

            if consume:
                return {'RUNNING_MODAL'}

        # MMB axis pickup: while held, all three axis lines are visible and
        # the constraint switches in real time as the mouse moves near a
        # different axis. Rotation continues normally on whichever axis is
        # active at any given moment.
        if event.type == 'MIDDLEMOUSE':
            if event.value == 'PRESS':
                if not self._numeric_active:
                    self._enter_mmb_pickup(context)
                return {'RUNNING_MODAL'}

            if event.value == 'RELEASE' and self._mmb_held:
                self._exit_mmb_pickup(context)
                return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            if self._numeric_active:
                return {'RUNNING_MODAL'}

            # While MMB is held, check proximity to the three axis lines
            # before applying rotation. If a different axis is now closest,
            # _switch_axis_constraint re-anchors the mouse angle and resets
            # the accumulated total — applying rotation this frame on top
            # would produce a jump, so we skip it. The next MOUSEMOVE will
            # naturally apply rotation against the new baseline.
            if self._mmb_held:
                switched = self._maybe_switch_axis_by_proximity(context, event)
                if switched:
                    self._guide_mouse_2d = Vector(
                        (event.mouse_region_x, event.mouse_region_y)
                    )
                    return {'RUNNING_MODAL'}

            mouse_now = Vector((event.mouse_region_x, event.mouse_region_y))
            self._guide_mouse_2d = mouse_now
            mouse_angle = _ellipse_angle_from_mouse(
                self._guide_center_2d,
                mouse_now,
                self._guide_basis_x_2d,
                self._guide_basis_y_2d,
            )
            if mouse_angle is not None:
                delta = _wrap_pi(mouse_angle - self._guide_last_mouse_angle)
                if event.shift:
                    delta *= 0.1
                self._guide_total_angle += delta
                self._guide_last_mouse_angle = mouse_angle

            angle = self._guide_total_angle

            # Apply angle snapping to the accumulated drag when Ctrl is held.
            if event.ctrl:
                angle = round(angle / ROTATE_SNAP_STEP) * ROTATE_SNAP_STEP

            _ROTATE_GUIDE_TOTAL_ANGLE = angle

            self._update_header_text(context, angle)

            self._apply_rotation(context, angle)
            
            tag_viewport_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self._remove_guide_handler()
            cleanup_rotation_modal(context)
            return {'FINISHED'}

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            restore_cursor_rotation(
                context.scene.cursor,
                self._rot_mode,
                self._start_rot,
            )
            self._remove_guide_handler()
            cleanup_rotation_modal(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}


class CURSORTRANSFORM_OT_rotate_free_modal(bpy.types.Operator):
    """Freely rotate the 3D Cursor by dragging inside the rotation sphere."""
    bl_idname = "cursortransform.rotate_free_modal"
    bl_label = "Cursor Rotate Free"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    def invoke(self, context, event):
        """
        Initialize the free-rotation arcball state from the current cursor and view.
        """
        cursor = context.scene.cursor
        wm = context.window_manager

        rot_state = cache_cursor_rotation_state(cursor)
        self._rot_mode = rot_state["rot_mode"]
        self._start_rot = rot_state["start_rot"]
        self._start_quat = rot_state["start_quat"]
        self._start_euler_compat = rot_state["start_euler_compat"]

        # Cache the cursor position and current view basis used to initialize the
        # free-rotation arcball and keep the drag visually stable.
        self._start_loc = cursor.matrix.translation.copy()
        self._start_view = get_view_rot_matrix(context).copy()

        center_2d = view3d_utils.location_3d_to_region_2d(
            context.region, context.region_data, self._start_loc
        )
        if center_2d is None:
            return {'CANCELLED'}

        # Derive the free-rotation arcball radius from the view ring size so the
        # trackball interaction matches the visible free-rotate disc.
        gizmo_pref = max(context.preferences.view.gizmo_size, 1)
        ring_radius_px = gizmo_pref * ROTATE_VIEW_RING_PIXEL_RADIUS
        self._arcball_radius_px = ring_radius_px * FREE_ROTATE_DISC_SCALE_FACTOR
        self._arcball_center_2d = center_2d

        self._start_mouse_2d = Vector((event.mouse_region_x, event.mouse_region_y))
        self._start_ball_vec = _map_to_arcball(
            self._arcball_center_2d,
            self._start_mouse_2d,
            self._arcball_radius_px,
        )

        if self._start_ball_vec is None:
            return {'CANCELLED'}

        # Freeze the view basis for the duration of the drag so the arcball mapping
        # remains stable even if the viewport changes.
        global _ROTATE_ACTIVE_VIEW
        _ROTATE_ACTIVE_VIEW = self._start_view.copy()

        wm.cursortransform_active_rotate_axis = "FREE"
        context.window.cursor_modal_set('SCROLL_XY')
        context.workspace.status_text_set(draw_status_rotate_free)
        wm.modal_handler_add(self)
        self._numeric_input = ""
        self._numeric_active = False
        return {'RUNNING_MODAL'}

    def _swap_to_view_rotation(self, context):
        """
        Mid-modal swap from trackball back to whatever rotation mode was
        active before swapping in. The mirror of
        rotate_modal._swap_to_trackball — together they close the loop so
        repeated R presses alternate trackball ↔ previous-axis-or-view
        indefinitely.

        _ROTATE_PREVIOUS_AXIS holds the axis state from before the swap
        (set by rotate_modal._swap_to_trackball). If it's a constrained
        axis (X/Y/Z), invoke rotate_modal directly with that axis. If
        it's "VIEW" or unset, fall through to rotate_view (which routes
        through rotate_modal with axis="VIEW").

        Cleans up trackball-specific shared state (_ROTATE_ACTIVE_VIEW)
        before invoking the new modal so the latter captures a fresh
        view basis, not the stale snapshot from before the round-trip.
        """
        global _ROTATE_ACTIVE_VIEW
        global _ROTATE_PREVIOUS_AXIS

        previous_axis = _ROTATE_PREVIOUS_AXIS

        cleanup_rotation_modal(context)
        _ROTATE_ACTIVE_VIEW = None
        _ROTATE_PREVIOUS_AXIS = None

        if previous_axis in {"X", "Y", "Z"}:
            bpy.ops.cursortransform.rotate_modal(
                'INVOKE_DEFAULT',
                axis=previous_axis,
            )
        else:
            # No previous axis recorded (shouldn't happen in normal use)
            # or the previous mode was VIEW. Either way, rotate_view is
            # the right choice — it invokes rotate_modal with axis="VIEW".
            bpy.ops.cursortransform.rotate_view('INVOKE_DEFAULT')

    def _apply_arcball_rotation(self, context, ball_now, snap):
        """
        Apply the current arcball rotation delta and update the header display.
        """
        view_rot = self._start_view.to_3x3()
        v0 = (view_rot @ self._start_ball_vec).normalized()
        v1 = (view_rot @ ball_now).normalized()
        delta_q = v0.rotation_difference(v1)

        # Snap the trackball delta per Euler axis, then rebuild the quaternion.
        if snap:
            delta_euler = delta_q.to_euler('XYZ')
            delta_euler.x = round(delta_euler.x / ROTATE_SNAP_STEP) * ROTATE_SNAP_STEP
            delta_euler.y = round(delta_euler.y / ROTATE_SNAP_STEP) * ROTATE_SNAP_STEP
            delta_euler.z = round(delta_euler.z / ROTATE_SNAP_STEP) * ROTATE_SNAP_STEP
            delta_q = delta_euler.to_quaternion()

        new_quat = delta_q @ self._start_quat
        cursor = context.scene.cursor
        set_cursor_from_quaternion(
            cursor,
            new_quat,
            self._start_euler_compat,
        )

        # Derive the displayed trackball values from the snapped delta quaternion so
        # the header matches the actual applied rotation.
        snapped_euler = delta_q.to_euler('XYZ')
        dx_deg = math.degrees(snapped_euler.x)
        dy_deg = math.degrees(snapped_euler.y)
        context.area.header_text_set(f"Trackball: {dx_deg:.2f}  {dy_deg:.2f}")    

    def modal(self, context, event):
        """
        Update the free-rotation arcball state and handle confirm/cancel.
        """
        global _ROTATE_ACTIVE_VIEW

        # Numeric input
        if event.value == 'PRESS':
            key = event.type

            self._numeric_input, self._numeric_active, confirm, consume = handle_numeric_key(
                key, self._numeric_input, self._numeric_active
            )

            if confirm:
                cleanup_rotation_modal(context)
                _ROTATE_ACTIVE_VIEW = None
                return {'FINISHED'}

            if key == 'G' and not event.is_repeat:
                _ROTATE_ACTIVE_VIEW = None
                switch_native_rotate_to_translate(context, None)
                return {'FINISHED'}

            if key == 'R' and not event.is_repeat:
                # Swap from trackball back to view rotation. Mirror of the
                # rotate_modal R-handler — closes the loop so multiple R
                # presses alternate view ↔ trackball indefinitely.
                self._swap_to_view_rotation(context)
                return {'FINISHED'}

            if self._numeric_active:
                typed_deg = parse_numeric_input(self._numeric_input)
                angle = math.radians(typed_deg)
                view_axis = (self._start_view @ Vector((0.0, 0.0, 1.0))).normalized()
                delta_q = Quaternion(view_axis, angle)
                new_quat = delta_q @ self._start_quat
                set_cursor_from_quaternion(context.scene.cursor, new_quat, self._start_euler_compat)
                context.area.header_text_set(
                    f"Trackball: [{self._numeric_input}] = {typed_deg:.2f}\u00b0  None"
                )
                tag_viewport_redraw(context)
                return {'RUNNING_MODAL'}

            if consume:
                return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            if self._numeric_active:
                return {'RUNNING_MODAL'}

            mouse_now = Vector((event.mouse_region_x, event.mouse_region_y))
            mouse_input = self._start_mouse_2d + (mouse_now - self._start_mouse_2d) * (0.1 if event.shift else 1.0)

            ball_now = _map_to_arcball(
                self._arcball_center_2d,
                mouse_input,
                self._arcball_radius_px,
            )

            if ball_now is not None:
                self._apply_arcball_rotation(context, ball_now, snap=event.ctrl)

            tag_viewport_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            cleanup_rotation_modal(context)
            _ROTATE_ACTIVE_VIEW = None
            return {'FINISHED'}

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            restore_cursor_rotation(
                context.scene.cursor,
                self._rot_mode,
                self._start_rot,
            )
            cleanup_rotation_modal(context)
            _ROTATE_ACTIVE_VIEW = None
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}


# ─────────────────────────────────────────────────────────────────────────────
# Translation and Wrapper Operators
# ─────────────────────────────────────────────────────────────────────────────

class CURSORTRANSFORM_OT_translate_modal(bpy.types.Operator):
    """Custom keyboard translate modal for the 3D Cursor."""
    bl_idname = "cursortransform.translate_modal"
    bl_label = "Cursor Translate Modal"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    release_confirm: bpy.props.BoolProperty(default=False)

    def invoke(self, context, event):
        cursor = context.scene.cursor

        if context.scene.tool_settings.use_snap:
            bpy.ops.cursortransform.translate_free(
                'INVOKE_DEFAULT',
                release_confirm=False,
            )
            return {'FINISHED'}

        self._start_loc = cursor.location.copy()
        self._start_mouse = None
        self._waiting_for_first_mousemove = True

        self._axis = ""
        self._plane_exclude_axis = ""
        self._cycle_state = 0
        self._mmb_held = False
        self._mmb_axis_dirs_2d = None
        self._precision_active = False
        self._precision_start_mouse = None
        self._precision_start_loc = None
        self._start_orient = build_orient_matrix(context).copy()
        self._start_orient_alternate = build_alternate_orient_matrix(context).copy()
        self._using_alternate_orient = False
        wm = context.window_manager
        wm.cursortransform_active_translate_axis = ""

        global _TRANSLATE_GHOST_START_LOC
        global _TRANSLATE_GHOST_START_ORIENT
        _TRANSLATE_GHOST_START_LOC = self._start_loc.copy()
        _TRANSLATE_GHOST_START_ORIENT = None

        self._axis_line_handler = bpy.types.SpaceView3D.draw_handler_add(
            _draw_translate_axis_line_op, (self,), 'WINDOW', 'POST_PIXEL'
        )

        context.window.cursor_modal_set('SCROLL_XY')
        context.workspace.status_text_set(draw_status_translate)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _remove_axis_line_handler(self):
        if getattr(self, "_axis_line_handler", None) is not None:
            bpy.types.SpaceView3D.draw_handler_remove(
                self._axis_line_handler, 'WINDOW'
            )
            self._axis_line_handler = None

    def _get_active_orient(self):
        if self._using_alternate_orient:
            return self._start_orient_alternate
        return self._start_orient

    def _get_axis_vector(self):
        if self._axis not in {"X", "Y", "Z"}:
            return None

        idx = AXIS_INDEX[self._axis]
        return self._get_active_orient().col[idx].to_3d().normalized()

    def _format_distance(self, value):
        return f"{value:.4f} m"

    def _get_orient_label(self, context):
        if self._using_alternate_orient:
            return alternate_orient_label(context).lower()
        return get_orient_type(context).lower()

    def _update_header_text(self, context):
        delta = context.scene.cursor.location - self._start_loc

        if self._plane_exclude_axis in {"X", "Y", "Z"}:
            orient_label = self._get_orient_label(context)

            axes = [
                axis for axis in ("X", "Y", "Z")
                if axis != self._plane_exclude_axis
            ]

            orient = self._get_active_orient()

            axis_a = axes[0]
            axis_b = axes[1]

            vec_a = orient.col[AXIS_INDEX[axis_a]].to_3d().normalized()
            vec_b = orient.col[AXIS_INDEX[axis_b]].to_3d().normalized()

            amount_a = delta.dot(vec_a)
            amount_b = delta.dot(vec_b)

            total = delta.length

            context.area.header_text_set(
                f"D:  {self._format_distance(amount_a)}   "
                f"D: {self._format_distance(amount_b)} "
                f"({self._format_distance(total)}) "
                f"locking {orient_label} {self._plane_exclude_axis}"
            )
            return

        if self._axis in {"X", "Y", "Z"}:
            axis_vec = self._get_axis_vector()
            if axis_vec is None:
                return

            amount = delta.dot(axis_vec)
            orient_label = self._get_orient_label(context)

            context.area.header_text_set(
                f"D:  {self._format_distance(amount)} "
                f"({self._format_distance(abs(amount))}) "
                f"along {orient_label} {self._axis}"
            )
            return

        dx = delta.x
        dy = delta.y
        dz = delta.z
        total = delta.length

        context.area.header_text_set(
            f"Dx: {self._format_distance(dx)}   "
            f"Dy:  {self._format_distance(dy)}   "
            f"Dz: {self._format_distance(dz)} "
            f"({self._format_distance(total)})"
        )

    def _update_status_bar(self, context):
        if context.workspace is not None:
            context.workspace.status_text_set(draw_status_translate)
            
    def _ensure_start_mouse(self, event):
        """
        Make sure keyboard constraint actions have a valid mouse baseline.

        This prevents errors when the user switches from rotation to translation
        and immediately presses X/Y/Z before the first MOUSEMOVE event.
        """
        if self._start_mouse is None:
            self._start_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
            self._waiting_for_first_mousemove = False
            
    def _set_axis_cycle(self, context, event, axis):
        global _TRANSLATE_GHOST_START_ORIENT

        self._ensure_start_mouse(event)

        if self._axis != axis:
            self._axis = axis
            self._cycle_state = 1
            self._using_alternate_orient = False

        elif self._cycle_state == 1:
            self._cycle_state = 2
            self._using_alternate_orient = True

        else:
            self._axis = ""
            self._cycle_state = 0
            self._using_alternate_orient = False

        context.window_manager.cursortransform_active_translate_axis = self._axis

        if self._axis in {"X", "Y", "Z"}:
            _TRANSLATE_GHOST_START_ORIENT = self._get_active_orient().copy()
        else:
            _TRANSLATE_GHOST_START_ORIENT = None

        context.scene.cursor.location = self._mouse_to_location(context, event)
        self._update_header_text(context)
        self._update_status_bar(context)
        tag_viewport_redraw(context)

    def _set_plane_cycle(self, context, event, exclude_axis):
        global _TRANSLATE_GHOST_START_ORIENT

        self._ensure_start_mouse(event)

        if self._plane_exclude_axis != exclude_axis:
            self._axis = ""
            self._plane_exclude_axis = exclude_axis
            self._cycle_state = 1
            self._using_alternate_orient = False

        elif self._cycle_state == 1:
            self._axis = ""
            self._cycle_state = 2
            self._using_alternate_orient = True

        else:
            self._axis = ""
            self._plane_exclude_axis = ""
            self._cycle_state = 0
            self._using_alternate_orient = False

        if self._plane_exclude_axis in {"X", "Y", "Z"}:
            plane = "".join(
                axis for axis in ("X", "Y", "Z")
                if axis != self._plane_exclude_axis
            )
            context.window_manager.cursortransform_active_translate_axis = plane
            _TRANSLATE_GHOST_START_ORIENT = self._get_active_orient().copy()
        else:
            context.window_manager.cursortransform_active_translate_axis = ""
            _TRANSLATE_GHOST_START_ORIENT = None

        context.scene.cursor.location = self._mouse_to_location(context, event)
        self._update_header_text(context)
        self._update_status_bar(context)
        tag_viewport_redraw(context)

    def _clear_constraints(self, context, event):
        global _TRANSLATE_GHOST_START_ORIENT

        self._ensure_start_mouse(event)
        
        self._axis = ""
        self._plane_exclude_axis = ""
        self._cycle_state = 0
        self._using_alternate_orient = False

        context.window_manager.cursortransform_active_translate_axis = ""
        _TRANSLATE_GHOST_START_ORIENT = None

        context.scene.cursor.location = self._mouse_to_location(context, event)
        self._update_header_text(context)
        self._update_status_bar(context)
        tag_viewport_redraw(context)

    def _switch_to_rotate(self, context):
        # Capture current translate constraint before cleanup clears it.
        axis = self._axis if self._axis in {"X", "Y", "Z"} else None

        self._finish(context)

        if axis is not None:
            bpy.ops.cursortransform.rotate_modal(
                'INVOKE_DEFAULT',
                axis=axis,
            )
        else:
            bpy.ops.cursortransform.rotate_view('INVOKE_DEFAULT')

    def _handoff_to_native_translate(self, context):
        """
        Finish the custom translate modal and hand control to Blender's native
        cursor translate operator.

        This is used for Ctrl snapping. Once handed off, Blender owns the
        transform until confirm/cancel.
        """
        axis = self._axis if self._axis in {"X", "Y", "Z"} else None

        plane = None
        if self._plane_exclude_axis in {"X", "Y", "Z"}:
            plane = "".join(
                axis_name for axis_name in ("X", "Y", "Z")
                if axis_name != self._plane_exclude_axis
            )

        self._finish(context)

        if axis is not None:
            bpy.ops.cursortransform.translate(
                'INVOKE_DEFAULT',
                axis=axis,
                release_confirm=False,
            )
            return

        if plane is not None:
            bpy.ops.cursortransform.translate_plane(
                'INVOKE_DEFAULT',
                plane=plane,
                release_confirm=False,
            )
            return

        bpy.ops.cursortransform.translate_free(
            'INVOKE_DEFAULT',
            release_confirm=False,
        )

    def _enter_mmb_pickup(self, context):
        self._mmb_held = True
        self._mmb_axis_dirs_2d = {}

        for axis in ("X", "Y", "Z"):
            idx = AXIS_INDEX[axis]
            axis_vec = self._get_active_orient().col[idx].to_3d().normalized()
            self._mmb_axis_dirs_2d[axis] = _project_axis_dir_2d(
                context,
                self._start_loc,
                axis_vec,
            )

        tag_viewport_redraw(context)

    def _exit_mmb_pickup(self, context):
        self._mmb_held = False
        self._mmb_axis_dirs_2d = None
        tag_viewport_redraw(context)

    def _set_axis_from_mmb(self, context, event, axis):
        global _TRANSLATE_GHOST_START_ORIENT

        self._axis = axis
        self._plane_exclude_axis = ""
        self._cycle_state = 1
        self._using_alternate_orient = False

        context.window_manager.cursortransform_active_translate_axis = axis
        _TRANSLATE_GHOST_START_ORIENT = self._get_active_orient().copy()

        context.scene.cursor.location = self._mouse_to_location(context, event)
        self._update_header_text(context)
        self._update_status_bar(context)
        tag_viewport_redraw(context)

    def _maybe_switch_axis_by_proximity(self, context, event):
        mouse_2d = Vector((event.mouse_region_x, event.mouse_region_y))

        threshold_px = (
            ROTATE_MMB_PROXIMITY_THRESHOLD_PX
            * context.preferences.system.pixel_size
        )

        new_axis = _closest_axis_to_mouse(
            mouse_2d,
            view3d_utils.location_3d_to_region_2d(
                context.region,
                context.region_data,
                self._start_loc,
            ),
            self._mmb_axis_dirs_2d,
            threshold_px,
        )

        if new_axis is not None and new_axis != self._axis:
            self._set_axis_from_mmb(context, event, new_axis)

    def _mouse_to_free_location(self, context, event):
        region = context.region
        rv3d = context.region_data

        base_loc = self._input_start_loc()

        start_2d = view3d_utils.location_3d_to_region_2d(
            region,
            rv3d,
            base_loc,
        )
        if start_2d is None:
            return base_loc.copy()

        new_2d = start_2d + self._mouse_delta_2d(event)

        ray_origin = view3d_utils.region_2d_to_origin_3d(
            region,
            rv3d,
            new_2d,
        )
        ray_dir = view3d_utils.region_2d_to_vector_3d(
            region,
            rv3d,
            new_2d,
        )

        view_normal = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))
        denom = ray_dir.dot(view_normal)

        if abs(denom) < 1e-8:
            return base_loc.copy()

        factor = (base_loc - ray_origin).dot(view_normal) / denom
        return ray_origin + ray_dir * factor

    def _mouse_delta_2d(self, event):
        mouse_delta = Vector((event.mouse_region_x, event.mouse_region_y)) - self._input_start_mouse()

        if self._precision_active:
            mouse_delta *= 0.1

        return mouse_delta

    def _project_world_vector_to_2d(self, context, world_vec):
        base_loc = self._input_start_loc()

        start_2d = view3d_utils.location_3d_to_region_2d(
            context.region,
            context.region_data,
            base_loc,
        )

        end_2d = view3d_utils.location_3d_to_region_2d(
            context.region,
            context.region_data,
            base_loc + world_vec,
        )

        if start_2d is None or end_2d is None:
            return None

        projected = end_2d - start_2d
        if projected.length <= 1e-6:
            return None

        return projected

    def _update_precision_state(self, context, event):
        mouse_now = Vector((event.mouse_region_x, event.mouse_region_y))

        # Enter precision mode:
        # Anchor precision movement from the current cursor location and mouse.
        if event.shift and not self._precision_active:
            self._precision_active = True
            self._precision_start_mouse = mouse_now
            self._precision_start_loc = context.scene.cursor.location.copy()
            return

        # Exit precision mode:
        # Promote the current precise cursor location to the new normal baseline.
        # This prevents the cursor from snapping back to the full-speed mouse position.
        if not event.shift and self._precision_active:
            self._precision_active = False

            self._start_mouse = mouse_now
            self._start_loc = context.scene.cursor.location.copy()

            self._precision_start_mouse = None
            self._precision_start_loc = None

    def _input_start_mouse(self):
        if self._precision_active and self._precision_start_mouse is not None:
            return self._precision_start_mouse
        return self._start_mouse

    def _input_start_loc(self):
        if self._precision_active and self._precision_start_loc is not None:
            return self._precision_start_loc
        return self._start_loc

    def _mouse_to_axis_location(self, context, event):
        axis_vec = self._get_axis_vector()
        if axis_vec is None:
            return self._mouse_to_free_location(context, event)

        axis_2d = self._project_world_vector_to_2d(context, axis_vec)
        if axis_2d is None:
            return self._input_start_loc().copy()

        mouse_delta = self._mouse_delta_2d(event)

        axis_dir_2d = axis_2d.normalized()

        # Convert screen movement along the projected axis back into world units.
        # This avoids the foreshortening bug caused by projecting a free view-plane
        # movement onto the 3D axis afterwards.
        amount = mouse_delta.dot(axis_dir_2d) / axis_2d.length

        return self._input_start_loc() + axis_vec * amount

    def _mouse_to_plane_location(self, context, event):
        if self._plane_exclude_axis not in {"X", "Y", "Z"}:
            return self._mouse_to_free_location(context, event)

        plane_axes = [
            axis for axis in ("X", "Y", "Z")
            if axis != self._plane_exclude_axis
        ]

        orient = self._get_active_orient()

        vec_a = orient.col[AXIS_INDEX[plane_axes[0]]].to_3d().normalized()
        vec_b = orient.col[AXIS_INDEX[plane_axes[1]]].to_3d().normalized()

        basis_a_2d = self._project_world_vector_to_2d(context, vec_a)
        basis_b_2d = self._project_world_vector_to_2d(context, vec_b)

        if basis_a_2d is None or basis_b_2d is None:
            return self._input_start_loc().copy()

        solved = _solve_2d_basis(
            self._mouse_delta_2d(event),
            basis_a_2d,
            basis_b_2d,
        )

        if solved is None:
            return self._input_start_loc().copy()

        amount_a, amount_b = solved

        return self._input_start_loc() + (vec_a * amount_a) + (vec_b * amount_b)

    def _mouse_to_location(self, context, event):
        if self._plane_exclude_axis in {"X", "Y", "Z"}:
            return self._mouse_to_plane_location(context, event)

        if self._axis in {"X", "Y", "Z"}:
            return self._mouse_to_axis_location(context, event)

        return self._mouse_to_free_location(context, event)

    def _finish(self, context):
        global _TRANSLATE_GHOST_START_LOC
        global _TRANSLATE_GHOST_START_ORIENT

        self._remove_axis_line_handler()

        _TRANSLATE_GHOST_START_LOC = None
        _TRANSLATE_GHOST_START_ORIENT = None

        context.window.cursor_modal_restore()
        context.window_manager.cursortransform_active_translate_axis = ""

        if context.area is not None:
            context.area.header_text_set(None)

        if context.workspace is not None:
            context.workspace.status_text_set(None)

        tag_viewport_redraw(context)

    def modal(self, context, event):

        if event.value == 'PRESS' and event.type == 'C' and not event.is_repeat:
            self._clear_constraints(context, event)
            return {'RUNNING_MODAL'}

        if event.value == 'PRESS' and event.type == 'R' and not event.is_repeat:
            self._switch_to_rotate(context)
            return {'FINISHED'}

        if event.value == 'PRESS' and event.type in {'LEFT_CTRL', 'RIGHT_CTRL'}:
            self._handoff_to_native_translate(context)
            return {'FINISHED'}

        if event.value == 'PRESS' and event.type == 'TAB' and event.shift:
            context.scene.tool_settings.use_snap = True
            self._handoff_to_native_translate(context)
            return {'FINISHED'}

        if event.type == 'MIDDLEMOUSE':               
            if event.value == 'PRESS':
                self._enter_mmb_pickup(context)
                return {'RUNNING_MODAL'}

            if event.value == 'RELEASE' and self._mmb_held:
                self._exit_mmb_pickup(context)
                return {'RUNNING_MODAL'}
        
        if event.value == 'PRESS' and event.type in {'X', 'Y', 'Z'} and not event.is_repeat:
            if event.shift:
                self._set_plane_cycle(context, event, event.type)
            else:
                self._plane_exclude_axis = ""
                self._set_axis_cycle(context, event, event.type)

            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            if self._waiting_for_first_mousemove:
                self._waiting_for_first_mousemove = False
                self._start_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
                return {'RUNNING_MODAL'}

            self._update_precision_state(context, event)

            if self._mmb_held:
                self._maybe_switch_axis_by_proximity(context, event)

            context.scene.cursor.location = self._mouse_to_location(context, event)
            self._update_header_text(context)

            tag_viewport_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'}:
            self._finish(context)
            return {'FINISHED'}

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            context.scene.cursor.location = self._start_loc
            self._finish(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}


class CURSORTRANSFORM_OT_translate(bpy.types.Operator):
    """Move 3D cursor along a constrained axis."""
    bl_idname  = "cursortransform.translate"
    bl_label   = "Cursor Translate"
    bl_options = {'INTERNAL'}

    axis: bpy.props.StringProperty(default="Z")
    release_confirm: bpy.props.BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        # Both gizmo and keyboard-shortcut entry paths require the cursor
        # tool to be the active workspace tool. Returning False from poll
        # means the keymap entry no-ops, so Blender falls through to the
        # default G/X/Y/Z handler (translate selected object). That gives
        # us "tool-aware" shortcuts without registering a tool-scoped
        # keymap, which is the documented stable approach.
        return active_tool_is_cursor(context)

    def invoke(self, context, event):
        """
        Launch Blender's native translate operator in axis-constrained cursor mode.
        """
        global _TRANSLATE_GHOST_START_LOC
        global _TRANSLATE_GHOST_START_ORIENT

        orient_matrix = build_orient_matrix(context)
        orient_mx = orient_matrix.to_3x3()
        orient_type = get_orient_type(context)

        wm = context.window_manager
        wm.cursortransform_active_translate_axis = self.axis

        # Store the starting transform for ghost preview drawing during translation.
        _TRANSLATE_GHOST_START_LOC = context.scene.cursor.location.copy()
        _TRANSLATE_GHOST_START_ORIENT = orient_matrix.copy()

        bpy.ops.transform.translate(
            'INVOKE_DEFAULT',
            cursor_transform=True,
            constraint_axis=AXIS_CONSTRAINT[self.axis],
            orient_type=orient_type,
            orient_matrix=orient_mx,
            orient_matrix_type=orient_type,
            release_confirm=self.release_confirm,
        )
        return {'FINISHED'}


class CURSORTRANSFORM_OT_translate_free(bpy.types.Operator):
    """Move 3D cursor freely in view plane."""
    bl_idname  = "cursortransform.translate_free"
    bl_label   = "Cursor Translate Free"
    bl_options = {'INTERNAL'}

    release_confirm: bpy.props.BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        return active_tool_is_cursor(context)

    def invoke(self, context, event):
        """
        Launch Blender's native translate operator for free cursor movement.
        """
        global _TRANSLATE_GHOST_START_LOC
        global _TRANSLATE_GHOST_START_ORIENT

        wm = context.window_manager
        wm.cursortransform_active_translate_axis = ""

        # Store the starting transform for ghost preview drawing during translation.
        _TRANSLATE_GHOST_START_LOC = context.scene.cursor.location.copy()
        _TRANSLATE_GHOST_START_ORIENT = None

        bpy.ops.transform.translate(
            'INVOKE_DEFAULT',
            cursor_transform=True,
            release_confirm=self.release_confirm,
        )
        return {'FINISHED'}


class CURSORTRANSFORM_OT_translate_plane(bpy.types.Operator):
    """Move 3D cursor along a constrained plane."""
    bl_idname  = "cursortransform.translate_plane"
    bl_label   = "Cursor Translate Plane"
    bl_options = {'INTERNAL'}

    plane: bpy.props.StringProperty(default="XY")
    release_confirm: bpy.props.BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        return active_tool_is_cursor(context)

    def invoke(self, context, event):
        """
        Launch Blender's native translate operator constrained to a plane.
        """        
        global _TRANSLATE_GHOST_START_LOC
        global _TRANSLATE_GHOST_START_ORIENT

        orient_matrix = build_orient_matrix(context)
        orient_mx = orient_matrix.to_3x3()
        orient_type = get_orient_type(context)

        wm = context.window_manager
        wm.cursortransform_active_translate_axis = self.plane

        # Store the starting transform for ghost preview drawing during translation.
        _TRANSLATE_GHOST_START_LOC = context.scene.cursor.location.copy()
        _TRANSLATE_GHOST_START_ORIENT = orient_matrix.copy()

        bpy.ops.transform.translate(
            'INVOKE_DEFAULT',
            cursor_transform=True,
            constraint_axis=PLANE_CONSTRAINT[self.plane],
            orient_type=orient_type,
            orient_matrix=orient_mx,
            orient_matrix_type=orient_type,
            release_confirm=self.release_confirm,
        )
        return {'FINISHED'}


class CURSORTRANSFORM_OT_rotate_x(bpy.types.Operator):
    """Launch X-axis cursor rotation."""
    bl_idname = "cursortransform.rotate_x"
    bl_label = "Cursor Rotate X"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return active_tool_is_cursor(context)

    def invoke(self, context, event):
        return bpy.ops.cursortransform.rotate_modal('INVOKE_DEFAULT', axis="X")


class CURSORTRANSFORM_OT_rotate_y(bpy.types.Operator):
    """Launch Y-axis cursor rotation."""
    bl_idname = "cursortransform.rotate_y"
    bl_label = "Cursor Rotate Y"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return active_tool_is_cursor(context)

    def invoke(self, context, event):
        return bpy.ops.cursortransform.rotate_modal('INVOKE_DEFAULT', axis="Y")


class CURSORTRANSFORM_OT_rotate_z(bpy.types.Operator):
    """Launch Z-axis cursor rotation."""
    bl_idname = "cursortransform.rotate_z"
    bl_label = "Cursor Rotate Z"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return active_tool_is_cursor(context)

    def invoke(self, context, event):
        return bpy.ops.cursortransform.rotate_modal('INVOKE_DEFAULT', axis="Z")


class CURSORTRANSFORM_OT_rotate_view(bpy.types.Operator):
    """Launch view-aligned cursor rotation."""
    bl_idname = "cursortransform.rotate_view"
    bl_label = "Cursor Rotate View"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return active_tool_is_cursor(context)

    def invoke(self, context, event):
        return bpy.ops.cursortransform.rotate_modal(
            'INVOKE_DEFAULT',
            axis="VIEW",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Gizmo Classes and Group
# ─────────────────────────────────────────────────────────────────────────────

class CURSORTRANSFORM_GT_filled_dot(bpy.types.Gizmo):
    """Non-selectable filled dot used for active and ghost center markers."""
    bl_idname = "CURSORTRANSFORM_GT_filled_dot"

    def setup(self):
        """
        Build the cached filled-circle shape used by the dot gizmo.
        """
        if hasattr(self, "_shape"):
            return

        self._shape = self.new_custom_shape(
            'TRIS',
            _build_circle_fan_vertices(radius=0.06, segments=24),
        )

    def draw(self, context):
        self.draw_custom_shape(self._shape)

    def draw_select(self, context, select_id):
        # Keep selection drawing valid even though the dot gizmo is used only as
        # a visual marker.
        self.draw_custom_shape(self._shape, select_id=select_id)


class CURSORTRANSFORM_GT_plane_square(bpy.types.Gizmo):
    """Square plane handle used for planar cursor translation and ghost previews."""
    bl_idname = "CURSORTRANSFORM_GT_plane_square"

    def setup(self):
        """
        Build the cached fill and outline shapes for the square plane handle.
        """
        if hasattr(self, "_fill_shape"):
            return

        # Unit square in local XY plane, centered at origin.
        s = 0.5

        fill_verts = [
            (-s, -s, 0.0), ( s, -s, 0.0), ( s,  s, 0.0),
            (-s, -s, 0.0), ( s,  s, 0.0), (-s,  s, 0.0),
        ]

        line_verts = [
            (-s, -s, 0.0), ( s, -s, 0.0),
            ( s, -s, 0.0), ( s,  s, 0.0),
            ( s,  s, 0.0), (-s,  s, 0.0),
            (-s,  s, 0.0), (-s, -s, 0.0),
        ]

        self._fill_shape = self.new_custom_shape('TRIS', fill_verts)
        self._line_shape = self.new_custom_shape('LINES', line_verts)

    def draw(self, context):
        """
        Draw the plane handle with separate fill and outline alpha states.
        """
        fill_color = getattr(self, "fill_color", (1.0, 1.0, 1.0))
        outline_color = getattr(self, "outline_color", fill_color)
        fill_alpha = float(getattr(self, "fill_alpha", 0.18))
        outline_alpha = float(getattr(self, "outline_alpha", 1.0))
        fill_alpha_highlight = float(getattr(self, "fill_alpha_highlight", fill_alpha))
        outline_alpha_highlight = float(getattr(self, "outline_alpha_highlight", outline_alpha))

        old_color = self.color
        old_alpha = self.alpha

        # Fill
        self.color = fill_color
        self.alpha = fill_alpha_highlight if self.is_highlight else fill_alpha
        self.draw_custom_shape(self._fill_shape)

        # Outline
        self.color = outline_color
        self.alpha = outline_alpha_highlight if self.is_highlight else outline_alpha

        gpu.state.blend_set('ALPHA')
        gpu.state.line_width_set(PLANE_LINE_WIDTH)
        self.draw_custom_shape(self._line_shape)
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')
        
        self.color = old_color
        self.alpha = old_alpha

    def draw_select(self, context, select_id):
        # Use the full quad for selection.
        self.draw_custom_shape(self._fill_shape, select_id=select_id)


class CURSORTRANSFORM_GT_rotate_free_disc(bpy.types.Gizmo):
    """Hoverable free-rotation disc used to start trackball-style cursor rotation."""
    bl_idname = "CURSORTRANSFORM_GT_rotate_free_disc"

    def setup(self):
        """
        Build the cached filled-disc shape used for free-rotation hit testing and hover.
        """
        if hasattr(self, "_shape"):
            return

        self._shape = self.new_custom_shape(
            'TRIS',
            _build_circle_fan_vertices(radius=1.0, segments=48),
        )

    def draw(self, context):
        self.draw_custom_shape(self._shape)

    def draw_select(self, context, select_id):
        self.draw_custom_shape(self._shape, select_id=select_id)

    def test_select(self, context, location):
        """
        Return a hit only inside the free-rotation disc and outside the move-center deadzone.
        """
        center_2d = view3d_utils.location_3d_to_region_2d(
            context.region, context.region_data, self.matrix_basis.translation
        )
        if center_2d is None:
            return -1

        mouse = Vector(location)
        dist = (mouse - center_2d).length

        outer_radius      = 75.0 * ROTATE_VIEW_RING_PIXEL_RADIUS * FREE_ROTATE_DISC_SCALE_FACTOR
        move_center_radius = (
            75.0
            * FREE_ROTATE_DISC_CENTER_DEADZONE_FACTOR
        )

        if dist <= move_center_radius:
            return -1
        if dist <= outer_radius:
            return 0
        return -1


class CURSORTRANSFORM_GT_rotate_sector(bpy.types.Gizmo):
    """Filled rotation sector overlay used for active constrained rotation feedback."""
    bl_idname = "CURSORTRANSFORM_GT_rotate_sector"

    def setup(self):
        """
        Build cached shapes that do not depend on the current drag angle.
        """
        if hasattr(self, "_full_sector_shape"):
            return

        self._full_sector_shape = self.new_custom_shape(
            'TRIS',
            _build_sector_fan_vertices(0.0, math.tau, 64),
        )

    def draw(self, context):
        """
        Draw the active rotation sector fill and its start/end radius markers.
        """
        start_angle = getattr(self, "start_angle", 0.0)
        total_angle = getattr(self, "total_angle", 0.0)

        start_width = float(getattr(self, "start_width", 1.0))
        end_width = float(getattr(self, "end_width", 1.0))

        sign = 1.0 if total_angle >= 0.0 else -1.0
        abs_angle = abs(total_angle)

        full_turns = int(abs_angle // math.tau)
        remainder = abs_angle - (full_turns * math.tau)

        radius_color = getattr(self, "radius_color", (1.0, 1.0, 1.0))
        fill_alpha = float(getattr(self, "fill_alpha", 0.25))

        old_color = self.color
        old_alpha = self.alpha

        # Draw the filled sector first so the radius markers remain visible on top.
        self.color = (1.0, 1.0, 1.0)
        self.alpha = fill_alpha

        if full_turns > 0:
            for _ in range(full_turns):
                self.draw_custom_shape(self._full_sector_shape)

        if remainder > 1e-6:
            a1 = start_angle + (sign * remainder)
            steps = max(12, int(ROTATE_SECTOR_STEPS * (remainder / math.tau)))
            part_shape = self.new_custom_shape(
                'TRIS',
                _build_sector_fan_vertices(start_angle, a1, steps),
            )
            self.draw_custom_shape(part_shape)

        self.color = radius_color
        self.alpha = 1.0

        start_shape = self.new_custom_shape(
            'TRIS',
            _build_radius_quad_vertices(start_angle, start_width),
        )
        self.draw_custom_shape(start_shape)

        end_shape = self.new_custom_shape(
            'TRIS',
            _build_radius_quad_vertices(start_angle + total_angle, end_width),
        )
        self.draw_custom_shape(end_shape)

        self.color = old_color
        self.alpha = old_alpha

    def draw_select(self, context, select_id):
        # This overlay is visual only and does not participate in selection.
        pass


class CURSORTRANSFORM_GT_axis_line(bpy.types.Gizmo):
    """
    Full-screen constraint axis line, rendered as a long 3D line through the
    cursor along the world-space rotation axis.

    Previously this was drawn in screen space via a POST_PIXEL draw handler,
    which forced it to render after the entire gizmo pass — covering the
    Ctrl-snap tick marks and any other rotation overlay gizmos. Drawing as a
    3D gizmo instead keeps it inside the same draw pass as the rings, sector,
    and ticks, so registration order in the gizmo group controls visual
    layering: sector under, axis line in the middle, ticks on top.

    Visual behavior matches the screen-space version: the line projects to
    a 2D screen-space line in the direction of the projected axis, naturally
    collapsing to a point when the camera looks straight along the axis.
    World-space endpoints are placed far enough from the cursor that they
    exit any reasonable viewport at any zoom level, while staying small
    enough to avoid floating-point precision artifacts.
    """
    bl_idname = "CURSORTRANSFORM_GT_axis_line"

    def draw(self, context):
        line_width_px = float(getattr(self, "line_width", ROTATE_CONSTRAINT_LINE_WIDTH))
        color = getattr(self, "axis_color", (1.0, 1.0, 1.0, 1.0))

        # Same DPI scaling as the tick gizmo — pixel_size compensates for
        # OS DPI scaling and Blender's Resolution Scale so the line keeps
        # the same physical thickness across displays.
        line_width_scaled = line_width_px * context.preferences.system.pixel_size

        # The line extends along the local Z axis to match the dial-ring
        # matrix convention used elsewhere (e.g. AXIS_ROT and the rotation
        # ring gizmos): rings live in local XY, with local Z being the
        # axis of rotation perpendicular to the ring. Configuring this
        # gizmo with the same matrix as a rotation ring places its line
        # along the world-space rotation axis automatically.
        far = 1.0e4
        verts = [(0.0, 0.0, -far), (0.0, 0.0, far)]

        shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'LINES', {"pos": verts})

        gpu.state.blend_set('ALPHA')

        # Save previous depth state. The axis line should:
        #   1. Draw over scene geometry (matching native Blender — line is
        #      visible through walls during rotation).
        #   2. Not block other gizmo elements drawn after it. The wedge,
        #      rings, and tick marks should all render on top regardless
        #      of where in 3D space they happen to overlap the line.
        # Depth-test 'NONE' satisfies (1); depth-mask False satisfies (2)
        # by leaving the depth buffer untouched. Both are restored after
        # the draw so we don't leak state into other gizmo draws or the
        # rest of the viewport pass.
        prev_depth_test = gpu.state.depth_test_get()
        prev_depth_mask = gpu.state.depth_mask_get()
        gpu.state.depth_test_set('NONE')
        gpu.state.depth_mask_set(False)

        with gpu.matrix.push_pop():
            gpu.matrix.multiply_matrix(self.matrix_world)

            shader.bind()
            shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
            shader.uniform_float("lineWidth", line_width_scaled)
            shader.uniform_float("color", color)
            batch.draw(shader)

        gpu.state.depth_mask_set(prev_depth_mask)
        gpu.state.depth_test_set(prev_depth_test)
        gpu.state.blend_set('NONE')

    def draw_select(self, context, select_id):
        # Visual only; no selection participation.
        pass


class CURSORTRANSFORM_GT_rotate_ticks(bpy.types.Gizmo):
    """
    Ctrl-snap tick marks rendered as a 3D gizmo.

    Drawing in 3D space (rather than screen space as before) gives two
    benefits at once:
      - Ticks sit precisely on the projected ring at every angle, because
        the gizmo's matrix_world transforms a unit ring into the same
        screen ellipse the rotation ring already uses.
      - Tick length and offset are expressed in local (ring-radius) units,
        so they scale with scale_basis instead of being hard-coded in
        pixels. Identical proportional appearance at any monitor resolution.

    Antialiasing: lines are drawn with the POLYLINE_UNIFORM_COLOR built-in
    shader, the same path Blender's own gizmos use, which produces smooth
    "vector-style" edges via per-pixel coverage. tick_width is the line
    width uniform in screen pixels — that's the one piece that remains
    pixel-based, matching Blender's native gizmo line-width convention.

    Geometry: a tick at parametric angle θ is one line segment from the
    base point (radius 1.0 + tick_offset along (cos θ, sin θ, 0)) out to
    the tip (radius 1.0 + tick_offset + tick_length along the same
    direction). Ticks run from start_angle through start_angle + 2π in 5°
    steps.
    """
    bl_idname = "CURSORTRANSFORM_GT_rotate_ticks"

    def draw(self, context):
        start_angle = float(getattr(self, "start_angle", 0.0))
        tick_offset = float(getattr(self, "tick_offset", ROTATE_TICK_OFFSET_LOCAL))
        tick_length = float(getattr(self, "tick_length", ROTATE_TICK_LENGTH_LOCAL))
        tick_width_px = float(getattr(self, "tick_width", ROTATE_TICK_WIDTH_PX))
        tick_color = getattr(self, "tick_color", ROTATE_TICK_COLOR)

        # Scale line width by the system's pixel_size multiplier so a tick
        # set to N "logical" pixels keeps the same physical thickness on
        # any display. This is the same multiplier Blender uses for its
        # own UI line widths — it combines OS DPI scaling and the user's
        # Resolution Scale preference. Without this, line widths set in
        # absolute device pixels render thinner on higher-DPI displays.
        # tick_offset and tick_length don't need this because they're in
        # local-space units that already get scaled through matrix_world.
        tick_width_scaled = tick_width_px * context.preferences.system.pixel_size

        # Build LINE-pair vertices for every 5° tick. Each tick is a single
        # line segment from base to tip in the gizmo's local frame; the
        # gizmo's matrix_world (applied below via gpu.matrix) transforms
        # the entire batch into world space.
        verts = []
        step = ROTATE_SNAP_STEP
        end_angle = start_angle + math.tau
        angle = start_angle
        while angle < end_angle - 1e-6:
            c = math.cos(angle)
            s = math.sin(angle)
            base = (c * (1.0 + tick_offset), s * (1.0 + tick_offset), 0.0)
            tip = (
                c * (1.0 + tick_offset + tick_length),
                s * (1.0 + tick_offset + tick_length),
                0.0,
            )
            verts.append(base)
            verts.append(tip)
            angle += step

        if not verts:
            return

        shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'LINES', {"pos": verts})

        gpu.state.blend_set('ALPHA')

        # Same depth state handling as the axis line — depth-test off so
        # ticks render over scene geometry (the rotation overlay should
        # always be visible during rotation), depth-mask off so they don't
        # write to the depth buffer. State is restored after the draw.
        prev_depth_test = gpu.state.depth_test_get()
        prev_depth_mask = gpu.state.depth_mask_get()
        gpu.state.depth_test_set('NONE')
        gpu.state.depth_mask_set(False)

        # gpu.matrix transforms apply to all subsequent draws within the
        # push_pop block. Multiplying the gizmo's matrix_world maps our
        # local-space tick coordinates into world space, where the
        # ModelViewProjectionMatrix uniform on the shader picks them up
        # correctly. (matrix_world already incorporates matrix_basis,
        # scale_basis, and any other gizmo-internal transforms.)
        with gpu.matrix.push_pop():
            gpu.matrix.multiply_matrix(self.matrix_world)

            shader.bind()
            shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
            shader.uniform_float("lineWidth", tick_width_scaled)
            shader.uniform_float("color", tick_color)
            batch.draw(shader)

        gpu.state.depth_mask_set(prev_depth_mask)
        gpu.state.depth_test_set(prev_depth_test)
        gpu.state.blend_set('NONE')

    def draw_select(self, context, select_id):
        # Visual only; no selection participation.
        pass


class CURSORTRANSFORM_GGT_main(bpy.types.GizmoGroup):
    """Main gizmo group that draws the 3D Cursor translation and rotation controls."""
    bl_idname = "CURSORTRANSFORM_GGT_main"
    bl_label  = "3D Cursor Transform Gizmo"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D', 'PERSISTENT', 'SHOW_MODAL_ALL'}

    @classmethod
    def poll(cls, context):
        """
        Show the gizmo group only in the 3D View when the Cursor tool and the
        relevant gizmo toggles are active.
        """
        if context.area is None or context.area.type != 'VIEW_3D':
            return False
        if context.space_data is None or context.space_data.type != 'VIEW_3D':
            return False
        if not active_tool_is_cursor(context):
            return False

        # Normal case: gizmo overlay on, sub-overlays usable.
        if (
            viewport_allows_gizmo(context)
            and (location_gizmo_enabled(context) or rotation_gizmo_enabled(context))
        ):
            return True

        return False

    def setup(self, context):
        """
        Create the gizmos used by the cursor transform group and bind their operators.
        """
        def _new_plane_square(selectable):
            gz = self.gizmos.new("CURSORTRANSFORM_GT_plane_square")
            gz.use_tooltip = False
            gz.use_draw_offset_scale = True
            gz.hide_select = not selectable
            return gz

        def _new_filled_dot(selectable):
            gz = self.gizmos.new("CURSORTRANSFORM_GT_filled_dot")
            gz.use_tooltip = False
            gz.hide_select = not selectable
            return gz

        def _new_rotate_ring(op_id):
            gz = self.gizmos.new("GIZMO_GT_dial_3d")
            gz.use_tooltip = False
            gz.line_width = 3
            gz.alpha = AXIS_IDLE_ALPHA
            gz.alpha_highlight = AXIS_ACTIVE_ALPHA
            gz.draw_options = {'CLIP'}
            gz.target_set_operator(op_id)
            return gz        
        
        self.move_arrows = {}
        for axis in ("X", "Y", "Z"):
            gz = self.gizmos.new("GIZMO_GT_arrow_3d")
            gz.use_tooltip = False
            gz.line_width = 2
            gz.alpha = AXIS_IDLE_ALPHA
            gz.alpha_highlight = AXIS_ACTIVE_ALPHA

            # Default arrow layout before runtime state is applied in draw_prepare().
            gz.length = 1.25
            gz.scale_basis = 0.34
            gz.use_draw_offset_scale = True

            # Offset the arrow along its local +Z axis so the default placement
            # matches Blender's native transform gizmo layout more closely.
            gz.matrix_offset = Matrix.Translation((0.0, 0.0, 0.62))

            props = gz.target_set_operator("cursortransform.translate")
            props.axis = axis
            self.move_arrows[axis] = gz

        self.move_planes = {}
        for plane in ("XY", "XZ", "YZ"):
            gz = _new_plane_square(selectable=True)

            props = gz.target_set_operator("cursortransform.translate_plane")
            props.plane = plane

            self.move_planes[plane] = gz

        self.ghost_move_planes = {}
        for plane in ("XY", "XZ", "YZ"):
            self.ghost_move_planes[plane] = _new_plane_square(selectable=False)

        self.ghost_move_arrow = self.gizmos.new("GIZMO_GT_arrow_3d")
        self.ghost_move_arrow.use_tooltip = False
        self.ghost_move_arrow.hide_select = True
        self.ghost_move_arrow.line_width = 2
        self.ghost_move_arrow.use_draw_offset_scale = True

        self.ghost_center_dot = _new_filled_dot(selectable=False)

        self.ghost_move_center = self.gizmos.new("GIZMO_GT_move_3d")
        self.ghost_move_center.use_tooltip = False
        self.ghost_move_center.hide_select = True
        self.ghost_move_center.line_width = 2
        self.ghost_move_center.draw_options = {'FILL_SELECT', 'ALIGN_VIEW'}
        
        self.axis_center_dots = {}
        for axis in ("X", "Y", "Z"):
            self.axis_center_dots[axis] = _new_filled_dot(selectable=False)
        
        # Create the free-rotation disc before the move center so the move center
        # takes precedence in overlapping hit-test regions.
        self.rotate_free_disc = self.gizmos.new("CURSORTRANSFORM_GT_rotate_free_disc")
        self.rotate_free_disc.use_tooltip = False
        self.rotate_free_disc.target_set_operator("cursortransform.rotate_free_modal")

        # Create the move center after the free-rotation disc so it wins the hit-test
        # order in the shared center region.
        self.move_center = self.gizmos.new("GIZMO_GT_move_3d")
        self.move_center.use_tooltip = False
        self.move_center.line_width = 2
        self.move_center.draw_options = {'FILL_SELECT', 'ALIGN_VIEW'}
        self.move_center.target_set_operator("cursortransform.translate_free")

        # Registration order matters here: Blender draws gizmos in REVERSE
        # registration order within a group, so the gizmo registered last
        # is drawn first (and ends up at the bottom of the visual stack).
        # The desired stack from bottom to top is: axis_line, sector wedge,
        # rotation rings, tick marks. So we register them in the opposite
        # order: ticks first (top), then rings, then sector, then axis_line
        # last (bottom). (Verified empirically via draw-order tracing.)
        self.rotate_ticks = self.gizmos.new("CURSORTRANSFORM_GT_rotate_ticks")
        self.rotate_ticks.use_tooltip = False
        self.rotate_ticks.hide_select = True

        rotate_ops = {
            "X": "cursortransform.rotate_x",
            "Y": "cursortransform.rotate_y",
            "Z": "cursortransform.rotate_z",
        }

        self.rotate_rings = {}
        for axis in ("X", "Y", "Z"):
            self.rotate_rings[axis] = _new_rotate_ring(rotate_ops[axis])

        self.view_ring = self.gizmos.new("GIZMO_GT_dial_3d")
        self.view_ring.use_tooltip = False
        self.view_ring.line_width = 2
        self.view_ring.alpha = 0.5
        self.view_ring.alpha_highlight = 1.0
        self.view_ring.target_set_operator("cursortransform.rotate_view")

        # Sector wedge registered after the rings → drawn before the rings →
        # ends up underneath them. The wedge fill and its start/end radius
        # markers therefore appear behind the highlighted ring stroke, which
        # matches native Blender's rotation gizmo layering.
        self.rotate_sector = self.gizmos.new("CURSORTRANSFORM_GT_rotate_sector")
        self.rotate_sector.use_tooltip = False
        self.rotate_sector.hide_select = True

        # Axis lines registered last → drawn first → bottom of the stack.
        # Three instances, one per X/Y/Z. During normal constrained rotation
        # only the active axis line is shown; during MMB axis pickup all
        # three are shown together (with the preselected one highlighted).
        self.axis_lines = {}
        for axis in ("X", "Y", "Z"):
            gz = self.gizmos.new("CURSORTRANSFORM_GT_axis_line")
            gz.use_tooltip = False
            gz.hide_select = True
            self.axis_lines[axis] = gz

    def draw_prepare(self, context):
        """
        Update gizmo visibility, transforms, colors, and ghost states before drawing.
        """
        loc = context.scene.cursor.location

        orient = build_orient_matrix(context)
        view_m = get_view_rot_matrix(context)
        loc_m = Matrix.Translation(loc)

        gizmo_colors = get_theme_gizmo_colors(context)
        ax = {
            "X": gizmo_colors["X"],
            "Y": gizmo_colors["Y"],
            "Z": gizmo_colors["Z"],
        }
        center_col = gizmo_colors["VIEW"]

        # Local gizmo-setup helpers keep repeated visual state assignment concise
        # without changing the control flow of draw_prepare().
        def _apply_filled_dot(gz, matrix_basis, scale_basis, color, alpha):
            gz.matrix_basis = matrix_basis
            gz.scale_basis = scale_basis
            gz.color = color
            gz.color_highlight = color
            gz.alpha = alpha
            gz.alpha_highlight = alpha

        def _apply_move_center(gz, matrix_basis, scale_basis, color, alpha, alpha_highlight):
            gz.matrix_basis = matrix_basis
            gz.scale_basis = scale_basis
            gz.color = color
            gz.color_highlight = color
            gz.alpha = alpha
            gz.alpha_highlight = alpha_highlight

        def _apply_plane_square(
            gz,
            matrix_basis,
            matrix_offset,
            scale_basis,
            fill_color,
            outline_color,
            fill_alpha,
            outline_alpha,
            fill_alpha_highlight,
            outline_alpha_highlight,
        ):
            gz.matrix_basis = matrix_basis
            gz.matrix_offset = matrix_offset
            gz.scale_basis = scale_basis
            gz.fill_color = fill_color
            gz.outline_color = outline_color
            gz.color = fill_color
            gz.color_highlight = fill_color
            gz.fill_alpha = fill_alpha
            gz.outline_alpha = outline_alpha
            gz.fill_alpha_highlight = fill_alpha_highlight
            gz.outline_alpha_highlight = outline_alpha_highlight
            gz.alpha = fill_alpha
            gz.alpha_highlight = fill_alpha_highlight

        def _apply_arrow(gz, matrix_basis, scale_basis, length, matrix_offset, color, alpha, alpha_highlight):
            gz.matrix_basis = matrix_basis
            gz.scale_basis = scale_basis
            gz.length = length
            gz.matrix_offset = matrix_offset
            gz.color = color
            gz.color_highlight = color
            gz.alpha = alpha
            gz.alpha_highlight = alpha_highlight

        def _apply_rotate_disc(gz, matrix_basis, scale_basis, color, alpha, alpha_highlight):
            gz.matrix_basis = matrix_basis
            gz.scale_basis = scale_basis
            gz.color = color
            gz.color_highlight = color
            gz.alpha = alpha
            gz.alpha_highlight = alpha_highlight

        def _apply_rotate_ring(gz, matrix_basis, scale_basis, color, alpha, alpha_highlight, draw_options):
            gz.matrix_basis = matrix_basis
            gz.scale_basis = scale_basis
            gz.color = color
            gz.color_highlight = color
            gz.alpha = alpha
            gz.alpha_highlight = alpha_highlight
            gz.draw_options = draw_options

        show_location = location_gizmo_enabled(context)
        show_rotation = rotation_gizmo_enabled(context)

        wm = context.window_manager
        translate_running = translate_modal_running(context)
        active_translate_axis = wm.cursortransform_active_translate_axis
        active_rotate_axis = wm.cursortransform_active_rotate_axis
        rotate_running = active_rotate_axis in {"X", "Y", "Z", "VIEW", "FREE"}
        free_rotate_running = (active_rotate_axis == "FREE")

        # Hide custom gizmos during native rotate/trackball after an R-swap.
        native_cursor_rotate_running = (
            active_tool_is_cursor(context)
            and native_rotate_modal_running(context)
        )

        if native_cursor_rotate_running:
            for gz in self.gizmos:
                gz.hide = True
            return

        global _TRANSLATE_GHOST_START_LOC
        global _TRANSLATE_GHOST_START_ORIENT

        global _ROTATE_ACTIVE_ORIENT
        global _ROTATE_ACTIVE_VIEW

        global _ROTATE_GUIDE_START_ANGLE
        global _ROTATE_GUIDE_TOTAL_ANGLE

        if not translate_running and active_translate_axis:
            wm.cursortransform_active_translate_axis = ""
            active_translate_axis = ""

        if not rotate_running and active_rotate_axis:
            wm.cursortransform_active_rotate_axis = ""
            active_rotate_axis = ""

        if not translate_running:
            _TRANSLATE_GHOST_START_LOC = None
            _TRANSLATE_GHOST_START_ORIENT = None

        rotate_basis = orient
        rotate_view_basis = view_m

        if rotate_running:
            if _ROTATE_ACTIVE_ORIENT is not None:
                rotate_basis = _ROTATE_ACTIVE_ORIENT
            if _ROTATE_ACTIVE_VIEW is not None:
                rotate_view_basis = _ROTATE_ACTIVE_VIEW

        hide_rotation_while_moving = (
            show_location
            and show_rotation
            and translate_running
        )

        active_axis_move = translate_running and active_translate_axis in {"X", "Y", "Z"}
        active_plane_move = translate_running and active_translate_axis in {"XY", "XZ", "YZ"}

        # Arrows
        for axis, gz in self.move_arrows.items():
            gz.hide = (not show_location) or rotate_running
            if gz.hide:
                continue

            is_active_move_axis = (
                translate_running and active_translate_axis == axis
            )

            if not show_rotation:
                arrow_length = 1.1
                arrow_offset = Matrix.Translation((0.0, 0.0, 0.22))
            elif translate_running:
                if is_active_move_axis:
                    arrow_length = 1.35
                    arrow_offset = Matrix.Translation((0.0, 0.0, 0.06))
                else:
                    arrow_length = 1.1
                    arrow_offset = Matrix.Translation((0.0, 0.0, 0.22))
            else:
                # Location + Rotation idle: arrow heads only
                arrow_length = 0.0
                arrow_offset = Matrix.Translation((0.0, 0.0, 1.35))

            axis_vec = orient.col[AXIS_INDEX[axis]].to_3d()

            if is_active_move_axis:
                axis_alpha = AXIS_ACTIVE_ALPHA
            else:
                axis_alpha = AXIS_IDLE_ALPHA * axis_view_alpha(context, axis_vec)

            _apply_arrow(
                gz,
                loc_m @ orient @ AXIS_ROT[axis],
                1.05,
                arrow_length,
                arrow_offset,
                ax[axis],
                axis_alpha,
                AXIS_ACTIVE_ALPHA,
            )

        # Plane squares (location-only mode)
        show_move_planes = (
            show_location
            and not show_rotation
        )

        for plane, gz in self.move_planes.items():
            is_active_plane = active_plane_move and active_translate_axis == plane

            gz.hide = (
                (not show_move_planes)
                or rotate_running
                or (translate_running and not is_active_plane)
            )
            if gz.hide:
                continue

            plane_normal_axis = PLANE_NORMAL_AXIS[plane]
            plane_col = ax[plane_normal_axis]
            plane_normal_vec = orient.col[AXIS_INDEX[plane_normal_axis]].to_3d()

            plane_fade = plane_view_alpha(context, plane_normal_vec)

            base_fill_alpha = PLANE_FILL_ALPHA * plane_fade
            base_outline_alpha = PLANE_OUTLINE_ALPHA * plane_fade
            hover_fill_alpha = PLANE_FILL_HOVER_ALPHA * plane_fade
            hover_outline_alpha = PLANE_OUTLINE_HOVER_ALPHA * plane_fade

            _apply_plane_square(
                gz,
                loc_m @ orient,
                Matrix.Translation(PLANE_OFFSET[plane]) @ PLANE_ROT[plane],
                PLANE_SCALE_BASIS,
                plane_col,
                plane_col,
                hover_fill_alpha if is_active_plane else base_fill_alpha,
                hover_outline_alpha if is_active_plane else base_outline_alpha,
                hover_fill_alpha,
                hover_outline_alpha,
            )

        # Center handle
        self.move_center.hide = (not show_location) or active_axis_move or active_plane_move or rotate_running
        if not self.move_center.hide:
            _apply_move_center(
                self.move_center,
                loc_m @ view_m,
                0.20,
                center_col,
                0.5,
                1.0,
            )

        for axis, gz in self.axis_center_dots.items():
            is_active_move_axis = (
                show_location
                and translate_running
                and active_translate_axis == axis
            )

            is_active_move_plane = (
                show_location
                and active_plane_move
                and PLANE_NORMAL_AXIS.get(active_translate_axis) == axis
            )

            show_dot = is_active_move_axis or is_active_move_plane

            gz.hide = not show_dot
            if gz.hide:
                continue

            active_col = ax[axis]

            _apply_filled_dot(
                gz,
                loc_m @ view_m,
                1.35,
                active_col,
                AXIS_ACTIVE_ALPHA,
            )

        # Ghost active axis / plane at the start position
        show_ghost_axis = (
            active_axis_move
            and _TRANSLATE_GHOST_START_LOC is not None
            and _TRANSLATE_GHOST_START_ORIENT is not None
        )

        show_ghost_plane = (
            active_plane_move
            and _TRANSLATE_GHOST_START_LOC is not None
            and _TRANSLATE_GHOST_START_ORIENT is not None
        )

        self.ghost_move_arrow.hide = not show_ghost_axis
        self.ghost_center_dot.hide = not (show_ghost_axis or show_ghost_plane)

        # Ghost active plane square at the start position
        for plane, gz in self.ghost_move_planes.items():
            gz.hide = not (show_ghost_plane and active_translate_axis == plane)

        if show_ghost_plane:
            ghost_loc_m = Matrix.Translation(_TRANSLATE_GHOST_START_LOC)
            ghost_orient = _TRANSLATE_GHOST_START_ORIENT
            ghost_col = (0.50, 0.50, 0.50)

            _apply_filled_dot(
                self.ghost_center_dot,
                ghost_loc_m @ view_m,
                1.35,
                ghost_col,
                GHOST_AXIS_ALPHA,
            )

            ghost_plane = active_translate_axis
            ghost_gz = self.ghost_move_planes[ghost_plane]

            _apply_plane_square(
                ghost_gz,
                ghost_loc_m @ ghost_orient,
                Matrix.Translation(PLANE_OFFSET[ghost_plane]) @ PLANE_ROT[ghost_plane],
                PLANE_SCALE_BASIS,
                ghost_col,
                ghost_col,
                GHOST_PLANE_FILL_ALPHA,
                GHOST_PLANE_OUTLINE_ALPHA,
                GHOST_PLANE_FILL_ALPHA,
                GHOST_PLANE_OUTLINE_ALPHA,
            )

        if show_ghost_axis:
            ghost_loc_m = Matrix.Translation(_TRANSLATE_GHOST_START_LOC)
            ghost_orient = _TRANSLATE_GHOST_START_ORIENT
            ghost_col = (0.50, 0.50, 0.50)

            _apply_arrow(
                self.ghost_move_arrow,
                ghost_loc_m @ ghost_orient @ AXIS_ROT[active_translate_axis],
                1.05,
                1.35,
                Matrix.Translation((0.0, 0.0, 0.06)),
                ghost_col,
                GHOST_AXIS_ALPHA,
                GHOST_AXIS_ALPHA,
            )

            _apply_filled_dot(
                self.ghost_center_dot,
                ghost_loc_m @ view_m,
                1.35,
                ghost_col,
                GHOST_AXIS_ALPHA,
            )

        # Ghost free-move center at the start position
        show_ghost_move_center = (
            translate_running
            and active_translate_axis == ""
            and _TRANSLATE_GHOST_START_LOC is not None
        )

        self.ghost_move_center.hide = not show_ghost_move_center

        if show_ghost_move_center:
            ghost_loc_m = Matrix.Translation(_TRANSLATE_GHOST_START_LOC)
            ghost_col = (0.50, 0.50, 0.50)

            _apply_move_center(
                self.ghost_move_center,
                ghost_loc_m @ view_m,
                0.20,
                ghost_col,
                GHOST_AXIS_ALPHA,
                GHOST_AXIS_ALPHA,
            )

        # Free rotate hover disc
        show_rotate_free_disc = (
            show_rotation
            and not hide_rotation_while_moving
            and not rotate_running
        )

        self.rotate_free_disc.hide = not show_rotate_free_disc

        if show_rotate_free_disc:
            disc_scale = 1.20 * FREE_ROTATE_DISC_SCALE_FACTOR

            _apply_rotate_disc(
                self.rotate_free_disc,
                loc_m @ rotate_view_basis,
                disc_scale,
                (1.0, 1.0, 1.0),
                0.0,
                FREE_ROTATE_DISC_HOVER_ALPHA,
            )

        # Active rotation sector and radius markers
        show_rotate_sector = rotate_running and not free_rotate_running

        self.rotate_sector.hide = not show_rotate_sector

        if show_rotate_sector:
            if active_rotate_axis == "VIEW":
                sector_basis = loc_m @ rotate_view_basis
                sector_scale = 1.20 * ROTATE_VIEW_SECTOR_SCALE_FACTOR
                sector_color = center_col
            else:
                sector_basis = loc_m @ rotate_basis @ AXIS_ROT[active_rotate_axis]
                sector_scale = 1.02 * ROTATE_SECTOR_SCALE_FACTOR
                sector_color = ax[active_rotate_axis]

            if active_rotate_axis == "VIEW":
                self.rotate_sector.start_width = ROTATE_VIEW_SECTOR_START_RADIUS_WIDTH
                self.rotate_sector.end_width = ROTATE_VIEW_SECTOR_END_RADIUS_WIDTH
            else:
                self.rotate_sector.start_width = ROTATE_SECTOR_START_RADIUS_WIDTH
                self.rotate_sector.end_width = ROTATE_SECTOR_END_RADIUS_WIDTH

            self.rotate_sector.matrix_basis = sector_basis
            self.rotate_sector.scale_basis = sector_scale
            self.rotate_sector.start_angle = _ROTATE_GUIDE_START_ANGLE
            self.rotate_sector.total_angle = _ROTATE_GUIDE_TOTAL_ANGLE
            self.rotate_sector.radius_color = sector_color
            self.rotate_sector.fill_alpha = ROTATE_SECTOR_FILL_COLOR[3]

        # Fullscreen constraint axis lines. Up to three are shown:
        #   - Normal constrained rotation (X/Y/Z, MMB not held): only the
        #     active axis line is visible, fully colored.
        #   - VIEW rotation (MMB not held): no axis line is visible.
        #   - MMB axis pickup (held during any constrained or view rotation):
        #     all three X/Y/Z axis lines are visible. The currently-active
        #     axis (which switches in real time as the mouse moves near a
        #     different axis line) is fully colored; the others are dimmed.
        # The gizmos are registered last in setup(), so they draw at the
        # bottom of the stack — the rotation rings, wedge, and tick marks
        # all render on top.
        for axis in ("X", "Y", "Z"):
            gz = self.axis_lines[axis]

            if _ROTATE_MMB_HELD and rotate_running:
                # MMB hold: all three lines visible; active full, others dim.
                if axis == active_rotate_axis:
                    alpha = 1.0
                else:
                    alpha = ROTATE_MMB_AXIS_LINE_DIM_ALPHA

                axis_rgb = axis_highlight_color(ax[axis])
                gz.hide = False
                gz.matrix_basis = (
                    loc_m @ rotate_basis @ AXIS_ROT[axis]
                )
                gz.scale_basis = 1.0
                gz.line_width = ROTATE_CONSTRAINT_LINE_WIDTH
                gz.axis_color = (axis_rgb[0], axis_rgb[1], axis_rgb[2], alpha)

            elif rotate_running and axis == active_rotate_axis:
                # Normal constrained rotation: only the active axis line.
                axis_rgb = axis_highlight_color(ax[axis])
                gz.hide = False
                gz.matrix_basis = (
                    loc_m @ rotate_basis @ AXIS_ROT[axis]
                )
                gz.scale_basis = 1.0
                gz.line_width = ROTATE_CONSTRAINT_LINE_WIDTH
                gz.axis_color = (axis_rgb[0], axis_rgb[1], axis_rgb[2], 1.0)

            else:
                gz.hide = True

        # Ctrl-snap tick marks. Drawn as a 3D gizmo so they sit precisely on
        # the projected ring at every angle and scale with the gizmo size
        # rather than being expressed in screen pixels. Same matrix and scale
        # as the active ring — the tick gizmo's tick_offset/tick_length place
        # the marks just inside or outside the perimeter.
        show_rotate_ticks = (
            show_rotate_sector
            and _ROTATE_GUIDE_CTRL_PRESSED
        )

        self.rotate_ticks.hide = not show_rotate_ticks

        if show_rotate_ticks:
            if active_rotate_axis == "VIEW":
                ticks_basis = loc_m @ rotate_view_basis
                ticks_scale = 1.20
                self.rotate_ticks.tick_offset = ROTATE_VIEW_TICK_OFFSET_LOCAL
                self.rotate_ticks.tick_length = ROTATE_VIEW_TICK_LENGTH_LOCAL
                self.rotate_ticks.tick_width = ROTATE_VIEW_TICK_WIDTH_PX
            else:
                ticks_basis = loc_m @ rotate_basis @ AXIS_ROT[active_rotate_axis]
                ticks_scale = 1.0
                self.rotate_ticks.tick_offset = ROTATE_TICK_OFFSET_LOCAL
                self.rotate_ticks.tick_length = ROTATE_TICK_LENGTH_LOCAL
                self.rotate_ticks.tick_width = ROTATE_TICK_WIDTH_PX

            self.rotate_ticks.matrix_basis = ticks_basis
            self.rotate_ticks.scale_basis = ticks_scale
            self.rotate_ticks.start_angle = _ROTATE_GUIDE_START_ANGLE
            self.rotate_ticks.tick_color = ROTATE_TICK_COLOR

        # Axis rings
        for axis, gz in self.rotate_rings.items():
            is_active_rotate_axis = rotate_running and active_rotate_axis == axis
            draw_options = set() if is_active_rotate_axis else {'CLIP'}

            gz.hide = (
                ((not show_rotation) and not is_active_rotate_axis)
                or hide_rotation_while_moving
                or (rotate_running and not is_active_rotate_axis)
            )
            if gz.hide:
                continue

            ring_basis = rotate_basis if is_active_rotate_axis else orient

            _apply_rotate_ring(
                gz,
                loc_m @ ring_basis @ AXIS_ROT[axis],
                1.0,
                ax[axis],
                AXIS_ACTIVE_ALPHA if is_active_rotate_axis else AXIS_IDLE_ALPHA,
                AXIS_ACTIVE_ALPHA,
                draw_options,
            )

        # Outer view ring
        self.view_ring.hide = (
            ((not show_rotation) and active_rotate_axis != "VIEW")
            or hide_rotation_while_moving
            or (rotate_running and active_rotate_axis != "VIEW")
        )
        if not self.view_ring.hide:
            _apply_rotate_ring(
                self.view_ring,
                loc_m @ rotate_view_basis,
                1.20,
                center_col,
                AXIS_ACTIVE_ALPHA if active_rotate_axis == "VIEW" else 0.5,
                AXIS_ACTIVE_ALPHA,
                self.view_ring.draw_options,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Registration
# ─────────────────────────────────────────────────────────────────────────────

classes = (
    CURSORTRANSFORM_AddonPreferences,
    CURSORTRANSFORM_OT_rotate_modal,
    CURSORTRANSFORM_OT_rotate_free_modal,
    CURSORTRANSFORM_OT_translate_modal,
    CURSORTRANSFORM_OT_translate,
    CURSORTRANSFORM_OT_translate_free,
    CURSORTRANSFORM_OT_translate_plane,
    CURSORTRANSFORM_OT_rotate_x,
    CURSORTRANSFORM_OT_rotate_y,
    CURSORTRANSFORM_OT_rotate_z,
    CURSORTRANSFORM_OT_rotate_view,
    CURSORTRANSFORM_GT_filled_dot,
    CURSORTRANSFORM_GT_plane_square,
    CURSORTRANSFORM_GT_rotate_free_disc,
    CURSORTRANSFORM_GT_rotate_sector,
    CURSORTRANSFORM_GT_axis_line,
    CURSORTRANSFORM_GT_rotate_ticks,
    CURSORTRANSFORM_GGT_main,
)


# Keymap items registered by this addon, stored so unregister() can remove them.
addon_keymaps = []


def _register_keymaps():
    """
    Register G and R for the 3D Cursor tool.

    The keymap is tool-scoped, so these shortcuts only run while Blender's
    Cursor tool is active. X/Y/Z are not registered here because Blender's
    native translate modal already handles axis constraints after G starts.
    """
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc is None:
        return

    km = kc.keymaps.new(name="3D View Tool: Cursor", space_type='VIEW_3D')

    kmi = km.keymap_items.new(
        idname="cursortransform.translate_modal",
        type='G',
        value='PRESS',
    )
    kmi.properties.release_confirm = False
    addon_keymaps.append((km, kmi))

    kmi = km.keymap_items.new(
        idname="cursortransform.rotate_view",
        type='R',
        value='PRESS',
    )
    addon_keymaps.append((km, kmi))


def _unregister_keymaps():
    """Remove all keymap entries this addon registered."""
    for km, kmi in addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except ReferenceError:
            pass
    addon_keymaps.clear()


def register():
    """Register the addon classes and runtime WindowManager properties."""
    global _CURSOR_ALIGN_IS_RUNNING

    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.WindowManager.cursortransform_active_translate_axis = (
        bpy.props.StringProperty(
            name="Active Cursor Transform Translate Axis",
            default="",
        )
    )

    bpy.types.WindowManager.cursortransform_active_rotate_axis = (
        bpy.props.StringProperty(
            name="Active Cursor Transform Rotate Axis",
            default="",
        )
    )

    _CURSOR_ALIGN_IS_RUNNING = False
    clear_cursor_align_cache()

    if cursor_align_rotation_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(
            cursor_align_rotation_handler
        )

    if not bpy.app.timers.is_registered(
        initialize_cursor_align_cache_after_register
    ):
        bpy.app.timers.register(
            initialize_cursor_align_cache_after_register,
            first_interval=0.0,
        )

    _register_keymaps()


def unregister():
    """Unregister the addon classes and remove runtime WindowManager properties."""
    global _CURSOR_ALIGN_IS_RUNNING

    _unregister_keymaps()

    if bpy.app.timers.is_registered(
        initialize_cursor_align_cache_after_register
    ):
        bpy.app.timers.unregister(
            initialize_cursor_align_cache_after_register
        )

    if cursor_align_rotation_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(
            cursor_align_rotation_handler
        )

    clear_cursor_align_cache()
    _CURSOR_ALIGN_IS_RUNNING = False

    if hasattr(
        bpy.types.WindowManager,
        "cursortransform_active_translate_axis",
    ):
        del bpy.types.WindowManager.cursortransform_active_translate_axis

    if hasattr(
        bpy.types.WindowManager,
        "cursortransform_active_rotate_axis",
    ):
        del bpy.types.WindowManager.cursortransform_active_rotate_axis

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)