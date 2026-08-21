# from .base import Profile, ClosedProfile
# from .curves import Line, Circle
# from .shapes import (
#     Triangle,
#     Parallelogram,
#     Polygon
# )
# from .solid import (
#     Extrude,
#     Fillet,
#     Union,
#     Subtract,
#     Intersect,
#     Boolean,
#     rect_profile,
#     edges_near,
#     edges_in_box,
#     attachment_seam,
#     edges_after_boolean,
#     center_hole,
#     holes_in_row
# )
# from .geometry import Frame
# from .display import Hide

# __all__ = [
#     'Profile',
#     'ClosedProfile',
#     'Polygon',
#     'Line',
#     'Circle',
#     'Triangle',
#     'Parallelogram',
#     'Extrude',
#     'Fillet',
#     'Hide',
#     'Union',
#     'Subtract',
#     'Intersect',
#     'Boolean',
#     'Frame',
#     'rect_profile',
#     'edges_near',
#     'edges_in_box',
#     'attachment_seam',
#     'edges_after_boolean',
#     'center_hole',
#     'holes_in_row'
# ]


from .base import Profile, ClosedProfile
from .curves import Line, Circle
from .shapes import (
    Triangle,
    Parallelogram,
    Polygon,
)
from .extrude_core import Extrude, rect_profile
from .fillet import Fillet
from .boolean_ops import Union, Subtract, Intersect, Boolean
from .edges_helpers import (
    edges_near,
    edges_in_box,
    attachment_seam,
    edges_after_boolean,
)
from .holes import center_hole, holes_in_row
from .geometry import Frame
from .display import Hide

__all__ = [
    "Profile",
    "ClosedProfile",
    "Polygon",
    "Line",
    "Circle",
    "Triangle",
    "Parallelogram",
    "Extrude",
    "Fillet",
    "Hide",
    "Union",
    "Subtract",
    "Intersect",
    "Boolean",
    "Frame",
    "rect_profile",
    "edges_near",
    "edges_in_box",
    "attachment_seam",
    "edges_after_boolean",
    "center_hole",
    "holes_in_row",
]