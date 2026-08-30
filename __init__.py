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
    "description": (
        "Bring Blender's native transform system to the 3D Cursor "
        "with gizmos, constraints, and snapping."
    ),
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


def reset_cursor_rotation(cursor):
    """Reset the 3D Cursor rotation while preserving its rotation mode."""
    rotation_mode = cursor.rotation_mode

    if rotation_mode == 'QUATERNION':
        cursor.rotation_quaternion = Quaternion(
            (1.0, 0.0, 0.0, 0.0)
        )
    elif rotation_mode == 'AXIS_ANGLE':
        cursor.rotation_axis_angle = (
            0.0,
            0.0,
            0.0,
            1.0,
        )
    else:
        cursor.rotation_euler = (0.0, 0.0, 0.0)


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

def _build_sector_fan_vertices(start_angle, end_angle, steps):
    """Build triangle vertices for a filled circular sector."""
    vertices = []
    center = (0.0, 0.0, 0.0)
    previous_point = None

    for index in range(steps + 1):
        factor = index / steps
        angle = start_angle + (end_angle - start_angle) * factor
        point = (math.cos(angle), math.sin(angle), 0.0)

        if previous_point is not None:
            vertices.extend((center, previous_point, point))

        previous_point = point

    return vertices


def _build_radius_quad_vertices(angle, width):
    """Build triangle vertices for a thin sector-radius marker."""
    half_width = width * 0.01

    direction = Vector((
        math.cos(angle),
        math.sin(angle),
        0.0,
    ))
    normal = Vector((
        -direction.y,
        direction.x,
        0.0,
    )) * half_width

    start_left = Vector((0.0, 0.0, 0.0)) - normal
    start_right = Vector((0.0, 0.0, 0.0)) + normal
    end_right = direction + normal
    end_left = direction - normal

    return [
        tuple(start_left),
        tuple(start_right),
        tuple(end_right),
        tuple(start_left),
        tuple(end_right),
        tuple(end_left),
    ]


def _build_circle_fan_vertices(radius, segments):
    """Build triangle vertices for a filled circle."""
    vertices = []
    center = (0.0, 0.0, 0.0)

    for index in range(segments):
        start_angle = (index / segments) * math.tau
        end_angle = ((index + 1) / segments) * math.tau

        start_point = (
            math.cos(start_angle) * radius,
            math.sin(start_angle) * radius,
            0.0,
        )
        end_point = (
            math.cos(end_angle) * radius,
            math.sin(end_angle) * radius,
            0.0,
        )

        vertices.extend((center, start_point, end_point))

    return vertices


def _draw_dashed_line_2d(
    start,
    end,
    color,
    dash_length,
    gap_length,
    line_width,
):
    """Draw an antialiased dashed line in screen space."""
    if start is None or end is None:
        return

    line_vector = end - start
    line_length = line_vector.length

    if line_length <= 1e-6:
        return

    pixel_size = bpy.context.preferences.system.pixel_size
    dash_pixels = dash_length * pixel_size
    gap_pixels = gap_length * pixel_size
    width_pixels = line_width * pixel_size

    step = dash_pixels + gap_pixels

    if step <= 1e-6:
        return

    direction = line_vector.normalized()
    segments = []
    position = 0.0

    # Build the pattern backward so any partial dash ends near the pivot.
    while position < line_length:
        segment_end = end - direction * position
        segment_start = end - direction * min(
            position + dash_pixels,
            line_length,
        )

        segments.extend((segment_start, segment_end))
        position += step

    if not segments:
        return

    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    batch = batch_for_shader(
        shader,
        'LINES',
        {"pos": segments},
    )

    gpu.state.blend_set('ALPHA')

    shader.bind()
    shader.uniform_float(
        "viewportSize",
        gpu.state.viewport_get()[2:],
    )
    shader.uniform_float("lineWidth", width_pixels)
    shader.uniform_float("color", color)
    batch.draw(shader)

    gpu.state.blend_set('NONE')


def _draw_translate_axis_line_op(operator):
    """Draw translation constraint lines during the custom modal."""
    context = bpy.context

    if operator._mmb_held:
        axes_to_draw = ("X", "Y", "Z")
    elif operator._axis in {"X", "Y", "Z"}:
        axes_to_draw = (operator._axis,)
    elif operator._plane_exclude_axis in {"X", "Y", "Z"}:
        axes_to_draw = tuple(
            axis
            for axis in ("X", "Y", "Z")
            if axis != operator._plane_exclude_axis
        )
    else:
        return

    center_2d = view3d_utils.location_3d_to_region_2d(
        context.region,
        context.region_data,
        operator._start_loc,
    )

    if center_2d is None:
        return

    half_length_pixels = float(
        max(context.region.width, context.region.height) * 2.0
    )

    axis_colors = get_theme_gizmo_colors(context)
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')

    scaled_line_width = (
        ROTATE_CONSTRAINT_LINE_WIDTH
        * context.preferences.system.pixel_size
    )

    gpu.state.blend_set('ALPHA')

    shader.bind()
    shader.uniform_float(
        "viewportSize",
        gpu.state.viewport_get()[2:],
    )
    shader.uniform_float("lineWidth", scaled_line_width)

    for axis in axes_to_draw:
        axis_index = AXIS_INDEX[axis]
        axis_vector = (
            operator._get_active_orient()
            .col[axis_index]
            .to_3d()
            .normalized()
        )

        direction_2d = _project_axis_dir_2d(
            context,
            operator._start_loc,
            axis_vector,
        )

        if direction_2d is None:
            continue

        axis_color = axis_highlight_color(axis_colors[axis])

        if operator._mmb_held:
            alpha = (
                1.0
                if axis == operator._axis
                else ROTATE_MMB_AXIS_LINE_DIM_ALPHA
            )
        else:
            alpha = 1.0

        color = (
            axis_color[0],
            axis_color[1],
            axis_color[2],
            alpha,
        )

        line_start = Vector((
            center_2d.x - direction_2d.x * half_length_pixels,
            center_2d.y - direction_2d.y * half_length_pixels,
        ))
        line_end = Vector((
            center_2d.x + direction_2d.x * half_length_pixels,
            center_2d.y + direction_2d.y * half_length_pixels,
        ))

        batch = batch_for_shader(
            shader,
            'LINES',
            {"pos": [line_start, line_end]},
        )

        shader.uniform_float("color", color)
        batch.draw(shader)

    gpu.state.blend_set('NONE')


# ── 2D ring and rotation math ────────────────────────────────────────────────

def _solve_2d_basis(vector, basis_x, basis_y):
    """
    Express a 2D vector in the given basis.

    Return the two basis coefficients, or None if the basis is degenerate.
    """
    determinant = (
        basis_x.x * basis_y.y
        - basis_x.y * basis_y.x
    )

    if abs(determinant) < 1e-8:
        return None

    coefficient_x = (
        vector.x * basis_y.y
        - vector.y * basis_y.x
    ) / determinant

    coefficient_y = (
        basis_x.x * vector.y
        - basis_x.y * vector.x
    ) / determinant

    return coefficient_x, coefficient_y


def _wrap_pi(angle):
    """Wrap an angle to the range from -π to π."""
    return (angle + math.pi) % math.tau - math.pi


def _ellipse_angle_from_mouse(center, mouse, basis_x, basis_y):
    """Return the mouse angle within a projected ellipse basis."""
    if (
        center is None
        or mouse is None
        or basis_x is None
        or basis_y is None
    ):
        return None

    coefficients = _solve_2d_basis(
        mouse - center,
        basis_x,
        basis_y,
    )

    if coefficients is None:
        return None

    coefficient_x, coefficient_y = coefficients

    if (
        abs(coefficient_x) < 1e-8
        and abs(coefficient_y) < 1e-8
    ):
        return None

    return math.atan2(coefficient_y, coefficient_x)


def _map_to_arcball(center_2d, mouse_2d, radius_pixels):
    """
    Map a screen-space mouse position to a virtual unit sphere.

    Positions outside the sphere are projected onto its rim.
    """
    if (
        center_2d is None
        or mouse_2d is None
        or radius_pixels <= 1e-6
    ):
        return None

    x = (mouse_2d.x - center_2d.x) / radius_pixels
    y = (mouse_2d.y - center_2d.y) / radius_pixels
    distance_squared = x * x + y * y

    if distance_squared <= 1.0:
        z = math.sqrt(1.0 - distance_squared)
        return Vector((x, y, z)).normalized()

    inverse_length = 1.0 / math.sqrt(distance_squared)

    return Vector((
        x * inverse_length,
        y * inverse_length,
        0.0,
    )).normalized()


# ── Screen-space projection helpers ──────────────────────────────────────────

def _build_screen_space_ring_basis(
    context,
    center_2d,
    center_3d,
    ring_matrix,
    pixel_radius,
):
    """
    Build a fixed-size screen-space basis for a projected rotation ring.
    """
    if center_2d is None:
        return None, None

    sample_distance = ROTATE_RING_BASIS_SAMPLE

    point_x_2d = view3d_utils.location_3d_to_region_2d(
        context.region,
        context.region_data,
        center_3d
        + ring_matrix.col[0].to_3d() * sample_distance,
    )
    point_y_2d = view3d_utils.location_3d_to_region_2d(
        context.region,
        context.region_data,
        center_3d
        + ring_matrix.col[1].to_3d() * sample_distance,
    )

    if point_x_2d is None or point_y_2d is None:
        return None, None

    vector_x = point_x_2d - center_2d
    vector_y = point_y_2d - center_2d

    length_x = vector_x.length
    length_y = vector_y.length

    if length_x <= 1e-6 or length_y <= 1e-6:
        return None, None

    # Preserve the projected ellipse shape while keeping a fixed screen size.
    maximum_length = max(length_x, length_y)

    basis_x_2d = (
        vector_x.normalized()
        * pixel_radius
        * (length_x / maximum_length)
    )
    basis_y_2d = (
        vector_y.normalized()
        * pixel_radius
        * (length_y / maximum_length)
    )

    return basis_x_2d, basis_y_2d


def _project_axis_dir_2d(context, center_3d, axis_vector):
    """Project a 3D axis into a normalized screen-space direction."""
    center_2d = view3d_utils.location_3d_to_region_2d(
        context.region,
        context.region_data,
        center_3d,
    )
    tip_2d = view3d_utils.location_3d_to_region_2d(
        context.region,
        context.region_data,
        center_3d
        + axis_vector.normalized() * ROTATE_CONSTRAINT_AXIS_SAMPLE,
    )

    if center_2d is None or tip_2d is None:
        return None

    direction_2d = tip_2d - center_2d

    if direction_2d.length <= 1e-6:
        return None

    return direction_2d.normalized()


def _closest_axis_to_mouse(
    mouse_2d,
    center_2d,
    axis_directions_2d,
    threshold_pixels,
):
    """
    Return the projected axis nearest to the mouse within the threshold.
    """
    if (
        mouse_2d is None
        or center_2d is None
        or not axis_directions_2d
    ):
        return None

    relative_mouse = mouse_2d - center_2d

    closest_axis = None
    closest_distance = float("inf")

    for axis in ("X", "Y", "Z"):
        direction = axis_directions_2d.get(axis)

        if direction is None:
            continue

        # Perpendicular distance to the infinite axis line.
        distance = abs(
            relative_mouse.x * direction.y
            - relative_mouse.y * direction.x
        )

        if distance < closest_distance:
            closest_distance = distance
            closest_axis = axis

    if closest_distance <= threshold_pixels:
        return closest_axis

    return None


# ── Rotation guide drawing ───────────────────────────────────────────────────

def _draw_shortcut_axis_line(operator):
    """
    Draw rotation constraint lines when the gizmo system is unavailable.
    """
    context = bpy.context

    gizmo_draws_axis_lines = (
        viewport_allows_gizmo(context)
        and (
            location_gizmo_enabled(context)
            or rotation_gizmo_enabled(context)
        )
    )

    if gizmo_draws_axis_lines:
        return

    if _ROTATE_MMB_HELD:
        axes_to_draw = ("X", "Y", "Z")
    elif operator.axis in {"X", "Y", "Z"}:
        axes_to_draw = (operator.axis,)
    else:
        return

    center_2d = view3d_utils.location_3d_to_region_2d(
        context.region,
        context.region_data,
        operator._start_loc,
    )

    if center_2d is None:
        return

    half_length_pixels = float(
        max(context.region.width, context.region.height) * 2.0
    )

    scaled_line_width = (
        ROTATE_CONSTRAINT_LINE_WIDTH
        * context.preferences.system.pixel_size
    )

    axis_colors = get_theme_gizmo_colors(context)
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')

    gpu.state.blend_set('ALPHA')

    shader.bind()
    shader.uniform_float(
        "viewportSize",
        gpu.state.viewport_get()[2:],
    )
    shader.uniform_float("lineWidth", scaled_line_width)

    for axis in axes_to_draw:
        axis_index = AXIS_INDEX[axis]
        world_axis = (
            operator._get_active_orient()
            .col[axis_index]
            .to_3d()
            .normalized()
        )

        direction_2d = _project_axis_dir_2d(
            context,
            operator._start_loc,
            world_axis,
        )

        if direction_2d is None:
            continue

        alpha = (
            1.0
            if axis == operator.axis
            else ROTATE_MMB_AXIS_LINE_DIM_ALPHA
        )

        axis_color = axis_highlight_color(axis_colors[axis])
        color = (
            axis_color[0],
            axis_color[1],
            axis_color[2],
            alpha,
        )

        line_start = Vector((
            center_2d.x
            - direction_2d.x * half_length_pixels,
            center_2d.y
            - direction_2d.y * half_length_pixels,
        ))
        line_end = Vector((
            center_2d.x
            + direction_2d.x * half_length_pixels,
            center_2d.y
            + direction_2d.y * half_length_pixels,
        ))

        batch = batch_for_shader(
            shader,
            'LINES',
            {"pos": [line_start, line_end]},
        )

        shader.uniform_float("color", color)
        batch.draw(shader)

    gpu.state.blend_set('NONE')


def _rotate_guide_draw_op(operator):
    """Draw the screen-space guide for the active rotation modal."""
    center = operator._guide_center_2d
    mouse = operator._guide_mouse_2d

    if center is None or mouse is None:
        return

    # Draw the constraint line first so the dashed guide remains on top.
    _draw_shortcut_axis_line(operator)

    shadow_start = center + ROTATE_GUIDE_SHADOW_OFFSET
    shadow_end = mouse + ROTATE_GUIDE_SHADOW_OFFSET

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
    """Preferences for the 3D Cursor Transform add-on."""

    bl_idname = __name__

    align_added_snapped_to_cursor_rotation: bpy.props.BoolProperty(
        name="Match 3D Cursor Rotation",
        description=(
            "Objects added at or snapped to the 3D Cursor "
            "will also match its rotation"
        ),
        default=False,
        update=update_cursor_align_preference,
    )

    def draw(self, _context):
        layout = self.layout
        layout.prop(
            self,
            "align_added_snapped_to_cursor_rotation",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Rotation Operators
# ─────────────────────────────────────────────────────────────────────────────

class CURSORTRANSFORM_OT_rotate_modal(bpy.types.Operator):
    """Rotate the 3D Cursor around a frozen axis by dragging."""

    bl_idname = "cursortransform.rotate_modal"
    bl_label = "Cursor Rotate"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    axis: bpy.props.StringProperty(default="Z")

    def invoke(self, context, event):
        """Initialize constrained cursor rotation."""
        cursor = context.scene.cursor

        self._start_loc = cursor.matrix.translation.copy()

        rotation_state = cache_cursor_rotation_state(cursor)
        self._rot_mode = rotation_state["rot_mode"]
        self._start_rot = rotation_state["start_rot"]
        self._start_quat = rotation_state["start_quat"]
        self._start_euler_compat = rotation_state["start_euler_compat"]

        # Freeze the transform bases for the duration of the modal operation.
        self._start_orient = build_orient_matrix(context).copy()
        self._start_orient_alternate = (
            build_alternate_orient_matrix(context).copy()
        )
        self._using_alternate_orient = False
        self._start_view = get_view_rot_matrix(context).copy()

        global _ROTATE_ACTIVE_ORIENT
        global _ROTATE_ACTIVE_VIEW

        _ROTATE_ACTIVE_ORIENT = self._start_orient.copy()
        _ROTATE_ACTIVE_VIEW = self._start_view.copy()

        self._guide_center_2d = view3d_utils.location_3d_to_region_2d(
            context.region,
            context.region_data,
            self._start_loc,
        )
        self._guide_mouse_2d = Vector((
            event.mouse_region_x,
            event.mouse_region_y,
        ))
        self._guide_start_mouse_2d = self._guide_mouse_2d.copy()

        gizmo_size = max(
            context.preferences.view.gizmo_size,
            1,
        )

        if self.axis == "VIEW":
            ring_matrix = self._start_view.copy()
            pixel_radius = (
                gizmo_size
                * ROTATE_VIEW_RING_PIXEL_RADIUS
            )
        else:
            ring_matrix = (
                self._get_active_orient()
                @ AXIS_ROT[self.axis]
            )
            pixel_radius = (
                gizmo_size
                * ROTATE_RING_PIXEL_RADIUS
            )

        (
            self._guide_basis_x_2d,
            self._guide_basis_y_2d,
        ) = _build_screen_space_ring_basis(
            context,
            self._guide_center_2d,
            self._start_loc,
            ring_matrix,
            pixel_radius,
        )

        self._guide_start_angle = 0.0
        self._guide_total_angle = 0.0

        initial_angle = _ellipse_angle_from_mouse(
            self._guide_center_2d,
            self._guide_start_mouse_2d,
            self._guide_basis_x_2d,
            self._guide_basis_y_2d,
        )

        if initial_angle is not None:
            self._guide_start_angle = initial_angle

        self._guide_last_mouse_angle = self._guide_start_angle

        global _ROTATE_GUIDE_START_ANGLE
        global _ROTATE_GUIDE_TOTAL_ANGLE

        _ROTATE_GUIDE_START_ANGLE = self._guide_start_angle
        _ROTATE_GUIDE_TOTAL_ANGLE = 0.0

        self._guide_handler = (
            bpy.types.SpaceView3D.draw_handler_add(
                _rotate_guide_draw_op,
                (self,),
                'WINDOW',
                'POST_PIXEL',
            )
        )

        context.workspace.status_text_set(
            draw_status_rotate_axis
        )
        context.window.cursor_modal_set('MOVE_X')

        window_manager = context.window_manager
        window_manager.cursortransform_active_rotate_axis = self.axis
        window_manager.modal_handler_add(self)

        self._numeric_input = ""
        self._numeric_active = False

        self._mmb_held = False
        self._mmb_axis_dirs_2d = None

        return {'RUNNING_MODAL'}

    def _remove_guide_handler(self):
        """Remove the guide handler and clear its cached state."""
        if getattr(self, "_guide_handler", None) is not None:
            bpy.types.SpaceView3D.draw_handler_remove(
                self._guide_handler,
                'WINDOW',
            )
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

    def _get_active_orient(self):
        """Return the currently active constrained-rotation basis."""
        if self._using_alternate_orient:
            return self._start_orient_alternate

        return self._start_orient

    def _get_frozen_axis_vector(self):
        """Return the frozen world-space rotation axis."""
        if self.axis == "VIEW":
            return (
                self._start_view
                @ Vector((0.0, 0.0, 1.0))
            ).normalized()

        axis_index = AXIS_INDEX[self.axis]

        return (
            self._get_active_orient()
            .col[axis_index]
            .to_3d()
            .normalized()
        )

    def _update_header_text(self, context, angle):
        """Update the rotation value shown in the viewport header."""
        degrees = math.degrees(angle)

        if self.axis == "VIEW":
            context.area.header_text_set(
                f"Rotation: {degrees:.2f}\u00b0"
            )
            return

        if self._using_alternate_orient:
            orientation_label = (
                alternate_orient_label(context).lower()
            )
        else:
            orientation_label = (
                get_orient_type(context).lower()
            )

        context.area.header_text_set(
            f"Rotation: {degrees:.2f}\u00b0 "
            f"along {orientation_label} {self.axis}"
        )

    def _switch_axis_constraint(
        self,
        context,
        event,
        new_axis,
        use_alternate_orient=False,
    ):
        """
        Switch the active rotation constraint without interrupting the modal.
        """
        if new_axis not in {"X", "Y", "Z", "VIEW"}:
            return

        if (
            self.axis == new_axis
            and self._using_alternate_orient == use_alternate_orient
        ):
            return

        cursor = context.scene.cursor

        # Continue from the current cursor rotation without jumping.
        self._start_quat = get_cursor_quaternion(cursor)
        self._start_euler_compat = cursor.rotation_euler.copy()

        self.axis = new_axis
        self._using_alternate_orient = use_alternate_orient

        global _ROTATE_ACTIVE_ORIENT
        _ROTATE_ACTIVE_ORIENT = self._get_active_orient().copy()

        self._guide_total_angle = 0.0

        gizmo_size = max(
            context.preferences.view.gizmo_size,
            1,
        )

        if self.axis == "VIEW":
            ring_matrix = self._start_view.copy()
            pixel_radius = (
                gizmo_size
                * ROTATE_VIEW_RING_PIXEL_RADIUS
            )
        else:
            ring_matrix = (
                self._get_active_orient()
                @ AXIS_ROT[self.axis]
            )
            pixel_radius = (
                gizmo_size
                * ROTATE_RING_PIXEL_RADIUS
            )

        (
            self._guide_basis_x_2d,
            self._guide_basis_y_2d,
        ) = _build_screen_space_ring_basis(
            context,
            self._guide_center_2d,
            self._start_loc,
            ring_matrix,
            pixel_radius,
        )

        current_mouse = Vector((
            event.mouse_region_x,
            event.mouse_region_y,
        ))
        self._guide_mouse_2d = current_mouse

        mouse_angle = _ellipse_angle_from_mouse(
            self._guide_center_2d,
            current_mouse,
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

        context.window_manager.cursortransform_active_rotate_axis = (
            self.axis
        )

        self._update_header_text(context, 0.0)
        tag_viewport_redraw(context)

    def _advance_axis_cycle(self, context, event, axis):
        """
        Advance the active axis through primary, alternate, and View modes.
        """
        if (
            self.axis == axis
            and not self._using_alternate_orient
        ):
            self._switch_axis_constraint(
                context,
                event,
                axis,
                use_alternate_orient=True,
            )
        elif (
            self.axis == axis
            and self._using_alternate_orient
        ):
            self._switch_axis_constraint(
                context,
                event,
                "VIEW",
            )
        else:
            self._switch_axis_constraint(
                context,
                event,
                axis,
            )

    def _clear_constraints(self, context, event):
        """Clear an axis constraint and return to View rotation."""
        if self.axis not in {"X", "Y", "Z"}:
            return

        self._switch_axis_constraint(
            context,
            event,
            "VIEW",
            use_alternate_orient=False,
        )

    def _swap_to_trackball(self, context):
        """Switch from constrained rotation to trackball rotation."""
        global _ROTATE_PREVIOUS_AXIS

        previous_axis = self.axis

        self._remove_guide_handler()
        cleanup_rotation_modal(context)

        # Restore the value cleared by the normal modal cleanup path.
        _ROTATE_PREVIOUS_AXIS = previous_axis

        bpy.ops.cursortransform.rotate_free_modal(
            'INVOKE_DEFAULT'
        )

    def _enter_mmb_pickup(self, context):
        """Begin screen-space axis selection with the middle mouse button."""
        global _ROTATE_MMB_HELD

        self._mmb_held = True
        self._mmb_axis_dirs_2d = {}

        for axis in ("X", "Y", "Z"):
            axis_index = AXIS_INDEX[axis]
            world_axis = (
                self._get_active_orient()
                .col[axis_index]
                .to_3d()
                .normalized()
            )

            self._mmb_axis_dirs_2d[axis] = (
                _project_axis_dir_2d(
                    context,
                    self._start_loc,
                    world_axis,
                )
            )

        _ROTATE_MMB_HELD = True
        tag_viewport_redraw(context)

    def _maybe_switch_axis_by_proximity(self, context, event):
        """Switch to the projected axis nearest to the mouse."""
        mouse_2d = Vector((
            event.mouse_region_x,
            event.mouse_region_y,
        ))
        threshold_pixels = (
            ROTATE_MMB_PROXIMITY_THRESHOLD_PX
            * context.preferences.system.pixel_size
        )

        new_axis = _closest_axis_to_mouse(
            mouse_2d,
            self._guide_center_2d,
            self._mmb_axis_dirs_2d,
            threshold_pixels,
        )

        if new_axis is not None and new_axis != self.axis:
            # Preserve the current primary or alternate orientation state.
            self._switch_axis_constraint(
                context,
                event,
                new_axis,
                use_alternate_orient=(
                    self._using_alternate_orient
                ),
            )
            return True

        return False

    def _exit_mmb_pickup(self, context):
        """End middle-mouse axis selection."""
        global _ROTATE_MMB_HELD

        self._mmb_held = False
        self._mmb_axis_dirs_2d = None
        _ROTATE_MMB_HELD = False

        tag_viewport_redraw(context)

    def _apply_rotation(self, context, angle):
        """Apply rotation around the frozen axis."""
        cursor = context.scene.cursor
        axis_vector = self._get_frozen_axis_vector()

        delta_quaternion = Quaternion(
            axis_vector,
            angle,
        )
        new_quaternion = (
            delta_quaternion
            @ self._start_quat
        )

        set_cursor_from_quaternion(
            cursor,
            new_quaternion,
            self._start_euler_compat,
        )

    def modal(self, context, event):
        """Handle constrained cursor rotation."""
        global _ROTATE_GUIDE_TOTAL_ANGLE
        global _ROTATE_GUIDE_CTRL_PRESSED

        _ROTATE_GUIDE_CTRL_PRESSED = event.ctrl

        if event.value == 'PRESS':
            key = event.type

            (
                self._numeric_input,
                self._numeric_active,
                confirm,
                consume,
            ) = handle_numeric_key(
                key,
                self._numeric_input,
                self._numeric_active,
            )

            if confirm:
                self._remove_guide_handler()
                cleanup_rotation_modal(context)
                return {'FINISHED'}

            if key == 'G' and not event.is_repeat:
                self._remove_guide_handler()
                switch_native_rotate_to_translate(
                    context,
                    (
                        self.axis
                        if self.axis in {"X", "Y", "Z"}
                        else None
                    ),
                )
                return {'FINISHED'}

            if (
                key in {"X", "Y", "Z"}
                and not event.is_repeat
            ):
                self._advance_axis_cycle(
                    context,
                    event,
                    key,
                )
                return {'RUNNING_MODAL'}

            if key == 'C' and not event.is_repeat:
                self._clear_constraints(
                    context,
                    event,
                )
                return {'RUNNING_MODAL'}

            if key == 'R' and not event.is_repeat:
                self._swap_to_trackball(context)
                return {'FINISHED'}

            if self._numeric_active:
                angle = math.radians(
                    parse_numeric_input(
                        self._numeric_input
                    )
                )
                _ROTATE_GUIDE_TOTAL_ANGLE = angle

                self._update_header_text(
                    context,
                    angle,
                )

                self._apply_rotation(
                    context,
                    angle,
                )
                tag_viewport_redraw(context)
                return {'RUNNING_MODAL'}

            if consume:
                return {'RUNNING_MODAL'}

        if event.type == 'MIDDLEMOUSE':
            if event.value == 'PRESS':
                if not self._numeric_active:
                    self._enter_mmb_pickup(context)

                return {'RUNNING_MODAL'}

            if (
                event.value == 'RELEASE'
                and self._mmb_held
            ):
                self._exit_mmb_pickup(context)
                return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            if self._numeric_active:
                return {'RUNNING_MODAL'}

            if self._mmb_held:
                switched_axis = (
                    self._maybe_switch_axis_by_proximity(
                        context,
                        event,
                    )
                )

                if switched_axis:
                    self._guide_mouse_2d = Vector((
                        event.mouse_region_x,
                        event.mouse_region_y,
                    ))
                    return {'RUNNING_MODAL'}

            current_mouse = Vector((
                event.mouse_region_x,
                event.mouse_region_y,
            ))
            self._guide_mouse_2d = current_mouse

            mouse_angle = _ellipse_angle_from_mouse(
                self._guide_center_2d,
                current_mouse,
                self._guide_basis_x_2d,
                self._guide_basis_y_2d,
            )

            if mouse_angle is not None:
                angle_delta = _wrap_pi(
                    mouse_angle
                    - self._guide_last_mouse_angle
                )

                if event.shift:
                    angle_delta *= 0.1

                self._guide_total_angle += angle_delta
                self._guide_last_mouse_angle = mouse_angle

            angle = self._guide_total_angle

            if event.ctrl:
                angle = (
                    round(angle / ROTATE_SNAP_STEP)
                    * ROTATE_SNAP_STEP
                )

            _ROTATE_GUIDE_TOTAL_ANGLE = angle

            self._update_header_text(
                context,
                angle,
            )
            self._apply_rotation(
                context,
                angle,
            )

            tag_viewport_redraw(context)
            return {'RUNNING_MODAL'}

        if (
            event.type == 'LEFTMOUSE'
            and event.value == 'RELEASE'
        ):
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
    """Freely rotate the 3D Cursor using a virtual trackball."""

    bl_idname = "cursortransform.rotate_free_modal"
    bl_label = "Cursor Rotate Free"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    def invoke(self, context, event):
        """Initialize the free-rotation modal state."""
        cursor = context.scene.cursor
        window_manager = context.window_manager

        rotation_state = cache_cursor_rotation_state(cursor)
        self._rot_mode = rotation_state["rot_mode"]
        self._start_rot = rotation_state["start_rot"]
        self._start_quat = rotation_state["start_quat"]
        self._start_euler_compat = rotation_state["start_euler_compat"]

        self._start_loc = cursor.matrix.translation.copy()
        self._start_view = get_view_rot_matrix(context).copy()

        center_2d = view3d_utils.location_3d_to_region_2d(
            context.region,
            context.region_data,
            self._start_loc,
        )

        if center_2d is None:
            return {'CANCELLED'}

        gizmo_size = max(context.preferences.view.gizmo_size, 1)
        ring_radius_pixels = (
            gizmo_size
            * ROTATE_VIEW_RING_PIXEL_RADIUS
        )

        self._arcball_center_2d = center_2d
        self._arcball_radius_px = (
            ring_radius_pixels
            * FREE_ROTATE_DISC_SCALE_FACTOR
        )

        self._start_mouse_2d = Vector((
            event.mouse_region_x,
            event.mouse_region_y,
        ))
        self._start_ball_vec = _map_to_arcball(
            self._arcball_center_2d,
            self._start_mouse_2d,
            self._arcball_radius_px,
        )

        if self._start_ball_vec is None:
            return {'CANCELLED'}

        # Freeze the view basis for the duration of the modal operation.
        global _ROTATE_ACTIVE_VIEW
        _ROTATE_ACTIVE_VIEW = self._start_view.copy()

        window_manager.cursortransform_active_rotate_axis = "FREE"
        context.window.cursor_modal_set('SCROLL_XY')
        context.workspace.status_text_set(draw_status_rotate_free)
        window_manager.modal_handler_add(self)

        self._numeric_input = ""
        self._numeric_active = False

        return {'RUNNING_MODAL'}

    def _swap_to_view_rotation(self, context):
        """Return from trackball rotation to the previous rotation mode."""
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
            return

        bpy.ops.cursortransform.rotate_view('INVOKE_DEFAULT')

    def _apply_arcball_rotation(self, context, ball_position, snap):
        """Apply the current trackball rotation."""
        view_rotation = self._start_view.to_3x3()

        start_vector = (
            view_rotation
            @ self._start_ball_vec
        ).normalized()
        current_vector = (
            view_rotation
            @ ball_position
        ).normalized()

        delta_quaternion = start_vector.rotation_difference(
            current_vector
        )

        if snap:
            delta_euler = delta_quaternion.to_euler('XYZ')
            delta_euler.x = (
                round(delta_euler.x / ROTATE_SNAP_STEP)
                * ROTATE_SNAP_STEP
            )
            delta_euler.y = (
                round(delta_euler.y / ROTATE_SNAP_STEP)
                * ROTATE_SNAP_STEP
            )
            delta_euler.z = (
                round(delta_euler.z / ROTATE_SNAP_STEP)
                * ROTATE_SNAP_STEP
            )
            delta_quaternion = delta_euler.to_quaternion()

        new_quaternion = delta_quaternion @ self._start_quat

        set_cursor_from_quaternion(
            context.scene.cursor,
            new_quaternion,
            self._start_euler_compat,
        )

        displayed_euler = delta_quaternion.to_euler('XYZ')
        horizontal_degrees = math.degrees(displayed_euler.x)
        vertical_degrees = math.degrees(displayed_euler.y)

        context.area.header_text_set(
            f"Trackball: "
            f"{horizontal_degrees:.2f}  "
            f"{vertical_degrees:.2f}"
        )

    def modal(self, context, event):
        """Update the trackball rotation and handle modal input."""
        global _ROTATE_ACTIVE_VIEW

        if event.value == 'PRESS':
            key = event.type

            (
                self._numeric_input,
                self._numeric_active,
                confirm,
                consume,
            ) = handle_numeric_key(
                key,
                self._numeric_input,
                self._numeric_active,
            )

            if confirm:
                cleanup_rotation_modal(context)
                _ROTATE_ACTIVE_VIEW = None
                return {'FINISHED'}

            if key == 'G' and not event.is_repeat:
                _ROTATE_ACTIVE_VIEW = None
                switch_native_rotate_to_translate(context)
                return {'FINISHED'}

            if key == 'R' and not event.is_repeat:
                self._swap_to_view_rotation(context)
                return {'FINISHED'}

            if self._numeric_active:
                typed_degrees = parse_numeric_input(
                    self._numeric_input
                )
                angle = math.radians(typed_degrees)

                view_axis = (
                    self._start_view
                    @ Vector((0.0, 0.0, 1.0))
                ).normalized()

                delta_quaternion = Quaternion(view_axis, angle)
                new_quaternion = (
                    delta_quaternion
                    @ self._start_quat
                )

                set_cursor_from_quaternion(
                    context.scene.cursor,
                    new_quaternion,
                    self._start_euler_compat,
                )

                context.area.header_text_set(
                    f"Trackball: [{self._numeric_input}] = "
                    f"{typed_degrees:.2f}\u00b0"
                )

                tag_viewport_redraw(context)
                return {'RUNNING_MODAL'}

            if consume:
                return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            if self._numeric_active:
                return {'RUNNING_MODAL'}

            current_mouse = Vector((
                event.mouse_region_x,
                event.mouse_region_y,
            ))

            precision_factor = 0.1 if event.shift else 1.0
            mouse_input = (
                self._start_mouse_2d
                + (
                    current_mouse
                    - self._start_mouse_2d
                ) * precision_factor
            )

            ball_position = _map_to_arcball(
                self._arcball_center_2d,
                mouse_input,
                self._arcball_radius_px,
            )

            if ball_position is not None:
                self._apply_arcball_rotation(
                    context,
                    ball_position,
                    snap=event.ctrl,
                )

            tag_viewport_redraw(context)
            return {'RUNNING_MODAL'}

        if (
            event.type == 'LEFTMOUSE'
            and event.value == 'RELEASE'
        ):
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

class CURSORTRANSFORM_OT_clear_transform(bpy.types.Operator):
    """Clear the 3D Cursor location or rotation."""

    bl_idname = "cursortransform.clear_transform"
    bl_label = "Clear 3D Cursor Transform"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(
        items=(
            ('LOCATION', "Location", "Clear the 3D Cursor location"),
            ('ROTATION', "Rotation", "Clear the 3D Cursor rotation"),
        ),
        default='LOCATION',
        options={'HIDDEN'},
    )

    @classmethod
    def poll(cls, context):
        """Run only while the 3D Cursor tool is active."""
        return active_tool_is_cursor(context)

    def execute(self, context):
        cursor = context.scene.cursor

        if self.mode == 'LOCATION':
            cursor.location = (0.0, 0.0, 0.0)
        elif self.mode == 'ROTATION':
            reset_cursor_rotation(cursor)

        tag_viewport_redraw(context)
        return {'FINISHED'}


class CURSORTRANSFORM_OT_translate_modal(bpy.types.Operator):
    """Move the 3D Cursor using a custom keyboard translation modal."""

    bl_idname = "cursortransform.translate_modal"
    bl_label = "Cursor Translate Modal"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    release_confirm: bpy.props.BoolProperty(default=False)
    axis: bpy.props.StringProperty(default="")

    def invoke(self, context, event):
        """Initialize the custom translation modal state."""
        cursor = context.scene.cursor

        if context.scene.tool_settings.use_snap:
            # Native operator combines axis constraints with snapping.
            if self.axis in {"X", "Y", "Z"}:
                bpy.ops.cursortransform.translate(
                    'INVOKE_DEFAULT',
                    axis=self.axis,
                    release_confirm=False,
                )
            else:
                bpy.ops.cursortransform.translate_free(
                    'INVOKE_DEFAULT',
                    release_confirm=False,
                )
            return {'FINISHED'}

        self._initial_loc = cursor.location.copy()
        self._start_loc = self._initial_loc.copy()
        self._start_mouse = None
        self._waiting_for_first_mousemove = True

        self._axis = ""
        self._plane_exclude_axis = ""
        self._cycle_state = 0
        self._using_alternate_orient = False

        self._mmb_held = False
        self._mmb_axis_dirs_2d = None

        self._precision_active = False
        self._precision_start_mouse = None
        self._precision_start_loc = None

        self._start_orient = build_orient_matrix(context).copy()
        self._start_orient_alternate = (
            build_alternate_orient_matrix(context).copy()
        )

        window_manager = context.window_manager

        global _TRANSLATE_GHOST_START_LOC
        global _TRANSLATE_GHOST_START_ORIENT

        _TRANSLATE_GHOST_START_LOC = self._initial_loc.copy()
        _TRANSLATE_GHOST_START_ORIENT = None

        if self.axis in {"X", "Y", "Z"}:
            # Started from a gizmo drag with an axis already chosen.
            # Use the click position as the mouse baseline immediately
            # instead of waiting for the first move, so the cursor
            # follows the drag from the initial click like a native
            # gizmo would.
            self._start_mouse = Vector((
                event.mouse_region_x,
                event.mouse_region_y,
            ))
            self._waiting_for_first_mousemove = False

            self._axis = self.axis
            self._cycle_state = 1

            window_manager.cursortransform_active_translate_axis = (
                self._axis
            )
            _TRANSLATE_GHOST_START_ORIENT = (
                self._get_active_orient().copy()
            )
        else:
            window_manager.cursortransform_active_translate_axis = ""

        self._axis_line_handler = (
            bpy.types.SpaceView3D.draw_handler_add(
                _draw_translate_axis_line_op,
                (self,),
                'WINDOW',
                'POST_PIXEL',
            )
        )

        context.window.cursor_modal_set('SCROLL_XY')
        context.workspace.status_text_set(draw_status_translate)
        window_manager.modal_handler_add(self)

        return {'RUNNING_MODAL'}

    def _remove_axis_line_handler(self):
        """Remove the translation-axis draw handler."""
        if getattr(self, "_axis_line_handler", None) is None:
            return

        bpy.types.SpaceView3D.draw_handler_remove(
            self._axis_line_handler,
            'WINDOW',
        )
        self._axis_line_handler = None

    def _get_active_orient(self):
        """Return the currently active translation orientation."""
        if self._using_alternate_orient:
            return self._start_orient_alternate

        return self._start_orient

    def _get_axis_vector(self):
        """Return the active translation axis in world space."""
        if self._axis not in {"X", "Y", "Z"}:
            return None

        axis_index = AXIS_INDEX[self._axis]

        return (
            self._get_active_orient()
            .col[axis_index]
            .to_3d()
            .normalized()
        )

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
            orientation = self._get_active_orient()

            plane_axes = [
                axis
                for axis in ("X", "Y", "Z")
                if axis != self._plane_exclude_axis
            ]

            first_axis = plane_axes[0]
            second_axis = plane_axes[1]

            first_vector = (
                orientation
                .col[AXIS_INDEX[first_axis]]
                .to_3d()
                .normalized()
            )
            second_vector = (
                orientation
                .col[AXIS_INDEX[second_axis]]
                .to_3d()
                .normalized()
            )

            first_amount = delta.dot(first_vector)
            second_amount = delta.dot(second_vector)
            total_distance = delta.length

            context.area.header_text_set(
                f"D:  {self._format_distance(first_amount)}   "
                f"D: {self._format_distance(second_amount)} "
                f"({self._format_distance(total_distance)}) "
                f"locking {orient_label} "
                f"{self._plane_exclude_axis}"
            )
            return

        if self._axis in {"X", "Y", "Z"}:
            axis_vector = self._get_axis_vector()

            if axis_vector is None:
                return

            amount = delta.dot(axis_vector)
            orient_label = self._get_orient_label(context)

            context.area.header_text_set(
                f"D:  {self._format_distance(amount)} "
                f"({self._format_distance(abs(amount))}) "
                f"along {orient_label} {self._axis}"
            )
            return

        context.area.header_text_set(
            f"Dx: {self._format_distance(delta.x)}   "
            f"Dy:  {self._format_distance(delta.y)}   "
            f"Dz: {self._format_distance(delta.z)} "
            f"({self._format_distance(delta.length)})"
        )

    def _update_status_bar(self, context):
        if context.workspace is not None:
            context.workspace.status_text_set(draw_status_translate)

    def _ensure_start_mouse(self, event):
        """
        Establish a mouse baseline when a constraint is selected before
        the first mouse-move event.
        """
        if self._start_mouse is not None:
            return

        self._start_mouse = Vector((
            event.mouse_region_x,
            event.mouse_region_y,
        ))
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

        context.window_manager.cursortransform_active_translate_axis = (
            self._axis
        )

        if self._axis in {"X", "Y", "Z"}:
            _TRANSLATE_GHOST_START_ORIENT = (
                self._get_active_orient().copy()
            )
        else:
            _TRANSLATE_GHOST_START_ORIENT = None

        context.scene.cursor.location = self._mouse_to_location(
            context,
            event,
        )

        self._update_header_text(context)
        self._update_status_bar(context)
        tag_viewport_redraw(context)

    def _set_plane_cycle(self, context, event, excluded_axis):
        global _TRANSLATE_GHOST_START_ORIENT

        self._ensure_start_mouse(event)

        if self._plane_exclude_axis != excluded_axis:
            self._axis = ""
            self._plane_exclude_axis = excluded_axis
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
                axis
                for axis in ("X", "Y", "Z")
                if axis != self._plane_exclude_axis
            )

            context.window_manager.cursortransform_active_translate_axis = (
                plane
            )
            _TRANSLATE_GHOST_START_ORIENT = (
                self._get_active_orient().copy()
            )
        else:
            context.window_manager.cursortransform_active_translate_axis = ""
            _TRANSLATE_GHOST_START_ORIENT = None

        context.scene.cursor.location = self._mouse_to_location(
            context,
            event,
        )

        self._update_header_text(context)
        self._update_status_bar(context)
        tag_viewport_redraw(context)

    def _clear_constraints(self, context, event):
        """Clear the active axis or plane constraint."""
        global _TRANSLATE_GHOST_START_ORIENT

        self._ensure_start_mouse(event)

        self._axis = ""
        self._plane_exclude_axis = ""
        self._cycle_state = 0
        self._using_alternate_orient = False

        context.window_manager.cursortransform_active_translate_axis = ""
        _TRANSLATE_GHOST_START_ORIENT = None

        context.scene.cursor.location = self._mouse_to_location(
            context,
            event,
        )

        self._update_header_text(context)
        self._update_status_bar(context)
        tag_viewport_redraw(context)

    def _switch_to_rotate(self, context):
        """Finish translation and start cursor rotation."""
        axis = (
            self._axis
            if self._axis in {"X", "Y", "Z"}
            else None
        )

        self._finish(context)

        if axis is not None:
            bpy.ops.cursortransform.rotate_modal(
                'INVOKE_DEFAULT',
                axis=axis,
            )
            return

        bpy.ops.cursortransform.rotate_view('INVOKE_DEFAULT')

    def _handoff_to_native_translate(self, context):
        """Continue translation using Blender's native transform operator."""
        axis = (
            self._axis
            if self._axis in {"X", "Y", "Z"}
            else None
        )

        plane = None

        if self._plane_exclude_axis in {"X", "Y", "Z"}:
            plane = "".join(
                axis_name
                for axis_name in ("X", "Y", "Z")
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
        """Begin automatic axis selection with the middle mouse button."""
        self._mmb_held = True
        self._mmb_axis_dirs_2d = {}

        for axis in ("X", "Y", "Z"):
            axis_index = AXIS_INDEX[axis]
            axis_vector = (
                self._get_active_orient()
                .col[axis_index]
                .to_3d()
                .normalized()
            )

            self._mmb_axis_dirs_2d[axis] = _project_axis_dir_2d(
                context,
                self._start_loc,
                axis_vector,
            )

        tag_viewport_redraw(context)

    def _exit_mmb_pickup(self, context):
        """End automatic axis selection."""
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
        _TRANSLATE_GHOST_START_ORIENT = (
            self._get_active_orient().copy()
        )

        context.scene.cursor.location = self._mouse_to_location(
            context,
            event,
        )

        self._update_header_text(context)
        self._update_status_bar(context)
        tag_viewport_redraw(context)

    def _maybe_switch_axis_by_proximity(self, context, event):
        mouse_2d = Vector((
            event.mouse_region_x,
            event.mouse_region_y,
        ))

        threshold_pixels = (
            ROTATE_MMB_PROXIMITY_THRESHOLD_PX
            * context.preferences.system.pixel_size
        )

        center_2d = view3d_utils.location_3d_to_region_2d(
            context.region,
            context.region_data,
            self._start_loc,
        )

        new_axis = _closest_axis_to_mouse(
            mouse_2d,
            center_2d,
            self._mmb_axis_dirs_2d,
            threshold_pixels,
        )

        if new_axis is not None and new_axis != self._axis:
            self._set_axis_from_mmb(
                context,
                event,
                new_axis,
            )

    def _mouse_to_free_location(self, context, event):
        region = context.region
        region_data = context.region_data
        base_location = self._input_start_loc()

        start_2d = view3d_utils.location_3d_to_region_2d(
            region,
            region_data,
            base_location,
        )

        if start_2d is None:
            return base_location.copy()

        target_2d = start_2d + self._mouse_delta_2d(event)

        ray_origin = view3d_utils.region_2d_to_origin_3d(
            region,
            region_data,
            target_2d,
        )
        ray_direction = view3d_utils.region_2d_to_vector_3d(
            region,
            region_data,
            target_2d,
        )

        view_normal = (
            region_data.view_rotation
            @ Vector((0.0, 0.0, -1.0))
        )
        denominator = ray_direction.dot(view_normal)

        if abs(denominator) < 1e-8:
            return base_location.copy()

        distance = (
            base_location - ray_origin
        ).dot(view_normal) / denominator

        return ray_origin + ray_direction * distance

    def _mouse_delta_2d(self, event):
        current_mouse = Vector((
            event.mouse_region_x,
            event.mouse_region_y,
        ))
        mouse_delta = current_mouse - self._input_start_mouse()

        if self._precision_active:
            mouse_delta *= 0.1

        return mouse_delta

    def _project_world_vector_to_2d(self, context, world_vector):
        base_location = self._input_start_loc()

        start_2d = view3d_utils.location_3d_to_region_2d(
            context.region,
            context.region_data,
            base_location,
        )
        end_2d = view3d_utils.location_3d_to_region_2d(
            context.region,
            context.region_data,
            base_location + world_vector,
        )

        if start_2d is None or end_2d is None:
            return None

        projected_vector = end_2d - start_2d

        if projected_vector.length <= 1e-6:
            return None

        return projected_vector

    def _update_precision_state(self, context, event):
        current_mouse = Vector((
            event.mouse_region_x,
            event.mouse_region_y,
        ))

        if event.shift and not self._precision_active:
            self._precision_active = True
            self._precision_start_mouse = current_mouse
            self._precision_start_loc = (
                context.scene.cursor.location.copy()
            )
            return

        if not event.shift and self._precision_active:
            self._precision_active = False

            # Continue normal movement from the current precise position.
            self._start_mouse = current_mouse
            self._start_loc = context.scene.cursor.location.copy()

            self._precision_start_mouse = None
            self._precision_start_loc = None

    def _input_start_mouse(self):
        if (
            self._precision_active
            and self._precision_start_mouse is not None
        ):
            return self._precision_start_mouse

        return self._start_mouse

    def _input_start_loc(self):
        if (
            self._precision_active
            and self._precision_start_loc is not None
        ):
            return self._precision_start_loc

        return self._start_loc

    def _mouse_to_axis_location(self, context, event):
        axis_vector = self._get_axis_vector()

        if axis_vector is None:
            return self._mouse_to_free_location(context, event)

        projected_axis = self._project_world_vector_to_2d(
            context,
            axis_vector,
        )

        if projected_axis is None:
            return self._input_start_loc().copy()

        axis_direction_2d = projected_axis.normalized()
        mouse_delta = self._mouse_delta_2d(event)

        amount = (
            mouse_delta.dot(axis_direction_2d)
            / projected_axis.length
        )

        return self._input_start_loc() + axis_vector * amount

    def _mouse_to_plane_location(self, context, event):
        if self._plane_exclude_axis not in {"X", "Y", "Z"}:
            return self._mouse_to_free_location(context, event)

        plane_axes = [
            axis
            for axis in ("X", "Y", "Z")
            if axis != self._plane_exclude_axis
        ]

        orientation = self._get_active_orient()

        first_vector = (
            orientation
            .col[AXIS_INDEX[plane_axes[0]]]
            .to_3d()
            .normalized()
        )
        second_vector = (
            orientation
            .col[AXIS_INDEX[plane_axes[1]]]
            .to_3d()
            .normalized()
        )

        first_basis_2d = self._project_world_vector_to_2d(
            context,
            first_vector,
        )
        second_basis_2d = self._project_world_vector_to_2d(
            context,
            second_vector,
        )

        if first_basis_2d is None or second_basis_2d is None:
            return self._input_start_loc().copy()

        coefficients = _solve_2d_basis(
            self._mouse_delta_2d(event),
            first_basis_2d,
            second_basis_2d,
        )

        if coefficients is None:
            return self._input_start_loc().copy()

        first_amount, second_amount = coefficients

        return (
            self._input_start_loc()
            + first_vector * first_amount
            + second_vector * second_amount
        )

    def _mouse_to_location(self, context, event):
        if self._plane_exclude_axis in {"X", "Y", "Z"}:
            return self._mouse_to_plane_location(context, event)

        if self._axis in {"X", "Y", "Z"}:
            return self._mouse_to_axis_location(context, event)

        return self._mouse_to_free_location(context, event)

    def _finish(self, context):
        """Clear translation modal state and restore the viewport UI."""
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
        """Update cursor translation and handle modal input."""
        if (
            event.value == 'PRESS'
            and event.type == 'C'
            and not event.is_repeat
        ):
            self._clear_constraints(context, event)
            return {'RUNNING_MODAL'}

        if (
            event.value == 'PRESS'
            and event.type == 'R'
            and not event.is_repeat
        ):
            self._switch_to_rotate(context)
            return {'FINISHED'}

        if (
            event.value == 'PRESS'
            and event.type in {'LEFT_CTRL', 'RIGHT_CTRL'}
        ):
            self._handoff_to_native_translate(context)
            return {'FINISHED'}

        if (
            event.value == 'PRESS'
            and event.type == 'TAB'
            and event.shift
        ):
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

        if (
            event.value == 'PRESS'
            and event.type in {'X', 'Y', 'Z'}
            and not event.is_repeat
        ):
            if event.shift:
                self._set_plane_cycle(
                    context,
                    event,
                    event.type,
                )
            else:
                self._plane_exclude_axis = ""
                self._set_axis_cycle(
                    context,
                    event,
                    event.type,
                )

            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            if self._waiting_for_first_mousemove:
                self._waiting_for_first_mousemove = False
                self._start_mouse = Vector((
                    event.mouse_region_x,
                    event.mouse_region_y,
                ))
                return {'RUNNING_MODAL'}

            self._update_precision_state(context, event)

            if self._mmb_held:
                self._maybe_switch_axis_by_proximity(
                    context,
                    event,
                )

            context.scene.cursor.location = self._mouse_to_location(
                context,
                event,
            )
            self._update_header_text(context)

            tag_viewport_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'}:
            self._finish(context)
            return {'FINISHED'}

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            context.scene.cursor.location = self._initial_loc
            self._finish(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}


class CURSORTRANSFORM_OT_translate(bpy.types.Operator):
    """Move the 3D Cursor along a constrained axis."""

    bl_idname = "cursortransform.translate"
    bl_label = "Cursor Translate"
    bl_options = {'INTERNAL'}

    axis: bpy.props.StringProperty(default="Z")
    release_confirm: bpy.props.BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        """Run only while the 3D Cursor tool is active."""
        return active_tool_is_cursor(context)

    def invoke(self, context, _event):
        """Start Blender's native cursor translation on one axis."""
        global _TRANSLATE_GHOST_START_LOC
        global _TRANSLATE_GHOST_START_ORIENT

        orientation_matrix = build_orient_matrix(context)
        orientation_type = get_orient_type(context)

        context.window_manager.cursortransform_active_translate_axis = (
            self.axis
        )

        _TRANSLATE_GHOST_START_LOC = (
            context.scene.cursor.location.copy()
        )
        _TRANSLATE_GHOST_START_ORIENT = (
            orientation_matrix.copy()
        )

        bpy.ops.transform.translate(
            'INVOKE_DEFAULT',
            cursor_transform=True,
            constraint_axis=AXIS_CONSTRAINT[self.axis],
            orient_type=orientation_type,
            orient_matrix=orientation_matrix.to_3x3(),
            orient_matrix_type=orientation_type,
            release_confirm=self.release_confirm,
        )

        return {'FINISHED'}


class CURSORTRANSFORM_OT_translate_gizmo_start(bpy.types.Operator):
    """Start the custom translation modal from a gizmo click."""

    bl_idname = "cursortransform.translate_gizmo_start"
    bl_label = "Cursor Translate (Gizmo Start)"
    bl_options = {'INTERNAL'}

    axis: bpy.props.StringProperty(default="")

    @classmethod
    def poll(cls, context):
        """Run only while the 3D Cursor tool is active."""
        return active_tool_is_cursor(context)

    def invoke(self, context, _event):
        """Hand off to the custom translation modal and finish."""
        # Returning FINISHED here, rather than the modal's own return
        # value, releases the gizmo's drag-tracking immediately.
        bpy.ops.cursortransform.translate_modal(
            'INVOKE_DEFAULT',
            axis=self.axis,
        )
        return {'FINISHED'}


class CURSORTRANSFORM_OT_translate_free(bpy.types.Operator):
    """Move the 3D Cursor freely in the view plane."""

    bl_idname = "cursortransform.translate_free"
    bl_label = "Cursor Translate Free"
    bl_options = {'INTERNAL'}

    release_confirm: bpy.props.BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        """Run only while the 3D Cursor tool is active."""
        return active_tool_is_cursor(context)

    def invoke(self, context, _event):
        """Start Blender's native free cursor translation."""
        global _TRANSLATE_GHOST_START_LOC
        global _TRANSLATE_GHOST_START_ORIENT

        context.window_manager.cursortransform_active_translate_axis = ""

        _TRANSLATE_GHOST_START_LOC = (
            context.scene.cursor.location.copy()
        )
        _TRANSLATE_GHOST_START_ORIENT = None

        bpy.ops.transform.translate(
            'INVOKE_DEFAULT',
            cursor_transform=True,
            release_confirm=self.release_confirm,
        )

        return {'FINISHED'}


class CURSORTRANSFORM_OT_translate_plane(bpy.types.Operator):
    """Move the 3D Cursor along a constrained plane."""

    bl_idname = "cursortransform.translate_plane"
    bl_label = "Cursor Translate Plane"
    bl_options = {'INTERNAL'}

    plane: bpy.props.StringProperty(default="XY")
    release_confirm: bpy.props.BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        """Run only while the 3D Cursor tool is active."""
        return active_tool_is_cursor(context)

    def invoke(self, context, _event):
        """Start Blender's native cursor translation on a plane."""
        global _TRANSLATE_GHOST_START_LOC
        global _TRANSLATE_GHOST_START_ORIENT

        orientation_matrix = build_orient_matrix(context)
        orientation_type = get_orient_type(context)

        context.window_manager.cursortransform_active_translate_axis = (
            self.plane
        )

        _TRANSLATE_GHOST_START_LOC = (
            context.scene.cursor.location.copy()
        )
        _TRANSLATE_GHOST_START_ORIENT = (
            orientation_matrix.copy()
        )

        bpy.ops.transform.translate(
            'INVOKE_DEFAULT',
            cursor_transform=True,
            constraint_axis=PLANE_CONSTRAINT[self.plane],
            orient_type=orientation_type,
            orient_matrix=orientation_matrix.to_3x3(),
            orient_matrix_type=orientation_type,
            release_confirm=self.release_confirm,
        )

        return {'FINISHED'}


class CURSORTRANSFORM_OT_rotate_x(bpy.types.Operator):
    """Start 3D Cursor rotation around the X axis."""

    bl_idname = "cursortransform.rotate_x"
    bl_label = "Cursor Rotate X"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return active_tool_is_cursor(context)

    def invoke(self, context, _event):
        return bpy.ops.cursortransform.rotate_modal(
            'INVOKE_DEFAULT',
            axis="X",
        )


class CURSORTRANSFORM_OT_rotate_y(bpy.types.Operator):
    """Start 3D Cursor rotation around the Y axis."""

    bl_idname = "cursortransform.rotate_y"
    bl_label = "Cursor Rotate Y"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return active_tool_is_cursor(context)

    def invoke(self, context, _event):
        return bpy.ops.cursortransform.rotate_modal(
            'INVOKE_DEFAULT',
            axis="Y",
        )


class CURSORTRANSFORM_OT_rotate_z(bpy.types.Operator):
    """Start 3D Cursor rotation around the Z axis."""

    bl_idname = "cursortransform.rotate_z"
    bl_label = "Cursor Rotate Z"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return active_tool_is_cursor(context)

    def invoke(self, context, _event):
        return bpy.ops.cursortransform.rotate_modal(
            'INVOKE_DEFAULT',
            axis="Z",
        )


class CURSORTRANSFORM_OT_rotate_view(bpy.types.Operator):
    """Start view-aligned 3D Cursor rotation."""

    bl_idname = "cursortransform.rotate_view"
    bl_label = "Cursor Rotate View"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return active_tool_is_cursor(context)

    def invoke(self, context, _event):
        return bpy.ops.cursortransform.rotate_modal(
            'INVOKE_DEFAULT',
            axis="VIEW",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Gizmo Classes and Group
# ─────────────────────────────────────────────────────────────────────────────

class CURSORTRANSFORM_GT_filled_dot(bpy.types.Gizmo):
    """Filled center marker used by active and ghost gizmos."""

    bl_idname = "CURSORTRANSFORM_GT_filled_dot"

    def setup(self):
        """Create the cached filled-circle shape."""
        if hasattr(self, "_shape"):
            return

        self._shape = self.new_custom_shape(
            'TRIS',
            _build_circle_fan_vertices(
                radius=0.06,
                segments=24,
            ),
        )

    def draw(self, _context):
        self.draw_custom_shape(self._shape)

    def draw_select(self, _context, select_id):
        self.draw_custom_shape(
            self._shape,
            select_id=select_id,
        )


class CURSORTRANSFORM_GT_plane_square(bpy.types.Gizmo):
    """Square handle used for planar translation and ghost previews."""

    bl_idname = "CURSORTRANSFORM_GT_plane_square"

    def setup(self):
        """Create the cached fill and outline shapes."""
        if hasattr(self, "_fill_shape"):
            return

        half_size = 0.5

        fill_vertices = [
            (-half_size, -half_size, 0.0),
            (half_size, -half_size, 0.0),
            (half_size, half_size, 0.0),
            (-half_size, -half_size, 0.0),
            (half_size, half_size, 0.0),
            (-half_size, half_size, 0.0),
        ]

        outline_vertices = [
            (-half_size, -half_size, 0.0),
            (half_size, -half_size, 0.0),
            (half_size, -half_size, 0.0),
            (half_size, half_size, 0.0),
            (half_size, half_size, 0.0),
            (-half_size, half_size, 0.0),
            (-half_size, half_size, 0.0),
            (-half_size, -half_size, 0.0),
        ]

        self._fill_shape = self.new_custom_shape(
            'TRIS',
            fill_vertices,
        )
        self._outline_shape = self.new_custom_shape(
            'LINES',
            outline_vertices,
        )

    def draw(self, _context):
        """Draw the plane handle fill and outline."""
        fill_color = getattr(
            self,
            "fill_color",
            (1.0, 1.0, 1.0),
        )
        outline_color = getattr(
            self,
            "outline_color",
            fill_color,
        )

        fill_alpha = float(
            getattr(self, "fill_alpha", 0.18)
        )
        outline_alpha = float(
            getattr(self, "outline_alpha", 1.0)
        )
        fill_highlight_alpha = float(
            getattr(
                self,
                "fill_alpha_highlight",
                fill_alpha,
            )
        )
        outline_highlight_alpha = float(
            getattr(
                self,
                "outline_alpha_highlight",
                outline_alpha,
            )
        )

        original_color = self.color
        original_alpha = self.alpha

        self.color = fill_color
        self.alpha = (
            fill_highlight_alpha
            if self.is_highlight
            else fill_alpha
        )
        self.draw_custom_shape(self._fill_shape)

        self.color = outline_color
        self.alpha = (
            outline_highlight_alpha
            if self.is_highlight
            else outline_alpha
        )

        gpu.state.blend_set('ALPHA')
        gpu.state.line_width_set(PLANE_LINE_WIDTH)

        self.draw_custom_shape(self._outline_shape)

        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')

        self.color = original_color
        self.alpha = original_alpha

    def draw_select(self, _context, select_id):
        self.draw_custom_shape(
            self._fill_shape,
            select_id=select_id,
        )


class CURSORTRANSFORM_GT_rotate_free_disc(bpy.types.Gizmo):
    """Free-rotation disc used to start trackball cursor rotation."""

    bl_idname = "CURSORTRANSFORM_GT_rotate_free_disc"

    def setup(self):
        """Create the cached free-rotation disc shape."""
        if hasattr(self, "_shape"):
            return

        self._shape = self.new_custom_shape(
            'TRIS',
            _build_circle_fan_vertices(
                radius=1.0,
                segments=48,
            ),
        )

    def draw(self, _context):
        self.draw_custom_shape(self._shape)

    def draw_select(self, _context, select_id):
        self.draw_custom_shape(
            self._shape,
            select_id=select_id,
        )

    def test_select(self, context, location):
        """Return a hit inside the rotation disc, excluding the center dead zone."""
        center_2d = view3d_utils.location_3d_to_region_2d(
            context.region,
            context.region_data,
            self.matrix_basis.translation,
        )

        if center_2d is None:
            return -1

        mouse = Vector(location)
        distance = (mouse - center_2d).length

        gizmo_size = max(
            context.preferences.view.gizmo_size,
            1,
        )

        outer_radius = (
            gizmo_size
            * ROTATE_VIEW_RING_PIXEL_RADIUS
            * FREE_ROTATE_DISC_SCALE_FACTOR
        )

        deadzone_radius = (
            gizmo_size
            * FREE_ROTATE_DISC_CENTER_DEADZONE_FACTOR
        )

        if distance <= deadzone_radius:
            return -1

        if distance <= outer_radius:
            return 0

        return -1


class CURSORTRANSFORM_GT_rotate_sector(bpy.types.Gizmo):
    """Rotation sector overlay for constrained cursor rotation."""

    bl_idname = "CURSORTRANSFORM_GT_rotate_sector"

    def setup(self):
        """Create the cached full-sector shape."""
        if hasattr(self, "_full_sector_shape"):
            return

        self._full_sector_shape = self.new_custom_shape(
            'TRIS',
            _build_sector_fan_vertices(
                0.0,
                math.tau,
                ROTATE_SECTOR_STEPS,
            ),
        )

    def draw(self, _context):
        """Draw the filled rotation sector and its radius markers."""
        start_angle = getattr(self, "start_angle", 0.0)
        total_angle = getattr(self, "total_angle", 0.0)

        start_width = float(getattr(self, "start_width", 1.0))
        end_width = float(getattr(self, "end_width", 1.0))

        direction = 1.0 if total_angle >= 0.0 else -1.0
        absolute_angle = abs(total_angle)

        full_turns = int(absolute_angle // math.tau)
        remaining_angle = (
            absolute_angle
            - (full_turns * math.tau)
        )

        radius_color = getattr(
            self,
            "radius_color",
            (1.0, 1.0, 1.0),
        )
        fill_alpha = float(
            getattr(self, "fill_alpha", 0.25)
        )

        original_color = self.color
        original_alpha = self.alpha

        self.color = (1.0, 1.0, 1.0)
        self.alpha = fill_alpha

        for _ in range(full_turns):
            self.draw_custom_shape(
                self._full_sector_shape
            )

        if remaining_angle > 1e-6:
            end_angle = (
                start_angle
                + direction * remaining_angle
            )

            steps = max(
                12,
                int(
                    ROTATE_SECTOR_STEPS
                    * (remaining_angle / math.tau)
                ),
            )

            partial_shape = self.new_custom_shape(
                'TRIS',
                _build_sector_fan_vertices(
                    start_angle,
                    end_angle,
                    steps,
                ),
            )

            self.draw_custom_shape(partial_shape)

        self.color = radius_color
        self.alpha = 1.0

        start_shape = self.new_custom_shape(
            'TRIS',
            _build_radius_quad_vertices(
                start_angle,
                start_width,
            ),
        )
        self.draw_custom_shape(start_shape)

        end_shape = self.new_custom_shape(
            'TRIS',
            _build_radius_quad_vertices(
                start_angle + total_angle,
                end_width,
            ),
        )
        self.draw_custom_shape(end_shape)

        self.color = original_color
        self.alpha = original_alpha

    def draw_select(self, _context, select_id):
        pass


class CURSORTRANSFORM_GT_axis_line(bpy.types.Gizmo):
    """Full-screen axis line for constrained cursor rotation."""

    bl_idname = "CURSORTRANSFORM_GT_axis_line"

    def draw(self, context):
        """Draw the rotation axis line over the scene."""
        line_width = float(
            getattr(
                self,
                "line_width",
                ROTATE_CONSTRAINT_LINE_WIDTH,
            )
        )
        color = getattr(
            self,
            "axis_color",
            (1.0, 1.0, 1.0, 1.0),
        )

        scaled_line_width = (
            line_width
            * context.preferences.system.pixel_size
        )

        line_extent = 1.0e4
        vertices = [
            (0.0, 0.0, -line_extent),
            (0.0, 0.0, line_extent),
        ]

        shader = gpu.shader.from_builtin(
            'POLYLINE_UNIFORM_COLOR'
        )
        batch = batch_for_shader(
            shader,
            'LINES',
            {"pos": vertices},
        )

        previous_depth_test = gpu.state.depth_test_get()
        previous_depth_mask = gpu.state.depth_mask_get()

        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        gpu.state.depth_mask_set(False)

        with gpu.matrix.push_pop():
            gpu.matrix.multiply_matrix(self.matrix_world)

            shader.bind()
            shader.uniform_float(
                "viewportSize",
                gpu.state.viewport_get()[2:],
            )
            shader.uniform_float(
                "lineWidth",
                scaled_line_width,
            )
            shader.uniform_float("color", color)

            batch.draw(shader)

        gpu.state.depth_mask_set(previous_depth_mask)
        gpu.state.depth_test_set(previous_depth_test)
        gpu.state.blend_set('NONE')

    def draw_select(self, _context, _select_id):
        pass


class CURSORTRANSFORM_GT_rotate_ticks(bpy.types.Gizmo):
    """Snap-angle tick marks for cursor rotation."""

    bl_idname = "CURSORTRANSFORM_GT_rotate_ticks"

    def draw(self, context):
        """Draw snap ticks around the active rotation ring."""
        start_angle = float(
            getattr(self, "start_angle", 0.0)
        )
        tick_offset = float(
            getattr(
                self,
                "tick_offset",
                ROTATE_TICK_OFFSET_LOCAL,
            )
        )
        tick_length = float(
            getattr(
                self,
                "tick_length",
                ROTATE_TICK_LENGTH_LOCAL,
            )
        )
        tick_width = float(
            getattr(
                self,
                "tick_width",
                ROTATE_TICK_WIDTH_PX,
            )
        )
        tick_color = getattr(
            self,
            "tick_color",
            ROTATE_TICK_COLOR,
        )

        scaled_tick_width = (
            tick_width
            * context.preferences.system.pixel_size
        )

        vertices = []
        angle = start_angle
        end_angle = start_angle + math.tau

        while angle < end_angle - 1e-6:
            cosine = math.cos(angle)
            sine = math.sin(angle)

            base_radius = 1.0 + tick_offset
            tip_radius = base_radius + tick_length

            base = (
                cosine * base_radius,
                sine * base_radius,
                0.0,
            )
            tip = (
                cosine * tip_radius,
                sine * tip_radius,
                0.0,
            )

            vertices.extend((base, tip))
            angle += ROTATE_SNAP_STEP

        if not vertices:
            return

        shader = gpu.shader.from_builtin(
            'POLYLINE_UNIFORM_COLOR'
        )
        batch = batch_for_shader(
            shader,
            'LINES',
            {"pos": vertices},
        )

        previous_depth_test = gpu.state.depth_test_get()
        previous_depth_mask = gpu.state.depth_mask_get()

        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        gpu.state.depth_mask_set(False)

        with gpu.matrix.push_pop():
            gpu.matrix.multiply_matrix(self.matrix_world)

            shader.bind()
            shader.uniform_float(
                "viewportSize",
                gpu.state.viewport_get()[2:],
            )
            shader.uniform_float(
                "lineWidth",
                scaled_tick_width,
            )
            shader.uniform_float(
                "color",
                tick_color,
            )

            batch.draw(shader)

        gpu.state.depth_mask_set(previous_depth_mask)
        gpu.state.depth_test_set(previous_depth_test)
        gpu.state.blend_set('NONE')

    def draw_select(self, _context, _select_id):
        pass


class CURSORTRANSFORM_GGT_main(bpy.types.GizmoGroup):
    """Main gizmo group that draws the 3D Cursor translation and rotation controls."""
    bl_idname = "CURSORTRANSFORM_GGT_main"
    bl_label = "3D Cursor Transform Gizmo"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D', 'PERSISTENT', 'SHOW_MODAL_ALL'}

    @classmethod
    def poll(cls, context):
        """Show the group while the active 3D View supports cursor gizmos."""
        if context.area is None or context.area.type != 'VIEW_3D':
            return False

        if context.space_data is None or context.space_data.type != 'VIEW_3D':
            return False

        if not active_tool_is_cursor(context):
            return False

        return (
            viewport_allows_gizmo(context)
            and (
                location_gizmo_enabled(context)
                or rotation_gizmo_enabled(context)
            )
        )

    def setup(self, _context):
        """Create the gizmos and bind their operators."""
        def _new_plane_square(selectable):
            gizmo = self.gizmos.new(
                "CURSORTRANSFORM_GT_plane_square"
            )
            gizmo.use_tooltip = False
            gizmo.use_draw_offset_scale = True
            gizmo.hide_select = not selectable
            return gizmo

        def _new_filled_dot(selectable):
            gizmo = self.gizmos.new(
                "CURSORTRANSFORM_GT_filled_dot"
            )
            gizmo.use_tooltip = False
            gizmo.hide_select = not selectable
            return gizmo

        def _new_rotate_ring(operator_idname):
            gizmo = self.gizmos.new("GIZMO_GT_dial_3d")
            gizmo.use_tooltip = False
            gizmo.line_width = 3
            gizmo.alpha = AXIS_IDLE_ALPHA
            gizmo.alpha_highlight = AXIS_ACTIVE_ALPHA
            gizmo.draw_options = {'CLIP'}
            gizmo.target_set_operator(operator_idname)
            return gizmo

        self.move_arrows = {}

        for axis in ("X", "Y", "Z"):
            gizmo = self.gizmos.new("GIZMO_GT_arrow_3d")
            gizmo.use_tooltip = False
            gizmo.line_width = 2
            gizmo.alpha = AXIS_IDLE_ALPHA
            gizmo.alpha_highlight = AXIS_ACTIVE_ALPHA
            gizmo.length = 1.25
            gizmo.scale_basis = 0.34
            gizmo.use_draw_offset_scale = True

            # Match Blender's native transform-gizmo arrow placement.
            gizmo.matrix_offset = Matrix.Translation(
                (0.0, 0.0, 0.62)
            )

            operator_properties = gizmo.target_set_operator(
                "cursortransform.translate_gizmo_start"
            )
            operator_properties.axis = axis

            self.move_arrows[axis] = gizmo

        self.move_planes = {}

        for plane in ("XY", "XZ", "YZ"):
            gizmo = _new_plane_square(selectable=True)

            operator_properties = gizmo.target_set_operator(
                "cursortransform.translate_plane"
            )
            operator_properties.plane = plane

            self.move_planes[plane] = gizmo

        self.ghost_move_planes = {}

        for plane in ("XY", "XZ", "YZ"):
            self.ghost_move_planes[plane] = (
                _new_plane_square(selectable=False)
            )

        self.ghost_move_arrow = self.gizmos.new(
            "GIZMO_GT_arrow_3d"
        )
        self.ghost_move_arrow.use_tooltip = False
        self.ghost_move_arrow.hide_select = True
        self.ghost_move_arrow.line_width = 2
        self.ghost_move_arrow.use_draw_offset_scale = True

        self.ghost_center_dot = _new_filled_dot(
            selectable=False
        )

        self.ghost_move_center = self.gizmos.new(
            "GIZMO_GT_move_3d"
        )
        self.ghost_move_center.use_tooltip = False
        self.ghost_move_center.hide_select = True
        self.ghost_move_center.line_width = 2
        self.ghost_move_center.draw_options = {
            'FILL_SELECT',
            'ALIGN_VIEW',
        }

        self.axis_center_dots = {}

        for axis in ("X", "Y", "Z"):
            self.axis_center_dots[axis] = (
                _new_filled_dot(selectable=False)
            )

        # The free-rotation disc must be created before the move center so
        # the move center takes precedence in their overlapping hit area.
        self.rotate_free_disc = self.gizmos.new(
            "CURSORTRANSFORM_GT_rotate_free_disc"
        )
        self.rotate_free_disc.use_tooltip = False
        self.rotate_free_disc.target_set_operator(
            "cursortransform.rotate_free_modal"
        )

        self.move_center = self.gizmos.new(
            "GIZMO_GT_move_3d"
        )
        self.move_center.use_tooltip = False
        self.move_center.line_width = 2
        self.move_center.draw_options = {
            'FILL_SELECT',
            'ALIGN_VIEW',
        }
        self.move_center.target_set_operator(
            "cursortransform.translate_free"
        )

        # Blender draws gizmos in reverse registration order. Preserve this
        # order so ticks appear above rings, sectors, and axis lines.
        self.rotate_ticks = self.gizmos.new(
            "CURSORTRANSFORM_GT_rotate_ticks"
        )
        self.rotate_ticks.use_tooltip = False
        self.rotate_ticks.hide_select = True

        rotate_operators = {
            "X": "cursortransform.rotate_x",
            "Y": "cursortransform.rotate_y",
            "Z": "cursortransform.rotate_z",
        }

        self.rotate_rings = {}

        for axis in ("X", "Y", "Z"):
            self.rotate_rings[axis] = _new_rotate_ring(
                rotate_operators[axis]
            )

        self.view_ring = self.gizmos.new(
            "GIZMO_GT_dial_3d"
        )
        self.view_ring.use_tooltip = False
        self.view_ring.line_width = 2
        self.view_ring.alpha = 0.5
        self.view_ring.alpha_highlight = 1.0
        self.view_ring.target_set_operator(
            "cursortransform.rotate_view"
        )

        # Register the sector after the rings so it is drawn beneath them.
        self.rotate_sector = self.gizmos.new(
            "CURSORTRANSFORM_GT_rotate_sector"
        )
        self.rotate_sector.use_tooltip = False
        self.rotate_sector.hide_select = True

        # Register axis lines last so they are drawn at the bottom.
        self.axis_lines = {}

        for axis in ("X", "Y", "Z"):
            gizmo = self.gizmos.new(
                "CURSORTRANSFORM_GT_axis_line"
            )
            gizmo.use_tooltip = False
            gizmo.hide_select = True

            self.axis_lines[axis] = gizmo

    def _apply_filled_dot(
        self,
        gizmo,
        matrix_basis,
        scale_basis,
        color,
        alpha,
    ):
        gizmo.matrix_basis = matrix_basis
        gizmo.scale_basis = scale_basis
        gizmo.color = color
        gizmo.color_highlight = color
        gizmo.alpha = alpha
        gizmo.alpha_highlight = alpha

    def _apply_move_center(
        self,
        gizmo,
        matrix_basis,
        scale_basis,
        color,
        alpha,
        alpha_highlight,
    ):
        gizmo.matrix_basis = matrix_basis
        gizmo.scale_basis = scale_basis
        gizmo.color = color
        gizmo.color_highlight = color
        gizmo.alpha = alpha
        gizmo.alpha_highlight = alpha_highlight

    def _apply_plane_square(
        self,
        gizmo,
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
        gizmo.matrix_basis = matrix_basis
        gizmo.matrix_offset = matrix_offset
        gizmo.scale_basis = scale_basis
        gizmo.fill_color = fill_color
        gizmo.outline_color = outline_color
        gizmo.color = fill_color
        gizmo.color_highlight = fill_color
        gizmo.fill_alpha = fill_alpha
        gizmo.outline_alpha = outline_alpha
        gizmo.fill_alpha_highlight = fill_alpha_highlight
        gizmo.outline_alpha_highlight = outline_alpha_highlight
        gizmo.alpha = fill_alpha
        gizmo.alpha_highlight = fill_alpha_highlight

    def _apply_arrow(
        self,
        gizmo,
        matrix_basis,
        scale_basis,
        length,
        matrix_offset,
        color,
        alpha,
        alpha_highlight,
    ):
        gizmo.matrix_basis = matrix_basis
        gizmo.scale_basis = scale_basis
        gizmo.length = length
        gizmo.matrix_offset = matrix_offset
        gizmo.color = color
        gizmo.color_highlight = color
        gizmo.alpha = alpha
        gizmo.alpha_highlight = alpha_highlight

    def _apply_rotate_disc(
        self,
        gizmo,
        matrix_basis,
        scale_basis,
        color,
        alpha,
        alpha_highlight,
    ):
        gizmo.matrix_basis = matrix_basis
        gizmo.scale_basis = scale_basis
        gizmo.color = color
        gizmo.color_highlight = color
        gizmo.alpha = alpha
        gizmo.alpha_highlight = alpha_highlight

    def _apply_rotate_ring(
        self,
        gizmo,
        matrix_basis,
        scale_basis,
        color,
        alpha,
        alpha_highlight,
        draw_options,
    ):
        gizmo.matrix_basis = matrix_basis
        gizmo.scale_basis = scale_basis
        gizmo.color = color
        gizmo.color_highlight = color
        gizmo.alpha = alpha
        gizmo.alpha_highlight = alpha_highlight
        gizmo.draw_options = draw_options

    def draw_prepare(self, context):
        """Prepare gizmo visibility, transforms, colors, and ghost states."""
        global _TRANSLATE_GHOST_START_LOC
        global _TRANSLATE_GHOST_START_ORIENT
        global _ROTATE_ACTIVE_ORIENT
        global _ROTATE_ACTIVE_VIEW
        global _ROTATE_GUIDE_START_ANGLE
        global _ROTATE_GUIDE_TOTAL_ANGLE

        cursor_location = context.scene.cursor.location

        orientation = build_orient_matrix(context)
        view_matrix = get_view_rot_matrix(context)
        location_matrix = Matrix.Translation(cursor_location)

        gizmo_colors = get_theme_gizmo_colors(context)
        axis_colors = {
            "X": gizmo_colors["X"],
            "Y": gizmo_colors["Y"],
            "Z": gizmo_colors["Z"],
        }
        center_color = gizmo_colors["VIEW"]

        show_location = location_gizmo_enabled(context)
        show_rotation = rotation_gizmo_enabled(context)

        window_manager = context.window_manager
        translate_running = translate_modal_running(context)

        active_translate_axis = (
            window_manager.cursortransform_active_translate_axis
        )
        active_rotate_axis = (
            window_manager.cursortransform_active_rotate_axis
        )

        rotate_running = active_rotate_axis in {
            "X",
            "Y",
            "Z",
            "VIEW",
            "FREE",
        }
        free_rotate_running = active_rotate_axis == "FREE"

        # Hide custom gizmos while Blender handles rotation after an R-swap.
        native_cursor_rotate_running = (
            active_tool_is_cursor(context)
            and native_rotate_modal_running(context)
        )

        if native_cursor_rotate_running:
            for gizmo in self.gizmos:
                gizmo.hide = True

            return

        if not translate_running and active_translate_axis:
            window_manager.cursortransform_active_translate_axis = ""
            active_translate_axis = ""

        if not rotate_running and active_rotate_axis:
            window_manager.cursortransform_active_rotate_axis = ""
            active_rotate_axis = ""

        if not translate_running:
            _TRANSLATE_GHOST_START_LOC = None
            _TRANSLATE_GHOST_START_ORIENT = None

        rotate_basis = orientation
        rotate_view_basis = view_matrix

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

        active_axis_move = (
            translate_running
            and active_translate_axis in {"X", "Y", "Z"}
        )
        active_plane_move = (
            translate_running
            and active_translate_axis in {"XY", "XZ", "YZ"}
        )

        # Translation arrows
        for axis, gizmo in self.move_arrows.items():
            gizmo.hide = (not show_location) or rotate_running

            if gizmo.hide:
                continue

            is_active_axis = (
                translate_running
                and active_translate_axis == axis
            )

            if not show_rotation:
                arrow_length = 1.1
                arrow_offset = Matrix.Translation(
                    (0.0, 0.0, 0.22)
                )
            elif translate_running:
                if is_active_axis:
                    arrow_length = 1.35
                    arrow_offset = Matrix.Translation(
                        (0.0, 0.0, 0.06)
                    )
                else:
                    arrow_length = 1.1
                    arrow_offset = Matrix.Translation(
                        (0.0, 0.0, 0.22)
                    )
            else:
                # Show only arrowheads while location and rotation are idle.
                arrow_length = 0.0
                arrow_offset = Matrix.Translation(
                    (0.0, 0.0, 1.35)
                )

            axis_vector = (
                orientation
                .col[AXIS_INDEX[axis]]
                .to_3d()
            )

            if is_active_axis:
                axis_alpha = AXIS_ACTIVE_ALPHA
            else:
                axis_alpha = (
                    AXIS_IDLE_ALPHA
                    * axis_view_alpha(
                        context,
                        axis_vector,
                    )
                )

            self._apply_arrow(
                gizmo,
                location_matrix
                @ orientation
                @ AXIS_ROT[axis],
                1.05,
                arrow_length,
                arrow_offset,
                axis_colors[axis],
                axis_alpha,
                AXIS_ACTIVE_ALPHA,
            )

        # Translation plane handles
        show_move_planes = (
            show_location
            and not show_rotation
        )

        for plane, gizmo in self.move_planes.items():
            is_active_plane = (
                active_plane_move
                and active_translate_axis == plane
            )

            gizmo.hide = (
                not show_move_planes
                or rotate_running
                or (
                    translate_running
                    and not is_active_plane
                )
            )

            if gizmo.hide:
                continue

            normal_axis = PLANE_NORMAL_AXIS[plane]
            plane_color = axis_colors[normal_axis]
            plane_normal = (
                orientation
                .col[AXIS_INDEX[normal_axis]]
                .to_3d()
            )

            plane_fade = plane_view_alpha(
                context,
                plane_normal,
            )

            fill_alpha = (
                PLANE_FILL_ALPHA
                * plane_fade
            )
            outline_alpha = (
                PLANE_OUTLINE_ALPHA
                * plane_fade
            )
            hover_fill_alpha = (
                PLANE_FILL_HOVER_ALPHA
                * plane_fade
            )
            hover_outline_alpha = (
                PLANE_OUTLINE_HOVER_ALPHA
                * plane_fade
            )

            self._apply_plane_square(
                gizmo,
                location_matrix @ orientation,
                (
                    Matrix.Translation(
                        PLANE_OFFSET[plane]
                    )
                    @ PLANE_ROT[plane]
                ),
                PLANE_SCALE_BASIS,
                plane_color,
                plane_color,
                (
                    hover_fill_alpha
                    if is_active_plane
                    else fill_alpha
                ),
                (
                    hover_outline_alpha
                    if is_active_plane
                    else outline_alpha
                ),
                hover_fill_alpha,
                hover_outline_alpha,
            )

        # Free-move center handle
        self.move_center.hide = (
            not show_location
            or active_axis_move
            or active_plane_move
            or rotate_running
        )

        if not self.move_center.hide:
            self._apply_move_center(
                self.move_center,
                location_matrix @ view_matrix,
                0.20,
                center_color,
                0.5,
                1.0,
            )

        # Active translation center markers
        for axis, gizmo in self.axis_center_dots.items():
            is_active_axis = (
                show_location
                and translate_running
                and active_translate_axis == axis
            )

            is_active_plane = (
                show_location
                and active_plane_move
                and (
                    PLANE_NORMAL_AXIS.get(
                        active_translate_axis
                    )
                    == axis
                )
            )

            gizmo.hide = not (
                is_active_axis
                or is_active_plane
            )

            if gizmo.hide:
                continue

            self._apply_filled_dot(
                gizmo,
                location_matrix @ view_matrix,
                1.35,
                axis_colors[axis],
                AXIS_ACTIVE_ALPHA,
            )

        # Translation ghosts
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
        self.ghost_center_dot.hide = not (
            show_ghost_axis
            or show_ghost_plane
        )

        for plane, gizmo in self.ghost_move_planes.items():
            gizmo.hide = not (
                show_ghost_plane
                and active_translate_axis == plane
            )

        ghost_color = (0.50, 0.50, 0.50)

        if show_ghost_plane:
            ghost_location_matrix = Matrix.Translation(
                _TRANSLATE_GHOST_START_LOC
            )
            ghost_orientation = (
                _TRANSLATE_GHOST_START_ORIENT
            )
            ghost_plane = active_translate_axis
            ghost_gizmo = self.ghost_move_planes[
                ghost_plane
            ]

            self._apply_filled_dot(
                self.ghost_center_dot,
                ghost_location_matrix @ view_matrix,
                1.35,
                ghost_color,
                GHOST_AXIS_ALPHA,
            )

            self._apply_plane_square(
                ghost_gizmo,
                (
                    ghost_location_matrix
                    @ ghost_orientation
                ),
                (
                    Matrix.Translation(
                        PLANE_OFFSET[ghost_plane]
                    )
                    @ PLANE_ROT[ghost_plane]
                ),
                PLANE_SCALE_BASIS,
                ghost_color,
                ghost_color,
                GHOST_PLANE_FILL_ALPHA,
                GHOST_PLANE_OUTLINE_ALPHA,
                GHOST_PLANE_FILL_ALPHA,
                GHOST_PLANE_OUTLINE_ALPHA,
            )

        if show_ghost_axis:
            ghost_location_matrix = Matrix.Translation(
                _TRANSLATE_GHOST_START_LOC
            )
            ghost_orientation = (
                _TRANSLATE_GHOST_START_ORIENT
            )

            self._apply_arrow(
                self.ghost_move_arrow,
                (
                    ghost_location_matrix
                    @ ghost_orientation
                    @ AXIS_ROT[active_translate_axis]
                ),
                1.05,
                1.35,
                Matrix.Translation(
                    (0.0, 0.0, 0.06)
                ),
                ghost_color,
                GHOST_AXIS_ALPHA,
                GHOST_AXIS_ALPHA,
            )

            self._apply_filled_dot(
                self.ghost_center_dot,
                ghost_location_matrix @ view_matrix,
                1.35,
                ghost_color,
                GHOST_AXIS_ALPHA,
            )

        show_ghost_move_center = (
            translate_running
            and active_translate_axis == ""
            and _TRANSLATE_GHOST_START_LOC is not None
        )

        self.ghost_move_center.hide = not (
            show_ghost_move_center
        )

        if show_ghost_move_center:
            ghost_location_matrix = Matrix.Translation(
                _TRANSLATE_GHOST_START_LOC
            )

            self._apply_move_center(
                self.ghost_move_center,
                ghost_location_matrix @ view_matrix,
                0.20,
                ghost_color,
                GHOST_AXIS_ALPHA,
                GHOST_AXIS_ALPHA,
            )

        # Free-rotation hover disc
        show_rotate_free_disc = (
            show_rotation
            and not hide_rotation_while_moving
            and not rotate_running
        )

        self.rotate_free_disc.hide = not (
            show_rotate_free_disc
        )

        if show_rotate_free_disc:
            disc_scale = (
                1.20
                * FREE_ROTATE_DISC_SCALE_FACTOR
            )

            self._apply_rotate_disc(
                self.rotate_free_disc,
                location_matrix @ rotate_view_basis,
                disc_scale,
                (1.0, 1.0, 1.0),
                0.0,
                FREE_ROTATE_DISC_HOVER_ALPHA,
            )

        # Active rotation sector
        show_rotate_sector = (
            rotate_running
            and not free_rotate_running
        )

        self.rotate_sector.hide = not (
            show_rotate_sector
        )

        if show_rotate_sector:
            if active_rotate_axis == "VIEW":
                sector_basis = (
                    location_matrix
                    @ rotate_view_basis
                )
                sector_scale = (
                    1.20
                    * ROTATE_VIEW_SECTOR_SCALE_FACTOR
                )
                sector_color = center_color
                start_width = (
                    ROTATE_VIEW_SECTOR_START_RADIUS_WIDTH
                )
                end_width = (
                    ROTATE_VIEW_SECTOR_END_RADIUS_WIDTH
                )
            else:
                sector_basis = (
                    location_matrix
                    @ rotate_basis
                    @ AXIS_ROT[active_rotate_axis]
                )
                sector_scale = (
                    1.02
                    * ROTATE_SECTOR_SCALE_FACTOR
                )
                sector_color = axis_colors[
                    active_rotate_axis
                ]
                start_width = (
                    ROTATE_SECTOR_START_RADIUS_WIDTH
                )
                end_width = (
                    ROTATE_SECTOR_END_RADIUS_WIDTH
                )

            self.rotate_sector.matrix_basis = sector_basis
            self.rotate_sector.scale_basis = sector_scale
            self.rotate_sector.start_angle = (
                _ROTATE_GUIDE_START_ANGLE
            )
            self.rotate_sector.total_angle = (
                _ROTATE_GUIDE_TOTAL_ANGLE
            )
            self.rotate_sector.radius_color = sector_color
            self.rotate_sector.fill_alpha = (
                ROTATE_SECTOR_FILL_COLOR[3]
            )
            self.rotate_sector.start_width = start_width
            self.rotate_sector.end_width = end_width

        # Rotation constraint axis lines
        for axis, gizmo in self.axis_lines.items():
            show_axis_line = (
                rotate_running
                and (
                    _ROTATE_MMB_HELD
                    or active_rotate_axis == axis
                )
            )

            gizmo.hide = not show_axis_line

            if gizmo.hide:
                continue

            if (
                _ROTATE_MMB_HELD
                and axis != active_rotate_axis
            ):
                alpha = (
                    ROTATE_MMB_AXIS_LINE_DIM_ALPHA
                )
            else:
                alpha = 1.0

            highlighted_color = axis_highlight_color(
                axis_colors[axis]
            )

            gizmo.matrix_basis = (
                location_matrix
                @ rotate_basis
                @ AXIS_ROT[axis]
            )
            gizmo.scale_basis = 1.0
            gizmo.line_width = (
                ROTATE_CONSTRAINT_LINE_WIDTH
            )
            gizmo.axis_color = (
                highlighted_color[0],
                highlighted_color[1],
                highlighted_color[2],
                alpha,
            )

        # Rotation snap ticks
        show_rotate_ticks = (
            show_rotate_sector
            and _ROTATE_GUIDE_CTRL_PRESSED
        )

        self.rotate_ticks.hide = not show_rotate_ticks

        if show_rotate_ticks:
            if active_rotate_axis == "VIEW":
                ticks_basis = (
                    location_matrix
                    @ rotate_view_basis
                )
                ticks_scale = 1.20
                tick_offset = (
                    ROTATE_VIEW_TICK_OFFSET_LOCAL
                )
                tick_length = (
                    ROTATE_VIEW_TICK_LENGTH_LOCAL
                )
                tick_width = (
                    ROTATE_VIEW_TICK_WIDTH_PX
                )
            else:
                ticks_basis = (
                    location_matrix
                    @ rotate_basis
                    @ AXIS_ROT[active_rotate_axis]
                )
                ticks_scale = 1.0
                tick_offset = ROTATE_TICK_OFFSET_LOCAL
                tick_length = ROTATE_TICK_LENGTH_LOCAL
                tick_width = ROTATE_TICK_WIDTH_PX

            self.rotate_ticks.matrix_basis = ticks_basis
            self.rotate_ticks.scale_basis = ticks_scale
            self.rotate_ticks.start_angle = (
                _ROTATE_GUIDE_START_ANGLE
            )
            self.rotate_ticks.tick_offset = tick_offset
            self.rotate_ticks.tick_length = tick_length
            self.rotate_ticks.tick_width = tick_width
            self.rotate_ticks.tick_color = (
                ROTATE_TICK_COLOR
            )

        # Axis rotation rings
        for axis, gizmo in self.rotate_rings.items():
            is_active_axis = (
                rotate_running
                and active_rotate_axis == axis
            )

            draw_options = (
                set()
                if is_active_axis
                else {'CLIP'}
            )

            gizmo.hide = (
                (
                    not show_rotation
                    and not is_active_axis
                )
                or hide_rotation_while_moving
                or (
                    rotate_running
                    and not is_active_axis
                )
            )

            if gizmo.hide:
                continue

            ring_basis = (
                rotate_basis
                if is_active_axis
                else orientation
            )

            self._apply_rotate_ring(
                gizmo,
                (
                    location_matrix
                    @ ring_basis
                    @ AXIS_ROT[axis]
                ),
                1.0,
                axis_colors[axis],
                (
                    AXIS_ACTIVE_ALPHA
                    if is_active_axis
                    else AXIS_IDLE_ALPHA
                ),
                AXIS_ACTIVE_ALPHA,
                draw_options,
            )

        # View rotation ring
        self.view_ring.hide = (
            (
                not show_rotation
                and active_rotate_axis != "VIEW"
            )
            or hide_rotation_while_moving
            or (
                rotate_running
                and active_rotate_axis != "VIEW"
            )
        )

        if not self.view_ring.hide:
            self._apply_rotate_ring(
                self.view_ring,
                (
                    location_matrix
                    @ rotate_view_basis
                ),
                1.20,
                center_color,
                (
                    AXIS_ACTIVE_ALPHA
                    if active_rotate_axis == "VIEW"
                    else 0.5
                ),
                AXIS_ACTIVE_ALPHA,
                self.view_ring.draw_options,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Keymaps and Registration
# ─────────────────────────────────────────────────────────────────────────────

classes = (
    CURSORTRANSFORM_AddonPreferences,
    CURSORTRANSFORM_OT_rotate_modal,
    CURSORTRANSFORM_OT_rotate_free_modal,
    CURSORTRANSFORM_OT_clear_transform,
    CURSORTRANSFORM_OT_translate_modal,
    CURSORTRANSFORM_OT_translate,
    CURSORTRANSFORM_OT_translate_gizmo_start,
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


_addon_keymaps = []


def _register_keymaps():
    """Register shortcuts for the 3D Cursor tool."""
    window_manager = bpy.context.window_manager
    keyconfig = window_manager.keyconfigs.addon

    if keyconfig is None:
        return

    keymap = keyconfig.keymaps.new(
        name="3D View Tool: Cursor",
        space_type='VIEW_3D',
    )

    keymap_item = keymap.keymap_items.new(
        idname="cursortransform.translate_modal",
        type='G',
        value='PRESS',
    )
    keymap_item.properties.release_confirm = False
    _addon_keymaps.append((keymap, keymap_item))

    keymap_item = keymap.keymap_items.new(
        idname="cursortransform.rotate_view",
        type='R',
        value='PRESS',
    )
    _addon_keymaps.append((keymap, keymap_item))

    keymap_item = keymap.keymap_items.new(
        idname="cursortransform.clear_transform",
        type='G',
        value='PRESS',
        alt=True,
    )
    keymap_item.properties.mode = 'LOCATION'
    _addon_keymaps.append((keymap, keymap_item))

    keymap_item = keymap.keymap_items.new(
        idname="cursortransform.clear_transform",
        type='R',
        value='PRESS',
        alt=True,
    )
    keymap_item.properties.mode = 'ROTATION'
    _addon_keymaps.append((keymap, keymap_item))
    

def _unregister_keymaps():
    """Remove the add-on's registered shortcuts."""
    for keymap, keymap_item in _addon_keymaps:
        try:
            keymap.keymap_items.remove(keymap_item)
        except ReferenceError:
            pass

    _addon_keymaps.clear()


def register():
    """Register the add-on."""
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

    if (
        cursor_align_rotation_handler
        not in bpy.app.handlers.depsgraph_update_post
    ):
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
    """Unregister the add-on."""
    global _CURSOR_ALIGN_IS_RUNNING

    _unregister_keymaps()

    if bpy.app.timers.is_registered(
        initialize_cursor_align_cache_after_register
    ):
        bpy.app.timers.unregister(
            initialize_cursor_align_cache_after_register
        )

    if (
        cursor_align_rotation_handler
        in bpy.app.handlers.depsgraph_update_post
    ):
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