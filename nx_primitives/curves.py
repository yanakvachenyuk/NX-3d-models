from __future__ import annotations

import math

import NXOpen
import NXOpen.Features
import NXOpen.GeometricUtilities

from .base import Profile


def _create_line_feature(
    workPart,
    start,
    end
):
    """
    Создает Feature линии.
    """

    start = (float(start[0]), float(start[1]), float(start[2]))
    end = (float(end[0]), float(end[1]), float(end[2]))

    length = math.sqrt(
        (end[0] - start[0]) ** 2 +
        (end[1] - start[1]) ** 2 +
        (end[2] - start[2]) ** 2
    )

    builder = workPart.BaseFeatures.CreateAssociativeLineBuilder(

        NXOpen.Features.AssociativeLine.Null

    )

    builder.StartPointOptions = (

        NXOpen.Features.AssociativeLineBuilder.StartOption.Point

    )

    builder.StartPointReference = (

        NXOpen.Features.AssociativeLineBuilder.StartReference.Absolute

    )

    builder.EndPointOptions = (

        NXOpen.Features.AssociativeLineBuilder.EndOption.Point

    )

    builder.EndPointReference = (

        NXOpen.Features.AssociativeLineBuilder.EndReference.Absolute

    )

    builder.StartAngle.SetFormula("0")

    builder.EndAngle.SetFormula("270")

    builder.Limits.StartLimit.Distance.SetFormula("0")

    builder.Limits.EndLimit.Distance.SetFormula(str(length))

    start_point = workPart.Points.CreatePoint(

        NXOpen.Point3d(*start)

    )

    end_point = workPart.Points.CreatePoint(

        NXOpen.Point3d(*end)

    )

    builder.StartPoint.Value = start_point

    builder.EndPoint.Value = end_point

    feature = builder.Commit()

    builder.Destroy()

    return feature


class Line(Profile):

    """
    Отрезок.
    """

    def __init__(
        self,
        workPart,
        start,
        end
    ):

        self.start = start
        self.end = end

        feature = _create_line_feature(

            workPart,
            start,
            end

        )

        curve = feature.FindObject("CURVE 1")

        self.feature = feature

        super().__init__([curve])

    @classmethod
    def on_frame(cls, workPart, frame, start_uv, end_uv):
        """
        Отрезок в плоскости frame, заданный ЛОКАЛЬНЫМИ (u, v)
        координатами начала и конца (та же схема, что и у
        Polygon.on_frame): start_uv = (u, v), end_uv = (u, v).

        ПРЕЖНЯЯ сигнатура on_frame(workPart, radius, frame, u=0.0, v=0.0)
        была скопирована с Circle.on_frame и не соответствовала
        __init__ этого класса (Line не принимает radius/center/normal) —
        любой вызов падал с TypeError. Эта версия приведена к реальной
        сигнатуре Line.__init__(workPart, start, end).
        """
        start, end = frame.points([start_uv, end_uv])
        return cls(workPart, start, end)


def _plane_basis(normal):
    """Возвращает два единичных вектора, образующих базис плоскости с данной нормалью."""
    nx, ny, nz = normal

    arbitrary = (1.0, 0.0, 0.0) if abs(nx) < 0.9 else (0.0, 1.0, 0.0)

    ux = ny * arbitrary[2] - nz * arbitrary[1]
    uy = nz * arbitrary[0] - nx * arbitrary[2]
    uz = nx * arbitrary[1] - ny * arbitrary[0]
    umag = math.sqrt(ux**2 + uy**2 + uz**2)
    u = (ux / umag, uy / umag, uz / umag)

    vx = ny * u[2] - nz * u[1]
    vy = nz * u[0] - nx * u[2]
    vz = nx * u[1] - ny * u[0]
    v = (vx, vy, vz)

    return u, v


def _create_circle_feature(workPart, radius, center, normal=(0.0, 0.0, 1.0)):
    """
    Создает Feature окружности в плоскости, заданной center (3D точка) и normal.
    """

    radius = float(radius)
    center = (float(center[0]), float(center[1]), float(center[2]))
    normal = (float(normal[0]), float(normal[1]), float(normal[2]))

    builder = workPart.BaseFeatures.CreateAssociativeArcBuilder(
        NXOpen.Features.AssociativeArc.Null
    )

    builder.Type = NXOpen.Features.AssociativeArcBuilder.Types.ArcFromCenter

    plane_origin = NXOpen.Point3d(center[0], center[1], center[2])
    plane_normal = NXOpen.Vector3d(normal[0], normal[1], normal[2])

    plane = workPart.Planes.CreatePlane(
        plane_origin,
        plane_normal,
        NXOpen.SmartObject.UpdateOption.WithinModeling
    )

    builder.SupportPlaneData.SupportPlane = plane

    builder.EndPointOptions = NXOpen.Features.AssociativeArcBuilder.EndOption.Radius

    builder.Radius.SetFormula(str(radius))

    builder.Limits.FullCircle = True

    center_point = workPart.Points.CreatePoint(
        NXOpen.Point3d(center[0], center[1], center[2])
    )

    builder.CenterPoint.Value = center_point

    builder.CenterPointReference = (
        NXOpen.Features.AssociativeArcBuilder.CenterReference.Absolute
    )

    u, v = _plane_basis(normal)

    start = (
        center[0] + radius * u[0],
        center[1] + radius * u[1],
        center[2] + radius * u[2]
    )

    start_point = workPart.Points.CreatePoint(NXOpen.Point3d(*start))

    builder.StartPoint.Value = start_point

    builder.ZonePoint = NXOpen.Point3d(
        center[0] + radius * 0.9 * u[0] + radius * 0.4 * v[0],
        center[1] + radius * 0.9 * u[1] + radius * 0.4 * v[1],
        center[2] + radius * 0.9 * u[2] + radius * 0.4 * v[2]
    )

    feature = builder.Commit()

    builder.Destroy()

    plane.DestroyPlane()

    return feature


class Circle(Profile):
    """
    Окружность.

    center может быть 2D (x, y) — тогда окружность строится
    в плоскости XY на z=0 (поведение по умолчанию, как раньше),
    либо 3D (x, y, z) вместе с normal — тогда окружность строится
    в произвольной плоскости (например, вертикальной).
    """

    def __init__(self, workPart, radius, center=(0.0, 0.0), normal=(0.0, 0.0, 1.0)):

        self.radius = radius

        if len(center) == 2:
            center3d = (center[0], center[1], 0.0)
        else:
            center3d = tuple(center)

        self.center = center3d
        self.normal = normal

        feature = _create_circle_feature(workPart, radius, center3d, normal)

        curve = feature.FindObject("CURVE 1")

        self.feature = feature

        super().__init__([curve])

    @classmethod
    def on_frame(cls, workPart, radius, frame, u=0.0, v=0.0):
        return cls(workPart, radius, center=frame.point(u, v), normal=frame.normal)